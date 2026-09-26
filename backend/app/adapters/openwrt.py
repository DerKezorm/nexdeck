"""OpenWrt: the router's own numbers, its interfaces and the devices it handed an address to.

Measured on 26.09.2026 against OpenWrt 25.12.5 with LuCI, in a container
from the project's own x86-64 image, with an interface up, a WAN whose
device does not exist, one switched off, and three invented DHCP leases.
The answers to a refusal and a stale session were checked on 24.10.8 too.

⚠️ The way in is the one LuCI takes: JSON-RPC on ``/ubus`` (uhttpd with its
ubus module, which LuCI brings along). ``session.login`` hands out a session
that runs out after five idle minutes; every call carries it as its first
parameter.

⚠️ A wrong password is a perfectly good answer, ``result: [6]``. A call the
session may not make is JSON-RPC error -32002 "Access denied", and so is a
call with a session that has run out; the adapter signs in once more before
it believes a refusal. Both versions answered alike.

⚠️ The load averages come as fixed-point numbers, 65536 for 1.0: a quiet
router read 10816. Memory has ``free`` and ``available``; the page cache
counts as used in ``free``, so the card goes by ``available``.

⚠️ A lease handed out for good has ``expires: false``, one that has run out
``expires: 0``; the card says so instead of "0s".

⚠️ Without the right to change the network the interface dump never
answers: in a container without NET_ADMIN, netifd hung and so did
``network.interface dump``. On a router that cannot happen, but the card
waits fifteen seconds and not forever.

⚠️ A user that is not root is an rpcd login in ``/etc/config/rpcd`` with
the read groups ``luci-mod-status-index``, ``luci-mod-status-index-dhcp`` and
``luci-base-network-status``. The last one also lets it read the wireless
configuration, keys included; that is how LuCI groups it.
"""

from __future__ import annotations

from typing import Any

from . import demo as fake
from .base import (
    Adapter,
    AdapterError,
    AuthFailed,
    Context,
    Field,
    WidgetData,
    WidgetType,
    base_url,
    duration_short,
    human_bytes,
    part_on,
)

SESSION = "openwrt_session"
NO_SESSION = "0" * 32
LOAD_SCALE = 65536
ACCESS_DENIED = -32002
READ_HINT = ("Sign in as root, or give an rpcd login the read groups luci-mod-status-index, "
             "luci-mod-status-index-dhcp and luci-base-network-status.")
PROTO = {"static": "Static address", "dhcp": "DHCP client", "dhcpv6": "DHCPv6 client", "pppoe": "PPPoE", "wireguard": "WireGuard",
         "none": "Unmanaged", "6in4": "IPv6 tunnel", "qmi": "Mobile", "modemmanager": "Mobile"}
ERROR_WORD = {"NO_DEVICE": "No device", "DEVICE_CLAIM_FAILED": "Device busy", "MISSING_ADDRESS": "No address",
              "NO_ADDRESS": "No address", "PROTO_FAILED": "Connection failed", "SETUP_FAILED": "Setup failed"}
ORDER = {"bad": 0, "warn": 1, "unknown": 2, "ok": 3}


class Refused(Exception):
    """A call turned away: rights missing, or a session that ran out."""


