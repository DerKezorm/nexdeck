"""The addresses of the card help in the editor: who may, what is probed and sent, one at a time, cancelling (KARTEN-17)."""

from __future__ import annotations

import asyncio
import threading
from typing import Any

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.cards import ai
from app.services.assistant import providers
from app.services.collector import collector

from .conftest import CSRF, create_user, login, setup_admin
from .test_cards_ai import ANSWER, SECRET_KEY, SECRET_NUMBER, SECRET_TEXT, Script, card
from .test_cards_router import BASE, as_admin, connection

API = "/api/v1/cards/ai"


@pytest.fixture
def admin(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    setup_admin(client)
    monkeypatch.setattr(collector, "running", False)
    return client


def switch_on(client: TestClient) -> None:
    done = client.put("/api/v1/settings/assistant", json={"provider": "anthropic", "model": "", "key": "sk-ant-test"}, headers=CSRF)
    assert done.status_code == 200, done.text


def post(client: TestClient, **body: Any) -> httpx.Response:
    return client.post(API, json=body, headers=CSRF)


def new_card(client: TestClient, sonarr: int, **more: Any) -> httpx.Response:
    return post(client, mode="new", description="Show my queue", connection_id=sonarr, path="/api/v3/queue", **more)


def test_karten17_ac1_ec6_without_a_provider_the_calls_answer_assistant_off(admin: TestClient) -> None:
    sonarr = connection(admin)
    answer = new_card(admin, sonarr)
    assert answer.status_code == 409 and answer.json()["detail"]["code"] == "assistant_off"
    assert admin.delete(API, headers=CSRF).json() == {"cancelled": False}


def test_karten17_only_administrators_may(admin: TestClient) -> None:
    switch_on(admin)
    create_user(admin, "ann")
    login(admin, "ann", "another-long-password")
    assert post(admin, mode="translate", yaml="x").status_code == 403
    assert admin.delete(API, headers=CSRF).status_code == 403
    admin.post("/api/v1/auth/logout", headers=CSRF)
    assert post(admin, mode="translate", yaml="x").status_code == 401


@respx.mock
def test_karten17_ac2_the_probe_is_asked_and_only_its_shape_leaves(admin: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    switch_on(admin)
    sonarr = connection(admin)
    respx.get(f"{BASE}/api/v3/queue").mock(return_value=httpx.Response(200, json=ANSWER))
    script = Script(card())
    monkeypatch.setattr(providers, "turn", script)
    answer = new_card(admin, sonarr)
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert body["ok"] is True and body["sent"] == {"values": False}
    assert body["summary"] == {"connection_kind": "sonarr", "path": "/api/v3/queue", "form": "list", "buttons": False, "requires": ["sonarr"], "paths": ["/api/v3/queue"], "methods": [], "asked": None}
    sent = script.sent()
    for secret in (SECRET_TEXT, str(SECRET_NUMBER), SECRET_KEY):
        assert secret not in sent
    # Nothing that names the connection or its credentials goes either.
    for name in ("svc.example.com", "My sonarr", "key-1", "8080"):
        assert name not in sent, name
    assert "records[0].title: string" in sent

    script = Script(card())
    monkeypatch.setattr(providers, "turn", script)
    assert new_card(admin, sonarr, include_values=True).json()["sent"] == {"values": True}
    assert SECRET_TEXT in script.sent() and SECRET_KEY not in script.sent()


@respx.mock
def test_karten17_ec1_a_service_that_does_not_answer_is_told_and_the_provider_is_not_asked(admin: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    switch_on(admin)
    sonarr = connection(admin)
    respx.get(f"{BASE}/api/v3/queue").mock(side_effect=httpx.ConnectError("refused"))
    script = Script(card())
    monkeypatch.setattr(providers, "turn", script)
    answer = new_card(admin, sonarr)
    assert answer.status_code == 502 and answer.json()["detail"]["code"] == "unreachable"
    assert script.seen == []


def test_karten17_the_provider_fails_in_the_words_of_the_provider(admin: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    switch_on(admin)
    from .cards_sample import VALUE_CARD

    monkeypatch.setattr(providers, "turn", Script(providers.AssistantError("rate_limited", "busy", "Your credit balance is too low.")))
    limit = post(admin, mode="translate", yaml=VALUE_CARD)
    assert limit.status_code == 502 and limit.json()["detail"] == {"code": "ai_limit", "message": "Your credit balance is too low."}
    monkeypatch.setattr(providers, "turn", Script(providers.AssistantError("unreachable", "Anthropic could not be reached.")))
    assert post(admin, mode="translate", yaml=VALUE_CARD).json()["detail"]["code"] == "ai_unreachable"
    assert post(admin, mode="dance").json()["detail"]["code"] == "bad_request"
    assert post(admin, mode="new", description="x").json()["detail"]["code"] == "bad_request"


def _hanging(monkeypatch: pytest.MonkeyPatch) -> threading.Event:
    entered = threading.Event()

    async def hang(*_args: object) -> providers.Turn:
        entered.set()
        await asyncio.Event().wait()
        raise AssertionError

    monkeypatch.setattr(providers, "turn", hang)
    return entered


def _first_request(client: TestClient) -> tuple[threading.Thread, dict[str, httpx.Response]]:
    from .cards_sample import VALUE_CARD

    got: dict[str, httpx.Response] = {}

    def go() -> None:
        got["answer"] = post(client, mode="translate", yaml=VALUE_CARD)

    thread = threading.Thread(target=go)
    thread.start()
    return thread, got


def test_karten17_ac8_a_second_request_waits_and_cancel_ends_the_first(admin: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    switch_on(admin)
    entered = _hanging(monkeypatch)
    thread, got = _first_request(admin)
    assert entered.wait(15), "the first request reached the provider"
    from .cards_sample import VALUE_CARD

    second = post(admin, mode="translate", yaml=VALUE_CARD)
    assert second.status_code == 409 and second.json()["detail"]["code"] == "ai_busy"
    assert admin.delete(API, headers=CSRF).json() == {"cancelled": True}
    thread.join(15)
    assert got["answer"].status_code == 409 and got["answer"].json()["detail"]["code"] == "ai_cancelled"
    assert ai.RUNNING == {}, "the next one may go"


def test_karten17_ec6_taking_the_provider_away_ends_the_request_that_waits_for_it(admin: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    switch_on(admin)
    entered = _hanging(monkeypatch)
    thread, got = _first_request(admin)
    assert entered.wait(15)
    assert admin.put("/api/v1/settings/assistant", json={"provider": "off"}, headers=CSRF).status_code == 200
    thread.join(15)
    assert got["answer"].status_code == 409 and got["answer"].json()["detail"]["code"] == "assistant_off"
    assert ai.RUNNING == {}


def test_karten17_a_card_is_never_called_ai(admin: TestClient) -> None:
    """The address ``/cards/ai`` is the help, so no card may carry that short name."""
    from .cards_sample import VALUE_CARD, changed

    as_admin(admin)
    refused = admin.post("/api/v1/cards", json={"yaml": changed("slug: queue-size", "slug: ai", VALUE_CARD)}, headers=CSRF)
    assert refused.status_code == 400
