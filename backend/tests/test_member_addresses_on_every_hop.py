"""An address a member typed is checked on every hop, not only on the first.

⚠️ The client hook that runs for every hop of a redirect checked the metadata
address and link-local, not loopback, because it serves connections as well,
and an administrator may point one of those at 127.0.0.1. Where a member typed
the address, in an RSS card or a reachability check, the first address got the
member rule and a redirect from a server of their own led on to 127.0.0.1
unchecked. The Wake-on-LAN card knocked on any address and sent its packet to
any broadcast address with no check at all. Found on 12.09.2026.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator

import httpx
import pytest

from app import config
from app.adapters import base as base_module
from app.adapters import get_adapter
from app.adapters import wol as wol_module
from app.adapters.base import AdapterError, Context, outbound_client
from app.services import health

LOOPBACK = "http://127.0.0.1:8000/api/v1/boards"
MAC = "00:1A:2B:3C:4D:5E"


@pytest.fixture(autouse=True)
def fresh_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.delenv("NEXDECK_ALLOW_LOOPBACK_TARGETS", raising=False)
    config.reset_settings_cache()
    yield
    config.reset_settings_cache()


def _redirecting(seen: list[str]) -> httpx.MockTransport:
    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if request.url.host != "127.0.0.1":
            return httpx.Response(302, headers={"Location": LOOPBACK})
        return httpx.Response(200, text="<rss version='2.0'><channel><item><title>inside</title></item></channel></rss>")

    return httpx.MockTransport(handler)


def test_a_member_client_refuses_a_redirect_to_loopback_and_a_connection_client_follows_it() -> None:
    seen: list[str] = []

    async def probe(member: bool) -> int:
        client = outbound_client(member=member, transport=_redirecting(seen), follow_redirects=True)
        try:
            return (await client.get("http://feeds.example.com/start")).status_code
        finally:
            await client.aclose()

    with pytest.raises(AdapterError) as refused:
        asyncio.run(probe(member=True))
    assert refused.value.code == "forbidden_host"
    assert seen == ["http://feeds.example.com/start"], f"the second hop was sent anyway: {seen}"

    seen.clear()
    assert asyncio.run(probe(member=False)) == 200, "an administrator's connection may still reach 127.0.0.1"
    assert seen == ["http://feeds.example.com/start", LOOPBACK]


def test_a_reachability_check_does_not_follow_a_redirect_to_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []
    real = health.outbound_client
    monkeypatch.setattr(health, "outbound_client", lambda **kwargs: real(transport=_redirecting(seen), **kwargs))
    monkeypatch.setattr(health, "_clients", {})
    ok, _latency, detail = asyncio.run(health.check_http("http://checks.example.com/start", 5.0, 0, False))
    assert ok is False
    assert "not an address nexdeck calls" in detail
    assert LOOPBACK not in seen


def test_an_rss_card_does_not_follow_a_feed_to_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []
    real = base_module.outbound_client
    monkeypatch.setattr(base_module, "outbound_client", lambda **kwargs: real(transport=_redirecting(seen), **kwargs))
    monkeypatch.setattr(base_module, "_member_clients", {}, raising=False)
    # What the collector hands every card: a shared client with the connection rule.
    shared = real(transport=_redirecting(seen), follow_redirects=True)
    ctx = Context(shared, integration_id=1, widget_id=1, cache={})

    async def fetch() -> object:
        try:
            return await get_adapter("rss").fetch("feed", {}, {"urls": "http://feeds.example.com/start"}, ctx)
        finally:
            await shared.aclose()

    data = asyncio.run(fetch())
    assert LOOPBACK not in seen, "the feed was read from 127.0.0.1"
    assert data.status == "bad"


def test_a_wake_on_lan_card_neither_knocks_on_nor_sends_to_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    knocked: list[str] = []
    sent: list[str] = []

    async def pretend_reachable(host: str, port: int, timeout: float = 2.0) -> bool:
        knocked.append(host)
        return True

    monkeypatch.setattr(wol_module, "reachable", pretend_reachable)
    monkeypatch.setattr(wol_module, "_send", lambda packet, broadcast, port: sent.append(broadcast))
    card = get_adapter("wol")
    ctx = Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})
    knock_on_the_server = {"mac": MAC, "host": "127.0.0.1", "check_port": 8000}

    with pytest.raises(AdapterError) as refused:
        asyncio.run(card.fetch("wake", {}, knock_on_the_server, ctx))
    assert refused.value.code == "forbidden_host"
    with pytest.raises(AdapterError):
        asyncio.run(card.test(knock_on_the_server, ctx))
    with pytest.raises(AdapterError) as refused_packet:
        asyncio.run(card.action("wake", "wake", {}, {}, {"mac": MAC, "broadcast": "127.0.0.1"}, ctx))
    assert refused_packet.value.code == "forbidden_host"
    assert knocked == [] and sent == []

    # The house stays reachable.
    asyncio.run(card.action("wake", "wake", {}, {}, {"mac": MAC, "broadcast": "192.0.2.255"}, ctx))
    assert sent == ["192.0.2.255"]
