"""Forgetting a password, and the ways that must not become a way in.

⚠️ The form answers the same whatever happens. Whether the name exists,
whether the account carries an address, whether the mail went out: identical.
Anything else turns it into a list of who has an account on this box, which is
the first thing somebody probing a self-hosted machine wants.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import db_session
from app.models import PasswordReset, Session, User, utcnow
from app.security import new_opaque_token
from app.services import password_reset

from .conftest import ADMIN, CSRF, create_user, setup_admin

SMTP = {
    "host": "smtp.example.com", "port": 587, "security": "starttls",
    "from_address": "deck@example.com",
}
NEW = "a-brand-new-long-one"


PUBLIC = "https://deck.example.com"


def _with_mail(client: TestClient, url: str = PUBLIC) -> None:
    """A mail server and an address to put in front of the link.

    Both, because a link without a host is a line of text nobody can click.
    """
    assert client.put("/api/v1/settings/mail", json=SMTP, headers=CSRF).status_code == 200
    if url:
        assert client.patch("/api/v1/settings", json={"public_url": url}, headers=CSRF).status_code == 200


def _stored_hash(username: str) -> str | None:
    """The raw token cannot be read back; the test reaches for the row."""
    with db_session() as db:
        user = db.scalar(select(User).where(User.username == username))
        if user is None:
            return None
        row = db.scalar(
            select(PasswordReset).where(PasswordReset.user_id == user.id, PasswordReset.used_at.is_(None))
        )
        return row.token_hash if row else None


def _plant(username: str = "admin", minutes: int = 30) -> str:
    """A link straight into the database, because the mail cannot be read."""
    with db_session() as db:
        user = db.scalar(select(User).where(User.username == username))
        assert user is not None
        token, token_hash, _prefix = new_opaque_token("nr")
        db.add(PasswordReset(
            user_id=user.id, token_hash=token_hash,
            expires_at=utcnow() + timedelta(minutes=minutes),
        ))
        db.commit()
    return token


def test_it_needs_a_mail_server_and_an_address(client: TestClient) -> None:
    """⚠️ Two conditions, not one. Without a server there is nowhere to send
    the link; without a public URL there is no link, only a path."""
    setup_admin(client)
    with db_session() as db:
        assert password_reset.available(db) is False, "neither"

    _with_mail(client, url="")
    with db_session() as db:
        assert password_reset.available(db) is False, "a server but no address"

    assert client.patch("/api/v1/settings", json={"public_url": PUBLIC}, headers=CSRF).status_code == 200
    with db_session() as db:
        assert password_reset.available(db) is True


def test_the_answer_is_the_same_for_a_name_that_exists_and_one_that_does_not(client: TestClient) -> None:
    setup_admin(client)
    _with_mail(client)
    real = client.post("/api/v1/auth/forgot", json={"username": "admin"}, headers=CSRF)
    made_up = client.post("/api/v1/auth/forgot", json={"username": "nobody-here"}, headers=CSRF)
    assert real.status_code == made_up.status_code == 202
    assert real.json() == made_up.json()


def test_an_account_without_an_address_gets_the_same_answer(client: TestClient) -> None:
    """⚠️ Saying that an account has no address would confirm the account."""
    setup_admin(client)
    _with_mail(client)
    create_user(client, "kim")
    answer = client.post("/api/v1/auth/forgot", json={"username": "kim"}, headers=CSRF)
    assert answer.status_code == 202
    assert _stored_hash("kim") is None, "and nothing was made"


def test_no_link_is_made_without_a_mail_server(client: TestClient) -> None:
    setup_admin(client)
    client.patch("/api/v1/auth/me", json={"email": "admin@example.com"}, headers=CSRF)
    assert client.post("/api/v1/auth/forgot", json={"username": "admin"}, headers=CSRF).status_code == 202
    assert _stored_hash("admin") is None


def test_a_link_is_made_for_a_real_account_with_an_address(client: TestClient) -> None:
    setup_admin(client)
    client.patch("/api/v1/auth/me", json={"email": "admin@example.com"}, headers=CSRF)
    _with_mail(client)
    # Sending fails against a host that is not there; the row is written first,
    # which is what this checks.
    client.post("/api/v1/auth/forgot", json={"username": "admin"}, headers=CSRF)
    assert _stored_hash("admin") is not None


def test_the_address_works_as_well_as_the_name(client: TestClient) -> None:
    """People type whichever they remember."""
    setup_admin(client)
    client.patch("/api/v1/auth/me", json={"email": "admin@example.com"}, headers=CSRF)
    _with_mail(client)
    client.post("/api/v1/auth/forgot", json={"username": "ADMIN@EXAMPLE.COM"}, headers=CSRF)
    assert _stored_hash("admin") is not None


def test_only_the_hash_is_kept(client: TestClient) -> None:
    """⚠️ A reset link out of a database dump would be a way into every
    account at once."""
    setup_admin(client)
    client.patch("/api/v1/auth/me", json={"email": "admin@example.com"}, headers=CSRF)
    _with_mail(client)
    client.post("/api/v1/auth/forgot", json={"username": "admin"}, headers=CSRF)
    stored = _stored_hash("admin")
    assert stored is not None
    assert not stored.startswith("nr_"), "that would be the token itself"
    assert len(stored) == 64, "a sha256 digest"


def test_a_link_redeems_once(client: TestClient) -> None:
    setup_admin(client)
    token = _plant()
    assert client.get(f"/api/v1/auth/reset/{token}").json() == {"valid": True, "username": "admin"}

    done = client.post("/api/v1/auth/reset", json={"token": token, "new_password": NEW}, headers=CSRF)
    assert done.status_code == 204, done.text

    again = client.post(
        "/api/v1/auth/reset", json={"token": token, "new_password": "yet-another-long-one"}, headers=CSRF,
    )
    assert again.status_code == 400
    assert client.get(f"/api/v1/auth/reset/{token}").json()["valid"] is False


def test_the_new_password_works_and_the_old_one_does_not(client: TestClient) -> None:
    setup_admin(client)
    token = _plant()
    client.post("/api/v1/auth/reset", json={"token": token, "new_password": NEW}, headers=CSRF)

    fresh = TestClient(client.app)
    assert fresh.post("/api/v1/auth/login", json=ADMIN).status_code == 401
    assert fresh.post("/api/v1/auth/login", json={"username": "admin", "password": NEW}).status_code == 200


def test_redeeming_ends_every_session_and_every_token(client: TestClient) -> None:
    """⚠️ Somebody resetting a password usually thinks the old one got out.
    Leaving the intruder's session running would defeat the whole point."""
    setup_admin(client)
    api_token = client.post("/api/v1/tokens", json={"name": "script"}, headers=CSRF).json()["token"]
    token = _plant()

    client.post("/api/v1/auth/reset", json={"token": token, "new_password": NEW}, headers=CSRF)

    assert client.get("/api/v1/auth/me").status_code == 401, "the browser that was signed in"
    after = TestClient(client.app)
    assert after.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {api_token}"}).status_code == 401

    with db_session() as db:
        user = db.scalar(select(User).where(User.username == "admin"))
        assert user is not None
        open_now = list(db.scalars(
            select(Session).where(Session.user_id == user.id, Session.revoked.is_(False))
        ))
        assert open_now == []


