"""TrueNAS: the current API over a WebSocket, the REST API behind it.

The answers are the shapes TrueNAS 25.10.7 gave on 18.09.2026. What matters
most here is where the key goes: a key that reaches the current API over
plain http is revoked by TrueNAS for good (issue #4).
"""

from __future__ import annotations

import json
import time
from typing import Any

import httpx
import pytest
import respx
from websockets.datastructures import Headers
from websockets.exceptions import InvalidStatus
from websockets.http11 import Response

from app.adapters import get_adapter
from app.adapters.base import AdapterError, Context
from app.adapters.truenas import _version

KEY = "1-readonlykey"
INFO = {"version": "25.10.7", "hostname": "truenas", "uptime_seconds": 3600.5, "loadavg": [0.5, 0.3, 0.1], "physmem": 8_333_570_048, "cores": 4}
POOLS = [{"name": "tank", "status": "ONLINE", "healthy": True, "size": 16_642_998_272, "allocated": 2_711_552}]
ALERTS = [
    {"level": "WARNING", "dismissed": False, "datetime": {"$date": 1_789_712_345_000}, "formatted": "Pool tank is 91% full."},
    {"level": "CRITICAL", "dismissed": True, "datetime": {"$date": 1_789_700_000_000}, "formatted": "Dismissed, not shown."},
]
#: The same from before 25.04, where the REST API is the only one there is.
OLD_INFO = {**INFO, "version": "TrueNAS-SCALE-24.10.2"}
#: What a plain GET of /api/current, without a key, said on 25.10.7 on 21.09.2026.
NEEDS_UPGRADE = 'No WebSocket UPGRADE hdr: None\n Can "Upgrade" only to "WebSocket".'
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


def current_api(address: str, status: int) -> respx.Route:
    """The keyless look at /api/current: 400 on a TrueNAS that has it, 404 on one that has not."""
    return respx.get(f"{address}/api/current").mock(return_value=httpx.Response(status, text=NEEDS_UPGRADE if status == 400 else "404 page not found"))


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
    current_api("http://truenas.example.com", 404)
    respx.get("http://truenas.example.com/api/v2.0/system/info").mock(return_value=httpx.Response(403))
    with pytest.raises(AdapterError) as refused:
        await adapter.test({"url": "http://truenas.example.com", "api_key": KEY}, ctx)
    assert refused.value.code == "auth_failed"
    assert "https://" in refused.value.hint


@respx.mock
async def test_http_with_a_full_key_keeps_working_over_rest(ctx: Context, monkeypatch: pytest.MonkeyPatch) -> None:
    """On a TrueNAS from before 25.04, which has no other API."""
    adapter = get_adapter("truenas")
    monkeypatch.setattr(adapter, "_open_socket", no_socket)
    current_api("http://truenas.example.com", 404)
    respx.get("http://truenas.example.com/api/v2.0/system/info").mock(return_value=httpx.Response(200, json=OLD_INFO))
    respx.get("http://truenas.example.com/api/v2.0/pool").mock(return_value=httpx.Response(200, json=POOLS))
    pools = await adapter.fetch("pools", {"url": "http://truenas.example.com", "api_key": "2-full"}, {}, ctx)
    assert [item["title"] for item in pools.items] == ["tank"]
    assert respx.calls.last.request.headers["Authorization"] == "Bearer 2-full"


@respx.mock
async def test_rest_is_refused_where_truenas_has_deprecated_it(ctx: Context, monkeypatch: pytest.MonkeyPatch) -> None:
    """⚠️ A full administrator's key over http reaches the REST API on 25.10 and
    gets its answers. That it works is the trouble. Measured on 25.10.7: every
    call that signs in is counted, and one alert on the NAS names the count of
    the last 24 hours. It only goes away at no call at all, so not even the
    version may be asked over REST. A plain GET of /api/current, without the
    key, tells a TrueNAS that has the current API, once an hour."""
    adapter = get_adapter("truenas")
    monkeypatch.setattr(adapter, "_open_socket", no_socket)
    look = current_api("http://truenas.example.com", 400)
    rest = respx.get(url__startswith="http://truenas.example.com/api/v2.0/").mock(return_value=httpx.Response(200, json=INFO))
    config = {"url": "http://truenas.example.com", "api_key": "2-full"}
    started = time.monotonic()
    for minutes, kind in enumerate(("pools", "system", "alerts")):
        # Five minutes apart: past every short cache, well inside the hour.
        # Asked in the same second, the second call never leaves the request
        # cache, and this passed with nothing remembered at all.
        monkeypatch.setattr(time, "monotonic", lambda minutes=minutes: started + 300 * minutes)
        with pytest.raises(AdapterError) as refused:
            await adapter.fetch(kind, config, {}, ctx)
        assert refused.value.code == "deprecated_api"
        assert "Change the URL to https://" in refused.value.hint
    assert not rest.called, "one call over REST is one too many: it keeps the alert alive"
    assert look.call_count == 1, "asked once an hour, not once a card"
    assert "authorization" not in look.calls.last.request.headers, "the key stays at home for this"


