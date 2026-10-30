"""B1 of the second security review: values go to the provider only for the one request the administrator agreed to.

The answer of a path the provider chose itself, or of a connection nobody picked, goes as its shape alone, whatever the tick
or the permission in the chat says. The check of a proposal asks the connection chosen in the editor (in the chat the one
the draft is for); only a card of another kind is asked of the first real connection of that kind, and the answer names it.
No real provider (``Script``), no real service (respx).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.cards import ai
from app.services.assistant import providers
from app.services.collector import collector
from tests.conftest import CSRF, client, data_dir, setup_admin  # noqa: F401 - the fixtures
from tests.test_cards_ai import ANSWER, CONFIG, SECRET_TEXT, Script, card
from tests.test_cards_ai_routes import switch_on
from tests.test_cards_router import BASE, connection

OTHER = "http://other.example.com:7878"
SERIES_SECRET = "Series-Secret-Zeta"
RADARR_SECRET = "Radarr-Secret-Omega"
SERIES = {"records": [{"title": SERIES_SECRET, "size": 3}]}
TO_RADARR = ai.EXAMPLE.replace("requires: [sonarr]", "requires: [radarr]").replace("path: /api/v3/queue", "path: /api/v3/movie")


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


def chat_turn(**given: Any) -> providers.Turn:
    call = {"id": "toolu_1", "name": "draft_card", "input": {"description": "my queue", **given}}
    return providers.Turn(text="", calls=[call], stop="tools")


def chat(admin: TestClient, **more: Any) -> dict[str, Any]:
    answer = admin.post("/api/v1/assistant/chat", json={"text": "Build me a card that shows my queue", **more}, headers=CSRF)
    assert answer.status_code == 200, answer.text
    return answer.json()


def test_karten8t_b1_unseen_answers_go_as_shapes_without_values_even_with_the_tick(monkeypatch: pytest.MonkeyPatch) -> None:
    series = card(ai.EXAMPLE.replace("path: /api/v3/queue", "path: /api/v3/series"))

    async def verify(definition: Any) -> ai.Checked:
        return ai.Checked([], {request.id: SERIES for request in definition.requests})

    script = Script(series, series)
    monkeypatch.setattr(providers, "turn", script)
    asked = ai.Ask(mode="new", description="Show my queue", connection_kind="sonarr", path="/api/v3/queue", answer=ANSWER, include_values=True)
    outcome = asyncio.run(ai.generate(asked, CONFIG, "key", verify))
    assert outcome.ok and len(script.seen) == 2
    # The request agreed to goes with its values; the one the provider chose goes as a shape.
    assert SECRET_TEXT in script.seen[0]["transcript"][0]["text"]
    shapes = json.dumps(script.seen[1]["transcript"][-1])
    assert "At /api/v3/series the service answered, as paths and types (no values)" in shapes and "records[0].title: string" in shapes
    assert SERIES_SECRET not in script.sent()
    assert outcome.summary["asked"] is None


def test_karten8t_b1_the_chat_permission_for_one_path_carries_no_values_of_another(admin: TestClient, monkeypatch: pytest.MonkeyPatch, svc: Any) -> None:
    connection(admin, "sonarr")
    svc.get(f"{BASE}/api/v3/queue").mock(return_value=httpx.Response(200, json=ANSWER))
    series = svc.get(f"{BASE}/api/v3/series").mock(return_value=httpx.Response(200, json=SERIES))
    wish = chat_turn(service="sonarr", path="/api/v3/queue", with_values=True)
    monkeypatch.setattr(providers, "turn", Script(wish, providers.Turn(text="May I?")))
    first = chat(admin)
    grant = first["permissions"][0]["grant"]
    assert admin.post(f"/api/v1/assistant/conversations/{first['conversation_id']}/allow", json={"grant": grant}, headers=CSRF).status_code == 200

    other = card(ai.EXAMPLE.replace("path: /api/v3/queue", "path: /api/v3/series"))
    script = Script(wish, other, other, providers.Turn(text="Done."))
    monkeypatch.setattr(providers, "turn", script)
    done = chat(admin, conversation_id=first["conversation_id"])
    assert series.call_count >= 1 and done["drafts"]
    assert SECRET_TEXT in script.sent(), "the values of the path agreed to went along"
    assert SERIES_SECRET not in script.sent()
    assert done["drafts"][0]["summary"]["asked"] is None, "the connection of the draft was asked"


def test_karten8t_b1_the_editor_asks_another_connection_only_for_another_kind_without_values_and_names_it(admin: TestClient, monkeypatch: pytest.MonkeyPatch, svc: Any) -> None:
    sonarr = connection(admin, "sonarr")
    connection(admin, "radarr", name="Film shelf", config={"url": OTHER, "api_key": "key-2"})
    svc.get(f"{BASE}/api/v3/queue").mock(return_value=httpx.Response(200, json=ANSWER))
    movies = svc.get(f"{OTHER}/api/v3/movie").mock(return_value=httpx.Response(200, json={"records": [{"title": RADARR_SECRET, "size": 1}]}))
    script = Script(card(TO_RADARR), card(TO_RADARR))
    monkeypatch.setattr(providers, "turn", script)
    body = {"mode": "change", "description": "Show it", "yaml": ai.EXAMPLE, "connection_id": sonarr, "path": "/api/v3/queue", "include_values": True}
    answer = admin.post("/api/v1/cards/ai", json=body, headers=CSRF)
    assert answer.status_code == 200, answer.text
    assert movies.call_count >= 1
    assert RADARR_SECRET not in script.sent() and "records[0].title: string" in json.dumps(script.seen[1]["transcript"][-1])
    assert answer.json()["summary"]["asked"] == {"name": "Film shelf", "kind": "radarr"}


def test_karten8t_b1_the_editor_asks_the_chosen_connection_first_and_names_none(admin: TestClient, monkeypatch: pytest.MonkeyPatch, svc: Any) -> None:
    connection(admin, "sonarr")
    chosen = connection(admin, "sonarr", name="Second sonarr", config={"url": OTHER, "api_key": "key-2"})
    first = svc.get(f"{BASE}/api/v3/queue").mock(return_value=httpx.Response(200, json=ANSWER))
    second = svc.get(f"{OTHER}/api/v3/queue").mock(return_value=httpx.Response(200, json=ANSWER))
    monkeypatch.setattr(providers, "turn", Script(card(), card()))
    answer = admin.post("/api/v1/cards/ai", json={"mode": "new", "description": "Show it", "connection_id": chosen, "path": "/api/v3/queue"}, headers=CSRF)
    assert answer.status_code == 200, answer.text
    assert first.call_count == 0 and second.call_count >= 1
    assert answer.json()["summary"]["asked"] is None
