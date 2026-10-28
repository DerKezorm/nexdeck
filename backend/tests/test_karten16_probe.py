"""KARTEN-16 EC-4: a probe of the editor is remembered for the administrator who made it, to warn about demo data that look like it."""

from __future__ import annotations

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.services.collector import collector
from app.workshop import real_values

from .cards_sample import DEMO_LINE, VALUE_CARD, changed
from .conftest import CSRF, setup_admin
from .karten16_sample import account
from .test_cards_router import BASE, add, connection

SHARE = "/api/v1/workshop/submit/check"
BODY = {"type": "card", "slug": "queue-size"}


@pytest.fixture
def admin(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    setup_admin(client)
    monkeypatch.setattr(collector, "running", False)
    real_values.forget()
    return client


def demo_with(title: str) -> str:
    return changed(DEMO_LINE, f'demo:\n  queue: {{totalRecords: 4, records: [{{title: "{title}", size: 100}}]}}\n')


@respx.mock
def test_karten16_ec4_what_the_editor_probed_is_what_the_demo_data_are_compared_with(admin: TestClient) -> None:
    assert add(admin, demo_with("The Private Show Name")).status_code == 201
    sonarr = connection(admin)
    respx.get(f"{BASE}/api/v3/queue").mock(return_value=httpx.Response(200, json={"records": [{"title": "The Private Show Name"}]}))
    before = admin.post(SHARE, json=BODY, headers=CSRF)
    assert before.status_code == 200 and before.json()["warnings"]["real_values"] == []
    probed = admin.post("/api/v1/cards/probe", json={"integration_id": sonarr, "path": "/api/v3/queue"}, headers=CSRF)
    assert probed.status_code == 200, probed.text
    found = admin.post(SHARE, json=BODY, headers=CSRF).json()
    assert found["warnings"]["real_values"] == [{"path": "demo.queue.records[0].title", "value": "The Private Show Name"}]
    assert found["problems"] == []


@respx.mock
def test_karten16_ec4_a_probe_that_failed_leaves_nothing_behind(admin: TestClient) -> None:
    assert add(admin, VALUE_CARD).status_code == 201
    sonarr = connection(admin)
    respx.get(f"{BASE}/api/v3/queue").mock(return_value=httpx.Response(500, json={"title": "Not A Show Name"}))
    admin.post("/api/v1/cards/probe", json={"integration_id": sonarr, "path": "/api/v3/queue"}, headers=CSRF)
    assert real_values._real(account(1)) == frozenset()  # noqa: SLF001
