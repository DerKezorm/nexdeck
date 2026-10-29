"""B4 of the second security review: what the chat's card draft tells the provider when the service could not be read.

⚠️ Only the code and nexdeck's own sentence, never the message of the failure: that one names the connection or an address.
No real provider (``Script``), no real service (respx).
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.services.assistant import providers, tools
from app.services.collector import collector
from tests.conftest import CSRF, client, data_dir, setup_admin  # noqa: F401 - the fixtures
from tests.test_cards_ai import Script
from tests.test_cards_ai_routes import switch_on
from tests.test_cards_router import BASE, connection

NAME = "Garage Rack 7"


@pytest.fixture
def admin(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> TestClient:  # noqa: F811
    setup_admin(client)
    monkeypatch.setattr(collector, "running", False)
    switch_on(client)
    return client


def drafting(admin: TestClient, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    call = {"id": "toolu_1", "name": "draft_card", "input": {"description": "my queue", "service": "sonarr", "path": "/api/v3/queue"}}
    script = Script(providers.Turn(text="", calls=[call], stop="tools"), providers.Turn(text="It could not be read."))
    monkeypatch.setattr(providers, "turn", script)
    assert admin.post("/api/v1/assistant/chat", json={"text": "Build me a card that shows my queue"}, headers=CSRF).status_code == 200
    seen = json.dumps(script.seen[1]["transcript"][-1])
    return {"seen": seen, "result": json.loads(script.seen[1]["transcript"][-1]["results"][0]["content"])}


def test_karten8t_b4_a_connection_in_demo_mode_is_not_named_to_the_provider(admin: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    connection(admin, "sonarr", name=NAME, demo=True)
    told = drafting(admin, monkeypatch)
    assert told["result"] == {"error": tools.UNREAD["demo_mode"], "code": "demo_mode"}
    assert NAME not in told["seen"]


def test_karten8t_b4_a_redirect_is_told_without_the_host_it_pointed_to(admin: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    connection(admin, "sonarr", name=NAME)
    with respx.mock(assert_all_called=False) as svc:
        svc.get(f"{BASE}/api/v3/queue").mock(return_value=httpx.Response(302, headers={"location": "http://inner.home.example/login"}))
        told = drafting(admin, monkeypatch)
    assert told["result"]["code"] in tools.UNREAD and told["result"]["error"] == tools.UNREAD[told["result"]["code"]]
    for private in (NAME, "inner.home.example", "svc.example.com"):
        assert private not in told["seen"], private


def test_karten8t_b4_an_unknown_code_gets_the_sentence_for_all_others() -> None:
    assert tools._unread("something_new") == {"error": tools.UNREAD_OTHERWISE, "code": "something_new"}
    assert all("{" not in sentence for sentence in [*tools.UNREAD.values(), tools.UNREAD_OTHERWISE])
