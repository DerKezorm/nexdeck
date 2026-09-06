"""The response cache: it has to forget, or it is the leak.

An entry holds a whole answer body. Nothing removed one, and an adapter whose
address carries a timestamp wrote a key nobody would ever look up again.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest
import respx

from app.adapters.base import (
    CACHE_PREFIX,
    MAX_CACHED_RESPONSES,
    AdapterError,
    Context,
    guard_outbound,
)


def _entries(ctx: Context) -> list[str]:
    return [key for key in ctx.cache if key.startswith(CACHE_PREFIX)]


@respx.mock
async def test_an_expired_answer_is_dropped_not_merely_skipped() -> None:
    respx.get(url__startswith="http://service.example.com/").mock(return_value=httpx.Response(200, json={"ok": True}))
    ctx = Context(httpx.AsyncClient(), integration_id=1, cache={})
    await ctx.get_json("http://service.example.com/a", cache_seconds=0.01)
    assert len(_entries(ctx)) == 1
    await asyncio.sleep(0.05)
    await ctx.get_json("http://service.example.com/b", cache_seconds=60)
    assert len(_entries(ctx)) == 1, "the expired one went out with the new one coming in"


@respx.mock
async def test_the_cache_stops_growing_at_its_cap() -> None:
    """An address with a timestamp in it makes a key that never repeats."""
    respx.get(url__startswith="http://service.example.com/").mock(return_value=httpx.Response(200, json={"ok": True}))
    ctx = Context(httpx.AsyncClient(), integration_id=1, cache={})
    for number in range(MAX_CACHED_RESPONSES * 3):
        await ctx.get_json("http://service.example.com/history", params={"since": number}, cache_seconds=600)
    assert len(_entries(ctx)) <= MAX_CACHED_RESPONSES


@respx.mock
async def test_a_live_answer_is_still_served_from_the_cache() -> None:
    route = respx.get("http://service.example.com/a").mock(return_value=httpx.Response(200, json={"ok": True}))
    ctx = Context(httpx.AsyncClient(), integration_id=1, cache={})
    for _ in range(5):
        await ctx.get_json("http://service.example.com/a", cache_seconds=60)
    assert route.call_count == 1, "the cache is still a cache"


@respx.mock
async def test_what_an_adapter_keeps_of_its_own_survives_a_sweep() -> None:
    """Tokens and cookies live in the same dict; only responses are pruned."""
    respx.get(url__startswith="http://service.example.com/").mock(return_value=httpx.Response(200, json={"ok": True}))
    ctx = Context(httpx.AsyncClient(), integration_id=1, cache={"kavita_token": "abc", "yt:@x": "UC..."})
    for number in range(MAX_CACHED_RESPONSES * 2):
        await ctx.get_json("http://service.example.com/x", params={"n": number}, cache_seconds=600)
    assert ctx.cache["kavita_token"] == "abc"
    assert ctx.cache["yt:@x"] == "UC..."


@pytest.mark.parametrize("url", [
    "http://169.254.169.254/latest/meta-data/iam/security-credentials/",
    "http://metadata.google.internal/computeMetadata/v1/",
    "http://[fd00:ec2::254]/latest/",
])
def test_the_machines_own_metadata_service_is_never_fetched(url: str) -> None:
    """A widget option is enough to name an address. This one hands out the
    credentials of the host nexdeck runs on."""
    with pytest.raises(AdapterError) as refused:
        guard_outbound(url)
    assert refused.value.code == "forbidden_host"


@pytest.mark.parametrize("url", [
    "http://192.168.1.10:8096/",
    "http://nas.local:5000/api",
    "https://example.com/feed.xml",
    "http://127.0.0.1:7878/",
])
def test_the_services_of_the_house_are_still_fetched(url: str) -> None:
    """A dashboard for a home network has to reach into that network."""
    guard_outbound(url)
