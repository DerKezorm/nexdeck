"""Leaving demo mode takes what the demo invented along, and nothing else.

Switching the flag off used to leave the demo's connections in place, each
with a demo switch of its own, so the demo board went on inventing data after
the notice that says so had gone."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from .conftest import CSRF, create_user, login, setup_admin


def _card(client: TestClient, page_id: int, kind: str, integration_id: int | None = None) -> dict:
    body: dict = {"kind": kind}
    if integration_id is not None:
        body["integration_id"] = integration_id
    response = client.post(f"/api/v1/pages/{page_id}/widgets", json=body, headers=CSRF)
    assert response.status_code == 201, response.text
    return response.json()["widget"]


def _demo_connection(client: TestClient) -> int:
    connections = client.get("/api/v1/integrations").json()
    return next(c["id"] for c in connections if c["kind"] == "docker" and c["demo"])


def test_the_demo_board_and_its_connections_go_and_a_starter_board_comes(client: TestClient) -> None:
    setup_admin(client, demo=True)

    def connections() -> list[tuple[int, str, bool]]:
        return [(c["id"], c["name"], c["demo"]) for c in client.get("/api/v1/integrations").json()]

    before = connections()
    assert before and all(demo for _, _, demo in before)

    plan = client.get("/api/v1/demo/leave").json()
    assert plan["flag"] is True and plan["boards"] == ["Home"] and plan["cards"] > 10
    assert connections() == before, "asking what would go changes nothing"

    left = client.post("/api/v1/demo/leave", headers=CSRF)
    assert left.status_code == 200, left.text
    assert client.get("/api/v1/integrations").json() == []
    boards = client.get("/api/v1/boards").json()
    assert [b["slug"] for b in boards] == [left.json()["starter"]], "nobody is left without a board"
    about = client.get("/api/v1/about").json()
    assert about["demo"] is False and about["demo_data"] is False

    # Stored, not only in memory: after a restart the demo stays left.
    from app.db import db_session
    from app.routers.system import load_demo_flag
    from app.services.collector import demo_flag, set_demo_flag

    set_demo_flag(True)
    with db_session() as db:
        load_demo_flag(db)
    assert demo_flag() is False


def test_a_board_of_ones_own_keeps_everything_but_the_invented_cards(client: TestClient) -> None:
    setup_admin(client, demo=True)
    demo = _demo_connection(client)
    real = client.post("/api/v1/integrations", json={"kind": "docker", "name": "Docker", "config": {"host": "tcp://docker.example.com:2375"}}, headers=CSRF).json()
    board = client.post("/api/v1/boards", json={"name": "Mine"}, headers=CSRF).json()
    first = board["pages"][0]["id"]
    clock = _card(client, first, "core.clock")
    mine = _card(client, first, "docker.containers", real["id"])
    borrowed = _card(client, first, "docker.load", demo)
    second = next(p for p in client.post(f"/api/v1/boards/{board['slug']}/pages", json={"name": "Borrowed"}, headers=CSRF).json()["pages"]
                  if p["name"] == "Borrowed")
    _card(client, second["id"], "docker.load", demo)
    plan = client.get("/api/v1/demo/leave").json()
    assert plan["boards"] == ["Home"] and plan["pages"] == 1

    assert client.post("/api/v1/demo/leave", headers=CSRF).status_code == 200
    view = client.get(f"/api/v1/boards/{board['slug']}").json()
    assert [p["name"] for p in view["pages"]] == [board["pages"][0]["name"]], "the page that held only demo cards went"
    ids = {w["id"] for w in view["pages"][0]["widgets"]}
    assert ids == {clock["id"], mine["id"]}
    assert str(borrowed["id"]) not in {item["i"] for item in view["pages"][0]["layouts"]["lg"]}, "no hole left in the arrangement"
    assert [c["id"] for c in client.get("/api/v1/integrations").json()] == [real["id"]]
    assert "Home" not in [b["name"] for b in client.get("/api/v1/boards").json()]


def test_a_real_connection_tried_in_demo_mode_stays_and_goes_back_to_real_data(client: TestClient) -> None:
    setup_admin(client)
    real = client.post("/api/v1/integrations", json={"kind": "docker", "name": "Docker", "demo": True, "config": {"host": "tcp://docker.example.com:2375"}}, headers=CSRF).json()
    board = client.post("/api/v1/boards", json={"name": "Mine"}, headers=CSRF).json()
    card = _card(client, board["pages"][0]["id"], "docker.load", real["id"])
    assert client.get("/api/v1/about").json()["demo_data"] is True

    plan = client.get("/api/v1/demo/leave").json()
    assert plan["switched"] == ["Docker"] and plan["connections"] == [] and plan["cards"] == 0
    assert client.post("/api/v1/demo/leave", headers=CSRF).status_code == 200
    connection = client.get("/api/v1/integrations").json()[0]
    assert connection["id"] == real["id"] and connection["demo"] is False
    assert [w["id"] for w in client.get(f"/api/v1/boards/{board['slug']}").json()["pages"][0]["widgets"]] == [card["id"]]


def test_leaving_is_for_administrators_and_not_while_the_container_holds_the_demo(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    setup_admin(client, demo=True)
    create_user(client, "member")
    from app import config

    monkeypatch.setenv("NEXDECK_DEMO", "1")
    config.reset_settings_cache()
    refused = client.post("/api/v1/demo/leave", headers=CSRF)
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "demo_forced"
    assert client.get("/api/v1/demo/leave").json()["forced"] is True
    monkeypatch.setenv("NEXDECK_DEMO", "0")
    config.reset_settings_cache()

    login(client, "member", "another-long-password")
    assert client.post("/api/v1/demo/leave", headers=CSRF).status_code == 403
    assert client.get("/api/v1/demo/leave").status_code == 403


def test_a_connection_deleted_while_its_card_is_read_is_no_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Leaving the demo deletes connections whose cards may be in the middle
    of a read; marking the connection afterwards found no row and logged an
    error with a traceback for something that is not one."""
    from contextlib import contextmanager

    from sqlalchemy.orm.exc import StaleDataError

    from app.services import collector as collector_module

    @contextmanager
    def gone():  # type: ignore[no-untyped-def]
        raise StaleDataError("UPDATE statement on table 'integrations' expected to update 1 row(s); 0 were matched.")
        yield

    monkeypatch.setattr(collector_module, "db_session", gone)
    collector_module.collector._caches.pop(424242, None)
    collector_module.collector._mark_integration(424242, ok=True)
