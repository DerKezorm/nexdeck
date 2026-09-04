"""First start, sign-in, sessions, tokens and the request guards."""

from __future__ import annotations

from fastapi.testclient import TestClient

from .conftest import ADMIN, CSRF, create_user, login, setup_admin


def test_setup_creates_admin_and_signs_in(client: TestClient) -> None:
    assert client.get("/api/v1/setup/status").json()["needs_setup"] is True
    user = setup_admin(client)
    assert user["role"] == "admin"
    assert client.get("/api/v1/setup/status").json()["needs_setup"] is False
    assert client.get("/api/v1/auth/me").json()["username"] == ADMIN["username"]
    # A second setup is refused.
    assert client.post("/api/v1/setup", json={**ADMIN, "username": "other"}).status_code == 409


def test_wrong_password_is_refused_and_throttled(client: TestClient) -> None:
    setup_admin(client)
    client.post("/api/v1/auth/logout", headers=CSRF)
    assert client.get("/api/v1/auth/me").status_code == 401
    codes = [client.post("/api/v1/auth/login", json={"username": "admin", "password": "wrong"}).status_code for _ in range(11)]
    assert codes[0] == 401
    assert 429 in codes, "the eleventh failure must be throttled"


def test_cookie_sessions_need_the_request_header(client: TestClient) -> None:
    setup_admin(client)
    # A cookie session on an unsafe method without the header is refused.
    assert client.post("/api/v1/boards", json={"name": "X"}).status_code == 403
    assert client.post("/api/v1/boards", json={"name": "X"}, headers=CSRF).status_code == 201


def test_api_token_authenticates_without_cookie(client: TestClient) -> None:
    setup_admin(client)
    token = client.post("/api/v1/tokens", json={"name": "script"}, headers=CSRF).json()["token"]
    assert token.startswith("nd_")
    bare = TestClient(client.app)
    assert bare.get("/api/v1/auth/me").status_code == 401
    response = bare.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json()["auth_kind"] == "token"
    # Bearer requests need no CSRF header: they cannot come from a cross-site form.
    assert bare.post("/api/v1/boards", json={"name": "Via token"}, headers={"Authorization": f"Bearer {token}"}).status_code == 201
    # Revoked tokens stop working.
    token_id = client.get("/api/v1/tokens").json()[0]["id"]
    client.delete(f"/api/v1/tokens/{token_id}", headers=CSRF)
    assert bare.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_password_change_signs_out_other_sessions(client: TestClient) -> None:
    setup_admin(client)
    other = TestClient(client.app)
    login(other, ADMIN["username"], ADMIN["password"])
    assert other.get("/api/v1/auth/me").status_code == 200
    response = client.post("/api/v1/auth/password", json={"current_password": ADMIN["password"], "new_password": "a-brand-new-password"}, headers=CSRF)
    assert response.status_code == 204
    assert other.get("/api/v1/auth/me").status_code == 401, "the older session must be invalid now"
    assert client.get("/api/v1/auth/me").status_code == 401, "and so is this one; the browser signs in again"
    login(client, ADMIN["username"], "a-brand-new-password")


def test_guests_may_look_but_not_change(client: TestClient) -> None:
    setup_admin(client)
    create_user(client, "visitor", role="guest")
    guest = TestClient(client.app)
    login(guest, "visitor", "another-long-password")
    assert guest.get("/api/v1/boards").status_code == 200
    assert guest.post("/api/v1/boards", json={"name": "Nope"}, headers=CSRF).status_code == 403
    assert guest.get("/api/v1/users").status_code == 200
    assert guest.post("/api/v1/users", json={"username": "x", "password": "long-enough-pw"}, headers=CSRF).status_code == 403


def test_disabled_user_cannot_sign_in(client: TestClient) -> None:
    setup_admin(client)
    user = create_user(client, "sam")
    other = TestClient(client.app)
    login(other, "sam", "another-long-password")
    client.patch(f"/api/v1/users/{user['id']}", json={"disabled": True}, headers=CSRF)
    assert other.get("/api/v1/auth/me").status_code == 401
    assert other.post("/api/v1/auth/login", json={"username": "sam", "password": "another-long-password"}).status_code == 401


def test_admin_cannot_remove_own_role_or_last_admin(client: TestClient) -> None:
    me = setup_admin(client)
    assert client.patch(f"/api/v1/users/{me['id']}", json={"role": "user"}, headers=CSRF).status_code == 400
    assert client.delete(f"/api/v1/users/{me['id']}", headers=CSRF).status_code == 400
