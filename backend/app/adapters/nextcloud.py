"""Nextcloud: users, files and how much room is left.

The serverinfo app answers one address with everything worth a card. It wants
an administrator, either through a token from the app's settings or through
the account itself.
"""

from __future__ import annotations

from typing import Any

from . import demo as fake
from .base import (
    Adapter,
    AdapterError,
    Context,
    Field,
    WidgetData,
    WidgetType,
    base_url,
    human_bytes,
    percent,
    status_from_percent,
)


class NextcloudAdapter(Adapter):
    kind = "nextcloud"
    label = "Nextcloud"
    category = "nas"
    description = "Users, files, free space and what the server says about itself."
    icon = "nextcloud"
    docs_url = "https://docs.nextcloud.com/server/latest/admin_manual/operations/monitoring.html"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="https://cloud.example.com"),
        Field("token", "Serverinfo token", type="password", secret=True, help="Settings > Administration > Monitoring. Leave empty to sign in with the account below."),
        Field("username", "User name", help="An administrator; only needed without a token."),
        Field("password", "Password", type="password", secret=True),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(
            kind="overview",
            label="Overview",
            description="Users, files and the free space of the data directory.",
            renderer="value",
            default_size=(2, 2),
            min_size=(1, 1),
            refresh_seconds=300,
            metrics=("users", "free_percent"),
        ),
        WidgetType(
            kind="activity",
            label="Active users",
            description="Who was there in the last five minutes, hour and day.",
            renderer="stats",
            default_size=(3, 2),
            refresh_seconds=300,
            metrics=("active_day",),
        ),
        WidgetType(
            kind="storage",
            label="Free space",
            description="How full the disk behind Nextcloud is.",
            renderer="gauge",
            default_size=(2, 2),
            refresh_seconds=300,
            metrics=("used_percent",),
        ),
    )

    async def _info(self, config: dict[str, Any], ctx: Context, cache: float = 120) -> dict[str, Any]:
        headers = {"OCS-APIRequest": "true", "Accept": "application/json"}
        token = str(config.get("token") or "")
        auth = None
        if token:
            headers["NC-Token"] = token
        else:
            user = str(config.get("username") or "")
            if not user:
                raise AdapterError("Nextcloud needs a token or an account.", code="missing_fields", hint="Fill in the serverinfo token, or a user name and password.")
            auth = (user, str(config.get("password") or ""))
        payload = await ctx.get_json(
            f"{base_url(config)}/ocs/v2.php/apps/serverinfo/api/v1/info",
            headers=headers,
            params={"format": "json"},
            auth=auth,
            verify=not config.get("insecure"),
            cache_seconds=cache,
        )
        data = ((payload or {}).get("ocs") or {}).get("data") or {}
        if not data:
            raise AdapterError("Nextcloud answered without server information.", code="not_json", hint="Is the serverinfo app enabled?")
        return data

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        info = await self._info(config, ctx, cache=0)
        version = ((info.get("nextcloud") or {}).get("system") or {}).get("version", "?")
        return f"Nextcloud {version} answers."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        info = await self._info(config, ctx)
        nextcloud = info.get("nextcloud") or {}
        system = nextcloud.get("system") or {}
        storage = nextcloud.get("storage") or {}
        active = info.get("activeUsers") or {}
        free = float(system.get("freespace") or 0)

        if widget_kind == "activity":
            return WidgetData(
                secondary=[
                    {"label": "Last five minutes", "value": int(active.get("last5minutes") or 0)},
                    {"label": "Last hour", "value": int(active.get("last1hour") or 0)},
                    {"label": "Last day", "value": int(active.get("last24hours") or 0)},
                ],
                metrics={"active_day": float(active.get("last24hours") or 0)},
            )

        if widget_kind == "storage":
            # Nextcloud reports the free bytes; the total comes from the disk
            # behind it, which serverinfo only knows through the memory block.
            total = float(system.get("disk_total") or 0) or free + float(storage.get("num_files") or 0) * 0
            if not total:
                raise AdapterError("Nextcloud does not report the size of the disk.", code="no_total", hint="Use the free space on the overview card instead.")
            used = max(0.0, total - free)
            share = percent(used, total)
            return WidgetData(
                status=status_from_percent(share),
                primary={"label": "Used", "value": share, "unit": "%"},
                secondary=[{"label": "Free", "value": human_bytes(free)}, {"label": "Total", "value": human_bytes(total)}],
                metrics={"used_percent": share},
            )

        users = int(storage.get("num_users") or 0)
        return WidgetData(
            status="warn" if free and free < 20 * 1024**3 else "ok",
            primary={"label": "Users", "value": users},
            secondary=[
                {"label": "Files", "value": int(storage.get("num_files") or 0)},
                {"label": "Free", "value": human_bytes(free)},
                {"label": "Version", "value": system.get("version", "?")},
            ],
            metrics={"users": float(users), "free_percent": 0.0},
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        if widget_kind == "activity":
            return WidgetData(
                secondary=[
                    {"label": "Last five minutes", "value": int(fake.walk("nc-5m", tick, 0, 4))},
                    {"label": "Last hour", "value": int(fake.walk("nc-1h", tick, 2, 9))},
                    {"label": "Last day", "value": int(fake.walk("nc-24h", tick, 6, 14))},
                ],
                metrics={"active_day": fake.walk("nc-24h", tick, 6, 14)},
            )
        free = 4.1e11 - tick * 1.2e6
        if widget_kind == "storage":
            total = 2.0e12
            share = round(100.0 * (total - free) / total, 1)
            return WidgetData(
                status=status_from_percent(share),
                primary={"label": "Used", "value": share, "unit": "%"},
                secondary=[{"label": "Free", "value": human_bytes(free)}, {"label": "Total", "value": human_bytes(total)}],
                metrics={"used_percent": share},
            )
        return WidgetData(
            primary={"label": "Users", "value": 14},
            secondary=[
                {"label": "Files", "value": fake.counter("nc-files", tick, 184320, 1.4)},
                {"label": "Free", "value": human_bytes(free)},
                {"label": "Version", "value": "31.0.2"},
            ],
            metrics={"users": 14.0, "free_percent": 0.0},
        )


ADAPTER = NextcloudAdapter()
