"""MCP connectors: a program that signs in with OAuth instead of being handed a key.

The whole way a program such as Claude goes, from the 401 of ``/api/mcp`` to
``tools/list`` with its own access token, and every way it must fail: a
wrong PKCE verifier, a code brought twice or too late, another resource, a
return address nobody may use, a refresh token brought again, a password
change, the switch, a sender that registers too often, a consent page
reached without a session, a level above the ceiling, a board of another
account.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import secrets
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import db_session
from app.models import McpKey, McpOAuthCode, User, utcnow
from app.services import journal, mcp_oauth, two_factor

from .conftest import CSRF, create_user, login, setup_admin
from .mcp_kit import _quiet, board, make_key, names, rpc, switch  # noqa: F401

BASE = "http://testserver"
RESOURCE = f"{BASE}/api/mcp"
BACK = "https://app.example.com/callback"


@pytest.fixture(autouse=True)
def _fresh_brake() -> None:
    mcp_oauth.forget_registrations()


@pytest.fixture
def ready(client: TestClient) -> TestClient:
    setup_admin(client)
    switch(client, oauth_allowed=True)
    return client


def pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def register(client: TestClient, *uris: str, name: str = "Claude") -> str:
    answer = client.post("/api/mcp/oauth/register", json={"client_name": name, "redirect_uris": list(uris or (BACK,)),
                                                          "token_endpoint_auth_method": "none"})
    assert answer.status_code == 201, answer.text
    return answer.json()["client_id"]


def request_of(client_id: str, challenge: str, **extra: str) -> dict[str, str]:
    return {"client_id": client_id, "redirect_uri": BACK, "code_challenge": challenge, "code_challenge_method": "S256",
            "resource": RESOURCE, **extra}


def agree(client: TestClient, client_id: str, challenge: str, *, allow: bool = True, level: str = "read",
          boards: list[int] | None = None, **extra: str):  # noqa: ANN201 - a response
    return client.post("/api/v1/mcp/consent", json={**request_of(client_id, challenge, **extra), "state": "xyz", "allow": allow,
                                                     "level": level, "boards": boards}, headers=CSRF)


def code_of(answer) -> str:  # noqa: ANN001
    assert answer.status_code == 200, answer.text
    query = parse_qs(urlsplit(answer.json()["redirect"]).query)
    assert query["state"] == ["xyz"] and query["iss"] == [BASE]
    return query["code"][0]


def trade(client: TestClient, client_id: str, code: str, verifier: str, **extra: str):  # noqa: ANN201 - a response
    return client.post("/api/mcp/oauth/token", data={"grant_type": "authorization_code", "code": code, "client_id": client_id,
                                                     "redirect_uri": BACK, "code_verifier": verifier, "resource": RESOURCE, **extra})


def renew(client: TestClient, client_id: str, refresh_token: str):  # noqa: ANN201 - a response
    return client.post("/api/mcp/oauth/token", data={"grant_type": "refresh_token", "refresh_token": refresh_token,
                                                     "client_id": client_id, "resource": RESOURCE})


def connect(client: TestClient, *, level: str = "read", boards: list[int] | None = None, name: str = "Claude",
            client_id: str | None = None) -> tuple[str, dict]:
    """Registration, consent and the trade, as a program and its person go them; the program's id and its tokens."""
    client_id = client_id or register(client, name=name)
    verifier, challenge = pkce()
    answer = trade(client, client_id, code_of(agree(client, client_id, challenge, level=level, boards=boards)), verifier)
    assert answer.status_code == 200, answer.text
    return client_id, answer.json()


def program(client: TestClient) -> TestClient:
    """The program's own client: no cookie of the person who signed it in."""
    return TestClient(client.app)


# -- the whole way --------------------------------------------------------------------------------


