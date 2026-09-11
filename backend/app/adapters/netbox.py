"""NetBox: which devices are not active, how full the prefixes are, and how much is documented.

Measured against NetBox 4.7.0 (netbox-docker) on 11.09.2026, with two sites,
five devices (two active, one offline, one planned, one failed), two prefixes
and three IP addresses in the first.

⚠️ Two token formats answer to one header. A token of the old kind worked as
``Token <key>`` and as ``Bearer <key>``; a v2 token only as
``Bearer nbt_<key>.<token>``. Its secret half alone got 403 "Invalid v1
token", which says nothing about what is wrong. The card always sends Bearer
with whatever was pasted.

⚠️ A prefix carries no utilisation. The card counts the IP addresses inside
each one with ``parent=`` and puts that against the size of the prefix. Child
prefixes and ranges are not counted, so a prefix that is split into smaller
ones reads emptier here than in NetBox.

⚠️ No token at all gets 403, not 401.
"""

from __future__ import annotations

import asyncio
import ipaddress
from typing import Any

from .base import (
    Adapter,
    AdapterError,
    AuthFailed,
    Context,
    Field,
    WidgetData,
    WidgetType,
    base_url,
)

#: NetBox's device states, worst first, with a colour and a word.
DEVICE = {
    "failed": ("bad", "Failed"), "offline": ("warn", "Offline"), "decommissioning": ("unknown", "Decommissioning"),
    "planned": ("unknown", "Planned"), "staged": ("unknown", "Staged"), "inventory": ("unknown", "Inventory"), "active": ("ok", "Active"),
}
PREFIX = {"active": "Active", "reserved": "Reserved", "deprecated": "Deprecated", "container": "Container"}


def usable(prefix: str) -> int | None:
    """How many addresses a prefix can hand out; ``None`` for one too big to be worth a share."""
    try:
        network = ipaddress.ip_network(prefix, strict=False)
    except ValueError:
        return None
    if network.version == 6 and network.prefixlen < 112:
        return None
    if network.version == 4 and network.prefixlen <= 30:
        return network.num_addresses - 2
    return network.num_addresses


