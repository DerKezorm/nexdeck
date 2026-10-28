"""KARTEN-12 AC-3 with KARTEN-3 EC-10: the check of an import names the fields replacing an own connection would throw away,
with what the connections keep in them, secrets included."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.adapters import forget_all_custom
from app.db import db_session
from app.models import Integration
from app.services.collector import collector

from .conftest import CSRF, setup_admin
from .karten12_sample import INTEGRATION, SHORT

RENAMED = INTEGRATION.replace("token_secret", "token_renamed")


@pytest.fixture
def admin(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    setup_admin(client)
    monkeypatch.setattr(collector, "running", False)
    yield client
    forget_all_custom()


def dropped(admin: TestClient, text: str) -> list[str] | None:
    answer = admin.post("/api/v1/cards/import/check", json={"text": text}, headers=CSRF)
    assert answer.status_code == 200, answer.text
    (document,) = answer.json()["documents"]
    return document.get("dropped_fields")


def test_karten12_ac3_the_check_names_the_fields_replacing_an_own_connection_throws_away(admin: TestClient) -> None:
    assert RENAMED != INTEGRATION
    assert dropped(admin, RENAMED) == []  # nothing here yet: nothing is thrown away
    assert admin.post("/api/v1/own-integrations", json={"yaml": INTEGRATION}, headers=CSRF).status_code == 201
    assert dropped(admin, INTEGRATION) == []  # the same text
    assert dropped(admin, RENAMED) == ["token_secret"]
    # And that is what replacing does: the secret of the connection is gone.
    body = {"kind": f"custom:{SHORT}", "name": "Wiki", "config": {"url": "http://wiki.example.com", "token_id": "ID-1", "token_secret": "SECRET-1"}}
    made = admin.post("/api/v1/integrations", json=body, headers=CSRF)
    assert made.status_code == 201, made.text
    replaced = admin.post("/api/v1/cards/import", json={"text": RENAMED, "choices": {f"integration:{SHORT}": "replace"}}, headers=CSRF)
    assert replaced.status_code == 201, replaced.text
    with db_session() as db:
        assert "token_secret" not in (db.get(Integration, made.json()["id"]).config or {})