def test_the_whole_way_from_the_401_to_tools_list(ready: TestClient) -> None:
    claude = program(ready)
    refused = rpc(claude, None, "ping")
    assert refused.status_code == 401
    metadata_at = refused.headers["www-authenticate"].split('resource_metadata="')[1].rstrip('"')
    resource = claude.get(urlsplit(metadata_at).path)
    assert resource.status_code == 200 and resource.json()["resource"] == RESOURCE
    assert claude.get("/.well-known/oauth-protected-resource/api/mcp").json() == resource.json()
    issuer = resource.json()["authorization_servers"][0]
    server = claude.get("/.well-known/oauth-authorization-server").json()
    assert server["issuer"] == issuer == BASE
    assert server["code_challenge_methods_supported"] == ["S256"]
    assert server["token_endpoint"] == f"{BASE}/api/mcp/oauth/token"

    registered = claude.post(urlsplit(server["registration_endpoint"]).path,
                             json={"client_name": "Claude", "redirect_uris": [BACK]})
    assert registered.status_code == 201, registered.text
    client_id = registered.json()["client_id"]
    verifier, challenge = pkce()
    sent = claude.get(urlsplit(server["authorization_endpoint"]).path, params={**request_of(client_id, challenge),
                                                                              "response_type": "code", "state": "xyz"},
                      follow_redirects=False)
    assert sent.status_code == 302
    page = urlsplit(sent.headers["location"])
    assert page.path == "/connect"
    asked = {key: values[0] for key, values in parse_qs(page.query).items()}
    assert asked["client_id"] == client_id and asked["state"] == "xyz" and asked["resource"] == RESOURCE

    # The person, in the browser where they are signed in.
    lab = board(ready)
    shown = ready.get("/api/v1/mcp/consent", params=request_of(client_id, challenge))
    assert shown.status_code == 200, shown.text
    assert shown.json()["client_name"] == "Claude" and shown.json()["redirect_host"] == "app.example.com"
    assert shown.json()["max_level"] == "act" and {"id": lab["id"], "name": "Lab"} in shown.json()["boards"]
    code = code_of(agree(ready, client_id, challenge))
    assert code.startswith("ndc_")

    tokens = trade(claude, client_id, code, verifier)
    assert tokens.status_code == 200, tokens.text
    assert tokens.headers["cache-control"] == "no-store"
    body = tokens.json()
    assert body["token_type"] == "Bearer" and body["expires_in"] == 3600
    assert body["access_token"].startswith("ndo_") and body["refresh_token"].startswith("ndr_")
    listed = rpc(claude, body["access_token"], "tools/list")
    assert listed.status_code == 200, listed.text
    assert "find_cards" in [tool["name"] for tool in listed.json()["result"]["tools"]]

    keys = ready.get("/api/v1/mcp/keys").json()
    assert [(key["kind"], key["client"], key["level"]) for key in keys] == [("oauth", "Claude", "read")]
    # The list says when the connector stops unless it refreshes: the refresh token's end, not the hour.
    assert keys[0]["expires_at"] > (utcnow() + timedelta(days=29)).isoformat()


def test_a_connector_sees_no_more_than_its_level_and_boards(ready: TestClient) -> None:
    lab = board(ready)
    board(ready, "Other")
    _client_id, tokens = connect(ready, level="read", boards=[lab["id"]])
    assert "press_button" not in names(program(ready), tokens["access_token"])
    with db_session() as db:
        key = db.scalar(select(McpKey).where(McpKey.kind == "oauth"))
        assert key.boards == [lab["id"]] and key.level == "read"


# -- the code -------------------------------------------------------------------------------------


def test_a_wrong_verifier_gets_no_token(ready: TestClient) -> None:
    client_id = register(ready)
    _verifier, challenge = pkce()
    code = code_of(agree(ready, client_id, challenge))
    other, _ = pkce()
    refused = trade(ready, client_id, code, other)
    assert refused.status_code == 400 and refused.json()["error"] == "invalid_grant"
    assert ready.get("/api/v1/mcp/keys").json() == []


