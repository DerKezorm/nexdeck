"""A card drafted in the chat (KARTEN-18): the question about the connection, the probe, the draft kept with the conversation."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.cards import load
from app.db import db_session
from app.models import Conversation, ConversationDraft, utcnow
from app.services.assistant import chat, providers
from app.services.collector import collector

from .conftest import CSRF, create_user, login, setup_admin
from .test_cards_ai import ANSWER, SECRET_KEY, SECRET_NUMBER, SECRET_TEXT, Script, card
from .test_cards_ai_routes import switch_on
from .test_cards_router import BASE, connection

ASK = {"text": "Build me a card that shows my queue"}


@pytest.fixture
def admin(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    setup_admin(client)
    monkeypatch.setattr(collector, "running", False)
    switch_on(client)
    return client


def draft_call(number: int = 1, **given: Any) -> dict:
    return {"id": f"toolu_{number}", "name": "draft_card", "input": {"description": "my queue", **given}}


def chat_turn(*calls: dict) -> providers.Turn:
    return providers.Turn(text="", calls=list(calls), stop="tools")


def ask(client: TestClient, **more: Any) -> dict:
    answer = client.post("/api/v1/assistant/chat", json={**ASK, **more}, headers=CSRF)
    assert answer.status_code == 200, answer.text
    return answer.json()


def serve() -> None:
    respx.get(f"{BASE}/api/v3/queue").mock(return_value=httpx.Response(200, json=ANSWER))


def tool_result(script: Script, turn: int = 1) -> dict:
    return json.loads(script.seen[turn]["transcript"][-1]["results"][0]["content"])


@respx.mock
def test_karten18_ac1_with_two_connections_that_fit_the_chat_is_told_to_ask(admin: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    connection(admin, "sonarr")
    connection(admin, "radarr")
    serve()
    script = Script(chat_turn(draft_call(path="/api/v3/queue")), providers.Turn(text="Which one: Sonarr or Radarr?"))
    monkeypatch.setattr(providers, "turn", script)
    reply = ask(admin)
    assert reply["drafts"] == [] and len(script.seen) == 2, "no draft, and the provider was not asked for a card"
    found = tool_result(script)
    assert found["ask"] is True and [one["kind"] for one in found["connections"]] == ["sonarr", "radarr"]
    assert "My sonarr" in json.dumps(found), "the chat may name the connections to ask which one; the card request never does"


@respx.mock
def test_karten18_ac2_ac5_a_clear_connection_is_probed_and_the_draft_comes_back_with_a_chip(admin: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    sonarr = connection(admin, "sonarr")
    serve()
    script = Script(chat_turn(draft_call(service="sonarr", path="/api/v3/queue")), card(), providers.Turn(text="Here is a card."))
    monkeypatch.setattr(providers, "turn", script)
    reply = ask(admin)
    assert len(reply["drafts"]) == 1
    draft = reply["drafts"][0]
    assert draft["name"] == "Download queue" and draft["form"] == "list" and draft["keep_days"] == chat.KEEP_DAYS == 30
    assert draft["summary"] == {"connection_kind": "sonarr", "path": "/api/v3/queue", "form": "list", "buttons": False}
    assert draft["sent"] == {"values": False} and draft["url"] == f"/system/custom-cards/new?draft={draft['id']}"
    assert sonarr and tool_result(script, 2)["drafted"] is True

    stored = admin.get(f"/api/v1/assistant/drafts/{draft['id']}")
    assert stored.status_code == 200, stored.text
    text = stored.json()["yaml"]
    definition = load.load_definition(text).definition
    assert definition.demo, "the small preview in the chat draws from invented examples"
    assert SECRET_TEXT not in text and SECRET_KEY not in text, "and those are not the real ones"
    # The chat shows the answer again later, chip included.
    shown = admin.get(f"/api/v1/assistant/conversations/{reply['conversation_id']}").json()
    assert shown["turns"][-1]["drafts"] == reply["drafts"]


@respx.mock
def test_karten18_ac4_the_card_request_carries_no_value_unless_the_person_allowed_it_for_that_request(admin: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    connection(admin, "sonarr")
    serve()
    script = Script(chat_turn(draft_call(service="sonarr", path="/api/v3/queue")), card(), providers.Turn(text="Done."))
    monkeypatch.setattr(providers, "turn", script)
    ask(admin)
    sent = script.sent()
    for secret in (SECRET_TEXT, str(SECRET_NUMBER), SECRET_KEY):
        assert secret not in sent, "neither the card request nor the chat itself saw a value"

    # With values: the person is asked first and nothing is sent until they allow it.
    script = Script(chat_turn(draft_call(service="sonarr", path="/api/v3/queue", with_values=True)), providers.Turn(text="I need your permission."))
    monkeypatch.setattr(providers, "turn", script)
    reply = ask(admin)
    assert len(script.seen) == 2 and reply["drafts"] == []
    wanted = reply["permissions"][0]
    assert wanted["kind"] == "values" and wanted["path"] == "/api/v3/queue" and wanted["integration"] == "My sonarr" and wanted["grant"].startswith("values:")
    assert SECRET_TEXT not in script.sent()

    allowed = admin.post(f"/api/v1/assistant/conversations/{reply['conversation_id']}/allow", json={"grant": wanted["grant"]}, headers=CSRF)
    assert allowed.status_code == 200, allowed.text
    script = Script(chat_turn(draft_call(service="sonarr", path="/api/v3/queue", with_values=True)), card(), providers.Turn(text="Done."))
    monkeypatch.setattr(providers, "turn", script)
    again = ask(admin, conversation_id=reply["conversation_id"])
    assert again["drafts"][0]["sent"] == {"values": True}
    nested = json.dumps(script.seen[1])
    assert SECRET_TEXT in nested and SECRET_KEY not in nested
    assert SECRET_TEXT not in json.dumps([script.seen[0], script.seen[2]]), "the chat itself still sees no value"


@respx.mock
def test_karten18_ac4_the_permission_is_for_one_request_and_a_failed_one_uses_it_up(admin: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    connection(admin, "sonarr")
    serve()
    wish = draft_call(service="sonarr", path="/api/v3/queue", with_values=True)
    monkeypatch.setattr(providers, "turn", Script(chat_turn(wish), providers.Turn(text="May I?")))
    first = ask(admin)
    conversation = first["conversation_id"]
    grant = first["permissions"][0]["grant"]
    assert admin.post(f"/api/v1/assistant/conversations/{conversation}/allow", json={"grant": grant}, headers=CSRF).status_code == 200

    # The one request that uses it fails for the provider's own reasons (twice an invalid card): the permission is gone all the same.
    broken = ai_example_other().replace("form: list", "form: carousel")
    script = Script(chat_turn(wish), card(broken), card(broken), providers.Turn(text="It did not work."))
    monkeypatch.setattr(providers, "turn", script)
    used = ask(admin, conversation_id=conversation)
    assert used["drafts"] == [] and SECRET_TEXT in json.dumps(script.seen[1])
    with db_session() as db:
        assert db.get(Conversation, conversation).grants == []

    # The next draft of the same connection and path asks again and sends no value.
    script = Script(chat_turn(wish), providers.Turn(text="May I?"))
    monkeypatch.setattr(providers, "turn", script)
    again = ask(admin, conversation_id=conversation)
    assert [one["grant"] for one in again["permissions"]] == [grant] and again["drafts"] == []
    assert len(script.seen) == 2 and SECRET_TEXT not in script.sent()

    # Allowed once more, it carries exactly one draft: a second one in the same answer asks.
    assert admin.post(f"/api/v1/assistant/conversations/{conversation}/allow", json={"grant": grant}, headers=CSRF).status_code == 200
    script = Script(chat_turn(draft_call(1, service="sonarr", path="/api/v3/queue", with_values=True), draft_call(2, service="sonarr", path="/api/v3/queue", with_values=True)),
                    card(), providers.Turn(text="One of two."))
    monkeypatch.setattr(providers, "turn", script)
    both = ask(admin, conversation_id=conversation)
    assert [one["sent"] for one in both["drafts"]] == [{"values": True}] and len(both["permissions"]) == 1


def test_karten18_ec2_a_connection_without_cards_of_its_own_gets_a_sentence_with_the_way_out(admin: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    made = admin.post("/api/v1/integrations", json={"kind": "docker", "name": "Host", "config": {}, "demo": True}, headers=CSRF)
    assert made.status_code == 201, made.text
    script = Script(chat_turn(draft_call(service="docker", path="/x")), providers.Turn(text="Not possible."))
    monkeypatch.setattr(providers, "turn", script)
    reply = ask(admin)
    assert reply["drafts"] == [] and len(script.seen) == 2
    said = tool_result(script)["error"]
    assert "docker" in said and "JSON API" in said and "own connection" in said


@respx.mock
def test_karten18_ec3_each_draft_of_a_conversation_has_its_own_number(admin: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    connection(admin, "sonarr")
    serve()
    script = Script(
        chat_turn(draft_call(1, service="sonarr", path="/api/v3/queue"), draft_call(2, service="sonarr", path="/api/v3/queue")),
        card(), card(ai_example_other()), providers.Turn(text="Two drafts."),
    )
    monkeypatch.setattr(providers, "turn", script)
    reply = ask(admin)
    ids = [one["id"] for one in reply["drafts"]]
    assert len(ids) == 2 and ids[0] != ids[1]
    assert [admin.get(f"/api/v1/assistant/drafts/{one}").status_code for one in ids] == [200, 200]


def ai_example_other() -> str:
    from app.cards import ai

    return ai.EXAMPLE.replace("slug: download-queue", "slug: download-queue-two")


@respx.mock
def test_karten18_ec1_a_draft_goes_with_its_conversation(admin: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    connection(admin, "sonarr")
    serve()
    monkeypatch.setattr(providers, "turn", Script(chat_turn(draft_call(service="sonarr", path="/api/v3/queue")), card(), providers.Turn(text="x")))
    first = ask(admin)
    monkeypatch.setattr(providers, "turn", Script(chat_turn(draft_call(service="sonarr", path="/api/v3/queue")), card(), providers.Turn(text="y")))
    second = ask(admin)
    assert first["conversation_id"] != second["conversation_id"]
    # Never opened for a month: the retention round takes the conversation and its draft.
    with db_session() as db:
        old = db.get(Conversation, first["conversation_id"])
        old.updated_at = utcnow() - timedelta(days=chat.KEEP_DAYS + 1)
        db.commit()
        assert chat.sweep(db) == 1
        db.commit()
        assert [row.conversation_id for row in db.scalars(select(ConversationDraft))] == [second["conversation_id"]]
    assert admin.get(f"/api/v1/assistant/drafts/{first['drafts'][0]['id']}").status_code == 404
    # And deleting the conversation by hand does the same.
    assert admin.delete(f"/api/v1/assistant/conversations/{second['conversation_id']}", headers=CSRF).status_code == 204
    assert admin.get(f"/api/v1/assistant/drafts/{second['drafts'][0]['id']}").status_code == 404


@respx.mock
def test_karten18_only_the_owner_reads_a_draft(admin: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    connection(admin, "sonarr")
    serve()
    monkeypatch.setattr(providers, "turn", Script(chat_turn(draft_call(service="sonarr", path="/api/v3/queue")), card(), providers.Turn(text="x")))
    number = ask(admin)["drafts"][0]["id"]
    create_user(admin, "second", role="admin")
    create_user(admin, "ann")
    login(admin, "second", "another-long-password")
    assert admin.get(f"/api/v1/assistant/drafts/{number}").status_code == 404
    login(admin, "ann", "another-long-password")
    assert admin.get(f"/api/v1/assistant/drafts/{number}").status_code == 403
    admin.post("/api/v1/auth/logout", headers=CSRF)
    assert admin.get(f"/api/v1/assistant/drafts/{number}").status_code == 401


def test_karten18_the_table_of_drafts_is_made_by_migration_29(admin: TestClient) -> None:
    from sqlalchemy import inspect

    from app.db import get_engine
    from app.migrations import MIGRATIONS, schema_version

    assert max(number for number, _name, _step in MIGRATIONS) == 29 and schema_version() == 29
    step = {number: function for number, _name, function in MIGRATIONS}[29]
    with get_engine().begin() as conn:
        conn.exec_driver_sql("DROP TABLE conversation_drafts")
        step(conn)
    assert "conversation_drafts" in inspect(get_engine()).get_table_names()
