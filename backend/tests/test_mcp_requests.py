"""MCP: pressing a button, and the requests that wait for the account to allow it.

A press checks what a press in the browser checks. "Ask", and every dangerous
button even where pressing is allowed, waits; the account allows it within
ten minutes, and only then the button is pressed, with exactly the arguments
it was asked with and with the rights as they stand at that moment.
"""

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import db_session
from app.models import ActionLog, BoardShare, Event, McpRequest, Notice, User, utcnow
from app.services import mcp
from app.services.state import live

from .conftest import CSRF, create_user, login, setup_admin
from .mcp_kit import _quiet, board, call, docker_card, make_key, offer, switch  # noqa: F401


@pytest.fixture
def lab(client: TestClient) -> dict:
    setup_admin(client)
    switch(client)
    made = board(client)
    card = docker_card(client, made["pages"][0]["id"])
    return {"client": client, "board": made, "card": card}


def _presses() -> list[tuple[str, str, dict]]:
    with db_session() as db:
        return [(row.actor, row.action, row.params) for row in db.scalars(select(ActionLog).order_by(ActionLog.id))]


def _requests() -> list[McpRequest]:
    with db_session() as db:
        return list(db.scalars(select(McpRequest).order_by(McpRequest.id)))


def _ask(lab: dict, token: str, action: str = "restart") -> int:
    answer = call(lab["client"], token, "press_button", card_id=lab["card"]["id"], action=action, params={"id": "c1"})
    assert answer["error"] is False and answer["value"]["status"] == "waiting", answer
    return answer["value"]["request"]


# -- pressing -----------------------------------------------------------------------------------


def test_allowed_a_harmless_button_is_pressed_at_once_and_logged_as_the_key(lab: dict) -> None:
    client = lab["client"]
    _key, token = make_key(client, "act", rights={"press_button": "allow"})
    answer = call(client, token, "press_button", card_id=lab["card"]["id"], action="restart", params={"id": "c1"})
    assert answer == {"error": False, "value": {"status": "done", "message": "Demo mode: restart would have run now."}}
    assert _presses() == [("Claude (MCP)", "restart", {"id": "c1"})]
    with db_session() as db:
        line = db.scalar(select(Event).where(Event.kind == "mcp_call"))
        assert (line.name, line.after, line.detail) == ("Host", "Restart", "Restart on Host by Claude (MCP)")
        assert line.board_id == lab["board"]["id"]
    assert _requests() == []


def test_by_default_a_press_waits_for_approval_and_the_bell_says_so(lab: dict) -> None:
    client = lab["client"]
    _key, token = make_key(client, "act")
    number = _ask(lab, token)
    assert _presses() == [], "nothing is pressed before the account allows it"
    with db_session() as db:
        notice = db.scalar(select(Notice).where(Notice.event == "mcp_request"))
        assert notice.link == f"/mcp/requests/{number}" and "Restart" in notice.title and notice.level == "info"
        assert db.scalar(select(User.username).where(User.id == notice.user_id)) == "admin"
    shown = client.get(f"/api/v1/mcp/requests/{number}").json()
    assert {key: shown[key] for key in ("key_name", "tool", "card_id", "card", "board", "action", "label", "danger", "params", "status")} == {
        "key_name": "Claude", "tool": "press_button", "card_id": lab["card"]["id"], "card": "Host", "board": "Lab", "action": "restart",
        "label": "Restart", "danger": False, "params": {"id": "c1"}, "status": "waiting",
    }
    assert [fact["fact"] for fact in shown["impact"]] == ["up"]
    assert [row["id"] for row in client.get("/api/v1/mcp/requests?status=waiting").json()] == [number]
    status = call(client, token, "request_status", request=number)["value"]
    assert status["status"] == "waiting" and "result" not in status


def test_a_dangerous_button_asks_even_where_pressing_is_allowed(lab: dict) -> None:
    client = lab["client"]
    _key, token = make_key(client, "act", rights={"press_button": "allow"})
    number = _ask(lab, token, "stop")
    assert _presses() == []
    assert client.get(f"/api/v1/mcp/requests/{number}").json()["danger"] is True
    with db_session() as db:
        assert db.scalar(select(Notice.level).where(Notice.event == "mcp_request")) == "warn"


