"""Three holes in the OIDC sign-in, closed before the larger rework.

1. Pointing a provider at another issuer kept its links. A subject means
   something only at the issuer that handed it out, so somebody at the new
   issuer whose subject happened to equal an old one walked into that account.
2. A provider added by hand handed out accounts to anybody with a login there,
   unless the operator thought to switch that off.
3. The attempt cookie was signed with the session key, and a used ``state``
   could be played back as long as the provider still took the code.
"""

from __future__ import annotations

import logging
import secrets
import time

import jwt
import pytest
from fastapi.testclient import TestClient

from app.db import db_session
from app.models import OidcLink, OidcProvider, User
from app.security import ALGORITHM, UNUSABLE_PASSWORD, _signing_key, create_session_token
from app.services import oidc as oidc_service

from .conftest import CSRF
from .test_oidc import (  # noqa: F401
    PROVIDER,
    _callback,
    _pretend_the_provider_answers,
    _walk_through,
    provider,
)

OTHER = {**PROVIDER, "slug": "pocket", "label": "Pocket ID", "issuer_url": "https://pocket.example.com"}


def _link(provider_id: int, subject: str) -> None:
    with db_session() as db:
        person = User(username=f"via-{subject}", display_name=subject, password_hash=UNUSABLE_PASSWORD, role="user")
        db.add(person)
        db.flush()
        db.add(OidcLink(provider_id=provider_id, user_id=person.id, subject=subject, email=""))


def _links(provider_id: int) -> int:
    with db_session() as db:
        return db.query(OidcLink).filter(OidcLink.provider_id == provider_id).count()


# -- 1. another issuer is another provider -------------------------------------


def test_another_issuer_drops_the_links_of_this_provider_and_no_other(
    client: TestClient, provider: dict, caplog: pytest.LogCaptureFixture,  # noqa: F811
) -> None:
    other = client.post("/api/v1/oidc/providers", json=OTHER, headers=CSRF).json()
    _link(provider["id"], "a-1")
    _link(provider["id"], "a-2")
    _link(other["id"], "b-1")
    assert client.get(f"/api/v1/oidc/providers/{provider['id']}").json()["links"] == 2

    caplog.set_level(logging.INFO, logger="nexdeck.oidc")
    moved = client.patch(f"/api/v1/oidc/providers/{provider['id']}", json={**PROVIDER, "issuer_url": "https://elsewhere.example.com/realms/home"}, headers=CSRF)
    assert moved.status_code == 200, moved.text
    assert moved.json()["links"] == 0
    assert _links(provider["id"]) == 0, "a subject of the old issuer must not open an account at the new one"
    assert _links(other["id"]) == 1, "the links of another provider are none of this change's business"
    assert f"OIDC issuer of provider {PROVIDER['slug']} changed, 2 links dropped" in caplog.text


@pytest.mark.parametrize("written", [
    PROVIDER["issuer_url"] + "/",
    f"  {PROVIDER['issuer_url']}/  ",
    f" {PROVIDER['issuer_url']}",
])
def test_the_same_issuer_written_differently_drops_nothing(client: TestClient, provider: dict, written: str) -> None:  # noqa: F811
    """authentik hands its issuer out with a slash at the end; the form stores it without."""
    _link(provider["id"], "a-1")
    saved = client.patch(f"/api/v1/oidc/providers/{provider['id']}", json={**PROVIDER, "issuer_url": written}, headers=CSRF)
    assert saved.status_code == 200, saved.text
    assert _links(provider["id"]) == 1
    assert saved.json()["issuer_url"] == PROVIDER["issuer_url"], "stored without spaces and without the slash at the end"


def test_same_issuer_ignores_spaces_and_the_slash_at_the_end() -> None:
    assert oidc_service.same_issuer("https://a.example.com/o/x/", " https://a.example.com/o/x ")
    assert not oidc_service.same_issuer("https://a.example.com/o/x", "https://a.example.com/o/y")


@pytest.mark.parametrize(("a", "b"), [
    ("https://ID.example.com/realms/home", "https://id.example.com/realms/home"),
    ("https://id.example.com/realms/Home", "https://id.example.com/realms/home"),
    ("http://id.example.com/realms/home", "https://id.example.com/realms/home"),
    ("https://id.example.com/realms/home", "https://id.example.com/realms/home/x"),
    ("https://id.example.com/realms/home", "https://id.example.com/realms"),
])
def test_same_issuer_equates_nothing_else(a: str, b: str) -> None:
    """Spaces and the slash at the end, nothing more: the token's ``iss`` is compared as written."""
    assert not oidc_service.same_issuer(a, b)
    assert not oidc_service.same_issuer(b, a)


def test_an_issuer_changed_only_in_case_drops_the_links(client: TestClient, provider: dict) -> None:  # noqa: F811
    _link(provider["id"], "a-1")
    moved = client.patch(f"/api/v1/oidc/providers/{provider['id']}", json={**PROVIDER, "issuer_url": PROVIDER["issuer_url"].replace("home", "Home")}, headers=CSRF)
    assert moved.status_code == 200, moved.text
    assert moved.json()["links"] == 0
    assert _links(provider["id"]) == 0


# -- 2. a new provider lets nobody in on its own -------------------------------


