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
    Status,
    Unreachable,
    WidgetData,
    WidgetType,
    ago,
    base_url,
    duration_short,
    guard_outbound,
    human_bytes,
    human_rate,
    join_parts,
    part_on,
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

#: How long an answer is kept, where a card's own refresh would ask too often.
#:
#: ⚠️ ``disk.temperatures`` sends a command to every disk: TrueNAS reads
#: ``temp1_input`` of the drivetemp module, and that goes to the drive each
#: time (its own comment in ``disk_class.py``, 25.10). TrueNAS keeps the value
#: five minutes itself; asking more often would only wake disks for nothing.
#:
#: ⚠️ ``update.status`` asks TrueNAS' update server on every call (it fetches
#: ``trains.json`` and the train's releases, 25.10 source), and so does
#: ``update.check_available`` on 25.04. Six hours is often enough to learn of
#: a release and rare enough not to be a load on anybody's server.
KEEP = {
    "network.general.summary": 300.0,
    "app.query": 120.0,
    "disk.query": 3600.0,
    "disk.temperatures": 300.0,
    "update.status": 21600.0,
    "update.check_available": 21600.0,
}

#: How long the update check may take before the system card goes on without it,
#: and how soon a check that never finished may be tried again; see ``_update``.
UPDATE_WAIT = 8.0
UPDATE_RETRY = 600.0