def test_approving_presses_exactly_what_was_asked_and_says_who_allowed_it(lab: dict) -> None:
    client = lab["client"]
    _key, token = make_key(client, "act")
    number = _ask(lab, token)
    answer = client.post(f"/api/v1/mcp/requests/{number}/approve", headers=CSRF)
    assert answer.status_code == 200, answer.text
    assert answer.json() == {"status": "approved", "result": {"message": "Demo mode: restart would have run now."}}
    assert _presses() == [("Claude (MCP), approved by admin", "restart", {"id": "c1"})]
    with db_session() as db:
        assert db.scalar(select(Event.detail).where(Event.kind == "mcp_call")) == "Restart on Host by Claude (MCP), approved by admin"
    status = call(client, token, "request_status", request=number)["value"]
    assert status["status"] == "approved" and status["result"] == {"message": "Demo mode: restart would have run now."}
    # Decided once, decided: a second click presses nothing.
    assert client.post(f"/api/v1/mcp/requests/{number}/approve", headers=CSRF).status_code == 409
    assert client.post(f"/api/v1/mcp/requests/{number}/decline", headers=CSRF).status_code == 409
    assert len(_presses()) == 1


def test_declining_presses_nothing(lab: dict) -> None:
    client = lab["client"]
    _key, token = make_key(client, "act")
    number = _ask(lab, token)
    assert client.post(f"/api/v1/mcp/requests/{number}/decline", headers=CSRF).json() == {"status": "declined", "result": None}
    assert client.post(f"/api/v1/mcp/requests/{number}/approve", headers=CSRF).status_code == 409
    assert _presses() == []
    assert call(client, token, "request_status", request=number)["value"]["status"] == "declined"


def test_the_arguments_cannot_be_changed_behind_the_request_s_back(lab: dict) -> None:
    client = lab["client"]
    _key, token = make_key(client, "act")
    number = _ask(lab, token)
    with db_session() as db:
        row = db.get(McpRequest, number)
        assert row.digest == mcp.digest(row.arguments)
        assert json.loads(row.arguments) == {"action": "restart", "card_id": lab["card"]["id"], "params": {"id": "c1"}}
        row.arguments = mcp.canonical({"action": "stop", "card_id": lab["card"]["id"], "params": {"id": "c1"}})
    answer = client.post(f"/api/v1/mcp/requests/{number}/approve", headers=CSRF).json()
    assert answer == {"status": "failed", "result": {"error": "The request does not match what was asked."}}
    assert _presses() == []


def test_a_request_runs_out_after_ten_minutes(lab: dict) -> None:
    client = lab["client"]
    _key, token = make_key(client, "act")
    number = _ask(lab, token)
    row = _requests()[0]
    assert timedelta(minutes=9, seconds=59) < row.expires_at - row.created_at <= timedelta(minutes=10)
    with db_session() as db:
        db.get(McpRequest, number).expires_at = utcnow() - timedelta(seconds=1)
    assert client.post(f"/api/v1/mcp/requests/{number}/approve", headers=CSRF).status_code == 409
    assert _presses() == []
    assert client.get(f"/api/v1/mcp/requests/{number}").json()["status"] == "expired"
    assert call(client, token, "request_status", request=number)["value"]["status"] == "expired"


def test_a_request_past_its_time_cannot_be_claimed_even_before_it_was_marked(lab: dict) -> None:
    """The time is checked in the same step that takes the request, not only by the sweep before it."""
    _key, token = make_key(lab["client"], "act")
    number = _ask(lab, token)
    with db_session() as db:
        db.get(McpRequest, number).expires_at = utcnow() - timedelta(seconds=1)
    with db_session() as db:
        row = db.get(McpRequest, number)
        with pytest.raises(mcp.McpError):
            mcp.claim(db, row, "approved", db.scalar(select(User)))
    assert _requests()[0].status == "waiting"


