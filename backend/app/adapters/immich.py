"""Immich: how many pictures, how much room is left.

The photo archive most homelabs installed in the last two years. The API key
comes from the account settings and rides in the ``x-api-key`` header; the
statistics endpoint needs an administrator's key.
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
    human_bytes,
    percent,
    status_from_percent,
)


class ImmichAdapter(Adapter):
    kind = "immich"
    label = "Immich"
    category = "media"
    description = "Pictures, videos and how full the archive is."
    icon = "immich"
    docs_url = "https://immich.app/docs/api/"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://immich:2283"),
        Field("api_key", "API key", type="password", secret=True, required=True, help="Account settings > API Keys. Statistics need an administrator's key."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(
            kind="library",
            label="Archive",
            description="Pictures, videos and what they occupy.",
            renderer="value",
            default_size=(2, 2),
            min_size=(1, 1),
            refresh_seconds=300,
            metrics=("photos", "videos"),
        ),
        WidgetType(
            kind="storage",
            label="Storage",
            description="How full the disk behind Immich is.",
            renderer="gauge",
            default_size=(2, 2),
            refresh_seconds=300,
            metrics=("used_percent",),
        ),
        WidgetType(
            kind="users",
            label="Users",
            description="Who keeps how much in the archive.",
            renderer="list",
            default_size=(3, 3),
            refresh_seconds=900,
            options=(Field("limit", "Entries", type="number", default=6),),
        ),
    )

    def _headers(self, config: dict[str, Any]) -> dict[str, str]:
        return {"x-api-key": str(config.get("api_key") or ""), "Accept": "application/json"}

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, cache: float = 60) -> Any:
        return await ctx.get_json(
            f"{base_url(config)}/api{path}",
            headers=self._headers(config),
            verify=not config.get("insecure"),
            cache_seconds=cache,
        )

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        about = await self._get(config, ctx, "/server/about", cache=0)
        return f"Immich {about.get('version', '?')} answers."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "storage":
            storage = await self._get(config, ctx, "/server/storage", cache=300)
            total = float(storage.get("diskSizeRaw") or 0)
            used = float(storage.get("diskUseRaw") or 0)
            share = float(storage.get("diskUsagePercentage") or percent(used, total))
            return WidgetData(
                status=status_from_percent(share),
                primary={"label": "Used", "value": round(share, 1), "unit": "%"},
                secondary=[
                    {"label": "Used", "value": human_bytes(used)},
                    {"label": "Free", "value": human_bytes(max(0.0, total - used))},
                    {"label": "Total", "value": human_bytes(total)},
                ],
                metrics={"used_percent": round(share, 1)},
            )

        statistics = await self._get(config, ctx, "/server/statistics", cache=300)
        photos = int(statistics.get("photos") or 0)
        videos = int(statistics.get("videos") or 0)
        usage = float(statistics.get("usage") or 0)

        if widget_kind == "users":
            limit = int(options.get("limit") or 6)
            rows = sorted(statistics.get("usageByUser") or [], key=lambda entry: float(entry.get("usage") or 0), reverse=True)
            items = [
                {
                    "title": entry.get("userName") or "?",
                    "subtitle": f"{int(entry.get('photos') or 0)} + {int(entry.get('videos') or 0)}",
                    "value": human_bytes(float(entry.get("usage") or 0)),
                    "status": "ok",
                }
                for entry in rows[:limit]
            ]
            return WidgetData(items=items, secondary=[{"label": "Users", "value": len(rows)}])

        return WidgetData(
            primary={"label": "Pictures", "value": photos},
            secondary=[
                {"label": "Videos", "value": videos},
                {"label": "Used", "value": human_bytes(usage)},
            ],
            metrics={"photos": float(photos), "videos": float(videos)},
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        photos = fake.counter("immich-photos", tick, 48210, 0.4)
        videos = fake.counter("immich-videos", tick, 1840, 0.05)
        usage = 1.42e12 + photos * 2200.0
        if widget_kind == "storage":
            total = 3.6e12
            share = round(100.0 * usage / total, 1)
            return WidgetData(
                status=status_from_percent(share),
                primary={"label": "Used", "value": share, "unit": "%"},
                secondary=[
                    {"label": "Used", "value": human_bytes(usage)},
                    {"label": "Free", "value": human_bytes(total - usage)},
                    {"label": "Total", "value": human_bytes(total)},
                ],
                metrics={"used_percent": share},
            )
        if widget_kind == "users":
            rows = [("Alex", 31200, 900, 8.1e11), ("Sam", 12400, 640, 4.2e11), ("Kim", 4610, 300, 1.9e11)]
            return WidgetData(
                items=[
                    {"title": name, "subtitle": f"{pictures} + {clips}", "value": human_bytes(bytes_used), "status": "ok"}
                    for name, pictures, clips, bytes_used in rows
                ],
                secondary=[{"label": "Users", "value": len(rows)}],
            )
        return WidgetData(
            primary={"label": "Pictures", "value": photos},
            secondary=[{"label": "Videos", "value": videos}, {"label": "Used", "value": human_bytes(usage)}],
            metrics={"photos": float(photos), "videos": float(videos)},
        )


ADAPTER = ImmichAdapter()