def test_an_old_link_is_no_link(client: TestClient) -> None:
    setup_admin(client)
    token = _plant(minutes=-1)
    assert client.get(f"/api/v1/auth/reset/{token}").json()["valid"] is False
    spent = client.post("/api/v1/auth/reset", json={"token": token, "new_password": NEW}, headers=CSRF)
    assert spent.status_code == 400


def test_a_made_up_link_is_no_link(client: TestClient) -> None:
    setup_admin(client)
    for bad in ("nonsense", "nr_" + "a" * 40, "nd_looks-like-an-api-token"):
        assert client.get(f"/api/v1/auth/reset/{bad}").json()["valid"] is False
        answer = client.post("/api/v1/auth/reset", json={"token": bad, "new_password": NEW}, headers=CSRF)
        assert answer.status_code == 400


def test_the_link_of_a_disabled_account_stops_working(client: TestClient) -> None:
    setup_admin(client)
    kim = create_user(client, "kim")
    token = _plant("kim")
    client.patch(f"/api/v1/users/{kim['id']}", json={"disabled": True}, headers=CSRF)
    assert client.get(f"/api/v1/auth/reset/{token}").json()["valid"] is False
    assert client.post(
        "/api/v1/auth/reset", json={"token": token, "new_password": NEW}, headers=CSRF,
    ).status_code == 400


