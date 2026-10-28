"""MCP: the endpoint, its walls in their order, and the keys.

Each wall is a test of its own that fails when the wall is taken out; the
endpoint has to turn away a web page, a switched-off installation, a key
that is wrong, run out, withdrawn or outlived by a password, and a program
that calls too often.
"""

from __future__ import annotations

import logging
import re
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import db_session
from app.models import McpKey, User, utcnow
from app.services import journal, mcp, two_factor

from .conftest import CSRF, create_user, login, setup_admin
from .mcp_kit import _quiet, board, make_key, names, rpc, switch  # noqa: F401


@pytest.fixture
def ready(client: TestClient) -> TestClient:
    setup_admin(client)
    switch(client)
    return client


# -- the protocol ---------------------------------------------------------------------------


def test_initialize_ping_and_a_notification(ready: TestClient) -> None:
    _key, token = make_key(ready)
    hello = rpc(ready, token, "initialize", {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "x"}})
    assert hello.status_code == 200 and hello.headers["content-type"].startswith("application/json")
    result = hello.json()["result"]
    assert result["protocolVersion"] == "2025-03-26" and result["serverInfo"]["name"] == "nexdeck"
    assert result["capabilities"] == {"tools": {"listChanged": False}}
    unknown = rpc(ready, token, "initialize", {"protocolVersion": "1999-01-01"})
    assert unknown.json()["result"]["protocolVersion"] == "2025-06-18", "a version not spoken here is answered with the newest"
    assert rpc(ready, token, "ping").json() == {"jsonrpc": "2.0", "id": 1, "result": {}}
    assert rpc(ready, token, "notifications/initialized", number=None).status_code == 202
    assert rpc(ready, token, "resources/list").json()["error"]["code"] == -32601


def test_no_stream_and_no_strange_versions_or_bodies(ready: TestClient) -> None:
    _key, token = make_key(ready)
    assert ready.get("/api/mcp").status_code == 405
    refused = rpc(ready, token, "ping", headers={"MCP-Protocol-Version": "2023-01-01"})
    assert refused.status_code == 400 and refused.json()["detail"]["code"] == "protocol_version"
    assert rpc(ready, token, "ping", headers={"MCP-Protocol-Version": "2025-06-18"}).status_code == 200
    broken = ready.post("/api/mcp", content="{not json", headers={"Authorization": f"Bearer {token}"})
    assert broken.status_code == 400 and broken.json()["error"]["code"] == -32700
    deep = ready.post("/api/mcp", content="[" * 100000 + "]" * 100000, headers={"Authorization": f"Bearer {token}"})
    assert deep.status_code == 400
    batch = ready.post("/api/mcp", content='[{"jsonrpc": "2.0", "id": 1, "method": "ping"}]', headers={"Authorization": f"Bearer {token}"})
    assert batch.json()["error"]["code"] == -32600


# -- the walls, in their order ----------------------------------------------------------------


def test_a_request_with_an_origin_is_refused_even_with_a_good_key(ready: TestClient) -> None:
    _key, token = make_key(ready)
    refused = rpc(ready, token, "ping", headers={"Origin": "https://evil.example.com"})
    assert refused.status_code == 403 and refused.json()["detail"]["code"] == "origin_refused"
    # Before every other wall: switched off, a page still learns nothing more than "not for web pages".
    switch(ready, allowed=False)
    assert rpc(ready, None, "ping", headers={"Origin": "https://evil.example.com"}).status_code == 403


def test_mcp_is_off_until_an_administrator_switches_it_on(client: TestClient) -> None:
    setup_admin(client)
    assert client.get("/api/v1/mcp/admin").json() == {"allowed": False, "max_level": "act", "oauth_allowed": False, "blocked_tools": []}
    refused = client.post("/api/v1/mcp/keys", json={"name": "x", "level": "read"}, headers=CSRF)
    assert refused.status_code == 403 and refused.json()["detail"]["code"] == "mcp_off"
    switch(client)
    _key, token = make_key(client)
    assert rpc(client, token, "ping").status_code == 200
    switch(client, allowed=False)
    # Off answers like an address that is not there, before the key is even looked at.
    assert rpc(client, token, "ping").status_code == 404
    assert rpc(client, None, "ping").status_code == 404


