"""pfSense through the REST API package.

⚠️ pfSense ships no API of its own. This adapter speaks to the community
package **pfSense-pkg-RESTAPI v2** (``/api/v2``), which has to be installed on
the firewall; the field help says so, because otherwise the connection test
fails with a 404 and nobody knows why.
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
    percent,
    status_from_percent,
)


class PfsenseAdapter(Adapter):
    kind = "pfsense"
    label = "pfSense"
    category = "network"
    description = "System load, uptime and the interfaces of a pfSense firewall."
    icon = "pfsense"
    docs_url = "https://pfrest.org/"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="https://pfsense.example.com"),
        Field("api_key", "API key", type="password", secret=True, required=True, help="Needs the package pfSense-pkg-RESTAPI; the key comes from System > REST API > Keys."),
        Field("insecure", "Ignore TLS errors", type="bool", default=True, help="On by default: most firewalls answer with their own certificate."),
    )
    widgets = (
        WidgetType(
            kind="system",
            label="System",
            description="Load, memory and uptime of the firewall.",
            renderer="value",
            default_size=(2, 2),
            min_size=(1, 1),
            refresh_seconds=60,
            metrics=("cpu", "memory"),
        ),
        WidgetType(
            kind="interfaces",
            label="Interfaces",
            description="One line per interface with its address and state.",
            renderer="list",
            default_size=(3, 3),
            refresh_seconds=120,
            metrics=("interfaces_down",),
        ),
    )

    def _headers(self, config: dict[str, Any]) -> dict[str, str]:
        return {"X-API-Key": str(config.get("api_key") or "")}

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, cache: float = 30) -> Any:
        payload = await ctx.get_json(
            f"{base_url(config)}/api/v2{path}",
            headers=self._headers(config),
            verify=not config.get("insecure", True),
            cache_seconds=cache,
        )
        # The package wraps everything in {code, status, data}.
        return payload.get("data") if isinstance(payload, dict) and "data" in payload else payload

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        version = await self._get(config, ctx, "/status/system/version", cache=0)
        current = (version or {}).get("current_version") or (version or {}).get("version") or "?"
        return f"pfSense {current} answers."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "interfaces":
            interfaces = await self._get(config, ctx, "/status/interfaces", cache=60)
            items = []
            down = 0
            for entry in interfaces if isinstance(interfaces, list) else []:
                up = str(entry.get("status") or "").lower() in ("up", "online")
                enabled = bool(entry.get("enable", True))
                if enabled and not up:
                    down += 1
                items.append({
                    "title": entry.get("descr") or entry.get("name") or entry.get("if") or "?",
                    "subtitle": f"{entry.get('ipaddr') or entry.get('ipaddrv6') or ''} · {'up' if up else 'down'}".strip(" ·"),
                    "value": "",
                    "status": "ok" if up else ("bad" if enabled else "unknown"),
                })
            items.sort(key=lambda item: 0 if item["status"] == "bad" else 1)
            return WidgetData(
                status="bad" if down else "ok",
                items=items,
                secondary=[{"label": "Interfaces", "value": len(items)}, {"label": "Down", "value": down}],
                metrics={"interfaces_down": float(down)},
            )

        system = await self._get(config, ctx, "/status/system", cache=30)
        memory_share = float(system.get("mem_usage") or percent(system.get("mem_used"), system.get("mem_total")))
        cpu = float(system.get("cpu_usage") or 0)
        uptime = system.get("uptime")
        return WidgetData(
            status=status_from_percent(max(memory_share, cpu)),
            primary={"label": "CPU", "value": round(cpu, 1), "unit": "%"},
            secondary=[
                {"label": "Memory", "value": f"{round(memory_share, 1)} %"},
                {"label": "Uptime", "value": duration_short(float(uptime)) if isinstance(uptime, int | float) else str(uptime or "?")},
                {"label": "Temperature", "value": f"{system.get('temp')} °C" if system.get("temp") else "?"},
            ],
            metrics={"cpu": round(cpu, 1), "memory": round(memory_share, 1)},
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        if widget_kind == "interfaces":
            wan_down = fake.flicker("pfsense-wan", tick, 0.07)
            rows = [
                ("WAN", "203.0.113.24", not wan_down, True),
                ("LAN", "192.0.2.1", True, True),
                ("GUEST", "192.0.2.65", True, True),
                ("IOT", "", False, False),
            ]
            items = [
                {
                    "title": name,
                    "subtitle": f"{address} · {'up' if up else 'down'}".strip(" ·"),
                    "value": "",
                    "status": "ok" if up else ("bad" if enabled else "unknown"),
                }
                for name, address, up, enabled in rows
            ]
            return WidgetData(
                status="bad" if wan_down else "ok",
                items=items,
                secondary=[{"label": "Interfaces", "value": len(items)}, {"label": "Down", "value": 1 if wan_down else 0}],
                metrics={"interfaces_down": 1.0 if wan_down else 0.0},
            )
        cpu = fake.walk("pfsense-cpu", tick, 3, 34)
        memory_share = fake.walk("pfsense-mem", tick, 22, 48)
        return WidgetData(
            status=status_from_percent(max(cpu, memory_share)),
            primary={"label": "CPU", "value": cpu, "unit": "%"},
            secondary=[
                {"label": "Memory", "value": f"{memory_share} %"},
                {"label": "Uptime", "value": duration_short(2_400_000 + tick * 30)},
                {"label": "Temperature", "value": "41 °C"},
            ],
            metrics={"cpu": cpu, "memory": memory_share},
        )


ADAPTER = PfsenseAdapter()
