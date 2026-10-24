"""Maintenance windows (roadmap M1, 24.10.2026).

An administrator puts a connection or an app tile into maintenance until a
time. Until then nothing about it is told except rejected credentials, no
outage is opened, and the availability bars draw the stretch grey.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import db_session
from app.models import HealthCheck, HistorySample, Maintenance, Notice, Outage, utcnow
from app.services import health as health_service
from app.services import maintenance, notify, retention
from app.services.collector import collector

from .conftest import CSRF, create_user, login, setup_admin


def _board(client: TestClient) -> dict:
    return client.post("/api/v1/boards", json={"name": "Lab"}, headers=CSRF).json()


def _connection(client: TestClient, name: str = "Movies") -> dict:
    response = client.post("/api/v1/integrations", json={"kind": "radarr", "name": name, "config": {"url": "http://radarr:7878", "api_key": "k"}}, headers=CSRF)
    assert response.status_code in (200, 201), response.text
    return response.json()


def _tile(client: TestClient, page_id: int, title: str = "Paperless") -> dict:
    response = client.post(f"/api/v1/pages/{page_id}/widgets", json={"kind": "core.app", "title": title, "link": "http://paperless.invalid", "options": {"check": True}}, headers=CSRF)
    assert response.status_code == 201, response.text
    widget = response.json()["widget"]
    collector.unschedule(widget["id"])
    return widget


def _check_of(widget_id: int) -> int:
    with db_session() as db:
        return db.scalar(select(HealthCheck.id).where(HealthCheck.widget_id == widget_id))


# -- the API ------------------------------------------------------------------


def test_an_admin_starts_moves_and_ends_maintenance(client: TestClient) -> None:
    setup_admin(client)
    movies = _connection(client)

    started = client.post("/api/v1/maintenance", json={"integration_id": movies["id"], "minutes": 120}, headers=CSRF)
    assert started.status_code == 201, started.text
    first = started.json()
    assert first["active"] and first["name"] == "Movies"
    ends = datetime.fromisoformat(first["ends_at"])
    assert timedelta(minutes=119) < ends - datetime.now(UTC) <= timedelta(minutes=120)

    # Again for the same connection: the end moves, no second stretch.
    later = (datetime.now(UTC) + timedelta(hours=5)).isoformat()
    moved = client.post("/api/v1/maintenance", json={"integration_id": movies["id"], "ends_at": later}, headers=CSRF).json()
    assert moved["id"] == first["id"]
    assert len(client.get("/api/v1/maintenance").json()) == 1

    ended = client.delete(f"/api/v1/maintenance/{first['id']}", headers=CSRF)
    assert ended.status_code == 200 and ended.json()["active"] is False
    with db_session() as db:
        assert maintenance.covering(db, integration_id=movies["id"]) is None


@pytest.mark.parametrize(("body", "code"), [
    ({"minutes": 60}, "bad_target"),
    ({"integration_id": 1, "widget_id": 1, "minutes": 60}, "bad_target"),
    ({"integration_id": 1}, "missing_end"),
    ({"integration_id": 1, "ends_at": "2020-01-01T00:00:00+00:00"}, "ends_in_the_past"),
    ({"integration_id": 1, "ends_at": "2999-01-01T00:00:00+00:00"}, "too_long"),
    ({"integration_id": 999, "minutes": 60}, "not_found"),
])
def test_what_is_refused(client: TestClient, body: dict, code: str) -> None:
    setup_admin(client)
    _connection(client)
    response = client.post("/api/v1/maintenance", json=body, headers=CSRF)
    assert response.status_code in (400, 404), response.text
    assert response.json()["detail"]["code"] == code


def test_only_an_app_tile_has_a_maintenance_of_its_own(client: TestClient) -> None:
    setup_admin(client)
    page = _board(client)["pages"][0]["id"]
    clock = client.post(f"/api/v1/pages/{page}/widgets", json={"kind": "core.clock"}, headers=CSRF).json()["widget"]
    tile = _tile(client, page)

    refused = client.post("/api/v1/maintenance", json={"widget_id": clock["id"], "minutes": 30}, headers=CSRF)
    assert refused.status_code == 400 and refused.json()["detail"]["code"] == "not_an_app"
    assert client.post("/api/v1/maintenance", json={"widget_id": tile["id"], "minutes": 30}, headers=CSRF).status_code == 201


def test_members_may_not_set_maintenance(client: TestClient) -> None:
    setup_admin(client)
    movies = _connection(client)
    create_user(client, "mia", role="user")
    login(client, "mia", "another-long-password")

    assert client.post("/api/v1/maintenance", json={"integration_id": movies["id"], "minutes": 30}, headers=CSRF).status_code == 403
    assert client.get("/api/v1/maintenance").status_code == 403


def test_a_card_says_until_when_its_connection_is_in_maintenance(client: TestClient) -> None:
    setup_admin(client)
    board = _board(client)
    movies = _connection(client)
    queue = client.post(f"/api/v1/pages/{board['pages'][0]['id']}/widgets", json={"kind": "radarr.queue", "integration_id": movies["id"]}, headers=CSRF).json()["widget"]
    assert queue["maintenance"] is None

    client.post("/api/v1/maintenance", json={"integration_id": movies["id"], "minutes": 60}, headers=CSRF)

    [shown] = [w for w in client.get(f"/api/v1/boards/{board['slug']}").json()["pages"][0]["widgets"] if w["id"] == queue["id"]]
    assert shown["maintenance"] is not None


# -- what is told -------------------------------------------------------------


def test_news_about_a_connection_in_maintenance_is_held_back_but_rejected_credentials_are_not(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(notify, "spawn", lambda job, name="": None)
    setup_admin(client)
    movies = _connection(client)
    client.post("/api/v1/maintenance", json={"integration_id": movies["id"], "minutes": 60}, headers=CSRF)

    notify.emit("widget_broken", "Radarr stopped working", integration_id=movies["id"])
    notify.emit("auth_rejected", "Radarr: the service rejected its credentials", integration_id=movies["id"])

    with db_session() as db:
        titles = list(db.scalars(select(Notice.title)))
    assert titles == ["Radarr: the service rejected its credentials"]


def test_a_check_in_maintenance_opens_no_outage_and_records_no_sample(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    told: list[str] = []
    monkeypatch.setattr(notify, "emit", lambda event, title, body="", **kw: told.append(event))
    setup_admin(client)
    tile = _tile(client, _board(client)["pages"][0]["id"])
    check_id = _check_of(tile["id"])
    client.post("/api/v1/maintenance", json={"widget_id": tile["id"], "minutes": 60}, headers=CSRF)
    service = health_service.HealthService()

    service._record(check_id, ok=False, latency=0, detail="ConnectError")
    with db_session() as db:
        db.get(HealthCheck, check_id).down_since = utcnow() - timedelta(minutes=30)
    service._record(check_id, ok=False, latency=0, detail="ConnectError")

    with db_session() as db:
        assert db.scalar(select(Outage)) is None
        assert db.scalar(select(HistorySample).where(HistorySample.key.like(f"{tile['id']}:%"))) is None
        assert db.get(HealthCheck, check_id).last_ok is False, "the tile still shows what it finds"
    assert told == []


def test_down_through_maintenance_counts_from_its_end(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    told: list[str] = []
    monkeypatch.setattr(notify, "emit", lambda event, title, body="", **kw: told.append(event))
    setup_admin(client)
    tile = _tile(client, _board(client)["pages"][0]["id"])
    check_id = _check_of(tile["id"])
    started = client.post("/api/v1/maintenance", json={"widget_id": tile["id"], "minutes": 60}, headers=CSRF).json()
    service = health_service.HealthService()
    service._record(check_id, ok=False, latency=0, detail="ConnectError")
    with db_session() as db:
        db.get(HealthCheck, check_id).down_since = utcnow() - timedelta(hours=1)

    client.delete(f"/api/v1/maintenance/{started['id']}", headers=CSRF)
    service._record(check_id, ok=False, latency=0, detail="ConnectError")

    with db_session() as db:
        outage = db.scalar(select(Outage))
        assert outage is not None and not outage.announced, "a fresh outage, not one an hour old"
        assert (utcnow() - db.get(HealthCheck, check_id).down_since) < timedelta(minutes=1)
    assert told == []


# -- the bars -------------------------------------------------------------------


def test_the_long_bars_leave_maintenance_out(client: TestClient) -> None:
    setup_admin(client)
    tile = _tile(client, _board(client)["pages"][0]["id"])
    check_id = _check_of(tile["id"])
    now = time.time()
    day = 86400

    def at(seconds_ago: float) -> datetime:
        return datetime.fromtimestamp(now - seconds_ago, UTC)

    with db_session() as db:
        db.get(HealthCheck, check_id).created_at = at(30 * day)
        # Yesterday all day in maintenance, and down through it.
        db.add(Maintenance(widget_id=tile["id"], starts_at=at(2 * day), ends_at=at(day)))
        db.add(Outage(check_id=check_id, started_at=at(2 * day), ended_at=at(day), announced=False))
        # The day before: half down, outside any maintenance.
        db.add(Outage(check_id=check_id, started_at=at(3 * day), ended_at=at(2.5 * day), announced=False))

    with db_session() as db:
        bars = health_service.outage_bars_for(db, [tile["id"]], "30d", now=now)[tile["id"]]

    assert bars[-2] is None, "a day of maintenance is unknown, not down"
    assert bars[-3] == pytest.approx(0.5, abs=0.01)
    assert bars[-1] == 1.0


def test_down_inside_maintenance_does_not_count_against_the_rest_of_the_day(client: TestClient) -> None:
    setup_admin(client)
    tile = _tile(client, _board(client)["pages"][0]["id"])
    check_id = _check_of(tile["id"])
    now = time.time()
    day = 86400

    def at(seconds_ago: float) -> datetime:
        return datetime.fromtimestamp(now - seconds_ago, UTC)

    with db_session() as db:
        db.get(HealthCheck, check_id).created_at = at(30 * day)
        # Four days ago: maintenance in the morning and down only then; up the rest of the day.
        db.add(Maintenance(widget_id=tile["id"], starts_at=at(4 * day), ends_at=at(3.5 * day)))
        db.add(Outage(check_id=check_id, started_at=at(4 * day), ended_at=at(3.5 * day), announced=False))

    with db_session() as db:
        bars = health_service.outage_bars_for(db, [tile["id"]], "30d", now=now)[tile["id"]]

    assert bars[-4] == 1.0, "the half that was measured was up"


def test_maintenance_is_swept_with_the_outages(client: TestClient) -> None:
    setup_admin(client)
    tile = _tile(client, _board(client)["pages"][0]["id"])
    with db_session() as db:
        db.add(Maintenance(widget_id=tile["id"], starts_at=utcnow() - timedelta(days=500), ends_at=utcnow() - timedelta(days=499)))
        db.add(Maintenance(widget_id=tile["id"], starts_at=utcnow() - timedelta(days=2), ends_at=utcnow() - timedelta(days=1)))
    with db_session() as db:
        gone = retention.prune_old_records(db)
        left = len(list(db.scalars(select(Maintenance))))
    assert gone["maintenance"] == 1 and left == 1