def test_a_disabled_account_gets_no_link(client: TestClient) -> None:
    setup_admin(client)
    _with_mail(client)
    kim = create_user(client, "kim")
    # Straight into the database: an administrator cannot set somebody else's
    # address through the API, and without one the test would pass for the
    # wrong reason.
    with db_session() as db:
        person = db.get(User, kim["id"])
        assert person is not None
        person.email = "kim@example.com"
        db.commit()
    client.patch(f"/api/v1/users/{kim['id']}", json={"disabled": True}, headers=CSRF)
    client.post("/api/v1/auth/forgot", json={"username": "kim"}, headers=CSRF)
    assert _stored_hash("kim") is None


def test_one_reset_closes_the_other_open_links(client: TestClient) -> None:
    """Asking three times and using one must not leave two doors open."""
    setup_admin(client)
    first, second = _plant(), _plant()
    client.post("/api/v1/auth/reset", json={"token": first, "new_password": NEW}, headers=CSRF)
    assert client.get(f"/api/v1/auth/reset/{second}").json()["valid"] is False


def test_only_three_links_stay_open_at_a_time(client: TestClient) -> None:
    """Somebody leaning on the button must not leave ten doors open."""
    setup_admin(client)
    client.patch("/api/v1/auth/me", json={"email": "admin@example.com"}, headers=CSRF)
    _with_mail(client)
    for _ in range(6):
        client.post("/api/v1/auth/forgot", json={"username": "admin"}, headers=CSRF)
    with db_session() as db:
        user = db.scalar(select(User).where(User.username == "admin"))
        assert user is not None
        open_now = list(db.scalars(
            select(PasswordReset).where(PasswordReset.user_id == user.id, PasswordReset.used_at.is_(None))
        ))
    assert len(open_now) == password_reset.MAX_OPEN


def test_asking_too_often_is_throttled(client: TestClient) -> None:
    """It sends mail; somebody who can send a hundred can fill an inbox."""
    setup_admin(client)
    _with_mail(client)
    codes = {
        client.post("/api/v1/auth/forgot", json={"username": "admin"}, headers=CSRF).status_code
        for _ in range(30)
    }
    assert 429 in codes


def test_old_links_are_thrown_away(client: TestClient) -> None:
    setup_admin(client)
    with db_session() as db:
        user = db.scalar(select(User).where(User.username == "admin"))
        assert user is not None
        _token, token_hash, _prefix = new_opaque_token("nr")
        db.add(PasswordReset(
            user_id=user.id, token_hash=token_hash, expires_at=utcnow() - timedelta(days=2),
        ))
        db.commit()
    with db_session() as db:
        assert password_reset.prune(db) == 1
        assert db.scalar(select(PasswordReset)) is None


def test_the_sign_in_page_is_told_whether_the_link_can_be_offered(client: TestClient) -> None:
    """⚠️ Public, and it has to be: the page shows it before anybody signs in.
    It says whether mail works here, nothing about who has an account."""
    setup_admin(client)
    assert client.get("/api/v1/setup/status").json()["can_reset_password"] is False
    _with_mail(client)
    assert client.get("/api/v1/setup/status").json()["can_reset_password"] is True


