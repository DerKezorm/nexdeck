"""A custom card reads through the kinds that came with release 0.51.0 the way the kind signs (JEDE-2, after the merge of ``main``).

``test_cards_every_kind.py`` answers ``{}`` to everything, so a kind that signs in first or asks who it talks to first is
listed there and played here with a stub that behaves. Also here: what a card may and may not ask of the kinds whose GET
can act, and the kinds a card cannot use at all.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import NOT_READ_BY_CARDS, AdapterError, Context
from app.adapters.rawread import refuse_a_command

BASE = "http://svc.example.com:8080"
PASSWORD = "Zk-password-1"
CARD_READS = Path(__file__).resolve().parent.parent / "app" / "cards" / "card_reads.json"


def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


# -- Keycloak: a token from a POST with the client's credentials ------------------------------------


class Keycloak:
    def __init__(self) -> None:
        self.tokens = 0
        self.valid: str | None = None

    def token(self, request: httpx.Request) -> httpx.Response:
        assert b"Zk-secret-1" in request.content
        self.tokens += 1
        self.valid = f"tok-{self.tokens}"
        return httpx.Response(200, json={"access_token": self.valid, "expires_in": 300})

    def read(self, request: httpx.Request) -> httpx.Response:
        if request.headers.get("authorization") != f"Bearer {self.valid}":
            return httpx.Response(401)
        return httpx.Response(200, json=[{"realm": "master"}])


@respx.mock
async def test_nach_merge_051_keycloak_a_card_uses_the_token_of_the_client_and_asks_for_a_new_one_when_it_was_turned_down() -> None:
    service = Keycloak()
    respx.post(f"{BASE}/realms/master/protocol/openid-connect/token").mock(side_effect=service.token)
    respx.get(url__regex=rf"{BASE}/admin/.*").mock(side_effect=service.read)
    adapter, config, held = get_adapter("keycloak"), {"url": BASE, "realm": "master", "client_id": "nexdeck", "client_secret": "Zk-secret-1"}, ctx()
    first = await adapter.raw_request("GET", "/admin/realms/master/users/count", config, held)
    assert first.status_code == 200 and service.tokens == 1
    service.valid = "revoked-by-the-server"
    again = await adapter.raw_request("GET", "/admin/realms/master/clients", config, held)
    assert again.status_code == 200 and service.tokens == 2, "a refusal makes the kind sign in again, once"


# -- Lemmy: a session from a POST ---------------------------------------------------------------------


@respx.mock
async def test_nach_merge_051_lemmy_a_card_carries_the_session_of_the_account() -> None:
    logins = respx.post(f"{BASE}/api/v3/user/login").mock(return_value=httpx.Response(200, json={"jwt": "jwt-1"}))
    respx.get(f"{BASE}/api/v3/site").mock(return_value=httpx.Response(200, json={"site_view": {}, "version": "0.19.5"}))
    seen = respx.get(f"{BASE}/api/v3/user/unread_count").mock(
        side_effect=lambda request: httpx.Response(200, json={"replies": 0}) if request.headers.get("authorization") == "Bearer jwt-1" else httpx.Response(401, json={"error": "not_logged_in"})
    )
    adapter, config, held = get_adapter("lemmy"), {"url": BASE, "username": "ann", "password": PASSWORD}, ctx()
    answer = await adapter.raw_request("GET", "/api/v3/user/unread_count", config, held)
    assert answer.status_code == 200 and seen.called and logins.call_count == 1


# -- Wazuh: a token from a POST with the account (Basic) --------------------------------------------------


class Wazuh:
    def __init__(self) -> None:
        self.logins = 0
        self.valid: str | None = None

    def authenticate(self, request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Basic " + base64.b64encode(f"wui:{PASSWORD}".encode()).decode()
        self.logins += 1
        self.valid = f"jwt-{self.logins}"
        return httpx.Response(200, text=self.valid)

    def read(self, request: httpx.Request) -> httpx.Response:
        if request.headers.get("authorization") != f"Bearer {self.valid}":
            return httpx.Response(401)
        return httpx.Response(200, json={"data": {"affected_items": [], "api_version": "4.9.0", "connection": {"total": 3}}})


@respx.mock
async def test_nach_merge_051_wazuh_a_card_carries_the_token_and_the_kind_signs_in_again_when_it_ran_out() -> None:
    service = Wazuh()
    respx.post(f"{BASE}/security/user/authenticate").mock(side_effect=service.authenticate)
    respx.get(url__regex=rf"{BASE}/(?!security).*").mock(side_effect=service.read)
    adapter, config, held = get_adapter("wazuh"), {"url": BASE, "username": "wui", "password": PASSWORD}, ctx()
    first = await adapter.raw_request("GET", "/agents/summary/status", config, held)
    assert first.status_code == 200 and service.logins == 1
    service.valid = "revoked-by-the-server"
    again = await adapter.raw_request("GET", "/manager/status", config, held)
    assert again.status_code == 200 and service.logins == 2, "a refusal makes the kind sign in again, once"


# -- Mastodon: the access token, without asking the public instance first -------------------------------------


@respx.mock
async def test_nach_merge_051_mastodon_a_card_carries_the_access_token_and_nothing_else_is_asked() -> None:
    route = respx.get(url__regex=rf"{BASE}/.*").mock(return_value=httpx.Response(200, json={"ok": True}))
    adapter, config = get_adapter("mastodon"), {"url": BASE, "token": "Zk-token-1"}
    await adapter.raw_request("GET", "/api/v1/accounts/verify_credentials", config, ctx())
    assert route.call_count == 1 and route.calls.last.request.headers["authorization"] == "Bearer Zk-token-1"
    # without a token the card is asked as nobody
    respx.reset()
    open_route = respx.get(url__regex=rf"{BASE}/.*").mock(return_value=httpx.Response(200, json={"ok": True}))
    await adapter.raw_request("GET", "/api/v1/instance", {"url": BASE}, ctx())
    assert "authorization" not in open_route.calls.last.request.headers


# -- Registry: Basic to the registry's own address --------------------------------------------------------------


@respx.mock
async def test_nach_merge_051_registry_a_card_signs_with_the_user_and_password_of_the_connection_to_the_registry_only() -> None:
    route = respx.get(url__regex=rf"{BASE}/v2/.*").mock(return_value=httpx.Response(200, json={"repositories": ["app"]}))
    adapter, config = get_adapter("registry"), {"url": BASE, "user": "robot", "password": PASSWORD}
    answer = await adapter.raw_request("GET", "/v2/_catalog?n=10", config, ctx())
    assert answer.status_code == 200
    sent = route.calls.last.request
    assert sent.headers["authorization"] == "Basic " + base64.b64encode(f"robot:{PASSWORD}".encode()).decode()
    assert sent.url.host == "svc.example.com"
    # a registry without an account is asked as nobody
    route.reset()
    await adapter.raw_request("GET", "/v2/_catalog?n=11", {"url": BASE}, ctx())
    assert "authorization" not in route.calls.last.request.headers


# -- InfluxDB: the scheme of the token depends on the version ---------------------------------------------------------


@pytest.mark.parametrize(("version", "scheme"), [("2", "Token"), ("3", "Bearer")])
@respx.mock
async def test_nach_merge_051_influxdb_a_card_signs_with_the_scheme_of_the_version_it_finds(version: str, scheme: str) -> None:
    if version == "3":
        respx.get(f"{BASE}/ping").mock(return_value=httpx.Response(200, json={"product_name": "InfluxDB 3 Core", "version": "3.1.0"}))
    else:
        respx.get(f"{BASE}/ping").mock(return_value=httpx.Response(204, headers={"X-Influxdb-Version": "v2.7.1"}))
    read = respx.get(f"{BASE}/api/v2/buckets").mock(return_value=httpx.Response(200, json={"buckets": []}))
    await get_adapter("influxdb").raw_request("GET", "/api/v2/buckets", {"url": BASE, "token": "Zk-token-1"}, ctx())
    assert read.calls.last.request.headers["authorization"] == f"{scheme} Zk-token-1"


# -- Steam: one address of its own, the key in the query ------------------------------------------------------------------


@respx.mock
async def test_nach_merge_051_steam_a_card_asks_the_web_api_with_the_key_and_the_key_goes_nowhere_else() -> None:
    route = respx.get(url__regex=r"https://api\.steampowered\.com/.*").mock(return_value=httpx.Response(200, json={"response": {}}))
    adapter, config = get_adapter("steam"), {"api_key": "Zk-key-1", "steam_id": "76561198000000000"}
    answer = await adapter.raw_request("GET", "/ISteamUser/GetPlayerSummaries/v2/?steamids=76561198000000000", config, ctx())
    assert answer.status_code == 200
    sent = route.calls.last.request
    assert sent.url.host == "api.steampowered.com" and sent.url.params["key"] == "Zk-key-1" and sent.url.params["steamids"] == "76561198000000000"


# -- the kinds a card cannot read -------------------------------------------------------------------------------------------


async def test_nach_merge_051_nut_speaks_no_http_so_a_card_cannot_read_through_it() -> None:
    assert "nut" in NOT_READ_BY_CARDS and not get_adapter("nut").raw_access
    with pytest.raises(AdapterError) as refused:
        await get_adapter("nut").raw_request("GET", "/x", {"host": "svc.example.com"}, ctx())
    assert refused.value.code == "no_raw_access"
    assert "nut" not in json.loads(CARD_READS.read_text(encoding="utf-8"))


# -- the GET that acts ---------------------------------------------------------------------------------------------------------


@respx.mock
async def test_nach_merge_051_a_request_that_starts_a_build_or_runs_an_event_never_leaves_the_server() -> None:
    anything = respx.route().mock(return_value=httpx.Response(200, json={}))
    jenkins = {"url": BASE, "username": "ann", "token": "Zk-token-1"}
    for kind, config, path in (
        ("jenkins", jenkins, "/job/api-tests/build"),
        ("jenkins", jenkins, "/job/api-tests/buildWithParameters?x=1"),
        ("cronicle", {"url": BASE, "api_key": "Zk-key-1"}, "/api/app/run_event/v1?id=e1"),
        ("mailcow", {"url": BASE, "api_key": "Zk-key-1"}, "/api/v1/edit/mailq"),
    ):
        with pytest.raises(AdapterError) as refused:
            await get_adapter(kind).raw_request("GET", path, config, ctx())
        assert refused.value.code == "command_refused", (kind, path)
    assert not anything.called, "nothing was sent, not even a sign-in"


def test_nach_merge_051_every_new_kind_that_a_card_can_read_either_has_reads_or_stands_in_the_gaps_with_its_reason() -> None:
    reads = json.loads(CARD_READS.read_text(encoding="utf-8"))
    for kind in ("amp", "uptimerobot", "wikijs", "warrior"):
        assert kind not in reads, kind
    for kind in ("anchor", "caddy", "jenkins", "keycloak", "mastodon", "steam", "stalwart", "cronicle", "mailcow"):
        assert reads.get(kind), kind
        for one in reads[kind]:
            refuse_a_command(get_adapter(kind), one["path"])
