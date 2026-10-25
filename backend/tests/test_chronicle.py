"""The chronicle (roadmap M2, 25.10.2026): what changed, and when, and who may read it."""

from __future__ import annotations

import time
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.adapters.base import WidgetData
from app.db import db_session
from app.models import Event, HealthCheck, Outage, utcnow
from app.services import chronicle, notify, retention
from app.services import health as health_service
from app.services.collector import Collector, collector
from app.services.state import live

from .conftest import CSRF, create_user, login, setup_admin


def _board(client: TestClient, name: str = "Lab") -> dict:
    response = client.post("/api/v1/boards", json={"name": name}, headers=CSRF)
    assert response.status_code == 201, response.text
    return response.json()


def _widget(client: TestClient, page_id: int, kind: str = "core.clock", **extra: object) -> dict:
    response = client.post(f"/api/v1/pages/{page_id}/widgets", json={"kind": kind, **extra}, headers=CSRF)
    assert response.status_code == 201, response.text
    widget = response.json()["widget"]
    collector.unschedule(widget["id"])
    return widget


def _lines(kind: str | None = None) -> list[Event]:
    with db_session() as db:
        query = select(Event).order_by(Event.id)
        if kind:
            query = query.where(Event.kind == kind)
        return list(db.scalars(query))


# -- what goes in -------------------------------------------------------------------


def test_a_card_that_changes_colour_is_one_line_and_its_first_answer_is_none(client: TestClient) -> None:
    setup_admin(client)
    nas = _widget(client, _board(client)["pages"][0]["id"], title="Synology")
    write = Collector._write_down

    write(nas["id"], "Synology", "synology.volumes", None, None, WidgetData(status="warn"))
    assert _lines("card") == [], "nobody knows what came before the first answer"
    write(nas["id"], "Synology", "synology.volumes", None, WidgetData(status="ok"), WidgetData(status="warn", meta={"status_reason": "Volume 1 is 91 % full"}))
    write(nas["id"], "Synology", "synology.volumes", None, WidgetData(status="warn"), WidgetData(status="warn"))
    write(nas["id"], "Synology", "synology.volumes", None, WidgetData(status="warn"), WidgetData(status="ok", error="Refused"))

    lines = _lines("card")
    assert [(line.before, line.after, line.level) for line in lines] == [("ok", "warn", "warn"), ("warn", "bad", "bad")]
    assert lines[0].detail == "Volume 1 is 91 % full" and lines[1].detail == "Refused"
    assert lines[0].board_id is not None


def test_cards_that_repeat_others_write_nothing(client: TestClient) -> None:
    setup_admin(client)
    card = _widget(client, _board(client)["pages"][0]["id"], kind="core.problems")
    Collector._write_down(card["id"], "Attention", "core.problems", None, WidgetData(status="ok"), WidgetData(status="bad"))
    assert _lines("card") == []


def test_since_survives_a_restart_through_the_chronicle(client: TestClient) -> None:
    setup_admin(client)
    nas = _widget(client, _board(client)["pages"][0]["id"], title="Synology")
    with db_session() as db:
        chronicle.record("card", level="warn", widget_id=nas["id"], name="Synology", before="ok", after="warn",
                         at=utcnow() - timedelta(hours=5), db=db)
    live.clear()
    live.set(nas["id"], WidgetData(status="warn"))

    since = live.recall(nas["id"], lambda: chronicle.last_turned(nas["id"], "warn"))

    assert since is not None and abs(since - (time.time() - 5 * 3600)) < 5
    assert chronicle.last_turned(nas["id"], "bad") is None, "the last line says yellow, not red"


def test_a_container_that_kept_running_did_not_restart() -> None:
    same = WidgetData(items=[{"id": "a", "title": "plex", "state": "running", "subtitle": "Up 3 days"}])
    assert chronicle.containers_changed(same, same) == []
    # Docker never rounds down: a minute less is a restart, however close.
    later = WidgetData(items=[{"id": "a", "title": "plex", "state": "running", "subtitle": "Up About a minute"}])
    earlier = WidgetData(items=[{"id": "a", "title": "plex", "state": "running", "subtitle": "Up 2 minutes"}])
    assert [kind for kind, *_ in chronicle.containers_changed(earlier, later)] == ["container_restarted"]


@pytest.mark.parametrize(("words", "seconds"), [
    ("Up 3 days (healthy)", 3 * 86400), ("Up About an hour", 3600), ("Up Less than a second", 0),
    ("Up 47 seconds", 47), ("Up 2 weeks", 2 * 604800), ("Exited (0) 3 hours ago", None),
])
def test_docker_says_how_long_a_container_is_up(words: str, seconds: float | None) -> None:
    assert chronicle.uptime(words) == seconds