class OpenWrtAdapter(Adapter):
    kind = "openwrt"
    label = "OpenWrt"
    category = "network"
    description = "The router's memory, load and uptime, its interfaces with their addresses and traffic, and the devices it gave an address to."
    icon = "openwrt"
    beta = False
    docs_url = "https://openwrt.org/docs/techref/ubus"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://192.168.1.1"),
        Field("username", "Username", default="root",
              help="root, or an rpcd login with the read groups luci-mod-status-index, luci-mod-status-index-dhcp and luci-base-network-status."),
        Field("password", "Password", type="password", secret=True),
        Field("insecure", "Ignore TLS errors", type="bool", default=False, help="LuCI over HTTPS comes with a certificate of its own making."),
    )
    widgets = (
        WidgetType(kind="system", label="Router",
                   description="Memory in use, load, uptime, firmware and the space left for packages.",
                   renderer="value", default_size=(3, 2), refresh_seconds=60, metrics=("memory_percent", "load"),
                   parts=(("load", "Load"), ("uptime", "Uptime"), ("firmware", "Firmware"), ("storage", "Storage"))),
        WidgetType(kind="interfaces", label="Interfaces",
                   description="Every interface with whether it is up, its address, how long it has been up and its traffic.",
                   renderer="list", default_size=(3, 3), refresh_seconds=60,
                   parts=(("address", "Address"), ("uptime", "Uptime"), ("traffic", "Traffic"))),
        WidgetType(kind="leases", label="DHCP devices",
                   description="The devices the router gave an address to, with how long it is theirs.",
                   renderer="list", default_size=(3, 3), refresh_seconds=120, metrics=("leases",)),
    )

    # -- talking to the router -----------------------------------------------

    async def _rpc(self, config: dict[str, Any], ctx: Context, session: str, target: str, method: str,
                   arguments: dict[str, Any] | None = None) -> Any:
        response = await ctx.request("POST", f"{base_url(config)}/ubus",
                                     json_body={"jsonrpc": "2.0", "id": 1, "method": "call", "params": [session, target, method, arguments or {}]},
                                     verify=not config.get("insecure"), timeout=15.0, auth_errors=False)
        if response.status_code == 404:
            raise AdapterError("The router has no ubus address.", code="no_ubus",
                               hint="LuCI brings it along; without LuCI install uhttpd-mod-ubus.")
        try:
            answer = response.json()
        except ValueError as error:
            raise AdapterError("This address answers with something other than OpenWrt.", code="not_openwrt",
                               hint="Enter the address LuCI is reached at.") from error
        if not isinstance(answer, dict):
            raise AdapterError("This address answers, but not the way OpenWrt does.", code="not_openwrt")
        error = answer.get("error")
        if isinstance(error, dict):
            if error.get("code") == ACCESS_DENIED:
                raise Refused
            raise AdapterError(f"OpenWrt refused: {error.get('message') or error.get('code')}", code="http_error")
        result = answer.get("result")
        if not isinstance(result, list) or not result:
            raise AdapterError("This address answers, but not the way OpenWrt does.", code="not_openwrt")
        if result[0] == 6:
            raise Refused
        if result[0] != 0:
            # 4 is "not found": the call exists on some routers only.
            return None
        return result[1] if len(result) > 1 else {}

    async def _session(self, config: dict[str, Any], ctx: Context, *, fresh: bool = False) -> str:
        who = (base_url(config), str(config.get("username") or "root"), str(config.get("password") or ""))
        held = ctx.cache.get(SESSION)
        if not fresh and isinstance(held, tuple) and held[0] == who:
            return str(held[1])
        try:
            answer = await self._rpc(config, ctx, NO_SESSION, "session", "login", {"username": who[1], "password": who[2]})
        except Refused as error:
            # ⚠️ [6] at the door is a wrong name or password.
            raise AuthFailed("OpenWrt rejected the user or the password.") from error
        session = str((answer or {}).get("ubus_rpc_session") or "")
        if not session:
            raise AdapterError("OpenWrt handed out no session.", code="not_openwrt")
        ctx.cache[SESSION] = (who, session)
        return session

    async def _call(self, config: dict[str, Any], ctx: Context, target: str, method: str) -> Any:
        try:
            return await self._rpc(config, ctx, await self._session(config, ctx), target, method)
        except Refused:
            # ⚠️ A session that ran out looks exactly like a missing right.
            pass
        try:
            return await self._rpc(config, ctx, await self._session(config, ctx, fresh=True), target, method)
        except Refused as error:
            raise AdapterError(f"The user may not call {target} {method}.", code="forbidden", hint=READ_HINT) from error

    # -- the hooks -----------------------------------------------------------

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        board = await self._call(config, ctx, "system", "board") or {}
        release = board.get("release") if isinstance(board.get("release"), dict) else {}
        return f"{release.get('description') or 'OpenWrt'} answers on {board.get('model') or board.get('hostname') or '?'}."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "leases":
            answer = await self._call(config, ctx, "luci-rpc", "getDHCPLeases") or {}
            return self._lease_rows(answer)
        if widget_kind == "interfaces":
            dump = await self._call(config, ctx, "network.interface", "dump") or {}
            devices = await self._call(config, ctx, "luci-rpc", "getNetworkDevices") if part_on(options, "traffic") else {}
            return self._interface_rows(dump.get("interface") or [], devices or {}, options)
        info = await self._call(config, ctx, "system", "info") or {}
        board = await self._call(config, ctx, "system", "board") if part_on(options, "firmware") else {}
        return self._system(info, board or {})

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def _system(info: dict[str, Any], board: dict[str, Any]) -> WidgetData:
        memory = info.get("memory") if isinstance(info.get("memory"), dict) else {}
        total = float(memory.get("total") or 0)
        # ⚠️ "available", not "free": the page cache is not in use.
        used = round(100 * (total - float(memory.get("available") or memory.get("free") or 0)) / total) if total else 0
        load = [float(one) / LOAD_SCALE for one in (info.get("load") or [])[:3]]
        root = info.get("root") if isinstance(info.get("root"), dict) else {}
        storage = round(100 * float(root.get("used") or 0) / float(root["total"])) if root.get("total") else None
        release = board.get("release") if isinstance(board.get("release"), dict) else {}
        secondary = [
            {"label": "Load", "value": " / ".join(f"{one:.2f}" for one in load) or "?", "part": "load"},
            {"label": "Uptime", "value": duration_short(info.get("uptime")), "part": "uptime"},
            {"label": "Firmware", "value": str(release.get("version") or "?"), "part": "firmware"},
            {"label": "Storage", "value": f"{storage} %" if storage is not None else "?", "part": "storage"},
        ]
        full = used >= 90 or (storage or 0) >= 90
        return WidgetData(
            status="warn" if full else "ok" if total else "unknown",
            primary={"label": "Memory used", "value": used, "unit": "%"},
            secondary=secondary,
            metrics={"memory_percent": float(used), "load": load[0] if load else 0.0},
        )

    @staticmethod
    def _interface_rows(interfaces: list[Any], devices: dict[str, Any], options: dict[str, Any]) -> WidgetData:
        rows = []
        for interface in interfaces:
            if not isinstance(interface, dict) or interface.get("interface") == "loopback":
                continue
            proto = str(interface.get("proto") or "")
            parts = [PROTO.get(proto, proto.upper() or "?")]
            if interface.get("up"):
                status = "ok"
                addresses = interface.get("ipv4-address") or []
                if part_on(options, "address") and addresses and isinstance(addresses[0], dict):
                    parts.append(f"{addresses[0].get('address')}/{addresses[0].get('mask')}")
                if part_on(options, "uptime") and interface.get("uptime") is not None:
                    parts.append(f"up {duration_short(interface.get('uptime'))}")
                stats = (devices.get(str(interface.get("l3_device") or interface.get("device") or "")) or {}).get("stats") or {}
                if part_on(options, "traffic") and stats:
                    parts.append(f"↓ {human_bytes(stats.get('rx_bytes'))} ↑ {human_bytes(stats.get('tx_bytes'))}")
                value = "Up"
            elif not interface.get("autostart", True):
                status, value = "unknown", "Switched off"
            else:
                errors = [ERROR_WORD.get(str(one.get("code")), str(one.get("code"))) for one in interface.get("errors") or [] if isinstance(one, dict)]
                parts += errors
                status, value = ("warn", "Connecting") if interface.get("pending") else ("bad", "Down")
            rows.append({"title": str(interface.get("interface") or "?"), "subtitle": " · ".join(parts), "value": value, "status": status})
        rows.sort(key=lambda row: (ORDER.get(row["status"], 9), row["title"]))
        return WidgetData(
            status="bad" if any(row["status"] == "bad" for row in rows) else "warn" if any(row["status"] == "warn" for row in rows)
            else "ok" if rows else "unknown",
            items=rows,
            meta={"empty": "OpenWrt reports no interface."},
        )

    @staticmethod
    def _lease_rows(answer: dict[str, Any]) -> WidgetData:
        rows = []
        for lease in [*(answer.get("dhcp_leases") or []), *(answer.get("dhcp6_leases") or [])]:
            if not isinstance(lease, dict):
                continue
            address = str(lease.get("ipaddr") or lease.get("ip6addr") or "")
            name = str(lease.get("hostname") or "")
            expires = lease.get("expires")
            parts = [address] if name else []
            parts.append(str(lease.get("macaddr") or lease.get("duid") or ""))
            # ⚠️ Measured: a lease without end is false, one that ran out is 0.
            if expires is False:
                value, status = "no end", "ok"
            elif isinstance(expires, int | float) and expires <= 0:
                value, status = "expired", "unknown"
            else:
                value, status = duration_short(expires) if expires is not None else "", "ok"
            rows.append({"title": name or address or "?", "subtitle": " · ".join(part for part in parts if part), "value": value, "status": status})
        rows.sort(key=lambda row: str(row["title"]).lower())
        return WidgetData(status="ok", items=rows, meta={"empty": "No device holds an address right now."},
                          metrics={"leases": float(len(rows))})

    # -- demo ----------------------------------------------------------------

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        wan_down = fake.flicker("openwrt-wan", tick, 0.1)
        if widget_kind == "leases":
            return self._lease_rows({"dhcp_leases": [
                {"hostname": "office-printer", "ipaddr": "192.168.1.101", "macaddr": "02:00:5E:10:00:01", "expires": 3591},
                {"ipaddr": "192.168.1.102", "macaddr": "02:00:5E:10:00:02", "expires": 39991},
                {"hostname": "tv-livingroom", "ipaddr": "192.168.1.103", "macaddr": "02:00:5E:10:00:03", "expires": 7400},
                {"hostname": "nas", "ipaddr": "192.168.1.10", "macaddr": "02:00:5E:10:00:04", "expires": False},
            ]})
        if widget_kind == "interfaces":
            return self._interface_rows([
                {"interface": "lan", "up": True, "autostart": True, "proto": "static", "l3_device": "br-lan", "uptime": 912000,
                 "ipv4-address": [{"address": "192.168.1.1", "mask": 24}]},
                {"interface": "wan", "up": not wan_down, "autostart": True, "proto": "pppoe", "l3_device": "pppoe-wan",
                 "uptime": 41000 + tick * 60, "ipv4-address": [{"address": "203.0.113.24", "mask": 32}],
                 "errors": [{"code": "PROTO_FAILED"}] if wan_down else None},
                {"interface": "guest", "up": False, "autostart": False, "proto": "static"},
            ], {"br-lan": {"stats": {"rx_bytes": 41_800_000_000, "tx_bytes": 318_000_000_000}},
                "pppoe-wan": {"stats": {"rx_bytes": 402_000_000_000 + tick * 9_000_000, "tx_bytes": 38_000_000_000}}}, options)
        return self._system({"uptime": 912000 + tick * 60, "load": [10816 + tick % 5 * 900, 10528, 9376],
                             "memory": {"total": 512_000_000, "available": 301_000_000, "free": 90_000_000},
                             "root": {"total": 102_000_000, "used": 31_000_000}},
                            {"release": {"version": "25.12.5"}})


ADAPTER = OpenWrtAdapter()
