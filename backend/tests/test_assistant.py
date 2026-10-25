"""The assistant (roadmap M3, 25.10.2026): administrators ask, tools read, buttons are proposed, never pressed.

⚠️ Nothing here asks a real provider. The chat loop runs against scripted
turns, the OpenAI form against respx, and Claude's SDK against a server of
the test's own on 127.0.0.1, which also shows what the SDK really sends.
"""

from __future__ import annotations

import json
import threading
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.adapters.base import WidgetData
from app.db import db_session
from app.models import ActionLog, Conversation, ConversationTurn, HealthCheck, utcnow
from app.services import retention
from app.services.assistant import chat, providers
from app.services.collector import collector
from app.services.state import live

from .conftest import CSRF, create_user, login, setup_admin


def _board(client: TestClient, name: str = "Lab") -> dict:
    response = client.post("/api/v1/boards", json={"name": name}, headers=CSRF)
    assert response.status_code == 201, response.text
    return response.json()


def _card(client: TestClient, page_id: int, kind: str, integration: str | None = None, **extra: object) -> dict:
    body: dict[str, Any] = {"kind": kind, **extra}
    if integration:
        made = client.post("/api/v1/integrations", json={"kind": integration, "name": integration.title(), "config": {}, "demo": True}, headers=CSRF)
        assert made.status_code == 201, made.text
        body["integration_id"] = made.json()["id"]
    response = client.post(f"/api/v1/pages/{page_id}/widgets", json=body, headers=CSRF)
    assert response.status_code == 201, response.text
    widget = response.json()["widget"]
    collector.unschedule(widget["id"])
    return widget


def _switch_on(client: TestClient) -> None:
    response = client.put("/api/v1/settings/assistant", json={"provider": "anthropic", "model": "", "key": "sk-ant-test"}, headers=CSRF)
    assert response.status_code == 200, response.text
    assert response.json()["ready"] is True


class Script:
    """Scripted provider turns, and what the loop sent each time."""

    def __init__(self, *turns: providers.Turn) -> None:
        self.turns = list(turns)
        self.seen: list[list[dict[str, Any]]] = []
        self.systems: list[str] = []

    async def __call__(self, settings: dict, key: str, system: str, transcript: list[dict], tools: list[dict]) -> providers.Turn:
        self.seen.append([dict(entry) for entry in transcript])
        self.systems.append(system)
        return self.turns.pop(0) if self.turns else providers.Turn(text="Done.")


def _call(name: str, number: int = 1, **given: object) -> dict:
    return {"id": f"toolu_{number}", "name": name, "input": given}


# -- the setting ---------------------------------------------------------------------------


def test_the_assistant_is_off_until_an_administrator_chooses_a_provider(client: TestClient) -> None:
    setup_admin(client)
    assert client.get("/api/v1/settings/assistant").json() == {
        "provider": "off", "base_url": "", "model": "", "has_key": False, "ready": False, "leaves_the_house": False,
    }
    refused = client.post("/api/v1/assistant/chat", json={"text": "Is anything wrong?"}, headers=CSRF)
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "off"


def test_the_key_is_kept_encrypted_and_never_comes_back(client: TestClient) -> None:
    setup_admin(client)
    _switch_on(client)
    shown = client.get("/api/v1/settings/assistant").json()
    assert shown["model"] == "claude-sonnet-5-5" and shown["has_key"] is True and shown["leaves_the_house"] is True
    assert "sk-ant-test" not in json.dumps(shown)
    with db_session() as db:
        from app.models import Setting

        stored = db.get(Setting, "assistant").value
    assert "sk-ant-test" not in json.dumps(stored), "the key lies encrypted in the database"
    # Left out, the key stays; empty, it goes.
    client.put("/api/v1/settings/assistant", json={"provider": "anthropic", "model": "claude-sonnet-5-5"}, headers=CSRF)
    assert client.get("/api/v1/settings/assistant").json()["has_key"] is True
    client.put("/api/v1/settings/assistant", json={"provider": "anthropic", "model": "claude-sonnet-5-5", "key": ""}, headers=CSRF)
    assert client.get("/api/v1/settings/assistant").json() | {} == {
        "provider": "anthropic", "base_url": "", "model": "claude-sonnet-5-5", "has_key": False, "ready": False, "leaves_the_house": True,
    }


@pytest.mark.parametrize(("address", "leaves"), [
    ("http://ollama:11434/v1", False), ("http://10.0.0.5:11434/v1", False), ("http://llm.home.arpa/v1", False),
    ("https://api.openai.com/v1", True), ("https://openrouter.ai/api/v1", True), ("http://9.9.9.9/v1", True),
])
def test_a_local_runner_keeps_the_questions_in_the_house(client: TestClient, address: str, leaves: bool) -> None:
    setup_admin(client)
    response = client.put("/api/v1/settings/assistant", json={"provider": "openai", "base_url": address, "model": "qwen3:14b"}, headers=CSRF)
    assert response.status_code == 200, response.text
    assert response.json()["ready"] is True, "Ollama needs no key"
    assert response.json()["leaves_the_house"] is leaves


def test_an_openai_shaped_service_needs_its_address(client: TestClient) -> None:
    setup_admin(client)
    missing = client.put("/api/v1/settings/assistant", json={"provider": "openai", "model": "qwen3"}, headers=CSRF)
    assert missing.status_code == 400 and missing.json()["detail"]["code"] == "missing_address"
    wrong = client.put("/api/v1/settings/assistant", json={"provider": "openai", "base_url": "ollama:11434", "model": "qwen3"}, headers=CSRF)
    assert wrong.json()["detail"]["code"] == "bad_address"
    unknown = client.put("/api/v1/settings/assistant", json={"provider": "gemini", "model": "x"}, headers=CSRF)
    assert unknown.json()["detail"]["code"] == "bad_provider"


