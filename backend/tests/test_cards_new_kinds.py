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


# -- Jackett: the cookie of the web interface, in a client of its own; a request without it is sent to the login page ----


class Jackett:
    def __init__(self, password: str = PASSWORD) -> None:
        self.password = password
        self.logins = 0
        self.session: str | None = None
        self.asked: list[httpx.Request] = []

    def sign_in(self, request: httpx.Request) -> httpx.Response:
        self.logins += 1
        if f"password={self.password}".encode() not in request.content:
            return httpx.Response(302, headers={"location": "Dashboard"})  # the same answer, without the cookie
        self.session = f"cookie-{self.logins}"
        return httpx.Response(302, headers={"location": "Dashboard", "set-cookie": f"Jackett={self.session}; Path=/"})

    def read(self, request: httpx.Request) -> httpx.Response:
        self.asked.append(request)
        if self.session is None or f"Jackett={self.session}" not in request.headers.get("cookie", ""):
            return httpx.Response(302, headers={"location": "/UI/Login?ReturnUrl=%2Fapi"})
        return httpx.Response(200, json={"app_version": "v0.24.2934"} if request.url.path.endswith("config") else [])


@respx.mock
async def test_nach_merge_jackett_a_card_signs_in_to_the_web_interface_and_keeps_its_cookie_when_it_ran_out() -> None:
    service = Jackett()
    respx.post(f"{BASE}/UI/Dashboard").mock(side_effect=service.sign_in)
    respx.get(url__regex=rf"{BASE}/(api|UI/Dashboard).*").mock(side_effect=service.read)
    adapter, config, held = get_adapter("jackett"), {"url": BASE, "password": PASSWORD}, ctx()
    answer = await adapter.raw_request("GET", "/api/v2.0/indexers?configured=true", config, held)
    assert answer.status_code == 200 and service.logins == 1
    sent = service.asked[-1]
    assert "Jackett=cookie-1" in sent.headers["cookie"] and PASSWORD not in str(sent.url) + str(sent.headers)
    await adapter.raw_request("GET", "/api/v2.0/server/config", config, held)
    assert service.logins == 1, "the cookie is the session of the kind's own cards too"
    service.session = None  # the cookie ran out at the service
    answer = await adapter.raw_request("GET", "/api/v2.0/indexers?configured=true", config, held)
    assert answer.status_code == 200 and service.logins == 2


@respx.mock
async def test_nach_merge_jackett_a_wrong_password_is_told_to_the_card_and_not_tried_for_ever() -> None:
    service = Jackett(password="Zk-other")
    respx.post(f"{BASE}/UI/Dashboard").mock(side_effect=service.sign_in)
    respx.get(url__regex=rf"{BASE}/(api|UI/Dashboard).*").mock(side_effect=service.read)
    with pytest.raises(AuthFailed):
        await get_adapter("jackett").raw_request("GET", "/api/v2.0/indexers", {"url": BASE, "password": PASSWORD}, ctx())
    assert service.logins == 1


# -- Homebridge and Node-RED: a bearer token from a POST sign-in, found by watching the kind's own connection test -------


class Bearer:
    """A service that signs in with a POST, hands out a bearer token, and turns every other one down with 401."""

    def __init__(self) -> None:
        self.logins = 0
        self.valid: str | None = None
        self.asked: list[httpx.Request] = []

    def sign_in(self, request: httpx.Request) -> httpx.Response:
        assert PASSWORD.encode() in request.content
        self.logins += 1
        self.valid = f"tok-{self.logins}"
        return httpx.Response(200, json={"access_token": self.valid, "expires_in": 3600})

    def authorised(self, request: httpx.Request) -> bool:
        return request.headers.get("authorization") == f"Bearer {self.valid}"


class HomebridgeService(Bearer):
    def read(self, request: httpx.Request) -> httpx.Response:
        self.asked.append(request)
        if request.url.path == "/api/auth/settings":
            return httpx.Response(200, json={"env": {"packageVersion": "5.29.0", "homebridgeVersion": "2.4.0"}})
        if not self.authorised(request):
            return httpx.Response(401, json={"message": "Unauthorized"})
        return httpx.Response(200, json={"status": "ok"} if request.url.path.endswith("/status/homebridge") else [])