def test_without_a_valid_key_the_answer_is_401_with_a_bearer_challenge(ready: TestClient) -> None:
    for token in (None, "", "ndm_" + "x" * 43, "nd_somethingelse", "Basic abc"):
        refused = rpc(ready, token, "ping")
        assert refused.status_code == 401, token
        assert refused.headers["www-authenticate"] == "Bearer"
    # The session cookie counts for nothing here: the test client is signed in as the administrator.
    assert ready.get("/api/v1/auth/me").status_code == 200
    assert rpc(ready, None, "ping").status_code == 401


def test_with_connectors_allowed_the_challenge_says_where_to_sign_in(ready: TestClient) -> None:
    switch(ready, oauth_allowed=True)
    refused = rpc(ready, None, "ping")
    assert refused.status_code == 401
    assert refused.headers["www-authenticate"] == 'Bearer resource_metadata="http://testserver/.well-known/oauth-protected-resource"'


def test_an_api_token_is_no_key_here(ready: TestClient) -> None:
    for scope in ("read", "full"):
        token = ready.post("/api/v1/tokens", json={"name": scope, "scope": scope}, headers=CSRF).json()["token"]
        assert rpc(ready, token, "ping").status_code == 401, scope


def _age_key(key_id: int, **changes: object) -> None:
    with db_session() as db:
        row = db.get(McpKey, key_id)
        for name, value in changes.items():
            setattr(row, name, value)


def test_a_key_that_ran_out_is_refused(ready: TestClient) -> None:
    key, token = make_key(ready, expires_days=30)
    assert rpc(ready, token, "ping").status_code == 200
    _age_key(key["id"], expires_at=utcnow() - timedelta(seconds=1))
    assert rpc(ready, token, "ping").status_code == 401


def test_a_withdrawn_or_locked_key_is_refused_and_stays_in_the_list(ready: TestClient) -> None:
    mine, token = make_key(ready)
    assert ready.delete(f"/api/v1/mcp/keys/{mine['id']}", headers=CSRF).status_code == 204
    assert rpc(ready, token, "ping").status_code == 401
    assert [key["revoked"] for key in ready.get("/api/v1/mcp/keys").json()] == [True]
    assert ready.delete(f"/api/v1/mcp/keys/{mine['id']}", headers=CSRF).status_code == 404

    create_user(ready, "kim")
    login(ready, "kim", "another-long-password")
    theirs, their_token = make_key(ready, name="Kim's agent")
    assert rpc(ready, their_token, "ping").status_code == 200
    login(ready, "admin", "correct-horse-battery")
    listed = ready.get("/api/v1/mcp/admin/keys").json()
    assert [(key["user"], key["name"], key["revoked"]) for key in listed] == [("admin", "Claude", True), ("kim", "Kim's agent", False)]
    assert ready.delete(f"/api/v1/mcp/admin/keys/{theirs['id']}", headers=CSRF).status_code == 204
    assert rpc(ready, their_token, "ping").status_code == 401


def test_only_the_owner_withdraws_a_key_and_only_an_administrator_sees_them_all(ready: TestClient) -> None:
    mine, token = make_key(ready)
    create_user(ready, "kim")
    login(ready, "kim", "another-long-password")
    assert ready.delete(f"/api/v1/mcp/keys/{mine['id']}", headers=CSRF).status_code == 404
    assert ready.put(f"/api/v1/mcp/keys/{mine['id']}/rights", json={"tool_rights": {}}, headers=CSRF).status_code == 404
    assert ready.get("/api/v1/mcp/keys").json() == []
    assert ready.get("/api/v1/mcp/admin/keys").status_code == 403
    assert ready.delete(f"/api/v1/mcp/admin/keys/{mine['id']}", headers=CSRF).status_code == 403
    assert ready.put("/api/v1/mcp/admin", json={"allowed": False, "max_level": "read"}, headers=CSRF).status_code == 403
    assert rpc(ready, token, "ping").status_code == 200


def test_a_password_change_ends_every_key_of_the_account(ready: TestClient) -> None:
    _key, token = make_key(ready)
    assert rpc(ready, token, "ping").status_code == 200
    changed = ready.post("/api/v1/auth/password", json={"current_password": "correct-horse-battery", "new_password": "a-brand-new-password"},
                         headers=CSRF)
    assert changed.status_code == 204, changed.text
    assert rpc(ready, token, "ping").status_code == 401


