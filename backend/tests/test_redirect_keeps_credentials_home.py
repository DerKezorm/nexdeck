"""A redirect to another place takes none of a connection's credentials along.

⚠️ httpx drops ``Authorization`` on a redirect to another origin and nothing
else, and the clients every built-in card fetches through follow redirects. A
Radarr that answered 302 to another host handed that host its ``X-Api-Key``,
a Plex its ``X-Plex-Token``, a Jellyfin its ``X-Emby-Token``. Found in the
review of the custom cards, 25.10.2026.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest

from app.adapters import base as base_module
from app.adapters.base import AdapterError, Context, outbound_client
from app.routers import widgets as widgets_module
from app.services import collector as collector_module

#: What the connections of this codebase sign in with, one of each kind.
CREDENTIALS = {
    "X-Api-Key": "radarr-key",
    "X-Plex-Token": "plex-token",
    "X-Emby-Token": "emby-token",
    "Authorization": "Bearer the-token",
    "Cookie": "session=signed-in",
}
START = "http://radarr.lan:7878/api/v3/system/status"


def _redirecting(seen: list[httpx.Request], target: str, status: int = 302) -> httpx.MockTransport:
    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if len(seen) == 1:
            return httpx.Response(status, headers={"Location": target, "Set-Cookie": "session=from-the-service; Path=/"})
        return httpx.Response(200, json={"version": "5.0"})

    return httpx.MockTransport(handler)


def _carried(request: httpx.Request) -> set[str]:
    return {name for name in CREDENTIALS if name.lower() in request.headers}


async def _follow(target: str, *, method: str = "GET", status: int = 302, **client: object) -> list[httpx.Request]:
    seen: list[httpx.Request] = []
    async with outbound_client(transport=_redirecting(seen, target, status), follow_redirects=True,
                               headers={"User-Agent": "nexdeck"}, **client) as http:
        await http.request(method, START, headers=CREDENTIALS, **({"json": {"password": "secret"}} if method != "GET" else {}))
    return seen


@pytest.mark.parametrize("target", [
    "http://collect.example.com/api/v3/system/status",
    "https://collect.example.com/api/v3/system/status",
    "http://radarr.lan:9999/api/v3/system/status",
])
async def test_a_redirect_to_another_place_carries_no_credentials(target: str) -> None:
    seen = await _follow(target)
    assert len(seen) == 2 and str(seen[1].url) == target
    assert _carried(seen[0]) == set(CREDENTIALS)
    assert _carried(seen[1]) == set(), f"carried on to {target}: {_carried(seen[1])}"
    assert seen[1].headers["user-agent"] == "nexdeck", "what says who asks still goes along"


async def test_https_lowered_to_http_on_the_same_host_carries_no_credentials() -> None:
    seen: list[httpx.Request] = []
    async with outbound_client(transport=_redirecting(seen, "http://radarr.lan/api"), follow_redirects=True) as http:
        await http.get("https://radarr.lan/api", headers=CREDENTIALS)
    assert _carried(seen[1]) == set()


@pytest.mark.parametrize("start, target", [
    ("http://radarr.lan:7878/api", "http://radarr.lan:7878/api/"),
    ("http://udm/proxy/network/integration/v1/info", "https://udm/proxy/network/integration/v1/info"),
    ("http://unifi.lan:8080/api/self", "https://unifi.lan:8443/api/self"),
    ("http://NAS.lan:5000/webapi", "https://nas.lan:5001/webapi"),
])
async def test_a_redirect_within_the_service_keeps_its_credentials(start: str, target: str) -> None:
    """The same address, and http raised to https on the same host: UniFi, a classic controller, a reverse proxy."""
    seen: list[httpx.Request] = []
    async with outbound_client(transport=_redirecting(seen, target), follow_redirects=True) as http:
        answer = await http.get(start, headers={name: value for name, value in CREDENTIALS.items() if name != "Cookie"})
    assert answer.status_code == 200
    assert _carried(seen[1]) == set(CREDENTIALS) - {"Cookie"}


async def test_a_cookie_the_service_set_does_not_follow_it_to_another_port() -> None:
    """A client with a cookie jar sends a host's cookies to every port of it; the redirect may not."""
    seen = await _follow("http://radarr.lan:9999/elsewhere", keep_cookies=True)
    assert "cookie" not in seen[1].headers