def test_a_request_without_pkce_s256_is_explained_by_the_page_that_may_lead_back(ready: TestClient) -> None:
    client_id = register(ready)
    wrong = {"client_id": client_id, "redirect_uri": BACK, "response_type": "code", "code_challenge": "x" * 43,
             "code_challenge_method": "plain", "state": "s1"}
    sent = ready.get("/api/mcp/oauth/authorize", params=wrong, follow_redirects=False)
    assert sent.status_code == 302 and urlsplit(sent.headers["location"]).path == "/connect"
    refused = ready.get("/api/v1/mcp/consent", params={**request_of(client_id, "x" * 43), "code_challenge_method": "plain", "state": "s1"})
    assert refused.status_code == 400 and refused.json()["detail"]["code"] == "oauth_pkce"
    # The way back is offered, to the registered address and with the mistake in OAuth's words.
    back = urlsplit(refused.json()["detail"]["back"])
    assert f"{back.scheme}://{back.netloc}{back.path}" == BACK
    assert parse_qs(back.query)["error"] == ["invalid_request"] and parse_qs(back.query)["state"] == ["s1"]
    assert refused.json()["detail"]["host"] == "app.example.com"
    _verifier, challenge = pkce()
    implicit = ready.get("/api/v1/mcp/consent", params={**request_of(client_id, challenge), "response_type": "token", "state": "s1"})
    assert implicit.status_code == 400 and implicit.json()["detail"]["code"] == "oauth_response_type"
    assert parse_qs(urlsplit(implicit.json()["detail"]["back"]).query)["error"] == ["unsupported_response_type"]
    # A response type that was never sent is no "code" either.
    empty = ready.get("/api/v1/mcp/consent", params={**request_of(client_id, challenge), "response_type": ""})
    assert empty.status_code == 400 and empty.json()["detail"]["code"] == "oauth_response_type"


def test_a_code_is_traded_once_and_the_second_time_ends_what_the_first_made(ready: TestClient) -> None:
    client_id = register(ready)
    verifier, challenge = pkce()
    code = code_of(agree(ready, client_id, challenge))
    first = trade(ready, client_id, code, verifier)
    assert first.status_code == 200
    access = first.json()["access_token"]
    assert rpc(program(ready), access, "ping").status_code == 200
    again = trade(ready, client_id, code, verifier)
    assert again.status_code == 400 and again.json()["error"] == "invalid_grant"
    # Somebody else holds the code: what the first trade made ends with it.
    assert rpc(program(ready), access, "ping").status_code == 401
    assert renew(ready, client_id, first.json()["refresh_token"]).status_code == 400


def test_a_code_runs_out_after_ten_minutes(ready: TestClient) -> None:
    client_id = register(ready)
    verifier, challenge = pkce()
    code = code_of(agree(ready, client_id, challenge))
    with db_session() as db:
        row = db.scalar(select(McpOAuthCode))
        assert row.expires_at - row.created_at == timedelta(minutes=10)
        row.expires_at = utcnow() - timedelta(seconds=1)
    refused = trade(ready, client_id, code, verifier)
    assert refused.status_code == 400 and refused.json()["error"] == "invalid_grant"


def test_a_code_belongs_to_its_program_and_its_return_address(ready: TestClient) -> None:
    client_id = register(ready, BACK, "http://localhost:4711/cb")
    stranger = register(ready, name="Stranger")
    verifier, challenge = pkce()
    code = code_of(agree(ready, client_id, challenge))
    assert trade(ready, stranger, code, verifier).json()["error"] == "invalid_grant"
    verifier, challenge = pkce()
    code = code_of(agree(ready, client_id, challenge))
    assert trade(ready, client_id, code, verifier, redirect_uri="http://localhost:4711/cb").json()["error"] == "invalid_grant"
    assert trade(ready, "nobody", code, verifier).status_code == 401


# -- the resource ---------------------------------------------------------------------------------


def test_another_resource_is_refused_everywhere(ready: TestClient) -> None:
    client_id = register(ready)
    verifier, challenge = pkce()
    elsewhere = "https://other.example.com/api/mcp"
    shown = ready.get("/api/v1/mcp/consent", params=request_of(client_id, challenge, resource=elsewhere))
    assert shown.status_code == 400 and shown.json()["detail"]["code"] == "oauth_resource"
    assert parse_qs(urlsplit(shown.json()["detail"]["back"]).query)["error"] == ["invalid_target"]
    assert agree(ready, client_id, challenge, resource=elsewhere).status_code == 400
    code = code_of(agree(ready, client_id, challenge))
    refused = trade(ready, client_id, code, verifier, resource=elsewhere)
    assert refused.status_code == 400 and refused.json()["error"] == "invalid_target"


