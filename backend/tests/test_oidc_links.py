"""Linking one's own account to a sign-in provider.

⚠️ Until 0.35.0 there was no way to do this at all. A provider either made a
new account on first sign-in or turned the person away, so an administrator
who set up authentik and then signed in through it got a second, empty
account with the role "user" instead of their own.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.db import db_session
from app.models import OidcLink, User
from app.security import UNUSABLE_PASSWORD
from app.services import oidc as oidc_service

from .conftest import CSRF, create_user, login
from .test_oidc import (  # noqa: F401
    PROVIDER,
    _callback,
    _pretend_the_provider_answers,
    _walk_through,
    provider,
)

SLUG = PROVIDER["slug"]


def _start_link(browser: TestClient) -> str:
    """Press the button on the profile page and read back the state the server expects."""
    started = browser.post(f"/api/v1/auth/oidc/{SLUG}/link", headers=CSRF)
    assert started.status_code == 200, started.text
    assert started.json()["url"].startswith(f"{PROVIDER['issuer_url']}/auth?")
    raw = ""
    for header, value in started.headers.multi_items():
        if header.lower() == "set-cookie" and value.startswith(f"{oidc_service.COOKIE_NAME}="):
            raw = value.split("=", 1)[1].split(";", 1)[0]
    attempt = oidc_service.unpack_state(raw)
    assert attempt is not None and attempt["purpose"] == "link"
    # The jar keeps the cookie for its path, so the callback carries it like a browser would.
    browser.cookies.set(oidc_service.COOKIE_NAME, raw, path="/api/v1/auth/oidc")
    return attempt["state"]


def _no_auto_create(client: TestClient, provider: dict) -> None:  # noqa: F811
    answer = client.patch(f"/api/v1/oidc/providers/{provider['id']}", json={**PROVIDER, "auto_create": False}, headers=CSRF)
    assert answer.status_code == 200, answer.text


def test_a_linked_account_signs_in_as_itself(client: TestClient, provider: dict, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    _no_auto_create(client, provider)
    _pretend_the_provider_answers(monkeypatch, {"sub": "admin-at-authentik", "email": "admin@example.com"})

    state = _start_link(client)
    back = _callback(client, SLUG, state)
    assert back.headers["location"] == f"/settings?oidc_linked={SLUG}", back.headers["location"]
    assert [entry["linked"] for entry in client.get("/api/v1/auth/oidc/links").json()] == [True]

    # A different browser, no password: straight into the administrator's own account.
    visitor = TestClient(client.app)
    state, _nonce = _walk_through(visitor, SLUG)
    answer = _callback(visitor, SLUG, state)
    assert answer.headers["location"] == "/", answer.headers["location"]
    me = visitor.get("/api/v1/auth/me").json()
    assert me["username"] == "admin" and me["role"] == "admin"
    with db_session() as db:
        assert db.query(User).count() == 1, "signing in through a linked identity must not make an account"


def test_an_address_alone_links_nothing(client: TestClient, provider: dict, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    """⚠️ authentik lets a user change their own address by default.

    Linking through a matching address, verified or not, would let anybody with
    an authentik login into the administrator's account by typing the
    administrator's address into their own profile.
    """
    _no_auto_create(client, provider)
    with db_session() as db:
        db.query(User).filter(User.username == "admin").one().email = "admin@example.com"
    _pretend_the_provider_answers(monkeypatch, {"sub": "a-stranger", "email": "admin@example.com", "email_verified": True})
    visitor = TestClient(client.app)
    state, _nonce = _walk_through(visitor, SLUG)
    answer = _callback(visitor, SLUG, state)
    assert "oidc_no_account" in answer.headers["location"]
    assert visitor.get("/api/v1/auth/me").status_code == 401
    with db_session() as db:
        assert db.query(OidcLink).count() == 0


def test_an_identity_linked_elsewhere_is_not_taken_over(client: TestClient, provider: dict, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    other = create_user(client, "kim")
    with db_session() as db:
        db.add(OidcLink(provider_id=provider["id"], user_id=other["id"], subject="kims-identity", email=""))
    _pretend_the_provider_answers(monkeypatch, {"sub": "kims-identity"})
    state = _start_link(client)
    back = _callback(client, SLUG, state)
    assert back.headers["location"].startswith("/settings?oidc_error=oidc_taken"), back.headers["location"]
    with db_session() as db:
        links = db.query(OidcLink).all()
        assert [(link.user_id, link.subject) for link in links] == [(other["id"], "kims-identity")]


def test_linking_needs_the_request_header(client: TestClient, provider: dict) -> None:  # noqa: F811
    """A POST with the CSRF header, so no other page can start it in somebody's browser."""
    assert client.post(f"/api/v1/auth/oidc/{SLUG}/link").status_code == 403
    assert TestClient(client.app).post(f"/api/v1/auth/oidc/{SLUG}/link", headers=CSRF).status_code == 401


def test_the_last_way_in_cannot_be_unlinked(client: TestClient, provider: dict) -> None:  # noqa: F811
    create_user(client, "kim")
    with db_session() as db:
        kim = db.query(User).filter(User.username == "kim").one()
        db.add(OidcLink(provider_id=provider["id"], user_id=kim.id, subject="kim", email=""))
    browser = TestClient(client.app)
    login(browser, "kim", "another-long-password")
    with db_session() as db:
        db.query(User).filter(User.username == "kim").one().password_hash = UNUSABLE_PASSWORD
    refused = browser.delete(f"/api/v1/auth/oidc/{SLUG}/link", headers=CSRF)
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "would_lock_out", refused.text

    # With a password there is another way in, and the link goes.
    assert client.delete(f"/api/v1/auth/oidc/{SLUG}/link", headers=CSRF).status_code == 204