@respx.mock
async def test_a_proxy_that_says_404_is_caught_by_the_version(ctx: Context, monkeypatch: pytest.MonkeyPatch) -> None:
    """The second line. Something in front says 404 for /api/current, so the
    REST API is asked, and what it says its version is settles it: once an
    hour, and nothing else goes there."""
    adapter = get_adapter("truenas")
    monkeypatch.setattr(adapter, "_open_socket", no_socket)
    current_api("http://truenas.example.com", 404)
    info = respx.get("http://truenas.example.com/api/v2.0/system/info").mock(return_value=httpx.Response(200, json={**INFO, "version": "25.10.1"}))
    pools = respx.get("http://truenas.example.com/api/v2.0/pool").mock(return_value=httpx.Response(200, json=POOLS))
    alerts = respx.get("http://truenas.example.com/api/v2.0/alert/list").mock(return_value=httpx.Response(200, json=ALERTS))
    config = {"url": "http://truenas.example.com", "api_key": "2-full"}
    started = time.monotonic()
    for minutes, kind in enumerate(("pools", "system", "alerts")):
        monkeypatch.setattr(time, "monotonic", lambda minutes=minutes: started + 300 * minutes)
        with pytest.raises(AdapterError) as refused:
            await adapter.fetch(kind, config, {}, ctx)
        assert refused.value.code == "deprecated_api"
        assert "25.10.1" in refused.value.message
    assert info.call_count == 1, "the version is asked once an hour, not once a card"
    assert not pools.called and not alerts.called


@respx.mock
async def test_the_system_card_of_an_older_truenas_keeps_moving(ctx: Context, monkeypatch: pytest.MonkeyPatch) -> None:
    """⚠️ The version comes from ``system/info``, and so do load and uptime. A
    first take kept that whole answer for the hour and handed it to the card:
    two minutes later the load had quadrupled and the card still said 12.5 %,
    on exactly the versions that were to notice nothing."""
    adapter = get_adapter("truenas")
    monkeypatch.setattr(adapter, "_open_socket", no_socket)
    current_api("http://truenas.example.com", 404)
    respx.get("http://truenas.example.com/api/v2.0/alert/list").mock(return_value=httpx.Response(200, json=[]))
    info = respx.get("http://truenas.example.com/api/v2.0/system/info").mock(return_value=httpx.Response(200, json=OLD_INFO))
    config = {"url": "http://truenas.example.com", "api_key": "2-full"}
    assert (await adapter.fetch("system", config, {}, ctx)).primary["value"] == 12.5
    started = time.monotonic()
    monkeypatch.setattr(time, "monotonic", lambda: started + 120)
    info.mock(return_value=httpx.Response(200, json={**OLD_INFO, "loadavg": [2.0, 1.0, 0.5]}))
    assert (await adapter.fetch("system", config, {}, ctx)).primary["value"] == 50.0


@respx.mock
async def test_behind_a_proxy_the_refusal_names_the_proxy_not_the_address(ctx: Context, monkeypatch: pytest.MonkeyPatch) -> None:
    """The address is https:// already. What has to change is the proxy that
    does not pass the WebSocket on, and the handshake's status says so."""
    adapter = get_adapter("truenas")
    monkeypatch.setattr(adapter, "_open_socket", turned_down(502))
    current_api("https://truenas.example.com", 400)
    rest = respx.get(url__startswith="https://truenas.example.com/api/v2.0/").mock(return_value=httpx.Response(200, json=INFO))
    with pytest.raises(AdapterError) as refused:
        await adapter.fetch("pools", {"url": "https://truenas.example.com", "api_key": "2-full"}, {}, ctx)
    assert not rest.called, "the look without the key was enough; nothing went over REST"
    assert refused.value.code == "deprecated_api"
    assert "HTTP 502" in refused.value.message
    assert "reverse proxy" in refused.value.hint
    assert "https://" not in refused.value.hint


@respx.mock
async def test_a_404_in_front_of_a_current_truenas_is_not_remembered_as_an_old_one(ctx: Context, monkeypatch: pytest.MonkeyPatch) -> None:
    """404 stands for a TrueNAS without the current API, for an hour. A proxy
    can say 404 as well; the version then shows it is no old TrueNAS, and the
    WebSocket has to be tried again once the proxy is mended."""
    adapter = get_adapter("truenas")
    attempts: list[str] = []

    async def gone(url: str, config: dict[str, Any]) -> Any:
        attempts.append(url)
        return await turned_down(404)(url, config)

    monkeypatch.setattr(adapter, "_open_socket", gone)
    respx.get("https://truenas.example.com/api/v2.0/system/info").mock(return_value=httpx.Response(200, json=INFO))
    config = {"url": "https://truenas.example.com", "api_key": "2-full"}
    for _ in range(2):
        with pytest.raises(AdapterError) as refused:
            await adapter.fetch("pools", config, {}, ctx)
        assert "reverse proxy" in refused.value.hint
    assert len(attempts) == 2


@pytest.mark.parametrize(("label", "expected"), [
    ("25.10.1", (25, 10)),
    ("25.04.0", (25, 4)),
    ("TrueNAS-SCALE-24.10.2", (24, 10)),
    ("TrueNAS-13.0-U6.1", (13, 0)),
    ("", (0, 0)),
    ("MASTER", (0, 0)),
])
def test_the_version_is_read_from_every_way_truenas_writes_it(label: str, expected: tuple[int, int]) -> None:
    assert _version(label) == expected


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
    current_api("https://truenas.example.com", 404)
    respx.get("https://truenas.example.com/api/v2.0/system/info").mock(return_value=httpx.Response(403))
    with pytest.raises(AdapterError) as refused:
        await adapter.test({"url": "https://truenas.example.com", "api_key": KEY}, ctx)
    assert "HTTP 400" in refused.value.message
    assert "reverse proxy" in refused.value.hint