def test_the_resource_may_be_written_a_little_differently() -> None:
    assert mcp_oauth.same_resource("HTTPS://Deck.Example.com:443/api/mcp/", "https://deck.example.com/api/mcp")
    assert not mcp_oauth.same_resource("https://deck.example.com/api/mcp/x", "https://deck.example.com/api/mcp")
    assert not mcp_oauth.same_resource("https://deck.example.com:8443/api/mcp", "https://deck.example.com/api/mcp")
    assert not mcp_oauth.same_resource("http://deck.example.com/api/mcp", "https://deck.example.com/api/mcp")


# -- return addresses -----------------------------------------------------------------------------


@pytest.mark.parametrize(("uri", "fine"), [
    ("https://app.example.com/cb", True),
    ("http://localhost:33418/callback", True),
    ("http://127.0.0.1:9/cb", True),
    ("http://localhost/cb", True),
    ("http://app.example.com/cb", False),
    ("http://192.168.1.5:8080/cb", False),
    ("http://[::1]:8080/cb", False),
    ("https://app.example.com/cb#here", False),
    ("https://someone@app.example.com/cb", False),
    ("https://*.example.com/cb", False),
    ("javascript:alert(1)", False),
    ("https://app.example.com/c b", False),
    ("http://localhost:notaport/cb", False),
])
def test_return_addresses_are_https_or_the_own_machine(uri: str, fine: bool) -> None:
    assert mcp_oauth.valid_redirect(uri) is fine


def test_registration_refuses_a_return_address_nobody_may_use(ready: TestClient) -> None:
    refused = ready.post("/api/mcp/oauth/register", json={"client_name": "x", "redirect_uris": ["http://app.example.com/cb"]})
    assert refused.status_code == 400 and refused.json()["error"] == "invalid_redirect_uri"
    secret = ready.post("/api/mcp/oauth/register", json={"redirect_uris": [BACK], "token_endpoint_auth_method": "client_secret_post"})
    assert secret.status_code == 400 and secret.json()["error"] == "invalid_client_metadata"


def test_an_address_the_program_did_not_register_is_never_sent_to(ready: TestClient) -> None:
    client_id = register(ready)
    _verifier, challenge = pkce()
    stolen = "https://thief.example.com/cb"
    sent = ready.get("/api/mcp/oauth/authorize", params={**request_of(client_id, challenge), "redirect_uri": stolen,
                                                         "response_type": "code", "code_challenge_method": "plain"},
                     follow_redirects=False)
    # Not back to the address, even with a mistake to report: on to the page, which says what is wrong.
    assert urlsplit(sent.headers["location"]).path == "/connect"
    shown = ready.get("/api/v1/mcp/consent", params={**request_of(client_id, challenge), "redirect_uri": stolen})
    assert shown.status_code == 400 and shown.json()["detail"]["code"] == "oauth_redirect"
    assert "back" not in shown.json()["detail"], "no way back to an address nobody registered"
    posted = ready.post("/api/v1/mcp/consent", json={**request_of(client_id, challenge), "redirect_uri": stolen, "allow": True,
                                                     "level": "read"}, headers=CSRF)
    assert posted.status_code == 400 and posted.json()["detail"]["code"] == "oauth_redirect"


@pytest.mark.parametrize("mistake", [
    {"response_type": "x"}, {"response_type": ""}, {"response_type": "token"}, {"code_challenge_method": "plain"},
    {"code_challenge": ""}, {"resource": "https://other.example.com/api/mcp"}, {"redirect_uri": "https://thief.example.com/cb"},
    {"client_id": "nobody"}, {"client_id": ""},
], ids=lambda mistake: ",".join(f"{key}={value or 'empty'}" for key, value in mistake.items()))
def test_authorize_leads_nowhere_but_to_its_own_page_whatever_is_wrong(ready: TestClient, mistake: dict[str, str]) -> None:
    """⚠️ Anybody may register a return address without an account; a redirect to it for a mistake was an open redirect."""
    stranger = program(ready)
    client_id = register(stranger, "https://phish.example/login")
    _verifier, challenge = pkce()
    params = {"client_id": client_id, "redirect_uri": "https://phish.example/login", "response_type": "code", "code_challenge": challenge,
              "code_challenge_method": "S256", "state": "s", "resource": RESOURCE, **mistake}
    sent = stranger.get("/api/mcp/oauth/authorize", params=params, follow_redirects=False)
    assert sent.status_code == 302
    where = urlsplit(sent.headers["location"])
    assert (where.scheme, where.netloc, where.path) == ("", "", "/connect"), sent.headers["location"]
    # The request is kept whole for the page, the empty response type included.
    assert "response_type" in parse_qs(where.query, keep_blank_values=True)


