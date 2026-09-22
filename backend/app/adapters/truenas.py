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

⚠️ **The REST API is for those older versions only.** With a full
administrator's key it still answers on 25.04 and later, and that is the
trouble. Measured on 25.10.7 on 21.09.2026: TrueNAS counts every call that
signs in over REST and raises one alert, "Deprecated REST API usage", with the
count of the last 24 hours and the addresses they came from; eight calls from
the cards read "8 times". TrueNAS 26 removes the API (its list of
deprecations). The alert only goes away at no call at all, so reading the
version over REST first would keep it alive, at 24 calls a day.

So a TrueNAS with the current API is recognised without a key: a plain GET of
``/api/current`` answered 400 ("Can Upgrade only to WebSocket"), a path that
does not exist 404, over http and over https alike, and neither moved the
count. Only a 404 there lets the REST API be asked, and what it says its
version is remains the second line, for a proxy that says 404 on TrueNAS'
behalf.

The system card reads CPU and memory from the realtime event
``reporting.realtime`` on the same connection, as TrueNAS' own dashboard does.
Measured on 25.10.7 on 22.09.2026 with a read-only administrator's key: the
subscription is allowed, the first event arrives 0.01 s after it, and an idle
NAS with 8 GB reported 3.3 GB free and 3.8 GB of ZFS cache. The services use
what is left, 1.3 GB; counting the cache as taken would have said 61 per cent.
Over REST there are no events, and the load average stands in as before.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import re
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

#: Not a method but the realtime event, read once per fetch on the same connection.
REALTIME = "reporting.realtime"
#: How long the first realtime event may take. TrueNAS sends it at once.
REALTIME_WAIT = 5.0

#: How long a TrueNAS without ``/api/current`` is not asked again.
LEGACY_SECONDS = 3600.0