def test_the_minute_round_ends_requests_nobody_looked_at(lab: dict) -> None:
    _key, token = make_key(lab["client"], "act")
    number = _ask(lab, token)
    with db_session() as db:
        db.get(McpRequest, number).expires_at = utcnow() - timedelta(seconds=1)
    with db_session() as db:
        assert mcp.expire(db) == 1
    assert _requests()[0].status == "expired"


# -- the rights at the moment of approval -------------------------------------------------------


def test_approval_after_the_key_was_withdrawn_presses_nothing(lab: dict) -> None:
    client = lab["client"]
    key, token = make_key(client, "act")
    number = _ask(lab, token)
    client.delete(f"/api/v1/mcp/keys/{key['id']}", headers=CSRF)
    answer = client.post(f"/api/v1/mcp/requests/{number}/approve", headers=CSRF).json()
    assert answer["status"] == "failed" and answer["result"]["error"].startswith("This is no longer possible")
    assert _presses() == []


def test_approval_after_the_tool_was_blocked_presses_nothing(lab: dict) -> None:
    client = lab["client"]
    _key, token = make_key(client, "act")
    number = _ask(lab, token)
    switch(client, blocked_tools=["press_button"])
    assert client.post(f"/api/v1/mcp/requests/{number}/approve", headers=CSRF).json()["status"] == "failed"
    assert _presses() == []


def test_approval_after_the_card_stopped_offering_the_button_presses_nothing(lab: dict) -> None:
    client = lab["client"]
    _key, token = make_key(client, "act")
    number = _ask(lab, token)
    offer(lab["card"]["id"], restart=False)
    answer = client.post(f"/api/v1/mcp/requests/{number}/approve", headers=CSRF).json()
    assert answer["status"] == "failed" and "no longer possible" in answer["result"]["error"]
    assert _presses() == []


def test_approval_after_the_account_lost_its_right_on_the_board_presses_nothing(lab: dict) -> None:
    client = lab["client"]
    kim = create_user(client, "kim")
    assert client.put(f"/api/v1/boards/{lab['board']['slug']}/shares", json={"shares": [{"user_id": kim["id"], "level": "act"}]},
                      headers=CSRF).status_code == 200
    login(client, "kim", "another-long-password")
    _key, token = make_key(client, "act")
    number = _ask(lab, token)
    with db_session() as db:
        db.scalar(select(BoardShare).where(BoardShare.user_id == kim["id"])).level = "view"
    answer = client.post(f"/api/v1/mcp/requests/{number}/approve", headers=CSRF).json()
    assert answer["status"] == "failed" and "no longer possible" in answer["result"]["error"]
    assert _presses() == []


# -- who may press what --------------------------------------------------------------------------


def test_a_key_that_may_only_read_cannot_press(lab: dict) -> None:
    _key, token = make_key(lab["client"], "read", rights={"press_button": "allow"})
    answer = call(lab["client"], token, "press_button", card_id=lab["card"]["id"], action="restart", params={"id": "c1"})
    assert answer["error"] is True and answer["value"] == "No tool called 'press_button'."
    assert _presses() == [] and _requests() == []


def test_a_denied_press_is_no_tool_at_all(lab: dict) -> None:
    _key, token = make_key(lab["client"], "act", rights={"press_button": "deny"})
    answer = call(lab["client"], token, "press_button", card_id=lab["card"]["id"], action="restart", params={"id": "c1"})
    assert answer["value"] == "No tool called 'press_button'."
    assert _presses() == [] and _requests() == []


def test_a_button_the_card_does_not_offer_is_not_pressed(lab: dict) -> None:
    _key, token = make_key(lab["client"], "act", rights={"press_button": "allow"})
    for action, params in (("remove", {"id": "c1"}), ("restart", {"id": "../volumes/prune?x="}), ("restart", {})):
        answer = call(lab["client"], token, "press_button", card_id=lab["card"]["id"], action=action, params=params)
        assert answer["error"] is True and "card_details" in answer["value"]["error"], (action, params)
    assert _presses() == [] and _requests() == []