class NodeRedService(Bearer):
    def read(self, request: httpx.Request) -> httpx.Response:
        self.asked.append(request)
        if request.url.path == "/auth/login":
            return httpx.Response(200, json={"type": "credentials", "prompts": []})
        if not self.authorised(request):
            return httpx.Response(401, json={"message": "Unauthorized"})
        if request.url.path == "/settings":
            return httpx.Response(200, json={"version": "4.1.0"})
        return httpx.Response(200, json={"state": "start"} if request.url.path == "/flows/state" else [])


@respx.mock
async def test_nach_merge_homebridge_a_card_uses_the_token_of_the_kinds_own_sign_in_and_renews_it_when_it_was_turned_down() -> None:
    service = HomebridgeService()
    respx.post(f"{BASE}/api/auth/login").mock(side_effect=service.sign_in)
    respx.get(url__regex=rf"{BASE}/api/.*").mock(side_effect=service.read)
    adapter, config, held = get_adapter("homebridge"), {"url": BASE, "username": "ZkUser", "password": PASSWORD}, ctx()
    await adapter.test(config, held)  # the kind's own cards sign in first, as the board does
    assert service.logins == 1
    answer = await adapter.raw_request("GET", "/api/accessories", config, held)
    assert answer.status_code == 200 and service.logins == 1, "the card uses the token the kind's cards hold"
    sent = service.asked[-1]
    assert sent.headers["authorization"] == "Bearer tok-1" and PASSWORD not in str(sent.url) + str(sent.headers)
    service.valid = "tok-restarted"  # Homebridge restarted with a new secret: the token is a made-up one now
    answer = await adapter.raw_request("GET", "/api/accessories", config, held)
    assert answer.status_code == 200 and service.logins == 2
    assert service.asked[-1].headers["authorization"] == "Bearer tok-2"


@respx.mock
async def test_nach_merge_homebridge_a_card_that_comes_first_signs_in_once() -> None:
    service = HomebridgeService()
    respx.post(f"{BASE}/api/auth/login").mock(side_effect=service.sign_in)
    respx.get(url__regex=rf"{BASE}/api/.*").mock(side_effect=service.read)
    adapter, config, held = get_adapter("homebridge"), {"url": BASE, "username": "ZkUser", "password": PASSWORD}, ctx()
    answer = await adapter.raw_request("GET", "/api/plugins", config, held)
    assert answer.status_code == 200 and service.asked[-1].headers["authorization"] == "Bearer tok-1"
    await adapter.test(config, held)
    assert service.logins == 1


@respx.mock
async def test_nach_merge_nodered_a_card_uses_the_token_of_the_kinds_own_sign_in_and_renews_it_when_it_was_turned_down() -> None:
    service = NodeRedService()
    respx.post(f"{BASE}/auth/token").mock(side_effect=service.sign_in)
    respx.get(url__regex=rf"{BASE}/.*").mock(side_effect=service.read)
    adapter, config, held = get_adapter("nodered"), {"url": BASE, "username": "ZkUser", "password": PASSWORD}, ctx()
    await adapter.test(config, held)
    assert service.logins == 1
    answer = await adapter.raw_request("GET", "/flows", config, held)
    assert answer.status_code == 200 and service.logins == 1
    sent = service.asked[-1]
    assert sent.headers["authorization"] == "Bearer tok-1" and PASSWORD not in str(sent.url) + str(sent.headers)
    service.valid = "tok-restarted"
    answer = await adapter.raw_request("GET", "/flows", config, held)
    assert answer.status_code == 200 and service.logins == 2
    assert service.asked[-1].headers["authorization"] == "Bearer tok-2"


@respx.mock
async def test_nach_merge_nodered_without_a_sign_in_the_card_asks_without_a_token() -> None:
    asked: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        asked.append(request)
        return httpx.Response(200, json={} if request.url.path == "/auth/login" else {"version": "4.1.0", "state": "start"})

    respx.get(url__regex=rf"{BASE}/.*").mock(side_effect=answer)
    response = await get_adapter("nodered").raw_request("GET", "/flows", {"url": BASE}, ctx())
    assert response.status_code == 200 and "authorization" not in asked[-1].headers
