"""Jellystat: the statistics beside Jellyfin.

Its API wants a key from the settings in the ``x-api-token`` header. Most of
its addresses answer a POST, even the ones that only read.
"""

from __future__ import annotations

from typing import Any

from .base import (
    Adapter,
    AdapterError,
    Context,
    Field,
    WidgetData,
    WidgetType,
    base_url,
)


class JellystatAdapter(Adapter):
    kind = "jellystat"
    label = "Jellystat"
    category = "media"
    description = "Libraries, playbacks and the most watched titles beside Jellyfin."
    icon = "jellystat"
    docs_url = "https://github.com/CyferShepard/Jellystat"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://jellystat:3000"),
        Field("api_key", "API key", type="password", secret=True, required=True, help="Settings > API Keys."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(
            kind="libraries",
            label="Libraries",
            description="One line per library with what it holds.",
            renderer="list",
            default_size=(3, 3),
            refresh_seconds=900,
            metrics=("items",),
        ),
        WidgetType(
            kind="watched",
            label="Most watched",
            description="The titles played most in the last days.",
            renderer="list",
            default_size=(3, 3),
            refresh_seconds=900,
            options=(Field("days", "Days", type="number", default=30), Field("limit", "Entries", type="number", default=6)),
        ),
    )

    def _headers(self, config: dict[str, Any]) -> dict[str, str]:
        return {"x-api-token": str(config.get("api_key") or ""), "Content-Type": "application/json"}

    async def _call(self, config: dict[str, Any], ctx: Context, method: str, path: str, body: Any = None) -> Any:
        response = await ctx.request(
            method,
            f"{base_url(config)}{path}",
            headers=self._headers(config),
            json_body=body,
            verify=not config.get("insecure"),
        )
        if response.status_code >= 400:
            raise AdapterError(f"Jellystat answered with HTTP {response.status_code}.", code="http_error")
        try:
            return response.json()
        except ValueError:
            return []

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        libraries = await self._call(config, ctx, "GET", "/api/getLibraries")
        return f"Jellystat answers with {len(libraries) if isinstance(libraries, list) else 0} libraries."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "watched":
            days = int(options.get("days") or 30)
            limit = int(options.get("limit") or 6)
            payload = await self._call(config, ctx, "POST", "/stats/getMostViewedByType", {"days": days})
            rows = payload if isinstance(payload, list) else []
            items = []
            for group in rows:
                for entry in (group.get("results") or [])[:limit]:
                    items.append({
                        "title": entry.get("Name") or entry.get("Label") or "?",
                        "subtitle": str(group.get("Label") or ""),
                        "value": int(entry.get("Plays") or entry.get("Count") or 0),
                        "status": "ok",
                    })
            items.sort(key=lambda item: -int(item["value"] or 0))
            return WidgetData(items=items[:limit], secondary=[{"label": "Days", "value": days}])

        libraries = await self._call(config, ctx, "GET", "/api/getLibraries")
        rows = libraries if isinstance(libraries, list) else []
        total = 0
        items = []
        for library in rows:
            count = int(library.get("Library_Count") or library.get("ItemCount") or 0)
            total += count
            items.append({
                "title": library.get("Name") or "?",
                "subtitle": str(library.get("CollectionType") or ""),
                "value": count,
                "status": "ok",
            })
        return WidgetData(
            items=items,
            secondary=[{"label": "Libraries", "value": len(items)}, {"label": "Items", "value": total}],
            metrics={"items": float(total)},
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        if widget_kind == "watched":
            rows = [("The Quiet Harbour", "Movies", 14), ("Harbour Lights", "Shows", 11), ("Northern Shore", "Shows", 8), ("Copper Sky", "Movies", 5)]
            return WidgetData(
                items=[{"title": title, "subtitle": kind, "value": plays, "status": "ok"} for title, kind, plays in rows],
                secondary=[{"label": "Days", "value": int(options.get("days") or 30)}],
            )
        rows = [("Movies", "movies", 1284), ("Shows", "tvshows", 218), ("Music", "music", 21840)]
        total = sum(count for _, _, count in rows)
        return WidgetData(
            items=[{"title": name, "subtitle": kind, "value": count, "status": "ok"} for name, kind, count in rows],
            secondary=[{"label": "Libraries", "value": len(rows)}, {"label": "Items", "value": total}],
            metrics={"items": float(total)},
        )


ADAPTER = JellystatAdapter()
