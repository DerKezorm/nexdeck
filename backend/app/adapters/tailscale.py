"""Tailscale: the devices of a tailnet.

The one address that is not in the house: Tailscale's control plane runs at
api.tailscale.com, and that is where the device list comes from. The token is
an API access token from the admin console.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from . import demo as fake
from .base import Adapter, Context, Field, WidgetData, WidgetType

API = "https://api.tailscale.com/api/v2"
#: A device that has not been seen this long counts as away.
ONLINE_SECONDS = 300


class TailscaleAdapter(Adapter):
    kind = "tailscale"
    label = "Tailscale"
    category = "network"
    description = "Devices of a tailnet, who is reachable and which client is out of date."
    icon = "tailscale"
    docs_url = "https://tailscale.com/api"
    fields = (
        Field("api_key", "API access token", type="password", secret=True, required=True, help="Admin console > Settings > Keys > API access token."),
        Field("tailnet", "Tailnet", default="-", help="The name of the tailnet; a single dash takes the one the token belongs to."),
    )
    widgets = (
        WidgetType(
            kind="devices",
            label="Devices",
            description="One line per device with its system and when it was last seen.",
            renderer="list",
            default_size=(4, 3),
            refresh_seconds=120,
            metrics=("devices", "online"),
            options=(Field("limit", "Entries", type="number", default=10), Field("only_offline", "Only away", type="bool", default=False)),
        ),
        WidgetType(
            kind="status",
            label="Status",
            description="How many devices there are, how many are reachable, and how many need an update.",
            renderer="value",
            default_size=(2, 2),
            min_size=(1, 1),
            refresh_seconds=300,
            metrics=("devices", "online"),
        ),
    )

    def default_link(self, config: dict[str, Any]) -> str:
        return "https://login.tailscale.com/admin/machines"

    async def _devices(self, config: dict[str, Any], ctx: Context, cache: float = 60) -> list[dict[str, Any]]:
        tailnet = str(config.get("tailnet") or "-").strip() or "-"
        payload = await ctx.get_json(
            f"{API}/tailnet/{tailnet}/devices",
            headers={"Authorization": f"Bearer {config.get('api_key') or ''}"},
            cache_seconds=cache,
        )
        return (payload or {}).get("devices") or []

    @staticmethod
    def _seen(device: dict[str, Any]) -> tuple[str, bool]:
        raw = str(device.get("lastSeen") or "")
        if not raw:
            return "?", False
        try:
            moment = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return raw, False
        seconds = (datetime.now(UTC) - moment).total_seconds()
        if seconds <= ONLINE_SECONDS:
            return "now", True
        if seconds < 3600:
            return f"{int(seconds // 60)} min", False
        if seconds < 86400:
            return f"{int(seconds // 3600)} h", False
        return f"{int(seconds // 86400)} d", False

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        devices = await self._devices(config, ctx, cache=0)
        return f"Tailscale answers with {len(devices)} devices."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        devices = await self._devices(config, ctx)
        online = 0
        updates = 0
        rows = []
        for device in devices:
            ago, reachable = self._seen(device)
            online += 1 if reachable else 0
            updates += 1 if device.get("updateAvailable") else 0
            addresses = device.get("addresses") or []
            rows.append({
                "title": device.get("name", "").split(".")[0] or device.get("hostname") or "?",
                "subtitle": f"{device.get('os', '')} · {addresses[0] if addresses else ''}".strip(" ·"),
                "value": ago,
                "status": "ok" if reachable else "unknown",
                "update": bool(device.get("updateAvailable")),
            })

        if widget_kind == "status":
            return WidgetData(
                status="warn" if updates else "ok",
                primary={"label": "Devices", "value": len(devices)},
                secondary=[
                    {"label": "Reachable", "value": online},
                    {"label": "Away", "value": len(devices) - online},
                    {"label": "Updates", "value": updates},
                ],
                metrics={"devices": float(len(devices)), "online": float(online)},
            )

        if options.get("only_offline"):
            rows = [row for row in rows if row["status"] != "ok"]
        rows.sort(key=lambda row: (0 if row["status"] == "ok" else 1, row["title"]))
        limit = int(options.get("limit") or 10)
        return WidgetData(
            items=[{key: value for key, value in row.items() if key != "update"} for row in rows[:limit]],
            secondary=[{"label": "Reachable", "value": online}, {"label": "Devices", "value": len(devices)}],
            metrics={"devices": float(len(devices)), "online": float(online)},
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        devices = [
            ("nexdeck", "linux", "100.64.0.1", True),
            ("phone", "iOS", "100.64.0.7", True),
            ("laptop", "macOS", "100.64.0.9", fake.flicker("tailscale-laptop", tick, 0.4)),
            ("nas", "linux", "100.64.0.3", True),
            ("tablet", "android", "100.64.0.11", False),
        ]
        online = sum(1 for *_, reachable in devices if reachable)
        updates = 1 if fake.flicker("tailscale-update", tick, 0.2) else 0
        if widget_kind == "status":
            return WidgetData(
                status="warn" if updates else "ok",
                primary={"label": "Devices", "value": len(devices)},
                secondary=[
                    {"label": "Reachable", "value": online},
                    {"label": "Away", "value": len(devices) - online},
                    {"label": "Updates", "value": updates},
                ],
                metrics={"devices": float(len(devices)), "online": float(online)},
            )
        rows = [
            {
                "title": name,
                "subtitle": f"{system} · {address}",
                "value": "now" if reachable else f"{2 + index} h",
                "status": "ok" if reachable else "unknown",
            }
            for index, (name, system, address, reachable) in enumerate(devices)
            if not options.get("only_offline") or not reachable
        ]
        rows.sort(key=lambda row: (0 if row["status"] == "ok" else 1, row["title"]))
        return WidgetData(
            items=rows[: int(options.get("limit") or 10)],
            secondary=[{"label": "Reachable", "value": online}, {"label": "Devices", "value": len(devices)}],
            metrics={"devices": float(len(devices)), "online": float(online)},
        )


ADAPTER = TailscaleAdapter()
