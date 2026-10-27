"""KARTEN-8: pressing a button of a custom card, through the same way as every other action (AC-5 to AC-9, EC-1 to EC-9).

The card is a list of downloads on a JSON API connection whose token signs every request; ``respx`` stands in for the
service and counts what leaves. A press goes through ``POST /widgets/{id}/actions/{action}``: the right to act, the kiosk,
the demo mode, the action log, the journal and the guard of what was offered are the ones every card has.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.adapters import get_adapter
from app.adapters.base import NOT_READ_BY_CARDS, AdapterError, Context
from app.cards import buttons, load, store
from app.db import db_session
from app.models import ActionLog, Event, Notice
from app.services import collector as collector_module
from app.services.collector import collector

from .conftest import CSRF, create_user, login, setup_admin
from .karten8_sample import DOWNLOADS, button, with_buttons

BASE = "http://svc.example.com:8080"
SECRET = "Zk-SuperSecret-0123456789"
LIST = f"{BASE}/api/v2/torrents/info"
ROWS = [{"name": "Ubuntu", "hash": "abc123", "progress": 50}, {"name": "Debian", "hash": "def456", "progress": 100}]


class Stand:
    """An administrator, a board with the card on a JSON API connection, and what the card spawned afterwards."""

    def __init__(self, client: TestClient, board: dict[str, Any], widget: int, integration: int) -> None:
        self.client = client
        self.board = board
        self.widget = widget
        self.integration = integration
        self.spawned: list[str] = []

    def refresh(self, rows: Any = None) -> dict[str, Any]:
        # The answers of a connection are kept for a few seconds; a new answer is what this refresh is for.
        collector._caches.clear()
        respx.get(LIST, name="list").mock(return_value=httpx.Response(200, json=ROWS if rows is None else rows))
        answer = self.client.post(f"/api/v1/widgets/{self.widget}/refresh", headers=CSRF)
        assert answer.status_code == 200, answer.text
        return answer.json()

    def press(self, action: str, params: dict[str, Any], client: TestClient | None = None, **headers: str) -> httpx.Response:
        return (client or self.client).post(f"/api/v1/widgets/{self.widget}/actions/{action}", json={"params": params}, headers={**CSRF, **headers})

    def define(self, text: str) -> None:
        """The saved card replaced by another text with the same short name, as the editor saves it."""
        put = self.client.put("/api/v1/cards/downloads", json={"yaml": text}, headers=CSRF)
        assert put.status_code == 200, put.text


def make_stand(client: TestClient, monkeypatch: pytest.MonkeyPatch, text: str = DOWNLOADS, *, demo: bool = False, kind: str = "custom.list") -> Stand:
    setup_admin(client)
    monkeypatch.setattr(collector, "running", False)
    # Two presses of refresh in a row are one fetch on a board; here the second has a new answer to show.
    monkeypatch.setattr(collector_module, "REFRESH_NOW_GAP", 0.0)
    stand_ref: dict[str, Stand] = {}

    def spawn(factory: Any, *, name: str = "") -> None:
        stand_ref["s"].spawned.append(name)

    monkeypatch.setattr(collector_module, "spawn", spawn)
    with db_session() as db:
        store.create(db, text)
    connection = client.post(
        "/api/v1/integrations",
        json={"kind": "jsonapi", "name": "Torrents", "config": {"url": BASE, "token": SECRET}, "demo": demo},
        headers=CSRF,
    )
    assert connection.status_code == 201, connection.text
    board = client.post("/api/v1/boards", json={"name": "Wall"}, headers=CSRF).json()
    widget = client.post(
        f"/api/v1/pages/{board['pages'][0]['id']}/widgets",
        json={"kind": kind, "integration_id": connection.json()["id"], "options": {"card": "downloads"}},
        headers=CSRF,
    )
    assert widget.status_code == 201, widget.text
    stand_ref["s"] = Stand(client, board, int(widget.json()["widget"]["id"]), int(connection.json()["id"]))
    return stand_ref["s"]


@pytest.fixture
def stand(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> Stand:
    return make_stand(client, monkeypatch)


def logged() -> list[tuple[str, str, dict[str, Any], bool, str]]:
    with db_session() as db:
        return [(one.actor, one.action, dict(one.params or {}), one.ok, one.message) for one in db.scalars(select(ActionLog).order_by(ActionLog.id))]


def noticed() -> list[tuple[str, str, str]]:
    with db_session() as db:
        return [(one.event, one.title, one.body) for one in db.scalars(select(Notice).order_by(Notice.id))]


def code_of(answer: httpx.Response) -> str:
    return str(answer.json()["detail"]["code"])


# -- AC-1, AC-2: on the board ---------------------------------------------------------------------------------------


@respx.mock
def test_karten8_ac2_the_card_on_the_board_offers_its_buttons_on_the_card_and_on_each_row(stand: Stand) -> None:
    shown = stand.refresh()
    assert [one["id"] for one in shown["actions"]] == ["button:limit"]
    assert [[(one["id"], one["params"]) for one in item["actions"]] for item in shown["items"]] == [
        [("button:pause", {"hash": "abc123"}), ("button:delete", {"hash": "abc123"})],
        [("button:pause", {"hash": "def456"}), ("button:delete", {"hash": "def456"})],
    ]


# -- AC-9: the answer ---------------------------------------------------------------------------------------------------


@respx.mock
def test_karten8_ac9_a_press_sends_one_signed_request_says_done_and_reloads_the_card(stand: Stand) -> None:
    stand.refresh()
    pause = respx.post(f"{BASE}/api/v2/torrents/pause").mock(return_value=httpx.Response(200, text="Ok."))
    answer = stand.press("button:pause", {"hash": "def456"})
    assert answer.status_code == 200, answer.text
    assert answer.json() == {"ok": True, "message": "Done"}, "the service's own text appears only when the button names a field"
    [call] = pause.calls
    assert call.request.headers["authorization"] == f"Bearer {SECRET}"
    assert call.request.headers["content-type"].startswith("application/x-www-form-urlencoded")
    assert dict(httpx.QueryParams(call.request.content.decode())) == {"hashes": "def456"}
    assert f"refresh-{stand.widget}" in stand.spawned


@respx.mock
def test_karten8_ac9_a_delete_puts_the_value_of_its_row_into_the_path(stand: Stand) -> None:
    stand.refresh()
    gone = respx.delete(f"{BASE}/api/v2/torrents/abc123").mock(return_value=httpx.Response(204))
    assert stand.press("button:delete", {"hash": "abc123"}).json()["message"] == "Done"
    assert gone.call_count == 1 and gone.calls.last.request.content == b""


@pytest.mark.parametrize(
    ("answer", "shown"),
    [
        ({"result": {"message": "Search started"}}, "Search started"),
        ({"result": {"message": 42}}, "42"),
        ({"result": {"message": "x" * 300}}, "x" * 199 + "…"),
        ({"result": {"message": "two\nlines\x07"}}, "two lines"),
        ({"result": {}}, "Done"),
        ({"result": {"message": ["a", "b"]}}, '["a", "b"]'),
    ],
)
@respx.mock
def test_karten8_ac9_the_field_the_button_names_is_shown_instead_of_done(client: TestClient, monkeypatch: pytest.MonkeyPatch, answer: Any, shown: str) -> None:
    text = with_buttons(button(path="/api/search", answer="result.message"))
    stand = make_stand(client, monkeypatch, text)
    stand.refresh()
    respx.post(f"{BASE}/api/search").mock(return_value=httpx.Response(200, json=answer))
    assert stand.press("button:go", {}).json()["message"] == shown


@respx.mock
def test_karten8_ac9_an_answer_that_is_no_json_says_done_even_with_a_field_named(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    stand = make_stand(client, monkeypatch, with_buttons(button(path="/api/search", answer="result")))
    stand.refresh()
    respx.post(f"{BASE}/api/search").mock(return_value=httpx.Response(200, text="<html>fine</html>"))
    assert stand.press("button:go", {}).json()["message"] == "Done"


@pytest.mark.parametrize("status", [400, 404, 409, 500, 503])
@respx.mock
def test_karten8_ac9_an_error_names_the_status_and_never_the_text_of_the_service(stand: Stand, status: int) -> None:
    stand.refresh()
    respx.post(f"{BASE}/api/v2/torrents/pause").mock(return_value=httpx.Response(status, text="Stack trace: secret internals"))
    answer = stand.press("button:pause", {"hash": "abc123"})
    assert answer.status_code == 400 and code_of(answer) == "http_error"
    assert answer.json()["detail"]["message"] == f"The service answered HTTP {status}." and "internals" not in answer.text
    assert logged()[-1][3] is False and f"refresh-{stand.widget}" not in stand.spawned


@pytest.mark.parametrize("status", [401, 403])
@respx.mock
def test_karten8_ac9_a_refused_sign_in_is_auth_failed(stand: Stand, status: int) -> None:
    stand.refresh()
    respx.post(f"{BASE}/api/v2/torrents/pause").mock(return_value=httpx.Response(status))
    answer = stand.press("button:pause", {"hash": "abc123"})
    assert code_of(answer) == "auth_failed"


# -- AC-5: who may press ----------------------------------------------------------------------------------------------------


@respx.mock
def test_karten8_ac5_without_the_right_to_act_or_on_a_kiosk_without_actions_the_press_is_refused_and_nothing_leaves(stand: Stand) -> None:
    stand.refresh()
    pause = respx.post(f"{BASE}/api/v2/torrents/pause").mock(return_value=httpx.Response(200))
    kim = create_user(stand.client, "kim")
    member = TestClient(stand.client.app)
    login(member, "kim", "another-long-password")
    for level, expected in (("view", 403), ("edit", 403), ("act", 200)):
        shared = stand.client.put(f"/api/v1/boards/{stand.board['slug']}/shares", json={"shares": [{"user_id": kim["id"], "level": level}]}, headers=CSRF)
        assert shared.status_code == 200, shared.text
        before = pause.call_count
        assert stand.press("button:pause", {"hash": "abc123"}, member).status_code == expected, level
        assert pause.call_count == before + (expected == 200), level
    for allowed, expected in ((False, 403), (True, 200)):
        made = stand.client.post(f"/api/v1/boards/{stand.board['slug']}/kiosk-tokens", json={"name": f"hall {allowed}", "allow_actions": allowed}, headers=CSRF)
        display = TestClient(stand.client.app)
        before = pause.call_count
        assert stand.press("button:pause", {"hash": "abc123"}, display, **{"X-Kiosk-Token": made.json()["token"]}).status_code == expected
        assert pause.call_count == before + (expected == 200), allowed
    assert [entry[0] for entry in logged()] == ["kim", "kiosk:hall True"]


# -- AC-6: the action log and the journal -------------------------------------------------------------------------------------


@respx.mock
def test_karten8_ac6_a_press_stands_in_the_action_log_and_in_the_journal_like_any_action(stand: Stand) -> None:
    stand.refresh()
    respx.post(f"{BASE}/api/v2/torrents/pause").mock(side_effect=[httpx.Response(200), httpx.Response(500)])
    stand.press("button:pause", {"hash": "abc123"})
    stand.press("button:pause", {"hash": "def456"})
    assert logged() == [
        ("admin", "button:pause", {"hash": "abc123"}, True, "Done"),
        ("admin", "button:pause", {"hash": "def456"}, False, "The service answered HTTP 500."),
    ]
    events = [one[0] for one in noticed()]
    assert "action_done" in events and "action_failed" in events
    assert any(title.startswith("button:pause on") for _event, title, _body in noticed())


# -- AC-7: demo mode ---------------------------------------------------------------------------------------------------------


@respx.mock
def test_karten8_ac7_in_demo_mode_nothing_leaves_and_the_card_says_it_would_have_run(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    stand = make_stand(client, monkeypatch, demo=True)
    everything = respx.route().mock(return_value=httpx.Response(200, json=ROWS))
    shown = client.post(f"/api/v1/widgets/{stand.widget}/refresh", headers=CSRF).json()
    assert [one["params"] for one in shown["items"][0]["actions"]] == [{"hash": "abc123"}, {"hash": "abc123"}], "the demo answers carry the buttons"
    answer = stand.press("button:pause", {"hash": "abc123"})
    assert answer.status_code == 200 and "would have run now" in answer.json()["message"]
    assert everything.call_count == 0


# -- AC-8, EC-3: only what was offered -------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "params",
    [{"hash": "zzz999"}, {"hash": "abc123", "deleteFiles": "true"}, {}, {"hash": "../../app/shutdown"}, {"hash": ["abc123"]}],
)
@respx.mock
def test_karten8_ac8_values_the_card_did_not_offer_are_refused_and_nothing_leaves(stand: Stand, params: dict[str, Any]) -> None:
    stand.refresh()
    everything = respx.route(method__in=["POST", "PUT", "PATCH", "DELETE"]).mock(return_value=httpx.Response(200))
    answer = stand.press("button:delete", params)
    assert answer.status_code == 400 and code_of(answer) == "no_longer_offered"
    assert everything.call_count == 0


@pytest.mark.parametrize("given", [True, 1.0])
@respx.mock
def test_karten8_ac8_a_value_of_another_type_that_python_calls_equal_is_not_what_was_offered(stand: Stand, given: Any) -> None:
    shown = stand.refresh(rows=[{"name": "One", "hash": 1, "progress": 1}])
    assert shown["items"][0]["actions"][1]["params"] == {"hash": 1}
    everything = respx.route(method__in=["POST", "PUT", "PATCH", "DELETE"]).mock(return_value=httpx.Response(200))
    answer = stand.press("button:delete", {"hash": given})
    assert answer.status_code == 400 and code_of(answer) == "no_longer_offered" and everything.call_count == 0
    # the value as it was offered still goes out
    respx.delete(f"{BASE}/api/v2/torrents/1").mock(return_value=httpx.Response(200))
    assert stand.press("button:delete", {"hash": 1}).status_code == 200


@respx.mock
def test_karten8_a_label_per_language_reaches_the_assistant_as_one_text(stand: Stand) -> None:
    from app.models import User
    from app.services.assistant import tools

    stand.refresh()
    with db_session() as db:
        user = db.scalars(select(User)).first()
        bench = tools.Bench(db=db, user=user, grants=[])
        details = json.loads(tools.card_details(bench, {"card_id": stand.widget}))
        asyncio.run(tools.propose_action(bench, {"card_id": stand.widget, "action": "button:pause", "params": {"hash": "abc123"}}))
    [proposal] = bench.proposals
    assert proposal["label"] == "Pause" and all(isinstance(one["label"], str) for one in details["buttons"]), (proposal, details)


@respx.mock
def test_karten8_ac8_a_button_the_card_never_had_is_refused(stand: Stand) -> None:
    stand.refresh()
    everything = respx.route(method__in=["POST", "PUT", "PATCH", "DELETE"]).mock(return_value=httpx.Response(200))
    assert code_of(stand.press("button:reboot", {})) == "no_longer_offered"
    assert everything.call_count == 0


@respx.mock
def test_karten8_ec3_a_row_that_is_gone_when_the_button_is_pressed_is_no_longer_offered(stand: Stand) -> None:
    stand.refresh()
    again = stand.refresh(rows=[ROWS[1]])
    assert [item["title"] for item in again["items"]] == ["Debian"], again
    everything = respx.route(method__in=["POST", "PUT", "PATCH", "DELETE"]).mock(return_value=httpx.Response(200))
    answer = stand.press("button:pause", {"hash": "abc123"})
    assert code_of(answer) == "no_longer_offered" and "No longer offered" in answer.json()["detail"]["message"]
    assert everything.call_count == 0
    assert stand.press("button:pause", {"hash": "def456"}).status_code == 200


def test_karten8_ec3_the_built_in_cards_keep_their_own_words() -> None:
    from app.adapters.base import Action, WidgetData
    from app.services.state import live

    live.set(9_018, WidgetData(actions=[Action(id="restart", label="Restart")]))
    try:
        with pytest.raises(AdapterError) as refused:
            collector._refuse_unless_offered(9_018, "stop", {})
        assert refused.value.code == "no_such_action"
    finally:
        live.forget(9_018)


# -- the definition changed between showing and pressing ------------------------------------------------------------------------


@respx.mock
def test_karten8_a_button_removed_since_it_was_shown_is_no_longer_offered(stand: Stand) -> None:
    stand.refresh()
    stand.define(with_buttons(button(id="other")))
    everything = respx.route(method__in=["POST", "PUT", "PATCH", "DELETE"]).mock(return_value=httpx.Response(200))
    assert code_of(stand.press("button:pause", {"hash": "abc123"})) == "no_longer_offered"
    assert everything.call_count == 0


@respx.mock
def test_karten8_a_path_changed_since_it_was_shown_is_the_new_path_with_the_values_that_were_offered(stand: Stand) -> None:
    stand.refresh()
    changed = with_buttons(dict(button(id="pause", where="row", path="/api/v3/torrents/{hash}/pause")))
    stand.define(changed)
    moved = respx.post(f"{BASE}/api/v3/torrents/abc123/pause").mock(return_value=httpx.Response(200))
    assert stand.press("button:pause", {"hash": "abc123"}).status_code == 200
    assert moved.call_count == 1


@respx.mock
def test_karten8_a_new_placeholder_since_it_was_shown_is_no_longer_offered(stand: Stand) -> None:
    stand.refresh()
    stand.define(with_buttons(dict(button(id="pause", where="row", path="/api/{name}/{hash}"))))
    everything = respx.route(method__in=["POST", "PUT", "PATCH", "DELETE"]).mock(return_value=httpx.Response(200))
    assert code_of(stand.press("button:pause", {"hash": "abc123"})) == "no_longer_offered"
    assert everything.call_count == 0


# -- EC-1: values in the path ----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["../admin", "a/b", "a\\b", "a?b", "a#b", "%2e", "%2E", "%2e%2e", ".", "..", "a b", "", "\x00", None, ["x"]])
def test_karten8_ec1_a_value_that_cannot_go_into_the_path_is_refused_before_sending(value: Any) -> None:
    pressed = load.load_definition(DOWNLOADS).definition.buttons[2]
    with pytest.raises(AdapterError) as refused:
        buttons.press(pressed, {"hash": value})
    assert refused.value.code == "bad_value" and refused.value.message == "A value of this button cannot go into an address."


@respx.mock
def test_karten8_ec1_a_single_dot_from_the_data_is_not_offered_and_nothing_goes_out(stand: Stand) -> None:
    shown = stand.refresh(rows=[{"name": "Evil", "hash": ".", "progress": 1}])
    offered = [one["id"] for one in shown["items"][0].get("actions") or []]
    sent = respx.route(method__in=["POST", "PUT", "PATCH", "DELETE"]).mock(return_value=httpx.Response(200))
    answer = stand.press("button:delete", {"hash": "."})
    assert "button:delete" not in offered and answer.status_code == 400 and sent.call_count == 0, (offered, answer.text)


@pytest.mark.parametrize("path", ["/api/v2/torrents/.", "/api/./x", "/api/v2/torrents/./x/."])
@respx.mock
def test_karten8_ec1_the_path_that_goes_out_is_the_path_that_was_put_together(monkeypatch: pytest.MonkeyPatch, path: str) -> None:
    # Even when the first check lets a path through, the second wall stops what the client would shorten.
    from app.cards import schema

    monkeypatch.setattr(schema, "stays_underneath", lambda _path: True)
    sent = respx.route(method__in=["POST", "PUT", "PATCH", "DELETE"]).mock(return_value=httpx.Response(200))
    adapter, config = get_adapter("qbittorrent"), {"url": BASE, "username": "admin", "password": "pw-Zk-1"}
    ctx = Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})
    with pytest.raises(AdapterError) as refused:
        asyncio.run(adapter.raw_act("DELETE", path, config, ctx))
    assert refused.value.code == "bad_path" and sent.call_count == 0


@pytest.mark.parametrize(("value", "path"), [("abc123", "/api/v2/torrents/abc123"), (7, "/api/v2/torrents/7"), ("a&b=c", "/api/v2/torrents/a%26b%3Dc"), ("Ünï", "/api/v2/torrents/%C3%9Cn%C3%AF")])
def test_karten8_ec1_a_plain_value_is_one_piece_of_the_path(value: Any, path: str) -> None:
    pressed = load.load_definition(DOWNLOADS).definition.buttons[2]
    assert buttons.press(pressed, {"hash": value}) == (path, None)


# -- EC-4: redirects ---------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("target", ["http://elsewhere.example.com/x", f"{BASE}/api/v2/torrents/pause2"])
@respx.mock
def test_karten8_ec4_a_redirect_is_not_followed_and_the_credentials_go_nowhere_else(stand: Stand, target: str) -> None:
    stand.refresh()
    respx.post(f"{BASE}/api/v2/torrents/pause").mock(return_value=httpx.Response(307, headers={"location": target}))
    elsewhere = respx.route(host="elsewhere.example.com").mock(return_value=httpx.Response(200))
    same = respx.post(f"{BASE}/api/v2/torrents/pause2").mock(return_value=httpx.Response(200))
    answer = stand.press("button:pause", {"hash": "abc123"})
    assert code_of(answer) == "redirected"
    assert answer.json()["detail"]["message"] == "The service answered with a redirect; nexdeck does not follow it."
    assert elsewhere.call_count == 0 and same.call_count == 0


# -- EC-6: two at once ----------------------------------------------------------------------------------------------------------------


@respx.mock
def test_karten8_ec6_two_people_pressing_at_once_both_go_out_and_both_are_logged(stand: Stand) -> None:
    stand.refresh()
    started = asyncio.Event()
    waiting: list[int] = []

    async def slow(request: httpx.Request) -> httpx.Response:
        waiting.append(1)
        if len(waiting) == 2:
            started.set()
        await asyncio.wait_for(started.wait(), 5)
        return httpx.Response(200)

    pause = respx.post(f"{BASE}/api/v2/torrents/pause").mock(side_effect=slow)

    async def both() -> list[str]:
        return await asyncio.gather(
            collector.run_action(stand.widget, "button:pause", {"hash": "abc123"}, actor="ann", user_id=None),
            collector.run_action(stand.widget, "button:pause", {"hash": "abc123"}, actor="bob", user_id=None),
        )

    assert asyncio.run(both()) == ["Done", "Done"]
    assert pause.call_count == 2, "nothing on the server holds the second one back"
    assert sorted(entry[0] for entry in logged()) == ["ann", "bob"]


# -- EC-7: no answer after sending ------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("failure", "code", "message"),
    [
        (httpx.ReadTimeout("slow"), "no_answer", "No answer. It may have run; check the service."),
        (httpx.RemoteProtocolError("closed"), "no_answer", "No answer. It may have run; check the service."),
        (httpx.ReadError("reset"), "no_answer", "No answer. It may have run; check the service."),
        (httpx.ConnectError("refused"), "unreachable", "The service could not be reached: ConnectError."),
        (httpx.ConnectTimeout("no route"), "unreachable", "The service did not answer in time."),
    ],
)
@respx.mock
def test_karten8_ec7_a_connection_that_breaks_after_sending_says_it_may_have_run(stand: Stand, failure: Exception, code: str, message: str) -> None:
    stand.refresh()
    respx.post(f"{BASE}/api/v2/torrents/pause").mock(side_effect=failure)
    answer = stand.press("button:pause", {"hash": "abc123"})
    assert (code_of(answer), answer.json()["detail"]["message"]) == (code, message)


# -- EC-8: values with quotes and brackets ------------------------------------------------------------------------------------------------

ODD = 'He said "hi" {x} [1] \\ ✓ \'quoted\' </b>'


@respx.mock
def test_karten8_ec8_a_value_with_quotes_braces_and_backslashes_goes_in_as_a_value_and_a_number_stays_a_number(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    body = {"name": "{name}", "note": "Title: {name}!", "progress": "{progress}", "nested": {"ids": ["{progress}", "fixed"], "flag": True, "none": None}}
    stand = make_stand(client, monkeypatch, with_buttons(button(where="row", path="/api/add", body=body)))
    stand.refresh(rows=[{"name": ODD, "progress": 12.5, "hash": "h"}])
    sent = respx.post(f"{BASE}/api/add").mock(return_value=httpx.Response(200))
    assert stand.press("button:go", {"name": ODD, "progress": 12.5}).status_code == 200
    request = sent.calls.last.request
    assert request.headers["content-type"] == "application/json"
    assert json.loads(request.content) == {
        "name": ODD, "note": f"Title: {ODD}!", "progress": 12.5, "nested": {"ids": [12.5, "fixed"], "flag": True, "none": None},
    }


@respx.mock
def test_karten8_ec8_a_form_takes_the_value_as_text_unchanged(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    stand = make_stand(client, monkeypatch, with_buttons(button(where="row", path="/api/add", send="form", body={"name": "{name}", "on": "{on}"})))
    stand.refresh(rows=[{"name": ODD, "on": True}])
    sent = respx.post(f"{BASE}/api/add").mock(return_value=httpx.Response(200))
    assert stand.press("button:go", {"name": ODD, "on": True}).status_code == 200
    assert dict(httpx.QueryParams(sent.calls.last.request.content.decode())) == {"name": ODD, "on": "true"}


# -- EC-9 and AC-4: blanks ---------------------------------------------------------------------------------------------------------------------


@respx.mock
def test_karten8_ec9_a_blank_out_of_range_or_of_the_wrong_type_is_refused_before_anything_leaves(stand: Stand) -> None:
    stand.refresh()
    limit = respx.post(f"{BASE}/api/v2/transfer/setDownloadLimit").mock(return_value=httpx.Response(200))
    for wrong in (100001, -1, "fast", 1.5, None, True):
        answer = stand.press("button:limit", {"ask.kib": wrong})
        assert answer.status_code == 400 and code_of(answer) == "bad_value", wrong
    assert limit.call_count == 0
    assert stand.press("button:limit", {"ask.kib": 512}).status_code == 200
    assert dict(httpx.QueryParams(limit.calls.last.request.content.decode())) == {"limit": "512"}


@pytest.mark.parametrize(
    "ask",
    [
        {"name": "kib", "label": "KiB?", "type": "number", "min": 0, "max": 10, "step": 1},
        {"name": "kib", "label": "KiB?", "type": "choice", "options": [{"value": "1", "label": "One"}]},
        {"name": "kib", "label": "KiB?", "type": "text", "max_length": 2},
    ],
)
@respx.mock
def test_karten8_ec9_a_blank_changed_since_it_was_shown_is_checked_against_the_definition_as_it_is_now(stand: Stand, ask: dict[str, Any]) -> None:
    stand.refresh()
    limit = dict(button(id="limit", path="/api/v2/transfer/setDownloadLimit", send="form", body={"limit": "{ask.kib}"}, asks=[ask]))
    stand.define(with_buttons(limit))
    sent = respx.route(method__in=["POST", "PUT", "PATCH", "DELETE"]).mock(return_value=httpx.Response(200))
    answer = stand.press("button:limit", {"ask.kib": "500" if ask["type"] != "number" else 500})
    assert answer.status_code == 400 and code_of(answer) == "bad_value" and sent.call_count == 0, answer.text


@respx.mock
def test_karten8_ec9_a_blank_the_definition_has_gained_since_is_no_longer_offered(stand: Stand) -> None:
    stand.refresh()
    asks = [{"name": "extra", "label": "Extra?", "type": "number", "min": 0, "max": 5, "step": 1}]
    stand.define(with_buttons(button(id="limit", path="/api/v2/transfer/setDownloadLimit", send="form", body={"limit": "{ask.kib}", "extra": "{ask.extra}"}, asks=asks + [{"name": "kib", "label": "KiB?", "type": "number", "min": 0, "max": 100000, "step": 1}])))
    sent = respx.route(method__in=["POST", "PUT", "PATCH", "DELETE"]).mock(return_value=httpx.Response(200))
    answer = stand.press("button:limit", {"ask.kib": 512})
    assert code_of(answer) == "no_longer_offered" and sent.call_count == 0, answer.text


@respx.mock
def test_karten8_ac4_a_number_blank_in_a_json_body_stays_a_number(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    asks = [{"name": "minutes", "label": "How many minutes?", "type": "number", "min": 1, "max": 120, "step": 1}]
    stand = make_stand(client, monkeypatch, with_buttons(button(body={"duration": "{ask.minutes}", "text": "{ask.minutes} min"}, asks=asks)))
    stand.refresh()
    sent = respx.post(f"{BASE}/api/go").mock(return_value=httpx.Response(200))
    assert stand.press("button:go", {"ask.minutes": "30"}).status_code == 200
    assert json.loads(sent.calls.last.request.content) == {"duration": 30, "text": "30 min"}


# -- what a button may reach ---------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("kind", sorted(NOT_READ_BY_CARDS))
def test_karten8_a_kind_a_card_cannot_read_has_no_buttons_either(kind: str) -> None:
    try:
        adapter = get_adapter(kind)
    except KeyError:
        pytest.skip(f"{kind} is not a kind of this build")
    with pytest.raises(AdapterError) as refused:
        asyncio.run(adapter.raw_act("POST", "/x", {"url": BASE}, Context(httpx.AsyncClient())))
    assert refused.value.code == "no_raw_access"


@pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS", "TRACE"])
def test_karten8_a_button_never_sends_a_get_or_anything_else_that_is_not_a_change(method: str) -> None:
    with pytest.raises(AdapterError) as refused:
        asyncio.run(get_adapter("jsonapi").raw_act(method, "/x", {"url": BASE}, Context(httpx.AsyncClient())))
    assert refused.value.code == "method_refused"


@pytest.mark.parametrize("path", ["//elsewhere.example.com/x", "/a/../b", "/a/%2e%2e/b", "x"])
@respx.mock
def test_karten8_raw_act_itself_keeps_a_path_underneath_the_address(path: str) -> None:
    everything = respx.route().mock(return_value=httpx.Response(200))
    with pytest.raises(AdapterError) as refused:
        asyncio.run(get_adapter("jsonapi").raw_act("POST", path, {"url": BASE}, Context(httpx.AsyncClient())))
    assert refused.value.code == "bad_path" and everything.call_count == 0


@respx.mock
def test_karten8_a_body_larger_than_64_kb_does_not_leave() -> None:
    everything = respx.route().mock(return_value=httpx.Response(200))
    with pytest.raises(AdapterError) as refused:
        asyncio.run(get_adapter("jsonapi").raw_act("POST", "/x", {"url": BASE}, Context(httpx.AsyncClient()), json_body={"a": "x" * 70_000}))
    assert refused.value.code == "body_too_large" and everything.call_count == 0


@respx.mock
def test_karten8_an_answer_larger_than_256_kb_is_not_read_and_may_have_run(stand: Stand) -> None:
    stand.refresh()
    respx.post(f"{BASE}/api/v2/torrents/pause").mock(return_value=httpx.Response(200, content=b"x" * 300_000))
    answer = stand.press("button:pause", {"hash": "abc123"})
    assert code_of(answer) == "answer_too_large" and "It may have run" in answer.json()["detail"]["message"]


# -- the credentials stay where they belong -----------------------------------------------------------------------------------------------------


@respx.mock
def test_karten8_the_token_is_in_no_answer_no_log_and_no_journal(stand: Stand, caplog: pytest.LogCaptureFixture) -> None:
    stand.refresh()
    outcomes: list[Any] = [
        httpx.Response(200, json={"ok": True}), httpx.Response(500, text="boom"), httpx.Response(401, text="no"),
        httpx.Response(302, headers={"location": "http://elsewhere.example.com/x"}), httpx.ConnectError("refused"),
        httpx.ReadTimeout("slow"),
    ]
    route = respx.post(f"{BASE}/api/v2/torrents/pause").mock(side_effect=outcomes)
    texts: list[str] = []
    with caplog.at_level(logging.DEBUG):
        for _ in outcomes:
            texts.append(stand.press("button:pause", {"hash": "abc123"}).text)
    assert all(call.request.headers["authorization"] == f"Bearer {SECRET}" for call in route.calls), "the token did travel"
    assert all(SECRET not in one for one in texts)
    assert SECRET not in json.dumps(logged()) and SECRET not in json.dumps(noticed())
    with db_session() as db:
        kept = json.dumps([[getattr(one, column.name) for column in Event.__table__.columns] for one in db.scalars(select(Event))], default=str)
    assert SECRET not in kept
    assert SECRET not in caplog.text