def test_a_button_the_card_does_not_offer_is_not_even_asked_for(lab: dict) -> None:
    _key, token = make_key(lab["client"], "act")
    answer = call(lab["client"], token, "press_button", card_id=lab["card"]["id"], action="remove", params={"id": "c1"})
    assert answer["error"] is True
    assert _requests() == [], "a request for a button nobody offered would put it in front of the account"


def test_approval_after_mcp_was_switched_off_presses_nothing(lab: dict) -> None:
    client = lab["client"]
    _key, token = make_key(client, "act")
    number = _ask(lab, token)
    switch(client, allowed=False)
    assert client.post(f"/api/v1/mcp/requests/{number}/approve", headers=CSRF).json()["status"] == "failed"
    assert _presses() == []


def test_a_member_who_may_only_look_at_the_board_cannot_press(lab: dict) -> None:
    client = lab["client"]
    kim = create_user(client, "kim")
    client.put(f"/api/v1/boards/{lab['board']['slug']}/shares", json={"shares": [{"user_id": kim["id"], "level": "view"}]}, headers=CSRF)
    login(client, "kim", "another-long-password")
    _key, token = make_key(client, "act", rights={"press_button": "allow"})
    answer = call(client, token, "press_button", card_id=lab["card"]["id"], action="restart", params={"id": "c1"})
    assert answer["error"] is True and "not press" in answer["value"]["error"]
    assert _presses() == [] and _requests() == []


def test_a_card_off_the_key_s_boards_is_pressed_like_one_that_does_not_exist(lab: dict) -> None:
    client = lab["client"]
    other = board(client, "Other")
    _key, token = make_key(client, "act", rights={"press_button": "allow"}, boards=[other["id"]])
    foreign = call(client, token, "press_button", card_id=lab["card"]["id"], action="restart", params={"id": "c1"})
    missing = call(client, token, "press_button", card_id=99999, action="restart", params={"id": "c1"})
    assert foreign == missing == {"error": True, "value": {"error": "No such card."}}
    assert _presses() == []


def test_only_the_account_decides_and_only_the_key_that_asked_learns_the_answer(lab: dict) -> None:
    client = lab["client"]
    _key, token = make_key(client, "act")
    _other, other = make_key(client, "act", name="Other")
    number = _ask(lab, token)
    assert call(client, other, "request_status", request=number)["value"] == call(client, other, "request_status", request=99999)["value"]
    create_user(client, "kim")
    login(client, "kim", "another-long-password")
    for path in (f"/api/v1/mcp/requests/{number}/approve", f"/api/v1/mcp/requests/{number}/decline"):
        assert client.post(path, headers=CSRF).status_code == 404
    assert client.get(f"/api/v1/mcp/requests/{number}").status_code == 404
    assert client.get("/api/v1/mcp/requests").json() == []
    assert _presses() == []


def _answer_together(lab: dict, monkeypatch: pytest.MonkeyPatch, paths: list[str]) -> list[int]:
    """Send these answers at one moment, each from a browser of its own, and return their status codes.

    Every request has read the row as "waiting" by the time any of them takes it: the barrier holds the
    first one at the door of ``claim`` until the second stands there too. Only a claim that decides in one
    step lets exactly one through.
    """
    original = mcp.claim
    gate = threading.Barrier(len(paths), timeout=15)

    def claim_together(db, row, status, user):  # noqa: ANN001, ANN202
        gate.wait()
        return original(db, row, status, user)

    monkeypatch.setattr(mcp, "claim", claim_together)
    browsers = []
    for _ in paths:
        other = TestClient(lab["client"].app)
        other.cookies.update(lab["client"].cookies)
        browsers.append(other)
    with ThreadPoolExecutor(max_workers=len(paths)) as pool:
        futures = [pool.submit(browser.post, path, headers=CSRF) for browser, path in zip(browsers, paths, strict=True)]
        return sorted(future.result().status_code for future in futures)