async def test_a_post_that_keeps_its_body_is_not_sent_to_another_place() -> None:
    """307 and 308 repeat the body, and the body of a sign-in is the password."""
    seen: list[httpx.Request] = []
    async with outbound_client(transport=_redirecting(seen, "http://collect.example.com/login", status=307), follow_redirects=True) as http:
        with pytest.raises(base_module.RedirectRefused):
            await http.post(START, json={"password": "secret"})
    assert len(seen) == 1, f"the body went on: {[str(request.url) for request in seen]}"


async def test_a_post_answered_with_302_goes_on_as_a_plain_get() -> None:
    seen = await _follow("http://collect.example.com/done", method="POST")
    assert seen[1].method == "GET" and seen[1].content == b""
    assert _carried(seen[1]) == set()


async def test_a_post_within_the_service_still_follows_with_its_body() -> None:
    seen = await _follow("http://radarr.lan:7878/login/again", method="POST", status=307)
    assert seen[1].method == "POST" and b"secret" in seen[1].content
    assert _carried(seen[1]) == set(CREDENTIALS) - {"Cookie"}


# -- the clients the cards fetch through -------------------------------------------


@pytest.fixture
async def shared_clients(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[list[httpx.Request]]:
    """The collector's client, the relaxed one and the picture client, all built with a transport that redirects."""
    seen: list[httpx.Request] = []
    transport = _redirecting(seen, "http://collect.example.com/api")
    real = base_module.outbound_client

    def built(**kwargs: object) -> httpx.AsyncClient:
        return real(transport=transport, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(collector_module, "outbound_client", built)
    monkeypatch.setattr(base_module, "outbound_client", built)
    monkeypatch.setattr(widgets_module, "outbound_client", built)
    monkeypatch.setattr(base_module, "_relaxed", None)
    monkeypatch.setattr(widgets_module, "_insecure_client", None)
    yield seen
    for client in (base_module._relaxed, widgets_module._insecure_client):
        if client is not None:
            await client.aclose()


@pytest.mark.parametrize("verify", [True, False])
async def test_a_card_request_on_either_tls_mode_carries_no_key_to_another_host(shared_clients: list[httpx.Request], verify: bool) -> None:
    collector = collector_module.Collector()
    ctx = Context(collector.client, integration_id=1, widget_id=1, cache={})
    try:
        await ctx.request("GET", START, headers={"X-Api-Key": "radarr-key"}, verify=verify)
    finally:
        await collector.client.aclose()
    assert [str(request.url) for request in shared_clients] == [START, "http://collect.example.com/api"]
    assert "x-api-key" not in shared_clients[1].headers


async def test_the_picture_client_for_self_signed_services_carries_no_key_to_another_host(shared_clients: list[httpx.Request]) -> None:
    await widgets_module._image_client(True).get(START, headers={"X-Plex-Token": "plex-token"})
    assert "x-plex-token" not in shared_clients[1].headers


async def test_a_card_request_whose_body_would_go_to_another_host_says_so() -> None:
    seen: list[httpx.Request] = []
    async with outbound_client(transport=_redirecting(seen, "http://collect.example.com/login", status=308), follow_redirects=True) as http:
        ctx = Context(http, integration_id=1, widget_id=1, cache={})
        with pytest.raises(AdapterError) as refused:
            await ctx.request("POST", START, json_body={"password": "secret"})
    assert refused.value.code == "redirect_refused"
    assert "collect.example.com" in refused.value.message
    assert len(seen) == 1
