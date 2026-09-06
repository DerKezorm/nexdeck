"""MikroTik: the router, through the REST interface of RouterOS 7.

⚠️ RouterOS 6 has no REST interface; there the API runs on its own port with
its own protocol, and this adapter cannot speak it. The field help says so,
because otherwise the connection test fails with a 404 for no visible reason.
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
    gauge_view_field,
    human_bytes,
    percent,
    status_from_percent,
)


class MikrotikAdapter(Adapter):
    kind = "mikrotik"
    label = "MikroTik"
    category = "network"
    description = "Load, memory and uptime of a RouterOS device, and the state of its interfaces."
    icon = "mikrotik"
    docs_url = "https://help.mikrotik.com/docs/display/ROS/REST+API"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="https://router.example.com", help="Needs RouterOS 7 with the www-ssl or www service switched on."),
        Field("username", "User name", required=True, help="A user with the read policy is enough."),
        Field("password", "Password", type="password", secret=True, required=True),
        Field("insecure", "Ignore TLS errors", type="bool", default=True, help="On by default: RouterOS answers with its own certificate."),
    )
    widgets = (
        WidgetType(
            kind="system",
            label="System",
            description="CPU, memory, uptime and the version it runs.",
            renderer="value",
            default_size=(2, 2),
            min_size=(1, 1),
            refresh_seconds=60,
            metrics=("cpu", "memory"),
            # The number is already a share of the machine; no ceiling needed.
            options=(gauge_view_field(),),
        ),
        WidgetType(
            kind="interfaces",
            label="Interfaces",
            description="One line per interface with what went through it.",
            renderer="list",
            default_size=(4, 3),
            refresh_seconds=60,
            metrics=("interfaces_down",),
            options=(Field("only_running", "Only running", type="bool", default=False),),
        ),
    )

    def _auth(self, config: dict[str, Any]) -> tuple[str, str]:
        return (str(config.get("username") or ""), str(config.get("password") or ""))

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, cache: float = 30) -> Any:
        return await ctx.get_json(
            f"{base_url(config)}/rest{path}",
            auth=self._auth(config),
            verify=not config.get("insecure", True),
            cache_seconds=cache,
        )

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        resource = await self._get(config, ctx, "/system/resource", cache=0)
        return f"RouterOS {resource.get('version', '?')} answers on a {resource.get('board-name', 'device')}."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "interfaces":
            interfaces = await self._get(config, ctx, "/interface", cache=30)
            items = []
            down = 0
            for entry in interfaces if isinstance(interfaces, list) else []:
                # RouterOS answers with strings, "true" and "false" included.
                running = str(entry.get("running")).lower() == "true"
                disabled = str(entry.get("disabled")).lower() == "true"
                if disabled is False and not running:
                    down += 1
                if options.get("only_running") and not running:
                    continue
                received = float(entry.get("rx-byte") or 0)
                sent = float(entry.get("tx-byte") or 0)
                items.append({
                    "title": entry.get("name") or "?",
                    "subtitle": f"{entry.get('type', '')} · {human_bytes(received)} / {human_bytes(sent)}".strip(" ·"),
                    "value": "",
                    "status": "unknown" if disabled else ("ok" if running else "bad"),
                })
            items.sort(key=lambda item: 0 if item["status"] == "bad" else 1)
            return WidgetData(
                status="bad" if down else "ok",
                items=items,
                secondary=[{"label": "Interfaces", "value": len(items)}, {"label": "Down", "value": down}],
                metrics={"interfaces_down": float(down)},
            )

        resource = await self._get(config, ctx, "/system/resource", cache=30)
        free = float(resource.get("free-memory") or 0)
        total = float(resource.get("total-memory") or 0)
        memory_share = percent(total - free, total)
        cpu = float(resource.get("cpu-load") or 0)
        return WidgetData(
            status=status_from_percent(max(cpu, memory_share)),
            primary={"label": "CPU", "value": cpu, "unit": "%"},
            secondary=[
                {"label": "Memory", "value": f"{memory_share} %"},
                # RouterOS says "1w2d3h4m5s"; that reads better than any number.
                {"label": "Uptime", "value": str(resource.get("uptime") or "?")},
                {"label": "Version", "value": str(resource.get("version") or "?")},
            ],
            metrics={"cpu": cpu, "memory": memory_share},
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        if widget_kind == "interfaces":
            broken = fake.flicker("mikrotik-port", tick, 0.07)
            rows = [
                ("ether1", "ether", 8.4e11, 2.1e11, True, False),
                ("ether2", "ether", 4.2e10, 9.8e10, not broken, False),
                ("bridge", "bridge", 9.1e11, 8.7e11, True, False),
                ("wg-home", "wg", 3.4e9, 2.9e9, True, False),
                ("ether5", "ether", 0, 0, False, True),
            ]
            items = [
                {
                    "title": name,
                    "subtitle": f"{kind} · {human_bytes(received)} / {human_bytes(sent)}",
                    "value": "",
                    "status": "unknown" if disabled else ("ok" if running else "bad"),
                }
                for name, kind, received, sent, running, disabled in rows
                if not options.get("only_running") or running
            ]
            items.sort(key=lambda item: 0 if item["status"] == "bad" else 1)
            return WidgetData(
                status="bad" if broken else "ok",
                items=items,
                secondary=[{"label": "Interfaces", "value": len(items)}, {"label": "Down", "value": 1 if broken else 0}],
                metrics={"interfaces_down": 1.0 if broken else 0.0},
            )
        cpu = fake.walk("mikrotik-cpu", tick, 2, 28)
        memory_share = fake.walk("mikrotik-mem", tick, 18, 42)
        return WidgetData(
            status=status_from_percent(max(cpu, memory_share)),
            primary={"label": "CPU", "value": cpu, "unit": "%"},
            secondary=[
                {"label": "Memory", "value": f"{memory_share} %"},
                {"label": "Uptime", "value": "6w2d4h"},
                {"label": "Version", "value": "7.16.2"},
            ],
            metrics={"cpu": cpu, "memory": memory_share},
        )


ADAPTER = MikrotikAdapter()