def test_a_disabled_account_or_one_made_a_guest_holds_no_working_key(ready: TestClient) -> None:
    kim = create_user(ready, "kim")
    login(ready, "kim", "another-long-password")
    _key, token = make_key(ready)
    login(ready, "admin", "correct-horse-battery")
    assert rpc(ready, token, "ping").status_code == 200
    assert ready.patch(f"/api/v1/users/{kim['id']}", json={"role": "guest"}, headers=CSRF).status_code == 200
    assert rpc(ready, token, "ping").status_code == 401
    assert ready.patch(f"/api/v1/users/{kim['id']}", json={"role": "user"}, headers=CSRF).status_code == 200
    assert rpc(ready, token, "ping").status_code == 200
    assert ready.patch(f"/api/v1/users/{kim['id']}", json={"disabled": True}, headers=CSRF).status_code == 200
    assert rpc(ready, token, "ping").status_code == 401
    # Disabling ends what the account had opened, keys like sessions; enabled again, it makes new ones.
    assert ready.patch(f"/api/v1/users/{kim['id']}", json={"disabled": False}, headers=CSRF).status_code == 200
    assert rpc(ready, token, "ping").status_code == 401


def test_a_key_waits_while_the_account_owes_a_second_factor(ready: TestClient) -> None:
    _key, token = make_key(ready)
    with db_session() as db:
        two_factor.set_required(db, True)
    assert rpc(ready, token, "ping").status_code == 401
    with db_session() as db:
        two_factor.set_required(db, False)
    assert rpc(ready, token, "ping").status_code == 200


def test_the_brake_stops_a_key_that_calls_too_often(ready: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mcp, "PER_MINUTE", 3)
    _key, token = make_key(ready)
    _other, other = make_key(ready, name="Other")
    assert [rpc(ready, token, "ping").status_code for _ in range(4)] == [200, 200, 200, 429]
    slowed = rpc(ready, token, "ping")
    assert slowed.status_code == 429 and slowed.headers["retry-after"] == "60"
    assert rpc(ready, other, "ping").status_code == 200, "the brake is per key"


def test_the_brake_lets_a_key_go_again_after_a_minute() -> None:
    mcp.forget_calls()
    assert all(mcp.brake(7, now=100.0 + n * 0.1) for n in range(mcp.PER_MINUTE))
    assert mcp.brake(7, now=130.0) is False
    assert mcp.brake(7, now=160.5) is True


# -- the keys -------------------------------------------------------------------------------


def test_a_key_is_shown_once_and_only_its_hash_is_kept(ready: TestClient) -> None:
    key, token = make_key(ready, "act", expires_days=90)
    assert re.fullmatch(r"ndm_[A-Za-z0-9_-]{43}", token)
    assert token.startswith(key["prefix"]) and len(key["prefix"]) < 16
    assert key["kind"] == "key" and key["level"] == "act" and key["boards"] is None and key["tool_rights"] == {}
    assert key["client"] is None and key["revoked"] is False and key["expires_at"] is not None
    listed = ready.get("/api/v1/mcp/keys").json()
    assert token not in str(listed)
    with db_session() as db:
        stored = db.scalar(select(McpKey))
        assert token not in (stored.token_hash, stored.prefix, str(stored.tool_rights))


def test_the_key_never_reaches_the_log() -> None:
    token = "ndm_" + "A1b2C3d4" * 5 + "xyz"
    assert journal.redact(f"Authorization: Bearer {token} sent") == "Authorization: Bearer ndm_*** sent"
    assert token not in journal.redact(f"/api/mcp?key={token}")
    record = logging.LogRecord("nexdeck.mcp", logging.INFO, __file__, 1, "Pasted %s by mistake", (token,), None)
    journal._Context().filter(record)
    assert token not in record.getMessage()