def test_authorize_with_nothing_at_all_goes_to_the_page_too(ready: TestClient) -> None:
    sent = program(ready).get("/api/mcp/oauth/authorize", follow_redirects=False)
    assert sent.status_code == 302 and urlsplit(sent.headers["location"]).path == "/connect"


# -- refreshing -----------------------------------------------------------------------------------


def test_a_refresh_gives_new_tokens_and_the_old_ones_stop(ready: TestClient) -> None:
    client_id, first = connect(ready)
    claude = program(ready)
    second = renew(claude, client_id, first["refresh_token"])
    assert second.status_code == 200, second.text
    tokens = second.json()
    assert tokens["access_token"] != first["access_token"] and tokens["refresh_token"] != first["refresh_token"]
    assert rpc(claude, tokens["access_token"], "ping").status_code == 200
    assert rpc(claude, first["access_token"], "ping").status_code == 401
    # Still the same connector, not a new one in the list.
    assert len(ready.get("/api/v1/mcp/keys").json()) == 1
    third = renew(claude, client_id, tokens["refresh_token"])
    assert third.status_code == 200


def test_a_refresh_token_brought_again_ends_the_whole_chain(ready: TestClient) -> None:
    client_id, first = connect(ready)
    claude = program(ready)
    second = renew(claude, client_id, first["refresh_token"]).json()
    again = renew(claude, client_id, first["refresh_token"])
    assert again.status_code == 400 and again.json()["error"] == "invalid_grant"
    # The thief and the program alike: the newer tokens are gone too, the key with them.
    assert renew(claude, client_id, second["refresh_token"]).status_code == 400
    assert rpc(claude, second["access_token"], "ping").status_code == 401
    assert ready.get("/api/v1/mcp/keys").json()[0]["revoked"] is True


def test_a_refresh_token_brought_by_two_at_the_same_moment_ends_the_chain(ready: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.models import McpOAuthRefresh

    client_id, tokens = connect(ready)
    checked = mcp_oauth._account_may

    def the_other_request_was_quicker(db, user_id, since):  # noqa: ANN001, ANN202
        # Between reading the token and using it up, another request used it: what two copies racing look like.
        db.execute(McpOAuthRefresh.__table__.update().values(used_at=utcnow()))
        db.commit()
        return checked(db, user_id, since)

    monkeypatch.setattr(mcp_oauth, "_account_may", the_other_request_was_quicker)
    assert renew(ready, client_id, tokens["refresh_token"]).json()["error"] == "invalid_grant"
    assert ready.get("/api/v1/mcp/keys").json()[0]["revoked"] is True


def test_a_refresh_token_belongs_to_its_program_and_this_resource(ready: TestClient) -> None:
    client_id, tokens = connect(ready)
    other = register(ready, name="Other")
    assert renew(ready, other, tokens["refresh_token"]).json()["error"] == "invalid_grant"
    elsewhere = ready.post("/api/mcp/oauth/token", data={"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"],
                                                         "client_id": client_id, "resource": "https://other.example.com/api/mcp"})
    assert elsewhere.status_code == 400 and elsewhere.json()["error"] == "invalid_target"
    # Neither used the token up: the program itself still refreshes with it.
    assert renew(ready, client_id, tokens["refresh_token"]).status_code == 200


def test_an_access_token_runs_out_after_an_hour(ready: TestClient) -> None:
    client_id, tokens = connect(ready)
    with db_session() as db:
        key = db.scalar(select(McpKey).where(McpKey.kind == "oauth"))
        assert timedelta(minutes=59) < key.expires_at - utcnow() <= timedelta(hours=1)
        key.expires_at = utcnow() - timedelta(seconds=1)
    assert rpc(program(ready), tokens["access_token"], "ping").status_code == 401
    assert renew(ready, client_id, tokens["refresh_token"]).status_code == 200


