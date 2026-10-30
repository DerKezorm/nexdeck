"""B3 of the second security review: every question the card help puts to a service leaves a line in the chronicle.

The editor's first question, the chat's draft and the check of a proposal, also when the question failed (level warn, with
the code, never the answer). No real provider (``Script``), no real service (respx).
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.cards import ai
from app.services.assistant import providers
from app.services.collector import collector
from tests.conftest import CSRF, client, data_dir, setup_admin  # noqa: F401 - the fixtures
from tests.test_cards_ai import ANSWER, Script, card
from tests.test_cards_ai_routes import switch_on
from tests.test_cards_router import BASE, connection

BROKEN = ai.EXAMPLE.replace("form: list", "form: carousel")


@pytest.fixture
def admin(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> TestClient:  # noqa: F811
    setup_admin(client)
    monkeypatch.setattr(collector, "running", False)
    switch_on(client)
    return client


@pytest.fixture
def svc() -> Any:
    with respx.mock(assert_all_called=False) as router:
        yield router


def probes(admin: TestClient) -> list[dict[str, Any]]:
    return [line for line in admin.get("/api/v1/chronicle").json()["events"] if line["kind"] == "card_probe"]


def chat(admin: TestClient, monkeypatch: pytest.MonkeyPatch, *after: providers.Turn) -> None:
    call = {"id": "toolu_1", "name": "draft_card", "input": {"description": "my queue", "service": "sonarr", "path": "/api/v3/queue"}}
    monkeypatch.setattr(providers, "turn", Script(providers.Turn(text="", calls=[call], stop="tools"), *after))
    assert admin.post("/api/v1/assistant/chat", json={"text": "Build me a card that shows my queue"}, headers=CSRF).status_code == 200


def test_karten8t_b3_the_chat_draft_writes_a_line_even_when_the_card_never_passes(admin: TestClient, monkeypatch: pytest.MonkeyPatch, svc: Any) -> None:
    connection(admin, "sonarr")
    queue = svc.get(f"{BASE}/api/v3/queue").mock(return_value=httpx.Response(200, json=ANSWER))
    chat(admin, monkeypatch, card(BROKEN), card(BROKEN), providers.Turn(text="No."))
    assert queue.call_count == 1
    lines = probes(admin)
    assert len(lines) == 1 and lines[0]["name"] == "My sonarr" and lines[0]["level"] == "info"
    assert lines[0]["detail"] == "/api/v3/queue (card help, chat)"
    assert "Zq-Marker-Alpha" not in str(lines)


def test_karten8t_b3_a_chat_draft_whose_question_failed_writes_a_warning(admin: TestClient, monkeypatch: pytest.MonkeyPatch, svc: Any) -> None:
    connection(admin, "sonarr")
    svc.get(f"{BASE}/api/v3/queue").mock(return_value=httpx.Response(404, json={"message": "NotFound"}))
    chat(admin, monkeypatch, providers.Turn(text="It failed."))
    lines = probes(admin)
    assert len(lines) == 1 and lines[0]["level"] == "warn" and lines[0]["detail"] == "[http_error] /api/v3/queue (card help, chat)"


def test_karten8t_b3_the_editor_writes_a_line_when_its_first_question_fails(admin: TestClient, monkeypatch: pytest.MonkeyPatch, svc: Any) -> None:
    sonarr = connection(admin, "sonarr")
    missing = svc.get(f"{BASE}/api/v3/nothing").mock(return_value=httpx.Response(404, json={"message": "NotFound"}))
    monkeypatch.setattr(providers, "turn", Script(card()))
    answer = admin.post("/api/v1/cards/ai", json={"mode": "new", "description": "x", "connection_id": sonarr, "path": "/api/v3/nothing"}, headers=CSRF)
    assert answer.status_code >= 400 and missing.call_count == 1
    lines = probes(admin)
    assert len(lines) == 1 and lines[0]["level"] == "warn" and lines[0]["detail"] == "[http_error] /api/v3/nothing (card help)"


def test_karten8t_b3_the_check_of_a_proposal_says_which_of_its_questions_failed(admin: TestClient, monkeypatch: pytest.MonkeyPatch, svc: Any) -> None:
    # A path the cards of the kind read (/api/v3/series): since B1 of the review of 1.0.2 nothing else is asked on its own.
    connection(admin, "sonarr")
    svc.get(f"{BASE}/api/v3/series").mock(return_value=httpx.Response(404, json={"message": "NotFound"}))
    wrong = card(ai.EXAMPLE.replace("path: /api/v3/queue", "path: /api/v3/series"))
    monkeypatch.setattr(providers, "turn", Script(wrong, wrong))
    admin.post("/api/v1/cards/ai", json={"mode": "change", "description": "Show it", "yaml": ai.EXAMPLE}, headers=CSRF)
    checks = [line for line in probes(admin) if line["detail"].endswith("(card help, check)")]
    assert checks and all(line["level"] == "warn" and line["detail"].startswith("[http_error] /api/v3/series") for line in checks)