class NetboxAdapter(Adapter):
    kind = "netbox"
    label = "NetBox"
    category = "network"
    description = "Which devices are not active, how full the prefixes are, and how much is documented."
    icon = "netbox"
    beta = False
    docs_url = "https://netboxlabs.com/docs/netbox/integrations/rest-api/"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://netbox:8080"),
        Field("token", "API token", type="password", secret=True, required=True,
              help="A read-only API token is enough. Paste it whole: a v2 token starts with nbt_ and has a dot in the middle."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(kind="devices", label="Devices", description="Devices that are not active, failed ones first, or all of them.",
                   renderer="list", default_size=(3, 3), refresh_seconds=600,
                   options=(Field("all", "Active devices too", type="bool", default=False),
                            Field("limit", "Entries", type="number", default=10))),
        WidgetType(kind="prefixes", label="Prefixes", description="How many addresses of each prefix are documented as in use.",
                   renderer="list", default_size=(3, 3), refresh_seconds=900,
                   options=(Field("limit", "Entries", type="number", default=8),)),
        WidgetType(kind="summary", label="Inventory", description="Devices, the ones not active, sites and IP addresses.",
                   renderer="value", default_size=(3, 2), refresh_seconds=900, metrics=("devices",)),
    )

    async def _json(self, config: dict[str, Any], ctx: Context, path: str, params: dict[str, Any] | None = None, cache: float = 30) -> Any:
        response = await ctx.request(
            "GET", f"{base_url(config)}/api{path}",
            headers={"Authorization": f"Bearer {str(config.get('token') or '').strip()}", "Accept": "application/json"},
            params=params, verify=not config.get("insecure"), cache_seconds=cache, auth_errors=False,
        )
        if response.status_code in (401, 403):
            raise AuthFailed("NetBox refused the token. A v2 token has to be pasted whole, nbt_ and the part after the dot included.")
        if response.status_code >= 400:
            raise AdapterError(f"NetBox answered with HTTP {response.status_code}.", code="http_error",
                               hint="Check the URL; it is the address of NetBox itself, without /api.")
        try:
            answer = response.json()
        except ValueError as error:
            raise AdapterError("NetBox did not answer with JSON.", code="not_json",
                               hint="The URL probably points at the sign-in page or a reverse proxy.") from error
        if not isinstance(answer, dict):
            raise AdapterError("This address answers, but not the way NetBox does.", code="not_netbox")
        return answer

    async def _count(self, config: dict[str, Any], ctx: Context, path: str, params: dict[str, Any] | None = None) -> int:
        answer = await self._json(config, ctx, path, {**(params or {}), "limit": 1, "brief": "true"})
        if "count" not in answer:
            raise AdapterError("This address answers, but not the way NetBox does.", code="not_netbox")
        return int(answer.get("count") or 0)

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        status = await self._json(config, ctx, "/status/", cache=0)
        if "netbox-version" not in status:
            raise AdapterError("This address answers, but not the way NetBox does.", code="not_netbox")
        devices = await self._count(config, ctx, "/dcim/devices/")
        return f"NetBox {status['netbox-version']} answers with {devices} devices."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "summary":
            devices, idle, sites, addresses = await asyncio.gather(
                self._count(config, ctx, "/dcim/devices/"), self._count(config, ctx, "/dcim/devices/", {"status__n": "active"}),
                self._count(config, ctx, "/dcim/sites/"), self._count(config, ctx, "/ipam/ip-addresses/"))
            return self._summary(devices, idle, sites, addresses)
        if widget_kind == "prefixes":
            limit = max(1, int(options.get("limit") or 8))
            answer = await self._json(config, ctx, "/ipam/prefixes/", {"limit": limit})
            prefixes = [one for one in answer.get("results") or [] if isinstance(one, dict)]
            used = await asyncio.gather(*(self._count(config, ctx, "/ipam/ip-addresses/", {"parent": str(one.get("prefix"))}) for one in prefixes))
            return self._prefixes(prefixes, list(used), int(answer.get("count") or len(prefixes)))
        params: dict[str, Any] = {"limit": 200}
        if not options.get("all"):
            params["status__n"] = "active"
        answer = await self._json(config, ctx, "/dcim/devices/", params)
        return self._devices([one for one in answer.get("results") or [] if isinstance(one, dict)], int(answer.get("count") or 0), options)

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def _devices(devices: list[dict[str, Any]], total: int, options: dict[str, Any]) -> WidgetData:
        order = list(DEVICE)

        def state(device: dict[str, Any]) -> str:
            return str((device.get("status") or {}).get("value") if isinstance(device.get("status"), dict) else device.get("status") or "")

        ranked = sorted(devices, key=lambda one: (order.index(state(one)) if state(one) in order else len(order), str(one.get("name") or "")))
        items = []
        for device in ranked[: int(options.get("limit") or 10)]:
            colour, word = DEVICE.get(state(device), ("unknown", state(device).capitalize()))
            site = device.get("site") if isinstance(device.get("site"), dict) else {}
            role = device.get("role") if isinstance(device.get("role"), dict) else {}
            row: dict[str, Any] = {
                "title": str(device.get("name") or device.get("display") or "?"),
                "subtitle": " · ".join(part for part in (word, str(site.get("name") or ""), str(role.get("name") or "")) if part),
                "status": colour,
            }
            if device.get("display_url"):
                row["url"] = str(device["display_url"])
            items.append(row)
        failed = sum(1 for one in devices if state(one) == "failed")
        return WidgetData(
            status="bad" if failed else "ok",
            items=items,
            secondary=[{"label": "Devices" if options.get("all") else "Not active", "value": total}],
            meta={"empty": "No devices yet." if options.get("all") else "Every device is active."},
        )

    @staticmethod
    def _prefixes(prefixes: list[dict[str, Any]], used: list[int], total: int) -> WidgetData:
        items = []
        for prefix, count in zip(prefixes, used, strict=True):
            size = usable(str(prefix.get("prefix") or ""))
            share = round(100 * count / size) if size else None
            state = str((prefix.get("status") or {}).get("value") if isinstance(prefix.get("status"), dict) else prefix.get("status") or "")
            vrf = prefix.get("vrf") if isinstance(prefix.get("vrf"), dict) else {}
            row: dict[str, Any] = {
                "title": str(prefix.get("prefix") or "?"),
                "subtitle": " · ".join(part for part in (PREFIX.get(state, state.capitalize()), str(vrf.get("name") or "")) if part),
                "status": "bad" if share is not None and share >= 90 else "warn" if share is not None and share >= 75 else "ok",
                "value": f"{share}%" if share is not None else str(count),
            }
            if share is not None:
                row["progress"] = float(min(100, share))
            if prefix.get("display_url"):
                row["url"] = str(prefix["display_url"])
            items.append(row)
        return WidgetData(
            status="ok",
            items=items,
            secondary=[{"label": "Prefixes", "value": total}],
            meta={"empty": "No prefixes yet."},
        )

    @staticmethod
    def _summary(devices: int, idle: int, sites: int, addresses: int) -> WidgetData:
        secondary: list[dict[str, Any]] = []
        if idle:
            secondary.append({"label": "Not active", "value": idle})
        secondary += [{"label": "Sites", "value": sites}, {"label": "IP addresses", "value": addresses}]
        return WidgetData(
            status="ok",
            primary={"label": "Devices", "value": devices},
            secondary=secondary,
            metrics={"devices": float(devices)},
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        if widget_kind == "summary":
            return self._summary(42, 3, 2, 186 + tick % 4)
        if widget_kind == "prefixes":
            prefixes = [{"prefix": "192.0.2.0/24", "status": {"value": "active"}}, {"prefix": "198.51.100.0/25", "status": {"value": "active"}},
                        {"prefix": "203.0.113.0/24", "status": {"value": "reserved"}}]
            return self._prefixes(prefixes, [201, 97 + tick % 3, 4], 3)
        devices = [
            {"name": "ups-cellar", "status": {"value": "failed"}, "site": {"name": "Home"}, "role": {"name": "Power"}},
            {"name": "old-pi", "status": {"value": "offline"}, "site": {"name": "Home"}, "role": {"name": "Server"}},
            {"name": "switch-garage", "status": {"value": "planned"}, "site": {"name": "Garage"}, "role": {"name": "Switch"}},
        ]
        return self._devices(devices, 3, options)


ADAPTER = NetboxAdapter()