#: Methods a TrueNAS may not have, or not on this version. An error from one of
#: them is an empty answer; a card that reads several still shows the rest.
#: ``cloud_backup`` came with 24.10, and the Incus instances are gone from
#: some builds. A refused role is not caught here: that is ``auth_failed``.
OPTIONAL = {"cloud_backup.query", "virt.instance.query", "vm.query"}

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
    description = "Pools, disks, apps, interfaces, data protection, services and VMs, with load and alerts."
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
        WidgetType(kind="system", label="System", description="CPU, memory, uptime, open alerts and a waiting TrueNAS update.", renderer="stats", default_size=(4, 2), refresh_seconds=30, metrics=("cpu", "memory", "load"),
                   parts=(("update", "Update available"),)),
        WidgetType(kind="pools", label="Pools", description="Every pool with usage, health and its last scrub.", renderer="list", default_size=(3, 2), refresh_seconds=120),
        WidgetType(kind="alerts", label="Alerts", description="Open alerts by level.", renderer="list", default_size=(3, 2), refresh_seconds=60),
        WidgetType(kind="interfaces", label="Interfaces", description="Every network interface with its link, address and live traffic. Needs TrueNAS 25.04 or later.",
                   renderer="list", default_size=(3, 2), refresh_seconds=30, metrics=("down", "up"),
                   parts=(("address", "Address"), ("speed", "Link speed"), ("value", "Traffic"))),
        WidgetType(kind="apps", label="Apps", description="Every app with its state and whether an update is waiting. Needs TrueNAS 25.04 or later.",
                   renderer="list", default_size=(3, 3), refresh_seconds=120, parts=(("version", "Version"),)),
        WidgetType(kind="disks", label="Disks", description="Every disk with its temperature, model and pool. Needs TrueNAS 25.04 or later.",
                   renderer="list", default_size=(3, 3), refresh_seconds=300, metrics=("temperature",),
                   parts=(("model", "Model"), ("pool", "Pool"), ("size", "Size"))),
        WidgetType(kind="protection", label="Data protection", description="Snapshot, replication, cloud sync, rsync and cloud backup tasks with their last run. Needs TrueNAS 25.04 or later.",
                   renderer="list", default_size=(3, 3), refresh_seconds=120,
                   parts=(("snapshot", "Snapshots"), ("replication", "Replication"), ("cloudsync", "Cloud sync"), ("rsync", "Rsync"), ("cloud_backup", "Cloud backup"))),
        WidgetType(kind="services", label="Services", description="The services that start with TrueNAS, such as SMB, NFS and SSH, and whether they run. Needs TrueNAS 25.04 or later.",
                   renderer="list", default_size=(3, 2), refresh_seconds=60,
                   options=(Field("all_services", "Show services that are switched off", type="bool", default=False),)),
        WidgetType(kind="vms", label="VMs and containers", description="Virtual machines and containers with their state. Needs TrueNAS 25.04 or later.",
                   renderer="list", default_size=(3, 2), refresh_seconds=30),
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
        # ⚠️ The cards added for issue #49 read what only the current API has.
        # Without this a missing REST path was a KeyError, which says nothing.
        if lacking := [method for method in methods if method not in READS and method != REALTIME]:
            raise AdapterError(
                f"TrueNAS {label or '?'} has no {lacking[0]} on its old REST API.", code="needs_current_api",
                hint="This card needs TrueNAS 25.04 or later, reached over https://.",
            )
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

    async def _rpc(self, config: dict[str, Any], methods: list[str], params: dict[str, list[Any]] | None = None) -> dict[str, Any]:
        """Log in with the key and call each method once, on one connection.

        ``params`` holds the arguments of the methods that take any; the
        others are called without.
        """
        params = params or {}
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
                        # ⚠️ Taken and then ended: TrueNAS answers the
                        # subscription with an id and only afterwards says it
                        # stopped, with ``notify_unsubscribed`` (a key whose
                        # role may not read the statistics). Waiting for an
                        # event after that cost every refresh the whole wait.
                        ended = message.get("params") if message.get("method") == "notify_unsubscribed" else None
                        if isinstance(ended, dict) and str(ended.get("collection") or "").startswith(REALTIME):
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
                        if method == REALTIME:
                            answers[method] = await realtime(socket)
                            continue
                        try:
                            answers[method] = await call(socket, method, *params.get(method, []))
                        except AdapterError as error:
                            if method not in OPTIONAL or error.code != "rpc_error":
                                raise
                            answers[method] = None
                    return answers
                finally:
                    await socket.close()
        except InvalidStatus as error:
            raise _NoCurrentApi(error.response.status_code) from error
        except TimeoutError as error:
            raise Unreachable("TrueNAS did not answer in time.") from error
        except (OSError, WebSocketException) as error:
            raise Unreachable(f"TrueNAS could not be reached: {error.__class__.__name__}.") from error

    async def _read(self, config: dict[str, Any], ctx: Context, methods: list[str], cache: float = 10,
                    params: dict[str, list[Any]] | None = None) -> dict[str, Any]:
        """What the cards need, from whichever API this TrueNAS should be asked.

        ``cache`` is how long an answer may be reused; ``KEEP`` raises it for
        the methods that must not be asked more often. 0 asks everything anew.
        """
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
                fresh = await self._rpc(config, missing, params)
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
            ctx.cache[f"truenas:{method}"] = (now + (max(cache, KEEP.get(method, 0.0)) if cache else 0.0), value)
        return {**found, **fresh}

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        info = (await self._read(config, ctx, ["system.info"], cache=0))["system.info"] or {}
        return f"TrueNAS {info.get('version', '?')} on {info.get('hostname', '?')} answers."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "interfaces":
            read = await self._read(config, ctx, [REALTIME, "network.general.summary"])
            return _interfaces(read.get(REALTIME), read.get("network.general.summary"), options)
        if widget_kind == "apps":
            return _apps((await self._read(config, ctx, ["app.query"]))["app.query"], options)
        if widget_kind == "disks":
            return await self._disks(config, ctx, options)
        if widget_kind == "protection":
            wanted = [method for key, method in PROTECTION_READS if part_on(options, key)]
            return _protection(await self._read(config, ctx, wanted, cache=60) if wanted else {})
        if widget_kind == "services":
            return _services((await self._read(config, ctx, ["service.query"], cache=30))["service.query"], options)
        if widget_kind == "vms":
            read = await self._read(config, ctx, ["vm.query", "virt.instance.query"])
            return _machines(read["vm.query"], read["virt.instance.query"])
        if widget_kind == "system":
            read = await self._read(config, ctx, ["system.info", "alert.list", REALTIME])
            info = read["system.info"] or {}
            alerts = [a for a in read["alert.list"] or [] if not a.get("dismissed")]
            flagged = "bad" if any(a.get("level") in ("CRITICAL", "ERROR") for a in alerts) else ("warn" if alerts else "")
            uptime = {"label": "Uptime", "value": duration_short(info.get("uptime_seconds"))}
            counted = {"label": "Alerts", "value": len(alerts)}
            if part_on(options, "update") and (waiting := await self._update(config, ctx, info)):
                counted = [counted, {"label": "Update available", "value": waiting, "part": "update"}]
            else:
                counted = [counted]
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
                    secondary=[*chips, uptime, *counted],
                    metrics={"cpu": cpu, "memory": memory},
                )
            load = float((info.get("loadavg") or [0])[0])
            cores = int(info.get("cores") or 1)
            load_percent = round(100.0 * load / cores, 1)
            memory_total = float(info.get("physmem") or 0)
            return WidgetData(
                status=flagged or status_from_percent(load_percent),
                primary={"label": "Load", "value": load_percent, "unit": "%"},
                secondary=[{"label": "Memory", "value": human_bytes(memory_total)}, uptime, *counted],
                metrics={"load": load_percent},
            )
        if widget_kind == "pools":
            items = []
            for pool in (await self._read(config, ctx, ["pool.query"], cache=60))["pool.query"] or []:
                used = percent(pool.get("allocated"), pool.get("size"))
                scan, scan_errors = _scan(pool.get("scan"))
                items.append({
                    "title": pool.get("name", "?"),
                    "subtitle": " · ".join(part for part in (f"{human_bytes(pool.get('allocated'))} of {human_bytes(pool.get('size'))}", str(pool.get("status", "?")), scan) if part),
                    "progress": used, "value": percent_text(used),
                    # A pool whose size did not come is not a healthy pool.
                    "status": "unknown" if used is None else ("ok" if pool.get("healthy") and used < 90 and not scan_errors else "warn"),
                })
            return WidgetData(items=items)
        alerts = [a for a in (await self._read(config, ctx, ["alert.list"]))["alert.list"] or [] if not a.get("dismissed")]
        items = [{"title": str(a.get("formatted") or a.get("text", "?"))[:120], "subtitle": _day(a.get("datetime")), "status": "bad" if a.get("level") in ("CRITICAL", "ERROR") else "warn"} for a in alerts]
        return WidgetData(status="bad" if any(i["status"] == "bad" for i in items) else ("warn" if items else "ok"), items=items or [], secondary=[{"label": "Open", "value": len(items)}])

    async def _update(self, config: dict[str, Any], ctx: Context, info: dict[str, Any]) -> str:
        """The TrueNAS release waiting to be installed, "Reboot required", or "".

        25.10 has ``update.status``; 25.04 has ``update.check_available``,
        with the same role. Both ask TrueNAS' update server, see ``KEEP``.

        ⚠️ Never a reason for the system card to fail or to wait. A NAS without
        internet answers with an error, or only after its own 15 seconds when
        the traffic is dropped, and its CPU is still worth showing. So the
        question gets ``UPDATE_WAIT``, a failure is kept as long as an answer
        would be, and the last answer stays on the card meanwhile: a chip that
        vanished for a failed check and came back would be told as news.

        ⚠️ The mark is set before asking. Two system cards starting together,
        or a fetch cancelled half-way (the settings preview gives up after 20
        seconds), would otherwise each send TrueNAS to its server again.

        ⚠️ A reboot ends what was said before it. An answer kept for six hours
        would show "Reboot required" all morning after the reboot, and the
        release just installed as still waiting; so a new boot drops it, and a
        release equal to the running one is not shown.
        """
        now = time.monotonic()
        booted = time.time() - _number(info.get("uptime_seconds"))
        known = ctx.cache.get("truenas:update-boot")
        if known is not None and abs(known - booted) > 120:
            for key in ("truenas:update.status", "truenas:update.check_available", "truenas:update-failed", "truenas:update-last"):
                ctx.cache.pop(key, None)
        ctx.cache["truenas:update-boot"] = booted
        last = str(ctx.cache.get("truenas:update-last") or "")
        method = "update.status" if _version(str(info.get("version") or "")) >= (25, 10) else "update.check_available"
        hit = ctx.cache.get(f"truenas:{method}")
        if not (hit and hit[0] > now):
            failed = ctx.cache.get("truenas:update-failed")
            if failed and failed > now:
                return _unless_installed(last, info)
            ctx.cache["truenas:update-failed"] = now + UPDATE_RETRY
        try:
            async with asyncio.timeout(UPDATE_WAIT):
                answer = (await self._read(config, ctx, [method]))[method]
        except (AdapterError, TimeoutError):
            ctx.cache["truenas:update-failed"] = now + KEEP[method]
            return _unless_installed(last, info)
        ctx.cache.pop("truenas:update-failed", None)
        waiting = _waiting_update(answer)
        ctx.cache["truenas:update-last"] = waiting
        return _unless_installed(waiting, info)

    async def _disks(self, config: dict[str, Any], ctx: Context, options: dict[str, Any]) -> WidgetData:
        """Every disk with its temperature; ``KEEP`` says why only every five minutes.

        ⚠️ ``disk.temperatures`` changed its arguments with 25.10. Before, the
        second is a dict, and ``powermode`` STANDBY has smartctl leave a disk
        alone that sleeps (``-n standby``). 25.10 reads the kernel's sensor and
        takes only whether to send the critical temperature along. Sending one
        version's arguments to the other is refused, so the version decides.
        """
        read = await self._read(config, ctx, ["system.info", "disk.query"], params={"disk.query": [[], {"extra": {"pools": True}}]})
        newer = _version(str((read["system.info"] or {}).get("version") or "")) >= (25, 10)
        arguments = [[], True] if newer else [[], {"powermode": "STANDBY"}]
        temperatures = (await self._read(config, ctx, ["disk.temperatures"], params={"disk.temperatures": arguments}))["disk.temperatures"]
        return _disk_rows(read["disk.query"], temperatures, options)

    #: Above this, a pool has stopped being somebody's problem for later.
    FULL_PERCENT = 90.0

    def detect(self, widget_kind: str, before: WidgetData | None, after: WidgetData,
               options: dict[str, Any]) -> list[Detected]:
        """A pool that crossed into the last tenth of itself, and what the newer cards notice.

        ⚠️ Only on the crossing. A pool that sits at 94 per cent for a month
        is not news every five minutes; it became news once.

        ⚠️ A failed task and a waiting update are told only when they appear
        between two fetches, never on the first. A NAS with twenty apps behind
        their releases would otherwise send twenty messages the moment the
        card is put on a board, about nothing that just happened.
        """
        if widget_kind == "disks":
            return [Detected(event="disk_hot", title=f"{item.get('title')} is at {item.get('value')}", body=str(item.get("subtitle") or ""),
                             level=item.get("status", "warn"), key=f"disk_hot:{item.get('title')}:{item.get('status')}", quiet_seconds=86400)
                    for item in _newly(before, after, lambda item: item.get("status") in ("warn", "bad"), first=True,
                                       # From yellow to red is news of its own.
                                       same=lambda old, new: old.get("status") == new.get("status") or new.get("status") == "warn")][:5]
        if widget_kind == "protection":
            return [Detected(event="backup_failed", title=f"{item.get('title')} failed", body=str(item.get("subtitle") or ""),
                             level="bad", key=f"backup_failed:{item.get('id')}", quiet_seconds=3600)
                    for item in _newly(before, after, lambda item: item.get("status") == "bad")][:5]
        if widget_kind == "apps":
            return [Detected(event="software_update", title=f"{item.get('title')}: update to {item['update']}" if item.get("update") != "image" else f"{item.get('title')}: new image",
                             level="ok", key=f"software_update:app:{item.get('title')}:{item.get('update')}", quiet_seconds=7 * 86400)
                    for item in _newly(before, after, lambda item: bool(item.get("update")), same=lambda a, b: a.get("update") == b.get("update"))][:5]
        if widget_kind == "system":
            now, was = _chip(after, "update"), _chip(before, "update") if before and not before.error else None
            if not now or before is None or before.error or now == was or now == "Reboot required":
                return []
            return [Detected(event="software_update", title=f"TrueNAS {now} is available", level="ok",
                             key=f"software_update:truenas:{now}", quiet_seconds=7 * 86400)]
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
            return WidgetData(items=[{"title": "tank", "subtitle": "41.2 TB of 58.0 TB · ONLINE · Scrub 6 d ago", "progress": 71.0, "value": "71%", "status": "ok"}, {"title": "fast", "subtitle": "1.2 TB of 1.8 TB · ONLINE · Scrub 2 d ago", "progress": 66.6, "value": "67%", "status": "ok"}])
        if widget_kind == "interfaces":
            down, up = fake.walk("truenas-down", tick, 2, 60) * 1_000_000, fake.walk("truenas-up", tick, 1, 20) * 1_000_000
            return _interfaces({"interfaces": {
                "enp1s0": {"link_state": "LINK_STATE_UP", "speed": 10000, "received_bytes_rate": down, "sent_bytes_rate": up},
                "enp2s0": {"link_state": "LINK_STATE_DOWN", "speed": 0, "received_bytes_rate": 0, "sent_bytes_rate": 0},
                "br0": {"link_state": "LINK_STATE_UP", "speed": 10000, "received_bytes_rate": down * 0.1, "sent_bytes_rate": up * 0.2},
            }}, {"ips": {"enp1s0": {"IPV4": ["192.168.1.20/24"]}, "br0": {"IPV4": ["192.168.1.21/24"]}}}, options)
        if widget_kind == "apps":
            return _apps([
                {"name": "jellyfin", "state": "RUNNING", "human_version": "10.10.7_1.2.3", "upgrade_available": True, "latest_version": "1.2.4", "portals": {"Web UI": "http://192.168.1.20:30013/"}},
                {"name": "immich", "state": "RUNNING", "human_version": "v1.132.3_1.6.1", "upgrade_available": False},
                {"name": "nextcloud", "state": "RUNNING", "human_version": "31.0.4_2.1.0", "image_updates_available": True},
                {"name": "syncthing", "state": "STOPPED", "human_version": "1.29.6_1.1.9"},
            ], options)
        if widget_kind == "disks":
            warm = fake.walk("truenas-disk", tick, 36, 44)
            return _disk_rows([
                {"name": "sda", "model": "WDC WD140EFGX", "pool": "tank", "size": 14_000_519_643_136, "type": "HDD"},
                {"name": "sdb", "model": "WDC WD140EFGX", "pool": "tank", "size": 14_000_519_643_136, "type": "HDD"},
                {"name": "sdc", "model": "ST14000NM001G", "pool": "tank", "size": 14_000_519_643_136, "type": "HDD"},
                {"name": "nvme0n1", "model": "Samsung SSD 990 PRO 2TB", "pool": "fast", "size": 2_000_398_934_016, "type": "SSD"},
            ], {"sda": [warm, 65.0], "sdb": [warm + 1, 65.0], "sdc": [warm + 9, 60.0], "nvme0n1": [warm + 8, 84.85]}, options)
        if widget_kind == "protection":
            hour = time.time() - 3600
            return _protection({
                "pool.snapshottask.query": [{"id": 1, "dataset": "tank/photos", "enabled": True, "state": {"state": "FINISHED", "datetime": {"$date": hour * 1000}}}],
                "replication.query": [{"id": 1, "name": "tank to backup-nas", "enabled": True, "state": {"state": "FINISHED", "datetime": {"$date": (hour - 3600) * 1000}}}],
                "cloudsync.query": [{"id": 1, "description": "Photos to B2", "enabled": True, "job": {"state": "FAILED", "time_finished": {"$date": (hour - 7200) * 1000}, "error": "Upload quota exceeded."}}],
                "rsynctask.query": [{"id": 1, "desc": "Documents to the office", "enabled": False, "job": None}],
            })
        if widget_kind == "services":
            return _services([{"service": "cifs", "enable": True, "state": "RUNNING"}, {"service": "nfs", "enable": True, "state": "RUNNING"},
                              {"service": "ssh", "enable": True, "state": "RUNNING"}, {"service": "ups", "enable": False, "state": "STOPPED"}], options)
        if widget_kind == "vms":
            return _machines([{"name": "homeassistant", "vcpus": 2, "cores": 1, "threads": 1, "memory": 4096, "status": {"state": "RUNNING"}},
                              {"name": "windows", "vcpus": 4, "cores": 1, "threads": 1, "memory": 8192, "status": {"state": "STOPPED"}}],
                             [{"name": "pihole", "type": "CONTAINER", "status": "RUNNING", "cpu": "1", "memory": 536_870_912}])
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


