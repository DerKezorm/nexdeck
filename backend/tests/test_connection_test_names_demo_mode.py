"""A passed connection test says so when the cards will not show what it found.

⚠️ Issue #2: the test asked a real Nomad and found 24 jobs, and the cards kept
showing the three sample nodes, because the setup wizard's demo board had put
the whole installation in demo mode. The test answered green with nothing
else, and the reporter went looking for a bug in the adapter.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.adapters import get_adapter
from app.config import get_settings
from app.services import collector as collector_module

from .conftest import CSRF, setup_admin

CONFIG = {"url": "http://radarr.example.com:7878", "api_key": "made-up"}


@pytest.fixture
def answers(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fine(self: object, config: dict, ctx: object) -> str:
        return "Radarr answers."

    monkeypatch.setattr(type(get_adapter("radarr")), "test", fine)


def _saved(client: TestClient) -> int:
    made = client.post("/api/v1/integrations", json={"kind": "radarr", "name": "Movies", "config": CONFIG}, headers=CSRF)
    assert made.status_code == 201, made.text
    return made.json()["id"]


def test_without_demo_mode_the_test_adds_nothing(client: TestClient, answers: None) -> None:
    setup_admin(client)
    answer = client.post("/api/v1/integrations/test", json={"kind": "radarr", "config": CONFIG}, headers=CSRF)
    assert answer.json() == {"ok": True, "message": "Radarr answers."}


def test_demo_mode_is_named_on_both_routes(client: TestClient, answers: None) -> None:
    setup_admin(client)
    number = _saved(client)
    assert client.patch("/api/v1/settings", json={"demo": True}, headers=CSRF).status_code == 200

    for answer in (
        client.post("/api/v1/integrations/test", json={"kind": "radarr", "config": CONFIG}, headers=CSRF),
        client.post(f"/api/v1/integrations/{number}/test", headers=CSRF),
    ):
        assert answer.json()["ok"] is True, answer.text
        assert "System > Integrations" in answer.json()["hint"]


def test_demo_mode_from_the_variable_names_the_variable(client: TestClient, answers: None, monkeypatch: pytest.MonkeyPatch) -> None:
    setup_admin(client)
    monkeypatch.setattr(get_settings(), "demo", True)
    collector_module.set_demo_flag(False)
    answer = client.post("/api/v1/integrations/test", json={"kind": "radarr", "config": CONFIG}, headers=CSRF)
    assert "NEXDECK_DEMO" in answer.json()["hint"]
    about = client.get("/api/v1/about").json()
    assert about["demo"] is True
    assert about["demo_forced"] is True
