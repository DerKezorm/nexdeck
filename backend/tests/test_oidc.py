"""The way in that needs no password at all.

⚠️ Until 07.09.2026 this had **no test of any kind**. A grep for "oidc" over
every backend and frontend test file found two hits, both of them entries in
the list of public addresses. It is a complete sign-in, it creates accounts,
and four of the findings of that day sat inside it.

The signature check itself is pyjwt's, and it is not retested here: ``claims``
is replaced so the tests can say what the provider claimed and get on with the
part that belongs to nexdeck.
"""

from __future__ import annotations

import time

import pyotp
import pytest
from fastapi.testclient import TestClient

from app.db import db_session
from app.models import OidcProvider, User
from app.services import oidc as oidc_service
from app.services import two_factor

from .conftest import CSRF, setup_admin

PROVIDER = {
    "slug": "keycloak",
    "label": "Keycloak",
    "issuer_url": "https://id.example.com/realms/home",
    "client_id": "nexdeck",
    "client_secret": "very-secret",
    "scopes": "openid profile email",
    "enabled": True,
    "auto_create": True,
    "default_role": "user",
    "trusts_second_factor": False,
}

DOCUMENT = {
    "issuer": PROVIDER["issuer_url"],
    "authorization_endpoint": f"{PROVIDER['issuer_url']}/auth",
    "token_endpoint": f"{PROVIDER['issuer_url']}/token",
    "jwks_uri": f"{PROVIDER['issuer_url']}/certs",
}