# -- the cards added for issue #49 -------------------------------------------

#: What the Data protection card reads, each behind its own tick box.
PROTECTION_READS = (
    ("snapshot", "pool.snapshottask.query"),
    ("replication", "replication.query"),
    ("cloudsync", "cloudsync.query"),
    ("rsync", "rsynctask.query"),
    ("cloud_backup", "cloud_backup.query"),
)
TASK_KINDS = {
    "pool.snapshottask.query": "Snapshots", "replication.query": "Replication", "cloudsync.query": "Cloud sync",
    "rsynctask.query": "Rsync", "cloud_backup.query": "Cloud backup",
}
#: The state zettarepl keeps for snapshot and replication tasks.
ZETTAREPL_STATES = {
    "FINISHED": ("ok", "Finished"), "RUNNING": ("ok", "Running"), "WAITING": ("ok", "Waiting"),
    "PENDING": ("unknown", "Pending"), "HOLD": ("warn", "On hold"), "ERROR": ("bad", "Failed"),
}
#: The state of the last job of a cloud sync, rsync or cloud backup task.
JOB_STATES = {
    "SUCCESS": ("ok", "Finished"), "RUNNING": ("ok", "Running"), "WAITING": ("ok", "Waiting"),
    "FAILED": ("bad", "Failed"), "ABORTED": ("warn", "Aborted"),
}
APP_STATES = {"RUNNING": "Running", "STOPPED": "Stopped", "CRASHED": "Crashed", "DEPLOYING": "Deploying", "STOPPING": "Stopping"}
#: What TrueNAS' own Services page calls them; ``service.query`` has the old names.
SERVICE_NAMES = {
    "cifs": "SMB", "nfs": "NFS", "ssh": "SSH", "ftp": "FTP", "iscsitarget": "iSCSI", "nvmet": "NVMe-oF",
    "snmp": "SNMP", "ups": "UPS", "smartd": "S.M.A.R.T.",
}
#: A VM in ``vm.query`` and an instance in ``virt.instance.query``, as a colour and a word.
MACHINE_STATES = {
    "RUNNING": ("ok", "Running"), "STARTING": ("ok", "Starting"), "STOPPING": ("ok", "Stopping"),
    "STOPPED": ("unknown", "Stopped"), "SUSPENDED": ("warn", "Paused"), "FROZEN": ("warn", "Paused"),
    "FREEZING": ("warn", "Paused"), "THAWED": ("ok", "Running"), "ERROR": ("bad", "Error"),
}
#: Which rows come first: the ones somebody has to look at.
ROW_ORDER = {"bad": 0, "warn": 1, "ok": 2, "unknown": 3}