def test_a_restarted_and_a_recreated_container_are_told_apart() -> None:
    before = WidgetData(items=[
        {"id": "aaa", "title": "sonarr", "state": "running", "subtitle": "Up 3 days", "image": "sonarr:4.0.15"},
        {"id": "bbb", "title": "plex", "state": "running", "subtitle": "Up 2 hours"},
        {"id": "ccc", "title": "steady", "state": "running", "subtitle": "Up 5 minutes"},
    ])
    after = WidgetData(items=[
        {"id": "zzz", "title": "sonarr", "state": "running", "subtitle": "Up 10 seconds", "image": "sonarr:4.0.16"},
        {"id": "bbb", "title": "plex", "state": "running", "subtitle": "Up 30 seconds"},
        {"id": "ccc", "title": "steady", "state": "running", "subtitle": "Up 6 minutes"},
    ])
    assert chronicle.containers_changed(before, after) == [
        ("container_recreated", "sonarr", "sonarr:4.0.15", "sonarr:4.0.16"),
        ("container_restarted", "plex", "Up 2 hours", "Up 30 seconds"),
    ]
    assert chronicle.containers_changed(None, after) == []
    assert chronicle.containers_changed(WidgetData(error="unreachable"), after) == []


def test_a_new_version_is_a_line_but_the_first_reading_is_not(client: TestClient) -> None:
    setup_admin(client)
    chronicle.version_read(7, "Sonarr", "4.0.15")
    chronicle.version_read(7, "Sonarr", "4.0.15")
    assert _lines("version") == []
    chronicle.version_read(7, "Sonarr", "4.0.16")
    [line] = _lines("version")
    assert (line.integration_id, line.before, line.after) == (7, "4.0.15", "4.0.16")


def test_an_outage_is_written_when_it_counts_dated_when_it_began(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(notify, "emit", lambda *args, **kwargs: None)
    setup_admin(client)
    tile = _widget(client, _board(client)["pages"][0]["id"], kind="core.app", title="Paperless", link="http://paperless.invalid")
    with db_session() as db:
        check_id = db.scalar(select(HealthCheck.id).where(HealthCheck.widget_id == tile["id"]))
    service = health_service.HealthService()
    service._record(check_id, ok=False, latency=0, detail="ConnectError")
    assert _lines("outage") == [], "a blip is no outage yet"
    with db_session() as db:
        began = utcnow() - timedelta(minutes=10)
        db.get(HealthCheck, check_id).down_since = began
        db.scalar(select(Outage)).started_at = began
    service._record(check_id, ok=False, latency=0, detail="ConnectError")
    service._record(check_id, ok=True, latency=5, detail="HTTP 200")

    [outage] = _lines("outage")
    [recovery] = _lines("recovery")
    assert outage.name == "Paperless" and abs(outage.at.timestamp() - began.timestamp()) < 2
    assert recovery.detail == "10 min"


def test_changes_made_in_nexdeck_are_lines(client: TestClient) -> None:
    setup_admin(client)
    movies = client.post("/api/v1/integrations", json={"kind": "radarr", "name": "Movies", "config": {"url": "http://radarr:7878", "api_key": "k"}}, headers=CSRF).json()
    client.patch(f"/api/v1/integrations/{movies['id']}", json={"name": "Films"}, headers=CSRF)
    page = _board(client)["pages"][0]["id"]
    card = _widget(client, page, kind="radarr.queue", integration_id=movies["id"], title="Queue")
    client.delete(f"/api/v1/widgets/{card['id']}", headers=CSRF)
    client.delete(f"/api/v1/integrations/{movies['id']}", headers=CSRF)

    kinds = [line.kind for line in _lines() if line.kind != "signed_in"]
    assert kinds == ["connection_added", "connection_changed", "card_added", "card_removed", "connection_removed"]
    changed = _lines("connection_changed")[0]
    assert "renamed" in changed.detail and "k" not in changed.detail.split(), "what changed, never a value"


def test_sign_ins_and_refused_ones_are_lines(client: TestClient) -> None:
    setup_admin(client)
    client.post("/api/v1/auth/logout", headers=CSRF)
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "wrong-password-here"})
    from .conftest import ADMIN

    login(client, ADMIN["username"], ADMIN["password"])
    assert [line.kind for line in _lines() if line.kind in ("signed_in", "sign_in_refused")][-2:] == ["sign_in_refused", "signed_in"]
    assert _lines("sign_in_refused")[0].name == "admin"


def test_maintenance_begins_and_ends_early_in_the_chronicle(client: TestClient) -> None:
    setup_admin(client)
    movies = client.post("/api/v1/integrations", json={"kind": "radarr", "name": "Movies", "config": {"url": "http://radarr:7878", "api_key": "k"}}, headers=CSRF).json()
    started = client.post("/api/v1/maintenance", json={"integration_id": movies["id"], "minutes": 60}, headers=CSRF).json()
    client.delete(f"/api/v1/maintenance/{started['id']}", headers=CSRF)
    assert [line.kind for line in _lines() if line.kind.startswith("maintenance")] == ["maintenance", "maintenance_end"]