def test_how_long_a_key_lives_is_one_of_four_choices(ready: TestClient) -> None:
    for days in (30, 90, 365, None):
        assert ready.post("/api/v1/mcp/keys", json={"name": "x", "level": "read", "expires_days": days}, headers=CSRF).status_code == 201
    refused = ready.post("/api/v1/mcp/keys", json={"name": "x", "level": "read", "expires_days": 7}, headers=CSRF)
    assert refused.status_code == 422 and refused.json()["detail"]["code"] == "bad_expiry"


def test_an_account_holds_at_most_twenty_keys(ready: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    for number in range(mcp.MAX_KEYS):
        make_key(ready, name=f"k{number}")
    refused = ready.post("/api/v1/mcp/keys", json={"name": "one more", "level": "read"}, headers=CSRF)
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "too_many_keys"
    first = ready.get("/api/v1/mcp/keys").json()[0]
    ready.delete(f"/api/v1/mcp/keys/{first['id']}", headers=CSRF)
    assert ready.post("/api/v1/mcp/keys", json={"name": "one more", "level": "read"}, headers=CSRF).status_code == 201


def test_a_guest_makes_no_key_and_an_api_token_makes_none_either(ready: TestClient) -> None:
    create_user(ready, "visitor", role="guest")
    token = ready.post("/api/v1/tokens", json={"name": "script", "scope": "full"}, headers=CSRF).json()["token"]
    script = TestClient(ready.app)
    from_token = script.post("/api/v1/mcp/keys", json={"name": "x", "level": "read"}, headers={"Authorization": f"Bearer {token}"})
    assert from_token.status_code == 403 and from_token.json()["detail"]["code"] == "session_required"
    login(ready, "visitor", "another-long-password")
    refused = ready.post("/api/v1/mcp/keys", json={"name": "x", "level": "read"}, headers=CSRF)
    assert refused.status_code == 403


def test_a_key_above_the_ceiling_is_refused_and_a_lowered_ceiling_holds_for_old_keys(ready: TestClient) -> None:
    _key, token = make_key(ready, "act", rights={"press_button": "allow"})
    assert "press_button" in names(ready, token)
    switch(ready, max_level="read")
    refused = ready.post("/api/v1/mcp/keys", json={"name": "x", "level": "act"}, headers=CSRF)
    assert refused.status_code == 403 and refused.json()["detail"]["code"] == "level_not_allowed"
    assert "press_button" not in names(ready, token), "the ceiling holds for a key made before it was lowered"
    assert ready.get("/api/v1/mcp/status").json()["max_level"] == "read"


def test_a_key_sees_only_boards_its_account_sees_and_a_foreign_one_is_refused_like_an_unknown_one(ready: TestClient) -> None:
    secret = board(ready, "Admin only")
    create_user(ready, "kim")
    login(ready, "kim", "another-long-password")
    own = board(ready, "Kim")
    key, _token = make_key(ready, boards=[own["id"]])
    assert key["boards"] == [own["id"]]
    foreign = ready.post("/api/v1/mcp/keys", json={"name": "x", "level": "read", "boards": [secret["id"]]}, headers=CSRF)
    missing = ready.post("/api/v1/mcp/keys", json={"name": "x", "level": "read", "boards": [99999]}, headers=CSRF)
    assert foreign.status_code == missing.status_code == 422
    assert foreign.json() == missing.json()
    assert ready.post("/api/v1/mcp/keys", json={"name": "x", "level": "read", "boards": []}, headers=CSRF).status_code == 422


def test_the_status_names_the_public_address(ready: TestClient) -> None:
    assert ready.get("/api/v1/mcp/status").json() == {"allowed": True, "max_level": "act", "oauth_allowed": False,
                                                      "endpoint": "http://testserver/api/mcp"}
    assert ready.patch("/api/v1/settings", json={"public_url": "https://deck.example.com/"}, headers=CSRF).status_code == 200
    assert ready.get("/api/v1/mcp/status").json()["endpoint"] == "https://deck.example.com/api/mcp"


def test_the_key_records_when_it_was_last_used(ready: TestClient) -> None:
    key, token = make_key(ready)
    assert ready.get("/api/v1/mcp/keys").json()[0]["last_used_at"] is None
    rpc(ready, token, "ping")
    assert ready.get("/api/v1/mcp/keys").json()[0]["last_used_at"] is not None
    with db_session() as db:
        assert db.get(User, db.get(McpKey, key["id"]).user_id).username == "admin"
