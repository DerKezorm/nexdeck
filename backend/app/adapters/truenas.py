"""TrueNAS SCALE through its current API, with the REST API v2 behind it.

TrueNAS has two APIs. The REST API under ``/api/v2.0`` is deprecated since
25.04, and on 25.10 it answers a key of a **read-only administrator** with 403
for everything, including ``system/info`` (issue #4, measured on 25.10.7). The
current API is JSON-RPC 2.0 over a WebSocket at ``/api/current``, and there
the same key reads the system, the pools and the alerts.

⚠️ **The key never goes over plain http to the current API.** TrueNAS revokes
a key the moment it arrives over ``ws://``, for good, with "Attempt to use
over an insecure transport". Measured on 25.10.7: one login over ``ws://`` and
the key was dead over ``wss://`` as well. The same kind of key sent to the
REST API over http was not revoked. So an ``http://`` address keeps the REST
API and explains what to change when that is refused; only ``https://``
speaks the current API.

⚠️ A TrueNAS older than 25.04 has no ``/api/current``. Whatever turns the
handshake down, the REST API is asked instead, which those versions accept
from a read-only key. That an older TrueNAS says 404 there is expected, not
measured; 25.10.7 said 404 for ``/api/v99``.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import ssl
import time
from datetime import UTC, datetime
from typing import Any

import websockets
from websockets.exceptions import InvalidStatus, WebSocketException

from . import demo as fake
from .base import (
    Adapter,
    AdapterError,
    AuthFailed,
    Context,
    Detected,
    Field,
    Unreachable,
    WidgetData,
    WidgetType,
    base_url,
    duration_short,
    guard_outbound,
    human_bytes,
    percent,
    percent_text,
    status_from_percent,
)

#: What each card reads: the JSON-RPC method and the same thing on REST v2.
READS = {
    "system.info": "/system/info",
    "pool.query": "/pool",
    "alert.list": "/alert/list",
}

#: How long a TrueNAS without ``/api/current`` is not asked again.
LEGACY_SECONDS = 3600.0

HTTP_REFUSED_HINT = (
    "Over http:// only the old REST API is safe, and TrueNAS 25.04 and later let only a full "
    "administrator's key use it. Change the URL to https:// and a read-only administrator's key "
    "works, because nexdeck then uses the current API. Over plain http TrueNAS would revoke the key."
)


class TruenasAdapter(Adapter):
    kind = "truenas"
    label = "TrueNAS"
    category = "nas"
    description = "Pools, alerts, load and uptime."
    icon = "truenas"
    docs_url = "https://www.truenas.com/docs/api/"
    #: Every card against TrueNAS SCALE 25.10.7 with a read-only and a full key, 18.09.2026.
    beta = False
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="https://truenas.local",
              help="Use https://. Over http:// a read-only key is refused."),
        Field("api_key", "API key", type="password", secret=True, required=True,
              help="Top-right user menu > API Keys. A user with the Read-Only Administrator role is enough."),
        Field("insecure", "Ignore TLS errors", type="bool", default=True),
    )
    widgets = (
        WidgetType(kind="system", label="System", description="Load, memory, uptime and open alerts.", renderer="stats", default_size=(4, 2), refresh_seconds=30, metrics=("load",)),
        WidgetType(kind="pools", label="Pools", description="Every pool with usage and health.", renderer="list", default_size=(3, 2), refresh_seconds=120),
        WidgetType(kind="alerts", label="Alerts", description="Open alerts by level.", renderer="list", default_size=(3, 2), refresh_seconds=60),
    )

    # -- the REST API v2 -------------------------------------------------------

    def _headers(self, config: dict[str, Any]) -> dict[str, str]:
        return {"Authorization": f"Bearer {config.get('api_key', '')}"}

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, cache: float = 10) -> Any:
        return await ctx.get_json(f"{base_url(config)}/api/v2.0{path}", headers=self._headers(config), verify=not config.get("insecure", True), cache_seconds=cache)

    # -- the current API -------------------------------------------------------

    async def _open_socket(self, url: str, config: dict[str, Any]) -> Any:
        """The WebSocket, as its own method so a test can hand in a fake one."""
        options: dict[str, Any] = {}
        if config.get("insecure", True):
            relaxed = ssl.create_default_context()
            relaxed.check_hostname = False
            relaxed.verify_mode = ssl.CERT_NONE
            options["ssl"] = relaxed
        return await websockets.connect(url, open_timeout=10, max_size=16 * 1024 * 1024, **options)

    async def _rpc(self, config: dict[str, Any], methods: list[str]) -> dict[str, Any]:
        """Log in with the key and call each method once, on one connection."""
        address = base_url(config)
        if not address.startswith("https://"):
            # The one line between a key and its revocation; see the top.
            raise AdapterError("The current TrueNAS API is only spoken over https.", code="bad_scheme")
        url = "wss://" + address.removeprefix("https://") + "/api/current"
        ids = itertools.count(1)

        async def call(socket: Any, method: str, *params: Any) -> Any:
            number = next(ids)
            await socket.send(json.dumps({"jsonrpc": "2.0", "id": number, "method": method, "params": list(params)}))
            while True:
                message = json.loads(await socket.recv())
                # Events and answers to something else are skipped.
                if message.get("id") != number:
                    continue
                if "error" in message:
                    error = message["error"] or {}
                    data = error.get("data") or {}
                    reason = str(data.get("reason") or error.get("message") or "TrueNAS refused the call.")
                    if data.get("errname") in ("EACCES", "ENOTAUTHENTICATED"):
                        raise AdapterError(f"TrueNAS refused {method}: {reason}", code="auth_failed",
                                           hint="The key's user needs at least the Read-Only Administrator role.")
                    raise AdapterError(f"TrueNAS answered {method} with an error: {reason}", code="rpc_error")
                return message.get("result")

        try:
            async with asyncio.timeout(20):
                socket = await self._open_socket(url, config)
                try:
                    if await call(socket, "auth.login_with_api_key", str(config.get("api_key") or "")) is not True:
                        raise AdapterError(
                            "TrueNAS refused the API key.", code="auth_failed",
                            hint="Check the key. TrueNAS revokes a key for good once it was sent over plain http; then only a new one helps.",
                        )
                    return {method: await call(socket, method) for method in methods}
                finally:
                    await socket.close()
        except InvalidStatus as error:
            raise _NoCurrentApi(error.response.status_code) from error
        except TimeoutError as error:
            raise Unreachable("TrueNAS did not answer in time.") from error
        except (OSError, WebSocketException) as error:
            raise Unreachable(f"TrueNAS could not be reached: {error.__class__.__name__}.") from error

    async def _read(self, config: dict[str, Any], ctx: Context, methods: list[str], cache: float = 10) -> dict[str, Any]:
        """What the cards need, from whichever API this TrueNAS should be asked."""
        guard_outbound(base_url(config))
        now = time.monotonic()
        found: dict[str, Any] = {}
        missing = []
        for method in methods:
            hit = ctx.cache.get(f"truenas:{method}")
            if cache and hit and hit[0] > now:
                found[method] = hit[1]
            else:
                missing.append(method)
        if not missing:
            return found
        legacy = ctx.cache.get("truenas:legacy")
        if base_url(config).startswith("https://") and not (legacy and legacy > now):
            try:
                fresh = await self._rpc(config, missing)
            except _NoCurrentApi as gone:
                # 404 is a TrueNAS without the current API, and that does not
                # change within the hour. Anything else is more likely a
                # reverse proxy that does not pass WebSockets on, and that
                # gets fixed; it is asked again every time.
                if gone.status == 404:
                    ctx.cache["truenas:legacy"] = now + LEGACY_SECONDS
                try:
                    fresh = {method: await self._get(config, ctx, READS[method], cache=cache) for method in missing}
                except AuthFailed as error:
                    raise AdapterError(
                        f"TrueNAS turned the WebSocket at /api/current down with HTTP {gone.status}, "
                        "and its old REST API refused the key.", code="auth_failed",
                        hint="A reverse proxy in front of TrueNAS has to pass WebSockets on. "
                             "The old REST API accepts only a full administrator's key on TrueNAS 25.04 and later.",
                    ) from error
        else:
            try:
                fresh = {method: await self._get(config, ctx, READS[method], cache=cache) for method in missing}
            except AuthFailed as error:
                if base_url(config).startswith("http://"):
                    raise AdapterError("TrueNAS refused the API key on its REST API.", code="auth_failed",
                                       hint=HTTP_REFUSED_HINT) from error
                raise
        for method, value in fresh.items():
            ctx.cache[f"truenas:{method}"] = (now + cache, value)
        return {**found, **fresh}

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        info = (await self._read(config, ctx, ["system.info"], cache=0))["system.info"] or {}
        return f"TrueNAS {info.get('version', '?')} on {info.get('hostname', '?')} answers."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "system":
            read = await self._read(config, ctx, ["system.info", "alert.list"])
            info = read["system.info"] or {}
            alerts = [a for a in read["alert.list"] or [] if not a.get("dismissed")]
            load = float((info.get("loadavg") or [0])[0])
            cores = int(info.get("cores") or 1)
            load_percent = round(100.0 * load / cores, 1)
            memory_total = float(info.get("physmem") or 0)
            return WidgetData(
                status="bad" if any(a.get("level") in ("CRITICAL", "ERROR") for a in alerts) else ("warn" if alerts else status_from_percent(load_percent)),
                primary={"label": "Load", "value": load_percent, "unit": "%"},
                secondary=[{"label": "Memory", "value": human_bytes(memory_total)}, {"label": "Uptime", "value": duration_short(info.get("uptime_seconds"))}, {"label": "Alerts", "value": len(alerts)}],
                metrics={"load": load_percent},
            )
        if widget_kind == "pools":
            items = []
            for pool in (await self._read(config, ctx, ["pool.query"], cache=60))["pool.query"] or []:
                used = percent(pool.get("allocated"), pool.get("size"))
                items.append({
                    "title": pool.get("name", "?"), "subtitle": f"{human_bytes(pool.get('allocated'))} of {human_bytes(pool.get('size'))} · {pool.get('status', '?')}",
                    "progress": used, "value": percent_text(used),
                    # A pool whose size did not come is not a healthy pool.
                    "status": "unknown" if used is None else ("ok" if pool.get("healthy") and used < 90 else "warn"),
                })
            return WidgetData(items=items)
        alerts = [a for a in (await self._read(config, ctx, ["alert.list"]))["alert.list"] or [] if not a.get("dismissed")]
        items = [{"title": str(a.get("formatted") or a.get("text", "?"))[:120], "subtitle": _day(a.get("datetime")), "status": "bad" if a.get("level") in ("CRITICAL", "ERROR") else "warn"} for a in alerts]
        return WidgetData(status="bad" if any(i["status"] == "bad" for i in items) else ("warn" if items else "ok"), items=items or [], secondary=[{"label": "Open", "value": len(items)}])

    #: Above this, a pool has stopped being somebody's problem for later.
    FULL_PERCENT = 90.0

    def detect(self, widget_kind: str, before: WidgetData | None, after: WidgetData,
               options: dict[str, Any]) -> list[Detected]:
        """A pool that crossed into the last tenth of itself.

        ⚠️ Only on the crossing. A pool that sits at 94 per cent for a month
        is not news every five minutes; it became news once.
        """
        if widget_kind not in ("pools", "volumes"):
            return []
        was = {}
        for item in (before.items if before and not before.error else []):
            was[str(item.get("title"))] = _percent(item)
        found = []
        for item in after.items:
            name = str(item.get("title") or "?")
            now = _percent(item)
            if now is None or now < self.FULL_PERCENT:
                continue
            earlier = was.get(name)
            if earlier is not None and earlier >= self.FULL_PERCENT:
                continue
            found.append(Detected(
                event="disk_filling",
                title=f"{name} is {now:.0f}% full",
                body=str(item.get("subtitle") or ""),
                level="warn",
                key=f"disk_filling:{name}",
                quiet_seconds=86400,
            ))
        return found[:5]

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        load = fake.walk("truenas-load", tick, 5, 30)
        if widget_kind == "system":
            return WidgetData(primary={"label": "Load", "value": load, "unit": "%"}, secondary=[{"label": "Memory", "value": "64.0 GB"}, {"label": "Uptime", "value": duration_short(12 * 86400 + tick)}, {"label": "Alerts", "value": 1}], metrics={"load": load}, status="warn")
        if widget_kind == "pools":
            return WidgetData(items=[{"title": "tank", "subtitle": "41.2 TB of 58.0 TB · ONLINE", "progress": 71.0, "value": "71%", "status": "ok"}, {"title": "fast", "subtitle": "1.2 TB of 1.8 TB · ONLINE", "progress": 66.6, "value": "67%", "status": "ok"}])
        return WidgetData(status="warn", items=[{"title": "Scrub of pool tank finished with 0 errors", "subtitle": "2026-09-04", "status": "warn"}], secondary=[{"label": "Open", "value": 1}])


ADAPTER = TruenasAdapter()


class _NoCurrentApi(Exception):
    """The WebSocket at ``/api/current`` was turned down before it opened."""

    def __init__(self, status: int) -> None:
        super().__init__(status)
        self.status = status


def _day(value: Any) -> str:
    """The day of an alert. TrueNAS sends ``{"$date": milliseconds}``.

    ⚠️ The card used to cut the first ten characters off that number and
    showed ``1788181994`` where a date belonged.
    """
    if isinstance(value, dict):
        value = value.get("$date")
    if isinstance(value, int | float):
        return datetime.fromtimestamp(value / 1000, UTC).strftime("%Y-%m-%d")
    return str(value or "")[:10]


def _percent(item: dict[str, Any]) -> float | None:
    """How full, from whichever field the card put it in."""
    for key in ("progress", "percent", "used_percent"):
        value = item.get(key)
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
    raw = str(item.get("value") or "").rstrip("%")
    try:
        return float(raw)
    except ValueError:
        return None
