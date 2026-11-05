"""Weekly maintenance (issue #62, 05.11.2026).

"Every Sunday from 03:00 for two hours": a plan writes an ordinary
maintenance stretch shortly before each start, so everything that already
knows maintenance holds the news back. The clock is the browser's zone.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from datetime import date as Date
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select, text

from app.db import db_session
from app.models import Event, Maintenance, MaintenancePlan, Notice
from app.services import maintenance, maintenance_plans, notify

from .conftest import CSRF, create_user, login, setup_admin

SUNDAY_THREE = {"days": [6], "starts": "03:00", "minutes": 120, "zone": "Europe/Berlin"}


@pytest.fixture(autouse=True)
def _fresh_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    # Ids start at 1 in every fresh database, and the stretches of a test began after "boot".
    monkeypatch.setattr(maintenance_plans, "_told", set())
    monkeypatch.setattr(maintenance_plans, "_since_boot", datetime(2000, 1, 1, tzinfo=UTC))


def _plan(**values: Any) -> MaintenancePlan:
    return MaintenancePlan(id=1, integration_id=1, created_by=None, **{**SUNDAY_THREE, **values})


def _utc(text_: str) -> datetime:
    return datetime.fromisoformat(text_).replace(tzinfo=UTC)


def _connection(client: TestClient, name: str = "Synology") -> dict:
    response = client.post("/api/v1/integrations", json={"kind": "radarr", "name": name, "config": {"url": "http://radarr:7878", "api_key": "k"}}, headers=CSRF)
    assert response.status_code in (200, 201), response.text
    return response.json()


def _running_now(minutes_ago: int = 10, length: int = 60) -> dict:
    """A plan of every day whose window began a few minutes ago, on the clock of UTC."""
    began = datetime.now(UTC) - timedelta(minutes=minutes_ago)
    return {"days": list(range(7)), "starts": began.strftime("%H:%M"), "minutes": length, "zone": "UTC"}


# -- the clock ----------------------------------------------------------------


def test_a_window_is_due_shortly_before_its_start_and_until_its_end_in_the_zone_it_was_set_in() -> None:
    plan = _plan()  # Sunday 8 November 2026, 03:00 in Berlin is 02:00 UTC (winter time)
    assert maintenance_plans.due(plan, _utc("2026-11-08T01:55:00")) == []
    [(began, ends)] = maintenance_plans.due(plan, _utc("2026-11-08T01:58:00"))
    assert (began.astimezone(UTC), ends.astimezone(UTC)) == (_utc("2026-11-08T02:00:00"), _utc("2026-11-08T04:00:00"))
    assert maintenance_plans.due(plan, _utc("2026-11-08T03:59:00")) != []
    assert maintenance_plans.due(plan, _utc("2026-11-08T04:00:00")) == []
    assert maintenance_plans.due(plan, _utc("2026-11-07T02:30:00")) == []  # a Saturday


def test_three_o_clock_stays_three_o_clock_in_summer_time() -> None:
    [(began, _ends)] = maintenance_plans.due(_plan(), _utc("2026-07-05T01:30:00"))
    assert began.astimezone(UTC) == _utc("2026-07-05T01:00:00")


def test_a_window_that_runs_past_midnight_is_still_due_the_next_morning() -> None:
    plan = _plan(days=[5], starts="23:00", minutes=180, zone="UTC")  # Saturday 23:00 to Sunday 02:00
    [(began, ends)] = maintenance_plans.due(plan, _utc("2026-11-08T01:30:00"))
    assert (began, ends) == (_utc("2026-11-07T23:00:00"), _utc("2026-11-08T02:00:00"))


def test_the_next_window_is_the_next_one_that_has_not_begun() -> None:
    began, ends = maintenance_plans.next_window(_plan(), _utc("2026-11-08T02:30:00")) or (None, None)
    assert began is not None and began.astimezone(UTC) == _utc("2026-11-15T02:00:00")
    assert ends is not None and ends - began == timedelta(hours=2)


def test_without_a_known_zone_the_server_clock_counts() -> None:
    [(began, _ends)] = maintenance_plans.windows(_plan(zone=""), Date(2026, 11, 8), Date(2026, 11, 8))
    assert began == datetime(2026, 11, 8, 3, 0).astimezone()


# -- writing the stretches ----------------------------------------------------


def test_each_window_is_written_once_and_an_early_end_is_not_undone(client: TestClient) -> None:
    setup_admin(client)
    synology = _connection(client)
    with db_session() as db:
        plan = MaintenancePlan(integration_id=synology["id"], created_by=None, **_running_now())
        db.add(plan)
        db.flush()
        [row] = maintenance_plans.write_due(db)
        assert (row.plan_id, row.integration_id) == (plan.id, synology["id"])
        assert maintenance_plans.write_due(db) == []
        maintenance.end(row)
        db.flush()
        assert maintenance_plans.write_due(db) == []
        assert len(list(db.scalars(select(Maintenance)))) == 1


def test_a_stretch_written_ahead_holds_nothing_back_before_its_start(client: TestClient) -> None:
    setup_admin(client)
    synology = _connection(client)
    soon = datetime.now(UTC) + timedelta(seconds=90)
    with db_session() as db:
        db.add(MaintenancePlan(integration_id=synology["id"], created_by=None, days=list(range(7)),
                               starts=soon.strftime("%H:%M"), minutes=30, zone="UTC"))
        db.flush()
        assert len(maintenance_plans.write_due(db)) == 1
        assert maintenance.covering(db, integration_id=synology["id"]) is None
        start = soon.replace(second=0, microsecond=0)
        assert maintenance.covering(db, integration_id=synology["id"], now=start + timedelta(seconds=1)) is not None


def test_a_round_writes_the_stretch_and_tells_its_beginning_once(client: TestClient) -> None:
    setup_admin(client)
    synology = _connection(client)
    with db_session() as db:
        db.add(MaintenancePlan(integration_id=synology["id"], created_by=None, **_running_now()))
    maintenance_plans.round_once()
    maintenance_plans.round_once()
    with db_session() as db:
        lines = list(db.scalars(select(Event).where(Event.kind == "maintenance")))
        assert [line.name for line in lines] == ["Synology"]
        assert maintenance.covering(db, integration_id=synology["id"]) is not None


def test_a_stretch_that_ran_before_a_restart_is_not_told_again(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    setup_admin(client)
    synology = _connection(client)
    with db_session() as db:
        plan = MaintenancePlan(integration_id=synology["id"], created_by=None, **_running_now())
        db.add(plan)
        db.flush()
        maintenance_plans.write_due(db)
    monkeypatch.setattr(maintenance_plans, "_since_boot", datetime.now(UTC))
    assert maintenance_plans.round_once() == set()
    with db_session() as db:
        assert list(db.scalars(select(Event).where(Event.kind == "maintenance"))) == []


# -- the API ------------------------------------------------------------------


def test_an_admin_plans_lists_and_removes_weekly_maintenance(client: TestClient) -> None:
    setup_admin(client)
    synology = _connection(client)
    made = client.post("/api/v1/maintenance/plans", json={"integration_id": synology["id"], **SUNDAY_THREE, "days": [6, 2, 6]}, headers=CSRF)
    assert made.status_code == 201, made.text
    plan = made.json()
    assert (plan["name"], plan["days"], plan["starts"], plan["minutes"], plan["zone"]) == ("Synology", [2, 6], "03:00", 120, "Europe/Berlin")
    assert datetime.fromisoformat(plan["next_starts_at"]) > datetime.now(UTC)

    listed = client.get("/api/v1/maintenance/plans", params={"integration_id": synology["id"]}).json()
    assert [one["id"] for one in listed] == [plan["id"]]
    assert client.get("/api/v1/maintenance/plans", params={"integration_id": synology["id"] + 1}).json() == []

    changed = client.put(f"/api/v1/maintenance/plans/{plan['id']}", json={**SUNDAY_THREE, "starts": "04:30"}, headers=CSRF)
    assert changed.status_code == 200 and changed.json()["starts"] == "04:30"

    assert client.delete(f"/api/v1/maintenance/plans/{plan['id']}", headers=CSRF).status_code == 204
    assert client.get("/api/v1/maintenance/plans").json() == []
    assert client.delete(f"/api/v1/maintenance/plans/{plan['id']}", headers=CSRF).status_code == 404


@pytest.mark.parametrize(("change", "code"), [
    ({"days": [7]}, "bad_days"),
    ({"starts": "3:00"}, "bad_time"),
    ({"starts": "24:00"}, "bad_time"),
    ({"zone": "Mars/Olympus"}, "bad_zone"),
    ({"integration_id": None}, "bad_target"),
    ({"integration_id": 999}, "not_found"),
])
def test_a_plan_that_makes_no_sense_is_refused(client: TestClient, change: dict, code: str) -> None:
    setup_admin(client)
    synology = _connection(client)
    response = client.post("/api/v1/maintenance/plans", json={"integration_id": synology["id"], **SUNDAY_THREE, **change}, headers=CSRF)
    assert response.status_code in (400, 404), response.text
    assert response.json()["detail"]["code"] == code


@pytest.mark.parametrize("change", [{"days": []}, {"minutes": 0}, {"minutes": 24 * 60 + 1}])
def test_a_plan_without_days_or_with_a_length_out_of_range_is_not_accepted(client: TestClient, change: dict) -> None:
    setup_admin(client)
    synology = _connection(client)
    response = client.post("/api/v1/maintenance/plans", json={"integration_id": synology["id"], **SUNDAY_THREE, **change}, headers=CSRF)
    assert response.status_code == 422


def test_only_an_app_tile_has_a_plan_of_its_own(client: TestClient) -> None:
    setup_admin(client)
    synology = _connection(client)
    board = client.post("/api/v1/boards", json={"name": "Lab"}, headers=CSRF).json()
    page_id = client.get(f"/api/v1/boards/{board['slug']}").json()["pages"][0]["id"]
    queue = client.post(f"/api/v1/pages/{page_id}/widgets", json={"kind": "radarr.queue", "integration_id": synology["id"]}, headers=CSRF).json()["widget"]
    response = client.post("/api/v1/maintenance/plans", json={"widget_id": queue["id"], **SUNDAY_THREE}, headers=CSRF)
    assert response.json()["detail"]["code"] == "not_an_app"


def test_a_member_may_not_plan_maintenance(client: TestClient) -> None:
    setup_admin(client)
    synology = _connection(client)
    create_user(client, "member")
    client.post("/api/v1/auth/logout", headers=CSRF)
    login(client, "member", "another-long-password")
    assert client.post("/api/v1/maintenance/plans", json={"integration_id": synology["id"], **SUNDAY_THREE}, headers=CSRF).status_code == 403
    assert client.get("/api/v1/maintenance/plans").status_code == 403


def test_a_plan_made_inside_its_window_holds_at_once_and_news_is_held_back(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(notify, "spawn", lambda job, name="": None)
    setup_admin(client)
    synology = _connection(client)
    made = client.post("/api/v1/maintenance/plans", json={"integration_id": synology["id"], **_running_now()}, headers=CSRF)
    assert made.status_code == 201, made.text
    [running] = [one for one in client.get("/api/v1/maintenance").json() if one["active"]]
    assert running["plan_id"] == made.json()["id"]

    notify.emit("widget_broken", "The Synology stopped answering", integration_id=synology["id"])
    maintenance_plans.round_once()
    with db_session() as db:
        assert list(db.scalars(select(Notice.title))) == []
        assert [line.name for line in db.scalars(select(Event).where(Event.kind == "maintenance"))] == ["Synology"]


def test_removing_a_plan_lets_the_running_window_end_and_drops_the_one_written_ahead(client: TestClient) -> None:
    setup_admin(client)
    synology = _connection(client)
    plan = client.post("/api/v1/maintenance/plans", json={"integration_id": synology["id"], **_running_now()}, headers=CSRF).json()
    with db_session() as db:
        db.add(Maintenance(integration_id=synology["id"], plan_id=plan["id"], starts_at=datetime.now(UTC) + timedelta(seconds=60),
                           ends_at=datetime.now(UTC) + timedelta(minutes=30)))
    client.delete(f"/api/v1/maintenance/plans/{plan['id']}", headers=CSRF)
    with db_session() as db:
        [left] = list(db.scalars(select(Maintenance)))
        assert left.plan_id is None and left.starts_at <= datetime.now(UTC) < left.ends_at
        assert maintenance.covering(db, integration_id=synology["id"]) is not None


def test_changing_a_plan_drops_the_stretch_written_ahead_for_the_old_time(client: TestClient) -> None:
    setup_admin(client)
    synology = _connection(client)
    soon = datetime.now(UTC) + timedelta(seconds=90)
    plan = client.post("/api/v1/maintenance/plans", json={"integration_id": synology["id"], "days": list(range(7)),
                                                         "starts": soon.strftime("%H:%M"), "minutes": 30, "zone": "UTC"}, headers=CSRF).json()
    with db_session() as db:
        assert len(list(db.scalars(select(Maintenance)))) == 1
    far = (datetime.now(UTC) + timedelta(hours=6)).strftime("%H:%M")
    client.put(f"/api/v1/maintenance/plans/{plan['id']}", json={"days": list(range(7)), "starts": far, "minutes": 30, "zone": "UTC"}, headers=CSRF)
    with db_session() as db:
        assert list(db.scalars(select(Maintenance))) == []


# -- the migration ------------------------------------------------------------


def test_the_migration_gives_an_older_maintenance_table_its_plan(tmp_path: Any) -> None:
    from app.migrations import _maintenance_plans

    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE integrations (id INTEGER PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE widgets (id INTEGER PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE maintenance (id INTEGER PRIMARY KEY, integration_id INTEGER, widget_id INTEGER, "
                                "starts_at VARCHAR, ends_at VARCHAR, created_by INTEGER, created_at VARCHAR)"))
        _maintenance_plans(connection)
        _maintenance_plans(connection)  # twice is harmless
    found = inspect(engine)
    assert "plan_id" in {column["name"] for column in found.get_columns("maintenance")}
    assert {"days", "starts", "minutes", "zone"} <= {column["name"] for column in found.get_columns("maintenance_plans")}
