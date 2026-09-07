"""OPNsense: the firewall, its gateways and whether an update is waiting.

Whoever runs their own firewall rarely runs one from Ubiquiti, and nexdeck knew
only UniFi. The API signs in with a key and a secret as basic authentication;
both come from System > Access > Users > API keys.
"""

from __future__ import annotations

from typing import Any

from . import demo as fake
from .base import (
    Adapter,
    Context,
    Field,
    WidgetData,
    WidgetType,
    base_url,
    duration_short,
    gauge_view_field,
    measured,
    percent,
    percent_primary,
    status_from_percent,
)


class OpnsenseAdapter(Adapter):
    kind = "opnsense"
    label = "OPNsense"
    category = "network"
    description = "System load, uptime, pending updates and the state of every gateway."
    icon = "opnsense"
    docs_url = "https://docs.opnsense.org/development/api.html"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="https://opnsense.example.com"),
        Field("api_key", "API key", type="password", secret=True, required=True, help="System > Access > Users > API keys"),
        Field("api_secret", "API secret", type="password", secret=True, required=True),
        Field("insecure", "Ignore TLS errors", type="bool", default=True, help="On by default: most firewalls answer with their own certificate."),
    )
    widgets = (
        WidgetType(
            kind="system",
            label="System",
            description="Load, memory, uptime and whether an update is waiting.",
            renderer="value",
            default_size=(2, 2),
            min_size=(1, 1),
            refresh_seconds=60,
            metrics=("cpu", "memory"),
            # The number is already a share of the machine; no ceiling needed.
            options=(gauge_view_field(),),
        ),
        WidgetType(
            kind="gateways",
            label="Gateways",
            description="One line per gateway with delay, loss and state.",
            renderer="list",
            default_size=(3, 3),
            refresh_seconds=60,
            metrics=("gateways_down",),
        ),
    )

    def _auth(self, config: dict[str, Any]) -> tuple[str, str]:
        return (str(config.get("api_key") or ""), str(config.get("api_secret") or ""))

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, cache: float = 30) -> Any:
        return await ctx.get_json(
            f"{base_url(config)}/api{path}",
            auth=self._auth(config),
            verify=not config.get("insecure", True),
            cache_seconds=cache,
        )

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        firmware = await self._get(config, ctx, "/core/firmware/status", cache=0)
        version = str(firmware.get("product_version") or (firmware.get("product") or {}).get("product_version") or "?")
        return f"OPNsense {version} answers."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "gateways":
            payload = await self._get(config, ctx, "/routes/gateway/status", cache=30)
            items = []
            down = 0
            for gateway in payload.get("items") or []:
                state = str(gateway.get("status_translated") or gateway.get("status") or "").lower()
                broken = state not in ("online", "none", "")
                down += 1 if broken else 0
                items.append({
                    "title": gateway.get("name") or "?",
                    "subtitle": f"{gateway.get('address', '?')} · {gateway.get('delay', '?')} · {gateway.get('loss', '?')}",
                    "value": gateway.get("status_translated") or gateway.get("status") or "",
                    "status": "bad" if broken else "ok",
                })
            items.sort(key=lambda entry: 0 if entry["status"] == "bad" else 1)
            return WidgetData(
                status="bad" if down else "ok",
                items=items,
                secondary=[{"label": "Gateways", "value": len(items)}, {"label": "Down", "value": down}],
                metrics={"gateways_down": float(down)},
            )

        resources = await self._get(config, ctx, "/diagnostics/system/systemResources", cache=30)
        firmware = await self._get(config, ctx, "/core/firmware/status", cache=600)
        memory = resources.get("memory") or {}
        used = float(memory.get("used") or 0)
        total = float(memory.get("total") or 0)
        memory_share = percent(used, total)
        # The load average of the last minute is the honest one for a firewall.
        load = resources.get("loadavg") or resources.get("load_average") or []
        load_one = float(load[0]) if isinstance(load, list) and load else 0.0
        updates = int(firmware.get("updates") or 0)
        uptime = resources.get("uptime") or (resources.get("system") or {}).get("uptime")
        return WidgetData(
            status="warn" if updates else status_from_percent(memory_share),
            primary=percent_primary("Memory", memory_share),
            secondary=[
                {"label": "Load", "value": round(load_one, 2)},
                {"label": "Uptime", "value": duration_short(float(uptime)) if isinstance(uptime, int | float) else str(uptime or "?")},
                {"label": "Updates", "value": updates},
            ],
            metrics=measured({"cpu": round(load_one, 2), "memory": memory_share}),
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        if widget_kind == "gateways":
            wan_down = fake.flicker("opnsense-wan", tick, 0.08)
            rows = [
                ("WAN_DHCP", "203.0.113.1", "12.4 ms", "0.0 %", wan_down),
                ("WAN2_LTE", "198.51.100.1", "48.1 ms", "1.2 %", False),
            ]
            items = [
                {
                    "title": name,
                    "subtitle": f"{address} · {delay} · {loss}",
                    "value": "down" if broken else "online",
                    "status": "bad" if broken else "ok",
                }
                for name, address, delay, loss, broken in rows
            ]
            return WidgetData(
                status="bad" if wan_down else "ok",
                items=items,
                secondary=[{"label": "Gateways", "value": len(items)}, {"label": "Down", "value": 1 if wan_down else 0}],
                metrics={"gateways_down": 1.0 if wan_down else 0.0},
            )
        memory_share = fake.walk("opnsense-mem", tick, 28, 61)
        updates = 1 if fake.flicker("opnsense-update", tick, 0.2) else 0
        return WidgetData(
            status="warn" if updates else status_from_percent(memory_share),
            primary={"label": "Memory", "value": memory_share, "unit": "%"},
            secondary=[
                {"label": "Load", "value": round(fake.walk("opnsense-load", tick, 0.1, 1.4), 2)},
                {"label": "Uptime", "value": duration_short(1_140_000 + tick * 30)},
                {"label": "Updates", "value": updates},
            ],
            metrics={"cpu": round(fake.walk("opnsense-load", tick, 0.1, 1.4), 2), "memory": memory_share},
        )


ADAPTER = OpnsenseAdapter()