def test_a_refresh_token_runs_out(ready: TestClient) -> None:
    from app.models import McpOAuthRefresh

    client_id, tokens = connect(ready)
    with db_session() as db:
        row = db.scalar(select(McpOAuthRefresh))
        assert timedelta(days=29) < row.expires_at - utcnow() <= timedelta(days=30)
        row.expires_at = utcnow() - timedelta(seconds=1)
    assert renew(ready, client_id, tokens["refresh_token"]).json()["error"] == "invalid_grant"


def test_revoking_a_token_ends_its_connector(ready: TestClient) -> None:
    client_id, tokens = connect(ready)
    claude = program(ready)
    assert claude.post("/api/mcp/oauth/revoke", data={"token": "ndr_never-was-one", "client_id": client_id}).status_code == 200
    assert rpc(claude, tokens["access_token"], "ping").status_code == 200
    assert claude.post("/api/mcp/oauth/revoke", data={"token": tokens["refresh_token"], "client_id": client_id}).status_code == 200
    assert rpc(claude, tokens["access_token"], "ping").status_code == 401
    _client_id, other = connect(ready, client_id=client_id)
    assert claude.post("/api/mcp/oauth/revoke", data={"token": other["access_token"]}).status_code == 200
    assert renew(claude, client_id, other["refresh_token"]).status_code == 400


def test_withdrawing_the_key_in_the_list_ends_the_connector(ready: TestClient) -> None:
    client_id, tokens = connect(ready)
    key = ready.get("/api/v1/mcp/keys").json()[0]
    assert ready.delete(f"/api/v1/mcp/keys/{key['id']}", headers=CSRF).status_code == 204
    assert rpc(program(ready), tokens["access_token"], "ping").status_code == 401
    assert renew(ready, client_id, tokens["refresh_token"]).json()["error"] == "invalid_grant"


def test_signing_the_same_program_in_again_replaces_its_connector_and_keeps_its_rights(ready: TestClient) -> None:
    client_id, first = connect(ready, level="act")
    key = ready.get("/api/v1/mcp/keys").json()[0]
    assert ready.put(f"/api/v1/mcp/keys/{key['id']}/rights", json={"tool_rights": {"press_button": "allow"}}, headers=CSRF).status_code == 200
    _same, second = connect(ready, level="act", client_id=client_id)
    assert rpc(program(ready), first["access_token"], "ping").status_code == 401
    keys = ready.get("/api/v1/mcp/keys").json()
    assert [entry["revoked"] for entry in keys] == [True, False]
    assert keys[1]["tool_rights"] == {"press_button": "allow"}
    assert rpc(program(ready), second["access_token"], "ping").status_code == 200


# -- what ends everything -------------------------------------------------------------------------


def test_a_password_change_ends_the_connector(ready: TestClient) -> None:
    client_id, tokens = connect(ready)
    changed = ready.post("/api/v1/auth/password", json={"current_password": "correct-horse-battery",
                                                        "new_password": "a-brand-new-password"}, headers=CSRF)
    assert changed.status_code == 204, changed.text
    claude = program(ready)
    assert rpc(claude, tokens["access_token"], "ping").status_code == 401
    refused = renew(claude, client_id, tokens["refresh_token"])
    assert refused.status_code == 400 and refused.json()["error"] == "invalid_grant"


def test_a_code_given_before_a_password_change_gets_no_token(ready: TestClient) -> None:
    client_id = register(ready)
    verifier, challenge = pkce()
    code = code_of(agree(ready, client_id, challenge))
    with db_session() as db:
        user = db.scalar(select(User).where(User.username == "admin"))
        user.password_changed_ms = int((utcnow() + timedelta(seconds=1)).timestamp() * 1000)
    assert trade(ready, client_id, code, verifier).json()["error"] == "invalid_grant"