def _number(value: Any) -> float:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else 0.0


def _overall(items: list[dict[str, Any]]) -> Status:
    states = {item.get("status") for item in items}
    return "bad" if "bad" in states else ("warn" if "warn" in states else "ok")


def _sorted(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(items, key=lambda item: (ROW_ORDER.get(str(item.get("status")), 3), str(item.get("title") or "").lower()))


def _when(value: Any) -> float | None:
    """A moment from TrueNAS as seconds since the epoch, or None.

    The current API writes datetimes as ``{"$date": milliseconds}``; the
    alerts do (measured on 25.10.7). Plain numbers and ISO text are read too,
    because a job's ``time_finished`` has not been seen live yet.
    """
    if isinstance(value, dict):
        value = value.get("$date")
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value) / 1000 if value > 1e11 else float(value)
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return (moment if moment.tzinfo else moment.replace(tzinfo=UTC)).timestamp()


def _scan(scan: Any) -> tuple[str, int]:
    """A pool's last scrub or resilver for its subtitle, and the errors it found.

    A running one has a share, a finished one an end time. Errors make the
    pool's row yellow: a scrub that had to repair something is the earliest
    sign of a disk on its way out.
    """
    if not isinstance(scan, dict) or not scan.get("function"):
        return "", 0
    what = "Resilver" if str(scan["function"]).upper() == "RESILVER" else "Scrub"
    errors = int(_number(scan.get("errors")))
    state = str(scan.get("state") or "").upper()
    if state == "SCANNING":
        share = scan.get("percentage")
        text = f"{what} {_number(share):.0f}%" if isinstance(share, int | float) else what
    elif state == "CANCELED":
        text = f"{what} canceled"
    else:
        age = ago(_when(scan.get("end_time")))
        text = f"{what} {age} ago" if age else what
    return (f"{text}, {errors} errors" if errors else text), errors


