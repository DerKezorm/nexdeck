"""Testing a saved connection answers with a reason, never with a bare 500.

⚠️ The interface tests a connection through ``POST /integrations/test``, which
catches an unreadable key and anything unexpected. The documented route for a
saved connection, ``POST /integrations/{id}/test``, read the stored config
outside its ``try`` and caught adapter errors only. After a restore with a
different ``NEXDECK_SECRET_KEY`` a script calling it got an HTTP 500 with no
word about the key. Found on 07.09.2026, still there on 12.09.2026.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.adapters import get_adapter
from app.routers import integrations as integrations_router

from .conftest import CSRF, setup_admin


def _saved(client: TestClient) -> int:
    made = client.post("/api/v1/integrations", json={"kind": "radarr", "name": "Movies", "config": {"url": "http://radarr.example.com:7878", "api_key": "made-up"}}, headers=CSRF)
    assert made.status_code == 201, made.text
    return made.json()["id"]


def test_an_unreadable_key_is_named(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    setup_admin(client)
    number = _saved(client)

    def unreadable(_integration: object) -> dict:
        raise integrations_router.SecretUnreadable("encrypted with another key")

    monkeypatch.setattr(integrations_router, "resolve_config", unreadable)
    answer = client.post(f"/api/v1/integrations/{number}/test", headers=CSRF)
    assert answer.status_code == 200, answer.text
    assert answer.json()["ok"] is False
    assert answer.json()["code"] == "secret_unreadable"
    assert "NEXDECK_SECRET_KEY" in answer.json()["hint"]


def test_an_unexpected_failure_is_a_message(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    setup_admin(client)
    number = _saved(client)

    async def breaks(self: object, config: dict, ctx: object) -> str:
        raise RuntimeError("something nobody planned for")

    monkeypatch.setattr(type(get_adapter("radarr")), "test", breaks)
    answer = client.post(f"/api/v1/integrations/{number}/test", headers=CSRF)
    assert answer.status_code == 200, answer.text
    assert answer.json() == {"ok": False, "message": "Unexpected error: RuntimeError.", "hint": "", "code": "crash"}
