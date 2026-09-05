"""Headscale: the same tailnet, but the control server is yours.

Its REST API sits under ``/api/v1`` and takes a key made with
``headscale apikeys create``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from . import demo as fake
from .base import Adapter, Context, Field, WidgetData, WidgetType, base_url


class HeadscaleAdapter(Adapter):
    kind = "headscale"
    label = "Headscale"
    category = "network"
    description = "Nodes of a self-hosted tailnet, who is online and to whom they belong."
    icon = "headscale"
    docs_url = "https://headscale.net/stable/ref/remote-cli/"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://headscale:8080"),
        Field("api_key", "API key", type="password", secret=True, required=True, help="On the server: headscale apikeys create."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(
            kind="nodes",
            label="Nodes",
            description="One line per node with its owner and when it was last seen.",
            renderer="list",
            default_size=(4, 3),
            refresh_seconds=120,
            metrics=("nodes", "online"),
            options=(Field("limit", "Entries", type="number", default=10), Field("only_offline", "Only away", type="bool", default=False)),
        ),
        WidgetType(
            kind="status",
            label="Status",
            description="Nodes, how many are online, and how many users they belong to.",
            renderer="value",
            default_size=(2, 2),
            min_size=(1, 1),
            refresh_seconds=300,
            metrics=("nodes", "online"),
        ),
    )

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, cache: float = 60) -> Any:
        return await ctx.get_json(
            f"{base_url(config)}/api/v1{path}",
            headers={"Authorization": f"Bearer {config.get('api_key') or ''}"},
            verify=not config.get("insecure"),
            cache_seconds=cache,
        )

    @staticmethod
    def _ago(raw: str) -> str:
        if not raw:
            return "?"
        try:
            moment = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            return str(raw)
        seconds = (datetime.now(UTC) - moment).total_seconds()
        if seconds < 3600:
            return f"{int(seconds // 60)} min"
        if seconds < 86400:
            return f"{int(seconds // 3600)} h"
        return f"{int(seconds // 86400)} d"

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        payload = await self._get(config, ctx, "/node", cache=0)
        return f"Headscale answers with {len(payload.get('nodes') or [])} nodes."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        payload = await self._get(config, ctx, "/node")
        nodes = payload.get("nodes") or []
        online = sum(1 for node in nodes if node.get("online"))

        if widget_kind == "status":
            users = await self._get(config, ctx, "/user", cache=600)
            return WidgetData(
                primary={"label": "Nodes", "value": len(nodes)},
                secondary=[
                    {"label": "Online", "value": online},
                    {"label": "Away", "value": len(nodes) - online},
                    {"label": "Users", "value": len(users.get("users") or [])},
                ],
                metrics={"nodes": float(len(nodes)), "online": float(online)},
            )

        rows = []
        for node in nodes:
            reachable = bool(node.get("online"))
            if options.get("only_offline") and reachable:
                continue
            addresses = node.get("ipAddresses") or []
            rows.append({
                "title": node.get("givenName") or node.get("name") or "?",
                "subtitle": f"{(node.get('user') or {}).get('name', '')} · {addresses[0] if addresses else ''}".strip(" ·"),
                "value": "now" if reachable else self._ago(node.get("lastSeen") or ""),
                "status": "ok" if reachable else "unknown",
            })
        rows.sort(key=lambda row: (0 if row["status"] == "ok" else 1, row["title"]))
        return WidgetData(
            items=rows[: int(options.get("limit") or 10)],
            secondary=[{"label": "Online", "value": online}, {"label": "Nodes", "value": len(nodes)}],
            metrics={"nodes": float(len(nodes)), "online": float(online)},
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        nodes = [
            ("nexdeck", "alex", "100.64.0.1", True),
            ("phone", "alex", "100.64.0.7", True),
            ("laptop", "sam", "100.64.0.9", fake.flicker("headscale-laptop", tick, 0.4)),
            ("nas", "alex", "100.64.0.3", True),
        ]
        online = sum(1 for *_, reachable in nodes if reachable)
        if widget_kind == "status":
            return WidgetData(
                primary={"label": "Nodes", "value": len(nodes)},
                secondary=[
                    {"label": "Online", "value": online},
                    {"label": "Away", "value": len(nodes) - online},
                    {"label": "Users", "value": 2},
                ],
                metrics={"nodes": float(len(nodes)), "online": float(online)},
            )
        rows = [
            {
                "title": name,
                "subtitle": f"{user} · {address}",
                "value": "now" if reachable else f"{3 + index} h",
                "status": "ok" if reachable else "unknown",
            }
            for index, (name, user, address, reachable) in enumerate(nodes)
            if not options.get("only_offline") or not reachable
        ]
        rows.sort(key=lambda row: (0 if row["status"] == "ok" else 1, row["title"]))
        return WidgetData(
            items=rows[: int(options.get("limit") or 10)],
            secondary=[{"label": "Online", "value": online}, {"label": "Nodes", "value": len(nodes)}],
            metrics={"nodes": float(len(nodes)), "online": float(online)},
        )


ADAPTER = HeadscaleAdapter()