def test_members_reach_none_of_it(client: TestClient) -> None:
    setup_admin(client)
    _switch_on(client)
    create_user(client, "member")
    login(client, "member", "another-long-password")
    for method, path, body in (
        ("get", "/api/v1/settings/assistant", None), ("put", "/api/v1/settings/assistant", {"provider": "off"}),
        ("post", "/api/v1/settings/assistant/test", None), ("get", "/api/v1/assistant", None),
        ("get", "/api/v1/assistant/conversations", None), ("post", "/api/v1/assistant/chat", {"text": "hi"}),
    ):
        response = client.request(method.upper(), path, json=body, headers=CSRF)
        assert response.status_code == 403, (path, response.text)


# -- the loop --------------------------------------------------------------------------------


def test_an_answer_looks_things_up_and_cites_the_cards_it_read(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    setup_admin(client)
    _switch_on(client)
    board = _board(client)
    nas = _card(client, board["pages"][0]["id"], "core.clock", title="Synology")
    live.set(nas["id"], WidgetData(status="warn", meta={"status_reason": "Volume 1 is 91 % full"}))
    script = Script(
        providers.Turn(text="", calls=[_call("needs_attention")], stop="tools"),
        providers.Turn(text="**Synology** is yellow: volume 1 is 91 % full.", stop="end"),
    )
    monkeypatch.setattr(providers, "turn", script)

    answer = client.post("/api/v1/assistant/chat", json={"text": "Is anything wrong?"}, headers=CSRF)
    assert answer.status_code == 200, answer.text
    reply = answer.json()
    assert reply["text"].startswith("**Synology** is yellow")
    assert reply["citations"] == [{"label": "Synology", "target": {"board": board["slug"], "page": board["pages"][0]["slug"], "widget": nas["id"]}}]
    assert reply["proposals"] == [] and reply["permissions"] == [] and reply["refused"] is False
    # The second turn saw what the tool found.
    result = json.loads(script.seen[1][-1]["results"][0]["content"])
    assert result["cards"][0]["reason"] == "Volume 1 is 91 % full" and result["cards"][0]["colour"] == "yellow"
    assert "Answer in English." in script.systems[0]

    # The chat shows it again: questions and answers, no tool traffic.
    shown = client.get(f"/api/v1/assistant/conversations/{reply['conversation_id']}").json()
    assert [turn["me"] for turn in shown["turns"]] == [True, False]
    assert shown["turns"][1]["citations"] == reply["citations"]
    assert client.get("/api/v1/assistant/conversations").json()[0]["title"] == "Is anything wrong?"


def test_a_second_question_carries_the_conversation_along(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    setup_admin(client)
    _switch_on(client)
    script = Script(providers.Turn(text="All green."), providers.Turn(text="Still green."))
    monkeypatch.setattr(providers, "turn", script)
    first = client.post("/api/v1/assistant/chat", json={"text": "Anything wrong?"}, headers=CSRF).json()
    client.post("/api/v1/assistant/chat", json={"text": "And now?", "conversation_id": first["conversation_id"]}, headers=CSRF)
    assert [(entry["role"], entry.get("text")) for entry in script.seen[1]] == [
        ("user", "Anything wrong?"), ("assistant", "All green."), ("answer", "All green."), ("user", "And now?"),
    ]


def test_a_conversation_of_somebody_else_cannot_be_continued(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    setup_admin(client)
    _switch_on(client)
    monkeypatch.setattr(providers, "turn", Script(providers.Turn(text="Hello.")))
    mine = client.post("/api/v1/assistant/chat", json={"text": "Hello"}, headers=CSRF).json()
    create_user(client, "second", role="admin")
    login(client, "second", "another-long-password")
    assert client.get(f"/api/v1/assistant/conversations/{mine['conversation_id']}").status_code == 404
    continued = client.post("/api/v1/assistant/chat", json={"text": "Hi", "conversation_id": mine["conversation_id"]}, headers=CSRF)
    assert continued.status_code == 404
    assert client.delete(f"/api/v1/assistant/conversations/{mine['conversation_id']}", headers=CSRF).status_code == 404


def test_a_model_that_keeps_calling_tools_is_stopped(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    setup_admin(client)
    _switch_on(client)
    script = Script(*[providers.Turn(text=f"Looking ({number}).", calls=[_call("find_cards", number)], stop="tools") for number in range(20)])
    monkeypatch.setattr(providers, "turn", script)
    reply = client.post("/api/v1/assistant/chat", json={"text": "Look at everything"}, headers=CSRF).json()
    assert len(script.seen) == chat.MAX_ROUNDS
    assert reply["text"] == f"Looking ({chat.MAX_ROUNDS - 1})."


def test_a_declined_answer_says_so(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    setup_admin(client)
    _switch_on(client)
    monkeypatch.setattr(providers, "turn", Script(providers.Turn(text="", stop="refusal")))
    reply = client.post("/api/v1/assistant/chat", json={"text": "Something odd"}, headers=CSRF).json()
    assert reply["refused"] is True and reply["text"] == ""


def test_a_provider_that_fails_is_named_and_the_question_stays(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    setup_admin(client)
    _switch_on(client)

    async def failing(*_args: object) -> providers.Turn:
        raise providers.AssistantError("auth", "Anthropic refused the key.")

    monkeypatch.setattr(providers, "turn", failing)
    answer = client.post("/api/v1/assistant/chat", json={"text": "Anything wrong?"}, headers=CSRF)
    assert answer.status_code == 502 and answer.json()["detail"] == {"code": "auth", "message": "Anthropic refused the key."}
    with db_session() as db:
        assert [turn.role for turn in db.scalars(select(ConversationTurn))] == ["user"]


def test_the_answer_is_in_the_language_of_the_person(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    setup_admin(client)
    _switch_on(client)
    assert client.patch("/api/v1/auth/me", json={"locale": "de"}, headers=CSRF).status_code == 200
    script = Script(providers.Turn(text="Alles grün."))
    monkeypatch.setattr(providers, "turn", script)
    client.post("/api/v1/assistant/chat", json={"text": "Alles gut?"}, headers=CSRF)
    assert "Answer in German." in script.systems[0]


def test_the_history_is_cut_only_before_a_question() -> None:
    entries = [{"role": "user", "text": "q"}, {"role": "assistant", "text": "", "calls": [_call("find_cards")]},
               {"role": "tool", "results": [{"id": "toolu_1", "content": "{}"}]}, {"role": "assistant", "text": "a"}] * 20
    # One more, so the plain cut would land on a tool call and not on a question.
    entries.append({"role": "user", "text": "last"})

    class Fake:
        id = 1

    class Rows:
        def scalars(self, _statement: object) -> list:
            return [ConversationTurn(role=entry["role"], content={k: v for k, v in entry.items() if k != "role"}, provider="anthropic") for entry in entries]

    kept = chat.transcript(Rows(), Fake())  # type: ignore[arg-type]
    assert len(entries) - chat.MAX_HISTORY == 21 and entries[21]["role"] == "assistant"
    assert len(kept) <= chat.MAX_HISTORY and kept[0]["role"] == "user"


# -- proposing a button ----------------------------------------------------------------------


def _plex_and_docker(client: TestClient) -> tuple[dict, dict]:
    page = _board(client)["pages"][0]["id"]
    docker = _card(client, page, "docker.containers", "docker", title="Host")
    plex = _card(client, page, "plex.nowplaying", "plex", title="Plex")
    live.set(docker["id"], WidgetData(items=[
        {"id": "c1", "title": "plex", "subtitle": "Up 3 days", "state": "running",
         "actions": [{"id": "restart", "label": "Restart", "params": {"id": "c1"}}, {"id": "stop", "label": "Stop", "danger": True, "params": {"id": "c1"}}]},
        {"id": "c2", "title": "nginx", "subtitle": "Up 2 hours", "actions": [{"id": "restart", "label": "Restart", "params": {"id": "c2"}}]},
    ]))
    live.set(plex["id"], WidgetData(items=[
        {"title": "Dune", "subtitle": "Anna", "progress": 40}, {"title": "Severance", "subtitle": "Ben · Bedroom TV · 1080p · Transcode", "progress": 10},
        {"title": "Library scan"},
    ]))
    return docker, plex


def test_a_proposed_button_comes_with_what_it_would_hit_and_is_not_pressed(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    setup_admin(client)
    _switch_on(client)
    docker, _plex = _plex_and_docker(client)
    pressed: list[str] = []

    async def press(*_args: object, **_kwargs: object) -> str:
        pressed.append("yes")
        return "ran"

    monkeypatch.setattr(collector, "run_action", press)
    monkeypatch.setattr(providers, "turn", Script(
        providers.Turn(calls=[_call("propose_action", card_id=docker["id"], action="stop", params={"id": "c1"})], stop="tools"),
        providers.Turn(text="The button stops **plex**; two streams end."),
    ))
    reply = client.post("/api/v1/assistant/chat", json={"text": "Stop plex"}, headers=CSRF).json()
    assert pressed == [], "the assistant never presses a button"
    assert reply["proposals"] == [{
        "card_id": docker["id"], "card": "Host", "row": "plex", "action": "stop", "label": "Stop", "danger": True, "params": {"id": "c1"},
        "impact": [{"fact": "up", "text": "Up 3 days"}, {"fact": "streams", "count": 2, "names": ["Dune · Anna", "Severance · Ben"]}],
    }]


def test_a_button_the_card_does_not_offer_is_not_proposed(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    setup_admin(client)
    _switch_on(client)
    docker, _plex = _plex_and_docker(client)
    script = Script(
        providers.Turn(calls=[_call("propose_action", 1, card_id=docker["id"], action="stop", params={"id": "c2"}),
                              _call("propose_action", 2, card_id=docker["id"], action="remove", params={"id": "c1"})], stop="tools"),
        providers.Turn(text="I cannot offer that."),
    )
    monkeypatch.setattr(providers, "turn", script)
    reply = client.post("/api/v1/assistant/chat", json={"text": "Stop nginx and remove plex"}, headers=CSRF).json()
    assert reply["proposals"] == []
    assert [result["is_error"] for result in script.seen[1][-1]["results"]] == [True, True]


def test_the_impact_is_there_for_the_ordinary_button_too_and_a_press_from_the_chat_is_logged_as_such(client: TestClient) -> None:
    setup_admin(client)
    docker, _plex = _plex_and_docker(client)
    impact = client.post(f"/api/v1/widgets/{docker['id']}/actions/restart/impact", json={"params": {"id": "c1"}}, headers=CSRF)
    assert impact.status_code == 200, impact.text
    assert [fact["fact"] for fact in impact.json()["impact"]] == ["up", "streams"]
    nginx = client.post(f"/api/v1/widgets/{docker['id']}/actions/restart/impact", json={"params": {"id": "c2"}}, headers=CSRF)
    assert nginx.json()["impact"] == [{"fact": "up", "text": "Up 2 hours"}], "nginx serves no streams"
    refused = client.post(f"/api/v1/widgets/{docker['id']}/actions/remove/impact", json={"params": {"id": "c1"}}, headers=CSRF)
    assert refused.status_code == 400

    pressed = client.post(f"/api/v1/widgets/{docker['id']}/actions/restart", json={"params": {"id": "c1"}, "via": "assistant"}, headers=CSRF)
    assert pressed.status_code == 200, pressed.text
    with db_session() as db:
        assert db.scalar(select(ActionLog.actor)) == "admin (via assistant)"


def test_a_member_who_may_only_look_learns_no_impact(client: TestClient) -> None:
    setup_admin(client)
    docker, _plex = _plex_and_docker(client)
    create_user(client, "member")
    login(client, "member", "another-long-password")
    assert client.post(f"/api/v1/widgets/{docker['id']}/actions/restart/impact", json={"params": {"id": "c1"}}, headers=CSRF).status_code == 403


# -- logs only when allowed ---------------------------------------------------------------------


def test_a_log_is_read_only_after_the_person_allowed_it(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    setup_admin(client)
    _switch_on(client)
    docker, _plex = _plex_and_docker(client)
    script = Script(
        providers.Turn(calls=[_call("container_log", card_id=docker["id"], container="nginx")], stop="tools"),
        providers.Turn(text="May I read the log of **nginx**?"),
    )
    monkeypatch.setattr(providers, "turn", script)
    reply = client.post("/api/v1/assistant/chat", json={"text": "Why does nginx restart?"}, headers=CSRF).json()
    grant = f"log:{docker['integration_id']}:nginx"
    assert reply["permissions"] == [{"kind": "log", "card_id": docker["id"], "container": "nginx", "grant": grant}]
    assert json.loads(script.seen[1][-1]["results"][0]["content"])["asked"] is True

    allowed = client.post(f"/api/v1/assistant/conversations/{reply['conversation_id']}/allow", json={"grant": grant}, headers=CSRF)
    assert allowed.json() == {"grants": [grant]}
    other = client.post(f"/api/v1/assistant/conversations/{reply['conversation_id']}/allow", json={"grant": "everything"}, headers=CSRF)
    assert other.status_code == 400

    read: list[str] = []

    async def log(bench: object, given: dict) -> str:
        read.append(given["container"])
        return json.dumps({"lines": ["ok"]})

    from app.services.assistant import tools

    monkeypatch.setitem(tools.HANDLERS, "container_log", log)
    monkeypatch.setattr(providers, "turn", Script(
        providers.Turn(calls=[_call("container_log", card_id=docker["id"], container="nginx")], stop="tools"), providers.Turn(text="Read."),
    ))
    client.post("/api/v1/assistant/chat", json={"text": "Yes, read it.", "conversation_id": reply["conversation_id"]}, headers=CSRF)
    assert read == ["nginx"]


def test_the_grant_holds_for_that_container_in_that_conversation_only(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    setup_admin(client)
    _switch_on(client)
    docker, _plex = _plex_and_docker(client)
    monkeypatch.setattr(providers, "turn", Script(providers.Turn(text="Hi.")))
    first = client.post("/api/v1/assistant/chat", json={"text": "Hi"}, headers=CSRF).json()
    client.post(f"/api/v1/assistant/conversations/{first['conversation_id']}/allow", json={"grant": f"log:{docker['integration_id']}:nginx"}, headers=CSRF)
    script = Script(
        providers.Turn(calls=[_call("container_log", 1, card_id=docker["id"], container="plex")], stop="tools"), providers.Turn(text="Asked."),
        providers.Turn(calls=[_call("container_log", 2, card_id=docker["id"], container="nginx")], stop="tools"), providers.Turn(text="Asked."),
    )
    monkeypatch.setattr(providers, "turn", script)
    same = client.post("/api/v1/assistant/chat", json={"text": "plex log", "conversation_id": first["conversation_id"]}, headers=CSRF).json()
    assert [one["container"] for one in same["permissions"]] == ["plex"]
    fresh = client.post("/api/v1/assistant/chat", json={"text": "nginx log"}, headers=CSRF).json()
    assert [one["container"] for one in fresh["permissions"]] == ["nginx"]


# -- keeping and forgetting ------------------------------------------------------------------------


def test_conversations_go_thirty_days_after_their_last_turn(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    setup_admin(client)
    _switch_on(client)
    monkeypatch.setattr(providers, "turn", Script(providers.Turn(text="Old."), providers.Turn(text="New.")))
    old = client.post("/api/v1/assistant/chat", json={"text": "old"}, headers=CSRF).json()
    new = client.post("/api/v1/assistant/chat", json={"text": "new"}, headers=CSRF).json()
    with db_session() as db:
        db.get(Conversation, old["conversation_id"]).updated_at = utcnow() - timedelta(days=chat.KEEP_DAYS, minutes=1)
        db.get(Conversation, new["conversation_id"]).updated_at = utcnow() - timedelta(days=chat.KEEP_DAYS - 1)
    with db_session() as db:
        assert retention.prune_old_records(db)["conversations"] == 1
    with db_session() as db:
        assert [row.id for row in db.scalars(select(Conversation))] == [new["conversation_id"]]
        assert {turn.conversation_id for turn in db.scalars(select(ConversationTurn))} == {new["conversation_id"]}


def test_a_person_deletes_one_or_all_of_their_conversations(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    setup_admin(client)
    _switch_on(client)
    monkeypatch.setattr(providers, "turn", Script())
    ids = [client.post("/api/v1/assistant/chat", json={"text": f"q{n}"}, headers=CSRF).json()["conversation_id"] for n in range(3)]
    assert client.delete(f"/api/v1/assistant/conversations/{ids[0]}", headers=CSRF).status_code == 204
    assert [row["id"] for row in client.get("/api/v1/assistant/conversations").json()] == [ids[2], ids[1]]
    assert client.delete("/api/v1/assistant/conversations", headers=CSRF).status_code == 204
    assert client.get("/api/v1/assistant/conversations").json() == []
    with db_session() as db:
        assert list(db.scalars(select(ConversationTurn))) == []


def test_one_answer_at_a_time(client: TestClient) -> None:
    from app.routers import assistant as router

    setup_admin(client)
    _switch_on(client)
    me = client.get("/api/v1/auth/me").json()
    router._busy.add(me["id"])
    try:
        busy = client.post("/api/v1/assistant/chat", json={"text": "again"}, headers=CSRF)
    finally:
        router._busy.discard(me["id"])
    assert busy.status_code == 409 and busy.json()["detail"]["code"] == "busy"


# -- what the tools see ------------------------------------------------------------------------


def test_a_failing_check_counts_as_red_and_repeating_cards_stay_out(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    setup_admin(client)
    _switch_on(client)
    page = _board(client)["pages"][0]["id"]
    tile = _card(client, page, "core.clock", title="Router")
    problems = _card(client, page, "core.problems")
    live.set(problems["id"], WidgetData(status="bad"))
    with db_session() as db:
        db.add(HealthCheck(widget_id=tile["id"], target="http://router", enabled=True, last_ok=False, last_error="timed out"))
    script = Script(providers.Turn(calls=[_call("needs_attention")], stop="tools"), providers.Turn(text="The router."))
    monkeypatch.setattr(providers, "turn", script)
    client.post("/api/v1/assistant/chat", json={"text": "What is down?"}, headers=CSRF)
    found = json.loads(script.seen[1][-1]["results"][0]["content"])
    assert [(row["card"], row["colour"], row["reason"]) for row in found["cards"]] == [("Router", "red", "timed out")]


def test_an_unknown_tool_or_a_failing_one_tells_the_model_and_the_answer_goes_on(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    setup_admin(client)
    _switch_on(client)
    from app.services.assistant import tools

    def broken(_bench: object, _given: dict) -> str:
        raise RuntimeError("boom")

    monkeypatch.setitem(tools.HANDLERS, "find_cards", broken)
    script = Script(providers.Turn(calls=[_call("find_cards", 1), _call("format_disk", 2)], stop="tools"), providers.Turn(text="Sorry."))
    monkeypatch.setattr(providers, "turn", script)
    reply = client.post("/api/v1/assistant/chat", json={"text": "?"}, headers=CSRF).json()
    assert reply["text"] == "Sorry."
    results = script.seen[1][-1]["results"]
    assert [result["is_error"] for result in results] == [True, True]
    assert "RuntimeError" in results[0]["content"] and "format_disk" in results[1]["content"]


# -- the providers themselves -------------------------------------------------------------------------


TRANSCRIPT = [
    {"role": "user", "text": "Is plex fine?"},
    {"role": "assistant", "text": "Looking.", "calls": [_call("find_cards", words="plex")], "provider": "anthropic",
     "raw": [{"type": "thinking", "thinking": "…", "signature": "sig"}, {"type": "text", "text": "Looking."},
             {"type": "tool_use", "id": "toolu_1", "name": "find_cards", "input": {"words": "plex"}}, {"type": "fallback_marker"}]},
    {"role": "tool", "results": [{"id": "toolu_1", "content": "{\"cards\": []}", "is_error": False}]},
    {"role": "answer", "text": "Plex is fine."},
]


def test_claude_gets_its_own_blocks_back_and_nothing_else() -> None:
    messages = providers.to_anthropic(TRANSCRIPT)
    assert [message["role"] for message in messages] == ["user", "assistant", "user"]
    assert [block["type"] for block in messages[1]["content"]] == ["thinking", "text", "tool_use"], "the thinking block goes back as it came"
    assert messages[2]["content"][0] == {"type": "tool_result", "tool_use_id": "toolu_1", "content": "{\"cards\": []}", "is_error": False}
    # An answer of another provider is rebuilt from nexdeck's own shape.
    other = providers.to_anthropic([{**TRANSCRIPT[1], "provider": "openai", "raw": None}])
    assert other[0]["content"] == [{"type": "text", "text": "Looking."}, {"type": "tool_use", "id": "toolu_1", "name": "find_cards", "input": {"words": "plex"}}]


def test_the_openai_form_carries_calls_and_results() -> None:
    messages = providers.to_openai("system", TRANSCRIPT)
    assert [message["role"] for message in messages] == ["system", "user", "assistant", "tool"]
    assert messages[2]["tool_calls"][0]["function"] == {"name": "find_cards", "arguments": "{\"words\": \"plex\"}"}
    assert messages[3] == {"role": "tool", "tool_call_id": "toolu_1", "content": "{\"cards\": []}"}


OLLAMA = {"provider": "openai", "base_url": "http://ollama:11434/v1", "model": "qwen3:14b"}


@pytest.mark.asyncio
@respx.mock
async def test_an_openai_shaped_turn_reads_tool_calls() -> None:
    route = respx.post("http://ollama:11434/v1/chat/completions").mock(return_value=httpx.Response(200, json={
        "choices": [{"finish_reason": "tool_calls", "message": {"content": None, "tool_calls": [
            {"id": "call_a", "type": "function", "function": {"name": "find_cards", "arguments": "{\"words\": \"nas\"}"}},
            {"id": "call_b", "type": "function", "function": {"name": "needs_attention", "arguments": "not json"}},
        ]}}], "usage": {"prompt_tokens": 120, "completion_tokens": 9},
    }))
    turn = await providers.turn(OLLAMA, "", "system", [{"role": "user", "text": "nas?"}], [{"name": "find_cards", "description": "d", "input_schema": {"type": "object"}}])
    assert turn.stop == "tools" and turn.tokens_in == 120
    assert turn.calls == [{"id": "call_a", "name": "find_cards", "input": {"words": "nas"}}, {"id": "call_b", "name": "needs_attention", "input": {}}]
    sent = json.loads(route.calls[0].request.content)
    assert sent["tools"][0]["function"]["name"] == "find_cards" and "Authorization" not in route.calls[0].request.headers


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize(("answer", "code"), [(401, "auth"), (404, "model"), (500, "provider")])
async def test_an_openai_shaped_service_that_says_no_is_named(answer: int, code: str) -> None:
    respx.post("http://ollama:11434/v1/chat/completions").mock(return_value=httpx.Response(answer))
    with pytest.raises(providers.AssistantError) as failure:
        await providers.turn(OLLAMA, "key", "system", [{"role": "user", "text": "?"}], [])
    assert failure.value.code == code


class _Claude(BaseHTTPRequestHandler):
    """Stands in for the Messages API and remembers what the SDK sent."""

    seen: list[dict[str, Any]] = []
    answer: dict[str, Any] = {}

    def do_POST(self) -> None:  # noqa: N802 - the name http.server calls
        body = self.rfile.read(int(self.headers["Content-Length"]))
        _Claude.seen.append({"path": self.path, "headers": {name.lower(): value for name, value in self.headers.items()}, "body": json.loads(body)})
        out = json.dumps(_Claude.answer).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def do_GET(self) -> None:  # noqa: N802 - the name http.server calls
        _Claude.seen.append({"path": self.path, "headers": {name.lower(): value for name, value in self.headers.items()}})
        out = json.dumps({"data": [
            {"type": "model", "id": "claude-opus-5-5", "display_name": "Claude Opus 5.5", "created_at": "2026-09-01T00:00:00Z"},
            {"type": "model", "id": "claude-sonnet-5-5", "display_name": "Claude Sonnet 5.5", "created_at": "2026-09-01T00:00:00Z"},
        ], "has_more": False, "first_id": "claude-opus-5-5", "last_id": "claude-sonnet-5-5"}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *_args: object) -> None:
        pass


@pytest.fixture
def claude(monkeypatch: pytest.MonkeyPatch):  # noqa: ANN201 - a fixture
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Claude)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(providers, "ANTHROPIC_BASE_URL", f"http://127.0.0.1:{server.server_address[1]}")
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    _Claude.seen = []
    yield _Claude
    server.shutdown()


def _message(content: list[dict], stop: str = "tool_use") -> dict:
    return {"id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5-5", "content": content,
            "stop_reason": stop, "stop_sequence": None,
            "usage": {"input_tokens": 12, "cache_creation_input_tokens": 1000, "cache_read_input_tokens": 488, "output_tokens": 40}}


@pytest.mark.asyncio
async def test_claude_is_asked_through_the_sdk_with_effort_caching_and_the_fallback(claude: type[_Claude]) -> None:
    claude.answer = _message([
        {"type": "thinking", "thinking": "", "signature": "sig"}, {"type": "text", "text": "Let me look."},
        {"type": "tool_use", "id": "toolu_9", "name": "needs_attention", "input": {}},
    ])
    settings = {"provider": "anthropic", "base_url": "", "model": "claude-opus-5-5"}
    turn = await providers.turn(settings, "sk-ant-test", "You are nexdeck.", [{"role": "user", "text": "Anything?"}],
                                [{"name": "needs_attention", "description": "d", "input_schema": {"type": "object", "properties": {}}}])
    assert (turn.text, turn.stop, turn.tokens_in) == ("Let me look.", "tools", 1500)
    assert turn.calls == [{"id": "toolu_9", "name": "needs_attention", "input": {}}]
    assert [block["type"] for block in turn.raw] == ["thinking", "text", "tool_use"]
    sent = claude.seen[0]
    assert sent["path"].startswith("/v1/messages")
    assert "server-side-fallback-2026-07-01" in sent["headers"].get("anthropic-beta", "")
    assert sent["headers"]["x-api-key"] == "sk-ant-test"
    body = sent["body"]
    assert body["model"] == "claude-opus-5-5" and body["fallbacks"] == "default"
    assert body["output_config"] == {"effort": "medium"} and body["cache_control"] == {"type": "ephemeral"}
    assert body["tools"][0]["name"] == "needs_attention" and body["system"] == [{"type": "text", "text": "You are nexdeck."}]


@pytest.mark.asyncio
async def test_an_older_claude_gets_no_field_it_would_refuse(claude: type[_Claude]) -> None:
    claude.answer = _message([{"type": "text", "text": "OK"}], stop="end_turn")
    turn = await providers.turn({"provider": "anthropic", "base_url": "", "model": "claude-haiku-4-5"}, "k", "s", [{"role": "user", "text": "?"}], [])
    assert turn.stop == "end"
    body = claude.seen[0]["body"]
    assert "output_config" not in body and "fallbacks" not in body and "tools" not in body
    assert "anthropic-beta" not in claude.seen[0]["headers"]


@pytest.mark.asyncio
async def test_a_declined_turn_of_claude_is_a_refusal(claude: type[_Claude]) -> None:
    claude.answer = _message([], stop="refusal")
    turn = await providers.turn({"provider": "anthropic", "base_url": "", "model": "claude-opus-5-5"}, "k", "s", [{"role": "user", "text": "?"}], [])
    assert turn.stop == "refusal" and turn.text == ""


@pytest.mark.asyncio
async def test_a_scene_says_which_devices_it_switches(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.adapters.homeassistant import ADAPTER

    async def state_of(entity_id: str, _config: dict, _ctx: object) -> dict:
        return {"entity_id": entity_id, "attributes": {"entity_id": ["light.kitchen", "light.hall", "switch.tv"], "last_triggered": "2026-10-24T21:10:00+00:00"}}

    monkeypatch.setattr(ADAPTER, "state_of", state_of)
    facts = await ADAPTER.impact("entity", "scene.turn_on", {"entity_id": "scene.evening"}, {}, None)  # type: ignore[arg-type]
    assert facts == [{"fact": "devices", "count": 3, "names": ["light.kitchen", "light.hall", "switch.tv"]},
                     {"fact": "last_run", "at": "2026-10-24T21:10:00+00:00"}]
    assert await ADAPTER.impact("entity", "light.turn_off", {"entity_id": "light.kitchen"}, {}, None) == []  # type: ignore[arg-type]


def test_a_demo_connection_has_no_log_to_read(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """⚠️ Found in the browser on 25.10.2026: asked anyway, it went to the Docker socket of the machine nexdeck runs on."""
    setup_admin(client)
    _switch_on(client)
    docker, _plex = _plex_and_docker(client)
    from app.adapters import docker as docker_adapter

    def never(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("the demo reached for a Docker engine")

    monkeypatch.setattr(docker_adapter, "docker_client", never)
    monkeypatch.setattr(providers, "turn", Script(providers.Turn(text="Hi.")))
    first = client.post("/api/v1/assistant/chat", json={"text": "Hi"}, headers=CSRF).json()
    client.post(f"/api/v1/assistant/conversations/{first['conversation_id']}/allow", json={"grant": f"log:{docker['integration_id']}:nginx"}, headers=CSRF)
    script = Script(providers.Turn(calls=[_call("container_log", card_id=docker["id"], container="nginx")], stop="tools"), providers.Turn(text="No log."))
    monkeypatch.setattr(providers, "turn", script)
    client.post("/api/v1/assistant/chat", json={"text": "log", "conversation_id": first["conversation_id"]}, headers=CSRF)
    result = script.seen[1][-1]["results"][0]
    assert result["is_error"] is True and "demo" in result["content"]


# -- picking the model ---------------------------------------------------------------------------


def test_claude_lists_its_models_with_the_stored_key(client: TestClient, claude: type[_Claude]) -> None:
    setup_admin(client)
    missing = client.post("/api/v1/settings/assistant/models", json={"provider": "anthropic"}, headers=CSRF)
    assert missing.status_code == 400 and missing.json()["detail"]["code"] == "missing_key"
    _switch_on(client)
    listed = client.post("/api/v1/settings/assistant/models", json={"provider": "anthropic"}, headers=CSRF)
    assert listed.status_code == 200, listed.text
    assert listed.json() == [{"id": "claude-opus-5-5", "name": "Claude Opus 5.5"}, {"id": "claude-sonnet-5-5", "name": "Claude Sonnet 5.5"}]
    asked = claude.seen[-1]
    assert asked["path"].startswith("/v1/models") and "lifecycle%5B%5D=active" in asked["path"], "only models that are not on their way out"
    assert asked["headers"]["x-api-key"] == "sk-ant-test"


@respx.mock
def test_a_stored_key_never_goes_to_an_address_typed_elsewhere(client: TestClient) -> None:
    setup_admin(client)
    client.put("/api/v1/settings/assistant", json={"provider": "openai", "base_url": "http://llm.home.arpa/v1", "model": "qwen3", "key": "sk-home"}, headers=CSRF)
    home = respx.get("http://llm.home.arpa/v1/models").mock(return_value=httpx.Response(200, json={"data": [{"id": "qwen3"}, {"id": "llama3.1:8b"}]}))
    elsewhere = respx.get("http://other.example/v1/models").mock(return_value=httpx.Response(200, json={"data": [{"id": "x"}]}))
    listed = client.post("/api/v1/settings/assistant/models", json={"provider": "openai", "base_url": "http://llm.home.arpa/v1/"}, headers=CSRF)
    assert [one["id"] for one in listed.json()] == ["qwen3", "llama3.1:8b"]
    assert home.calls[0].request.headers["Authorization"] == "Bearer sk-home"
    client.post("/api/v1/settings/assistant/models", json={"provider": "openai", "base_url": "http://other.example/v1"}, headers=CSRF)
    assert "Authorization" not in elsewhere.calls[0].request.headers
    typed = client.post("/api/v1/settings/assistant/models", json={"provider": "openai", "base_url": "http://other.example/v1", "key": "sk-typed"}, headers=CSRF)
    assert typed.status_code == 200 and elsewhere.calls[1].request.headers["Authorization"] == "Bearer sk-typed"


@respx.mock
def test_a_service_without_a_list_says_to_type_the_name(client: TestClient) -> None:
    setup_admin(client)
    respx.get("http://llm.home.arpa/v1/models").mock(return_value=httpx.Response(404))
    answer = client.post("/api/v1/settings/assistant/models", json={"provider": "openai", "base_url": "http://llm.home.arpa/v1"}, headers=CSRF)
    assert answer.status_code == 400 and answer.json()["detail"]["code"] == "no_list"
    wrong = client.post("/api/v1/settings/assistant/models", json={"provider": "openai", "base_url": "llm:11434"}, headers=CSRF)
    assert wrong.json()["detail"]["code"] == "bad_address"


def test_members_get_no_list_of_models(client: TestClient) -> None:
    setup_admin(client)
    create_user(client, "member")
    login(client, "member", "another-long-password")
    assert client.post("/api/v1/settings/assistant/models", json={"provider": "anthropic"}, headers=CSRF).status_code == 403


# -- logs from every engine that has them ------------------------------------------------------


def test_docker_frames_and_times_come_out_as_lines() -> None:
    from app.adapters.docker import log_lines

    def frame(stream: int, text: str) -> bytes:
        body = text.encode()
        return bytes([stream, 0, 0, 0]) + len(body).to_bytes(4, "big") + body

    raw = frame(1, "2026-10-25T10:02:01.068709153Z started\n") + frame(2, "2026-10-25T10:02:02.1Z CUDA out of memory\n")
    assert log_lines(raw, tty=False) == ["10:02:01 started", "10:02:02 CUDA out of memory"]
    assert log_lines(b"2026-10-25T10:02:01.5Z plain\n\n", tty=True) == ["10:02:01 plain"]


async def test_a_synology_gives_its_container_log_oldest_first(monkeypatch: pytest.MonkeyPatch) -> None:
    """The shape measured against DSM 7 on 25.10.2026: name and order as JSON strings, newest first."""
    from app.adapters.synology import SynologyAdapter

    asked: list[dict] = []

    async def api(_self: object, _config: dict, _ctx: object, api: str, method: str, version: str = "1", extra: dict | None = None, **_: object) -> dict:
        asked.append({"api": api, "method": method, **(extra or {})})
        return {"logs": [{"created": "2026-10-25T10:02:02.5Z", "stream": "stderr", "text": "second\n"},
                         {"created": "2026-10-25T10:02:01.1Z", "stream": "stdout", "text": "first"}], "total": 2}

    monkeypatch.setattr(SynologyAdapter, "_api", api)
    lines = await SynologyAdapter().container_log({}, None, "immich_server", 2)  # type: ignore[arg-type]
    assert lines == ["10:02:01 first", "10:02:02 second"]
    assert asked == [{"api": "SYNO.Docker.Container.Log", "method": "get", "name": '"immich_server"', "offset": "0", "limit": "2", "sort_dir": '"DESC"'}]


@respx.mock
async def test_portainer_gives_the_log_through_its_docker_interface() -> None:
    from app.adapters.base import Context
    from app.adapters.portainer import PortainerAdapter

    base = "https://portainer:9443/api/endpoints/3/docker"
    respx.get("https://portainer:9443/api/endpoints").mock(return_value=httpx.Response(200, json=[{"Id": 3, "Name": "local"}]))
    respx.get(f"{base}/containers/json").mock(return_value=httpx.Response(200, json=[{"Id": "abc", "Names": ["/nginx"]}]))
    respx.get(f"{base}/containers/abc/json").mock(return_value=httpx.Response(200, json={"Config": {"Tty": True}}))
    logs = respx.get(f"{base}/containers/abc/logs").mock(return_value=httpx.Response(200, content=b"2026-10-25T10:00:00.1Z up\n"))
    ctx = Context(httpx.AsyncClient(), integration_id=1, cache={})
    lines = await PortainerAdapter().container_log({"url": "https://portainer:9443", "api_key": "k", "insecure": True}, ctx, "nginx", 20)
    assert lines == ["10:00:00 up"]
    assert logs.calls[0].request.url.params["tail"] == "20"


def test_a_connection_without_logs_is_said_so_before_anybody_is_asked(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    setup_admin(client)
    _switch_on(client)
    _docker, plex = _plex_and_docker(client)
    script = Script(providers.Turn(calls=[_call("container_log", card_id=plex["id"], container="plex")], stop="tools"), providers.Turn(text="Cannot."))
    monkeypatch.setattr(providers, "turn", script)
    reply = client.post("/api/v1/assistant/chat", json={"text": "plex log"}, headers=CSRF).json()
    assert reply["permissions"] == [], "nobody is asked for something that cannot be read"
    assert "Docker, Portainer and a Synology" in script.seen[1][-1]["results"][0]["content"]


def test_an_allowed_log_of_a_synology_is_read_and_its_secrets_masked(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.adapters.synology import SynologyAdapter

    setup_admin(client)
    _switch_on(client)
    page = _board(client)["pages"][0]["id"]
    made = client.post("/api/v1/integrations", json={"kind": "synology", "name": "NAS", "config": {"url": "https://nas.example.com:5001", "username": "u", "password": "p"}}, headers=CSRF)
    assert made.status_code == 201, made.text
    card = client.post(f"/api/v1/pages/{page}/widgets", json={"kind": "synology.containers", "integration_id": made.json()["id"]}, headers=CSRF).json()["widget"]
    collector.unschedule(card["id"])

    async def log(_self: object, _config: dict, _ctx: object, container: str, lines: int) -> list[str]:
        return [f"10:00:00 {container} starting", "10:00:01 connecting with password=hunter2-secret"]

    monkeypatch.setattr(SynologyAdapter, "container_log", log)
    monkeypatch.setattr(providers, "turn", Script(providers.Turn(text="Hi.")))
    first = client.post("/api/v1/assistant/chat", json={"text": "Hi"}, headers=CSRF).json()
    client.post(f"/api/v1/assistant/conversations/{first['conversation_id']}/allow", json={"grant": f"log:{made.json()['id']}:immich_server"}, headers=CSRF)
    script = Script(providers.Turn(calls=[_call("container_log", card_id=card["id"], container="immich_server")], stop="tools"), providers.Turn(text="Read."))
    monkeypatch.setattr(providers, "turn", script)
    reply = client.post("/api/v1/assistant/chat", json={"text": "log", "conversation_id": first["conversation_id"]}, headers=CSRF).json()
    lines = json.loads(script.seen[1][-1]["results"][0]["content"])["lines"]
    assert lines[0] == "10:00:00 immich_server starting"
    assert "hunter2-secret" not in lines[1]
    assert reply["citations"][0]["target"]["widget"] == card["id"]


@pytest.mark.parametrize(("line", "gone"), [
    ("connecting with password=hunter2-secret", "hunter2-secret"),
    ('{"api_key": "sk-abcdef123456"}', "sk-abcdef123456"),
    ("TOKEN: 9f8e7d6c5b4a", "9f8e7d6c5b4a"),
    ("Authorization: Bearer abcdefghijklmnop", "abcdefghijklmnop"),
    ("GET postgres://immich:dbpass99@db:5432/immich", "dbpass99"),
    ("session eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U", "dozjgNryP4J3jVmNHl0w5N"),
    ("GET /api/x?apikey=abc123def", "abc123def"),
])
def test_a_log_line_goes_out_with_its_secrets_masked(line: str, gone: str) -> None:
    from app.services.assistant.tools import log_redact
    from app.services.journal import redact

    assert gone not in log_redact(redact(line))


def test_an_ordinary_log_line_stays_as_it_was() -> None:
    from app.services.assistant.tools import log_redact

    line = "10:00:01 [Nest] 7 LOG Bootstrap complete, 3 workers, token cache warm"
    assert log_redact(line) == line
