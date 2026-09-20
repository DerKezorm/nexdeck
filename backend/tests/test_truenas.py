"""TrueNAS: the current API over a WebSocket, the REST API behind it.

The answers are the shapes TrueNAS 25.10.7 gave on 18.09.2026. What matters
most here is where the key goes: a key that reaches the current API over
plain http is revoked by TrueNAS for good (issue #4).
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx
from websockets.datastructures import Headers
from websockets.exceptions import InvalidStatus
from websockets.http11 import Response

from app.adapters import get_adapter
from app.adapters.base import AdapterError, Context

KEY = "1-readonlykey"
INFO = {"version": "25.10.7", "hostname": "truenas", "uptime_seconds": 3600.5, "loadavg": [0.5, 0.3, 0.1], "physmem": 8_333_570_048, "cores": 4}
POOLS = [{"name": "tank", "status": "ONLINE", "healthy": True, "size": 16_642_998_272, "allocated": 2_711_552}]
ALERTS = [
    {"level": "WARNING", "dismissed": False, "datetime": {"$date": 1_789_712_345_000}, "formatted": "Pool tank is 91% full."},
    {"level": "CRITICAL", "dismissed": True, "datetime": {"$date": 1_789_700_000_000}, "formatted": "Dismissed, not shown."},
]
ANSWERS = {"system.info": INFO, "pool.query": POOLS, "alert.list": ALERTS}


class FakeTruenas:
    """A WebSocket that speaks JSON-RPC like TrueNAS, one per connection."""

    def __init__(self, key: str = KEY, refuse: dict[str, str] | None = None) -> None:
        self.key = key
        self.refuse = refuse or {}
        self.sent: list[dict[str, Any]] = []
        self.opened: list[str] = []
        self.closed = 0
        self._pending: list[str] = []
        self._authenticated = False

    async def open(self, url: str, config: dict[str, Any]) -> FakeTruenas:
        self.opened.append(url)
        self._authenticated = False
        return self

    async def send(self, text: str) -> None:
        message = json.loads(text)
        self.sent.append(message)
        method, number = message["method"], message["id"]
        # An event in between, as TrueNAS sends them, must not be taken for the answer.
        self._pending.append(json.dumps({"jsonrpc": "2.0", "method": "collection_update", "params": {}}))
        if method == "auth.login_with_api_key":
            self._authenticated = message["params"] == [self.key]
            self._pending.append(json.dumps({"jsonrpc": "2.0", "id": number, "result": self._authenticated}))
        elif not self._authenticated:
            self._pending.append(json.dumps({"jsonrpc": "2.0", "id": number, "error": {"code": -32001, "message": "Method call error", "data": {"errname": "ENOTAUTHENTICATED", "reason": "[ENOTAUTHENTICATED] Not authenticated"}}}))
        elif method in self.refuse:
            self._pending.append(json.dumps({"jsonrpc": "2.0", "id": number, "error": {"code": -32001, "message": "Method call error", "data": {"errname": self.refuse[method], "reason": "Not permitted"}}}))
        else:
            self._pending.append(json.dumps({"jsonrpc": "2.0", "id": number, "result": ANSWERS[method]}))

    async def recv(self) -> str:
        return self._pending.pop(0)

    async def close(self) -> None:
        self.closed += 1

    def methods(self) -> list[str]:
        return [message["method"] for message in self.sent]


def turned_down(status: int):
    async def open_socket(url: str, config: dict[str, Any]) -> Any:
        raise InvalidStatus(Response(status, "Not Found", Headers()))

    return open_socket


async def no_socket(url: str, config: dict[str, Any]) -> Any:
    raise AssertionError(f"a WebSocket was opened to {url}; over http that revokes the key")


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


@pytest.fixture
def truenas(monkeypatch: pytest.MonkeyPatch):
    adapter = get_adapter("truenas")
    fake = FakeTruenas()
    monkeypatch.setattr(adapter, "_open_socket", fake.open)
    return adapter, fake


async def test_https_reads_everything_through_the_current_api(ctx: Context, truenas) -> None:
    """A read-only administrator's key gets 403 from the REST API on 25.10 and
    everything from the current API."""
    adapter, fake = truenas
    config = {"url": "https://truenas.example.com/", "api_key": KEY}

    assert await adapter.test(config, ctx) == "TrueNAS 25.10.7 on truenas answers."
    assert fake.opened == ["wss://truenas.example.com/api/current"]

    fake.sent.clear()
    system = await adapter.fetch("system", config, {}, ctx)
    assert fake.methods() == ["auth.login_with_api_key", "system.info", "alert.list"], "one connection for both"
    assert system.primary == {"label": "Load", "value": 12.5, "unit": "%"}
    assert [entry["value"] for entry in system.secondary if entry["label"] == "Alerts"] == [1]
    assert system.status == "warn"

    pools = await adapter.fetch("pools", config, {}, ctx)
    assert [(item["title"], item["status"]) for item in pools.items] == [("tank", "ok")]

    alerts = await adapter.fetch("alerts", config, {}, ctx)
    assert [(item["title"], item["subtitle"]) for item in alerts.items] == [("Pool tank is 91% full.", "2026-09-18")], "a day, not the first ten digits of a timestamp"
    assert fake.closed == len(fake.opened), "every connection is closed again"


async def test_cards_share_what_was_just_read(ctx: Context, truenas) -> None:
    adapter, fake = truenas
    config = {"url": "https://truenas.example.com", "api_key": KEY}
    await adapter.fetch("system", config, {}, ctx)
    opened = len(fake.opened)
    await adapter.fetch("alerts", config, {}, ctx)
    assert len(fake.opened) == opened, "the alerts were read a moment ago by the system card"


async def test_a_refused_key_says_so_and_does_not_try_the_rest_api(ctx: Context, truenas) -> None:
    adapter, fake = truenas
    config = {"url": "https://truenas.example.com", "api_key": "1-wrong"}
    with respx.mock(assert_all_called=False) as router:
        rest = router.get(url__regex=r".*/api/v2\.0/.*").mock(return_value=httpx.Response(200, json={}))
        with pytest.raises(AdapterError) as refused:
            await adapter.test(config, ctx)
    assert refused.value.code == "auth_failed"
    assert "revokes" in refused.value.hint
    assert fake.methods() == ["auth.login_with_api_key"]
    assert not rest.called


async def test_a_method_the_role_may_not_call_names_the_role(ctx: Context, monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = get_adapter("truenas")
    fake = FakeTruenas(refuse={"pool.query": "EACCES"})
    monkeypatch.setattr(adapter, "_open_socket", fake.open)
    with pytest.raises(AdapterError) as refused:
        await adapter.fetch("pools", {"url": "https://truenas.example.com", "api_key": KEY}, {}, ctx)
    assert refused.value.code == "auth_failed"
    assert "Read-Only Administrator" in refused.value.hint


@respx.mock
async def test_http_never_opens_the_websocket_and_says_why_it_is_refused(ctx: Context, monkeypatch: pytest.MonkeyPatch) -> None:
    """TrueNAS revoked a key for good after one login over ws:// (measured).
    Over http the REST API is the only safe way, and on 25.10 it refuses a
    read-only key; the message has to say what to change."""
    adapter = get_adapter("truenas")
    monkeypatch.setattr(adapter, "_open_socket", no_socket)
    respx.get("http://truenas.example.com/api/v2.0/system/info").mock(return_value=httpx.Response(403))
    with pytest.raises(AdapterError) as refused:
        await adapter.test({"url": "http://truenas.example.com", "api_key": KEY}, ctx)
    assert refused.value.code == "auth_failed"
    assert "https://" in refused.value.hint


@respx.mock
async def test_http_with_a_full_key_keeps_working_over_rest(ctx: Context, monkeypatch: pytest.MonkeyPatch) -> None:
    """On a TrueNAS from before 25.04, where the REST API is the only one there is."""
    adapter = get_adapter("truenas")
    monkeypatch.setattr(adapter, "_open_socket", no_socket)
    respx.get("http://truenas.example.com/api/v2.0/system/info").mock(return_value=httpx.Response(200, json={**INFO, "version": "TrueNAS-SCALE-24.10.2"}))
    respx.get("http://truenas.example.com/api/v2.0/pool").mock(return_value=httpx.Response(200, json=POOLS))
    pools = await adapter.fetch("pools", {"url": "http://truenas.example.com", "api_key": "2-full"}, {}, ctx)
    assert [item["title"] for item in pools.items] == ["tank"]
    assert respx.calls.last.request.headers["Authorization"] == "Bearer 2-full"


@respx.mock
async def test_the_rest_api_is_refused_on_a_truenas_that_deprecates_it(ctx: Context, monkeypatch: pytest.MonkeyPatch) -> None:
    """⚠️ A full administrator's key over http reached the REST API on 25.10 and
    it worked, quietly: every call raised a deprecation alert on the NAS from
    25.10.1, and 26 removes the API altogether. The version is read once and
    the card says what to change, rather than feeding an API that is on its
    way out."""
    adapter = get_adapter("truenas")
    monkeypatch.setattr(adapter, "_open_socket", no_socket)
    respx.get("http://truenas.example.com/api/v2.0/system/info").mock(return_value=httpx.Response(200, json={**INFO, "version": "25.10.1"}))
    pools = respx.get("http://truenas.example.com/api/v2.0/pool").mock(return_value=httpx.Response(200, json=POOLS))
    with pytest.raises(AdapterError) as refused:
        await adapter.fetch("pools", {"url": "http://truenas.example.com", "api_key": "2-full"}, {}, ctx)
    assert refused.value.code == "deprecated_api"
    assert "https://" in refused.value.hint
    assert not pools.called, "nothing but the version check goes to the deprecated API"


async def test_the_websocket_path_refuses_http_on_its_own(truenas) -> None:
    """The last line in front of a revoked key does not rely on the caller."""
    adapter, fake = truenas
    with pytest.raises(AdapterError):
        await adapter._rpc({"url": "http://truenas.example.com", "api_key": KEY}, ["system.info"])
    assert fake.opened == []


@respx.mock
async def test_an_older_truenas_without_the_current_api_falls_back_to_rest(ctx: Context, monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = get_adapter("truenas")
    attempts: list[str] = []

    async def gone(url: str, config: dict[str, Any]) -> Any:
        attempts.append(url)
        return await turned_down(404)(url, config)

    monkeypatch.setattr(adapter, "_open_socket", gone)
    respx.get("https://truenas.example.com/api/v2.0/system/info").mock(return_value=httpx.Response(200, json={**INFO, "version": "TrueNAS-SCALE-24.10.2"}))
    config = {"url": "https://truenas.example.com", "api_key": KEY}
    assert await adapter.test(config, ctx) == "TrueNAS TrueNAS-SCALE-24.10.2 on truenas answers."
    assert await adapter.test(config, ctx) == "TrueNAS TrueNAS-SCALE-24.10.2 on truenas answers."
    assert len(attempts) == 1, "a TrueNAS without the current API is not asked again within the hour"


@respx.mock
async def test_a_proxy_without_websockets_is_named_when_rest_refuses_too(ctx: Context, monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = get_adapter("truenas")
    monkeypatch.setattr(adapter, "_open_socket", turned_down(400))
    respx.get("https://truenas.example.com/api/v2.0/system/info").mock(return_value=httpx.Response(403))
    with pytest.raises(AdapterError) as refused:
        await adapter.test({"url": "https://truenas.example.com", "api_key": KEY}, ctx)
    assert "HTTP 400" in refused.value.message
    assert "reverse proxy" in refused.value.hint