@pytest.fixture
def provider(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> dict:
    # ⚠️ Without a public URL the sign-in stops before it starts: the return
    # address is built from it, and OIDC cannot work without one.
    monkeypatch.setenv("NEXDECK_PUBLIC_URL", "https://deck.example.com")
    from app import config

    config.reset_settings_cache()
    setup_admin(client)
    made = client.post("/api/v1/oidc/providers", json=PROVIDER, headers=CSRF)
    assert made.status_code == 201, made.text
    return made.json()


def _pretend_the_provider_answers(monkeypatch: pytest.MonkeyPatch, claims: dict) -> None:
    """Everything between the redirect and the claims, without a real provider."""

    async def discovery(_issuer: str) -> dict:
        return DOCUMENT

    async def exchange(*_args, **_kwargs) -> dict:  # noqa: ANN002, ANN003
        return {"id_token": "pretend", "access_token": "pretend"}

    async def claims_(*_args, **_kwargs) -> dict:  # noqa: ANN002, ANN003
        return claims

    async def userinfo(*_args, **_kwargs) -> dict:  # noqa: ANN002, ANN003
        return {}

    monkeypatch.setattr(oidc_service, "discovery", discovery)
    monkeypatch.setattr(oidc_service, "exchange", exchange)
    monkeypatch.setattr(oidc_service, "claims", claims_)
    monkeypatch.setattr(oidc_service, "userinfo", userinfo)


def _walk_through(client: TestClient, slug: str) -> tuple[str, str]:
    """Start a sign-in and read back the state the server expects.

    ⚠️ The stand-in for the provider has to be in place before this: ``/login``
    fetches the discovery document for real, and without it the route gives up
    with ``oidc_unreachable`` before it ever sets the cookie.
    """
    started = client.get(f"/api/v1/auth/oidc/{slug}/login", follow_redirects=False)
    assert started.status_code in (302, 303, 307), started.text
    # Read it out of the header, not the jar: the cookie is scoped to
    # /api/v1/auth/oidc, and the jar hands nothing back for another path.
    raw = ""
    for header, value in started.headers.multi_items():
        if header.lower() == "set-cookie" and value.startswith(f"{oidc_service.COOKIE_NAME}="):
            raw = value.split("=", 1)[1].split(";", 1)[0]
    attempt = oidc_service.unpack_state(raw)
    assert attempt is not None, "the attempt cookie was not set"
    return attempt["state"], attempt["nonce"]


def _callback(client: TestClient, slug: str, state: str) -> object:
    return client.get(f"/api/v1/auth/oidc/{slug}/callback?code=whatever&state={state}", follow_redirects=False)


def test_a_token_without_a_subject_is_refused(client: TestClient, provider: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    """⚠️ ``sub`` is the identity, and pyjwt does not require it.

    Without this check the empty string became the key, so the second person
    whose provider omits the claim would have walked into the account of the
    first.
    """
    _pretend_the_provider_answers(monkeypatch, {"email": "someone@example.com", "name": "Someone"})
    visitor = TestClient(client.app)
    state, _nonce = _walk_through(visitor, provider["slug"])
    answer = _callback(visitor, provider["slug"], state)
    assert "oidc_bad_token" in answer.headers["location"]
    with db_session() as db:
        assert db.query(User).count() == 1, "no account may be made from a token with no subject"


def test_a_stale_attempt_is_refused(client: TestClient, provider: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    """The state in the address has to match the one in the cookie."""
    _pretend_the_provider_answers(monkeypatch, {"sub": "abc"})
    visitor = TestClient(client.app)
    _walk_through(visitor, provider["slug"])
    answer = _callback(visitor, provider["slug"], "not-the-state-we-sent")
    assert "oidc_state_mismatch" in answer.headers["location"]


def test_a_second_factor_is_not_skipped_just_because_a_provider_vouched(
    client: TestClient, provider: dict, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """⚠️ The provider proved who this is; it did not prove the second factor.

    This path used to open a session outright, so an account with a confirmed
    authenticator app was let in without a code as long as it came through
    OpenID Connect. The password path has asked for one since the beginning.
    """
    # The administrator switches a factor on for themselves, then links OIDC.
    started = client.post("/api/v1/auth/two-factor/start", headers=CSRF)
    secret = started.json()["secret"]
    assert client.post("/api/v1/auth/two-factor/confirm", json={"code": pyotp.TOTP(secret).now()}, headers=CSRF).status_code == 200
    with db_session() as db:
        admin = db.query(User).first()
        assert two_factor.enabled(admin)
        subject = "admin-at-the-provider"
        from app.models import OidcLink

        db.add(OidcLink(provider_id=provider["id"], user_id=admin.id, subject=subject, email=""))

    _pretend_the_provider_answers(monkeypatch, {"sub": subject, "email": "admin@example.com"})
    visitor = TestClient(client.app)
    state, _nonce = _walk_through(visitor, provider["slug"])
    answer = _callback(visitor, provider["slug"], state)

    assert "second_step=1" in answer.headers["location"], answer.headers["location"]
    assert "nexdeck_session" not in answer.cookies, "a session was opened without the second factor"
    assert visitor.get("/api/v1/auth/me").status_code == 401, "the half-finished sign-in must open nothing"

    # The ticket is in a cookie, not in the address: this is a redirect, and an
    # address ends up in every proxy log.
    finished = visitor.post(
        "/api/v1/auth/login/second-step",
        # ⚠️ The next window, not this one. A code that has been used once is
        # refused a second time, and the same one confirmed the factor above.
        json={"code": pyotp.TOTP(secret).at(int(time.time()) + 30)}, headers=CSRF,
    )
    assert finished.status_code == 200, finished.text
    assert visitor.get("/api/v1/auth/me").status_code == 200


def test_a_provider_that_checks_the_factor_itself_is_believed(
    client: TestClient, provider: dict, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The operator's decision, per provider: authentik already asked."""
    started = client.post("/api/v1/auth/two-factor/start", headers=CSRF)
    secret = started.json()["secret"]
    client.post("/api/v1/auth/two-factor/confirm", json={"code": pyotp.TOTP(secret).now()}, headers=CSRF)
    client.patch(f"/api/v1/oidc/providers/{provider['id']}", json={**PROVIDER, "trusts_second_factor": True}, headers=CSRF)
    with db_session() as db:
        from app.models import OidcLink

        admin = db.query(User).first()
        db.add(OidcLink(provider_id=provider["id"], user_id=admin.id, subject="trusted", email=""))

    _pretend_the_provider_answers(monkeypatch, {"sub": "trusted"})
    visitor = TestClient(client.app)
    state, _nonce = _walk_through(visitor, provider["slug"])
    answer = _callback(visitor, provider["slug"], state)
    assert "second_step" not in answer.headers["location"]
    assert visitor.get("/api/v1/auth/me").status_code == 200


def test_a_taken_slug_is_a_conflict_and_not_a_crash(client: TestClient, provider: dict) -> None:
    """⚠️ POST answered 409 and PATCH let the unique constraint answer, which
    means 500 and a stack trace for a name somebody simply typed twice.
    """
    second = client.post("/api/v1/oidc/providers", json={**PROVIDER, "slug": "authentik"}, headers=CSRF)
    assert second.status_code == 201, second.text
    clash = client.patch(f"/api/v1/oidc/providers/{second.json()['id']}", json=PROVIDER, headers=CSRF)
    assert clash.status_code == 409, clash.text
    assert clash.json()["detail"]["code"] == "taken"


def test_removing_a_provider_says_who_it_would_lock_out(client: TestClient, provider: dict) -> None:
    """⚠️ The links go with the provider (``ondelete="CASCADE"``), and an
    account made through it has no password. Deleting the provider locked those
    accounts out for good, silently and with no undo.
    """
    from app.models import OidcLink
    from app.security import UNUSABLE_PASSWORD

    with db_session() as db:
        stranded = User(username="only-via-provider", display_name="Guest", password_hash=UNUSABLE_PASSWORD, role="user")
        db.add(stranded)
        db.flush()
        db.add(OidcLink(provider_id=provider["id"], user_id=stranded.id, subject="s-1", email=""))

    refused = client.delete(f"/api/v1/oidc/providers/{provider['id']}", headers=CSRF)
    assert refused.status_code == 409, refused.text
    assert "only-via-provider" in refused.json()["detail"]["message"]

    forced = client.delete(f"/api/v1/oidc/providers/{provider['id']}?force=true", headers=CSRF)
    assert forced.status_code == 204
    with db_session() as db:
        assert db.query(OidcProvider).count() == 0
