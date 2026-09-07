"""Where the interface used to give up quietly.

⚠️ Each of these had the same shape: something failed, nothing said so, and
whoever was in front of it had no way to tell.

* Two browsers in edit mode overwrote each other. The second save put the
  first person's arrangement back, it looked saved on screen, and after a
  reload the work was gone.
* A mistyped or withdrawn ``/api/`` address answered 200 with the whole
  dashboard page, so a client asking for JSON got HTML and a success. POST
  already answered 405, so the two methods disagreed about whether the address
  exists at all.
* After a restore into an installation with a different NEXDECK_SECRET_KEY,
  the sign-in of an account with a second factor answered 500, and pressing
  Test on a saved connection did too. That is exactly the moment somebody
  needs to get in.
* A refresh interval could be set and never taken off again.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.db import db_session
from app.models import Widget

from .conftest import CSRF, setup_admin


def _board_and_page(client: TestClient) -> tuple[dict, int]:
    board = client.post("/api/v1/boards", json={"name": "Wall"}, headers=CSRF).json()
    return board, board["pages"][0]["id"]


def test_two_browsers_arranging_the_same_page_do_not_overwrite_each_other(client: TestClient) -> None:
    setup_admin(client)
    board, page_id = _board_and_page(client)
    made = client.post(f"/api/v1/pages/{page_id}/widgets", json={"kind": "core.clock", "title": "Clock"}, headers=CSRF)
    widget_id = made.json()["widget"]["id"]

    seen = client.get(f"/api/v1/boards/{board['slug']}").json()
    version = seen["pages"][0]["layout_version"]
    assert isinstance(version, int), "the page does not say what version it stands at"

    # The first browser saves and moves the page on.
    first = client.put(f"/api/v1/pages/{page_id}/layouts", json={
        "lg": [{"i": str(widget_id), "x": 0, "y": 0, "w": 2, "h": 2}], "version": version,
    }, headers=CSRF)
    assert first.status_code == 200, first.text
    assert first.json()["version"] == version + 1

    # The second browser was still looking at the old one.
    second = client.put(f"/api/v1/pages/{page_id}/layouts", json={
        "lg": [{"i": str(widget_id), "x": 6, "y": 6, "w": 2, "h": 2}], "version": version,
    }, headers=CSRF)
    assert second.status_code == 409, second.text
    assert second.json()["detail"]["code"] == "layout_moved_on"

    # And the first arrangement is what is stored.
    now = client.get(f"/api/v1/boards/{board['slug']}").json()
    assert now["pages"][0]["layouts"]["lg"][0]["x"] == 0, "the refused save was written anyway"


def test_a_browser_that_sends_no_version_is_not_held_hostage(client: TestClient) -> None:
    """An older tab. Refusing its save would be worse than the race it loses."""
    setup_admin(client)
    board, page_id = _board_and_page(client)
    made = client.post(f"/api/v1/pages/{page_id}/widgets", json={"kind": "core.clock", "title": "Clock"}, headers=CSRF)
    widget_id = made.json()["widget"]["id"]

    for _ in range(2):
        answer = client.put(f"/api/v1/pages/{page_id}/layouts", json={
            "lg": [{"i": str(widget_id), "x": 1, "y": 1, "w": 2, "h": 2}],
        }, headers=CSRF)
        assert answer.status_code == 200, answer.text


def test_an_address_that_does_not_exist_says_so_for_get_as_well(client: TestClient) -> None:
    """⚠️ GET answered 200 with the dashboard page, POST answered 405: the two
    disagreed about whether the address exists.
    """
    setup_admin(client)
    missing = client.get("/api/v1/gibtesnicht")
    assert missing.status_code == 404, missing.text
    assert missing.headers["content-type"].startswith("application/json")
    assert missing.json()["code"] == "not_found"


def test_a_second_factor_that_cannot_be_read_is_not_a_locked_door(client: TestClient) -> None:
    """⚠️ ``SecretUnreadable`` came back as a 500 at the sign-in. That happens
    after a restore into an installation with a different key, which is the
    moment somebody most needs to get in. An unreadable factor counts as none.
    """
    setup_admin(client)
    from app.models import User
    from app.services import two_factor

    with db_session() as db:
        user = db.scalar(User.__table__.select().with_only_columns(User.id).limit(1))
        account = db.get(User, user)
        assert account is not None
        account.totp_secret = "enc:gAAAAABnot-a-value-this-key-can-read"
        account.totp_confirmed = True

    with db_session() as db:
        account = db.get(User, user)
        assert account is not None
        assert two_factor.read_secret(account) == ""
        assert two_factor.enabled(account) is False, "the account is asked for a code it cannot have"


def test_testing_a_connection_whose_keys_cannot_be_read_answers_in_words(client: TestClient) -> None:
    setup_admin(client)
    made = client.post("/api/v1/integrations", json={
        "kind": "radarr", "name": "Films", "config": {"url": "http://films.example.com", "api_key": "x" * 32},
        "enabled": True, "demo": True,
    }, headers=CSRF)
    number = made.json()["id"]

    from app.models import Integration

    with db_session() as db:
        row = db.get(Integration, number)
        assert row is not None
        row.config = {**row.config, "api_key": "enc:gAAAAABnot-a-value-this-key-can-read"}

    answer = client.post("/api/v1/integrations/test", json={
        "kind": "radarr", "integration_id": number, "config": {"url": "http://films.example.com"},
    }, headers=CSRF)
    assert answer.status_code == 200, answer.text
    assert answer.json()["ok"] is False
    assert answer.json()["code"] == "secret_unreadable"
    assert "NEXDECK_SECRET_KEY" in answer.json()["hint"]


def test_a_refresh_interval_can_be_taken_off_again(client: TestClient) -> None:
    """⚠️ ``None`` already means "not sent", so an emptied field said nothing
    and the card kept its number for good.
    """
    setup_admin(client)
    _board, page_id = _board_and_page(client)
    made = client.post(f"/api/v1/pages/{page_id}/widgets", json={
        "kind": "core.clock", "title": "Clock", "refresh_seconds": 120,
    }, headers=CSRF)
    widget_id = made.json()["widget"]["id"]
    with db_session() as db:
        assert db.get(Widget, widget_id).refresh_seconds == 120

    back = client.patch(f"/api/v1/widgets/{widget_id}", json={"clear_refresh": True}, headers=CSRF)
    assert back.status_code == 200, back.text
    with db_session() as db:
        assert db.get(Widget, widget_id).refresh_seconds is None, "the card kept the interval"
