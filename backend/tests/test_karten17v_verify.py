"""The card help checks its proposal against the service before it is shown (found in a real run on 1.0.0, 29.10.2026).

Asked "how many episodes are missing in nexcrate", the provider wrote Sonarr's ``/api/v3/wanted/missing``: a valid card
that nexcrate answers with 404, so the preview failed only once it was taken over. Now the provider is shown the paths
nexdeck's own cards read from the kind, and a proposal is asked of a real connection of its kind: a path the service does
not answer goes back once, with those paths. A service that is down says nothing about the card.

⚠️ No real provider is asked (``Script``), and the service is a stand-in (respx).
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
from app.cards.load import Problem
from app.services.assistant import providers

from .conftest import CSRF
from .test_cards_ai import ANSWER, CONFIG, Script, card
from .test_cards_ai_routes import admin, switch_on  # noqa: F401 - the fixture
from .test_cards_router import BASE, connection

WRONG = "/api/v3/wanted/missing?pageSize=50"
RIGHT = "/api/v3/queue"


def proposing(path: str) -> providers.Turn:
    return card(ai.EXAMPLE.replace("path: /api/v3/queue", f"path: {path}"))


def test_karten17v_the_provider_is_shown_the_paths_nexdeck_reads_from_the_kind() -> None:
    sent = ai.outbound(ai.Ask(mode="new", description="Show my queue", connection_kind="sonarr", path=RIGHT, answer=ANSWER)).message
    assert "Paths nexdeck's own cards read from sonarr" in sent
    assert "- /api/v3/queue?pageSize=100&includeUnknownMovieItems=true" in sent and "- /api/v3/series" in sent
    assert "Never take a path from another service" in ai.outbound(ai.Ask(mode="change", yaml=ai.EXAMPLE)).system
    # A translation keeps every path, and a kind nexdeck knows nothing of has nothing to show.
    assert "Paths nexdeck's own cards" not in ai.outbound(ai.Ask(mode="translate", yaml=ai.EXAMPLE, connection_kind="sonarr")).message
    assert "Paths nexdeck's own cards" not in ai.outbound(ai.Ask(mode="change", yaml=ai.EXAMPLE, connection_kind="custom:mine")).message


def test_karten17v_a_path_the_service_does_not_answer_goes_back_once_with_the_known_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    asked: list[list[str]] = []

    async def verify(definition: Any) -> list[Problem]:
        paths = [request.path for request in definition.requests]
        asked.append(paths)
        return [Problem(ai.PATH_FAILED, f"The service did not answer {path}.", params={"path": path, "failure": "http_error"}) for path in paths if path != RIGHT]

    script = Script(proposing(WRONG), proposing(RIGHT))
    monkeypatch.setattr(providers, "turn", script)
    result = asyncio.run(ai.generate(ai.Ask(mode="change", description="How many are missing", yaml=ai.EXAMPLE), CONFIG, "key", verify))
    assert result.ok and result.summary["paths"] == [RIGHT]
    assert asked == [[WRONG], [RIGHT]]
    again = json.dumps(script.seen[1]["transcript"][-1])
    assert f"The service did not answer {WRONG}." in again and "Paths nexdeck's own cards read from sonarr" in again and "/api/v3/series" in again

    # Wrong twice: shown with the problem and its blanks, nothing taken over without the administrator.
    monkeypatch.setattr(providers, "turn", Script(proposing(WRONG), proposing(WRONG)))
    result = asyncio.run(ai.generate(ai.Ask(mode="change", description="How many are missing", yaml=ai.EXAMPLE), CONFIG, "key", verify))
    assert not result.ok and [problem["code"] for problem in result.problems] == [ai.PATH_FAILED]
    assert result.problems[0]["params"] == {"path": WRONG, "failure": "http_error"}

    # A translation is not asked of the service.
    asked.clear()
    monkeypatch.setattr(providers, "turn", Script(card()))
    assert asyncio.run(ai.generate(ai.Ask(mode="translate", yaml=ai.EXAMPLE), CONFIG, "key", verify)).ok and asked == []


@respx.mock
def test_karten17v_the_route_asks_a_real_connection_of_the_kind_even_when_the_editor_named_none(admin: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    switch_on(admin)
    connection(admin)
    wrong = respx.get(f"{BASE}/api/v3/wanted/missing").mock(return_value=httpx.Response(404, json={"message": "NotFound"}))
    right = respx.get(f"{BASE}{RIGHT}").mock(return_value=httpx.Response(200, json=ANSWER))
    script = Script(proposing(WRONG), proposing(RIGHT))
    monkeypatch.setattr(providers, "turn", script)
    # As in the real run: "Ask AI" on an empty new card, no service and no connection chosen, so the text goes as a change.
    answer = admin.post("/api/v1/cards/ai", json={"mode": "change", "description": "How many are missing", "yaml": ai.EXAMPLE}, headers=CSRF)
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert body["ok"] is True and body["summary"]["paths"] == [RIGHT]
    assert wrong.call_count == 1 and right.call_count == 1
    assert "HTTP 404" in json.dumps(script.seen[1]["transcript"][-1])
    # Nothing of the service's answers went to the provider, only which path failed.
    assert "NotFound" not in script.sent() and "svc.example.com" not in script.sent()
    lines = admin.get("/api/v1/chronicle").json()["events"]
    assert any(line["kind"] == "card_probe" and "(card help, check)" in json.dumps(line) for line in lines)


@respx.mock
def test_karten17v_a_service_that_is_down_holds_nothing_against_the_card(admin: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    switch_on(admin)
    connection(admin)
    respx.get(f"{BASE}{RIGHT}").mock(side_effect=httpx.ConnectError("down"))
    monkeypatch.setattr(providers, "turn", Script(proposing(RIGHT)))
    body = admin.post("/api/v1/cards/ai", json={"mode": "change", "description": "Show my queue", "yaml": ai.EXAMPLE}, headers=CSRF).json()
    assert body["ok"] is True


def test_karten17v_without_a_connection_of_the_kind_nothing_is_asked(admin: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    switch_on(admin)
    connection(admin, kind="radarr")
    with respx.mock(assert_all_called=False) as stand_in:
        monkeypatch.setattr(providers, "turn", Script(proposing(WRONG)))
        body = admin.post("/api/v1/cards/ai", json={"mode": "change", "description": "Show my queue", "yaml": ai.EXAMPLE}, headers=CSRF).json()
        assert body["ok"] is True and stand_in.calls.call_count == 0


@respx.mock
def test_karten17v_the_connection_chosen_in_the_editor_is_asked_before_the_first_of_its_kind(admin: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    switch_on(admin)
    connection(admin)
    other = "http://second.example.com:8989"
    chosen = connection(admin, config={"url": other, "api_key": "key-2"})
    first = respx.get(f"{BASE}{RIGHT}").mock(return_value=httpx.Response(200, json=ANSWER))
    second = respx.get(f"{other}{RIGHT}").mock(return_value=httpx.Response(200, json=ANSWER))
    monkeypatch.setattr(providers, "turn", Script(proposing(RIGHT)))
    body = admin.post("/api/v1/cards/ai", json={"mode": "change", "description": "Show my queue", "yaml": ai.EXAMPLE, "connection_id": chosen}, headers=CSRF).json()
    assert body["ok"] is True and second.call_count == 1 and first.call_count == 0
