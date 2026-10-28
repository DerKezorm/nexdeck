"""MCP: which tools a key has, and that every one of them sees only what the key may see.

A tool that is denied, above the key's level, for administrators only or
blocked by the administrator does not exist for the key; a card on a board
the key may not see answers exactly like one that does not exist.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import db_session
from app.models import McpKey
from app.services import chronicle
from app.services.state import live

from .conftest import CSRF, create_user, login, setup_admin
from .mcp_kit import _quiet, board, call, docker_card, make_key, names, rpc, switch  # noqa: F401

READING = ["needs_attention", "find_cards", "card_details", "chronicle", "metric_history", "request_status"]


@pytest.fixture
def ready(client: TestClient) -> TestClient:
    setup_admin(client)
    switch(client)
    return client


def _as_kim(client: TestClient) -> None:
    create_user(client, "kim")
    login(client, "kim", "another-long-password")


# -- which tools ------------------------------------------------------------------------------


def test_a_reading_key_has_the_reading_tools_and_nothing_else(ready: TestClient) -> None:
    _key, token = make_key(ready)
    assert names(ready, token) == READING


def test_an_acting_key_has_press_button_with_the_hints_a_client_shows(ready: TestClient) -> None:
    _key, token = make_key(ready, "act")
    listed = {tool["name"]: tool for tool in rpc(ready, token, "tools/list").json()["result"]["tools"]}
    assert list(listed) == READING[:5] + ["press_button", "request_status"]
    assert listed["press_button"]["annotations"] == {"readOnlyHint": False, "destructiveHint": True}
    assert listed["find_cards"]["annotations"] == {"readOnlyHint": True, "destructiveHint": False}
    assert listed["press_button"]["inputSchema"]["required"] == ["card_id", "action"]


def test_a_denied_tool_is_missing_and_answers_like_one_that_does_not_exist(ready: TestClient) -> None:
    _key, token = make_key(ready, rights={"chronicle": "deny"})
    assert "chronicle" not in names(ready, token)
    denied = call(ready, token, "chronicle")
    unknown = call(ready, token, "no_such_tool")
    assert denied["error"] and unknown["error"]
    assert denied["value"].replace("chronicle", "X") == unknown["value"].replace("no_such_tool", "X")


def test_a_tool_the_administrator_blocked_is_gone_for_every_key(ready: TestClient) -> None:
    _key, token = make_key(ready, "act", rights={"press_button": "allow"})
    switch(ready, blocked_tools=["press_button", "find_cards"])
    assert names(ready, token) == ["needs_attention", "card_details", "chronicle", "metric_history", "request_status"]
    assert call(ready, token, "find_cards")["error"] is True
    tools = {tool["name"]: tool for tool in ready.get("/api/v1/mcp/tools").json()}
    assert tools["press_button"]["blocked"] is True and tools["card_details"]["blocked"] is False
    refused = ready.put("/api/v1/mcp/admin", json={"allowed": True, "max_level": "act", "blocked_tools": ["request_status"]}, headers=CSRF)
    assert refused.status_code == 422, "the way to learn what came of a request is never blocked"


def test_the_administrators_tools_stay_away_from_a_member_whatever_the_key_says(ready: TestClient) -> None:
    _key, admins = make_key(ready, rights={"diagnosis": "allow", "container_log": "allow"})
    assert {"diagnosis", "container_log"} <= set(names(ready, admins))
    _as_kim(ready)
    _key, kims = make_key(ready, rights={"diagnosis": "allow", "container_log": "allow"})
    assert "diagnosis" not in names(ready, kims) and "container_log" not in names(ready, kims)
    assert call(ready, kims, "diagnosis", card_id=1)["error"] is True


def test_the_administrators_tools_are_denied_until_a_key_allows_them(ready: TestClient) -> None:
    _key, token = make_key(ready)
    assert "diagnosis" not in names(ready, token)
    listed = {tool["name"]: tool for tool in ready.get("/api/v1/mcp/tools").json()}
    assert "request_status" not in listed
    assert {name: (tool["group"], tool["default_right"], tool["admin_only"]) for name, tool in listed.items()} == {
        "needs_attention": ("read", "allow", False), "find_cards": ("read", "allow", False), "card_details": ("read", "allow", False),
        "chronicle": ("read", "allow", False), "metric_history": ("read", "allow", False),
        "diagnosis": ("admin", "deny", True), "container_log": ("admin", "deny", True), "press_button": ("act", "ask", False),
    }


def test_rights_keep_only_what_differs_and_looking_is_never_asked_for(ready: TestClient) -> None:
    key, _token = make_key(ready, "act")
    rights = f"/api/v1/mcp/keys/{key['id']}/rights"
    saved = ready.put(rights, json={"tool_rights": {"find_cards": "allow", "chronicle": "deny", "press_button": "allow"}}, headers=CSRF)
    assert saved.status_code == 200 and saved.json()["tool_rights"] == {"chronicle": "deny", "press_button": "allow"}
    for wrong in ({"find_cards": "ask"}, {"diagnosis": "ask"}, {"press_button": "maybe"}, {"nothing": "allow"}, {"request_status": "deny"}):
        assert ready.put(rights, json={"tool_rights": wrong}, headers=CSRF).status_code == 422, wrong
    with db_session() as db:
        assert db.scalar(select(McpKey.tool_rights)) == {"chronicle": "deny", "press_button": "allow"}


def test_wrong_arguments_are_refused_before_anything_runs(ready: TestClient) -> None:
    _key, token = make_key(ready)
    assert call(ready, token, "card_details")["value"] == "'card_id' is missing."
    assert call(ready, token, "card_details", card_id="seven")["value"] == "'card_id' must be of type integer."
    assert call(ready, token, "card_details", card_id=True)["error"] is True
    assert call(ready, token, "find_cards", words="x", extra=1)["value"] == "There is no argument 'extra'."
    assert call(ready, token, "chronicle", group="everything")["error"] is True
    assert call(ready, token, "find_cards", words="x" * 5000)["error"] is True
    nested: dict = {}
    inner = nested
    for _ in range(30):
        inner["a"] = {}
        inner = inner["a"]
    assert rpc(ready, token, "tools/call", {"name": "find_cards", "arguments": nested}).json()["result"]["isError"] is True
    assert rpc(ready, token, "tools/call", {"name": "find_cards", "arguments": "words"}).json()["result"]["isError"] is True


# -- what a key may see ------------------------------------------------------------------------


@pytest.fixture
def two_boards(ready: TestClient) -> dict:
    """Kim owns two boards with a card each; the administrator has one of his own."""
    secret = board(ready, "Admin")
    secret_card = docker_card(ready, secret["pages"][0]["id"], "Secret host")
    kim = create_user(ready, "kim")
    first, second = board(ready, "Kitchen"), board(ready, "Garage")
    one = docker_card(ready, first["pages"][0]["id"], "Kitchen host")
    two = docker_card(ready, second["pages"][0]["id"], "Garage host")
    for made in (first, second):
        given = ready.patch(f"/api/v1/boards/{made['slug']}", json={"owner_id": kim["id"]}, headers=CSRF)
        assert given.status_code == 200, given.text
    login(ready, "kim", "another-long-password")
    return {"secret": secret, "secret_card": secret_card, "first": first, "second": second, "one": one, "two": two}


def test_a_card_on_a_board_the_account_may_not_see_answers_like_one_that_does_not_exist(ready: TestClient, two_boards: dict) -> None:
    _key, token = make_key(ready)
    found = call(ready, token, "find_cards")["value"]["cards"]
    assert sorted(card["title"] for card in found) == ["Garage host", "Kitchen host"]
    foreign = call(ready, token, "card_details", card_id=two_boards["secret_card"]["id"])
    missing = call(ready, token, "card_details", card_id=99999)
    assert foreign == missing == {"error": True, "value": {"error": "No such card."}}
    assert call(ready, token, "metric_history", card_id=two_boards["secret_card"]["id"], metric="cpu") == missing


def test_a_key_limited_to_a_board_sees_only_that_board(ready: TestClient, two_boards: dict) -> None:
    from app.services.notify import emit

    # An unread warning in the bell, so the empty list below is the key's limit and not an empty bell.
    emit("widget_broken", "The garage card stopped working", level="warn", user_ids=[_kim_id()])
    _key, token = make_key(ready, boards=[two_boards["first"]["id"]])
    found = call(ready, token, "find_cards")["value"]["cards"]
    assert [card["title"] for card in found] == ["Kitchen host"]
    assert call(ready, token, "card_details", card_id=two_boards["two"]["id"])["value"] == {"error": "No such card."}
    assert call(ready, token, "card_details", card_id=two_boards["one"]["id"])["error"] is False
    attention = call(ready, token, "needs_attention")["value"]
    assert [row["card"] for row in attention["cards"]] == ["Kitchen host"]
    assert attention["unread_warnings"] == [], "the bell names every board; a limited key does not read it"


def _kim_id() -> int:
    with db_session() as db:
        from app.models import User

        return db.scalar(select(User.id).where(User.username == "kim"))


def test_a_key_for_every_board_sees_the_bell_of_its_account(ready: TestClient, two_boards: dict) -> None:
    from app.services.notify import emit

    emit("widget_broken", "The garage card stopped working", level="warn", user_ids=[_kim_id()])
    _key, token = make_key(ready)
    attention = call(ready, token, "needs_attention")["value"]
    assert [warning["title"] for warning in attention["unread_warnings"]] == ["The garage card stopped working"]
    assert sorted(row["card"] for row in attention["cards"]) == ["Garage host", "Kitchen host"]


def test_the_chronicle_follows_the_key_s_boards(ready: TestClient, two_boards: dict) -> None:
    chronicle.card_turned(two_boards["one"]["id"], "Kitchen host", "ok", "bad", "down")
    chronicle.card_turned(two_boards["two"]["id"], "Garage host", "ok", "bad", "down")
    chronicle.card_turned(two_boards["secret_card"]["id"], "Secret host", "ok", "bad", "down")
    _key, every = make_key(ready, name="every")
    _key, kitchen = make_key(ready, name="kitchen", boards=[two_boards["first"]["id"]])
    assert sorted(line["name"] for line in call(ready, every, "chronicle", group="cards")["value"]["lines"]) == ["Garage host", "Kitchen host"]
    assert [line["name"] for line in call(ready, kitchen, "chronicle", group="cards")["value"]["lines"]] == ["Kitchen host"]


def _shared_connection(ready: TestClient) -> dict:
    """One connection on a board Kim may open and on one she may not; each card turned red once."""
    lab, private = board(ready, "Lab"), board(ready, "Private")
    made = ready.post("/api/v1/integrations", json={"kind": "docker", "name": "Shared", "config": {}, "demo": True}, headers=CSRF).json()
    ids = {}
    for target, title in ((lab, "Lab card"), (private, "Secret card")):
        answer = ready.post(f"/api/v1/pages/{target['pages'][0]['id']}/widgets",
                            json={"kind": "docker.containers", "title": title, "integration_id": made["id"]}, headers=CSRF)
        ids[title] = answer.json()["widget"]["id"]
        chronicle.card_turned(ids[title], title, "ok", "bad", "down", integration_id=made["id"])
    kim = create_user(ready, "kim")
    shared = ready.put(f"/api/v1/boards/{lab['slug']}/shares", json={"shares": [{"user_id": kim["id"], "level": "view"}]}, headers=CSRF)
    assert shared.status_code in (200, 201), shared.text
    return {"lab": lab, "private": private, "ids": ids}


def test_the_chronicle_names_no_card_of_a_board_the_account_may_not_open_though_a_connection_is_shared(ready: TestClient) -> None:
    shared = _shared_connection(ready)
    login(ready, "kim", "another-long-password")
    _key, token = make_key(ready)
    lines = call(ready, token, "chronicle", hours=24, group="cards")["value"]["lines"]
    assert [line["name"] for line in lines] == ["Lab card"], lines
    assert call(ready, token, "card_details", card_id=shared["ids"]["Secret card"])["value"] == {"error": "No such card."}


def test_the_chronicle_of_a_limited_key_names_no_card_of_another_board_that_shares_its_connection(ready: TestClient) -> None:
    shared = _shared_connection(ready)
    _key, token = make_key(ready, boards=[shared["lab"]["id"]])
    lines = call(ready, token, "chronicle", hours=24, group="cards")["value"]["lines"]
    assert [line["name"] for line in lines] == ["Lab card"], lines
    _key, whole = make_key(ready, name="whole")
    assert sorted(line["name"] for line in call(ready, whole, "chronicle", hours=24, group="cards")["value"]["lines"]) == ["Lab card", "Secret card"]


def test_a_board_lost_since_the_key_was_made_is_lost_to_the_key(ready: TestClient, two_boards: dict) -> None:
    key, token = make_key(ready, boards=[two_boards["first"]["id"], two_boards["second"]["id"]])
    login(ready, "admin", "correct-horse-battery")
    with db_session() as db:
        from app.models import Board, User

        admin = db.scalar(select(User).where(User.username == "admin"))
        db.get(Board, two_boards["second"]["id"]).owner_id = admin.id
    assert [card["title"] for card in call(ready, token, "find_cards")["value"]["cards"]] == ["Kitchen host"]
    login(ready, "kim", "another-long-password")
    assert ready.get("/api/v1/mcp/keys").json()[0]["boards"] == [two_boards["first"]["id"]]
    assert key["boards"] == sorted([two_boards["first"]["id"], two_boards["second"]["id"]])


def test_a_limited_administrator_key_asks_no_diagnosis_about_a_service_off_its_boards(ready: TestClient) -> None:
    lab, other = board(ready, "Lab"), board(ready, "Other")
    mine = docker_card(ready, lab["pages"][0]["id"], "Lab host")
    theirs = docker_card(ready, other["pages"][0]["id"], "Other host")
    _key, token = make_key(ready, boards=[lab["id"]], rights={"diagnosis": "allow"})
    with db_session() as db:
        from app.models import Widget

        integration = db.get(Widget, theirs["id"]).integration_id
    refused = call(ready, token, "diagnosis", ref=f"integration:{integration}")
    assert refused["value"] == {"error": "Name a service by its ref or one of its cards by card_id."}
    assert call(ready, token, "diagnosis", card_id=theirs["id"])["value"] == refused["value"]
    assert call(ready, token, "diagnosis", card_id=mine["id"])["error"] is False


def test_a_limited_administrator_key_reads_nothing_of_a_card_on_another_board_in_a_diagnosis(client: TestClient) -> None:
    """⚠️ A service is shown by cards on several boards; the diagnosis named all of them, their lines and their buttons."""
    from app.adapters.base import WidgetData
    from app.services.collector import collector

    from .test_dependencies import _chain

    _pve, engine, plex = _chain(client)
    switch(client)
    lab, other = board(client, "Lab"), board(client, "Other")

    def card(target: dict, kind: str, integration: int, title: str) -> int:
        made = client.post(f"/api/v1/pages/{target['pages'][0]['id']}/widgets",
                           json={"kind": kind, "title": title, "integration_id": integration}, headers=CSRF)
        assert made.status_code == 201, made.text
        collector.unschedule(made.json()["widget"]["id"])
        return made.json()["widget"]["id"]

    mine = card(lab, "plex.nowplaying", plex, "Lab plex")
    theirs = card(other, "plex.nowplaying", plex, "Secret plex")
    engine_card = card(other, "docker.containers", engine, "Secret docker")
    live.set(engine_card, WidgetData(status="ok", items=[{"title": "plex", "actions": [{"id": "restart", "label": "Restart", "params": {"id": "c1"}}]}]))
    chronicle.card_turned(theirs, "Secret plex", "ok", "bad", "down", integration_id=plex)
    _key, limited = make_key(client, "read", boards=[lab["id"]], rights={"diagnosis": "allow"})
    _key, whole = make_key(client, "read", name="whole", rights={"diagnosis": "allow"})

    # The same question to a key that sees both boards names what the limited one must not hear of.
    everything = call(client, whole, "diagnosis", card_id=mine)["value"]
    assert sorted(one["title"] for one in everything["cards"]) == ["Lab plex", "Secret plex"]
    assert [one["card"] for one in everything["buttons"]] == ["Secret docker"]
    assert "Secret plex" in json.dumps(everything["lines"])

    answer = call(client, limited, "diagnosis", card_id=mine)
    assert answer["error"] is False
    assert [one["title"] for one in answer["value"]["cards"]] == ["Lab plex"]
    assert answer["value"]["buttons"] == []
    assert "Secret" not in json.dumps(answer["value"])


def _listing_card(ready: TestClient) -> dict:
    return docker_card(ready, board(ready, "Lab")["pages"][0]["id"])


def test_a_container_log_is_read_only_for_a_container_the_card_lists(ready: TestClient) -> None:
    """The connection serves other cards too; asking for a container only they list is asking for their log."""
    card = _listing_card(ready)
    _key, token = make_key(ready, rights={"container_log": "allow"})
    foreign = call(ready, token, "container_log", card_id=card["id"], container="nginx")
    assert foreign == {"error": True, "value": {"error": "That container is not on this card. Name one that card_details lists."}}
    # By its name, or by the id the card gives it: past the question and on to the engine (a demo has none).
    for listed in ("plex", "c1"):
        answer = call(ready, token, "container_log", card_id=card["id"], container=listed)
        assert answer["value"] == {"error": "This connection is in the demo and has no real log."}, listed


def test_a_container_log_is_asked_of_no_card_that_lists_nothing_yet(ready: TestClient) -> None:
    card = _listing_card(ready)
    live.clear()
    _key, token = make_key(ready, rights={"container_log": "allow"})
    answer = call(ready, token, "container_log", card_id=card["id"], container="plex")
    assert answer["error"] is True and "not on this card" in answer["value"]["error"]


def test_a_container_log_over_mcp_needs_no_question_in_a_conversation_but_its_right(ready: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    lab = board(ready, "Lab")
    card = docker_card(ready, lab["pages"][0]["id"])
    _key, token = make_key(ready, rights={"container_log": "allow"})
    answer = call(ready, token, "container_log", card_id=card["id"], container="plex")
    assert answer["value"] == {"error": "This connection is in the demo and has no real log."}, "it went past the question to the log itself"
    assert live.get(card["id"]) is not None


def test_a_looking_tool_set_to_ask_in_the_database_still_just_looks(ready: TestClient) -> None:
    """The routes refuse "ask" for a looking tool; a row that holds it anyway must not make the tool wait or vanish."""
    key, token = make_key(ready)
    with db_session() as db:
        # A right that is none of allow, ask, deny falls back to the default: the administrators' tool stays denied.
        db.get(McpKey, key["id"]).tool_rights = {"find_cards": "ask", "chronicle": "whatever", "diagnosis": "whatever"}
    assert names(ready, token) == READING
    assert call(ready, token, "find_cards")["error"] is False


def test_the_right_of_a_looking_tool_is_allow_never_ask() -> None:
    """Only ``press_button`` reads what the right is beyond "there or not", so this is checked on ``Caller.right`` itself:
    a looking tool must never come back as "ask", or the next tool that reads it would wait for nothing."""
    from app.services.mcp import Caller
    from app.services.mcp_calls import BY_NAME

    caller = Caller(user_id=1, username="admin", role="admin", key_id=1, key_name="k", level="act",
                    rights={"find_cards": "ask", "diagnosis": "ask", "press_button": "maybe"}, blocked=frozenset(), boards=None)
    assert caller.right(BY_NAME["find_cards"]) == "allow"
    assert caller.right(BY_NAME["diagnosis"]) == "allow"
    assert caller.right(BY_NAME["press_button"]) == "ask", "an unknown right is the group's default"