def test_a_disabled_account_refreshes_nothing(ready: TestClient) -> None:
    kim = create_user(ready, "kim")
    login(ready, "kim", "another-long-password")
    client_id, tokens = connect(ready)
    with db_session() as db:
        db.get(User, kim["id"]).disabled = True
    assert renew(ready, client_id, tokens["refresh_token"]).json()["error"] == "invalid_grant"
    with db_session() as db:
        db.get(User, kim["id"]).disabled = False
    # Ended, not paused: the chain does not come back with the account.
    assert renew(ready, client_id, tokens["refresh_token"]).json()["error"] == "invalid_grant"


def test_an_account_that_owes_a_second_factor_waits(ready: TestClient) -> None:
    client_id, tokens = connect(ready)
    with db_session() as db:
        two_factor.set_required(db, True)
    assert renew(ready, client_id, tokens["refresh_token"]).json()["error"] == "invalid_grant"
    with db_session() as db:
        two_factor.set_required(db, False)
    assert renew(ready, client_id, tokens["refresh_token"]).status_code == 200


def test_switching_connectors_off_ends_them(ready: TestClient) -> None:
    client_id, tokens = connect(ready)
    _key, by_hand = make_key(ready)
    claude = program(ready)
    switch(ready, oauth_allowed=False)
    assert rpc(claude, tokens["access_token"], "ping").status_code == 401
    assert rpc(claude, by_hand, "ping").status_code == 200, "a key made by hand stays"
    assert claude.get("/.well-known/oauth-authorization-server").status_code == 404
    assert claude.get("/.well-known/oauth-protected-resource").status_code == 404
    assert renew(claude, client_id, tokens["refresh_token"]).status_code == 404
    assert claude.post("/api/mcp/oauth/register", json={"redirect_uris": [BACK]}).status_code == 404
    assert ready.get("/api/v1/mcp/consent", params=request_of(client_id, "x" * 43)).json()["detail"]["code"] == "oauth_off"
    # On again, the connector does not come back: its account signs it in again.
    switch(ready, oauth_allowed=True)
    assert rpc(claude, tokens["access_token"], "ping").status_code == 401
    assert renew(claude, client_id, tokens["refresh_token"]).json()["error"] == "invalid_grant"


def test_switching_mcp_off_ends_the_connectors_too(ready: TestClient) -> None:
    client_id, tokens = connect(ready)
    switch(ready, allowed=False, oauth_allowed=True)
    claude = program(ready)
    assert rpc(claude, tokens["access_token"], "ping").status_code == 404
    assert claude.get("/api/mcp/oauth/authorize", follow_redirects=False).status_code == 404
    switch(ready, oauth_allowed=True)
    assert rpc(claude, tokens["access_token"], "ping").status_code == 401
    assert renew(claude, client_id, tokens["refresh_token"]).json()["error"] == "invalid_grant"


# -- registering ----------------------------------------------------------------------------------


def test_registering_is_braked_per_sender(ready: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mcp_oauth, "REGISTER_PER_SENDER", 3)
    for _ in range(3):
        register(ready)
    refused = ready.post("/api/mcp/oauth/register", json={"redirect_uris": [BACK]})
    assert refused.status_code == 429 and refused.json()["error"] == "temporarily_unavailable"
    # Another sender still may, and the hour passes.
    assert mcp_oauth.may_register("192.0.2.7")
    assert mcp_oauth.may_register("testclient", now=10**9)


def test_registering_is_braked_for_the_whole_server(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mcp_oauth, "REGISTER_PER_MINUTE", 4)
    assert all(mcp_oauth.may_register(f"192.0.2.{number}", now=100.0) for number in range(4))
    assert not mcp_oauth.may_register("192.0.2.99", now=100.0)
    assert mcp_oauth.may_register("192.0.2.99", now=161.0)


# -- the consent page -----------------------------------------------------------------------------