def test_two_approvals_at_the_same_moment_press_the_button_once(lab: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    _key, token = make_key(lab["client"], "act")
    number = _ask(lab, token)
    path = f"/api/v1/mcp/requests/{number}/approve"
    assert _answer_together(lab, monkeypatch, [path, path]) == [200, 409]
    assert len(_presses()) == 1
    assert _requests()[0].status == "approved"


def test_an_approval_and_a_decline_at_the_same_moment_decide_once(lab: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    _key, token = make_key(lab["client"], "act")
    number = _ask(lab, token)
    base = f"/api/v1/mcp/requests/{number}"
    assert _answer_together(lab, monkeypatch, [f"{base}/approve", f"{base}/decline"]) == [200, 409]
    row = _requests()[0]
    # Whichever was first stands, and the button ran if and only if it was the approval.
    assert (row.status, len(_presses())) in (("approved", 1), ("declined", 0))


def test_the_ceiling_lowered_between_asking_and_allowing_stops_the_press(lab: dict) -> None:
    client = lab["client"]
    _key, token = make_key(client, "act")
    number = _ask(lab, token)
    switch(client, max_level="read")
    approved = client.post(f"/api/v1/mcp/requests/{number}/approve", headers=CSRF)
    assert approved.status_code == 200 and approved.json()["status"] == "failed", approved.text
    assert "no longer possible" in approved.json()["result"]["error"]
    assert _presses() == []


def _caller_of(key_id: int):  # noqa: ANN202
    with db_session() as db:
        return mcp.caller_of_key(db, key_id)


def test_the_arguments_of_a_request_hold_at_most_64_kb(lab: dict) -> None:
    key, _token = make_key(lab["client"], "act")
    caller = _caller_of(key["id"])
    base = {"card_id": 1, "action": "restart", "pad": ""}
    room = mcp.MAX_REQUEST_BYTES - len(mcp.canonical(base).encode("utf-8"))
    assert mcp.MAX_REQUEST_BYTES == 64 * 1024

    def ask(arguments: dict) -> None:
        with db_session() as db:
            mcp.add_request(db, caller, "press_button", arguments, widget_id=None, card="Host", board="Lab", action="restart",
                            label="Restart", danger=False, impact=[])

    ask({**base, "pad": "x" * room})
    assert len(_requests()) == 1
    with pytest.raises(mcp.McpError) as refused:
        ask({**base, "pad": "x" * (room + 1)})
    assert refused.value.status == 413 and refused.value.code == "too_large"
    assert len(_requests()) == 1
    # Bytes, not characters: a character of two bytes counts for two.
    with pytest.raises(mcp.McpError):
        ask({**base, "pad": "é" * (room // 2 + 1)})


def test_a_guest_cannot_approve_but_may_say_no(lab: dict) -> None:
    client = lab["client"]
    kim = create_user(client, "kim")
    client.put(f"/api/v1/boards/{lab['board']['slug']}/shares", json={"shares": [{"user_id": kim["id"], "level": "act"}]}, headers=CSRF)
    login(client, "kim", "another-long-password")
    _key, token = make_key(client, "act")
    first, second = _ask(lab, token), _ask(lab, token)
    login(client, "admin", "correct-horse-battery")
    client.patch(f"/api/v1/users/{kim['id']}", json={"role": "guest"}, headers=CSRF)
    login(client, "kim", "another-long-password")
    assert client.post(f"/api/v1/mcp/requests/{first}/approve", headers=CSRF).status_code == 403
    assert client.post(f"/api/v1/mcp/requests/{second}/decline", headers=CSRF).status_code == 200
    assert _presses() == []


def test_a_key_may_keep_ten_waiting_and_an_account_twenty(lab: dict) -> None:
    client = lab["client"]
    _key, first = make_key(client, "act", name="first")
    for _ in range(mcp.MAX_WAITING_PER_KEY):
        _ask(lab, first)
    full = call(client, first, "press_button", card_id=lab["card"]["id"], action="restart", params={"id": "c1"})
    assert full["error"] is True and "10 requests of this key" in full["value"]["error"]
    _key, second = make_key(client, "act", name="second")
    _key, third = make_key(client, "act", name="third")
    for _ in range(mcp.MAX_WAITING_PER_KEY):
        _ask(lab, second)
    over = call(client, third, "press_button", card_id=lab["card"]["id"], action="restart", params={"id": "c1"})
    assert over["error"] is True and "20 requests wait for this account" in over["value"]["error"]
    assert len(_requests()) == 20
    # Decided ones make room again.
    client.post(f"/api/v1/mcp/requests/{_requests()[0].id}/decline", headers=CSRF)
    _ask(lab, third)


def test_the_list_filters_by_status_and_refuses_one_that_does_not_exist(lab: dict) -> None:
    client = lab["client"]
    _key, token = make_key(client, "act")
    first, second = _ask(lab, token), _ask(lab, token)
    client.post(f"/api/v1/mcp/requests/{first}/decline", headers=CSRF)
    assert [row["id"] for row in client.get("/api/v1/mcp/requests").json()] == [second, first]
    assert [row["id"] for row in client.get("/api/v1/mcp/requests?status=declined").json()] == [first]
    assert client.get("/api/v1/mcp/requests?status=whatever").status_code == 422
    assert live.get(lab["card"]["id"]) is not None


def test_decided_requests_are_swept_with_the_action_log_and_waiting_ones_never(lab: dict) -> None:
    from app.services import retention

    client = lab["client"]
    _key, token = make_key(client, "act")
    old, young, waiting = _ask(lab, token), _ask(lab, token), _ask(lab, token)
    for number in (old, young):
        client.post(f"/api/v1/mcp/requests/{number}/decline", headers=CSRF)
    with db_session() as db:
        for number in (old, waiting):
            db.get(McpRequest, number).created_at = utcnow() - timedelta(days=400)
        db.get(McpRequest, waiting).expires_at = utcnow() + timedelta(minutes=5)
    with db_session() as db:
        gone = retention.prune_old_records(db)
    assert gone["mcp_requests"] == 1
    assert [row.id for row in _requests()] == [young, waiting]


def test_a_press_that_breaks_unexpectedly_fails_the_request_instead_of_leaving_it_half_done(lab: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.collector import collector

    client = lab["client"]
    _key, token = make_key(client, "act")
    number = _ask(lab, token)

    async def broken(*_args: object, **_kwargs: object) -> str:
        raise RuntimeError("socket gone")

    monkeypatch.setattr(collector, "run_action", broken)
    answer = client.post(f"/api/v1/mcp/requests/{number}/approve", headers=CSRF)
    assert answer.status_code == 200 and answer.json() == {"status": "failed", "result": {"error": "The button failed (RuntimeError)."}}
    _key, allowed = make_key(client, "act", name="allowed", rights={"press_button": "allow"})
    pressed = call(client, allowed, "press_button", card_id=lab["card"]["id"], action="restart", params={"id": "c1"})
    assert pressed == {"error": True, "value": {"error": "The tool failed (RuntimeError)."}}


def test_a_check_that_breaks_unexpectedly_fails_the_request_too(lab: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    """Claimed already, a request must not stay "approved" with no answer when the check before the press breaks."""
    from app.services.collector import collector

    client = lab["client"]
    _key, token = make_key(client, "act")
    number = _ask(lab, token)

    def broken(*_args: object, **_kwargs: object) -> dict:
        raise RuntimeError("cache gone")

    monkeypatch.setattr(collector, "_refuse_unless_offered", broken)
    answer = client.post(f"/api/v1/mcp/requests/{number}/approve", headers=CSRF)
    assert answer.status_code == 200
    assert answer.json() == {"status": "failed", "result": {"error": "This is no longer possible (RuntimeError)."}}
    assert _presses() == []


def test_every_call_leaves_a_line_in_the_log(lab: dict, caplog: pytest.LogCaptureFixture) -> None:
    client = lab["client"]
    key, token = make_key(client, "act", rights={"press_button": "allow"})
    with caplog.at_level("INFO", logger="nexdeck.mcp"):
        call(client, token, "press_button", card_id=lab["card"]["id"], action="restart", params={"id": "c1"})
        call(client, token, "request_status", request=99999)
        call(client, token, "find_cards")
    assert f"MCP tool press_button called by key {key['id']}." in caplog.text
    assert f"MCP tool request_status called by key {key['id']}: No such request." in caplog.text
    assert f"MCP tool find_cards called by key {key['id']}." in caplog.text
