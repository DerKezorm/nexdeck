"""Issue #20: a connection can be muted, and then nothing about it is told.

The channels already choose which events they carry. The bell on a
connection is the other axis: this one service, on every way at once.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text

from app.adapters.base import WidgetData
from app.db import db_session
from app.migrations import MIGRATIONS
from app.models import Integration, Notice
from app.services import notify

from .conftest import CSRF, setup_admin


@pytest.fixture(autouse=True)
def _no_probes(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import health

    async def nothing(force: bool = False) -> None:
        return None

    monkeypatch.setattr(health.health, "run_due", nothing)


@pytest.fixture
def dispatched(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """What was handed on to the channels, by name of the background task."""
    handed: list[str] = []
    monkeypatch.setattr(notify, "spawn", lambda job, name="": handed.append(name))
    return handed


def _connection(client: TestClient, name: str = "Sonarr") -> int:
    response = client.post("/api/v1/integrations", json={"kind": "sonarr", "name": name, "demo": True}, headers=CSRF)
    assert response.status_code == 201, response.text
    assert response.json()["muted"] is False, "a new connection speaks"
    return response.json()["id"]


def _mute(client: TestClient, integration_id: int, muted: bool) -> dict:
    response = client.patch(f"/api/v1/integrations/{integration_id}", json={"muted": muted}, headers=CSRF)
    assert response.status_code == 200, response.text
    return response.json()


def _notices() -> list[str]:
    with db_session() as db:
        return list(db.scalars(select(Notice.title)))


def test_a_muted_connection_reaches_neither_the_bell_nor_a_channel(client: TestClient, dispatched: list[str]) -> None:
    setup_admin(client)
    sonarr = _connection(client)
    assert _mute(client, sonarr, True)["muted"] is True

    notify.emit("widget_broken", "Sonarr stopped working", level="warn", integration_id=sonarr)
    assert _notices() == []
    assert dispatched == [], "the channels hear nothing either"

    _mute(client, sonarr, False)
    notify.emit("widget_broken", "Sonarr stopped working", level="warn", integration_id=sonarr)
    assert _notices() == ["Sonarr stopped working"]
    assert dispatched == ["notify-dispatch"]


def test_muting_one_connection_leaves_the_others_and_the_rest_speaking(client: TestClient, dispatched: list[str]) -> None:
    setup_admin(client)
    sonarr = _connection(client, "Sonarr")
    radarr = _connection(client, "Radarr")
    _mute(client, sonarr, True)

    notify.emit("outage", "Radarr is down", integration_id=radarr)
    notify.emit("update_available", "nexdeck 9.9.9 is out")
    assert sorted(_notices()) == ["Radarr is down", "nexdeck 9.9.9 is out"]


def test_the_list_says_which_connection_is_muted(client: TestClient) -> None:
    setup_admin(client)
    sonarr = _connection(client)
    _mute(client, sonarr, True)
    listed = {row["id"]: row for row in client.get("/api/v1/integrations").json()}
    assert listed[sonarr]["muted"] is True


def test_the_bell_alone_leaves_the_cards_alone(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Rescheduling logs every card in again and wipes the last error; the
    bell changes nothing about how they talk to the service."""
    from app.routers import integrations

    setup_admin(client)
    sonarr = _connection(client)
    rescheduled: list[int] = []
    monkeypatch.setattr(integrations.collector, "reschedule_integration", lambda integration_id, farewell=None: rescheduled.append(integration_id))
    with db_session() as db:
        db.get(Integration, sonarr).last_error = "401 Unauthorized"

    answer = _mute(client, sonarr, True)
    assert rescheduled == []
    assert answer["last_error"] == "401 Unauthorized", "the red line under the name stays until the card says otherwise"

    client.patch(f"/api/v1/integrations/{sonarr}", json={"name": "Sonarr 4K"}, headers=CSRF)
    assert rescheduled == [sonarr], "any other change still reschedules"


def test_a_user_may_not_mute_a_connection(client: TestClient) -> None:
    from .conftest import create_user, login

    setup_admin(client)
    sonarr = _connection(client)
    create_user(client, "sam")
    login(client, "sam", "another-long-password")
    response = client.patch(f"/api/v1/integrations/{sonarr}", json={"muted": True}, headers=CSRF)
    assert response.status_code == 403


def test_a_card_of_a_muted_connection_says_nothing_when_it_breaks(client: TestClient, dispatched: list[str]) -> None:
    from app.services.collector import collector

    setup_admin(client)
    sonarr = _connection(client)
    _mute(client, sonarr, True)
    collector._tell_about_failure(9001, "Sonarr", WidgetData(error="refused", meta={"code": "auth_failed"}), sonarr)
    collector._tell_about_failure(9002, "Sonarr", WidgetData(error="refused"), sonarr)
    assert _notices() == []

    # The way the refresh loop takes: through the one door for every answer.
    collector._tell_about(9004, "Sonarr", object(), "queue", None, WidgetData(error="refused"), {}, sonarr)
    assert _notices() == []

    _mute(client, sonarr, False)
    collector._tell_about_failure(9003, "Sonarr", WidgetData(error="refused"), sonarr)
    assert _notices() == ["Sonarr stopped working"]


def test_what_a_card_of_a_muted_connection_notices_stays_quiet(client: TestClient, dispatched: list[str]) -> None:
    """The detectors: a finished download, a new request, a disk filling up."""
    from app.adapters.base import Detected
    from app.services.collector import collector

    class Noticing:
        def detect(self, kind: str, before: Any, after: Any, options: dict) -> list[Detected]:
            return [Detected(event="download_done", title="Film.2026 finished", key="x")]

    setup_admin(client)
    sonarr = _connection(client)
    _mute(client, sonarr, True)
    collector._tell_about(9101, "Queue", Noticing(), "queue", WidgetData(), WidgetData(), {}, sonarr)
    assert _notices() == []


def test_an_outage_of_a_check_on_a_muted_connection_stays_quiet(client: TestClient, dispatched: list[str]) -> None:
    from app.services.health import health

    setup_admin(client)
    sonarr = _connection(client)
    _mute(client, sonarr, True)
    health._announce((None, {}, ("outage", "Sonarr is down", "", "error", sonarr)))
    assert _notices() == []
    health._announce((None, {}, ("outage", "Plain tile is down", "", "error", None)))
    assert _notices() == ["Plain tile is down"]


def test_the_step_adds_the_column_to_an_older_database() -> None:
    step = {version: function for version, _description, function in MIGRATIONS}[15]
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE integrations (id INTEGER PRIMARY KEY, name VARCHAR(120))"))
        connection.execute(text("INSERT INTO integrations (id, name) VALUES (1, 'Sonarr')"))
        step(connection)
        step(connection)  # twice is harmless
        assert connection.execute(text("SELECT muted FROM integrations")).scalar() == 0, "an existing connection keeps speaking"