def _waiting_update(answer: Any) -> str:
    """What ``update.status`` (25.10) or ``update.check_available`` (25.04) says is waiting.

    ``update.status`` answers ``{"code": "NORMAL", "status": {"new_version":
    {"version": …}}}``, and ``code`` ERROR with ``EREBOOTREQUIRED`` once an
    update was installed and waits for the reboot. ``check_available`` says
    ``AVAILABLE`` with ``version``, or ``REBOOT_REQUIRED``.
    """
    if not isinstance(answer, dict):
        return ""
    if "code" in answer:
        error = answer.get("error") if isinstance(answer.get("error"), dict) else {}
        if answer.get("code") == "ERROR" and error.get("errname") == "EREBOOTREQUIRED":
            return "Reboot required"
        if answer.get("code") != "NORMAL":
            return ""
        status = answer.get("status") if isinstance(answer.get("status"), dict) else {}
        new = status.get("new_version") if isinstance(status.get("new_version"), dict) else {}
        return str(new.get("version") or "")
    if answer.get("status") == "REBOOT_REQUIRED":
        return "Reboot required"
    return str(answer.get("version") or "") if answer.get("status") == "AVAILABLE" else ""


def _unless_installed(waiting: str, info: dict[str, Any]) -> str:
    """The waiting release, unless it is the one running now.

    ``system.info`` may write ``TrueNAS-25.10.8`` where the update check
    writes ``25.10.8``, so both are compared without the product name.
    """
    def bare(label: Any) -> str:
        return re.sub(r"^TrueNAS-(SCALE-)?", "", str(label or "")).strip()

    if waiting and waiting != "Reboot required" and bare(waiting) == bare(info.get("version")):
        return ""
    return waiting