def test_a_line_that_cannot_be_written_breaks_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken():  # noqa: ANN202
        raise RuntimeError("disk full")

    monkeypatch.setattr(chronicle, "db_session", broken)
    chronicle.record("card", name="Anything")


def test_an_unknown_kind_is_refused() -> None:
    with pytest.raises(ValueError):
        chronicle.record("gossip", name="?")


# -- who reads what --------------------------------------------------------------------


def _write_some(client: TestClient) -> dict:
    setup_admin(client)
    mine = _board(client, "Infrastructure")
    nas = _widget(client, mine["pages"][0]["id"], title="Synology")
    Collector._write_down(nas["id"], "Synology", "synology.volumes", None, WidgetData(status="ok"), WidgetData(status="bad"))
    create_user(client, "mia")
    return {"board": mine, "nas": nas}


def test_an_administrator_reads_everything(client: TestClient) -> None:
    _write_some(client)
    kinds = {line["kind"] for line in client.get("/api/v1/chronicle").json()["events"]}
    assert {"card", "signed_in", "card_added"} <= kinds


def test_a_member_reads_only_the_boards_she_may_open_and_nothing_about_the_installation(client: TestClient) -> None:
    lab = _write_some(client)
    login(client, "mia", "another-long-password")
    assert client.get("/api/v1/chronicle").json()["events"] == []

    from .conftest import ADMIN

    login(client, ADMIN["username"], ADMIN["password"])
    # A connection used on her board: its changes are about the installation all the same.
    movies = client.post("/api/v1/integrations", json={"kind": "radarr", "name": "Movies", "config": {"url": "http://radarr:7878", "api_key": "k"}}, headers=CSRF).json()
    _widget(client, lab["board"]["pages"][0]["id"], kind="radarr.queue", integration_id=movies["id"], title="Queue")
    mia = next(user for user in client.get("/api/v1/users").json() if user["username"] == "mia")
    shared = client.put(f"/api/v1/boards/{lab['board']['slug']}/shares", json={"shares": [{"user_id": mia["id"], "level": "view"}]}, headers=CSRF)
    assert shared.status_code in (200, 201), shared.text
    login(client, "mia", "another-long-password")

    lines = client.get("/api/v1/chronicle").json()["events"]
    assert {line["kind"] for line in lines} == {"card", "card_added"}
    card = next(line for line in lines if line["kind"] == "card")
    assert card["target"]["widget"] == lab["nas"]["id"]


def test_the_page_filters_by_group_window_and_words_and_pages_back(client: TestClient) -> None:
    _write_some(client)
    with db_session() as db:
        chronicle.record("version", name="Sonarr", before="4.0.15", after="4.0.16", db=db)
        chronicle.record("version", name="Radarr", before="5.1", after="5.2", at=utcnow() - timedelta(days=3), db=db)
    versions = client.get("/api/v1/chronicle?group=versions&days=1").json()["events"]
    assert [line["name"] for line in versions] == ["Sonarr"]
    assert [line["name"] for line in client.get("/api/v1/chronicle?group=versions&days=7").json()["events"]] == ["Sonarr", "Radarr"]
    found = client.get("/api/v1/chronicle?q=radar").json()
    assert [line["name"] for line in found["events"]] == ["Radarr"], found
    first = client.get("/api/v1/chronicle?group=versions&limit=1").json()
    assert first["more"] is True
    rest = client.get(f"/api/v1/chronicle?group=versions&limit=1&before={first['events'][0]['id']}").json()
    assert [line["name"] for line in rest["events"]] == ["Radarr"]
    assert client.get("/api/v1/chronicle?days=3").status_code == 400
    assert client.get("/api/v1/chronicle?group=gossip").status_code == 400


def test_the_card_shows_the_boards_of_its_owner(client: TestClient) -> None:
    lab = _write_some(client)
    other = _board(client, "Media")
    card = _widget(client, other["pages"][0]["id"], kind="core.chronicle")
    with db_session() as db:
        whole = chronicle.card_lines(db, card["id"], kinds=("card",), whole=True, limit=10)
        alone = chronicle.card_lines(db, card["id"], kinds=("card",), whole=False, limit=10)
    assert [line["name"] for line in whole] == ["Synology"]
    assert alone == []
    assert lab["nas"]["id"] == whole[0]["target"]["widget"]


def test_lines_older_than_a_year_are_swept(client: TestClient) -> None:
    setup_admin(client)
    with db_session() as db:
        chronicle.record("card", name="Old", at=utcnow() - timedelta(days=400), db=db)
        chronicle.record("card", name="New", db=db)
    with db_session() as db:
        gone = retention.prune_old_records(db)
    assert gone["events"] == 1
    assert [line.name for line in _lines("card")] == ["New"]
