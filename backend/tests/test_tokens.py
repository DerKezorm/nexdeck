"""What a token is worth after it was handed out.

An API token used to outlive the password change that was meant to lock its
owner out, a kiosk token had no end and rode in every address the display
loaded, and a share that could not press a button could mint a display that
could. Each test here is one of those, written as the attack.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import db_session
from app.models import ApiToken, Board, KioskToken

from .conftest import CSRF, create_user, login, setup_admin


def _api_token(client: TestClient, name: str = "script", days: int = 0) -> str:
    answer = client.post("/api/v1/tokens", json={"name": name, "expires_days": days}, headers=CSRF)
    assert answer.status_code == 201, answer.text
    return answer.json()["token"]


def _board(client: TestClient, name: str = "Wall") -> dict:
    answer = client.post("/api/v1/boards", json={"name": name}, headers=CSRF)
    assert answer.status_code == 201, answer.text
    return answer.json()


def _kiosk(client: TestClient, slug: str, **body: object) -> dict:
    answer = client.post(f"/api/v1/boards/{slug}/kiosk-tokens", json={"name": "Hall", **body}, headers=CSRF)
    assert answer.status_code == 201, answer.text
    return answer.json()


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _age(model: type, token_id: int, **delta: float) -> None:
    """Move a stored timestamp, so an end can be reached without waiting."""
    with db_session() as db:
        row = db.get(model, token_id)
        assert row is not None
        row.expires_at = datetime.now(UTC) - timedelta(**delta)


# ---------------------------------------------------------------------------
# API tokens
# ---------------------------------------------------------------------------


def test_an_api_token_dies_with_the_password_it_was_made_under(client: TestClient) -> None:
    """The attack: make a token, lose the account, keep the token.

    Every session cookie carries its issue time and is refused after a
    password change. The bearer path never looked, so the one thing an
    intruder would leave behind was the one thing a reset did not remove.
    """
    setup_admin(client)
    token = _api_token(client)
    fresh = TestClient(client.app)
    assert fresh.get("/api/v1/auth/me", headers=_bearer(token)).status_code == 200

    changed = client.post("/api/v1/auth/password", json={
        "current_password": "correct-horse-battery", "new_password": "a-brand-new-long-one",
    }, headers=CSRF)
    assert changed.status_code in (200, 204), changed.text

    after = TestClient(client.app)
    assert after.get("/api/v1/auth/me", headers=_bearer(token)).status_code == 401


def test_a_withdrawn_api_token_stays_withdrawn(client: TestClient) -> None:
    setup_admin(client)
    token = _api_token(client)
    listed = client.get("/api/v1/tokens").json()
    assert len(listed) == 1
    assert client.delete(f"/api/v1/tokens/{listed[0]['id']}", headers=CSRF).status_code == 204

    assert client.get("/api/v1/tokens").json() == []
    fresh = TestClient(client.app)
    assert fresh.get("/api/v1/auth/me", headers=_bearer(token)).status_code == 401

    with db_session() as db:
        row = db.scalar(select(ApiToken))
        assert row is not None, "the row stays, so the hash can never be granted again"
        assert row.revoked and row.revoked_at is not None


def test_an_expired_api_token_is_refused(client: TestClient) -> None:
    setup_admin(client)
    token = _api_token(client, days=30)
    listed = client.get("/api/v1/tokens").json()
    fresh = TestClient(client.app)
    assert fresh.get("/api/v1/auth/me", headers=_bearer(token)).status_code == 200

    _age(ApiToken, listed[0]["id"], seconds=1)
    after = TestClient(client.app)
    assert after.get("/api/v1/auth/me", headers=_bearer(token)).status_code == 401


def test_a_token_without_an_end_keeps_working(client: TestClient) -> None:
    """The end is optional; a script that should keep running keeps running."""
    setup_admin(client)
    token = _api_token(client)
    assert client.get("/api/v1/tokens").json()[0]["expires_at"] is None
    fresh = TestClient(client.app)
    assert fresh.get("/api/v1/auth/me", headers=_bearer(token)).status_code == 200


# ---------------------------------------------------------------------------
# Kiosk tokens
# ---------------------------------------------------------------------------


def test_the_token_is_no_longer_read_from_the_address(client: TestClient) -> None:
    """``?kiosk=`` used to be enough, and the browser put it in every image address."""
    setup_admin(client)
    board = _board(client)
    made = _kiosk(client, board["slug"])

    display = TestClient(client.app)
    assert display.get(f"/api/v1/kiosk?kiosk={made['token']}").status_code == 401


def test_a_display_is_let_in_by_the_cookie_it_is_given(client: TestClient) -> None:
    setup_admin(client)
    board = _board(client)
    made = _kiosk(client, board["slug"])

    display = TestClient(client.app)
    door = display.post("/api/v1/kiosk/session", json={"token": made["token"]}, headers=CSRF)
    assert door.status_code == 200, door.text
    assert "nexdeck_kiosk" in display.cookies

    opened = display.get("/api/v1/kiosk")
    assert opened.status_code == 200, opened.text
    assert opened.json()["slug"] == board["slug"]


def test_a_withdrawn_display_is_shut_out_at_the_next_request(client: TestClient) -> None:
    """The cookie stays in the browser; the row it points at decides."""
    setup_admin(client)
    board = _board(client)
    made = _kiosk(client, board["slug"])
    display = TestClient(client.app)
    display.post("/api/v1/kiosk/session", json={"token": made["token"]}, headers=CSRF)
    assert display.get("/api/v1/kiosk").status_code == 200

    assert client.delete(f"/api/v1/kiosk-tokens/{made['id']}", headers=CSRF).status_code == 204
    assert display.get("/api/v1/kiosk").status_code == 401, "the cookie must stop working"
    assert client.get(f"/api/v1/boards/{board['slug']}/kiosk-tokens").json() == []

    with db_session() as db:
        row = db.scalar(select(KioskToken))
        assert row is not None and row.revoked

    again = TestClient(client.app)
    assert again.post("/api/v1/kiosk/session", json={"token": made["token"]}, headers=CSRF).status_code == 401


def test_an_expired_display_is_shut_out(client: TestClient) -> None:
    setup_admin(client)
    board = _board(client)
    made = _kiosk(client, board["slug"], expires_days=7)
    assert made["expires_at"] is not None

    display = TestClient(client.app)
    display.post("/api/v1/kiosk/session", json={"token": made["token"]}, headers=CSRF)
    assert display.get("/api/v1/kiosk").status_code == 200

    _age(KioskToken, made["id"], seconds=1)
    assert display.get("/api/v1/kiosk").status_code == 401


def test_a_share_cannot_hand_out_more_than_it_holds(client: TestClient) -> None:
    """The attack: an "edit" share mints a display that may press buttons.

    Creating a kiosk link needed ``edit`` and the body carried
    ``allow_actions``, so the right the owner held back was one request away.
    """
    setup_admin(client)
    board = _board(client, "Shared")
    kim = create_user(client, "kim")
    granted = client.put(f"/api/v1/boards/{board['slug']}/shares", json={
        "shares": [{"user_id": kim["id"], "level": "edit"}],
    }, headers=CSRF)
    assert granted.status_code == 200, granted.text

    other = TestClient(client.app)
    login(other, "kim", "another-long-password")
    refused = other.post(f"/api/v1/boards/{board['slug']}/kiosk-tokens", json={
        "name": "Hall", "allow_actions": True,
    }, headers=CSRF)
    assert refused.status_code == 403, refused.text

    plain = other.post(f"/api/v1/boards/{board['slug']}/kiosk-tokens", json={"name": "Hall"}, headers=CSRF)
    assert plain.status_code == 201, "an edit share may still make a read-only display"
    assert plain.json()["allow_actions"] is False


def test_the_owner_may_still_give_a_display_the_right_to_act(client: TestClient) -> None:
    setup_admin(client)
    board = _board(client)
    made = _kiosk(client, board["slug"], allow_actions=True)
    assert made["allow_actions"] is True


def test_withdrawing_a_link_asks_the_right_board(client: TestClient) -> None:
    """The last place that looked a board up by its number through the slug.

    Creating a board named after a number is refused now, so the trap is put
    straight into the database: that is what a board from before the rule, or
    one out of an imported file, looks like. The lookup must not be the thing
    standing between them.
    """
    setup_admin(client)
    board = _board(client, "Wall")
    made = _kiosk(client, board["slug"])

    kim = create_user(client, "kim")
    with db_session() as db:
        db.add(Board(slug=str(board["id"]), name="trap", owner_id=kim["id"]))

    other = TestClient(client.app)
    login(other, "kim", "another-long-password")
    assert other.delete(f"/api/v1/kiosk-tokens/{made['id']}", headers=CSRF).status_code == 403
    assert client.get(f"/api/v1/boards/{board['slug']}/kiosk-tokens").json(), "the link is still there"


# ---------------------------------------------------------------------------
# Signed in, with a display's cookie in the same browser
# ---------------------------------------------------------------------------


def _open_display_here(client: TestClient, token: str) -> None:
    """What happens when the owner tries the link they just made: the kiosk cookie lands next to the session."""
    door = client.post("/api/v1/kiosk/session", json={"token": token}, headers=CSRF)
    assert door.status_code == 200, door.text
    assert "nexdeck_kiosk" in client.cookies


def test_a_display_link_opened_once_does_not_lock_its_owner_out_of_every_other_board(client: TestClient) -> None:
    """Found 11.09.2026: the kiosk cookie won over the signed-in session.

    From the moment the owner had looked at a wall display's link in their own
    browser, every other board, its cards and its sparklines answered 403
    "This kiosk token belongs to another board", and the app showed "The board
    could not be loaded" with no way to tell why.
    """
    setup_admin(client)
    wall = _board(client, "Wall")
    desk = _board(client, "Desk")
    clock = client.post(f"/api/v1/pages/{desk['pages'][0]['id']}/widgets", json={"kind": "core.clock"}, headers=CSRF)
    assert clock.status_code == 201, clock.text
    _open_display_here(client, _kiosk(client, wall["slug"])["token"])

    opened = client.get(f"/api/v1/boards/{desk['slug']}")
    assert opened.status_code == 200, opened.text
    assert opened.json()["permission"] == "owner"
    assert "kiosk" not in opened.json(), "the display's settings belong to its own board"
    assert client.get(f"/api/v1/boards/{desk['slug']}/history").status_code == 200
    assert client.get(f"/api/v1/widgets/{clock.json()['widget']['id']}/data").status_code == 200
    assert client.get(f"/api/v1/boards/{wall['slug']}").json()["permission"] == "owner"


def test_a_display_without_a_sign_in_still_sees_its_own_board_and_no_other(client: TestClient) -> None:
    setup_admin(client)
    wall = _board(client, "Wall")
    desk = _board(client, "Desk")
    made = _kiosk(client, wall["slug"])

    display = TestClient(client.app)
    _open_display_here(display, made["token"])
    assert display.get(f"/api/v1/boards/{wall['slug']}").json()["permission"] == "view"
    refused = display.get(f"/api/v1/boards/{desk['slug']}")
    assert refused.status_code == 403, refused.text
    assert display.get(f"/api/v1/boards/{desk['slug']}/history").status_code == 403


def test_with_both_the_higher_right_counts_and_neither_takes_one_away(client: TestClient) -> None:
    """Each alone grants what it grants; together they grant nothing more than the better of the two."""
    setup_admin(client)
    wall = _board(client, "Wall")
    hidden = _board(client, "Hidden")
    kim = create_user(client, "kim")
    shared = client.put(f"/api/v1/boards/{wall['slug']}/shares", json={"shares": [{"user_id": kim["id"], "level": "view"}]}, headers=CSRF)
    assert shared.status_code == 200, shared.text
    acting = _kiosk(client, wall["slug"], allow_actions=True)
    looking = _kiosk(client, hidden["slug"])

    other = TestClient(client.app)
    login(other, "kim", "another-long-password")
    _open_display_here(other, acting["token"])
    assert other.get(f"/api/v1/boards/{wall['slug']}").json()["permission"] == "act", "the display may act, so kim may here"

    _open_display_here(other, looking["token"])
    assert other.get(f"/api/v1/boards/{hidden['slug']}").json()["permission"] == "view", "a board kim cannot see, opened by its display"
    assert other.get(f"/api/v1/boards/{wall['slug']}").json()["permission"] == "view", "kim's own share still counts"