def _interfaces(realtime: Any, summary: Any, options: dict[str, Any]) -> WidgetData:
    """Every interface from the realtime event, with its address from ``network.general.summary``.

    ⚠️ The traffic is the event's, not ``reporting.netdata_get_data``: the
    event the system card subscribes to anyway carries every interface's rate
    in bytes per second (``get_interface_stats``, 25.04 and 25.10), so the
    card costs TrueNAS nothing new. The link speed is in Mbit/s there, and the
    names are those of ``interface.query``, so no container's veth turns up.

    A link that is down is grey, not red. A NAS with four ports and one cable
    is not broken.
    """
    interfaces = realtime.get("interfaces") if isinstance(realtime, dict) else None
    if not isinstance(interfaces, dict):
        raise AdapterError("TrueNAS sent no live figures for its interfaces.", code="no_realtime",
                           hint="The key's user needs the Read-Only Administrator role, which may read the reporting.")
    if not interfaces:
        # ⚠️ Not measured. The one event on record, from a test VM on
        # 25.10.7, had an empty ``interfaces``; whether that VM had none
        # configured or the event leaves them out is open. An empty card would
        # hide which, so it says so instead.
        raise AdapterError("TrueNAS listed no interfaces in its live figures.", code="no_interfaces",
                           hint="TrueNAS takes them from Network > Interfaces; one set up there should appear here.")
    addresses =summary.get("ips") if isinstance(summary, dict) and isinstance(summary.get("ips"), dict) else {}
    items: list[dict[str, Any]] = []
    down = up = 0.0
    for name in sorted(interfaces):
        stats = interfaces[name] if isinstance(interfaces[name], dict) else {}
        linked = stats.get("link_state") == "LINK_STATE_UP"
        received, sent = _number(stats.get("received_bytes_rate")), _number(stats.get("sent_bytes_rate"))
        down, up = down + received, up + sent
        ips = addresses.get(name) if isinstance(addresses.get(name), dict) else {}
        first = next(iter([*(ips.get("IPV4") or []), *(ips.get("IPV6") or [])]), "")
        speed = _number(stats.get("speed"))
        items.append({
            "title": name,
            "subtitle": join_parts(options, ("address", first), ("speed", f"{speed:.0f} Mbit/s" if linked and speed else ""),
                                   ("link", "" if linked else "No link")),
            "value": f"↓ {human_rate(received)} ↑ {human_rate(sent)}" if linked else "",
            "status": "ok" if linked else "unknown",
        })
    return WidgetData(items=items, metrics={"down": down, "up": up},
                      secondary=[{"label": "Download", "metric": "down", "value": human_rate(down)},
                                 {"label": "Upload", "metric": "up", "value": human_rate(up)}])


def _portal(portals: Any) -> str:
    """The first web address an app offers, for the link on its row."""
    if isinstance(portals, dict):
        for address in portals.values():
            if isinstance(address, str) and address.startswith(("http://", "https://")):
                return address
    return ""


