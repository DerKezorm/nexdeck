"""A custom card signs in to the kinds that came with release 0.50.0 the way the kind does (JEDE-2, after the merge of ``main``).

The test over every kind (``test_cards_every_kind.py``) answers ``{}`` to everything and so cannot play a service that signs
in properly or asks who it talks to first. These kinds are listed there and played here, each with a stub that behaves.
"""

from __future__ import annotations

import base64
import time

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context

BASE = "http://svc.example.com:8080"
PASSWORD = "Zk-password-1"


def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


# -- slskd: a token from a POST, or an API key ------------------------------------------------


class Slskd:
    def __init__(self) -> None:
        self.logins = 0
        self.valid: str | None = None
        self.asked: list[httpx.Request] = []

    def login(self, request: httpx.Request) -> httpx.Response:
        assert PASSWORD.encode() in request.content
        self.logins += 1
        self.valid = f"tok-{self.logins}"
        return httpx.Response(200, json={"token": self.valid, "expires": time.time() + 3600})

    def read(self, request: httpx.Request) -> httpx.Response:
        self.asked.append(request)
        if request.headers.get("authorization") != f"Bearer {self.valid}":
            return httpx.Response(401)
        return httpx.Response(200, json={"version": {"current": "0.26.2"}})


@respx.mock
async def test_nach_merge_slskd_a_card_uses_the_token_of_the_sign_in_and_signs_in_again_when_it_was_turned_down() -> None:
    service = Slskd()
    respx.post(f"{BASE}/api/v0/session").mock(side_effect=service.login)
    respx.get(url__regex=rf"{BASE}/api/v0/.*").mock(side_effect=service.read)
    adapter, config, held = get_adapter("slskd"), {"url": BASE, "username": "ZkUser", "password": PASSWORD}, ctx()
    answer = await adapter.raw_request("GET", "/api/v0/application", config, held)
    assert answer.status_code == 200 and service.logins == 1
    sent = service.asked[-1]
    assert sent.headers["authorization"] == "Bearer tok-1" and PASSWORD not in str(sent.url) + str(sent.headers)
    await adapter.raw_request("GET", "/api/v0/transfers/downloads", config, held)
    assert service.logins == 1, "the token is kept, not asked for again with every card"
    service.valid = None  # revoked at the service
    answer = await adapter.raw_request("GET", "/api/v0/application", config, held)
    assert answer.status_code == 200 and service.logins == 2
    assert service.asked[-1].headers["authorization"] == "Bearer tok-2"


@respx.mock
async def test_nach_merge_slskd_a_path_the_service_keeps_turning_down_is_asked_once_more_and_then_the_card_fails() -> None:
    service = Slskd()
    respx.post(f"{BASE}/api/v0/session").mock(side_effect=service.login)
    respx.get(url__regex=rf"{BASE}/api/v0/.*").mock(return_value=httpx.Response(401))
    adapter, config = get_adapter("slskd"), {"url": BASE, "username": "ZkUser", "password": PASSWORD}
    with pytest.raises(AuthFailed):
        await adapter.raw_request("GET", "/api/v0/nothing", config, ctx())
    assert service.logins == 2, "one sign-in for the first ask and one renewal, never a third"


@respx.mock
async def test_nach_merge_slskd_an_api_key_travels_in_its_header_and_is_never_renewed() -> None:
    signed_in = respx.post(f"{BASE}/api/v0/session").mock(return_value=httpx.Response(200, json={}))
    read = respx.get(url__regex=rf"{BASE}/api/v0/.*").mock(return_value=httpx.Response(401))
    adapter, config = get_adapter("slskd"), {"url": BASE, "api_key": "ZkKey-1"}
    with pytest.raises(AuthFailed):
        await adapter.raw_request("GET", "/api/v0/application", config, ctx())
    assert read.calls.last.request.headers["x-api-key"] == "ZkKey-1" and not signed_in.called


# -- Shelly: asks the device for its generation first, then Basic (Gen1) or Digest (Gen2) ----------------------


def _shelly(identity: dict[str, object], scheme: str, challenge: str | None = None):  # noqa: ANN202
    """A device that tells its generation without a sign-in and wants ``scheme`` for everything else."""
    asked: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        asked.append(request)
        if request.url.path == "/shelly":
            return httpx.Response(200, json=identity)
        if not request.headers.get("authorization", "").startswith(scheme):
            return httpx.Response(401, headers={"www-authenticate": challenge} if challenge else {})
        return httpx.Response(200, json={"ok": True})

    return asked, answer


@respx.mock
async def test_nach_merge_shelly_a_gen1_device_gets_the_basic_login_of_the_connection() -> None:
    asked, answer = _shelly({"type": "SHSW-1", "fw": "20230913-112003/v1.14.0"}, "Basic ")
    respx.get(url__regex=rf"{BASE}/.*").mock(side_effect=answer)
    adapter, config = get_adapter("shelly"), {"url": BASE, "username": "ZkUser", "password": PASSWORD}
    response = await adapter.raw_request("GET", "/status", config, ctx())
    assert response.status_code == 200
    login = base64.b64decode(asked[-1].headers["authorization"][6:]).decode()
    assert login == f"ZkUser:{PASSWORD}" and PASSWORD not in str(asked[-1].url)


@respx.mock
async def test_nach_merge_shelly_a_gen2_device_gets_the_digest_login_of_admin() -> None:
    challenge = 'Digest qop="auth", realm="shellyplus1-aabbcc", nonce="1700000000", algorithm=SHA-256'
    asked, answer = _shelly({"gen": 2, "id": "shellyplus1-aabbcc", "ver": "1.4.4"}, "Digest ", challenge)
    respx.get(url__regex=rf"{BASE}/.*").mock(side_effect=answer)
    adapter, config = get_adapter("shelly"), {"url": BASE, "username": "ZkUser", "password": PASSWORD}
    response = await adapter.raw_request("GET", "/rpc/Shelly.GetStatus", config, ctx())
    assert response.status_code == 200
    login = asked[-1].headers["authorization"]
    assert 'username="admin"' in login and "SHA-256" in login and PASSWORD not in login + str(asked[-1].url)


@respx.mock
async def test_nach_merge_shelly_a_device_without_a_password_is_asked_without_a_login() -> None:
    asked, answer = _shelly({"gen": 3, "id": "shelly1pmg3-aabbcc"}, "")
    respx.get(url__regex=rf"{BASE}/.*").mock(side_effect=answer)
    response = await get_adapter("shelly").raw_request("GET", "/rpc/Shelly.GetStatus", {"url": BASE}, ctx())
    assert response.status_code == 200 and "authorization" not in asked[-1].headers


@respx.mock
async def test_nach_merge_shelly_a_command_that_switches_never_leaves_the_server() -> None:
    asked, answer = _shelly({"type": "SHSW-1", "fw": "x"}, "")
    respx.get(url__regex=rf"{BASE}/.*").mock(side_effect=answer)
    with pytest.raises(AdapterError) as refused:
        await get_adapter("shelly").raw_request("GET", "/relay/0?turn=on", {"url": BASE}, ctx())
    assert refused.value.code == "command_refused" and not asked