#: How long the version read over REST is kept, and from which one on REST is refused.
VERSION_SECONDS = 3600.0
REST_DEPRECATED_FROM = (25, 4)

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
              help="Use https://. Over http:// only a TrueNAS before 25.04 is read, and only with a full administrator's key."),
        Field("api_key", "API key", type="password", secret=True, required=True,
              help="Top-right user menu > API Keys. A user with the Read-Only Administrator role is enough."),
        Field("insecure", "Ignore TLS errors", type="bool", default=True),
    )
    widgets = (
        WidgetType(kind="system", label="System", description="CPU, memory, uptime and open alerts.", renderer="stats", default_size=(4, 2), refresh_seconds=30, metrics=("cpu", "memory", "load")),
        WidgetType(kind="pools", label="Pools", description="Every pool with usage and health.", renderer="list", default_size=(3, 2), refresh_seconds=120),
        WidgetType(kind="alerts", label="Alerts", description="Open alerts by level.", renderer="list", default_size=(3, 2), refresh_seconds=60),
    )

    # -- the REST API v2 -------------------------------------------------------

    def _headers(self, config: dict[str, Any]) -> dict[str, str]:
        return {"Authorization": f"Bearer {config.get('api_key', '')}"}

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, cache: float = 10) -> Any:
        return await ctx.get_json(f"{base_url(config)}/api/v2.0{path}", headers=self._headers(config), verify=not config.get("insecure", True), cache_seconds=cache)

    async def _has_current_api(self, config: dict[str, Any], ctx: Context, fresh: bool = False) -> bool:
        """Whether this TrueNAS has ``/api/current``, asked without the key; see the top.

        ⚠️ No ``Authorization`` header here, ever. It is what makes a call count
        for TrueNAS' alert, and over http it would be the key in the clear on
        its way to an API that revokes it for that.

        Only 404 means no. A redirect to https, a proxy's 502 and the 400 of
        TrueNAS itself all belong to somebody who should not get REST calls.
        """
        now = time.monotonic()
        known = ctx.cache.get("truenas:current-api")
        if not fresh and known and known[0] > now:
            return known[1]
        answer = await ctx.request("GET", f"{base_url(config)}/api/current", verify=not config.get("insecure", True), timeout=10, auth_errors=False)
        there = answer.status_code != 404
        ctx.cache["truenas:current-api"] = (now + VERSION_SECONDS, there)
        return there

    async def _rest(self, config: dict[str, Any], ctx: Context, methods: list[str], cache: float, turned_down: int | None = None) -> dict[str, Any]:
        """The REST API, for a TrueNAS that has nothing newer; see the top.

        ``turned_down`` is the status the WebSocket handshake was refused with,
        when that is why REST is asked at all.

        ⚠️ Only the version is kept for the hour, never the answer it came in.
        The system card takes load and uptime from ``system/info`` too, and an
        answer kept for an hour would freeze that card on exactly the older
        versions this fallback is for.
        """
        now = time.monotonic()
        # A handshake that said 404 has asked the question below already.
        if turned_down != 404 and await self._has_current_api(config, ctx, fresh=not cache):
            raise _rest_refused("", base_url(config), turned_down)
        fresh: dict[str, Any] = {}
        known = ctx.cache.get("truenas:version")
        if cache and known and known[0] > now:
            label = known[1]
        else:
            info = await self._get(config, ctx, READS["system.info"], cache=cache)
            label = str((info or {}).get("version") or "")
            ctx.cache["truenas:version"] = (now + VERSION_SECONDS, label)
            fresh["system.info"] = info
        if _version(label) >= REST_DEPRECATED_FROM:
            # Not a TrueNAS without the current API after all, whatever the
            # handshake said: the WebSocket is tried again next time.
            ctx.cache.pop("truenas:legacy", None)
            raise _rest_refused(label, base_url(config), turned_down)
        for method in methods:
            if method == REALTIME:
                # The REST API has no realtime events: the load average stands in.
                fresh[method] = None
            elif method not in fresh:
                fresh[method] = await self._get(config, ctx, READS[method], cache=cache)
        return {method: fresh[method] for method in methods}

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

        async def realtime(socket: Any) -> dict[str, Any] | None:
            """One realtime event: CPU and memory as TrueNAS' own dashboard shows them.

            A subscription, not a call: ``core.subscribe`` answers with an
            id, then ``collection_update`` messages arrive, the first at once
            (the event source sends before its first pause). One is enough;
            the socket closes after it. Anything short of an event, a refusal
            or silence, is None, and the card falls back to the load average.
            """
            number = next(ids)
            await socket.send(json.dumps({"jsonrpc": "2.0", "id": number, "method": "core.subscribe", "params": [REALTIME]}))
            try:
                async with asyncio.timeout(REALTIME_WAIT):
                    while True:
                        message = json.loads(await socket.recv())
                        if message.get("id") == number and "error" in message:
                            return None
                        params = message.get("params") if message.get("method") == "collection_update" else None
                        if isinstance(params, dict) and str(params.get("collection") or "").startswith(REALTIME):
                            fields = params.get("fields")
                            return fields if isinstance(fields, dict) and fields else None
            except TimeoutError:
                return None

        try:
            async with asyncio.timeout(20):
                socket = await self._open_socket(url, config)
                try:
                    if await call(socket, "auth.login_with_api_key", str(config.get("api_key") or "")) is not True:
                        raise AdapterError(
                            "TrueNAS refused the API key.", code="auth_failed",
                            hint="Check the key. TrueNAS revokes a key for good once it was sent over plain http; then only a new one helps.",
                        )
                    answers = {}
                    for method in methods:
                        answers[method] = await realtime(socket) if method == REALTIME else await call(socket, method)
                    return answers
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
                    fresh = await self._rest(config, ctx, missing, cache, turned_down=gone.status)
                except AuthFailed as error:
                    raise AdapterError(
                        f"TrueNAS turned the WebSocket at /api/current down with HTTP {gone.status}, "
                        "and its old REST API refused the key.", code="auth_failed",
                        hint="A reverse proxy in front of TrueNAS has to pass WebSockets on. "
                             "The old REST API accepts only a full administrator's key on TrueNAS 25.04 and later.",
                    ) from error
        else:
            # Over https this branch is only reached within the hour after a
            # handshake that said 404, and that answer still stands.
            remembered = 404 if base_url(config).startswith("https://") else None
            try:
                fresh = await self._rest(config, ctx, missing, cache, turned_down=remembered)
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
            read = await self._read(config, ctx, ["system.info", "alert.list", REALTIME])
            info = read["system.info"] or {}
            alerts = [a for a in read["alert.list"] or [] if not a.get("dismissed")]
            flagged = "bad" if any(a.get("level") in ("CRITICAL", "ERROR") for a in alerts) else ("warn" if alerts else "")
            uptime = {"label": "Uptime", "value": duration_short(info.get("uptime_seconds"))}
            counted = {"label": "Alerts", "value": len(alerts)}
            live = _live(read.get(REALTIME))
            if live is not None:
                cpu, used, total, cache = live
                chips = [{"label": "Memory", "value": f"{human_bytes(used)} of {human_bytes(total)}"}]
                if cache:
                    chips.append({"label": "ZFS cache", "value": human_bytes(cache)})
                memory = round(100.0 * used / total, 1)
                return WidgetData(
                    status=flagged or status_from_percent(max(cpu, memory)),
                    primary={"label": "CPU", "value": cpu, "unit": "%"},
                    secondary=[*chips, uptime, counted],
                    metrics={"cpu": cpu, "memory": memory},
                )
            load = float((info.get("loadavg") or [0])[0])
            cores = int(info.get("cores") or 1)
            load_percent = round(100.0 * load / cores, 1)
            memory_total = float(info.get("physmem") or 0)
            return WidgetData(
                status=flagged or status_from_percent(load_percent),
                primary={"label": "Load", "value": load_percent, "unit": "%"},
                secondary=[{"label": "Memory", "value": human_bytes(memory_total)}, uptime, counted],
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
            memory = fake.walk("truenas-memory", tick, 18, 26)
            return WidgetData(primary={"label": "CPU", "value": load, "unit": "%"},
                              secondary=[{"label": "Memory", "value": f"{human_bytes(memory / 100 * 64 * 1024 ** 3)} of 64.0 GB"}, {"label": "ZFS cache", "value": "38.2 GB"},
                                         {"label": "Uptime", "value": duration_short(12 * 86400 + tick)}, {"label": "Alerts", "value": 1}],
                              metrics={"cpu": load, "memory": memory}, status="warn")
        if widget_kind == "pools":
            return WidgetData(items=[{"title": "tank", "subtitle": "41.2 TB of 58.0 TB · ONLINE", "progress": 71.0, "value": "71%", "status": "ok"}, {"title": "fast", "subtitle": "1.2 TB of 1.8 TB · ONLINE", "progress": 66.6, "value": "67%", "status": "ok"}])
        return WidgetData(status="warn", items=[{"title": "Scrub of pool tank finished with 0 errors", "subtitle": "2026-09-04", "status": "warn"}], secondary=[{"label": "Open", "value": 1}])


ADAPTER = TruenasAdapter()


class _NoCurrentApi(Exception):
    """The WebSocket at ``/api/current`` was turned down before it opened."""

    def __init__(self, status: int) -> None:
        super().__init__(status)
        self.status = status


def _version(label: str) -> tuple[int, int]:
    """``25.10.1`` and ``TrueNAS-SCALE-24.10.2`` as (25, 10) and (24, 10).

    (0, 0) when there is no number in it. That reads as "older", so a TrueNAS
    that names itself in some way nobody has seen yet keeps its cards.
    """
    found = re.search(r"(\d+)\.(\d+)", label)
    return (int(found.group(1)), int(found.group(2))) if found else (0, 0)


def _rest_refused(label: str, address: str, turned_down: int | None) -> AdapterError:
    """Why the REST API is not used on this TrueNAS, and what to change.

    ⚠️ The way out depends on the address. Over http:// it is https://. Over
    https:// the address is right already and something in between does not
    pass the WebSocket on; telling that reader to change to https:// would
    send them looking in the wrong place.
    """
    which = f"TrueNAS {label}" if label else "This TrueNAS"
    why = (f"{which} has the current API and has deprecated the old REST API: TrueNAS 25.10 counts every call to it "
           "in an alert on the NAS, and TrueNAS 26 removes it. nexdeck does not use it there.")
    if address.startswith("https://"):
        status = f" with HTTP {turned_down}" if turned_down else ""
        return AdapterError(
            f"TrueNAS turned the WebSocket at /api/current down{status}. {why}", code="deprecated_api",
            hint="A reverse proxy in front of TrueNAS has to pass WebSockets on, that is the Upgrade and "
                 "Connection headers. Or point the URL straight at TrueNAS.",
        )
    return AdapterError(
        why, code="deprecated_api",
        hint="Change the URL to https://. nexdeck then uses the current API, and the key of a read-only "
             "administrator is enough. Over plain http TrueNAS would revoke the key, so that is never tried.",
    )


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


def _live(fields: Any) -> tuple[float, float, float, float] | None:
    """CPU in per cent, memory the services use, all memory, and the ZFS cache.

    The shape of 25.04 and 25.10 (``cpu.cpu.usage``,
    ``memory.physical_memory_*``, ``memory.arc_size``), read from the
    middleware's source. What the services use is what TrueNAS' own dashboard
    calls Services: all of it less what is free less the ZFS cache, which the
    kernel counts as taken but hands back when asked. Without that the card
    would read 90 per cent on every NAS that has been up for a day.
    """
    if not isinstance(fields, dict):
        return None
    cpu = ((fields.get("cpu") or {}).get("cpu") or {}).get("usage")
    memory = fields.get("memory") or {}
    total, free = memory.get("physical_memory_total"), memory.get("physical_memory_available")
    if not all(isinstance(value, (int, float)) for value in (cpu, total, free)) or not total:
        return None
    cache = memory.get("arc_size") if isinstance(memory.get("arc_size"), (int, float)) else 0
    used = max(0.0, float(total) - float(free) - float(cache))
    return round(float(cpu), 1), used, float(total), float(cache)


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