def _apps(apps: Any, options: dict[str, Any]) -> WidgetData:
    """Every app, the ones that need somebody first: crashed, then with an update.

    Two kinds of update, both of which TrueNAS' Apps page marks: a newer
    version from the catalog (``upgrade_available`` with ``latest_version``)
    and newer images for the same version (``image_updates_available``, the
    only kind a custom app ever has). ``update`` on the row says which, for
    ``detect``; the renderer ignores it.
    """
    items: list[dict[str, Any]] = []
    for app in apps or []:
        if not isinstance(app, dict):
            continue
        state = str(app.get("state") or "").upper()
        newer = str(app.get("latest_version") or "") if app.get("upgrade_available") else ""
        update = newer or ("image" if app.get("image_updates_available") else "")
        row: dict[str, Any] = {
            "title": str(app.get("name") or app.get("id") or "?"),
            "subtitle": join_parts(options, ("version", app.get("human_version") or app.get("version")), ("state", APP_STATES.get(state, state.title()))),
            "value": "Update available" if update else "",
            "status": "bad" if state == "CRASHED" else ("warn" if update else ("ok" if state == "RUNNING" else "unknown")),
            "update": update,
        }
        if link := _portal(app.get("portals")):
            row["url"] = link
        items.append(row)
    running = sum(1 for app in apps or [] if isinstance(app, dict) and str(app.get("state") or "").upper() == "RUNNING")
    waiting = sum(1 for item in items if item["update"])
    return WidgetData(status=_overall(items), items=_sorted(items),
                      secondary=[{"label": "Running", "value": running}, {"label": "Updates", "value": waiting}])


def _disk_rows(disks: Any, temperatures: Any, options: dict[str, Any]) -> WidgetData:
    """Every disk with its temperature.

    25.10 sends ``[temperature, critical]`` per disk when asked for the
    thresholds, 25.04 the temperature alone, and ``None`` for a disk that did
    not say, which on 25.04 includes one that sleeps. The critical value is
    the disk's own (``temp1_crit``) and lowers the limits, never raises them.

    The limits without one: 50 and 60 °C for a spinning disk, where its
    failure rate starts to climb, 70 and 80 for flash, which throttles there.
    """
    readings = temperatures if isinstance(temperatures, dict) else {}
    items: list[dict[str, Any]] = []
    hottest: float | None = None
    named = sorted((one for one in disks or [] if isinstance(one, dict)), key=lambda one: (len(str(one.get("name") or "")), str(one.get("name") or "")))
    for disk in named:
        name = str(disk.get("name") or "?")
        reading = readings.get(name)
        temp, crit = (reading[0], reading[1]) if isinstance(reading, list | tuple) and len(reading) >= 2 else (reading, None)
        temp = float(temp) if isinstance(temp, int | float) and not isinstance(temp, bool) else None
        solid = name.startswith("nvme") or str(disk.get("type") or "").upper() == "SSD"
        warn, bad = (70.0, 80.0) if solid else (50.0, 60.0)
        if isinstance(crit, int | float) and not isinstance(crit, bool) and crit > 0:
            bad = min(bad, float(crit))
            warn = min(warn, bad - 5)
        items.append({
            "title": name,
            "subtitle": join_parts(options, ("model", disk.get("model")), ("pool", disk.get("pool")), ("size", human_bytes(disk["size"]) if disk.get("size") else "")),
            "value": f"{temp:.0f} °C" if temp is not None else "",
            "status": "unknown" if temp is None else ("bad" if temp >= bad else ("warn" if temp >= warn else "ok")),
        })
        if temp is not None:
            hottest = temp if hottest is None else max(hottest, temp)
    return WidgetData(status=_overall(items), items=items, metrics={"temperature": hottest} if hottest is not None else {})


def _task_row(method: str, task: dict[str, Any]) -> dict[str, Any]:
    """One task of the Data protection card.

    Snapshot and replication tasks carry zettarepl's ``state`` (a dict, or a
    plain error text when zettarepl itself failed); the others carry their
    last ``job``. A failed row says why in place of the word "Failed": the
    red dot says that already, and the reason is what somebody needs.
    """
    if method == "pool.snapshottask.query":
        title = str(task.get("dataset") or "?")
    elif method == "replication.query":
        title = str(task.get("name") or "?")
    else:
        title = str(task.get("description") or task.get("desc") or task.get("path") or "?")
    state, job = task.get("state"), task.get("job")
    error: Any = None
    moment: float | None = None
    status: Status
    if isinstance(state, str) and state:
        status, word, error = "bad", "Failed", state
    elif isinstance(state, dict) and state.get("state"):
        status, word = ZETTAREPL_STATES.get(str(state["state"]).upper(), ("unknown", str(state["state"]).title()))
        moment, error = _when(state.get("datetime")), state.get("error")
    elif isinstance(job, dict) and job.get("state"):
        status, word = JOB_STATES.get(str(job["state"]).upper(), ("unknown", str(job["state"]).title()))
        moment, error = _when(job.get("time_finished") or job.get("time_started")), job.get("error")
    else:
        status, word = "unknown", "Never ran"
    if task.get("locked"):
        status, word = "warn", "Locked"
    if task.get("enabled") is False:
        status, word = "unknown", "Off"
    reason = str(error or "").strip()[:200] if status == "bad" else ""
    return {"id": f"{method}:{task.get('id')}", "title": title, "subtitle": f"{TASK_KINDS[method]} · {reason or word}",
            "value": ago(moment), "status": status}


