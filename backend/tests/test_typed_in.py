"""The one action that lets somebody type the value in.

⚠️ Everything else nexdeck runs is reachable only because the card put it in
its last answer with exactly those parameters, which is the guard of 0.2.0. A
field on a card breaks that comparison by design: nobody knows in advance which
address a person will paste. The way through is not a hole but a declaration —
the adapter says which single parameter is blank and what may go in it — and
these tests are what keeps the declaration from turning back into a hole.

Written against the MeTube card, which is the only card in the catalogue with a
field, and against a demo connection, so nothing here reaches a real service.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.adapters.base import AdapterError, Ask, fill_in
from tests.conftest import CSRF, setup_admin

ADDRESS = "https://videos.example.com/watch?v=abcdefg"


def _fetch_card(client: TestClient) -> dict:
    integration = client.post(
        "/api/v1/integrations",
        json={"kind": "metube", "name": "MeTube", "config": {"url": "http://metube.example.com"}, "demo": True},
        headers=CSRF,
    ).json()
    board = client.post("/api/v1/boards", json={"name": "Wall"}, headers=CSRF).json()
    widget = client.post(
        f"/api/v1/pages/{board['pages'][0]['id']}/widgets",
        json={"kind": "metube.fetch", "integration_id": integration["id"]},
        headers=CSRF,
    )
    assert widget.status_code == 201, widget.text
    return widget.json()["widget"]


def _offer(client: TestClient, widget_id: int) -> dict:
    """Refresh the card and take the action that leaves a blank."""
    refreshed = client.post(f"/api/v1/widgets/{widget_id}/refresh", headers=CSRF)
    assert refreshed.status_code == 200, refreshed.text
    for action in refreshed.json().get("actions") or []:
        if action.get("ask"):
            return action
    raise AssertionError("the card offered no action with a field, so this test proves nothing")


def _run(client: TestClient, widget_id: int, action: dict, params: dict) -> dict:
    return client.post(
        f"/api/v1/widgets/{widget_id}/actions/{action['id']}",
        json={"params": {**(action.get("params") or {}), **params}},
        headers=CSRF,
    )


def test_the_card_tells_the_browser_what_it_may_fill_in(client: TestClient) -> None:
    setup_admin(client)
    widget = _fetch_card(client)
    action = _offer(client, widget["id"])
    assert action["ask"] == {
        "name": "url", "label": "Video address", "kind": "url",
        "placeholder": "https://...", "max_length": 2048,
    }
    assert "url" not in (action.get("params") or {}), "the blank must not arrive already filled in"


def test_an_address_somebody_typed_goes_through(client: TestClient) -> None:
    setup_admin(client)
    widget = _fetch_card(client)
    action = _offer(client, widget["id"])
    answer = _run(client, widget["id"], action, {"url": ADDRESS})
    assert answer.status_code == 200, answer.text


def test_the_rest_of_the_action_still_has_to_match(client: TestClient) -> None:
    """The blank is one parameter. The others are still the card's own words.

    Without this the field would be a way to send the adapter anything at all,
    with the typed value as the excuse.
    """
    setup_admin(client)
    widget = _fetch_card(client)
    action = _offer(client, widget["id"])
    answer = client.post(
        f"/api/v1/widgets/{widget['id']}/actions/{action['id']}",
        json={"params": {**action["params"], "url": ADDRESS, "download_type": "../something"}},
        headers=CSRF,
    )
    assert answer.status_code == 400, answer.text
    assert answer.json()["detail"]["code"] == "no_such_action"


@pytest.mark.parametrize("value", [
    "",
    "   ",
    "ftp://videos.example.com/clip.mp4",
    "javascript:alert(1)",
    "file:///etc/passwd",
    "videos.example.com/clip.mp4",
    "https://videos.example.com/\nHost: elsewhere",
    "https://" + "a" * 2100 + ".example.com",
])
def test_what_may_not_be_typed_in(client: TestClient, value: str) -> None:
    setup_admin(client)
    widget = _fetch_card(client)
    action = _offer(client, widget["id"])
    answer = _run(client, widget["id"], action, {"url": value})
    assert answer.status_code == 400, f"{value!r} went through: {answer.text}"
    assert answer.json()["detail"]["code"] in ("bad_value", "bad_scheme", "bad_url"), answer.text


def test_an_address_that_only_the_server_can_reach_is_refused(client: TestClient) -> None:
    """The same rule a member-supplied notification address gets.

    A field on a board is the least trusted way an address enters nexdeck, and
    loopback answers to whatever else runs beside the server.
    """
    setup_admin(client)
    widget = _fetch_card(client)
    action = _offer(client, widget["id"])
    for value in ("http://127.0.0.1:8080/x", "http://169.254.169.254/latest/meta-data/"):
        answer = _run(client, widget["id"], action, {"url": value})
        assert answer.status_code == 400, f"{value} went through: {answer.text}"


def test_a_blank_is_no_excuse_for_an_action_that_was_never_offered(client: TestClient) -> None:
    setup_admin(client)
    widget = _fetch_card(client)
    _offer(client, widget["id"])
    answer = client.post(
        f"/api/v1/widgets/{widget['id']}/actions/remove",
        json={"params": {"where": "done", "id": "abc", "url": ADDRESS}},
        headers=CSRF,
    )
    assert answer.status_code == 400, answer.text
    assert answer.json()["detail"]["code"] == "no_such_action"


# -- the declaration on its own ---------------------------------------------


def test_a_plain_field_takes_words_but_not_control_characters() -> None:
    plain = Ask(name="note", label="Note", max_length=20)
    assert fill_in(plain, "  hello there  ") == "hello there"
    for bad in ("hello\x00there", "a" * 21, 7, None, ""):
        with pytest.raises(AdapterError) as refused:
            fill_in(plain, bad)
        assert refused.value.code == "bad_value", bad


def test_a_url_field_keeps_the_address_exactly_as_typed() -> None:
    """⚠️ Refuses rather than trims. A silently shortened address is a
    download of something else, and nobody would see which."""
    ask = Ask(name="url", label="Video address", kind="url", max_length=40)
    assert fill_in(ask, " https://videos.example.com/clip ") == "https://videos.example.com/clip"
    with pytest.raises(AdapterError):
        fill_in(ask, "https://videos.example.com/" + "x" * 40)
