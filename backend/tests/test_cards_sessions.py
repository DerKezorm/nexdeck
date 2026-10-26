"""A custom card signs in the way the kind does, and renews the session the way the kind does (JEDE-2, patterns).

One test per pattern, not per service. The stub plays the service properly: it signs in, hands out a session, accepts it,
and lets it run out when the test says so. The card must (1) use the session the kind's own cards hold instead of
signing in a second time, (2) send it the way the kind sends it, (3) sign in again when it ran out, and (4) never send
the password along with a request that only asks.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AuthFailed, Context

BASE = "http://svc.example.com:8080"
PASSWORD = "Zk-password-1"


def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


class Service:
    """A service with one valid session at a time."""

    def __init__(self) -> None:
        self.logins = 0
        self.valid: str | None = None
        self.asked: list[httpx.Request] = []


# -- header from a POST: Pi-hole -------------------------------------------------------


class PiHole(Service):
    def login(self, request: httpx.Request) -> httpx.Response:
        assert b"Zk-password-1" in request.content
        self.logins += 1
        self.valid = f"sid-{self.logins}"
        return httpx.Response(200, json={"session": {"valid": True, "sid": self.valid}})

    def read(self, request: httpx.Request) -> httpx.Response:
        self.asked.append(request)
        if request.headers.get("sid") != self.valid:
            return httpx.Response(401, json={})
        return httpx.Response(200, json={"version": {"core": {"local": {"version": "6.0"}}}})


@respx.mock
async def test_jede3_a_session_in_a_header_is_the_one_the_kinds_own_cards_hold_and_is_renewed_when_it_ran_out() -> None:
    service = PiHole()
    respx.post(f"{BASE}/api/auth").mock(side_effect=service.login)
    respx.get(url__regex=rf"{BASE}/api/.*").mock(side_effect=service.read)
    adapter, config, held = get_adapter("pihole"), {"url": BASE, "password": PASSWORD}, ctx()
    # The kind's own card signs in first, as the board does.
    await adapter.test(config, held)
    assert service.logins == 1
    # The custom card uses that very session: no second sign-in, the header of the kind, no password on the way.
    answer = await adapter.raw_request("GET", "/api/info/version", config, held)
    assert answer.status_code == 200 and service.logins == 1
    sent = service.asked[-1]
    assert sent.headers["sid"] == "sid-1" and PASSWORD not in str(sent.url) + str(sent.headers)
    await adapter.raw_request("GET", "/api/stats/summary", config, held)
    assert service.logins == 1
    # The session runs out at the service: the card signs in again, once, by the kind's own sign-in.
    service.valid = None
    answer = await adapter.raw_request("GET", "/api/stats/again", config, held)
    assert answer.status_code == 200 and service.logins == 2
    assert service.asked[-1].headers["sid"] == "sid-2"


@respx.mock
async def test_jede3_a_card_that_comes_first_signs_in_once_and_the_kinds_card_after_it_uses_that_session() -> None:
    service = PiHole()
    respx.post(f"{BASE}/api/auth").mock(side_effect=service.login)
    respx.get(url__regex=rf"{BASE}/api/.*").mock(side_effect=service.read)
    adapter, config, held = get_adapter("pihole"), {"url": BASE, "password": PASSWORD}, ctx()
    await adapter.raw_request("GET", "/api/info/version", config, held)
    assert service.logins == 1
    await adapter.test(config, held)
    assert service.logins == 1, "the built-in card did not sign in a second time"


@respx.mock
async def test_jede3_a_refusal_that_stays_after_signing_in_again_is_an_auth_failure_and_no_loop() -> None:
    service = PiHole()
    respx.post(f"{BASE}/api/auth").mock(side_effect=service.login)
    respx.get(url__regex=rf"{BASE}/api/.*").mock(return_value=httpx.Response(401, json={}))
    adapter, config, held = get_adapter("pihole"), {"url": BASE, "password": PASSWORD}, ctx()
    with pytest.raises(AuthFailed):
        await adapter.raw_request("GET", "/api/info/version", config, held)
    assert service.logins == 2, "signed in once for the card and once more after the refusal, then it gave up"


# -- session id in the address, a 200 that says it ran out: Synology -------------------------


class Synology(Service):
    def post(self, request: httpx.Request) -> httpx.Response:
        assert b"passwd=Zk-password-1" in request.content
        self.logins += 1
        self.valid = f"dsm-{self.logins}"
        return httpx.Response(200, json={"success": True, "data": {"sid": self.valid}})

    def get(self, request: httpx.Request) -> httpx.Response:
        self.asked.append(request)
        if request.url.params.get("_sid") != self.valid:
            return httpx.Response(200, json={"success": False, "error": {"code": 119}})
        return httpx.Response(200, json={"success": True, "data": {"model": "DS", "firmware_ver": "7"}})


@respx.mock
async def test_jede3_a_session_id_in_the_address_comes_along_and_a_200_with_the_expiry_code_renews_it() -> None:
    service = Synology()
    respx.post(f"{BASE}/webapi/auth.cgi").mock(side_effect=service.post)
    respx.get(f"{BASE}/webapi/entry.cgi").mock(side_effect=service.get)
    adapter, config, held = get_adapter("synology"), {"url": BASE, "username": "admin", "password": PASSWORD}, ctx()
    answer = await adapter.raw_request("GET", "/webapi/entry.cgi?api=SYNO.Core.System&method=info&version=1", config, held)
    assert answer.json()["success"] is True and service.logins == 1
    sent = service.asked[-1]
    assert sent.url.params["_sid"] == "dsm-1" and sent.url.params["api"] == "SYNO.Core.System", "the card's own question is kept"
    assert "passwd" not in str(sent.url)
    service.valid = None  # the service restarted: dsm-1 is gone
    answer = await adapter.raw_request("GET", "/webapi/entry.cgi?api=SYNO.Core.System&method=info&version=1&x=1", config, held)
    assert answer.json()["success"] is True and service.logins == 2


# -- the cookie of a client of the kind's own: qBittorrent -----------------------------------


class QBittorrent(Service):
    def login(self, request: httpx.Request) -> httpx.Response:
        assert b"password=Zk-password-1" in request.content
        self.logins += 1
        self.valid = f"SID=cookie-{self.logins}"
        return httpx.Response(200, text="Ok.", headers={"set-cookie": f"{self.valid}; Path=/"})

    def read(self, request: httpx.Request) -> httpx.Response:
        self.asked.append(request)
        if self.valid is None or request.headers.get("cookie") != self.valid:
            return httpx.Response(403, text="Forbidden")
        # The kind's own connection test asks these two, and understands only these shapes.
        return httpx.Response(200, json=[] if request.url.path.endswith("/torrents/info") else {"version": "5"})


@respx.mock
async def test_jede3_the_cookie_of_the_kinds_own_client_is_used_and_a_403_signs_in_again() -> None:
    service = QBittorrent()
    respx.post(f"{BASE}/api/v2/auth/login").mock(side_effect=service.login)
    respx.get(url__regex=rf"{BASE}/api/v2/.*").mock(side_effect=service.read)
    adapter, config, held = get_adapter("qbittorrent"), {"url": BASE, "username": "admin", "password": PASSWORD}, ctx()
    answer = await adapter.raw_request("GET", "/api/v2/app/version", config, held)
    assert answer.status_code == 200 and service.logins == 1
    await adapter.raw_request("GET", "/api/v2/transfer/info", config, held)
    assert service.logins == 1, "the session is kept"
    service.valid = None  # the service forgot the cookie
    answer = await adapter.raw_request("GET", "/api/v2/sync/maindata", config, held)
    assert answer.status_code == 200 and service.logins == 2
    assert all(PASSWORD not in str(one.url) for one in service.asked)


@respx.mock
async def test_jede3_a_refusal_that_stays_after_signing_in_again_is_an_auth_failure_and_not_a_loop() -> None:
    service = QBittorrent()
    respx.post(f"{BASE}/api/v2/auth/login").mock(side_effect=service.login)
    respx.get(url__regex=rf"{BASE}/api/v2/.*").mock(return_value=httpx.Response(403, text="Forbidden"))
    adapter, config, held = get_adapter("qbittorrent"), {"url": BASE, "username": "admin", "password": PASSWORD}, ctx()
    answer = await adapter.raw_request("GET", "/api/v2/app/version", config, held)
    assert answer.status_code == 403 and service.logins == 1


# -- a token from a sign-in on another host: Twitch ---------------------------------------


@respx.mock
async def test_jede3_a_token_from_another_host_goes_only_to_the_kinds_api_host() -> None:
    token = respx.post("https://id.twitch.tv/oauth2/token").mock(return_value=httpx.Response(200, json={"access_token": "tok-1", "expires_in": 3600}))
    api = respx.get(url__regex=r"https://api\.twitch\.tv/helix/.*").mock(return_value=httpx.Response(200, json={"data": []}))
    adapter, config, held = get_adapter("twitch"), {"client_id": "Zk-id", "client_secret": "Zk-secret"}, ctx()
    answer = await adapter.raw_request("GET", "/streams", config, held)
    assert answer.status_code == 200
    sent = api.calls.last.request
    assert sent.url.host == "api.twitch.tv" and sent.headers["authorization"].endswith("tok-1")
    assert token.called and all("Zk-secret" not in str(call.request.url) for call in api.calls)