def test_the_consent_page_needs_a_signed_in_member(ready: TestClient) -> None:
    client_id = register(ready)
    _verifier, challenge = pkce()
    stranger = program(ready)
    assert stranger.get("/api/v1/mcp/consent", params=request_of(client_id, challenge)).status_code == 401
    assert stranger.post("/api/v1/mcp/consent", json={**request_of(client_id, challenge), "allow": True}, headers=CSRF).status_code == 401
    # Not with an API token either: it would mint access that outlives what made it.
    full = ready.post("/api/v1/tokens", json={"name": "script", "scope": "full"}, headers=CSRF).json()["token"]
    refused = stranger.get("/api/v1/mcp/consent", params=request_of(client_id, challenge), headers={"Authorization": f"Bearer {full}"})
    assert refused.status_code == 403 and refused.json()["detail"]["code"] == "session_required"
    # And the cookie needs the app's own header, like every change.
    assert ready.post("/api/v1/mcp/consent", json={**request_of(client_id, challenge), "allow": True}).status_code == 403
    create_user(ready, "gus", role="guest")
    login(ready, "gus", "another-long-password")
    assert ready.get("/api/v1/mcp/consent", params=request_of(client_id, challenge)).status_code == 403
    assert agree(ready, client_id, challenge).status_code == 403


def test_declining_sends_the_program_away_with_nothing(ready: TestClient) -> None:
    client_id = register(ready)
    _verifier, challenge = pkce()
    answer = agree(ready, client_id, challenge, allow=False)
    assert answer.status_code == 200
    query = parse_qs(urlsplit(answer.json()["redirect"]).query)
    assert query["error"] == ["access_denied"] and query["state"] == ["xyz"] and "code" not in query
    with db_session() as db:
        assert db.scalar(select(McpOAuthCode)) is None


def test_a_level_above_the_ceiling_is_refused(ready: TestClient) -> None:
    switch(ready, max_level="read", oauth_allowed=True)
    client_id = register(ready)
    _verifier, challenge = pkce()
    assert ready.get("/api/v1/mcp/consent", params=request_of(client_id, challenge)).json()["max_level"] == "read"
    refused = agree(ready, client_id, challenge, level="act")
    assert refused.status_code == 403 and refused.json()["detail"]["code"] == "level_not_allowed"
    assert agree(ready, client_id, challenge, level="act-more").status_code == 422
    assert agree(ready, client_id, challenge, level="read").status_code == 200


def test_a_board_of_another_account_is_refused(ready: TestClient) -> None:
    private = board(ready, "Admin only")
    create_user(ready, "kim")
    login(ready, "kim", "another-long-password")
    mine = board(ready, "Kim's")
    client_id = register(ready)
    _verifier, challenge = pkce()
    shown = ready.get("/api/v1/mcp/consent", params=request_of(client_id, challenge)).json()["boards"]
    assert [entry["id"] for entry in shown] == [mine["id"]]
    refused = agree(ready, client_id, challenge, boards=[mine["id"], private["id"]])
    assert refused.status_code == 422 and refused.json()["detail"]["code"] == "unknown_board"
    assert agree(ready, client_id, challenge, boards=[]).status_code == 422
    assert agree(ready, client_id, challenge, boards=[mine["id"]]).status_code == 200


def test_a_connector_counts_against_the_twenty_keys(ready: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import mcp

    monkeypatch.setattr(mcp, "MAX_KEYS", 2)
    client_id, tokens = connect(ready)
    make_key(ready)
    with db_session() as db:
        # The access token has run out; the connector still counts while it can refresh.
        db.scalar(select(McpKey).where(McpKey.kind == "oauth")).expires_at = utcnow() - timedelta(seconds=1)
    assert ready.post("/api/v1/mcp/keys", json={"name": "third", "level": "read"}, headers=CSRF).status_code == 409
    other = register(ready, name="Other")
    _verifier, challenge = pkce()
    refused = agree(ready, other, challenge)
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "too_many_keys"
    # The same program signing in again replaces its own connector, so it may.
    _verifier, challenge = pkce()
    assert agree(ready, client_id, challenge).status_code == 200


# -- logs -----------------------------------------------------------------------------------------


def test_the_log_never_shows_what_a_connector_holds() -> None:
    for prefix in ("ndo", "ndr", "ndc"):
        token = f"{prefix}_" + "A1b2C3d4" * 5
        assert journal.redact(f"body {token} and Bearer {token}") == f"body {prefix}_*** and Bearer {prefix}_***"
        record = logging.LogRecord("nexdeck.mcp", logging.INFO, __file__, 1, "Pasted %s by mistake", (token,), None)
        journal._Context().filter(record)
        assert token not in record.getMessage()
    assert journal.redact("nd_plain stays") == "nd_plain stays"