def test_a_provider_added_without_saying_so_creates_no_accounts(client: TestClient, provider: dict, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    body = {key: value for key, value in OTHER.items() if key != "auto_create"}
    made = client.post("/api/v1/oidc/providers", json=body, headers=CSRF)
    assert made.status_code == 201, made.text
    assert made.json()["auto_create"] is False

    _pretend_the_provider_answers(monkeypatch, {"sub": "a-stranger", "email": "stranger@example.com"})
    visitor = TestClient(client.app)
    state, _nonce = _walk_through(visitor, OTHER["slug"])
    answer = _callback(visitor, OTHER["slug"], state)
    assert "oidc_no_account" in answer.headers["location"], answer.headers["location"]
    with db_session() as db:
        assert db.query(User).count() == 1, "only the administrator; the stranger got nothing"


def test_the_model_default_is_off(client: TestClient) -> None:
    with db_session() as db:
        row = OidcProvider(slug="bare", label="Bare", issuer_url="https://bare.example.com", client_id="x", client_secret="")
        db.add(row)
        db.flush()
        assert row.auto_create is False


# -- 3. the attempt cookie ------------------------------------------------------


def _attempt_payload(slug: str) -> dict:
    return {
        "slug": slug, "state": secrets.token_urlsafe(24), "nonce": secrets.token_urlsafe(24), "verifier": secrets.token_urlsafe(48),
        "purpose": "login", "user_id": None, "type": "oidc", "exp": int(time.time()) + 600,
    }


def test_an_attempt_signed_with_the_session_key_is_refused(client: TestClient, provider: dict, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    _pretend_the_provider_answers(monkeypatch, {"sub": "a-stranger"})
    payload = _attempt_payload(PROVIDER["slug"])
    forged = jwt.encode(payload, _signing_key(), algorithm=ALGORITHM)
    assert oidc_service.unpack_state(forged) is None

    visitor = TestClient(client.app)
    visitor.cookies.set(oidc_service.COOKIE_NAME, forged, path="/api/v1/auth/oidc")
    answer = _callback(visitor, PROVIDER["slug"], payload["state"])
    assert "oidc_state_mismatch" in answer.headers["location"], answer.headers["location"]


def test_a_session_token_is_no_attempt(client: TestClient) -> None:
    assert oidc_service.unpack_state(create_session_token(1, 1)) is None


def test_an_attempt_without_its_type_is_refused(client: TestClient) -> None:
    """Same key, but not marked as an attempt: whatever it is, it is not one."""
    payload = _attempt_payload(PROVIDER["slug"])
    del payload["type"]
    assert oidc_service.unpack_state(jwt.encode(payload, oidc_service._attempt_key(), algorithm=ALGORITHM)) is None
    payload["type"] = "session"
    assert oidc_service.unpack_state(jwt.encode(payload, oidc_service._attempt_key(), algorithm=ALGORITHM)) is None


def test_a_state_is_used_once(client: TestClient, provider: dict, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    _link(provider["id"], "a-1")
    _pretend_the_provider_answers(monkeypatch, {"sub": "a-1"})
    visitor = TestClient(client.app)
    started = visitor.get(f"/api/v1/auth/oidc/{PROVIDER['slug']}/login", follow_redirects=False)
    raw = ""
    for header, value in started.headers.multi_items():
        if header.lower() == "set-cookie" and value.startswith(f"{oidc_service.COOKIE_NAME}="):
            raw = value.split("=", 1)[1].split(";", 1)[0]
    state = oidc_service.unpack_state(raw)["state"]

    first = TestClient(client.app)
    first.cookies.set(oidc_service.COOKIE_NAME, raw, path="/api/v1/auth/oidc")
    assert _callback(first, PROVIDER["slug"], state).headers["location"] == "/"

    # The same cookie and the same state again, from a browser that kept a copy.
    again = TestClient(client.app)
    again.cookies.set(oidc_service.COOKIE_NAME, raw, path="/api/v1/auth/oidc")
    replay = _callback(again, PROVIDER["slug"], state)
    assert "oidc_state_mismatch" in replay.headers["location"], replay.headers["location"]
    assert again.get("/api/v1/auth/me").status_code == 401


def test_a_failed_code_exchange_uses_the_state_up_as_well(client: TestClient, provider: dict, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    """Used up when it is checked, not when the exchange worked: a refused code does not leave it open for a second go."""
    _link(provider["id"], "a-1")
    _pretend_the_provider_answers(monkeypatch, {"sub": "a-1"})
    visitor = TestClient(client.app)
    started = visitor.get(f"/api/v1/auth/oidc/{PROVIDER['slug']}/login", follow_redirects=False)
    raw = ""
    for header, value in started.headers.multi_items():
        if header.lower() == "set-cookie" and value.startswith(f"{oidc_service.COOKIE_NAME}="):
            raw = value.split("=", 1)[1].split(";", 1)[0]
    state = oidc_service.unpack_state(raw)["state"]

    async def refused(*_args, **_kwargs) -> dict:  # noqa: ANN002, ANN003
        raise oidc_service.OidcError("oidc_token_refused", "The identity provider refused the code (HTTP 400).")

    monkeypatch.setattr(oidc_service, "exchange", refused)
    first = TestClient(client.app)
    first.cookies.set(oidc_service.COOKIE_NAME, raw, path="/api/v1/auth/oidc")
    assert "oidc_token_refused" in _callback(first, PROVIDER["slug"], state).headers["location"]

    async def works(*_args, **_kwargs) -> dict:  # noqa: ANN002, ANN003
        return {"id_token": "pretend", "access_token": "pretend"}

    monkeypatch.setattr(oidc_service, "exchange", works)
    again = TestClient(client.app)
    again.cookies.set(oidc_service.COOKIE_NAME, raw, path="/api/v1/auth/oidc")
    replay = _callback(again, PROVIDER["slug"], state)
    assert "oidc_state_mismatch" in replay.headers["location"], replay.headers["location"]
    assert again.get("/api/v1/auth/me").status_code == 401
