"""B1 of a review of 1.0.2: a GET that acts is no read, and the card help asks only what the administrator named.

Watchtower starts an update run with ``GET /v1/update``, ntfy publishes with ``GET /<topic>/publish``. The kinds whose
documentation knows a GET that acts list what a card may ask (``raw_read_commands``), and a card with such a request is
refused when it is checked. The card help asks on its own only paths the administrator named or that nexdeck's own cards
of the kind read; any other path of a proposal waits for the preview with real data (``summary.unasked``). In the chat a
path nexdeck's own cards do not read is not asked at all.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.adapters import get_adapter
from app.adapters.base import AdapterError
from app.adapters.rawread import refuse_a_command
from app.cards import ai, card_reads, load
from app.services.assistant import providers
from app.services.collector import collector

from .conftest import CSRF, setup_admin
from .test_cards_ai import Script, card
from .test_cards_ai_routes import switch_on

BASE = "http://svc.example.com:8080"

#: Kind -> (requests that act, requests that read). Each list with its source in the adapter's comment.
BY_KIND: dict[str, tuple[list[str], list[str]]] = {
    "watchtower": (["/v1/update", "/v1/update?async=true", "/"], ["/v1/status", "/v1/metrics"]),
    "ntfy": (
        ["/alerts/publish?message=x", "/alerts/send?m=x", "/alerts/trigger", "/alerts/json?poll=1&email=someone@example.com",
         "/alerts/json?poll=1&call=yes", "/alerts/json?poll=1&delay=1h"],
        ["/alerts/json?poll=1&since=12h", "/alerts/json?poll=1&message=disk&priority=5&tags=warning", "/v1/health"],
    ),
    "cup": (["/api/v3/refresh"], ["/api/v3/json"]),
    "m3ueditor": (["/playlist/0d4c/sync", "/epg/0d4c/sync"], ["/user/playlists", "/user/epgs"]),
    "changedetection": (
        ["/api/v1/watch?recheck_all=1", "/api/v1/watch/0d4c?recheck=1", "/api/v1/watch/0d4c?paused=paused", "/api/v1/watch/0d4c?muted=muted"],
        ["/api/v1/watch", "/api/v1/watch?tag=web", "/api/v1/watch/0d4c", "/api/v1/systeminfo"],
    ),
    "healthchecks": (["/ping/0d4c", "/ping/0d4c/fail", "/ping/key/backup/start"], ["/api/v3/checks/", "/api/v3/checks/0d4c/pings/"]),
    "uptimekuma": (["/api/push/abc?status=up&msg=OK"], ["/api/status-page/heartbeat/main", "/metrics"]),
    "n8n": (["/webhook/deploy", "/webhook-test/deploy", "/webhook-waiting/12"], ["/api/v1/workflows?limit=250", "/api/v1/executions?limit=100"]),
    "elasticsearch": (["/logs/_refresh", "/_refresh", "/logs/_flush"], ["/_cluster/health", "/_cat/indices?format=json"]),
    "goatcounter": (["/count?p=/blog"], ["/api/v0/stats/total", "/api/v0/stats/hits?limit=5"]),
}


@pytest.mark.parametrize("kind", sorted(BY_KIND))
def test_karten8u_b1_a_get_that_acts_is_refused_and_a_read_goes_through(kind: str) -> None:
    acting, reading = BY_KIND[kind]
    adapter = get_adapter(kind)
    for path in acting:
        with pytest.raises(AdapterError) as refused:
            refuse_a_command(adapter, path)
        assert refused.value.code == "command_refused", path
    for path in reading:
        refuse_a_command(adapter, path)


def test_karten8u_b1_what_nexdecks_own_cards_read_stays_allowed() -> None:
    for kind in BY_KIND:
        adapter = get_adapter(kind)
        for read in card_reads.reads_of(kind):
            refuse_a_command(adapter, read["path"].replace("{topic}", "alerts").replace("{tag}", "web").replace("{status_page}", "main"))


WATCHTOWER_CARD = """\
nexdeck-card: 1
slug: update-state
name: {en: Update state}
version: 1.0.0
requires: [watchtower]
requests:
  - id: state
    path: /v1/update