def _protection(read: dict[str, Any]) -> WidgetData:
    items = [_task_row(method, task) for _key, method in PROTECTION_READS for task in read.get(method) or [] if isinstance(task, dict)]
    failed = sum(1 for item in items if item["status"] == "bad")
    return WidgetData(status=_overall(items), items=_sorted(items),
                      secondary=[{"label": "Tasks", "value": len(items)}, {"label": "Failed", "value": failed}])


def _services(services: Any, options: dict[str, Any]) -> WidgetData:
    """The services meant to start with TrueNAS, and whether they run.

    ``enable`` is "start on boot". One that should start and is stopped is
    red; one that runs without being set to start is shown as well, since it
    runs. The rest only with the option, or the card would list eight
    services most people never switched on.
    """
    every = bool(options.get("all_services"))
    items: list[dict[str, Any]] = []
    for service in services or []:
        if not isinstance(service, dict):
            continue
        state = str(service.get("state") or "").upper()
        running = state == "RUNNING"
        if not (every or service.get("enable") or running):
            continue
        name = str(service.get("service") or "?")
        items.append({
            "title": SERVICE_NAMES.get(name, name.upper()),
            "value": "Running" if running else ("Stopped" if state == "STOPPED" else "Unknown"),
            "status": "ok" if running else ("bad" if service.get("enable") and state == "STOPPED" else "unknown"),
        })
    return WidgetData(status=_overall(items), items=_sorted(items))


def _machines(vms: Any, instances: Any) -> WidgetData:
    """Virtual machines from ``vm.query`` and containers from ``virt.instance.query``.

    25.10 makes VMs with ``vm.*`` again and keeps Incus for containers; 25.04
    could make VMs with Incus too. So both are read, and an Incus VM with the
    name of a ``vm.query`` one is the same machine, counted once. ``vm.query``
    gives memory in MiB, Incus in bytes.
    """
    if vms is None and instances is None:
        raise AdapterError("TrueNAS answered neither vm.query nor virt.instance.query.", code="rpc_error",
                           hint="Virtual machines and containers need TrueNAS 25.04 or later.")
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for vm in vms or []:
        if not isinstance(vm, dict):
            continue
        name = str(vm.get("name") or "?")
        seen.add(name)
        status = vm.get("status") if isinstance(vm.get("status"), dict) else {}
        cpus = int(_number(vm.get("vcpus")) or 1) * int(_number(vm.get("cores")) or 1) * int(_number(vm.get("threads")) or 1)
        memory = _number(vm.get("memory")) * 1024 * 1024
        items.append(_machine_row(name, "VM", f"{cpus} vCPU", human_bytes(memory) if memory else "", str(status.get("state") or "").upper()))
    for instance in instances or []:
        if not isinstance(instance, dict):
            continue
        name = str(instance.get("name") or "?")
        kind = "VM" if str(instance.get("type") or "").upper() == "VM" else "Container"
        if kind == "VM" and name in seen:
            continue
        # Incus takes a count or a set of cores ("0-3"); only a count is a number of vCPUs.
        cpu = str(instance.get("cpu") or "")
        memory = _number(instance.get("memory"))
        items.append(_machine_row(name, kind, (f"{cpu} vCPU" if cpu.isdigit() else f"CPU {cpu}") if cpu else "", human_bytes(memory) if memory else "", str(instance.get("status") or "").upper()))
    running = sum(1 for item in items if item["value"] == "Running")
    return WidgetData(status=_overall(items), items=_sorted(items), secondary=[{"label": "Running", "value": running}])


def _machine_row(name: str, kind: str, cpu: str, memory: str, state: str) -> dict[str, Any]:
    status, word = MACHINE_STATES.get(state, ("unknown", state.title() or "Unknown"))
    return {"title": name, "subtitle": " · ".join(part for part in (kind, cpu, memory) if part), "value": word, "status": status}


def _newly(before: WidgetData | None, after: WidgetData, test: Any, *, first: bool = False, same: Any = None) -> list[dict[str, Any]]:
    """The rows of ``after`` for which ``test`` holds and did not before.

    Matched by ``id``, else by title. ``same`` says whether a row that held
    before is still the same news: an app whose waiting update moved on to a
    newer version is news again. ``first`` lets a card speak that has nothing
    before it; see ``detect``.
    """
    if after.error:
        return []
    # ⚠️ A card in error keeps its last good rows (``collector._failure``).
    # Compared against those, a task that failed while TrueNAS rebooted is
    # still news afterwards; treated as "nothing before", it was lost.
    if before is None or (before.error and not before.items):
        return [item for item in after.items if test(item)] if first else []

    def key(item: dict[str, Any]) -> str:
        return str(item.get("id") or item.get("title") or "")

    earlier = {key(item): item for item in before.items}
    found = []
    for item in after.items:
        if not test(item):
            continue
        old = earlier.get(key(item))
        if old is not None and test(old) and (same is None or same(old, item)):
            continue
        found.append(item)
    return found


def _chip(data: WidgetData | None, part: str) -> str | None:
    """The value of the row tagged with ``part``, or None."""
    for row in (data.secondary if data else []):
        if row.get("part") == part:
            return str(row.get("value"))
    return None