# ---------------------------------------------------------------------------
# What actually lands in the mail
# ---------------------------------------------------------------------------


def _catch_mail(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str, str]]:
    """Hold the outgoing mail instead of sending it, and hand it back."""
    caught: list[tuple[str, str, str]] = []

    def instead(_config: dict, to_address: str, subject: str, body: str) -> None:
        caught.append((to_address, subject, body))

    monkeypatch.setattr("app.services.mail.send", instead)
    return caught


def test_the_link_in_the_mail_carries_the_host(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """⚠️ The one that made the whole feature useless. The mail carried
    "/reset/nr_..." with nothing in front of it, because the address was read
    only from the setting and this installation had it in the environment."""
    setup_admin(client)
    client.patch("/api/v1/auth/me", json={"email": "admin@example.com"}, headers=CSRF)
    _with_mail(client)
    caught = _catch_mail(monkeypatch)

    client.post("/api/v1/auth/forgot", json={"username": "admin"}, headers=CSRF)

    assert len(caught) == 1
    _to, _subject, body = caught[0]
    assert f"{PUBLIC}/reset/nr_" in body
    assert "\n/reset/" not in body, "a path on its own is not a link"


def test_the_address_may_come_from_the_environment(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """⚠️ The ordinary Docker case: NEXDECK_PUBLIC_URL in the compose file and
    nothing in the settings. The rest of the app falls back to it; this did
    not, and only this one sends a link out of the building."""
    monkeypatch.setenv("NEXDECK_PUBLIC_URL", "https://deck.example.org")
    from app import config

    config.reset_settings_cache()

    setup_admin(client)
    client.patch("/api/v1/auth/me", json={"email": "admin@example.com"}, headers=CSRF)
    _with_mail(client, url="")
    with db_session() as db:
        assert password_reset.available(db) is True, "the variable counts"

    caught = _catch_mail(monkeypatch)
    client.post("/api/v1/auth/forgot", json={"username": "admin"}, headers=CSRF)
    assert "https://deck.example.org/reset/nr_" in caught[0][2]


def test_a_stored_address_beats_the_environment(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Somebody who types one into the settings means it."""
    monkeypatch.setenv("NEXDECK_PUBLIC_URL", "https://from-the-compose-file.example.org")
    from app import config

    config.reset_settings_cache()

    setup_admin(client)
    client.patch("/api/v1/auth/me", json={"email": "admin@example.com"}, headers=CSRF)
    _with_mail(client)
    caught = _catch_mail(monkeypatch)
    client.post("/api/v1/auth/forgot", json={"username": "admin"}, headers=CSRF)
    assert f"{PUBLIC}/reset/nr_" in caught[0][2]


def test_no_address_means_no_mail_at_all(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """⚠️ Refused, not sent half. A mail that arrives with an unusable link is
    worse than none: the person waits for the one that already came."""
    setup_admin(client)
    client.patch("/api/v1/auth/me", json={"email": "admin@example.com"}, headers=CSRF)
    _with_mail(client, url="")
    caught = _catch_mail(monkeypatch)

    answer = client.post("/api/v1/auth/forgot", json={"username": "admin"}, headers=CSRF)
    assert answer.status_code == 202, "and the form still says the same thing"
    assert caught == []
    assert _stored_hash("admin") is None, "and no link was written either"


def test_a_trailing_slash_does_not_double_up(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    setup_admin(client)
    client.patch("/api/v1/auth/me", json={"email": "admin@example.com"}, headers=CSRF)
    _with_mail(client, url="https://deck.example.com/")
    caught = _catch_mail(monkeypatch)
    client.post("/api/v1/auth/forgot", json={"username": "admin"}, headers=CSRF)
    assert "https://deck.example.com/reset/nr_" in caught[0][2]
    assert "//reset/" not in caught[0][2]