form: value
value: {path: "@", label: State}
"""

NTFY_CARD = """\
nexdeck-card: 1
slug: topic-state
name: {en: Topic state}
version: 1.0.0
requires: [ntfy]
requests:
  - id: state
    path: /alerts/publish?message=Your%20NAS%20was%20wiped&priority=5&email=someone@example.com
form: value
value: {path: "@", label: State}
"""


@pytest.mark.parametrize("text", [WATCHTOWER_CARD, NTFY_CARD], ids=["watchtower", "ntfy"])
def test_karten8u_b1_checking_the_card_refuses_the_get_that_acts(text: str) -> None:
    """The probe of the review, turned round: the check (editor, import, shop) no longer takes it."""
    with pytest.raises(load.CardInvalid) as invalid:
        load.load_definition(text)
    assert [one.code for one in invalid.value.problems] == ["card_request_acts"]
    assert invalid.value.problems[0].path == "requests[0].path"


def test_karten8u_b1_a_path_nexdecks_own_cards_read_is_known_with_its_placeholders() -> None:
    assert card_reads.read_by_own_cards("ntfy", "/alerts/json?poll=1&since=12h")
    assert card_reads.read_by_own_cards("watchtower", "/v1/status")
    assert not card_reads.read_by_own_cards("watchtower", "/v1/update")
    assert not card_reads.read_by_own_cards("ntfy", "/alerts/json/../publish?poll=1&since=12h")
    assert not card_reads.read_by_own_cards("ntfy", "/alerts/publish?poll=1&since=12h")


@pytest.fixture
def admin(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    setup_admin(client)
    monkeypatch.setattr(collector, "running", False)
    switch_on(client)
    return client


def connect(client: TestClient, kind: str, config: dict[str, Any]) -> int:
    made = client.post("/api/v1/integrations", json={"kind": kind, "name": f"My {kind}", "config": {"url": BASE, **config}}, headers=CSRF)
    assert made.status_code == 201, made.text
    return int(made.json()["id"])


def proposal(path: str) -> str:
    """A card for "change a card": the slug of the example, read through Watchtower at ``path``."""
    return WATCHTOWER_CARD.replace("slug: update-state", "slug: download-queue").replace("/v1/update", path)


def test_karten8u_b1_the_card_help_does_not_ask_a_path_nobody_named(admin: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """The provider (or an instruction in the text of a shop card) proposes a path: it is not asked before the administrator takes the card."""
    connect(admin, "watchtower", {"token": "wt-token-123456"})
    with respx.mock(assert_all_called=False) as svc:
        anything = svc.get(url__startswith=BASE).mock(return_value=httpx.Response(200, json={"ok": True}))
        monkeypatch.setattr(providers, "turn", Script(card(proposal("/v1/metrics")), card(proposal("/v1/metrics"))))
        answer = admin.post("/api/v1/cards/ai", json={"mode": "change", "description": "Make it nicer", "yaml": ai.EXAMPLE}, headers=CSRF)
    assert answer.status_code == 200, answer.text
    assert anything.call_count == 0
    assert answer.json()["ok"] is True
    assert answer.json()["summary"]["unasked"] == ["/v1/metrics"]


def test_karten8u_b1_probe_watchtower_update_is_not_asked_and_not_taken(admin: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    connect(admin, "watchtower", {"token": "wt-token-123456"})
    with respx.mock(assert_all_called=False) as svc:
        update = svc.get(f"{BASE}/v1/update").mock(return_value=httpx.Response(200, text="ok"))
        monkeypatch.setattr(providers, "turn", Script(card(proposal("/v1/update")), card(proposal("/v1/update"))))
        answer = admin.post("/api/v1/cards/ai", json={"mode": "change", "description": "Make it nicer", "yaml": ai.EXAMPLE}, headers=CSRF)
    assert answer.status_code == 200, answer.text
    assert update.call_count == 0
    assert answer.json()["ok"] is False  # the check refuses the request that acts


def test_karten8u_b1_a_path_nexdecks_own_cards_read_is_asked(admin: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    connect(admin, "watchtower", {"token": "wt-token-123456"})
    with respx.mock(assert_all_called=False) as svc:
        status = svc.get(f"{BASE}/v1/status").mock(return_value=httpx.Response(200, json={"state": "idle"}))
        monkeypatch.setattr(providers, "turn", Script(card(proposal("/v1/status")), card(proposal("/v1/status"))))
        answer = admin.post("/api/v1/cards/ai", json={"mode": "change", "description": "Make it nicer", "yaml": ai.EXAMPLE}, headers=CSRF)
    assert answer.status_code == 200, answer.text
    assert status.call_count >= 1
    assert answer.json()["summary"]["unasked"] == []


def test_karten8u_b1_a_path_of_the_card_in_the_editor_counts_as_named(admin: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    connect(admin, "watchtower", {"token": "wt-token-123456"})
    mine = proposal("/v1/metrics")
    with respx.mock(assert_all_called=False) as svc:
        metrics = svc.get(f"{BASE}/v1/metrics").mock(return_value=httpx.Response(200, json={"scanned": 3}))
        monkeypatch.setattr(providers, "turn", Script(card(mine), card(mine)))
        answer = admin.post("/api/v1/cards/ai", json={"mode": "change", "description": "Make it nicer", "yaml": mine}, headers=CSRF)
    assert answer.status_code == 200, answer.text
    assert metrics.call_count >= 1
    assert answer.json()["summary"]["unasked"] == []


def _chat(admin: TestClient, monkeypatch: pytest.MonkeyPatch, path: str) -> tuple[Any, list[Any]]:
    call = {"id": "toolu_1", "name": "draft_card", "input": {"description": "update state", "service": "watchtower", "path": path}}
    chat_turns = [providers.Turn(text="", calls=[call], stop="tools"), providers.Turn(text="Done.")]
    seen: list[Any] = []

    async def turn(settings: Any, key: str, system: str, transcript: Any, tools: Any) -> providers.Turn:
        if system.startswith("You write cards"):
            return card(WATCHTOWER_CARD.replace("/v1/update", "/v1/status"))
        seen.append([dict(one) for one in transcript])
        return chat_turns.pop(0)

    monkeypatch.setattr(providers, "turn", turn)
    said = admin.post("/api/v1/assistant/chat", json={"text": "What does the log of my proxy say?"}, headers=CSRF)
    return said, seen


def test_karten8u_b1_in_the_chat_a_path_nexdecks_cards_do_not_read_is_not_asked(admin: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """The probe of the review, turned round: ``draft_card`` with ``/v1/update`` asks nothing and names the known paths."""
    connect(admin, "watchtower", {"token": "wt-token-123456"})
    with respx.mock(assert_all_called=False) as svc:
        anything = svc.get(url__startswith=BASE).mock(return_value=httpx.Response(200, json={"ok": True}))
        said, seen = _chat(admin, monkeypatch, "/v1/update")
    assert said.status_code == 200, said.text
    assert anything.call_count == 0
    results = [result for entry in seen[-1] if entry.get("role") == "tool" for result in entry["results"]]
    told = json.loads(results[0]["content"])
    assert told["known_paths"] == ["/v1/status"]
    assert "probe" in told["error"]


def test_karten8u_b1_in_the_chat_a_path_nexdecks_cards_read_is_asked(admin: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    connect(admin, "watchtower", {"token": "wt-token-123456"})
    with respx.mock(assert_all_called=False) as svc:
        status = svc.get(f"{BASE}/v1/status").mock(return_value=httpx.Response(200, json={"state": "idle"}))
        said, _seen = _chat(admin, monkeypatch, "/v1/status")
    assert said.status_code == 200, said.text
    assert status.call_count >= 1
