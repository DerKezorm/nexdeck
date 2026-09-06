"""Komga: comics and books, the counterpart to Readarr.

Komga takes an API key in a header since 1.10; older versions want the account
itself, so both are offered.
"""

from __future__ import annotations

from typing import Any

from . import demo as fake
from .base import Adapter, Context, Field, WidgetData, WidgetType, base_url


class KomgaAdapter(Adapter):
    kind = "komga"
    label = "Komga"
    category = "media"
    description = "Libraries, series and books, and what was added last."
    icon = "komga"
    #: Seen against a live Komga (06.09.2026).
    beta = False
    docs_url = "https://komga.org/docs/api/rest"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://komga:25600"),
        Field("api_key", "API key", type="password", secret=True, help="Account settings > API keys (Komga 1.10 and newer)."),
        Field("username", "E-mail address", help="Only for older versions without an API key."),
        Field("password", "Password", type="password", secret=True),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(
            kind="library",
            label="Library",
            description="Series, books and libraries in one number.",
            renderer="value",
            default_size=(2, 2),
            min_size=(1, 1),
            refresh_seconds=600,
            metrics=("series", "books"),
        ),
        WidgetType(
            kind="latest",
            label="Recently added",
            description="The books that arrived last.",
            renderer="list",
            default_size=(3, 3),
            refresh_seconds=600,
            options=(Field("limit", "Entries", type="number", default=6),),
        ),
    )

    def _headers(self, config: dict[str, Any]) -> dict[str, str]:
        key = str(config.get("api_key") or "")
        return {"X-API-Key": key} if key else {}

    def _auth(self, config: dict[str, Any]) -> tuple[str, str] | None:
        user = str(config.get("username") or "")
        return (user, str(config.get("password") or "")) if user and not config.get("api_key") else None

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, params: dict[str, Any] | None = None, cache: float = 120) -> Any:
        return await ctx.get_json(
            f"{base_url(config)}/api/v1{path}",
            headers=self._headers(config),
            auth=self._auth(config),
            params=params,
            verify=not config.get("insecure"),
            cache_seconds=cache,
        )

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        libraries = await self._get(config, ctx, "/libraries", cache=0)
        return f"Komga answers with {len(libraries) if isinstance(libraries, list) else 0} libraries."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "latest":
            limit = int(options.get("limit") or 6)
            payload = await self._get(config, ctx, "/books/latest", params={"size": limit}, cache=300)
            items = [
                {
                    "title": entry.get("metadata", {}).get("title") or entry.get("name") or "?",
                    "subtitle": entry.get("seriesTitle") or "",
                    "status": "ok",
                }
                for entry in (payload.get("content") or [])[:limit]
            ]
            return WidgetData(items=items, secondary=[{"label": "Entries", "value": len(items)}])

        libraries = await self._get(config, ctx, "/libraries", cache=600)
        series = await self._get(config, ctx, "/series", params={"size": 1}, cache=300)
        books = await self._get(config, ctx, "/books", params={"size": 1}, cache=300)
        return WidgetData(
            primary={"label": "Series", "value": int(series.get("totalElements") or 0)},
            secondary=[
                {"label": "Books", "value": int(books.get("totalElements") or 0)},
                {"label": "Libraries", "value": len(libraries) if isinstance(libraries, list) else 0},
            ],
            metrics={"series": float(series.get("totalElements") or 0), "books": float(books.get("totalElements") or 0)},
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        if widget_kind == "latest":
            rows = [("Harbour Tales #12", "Harbour Tales"), ("The Iron Ferry #3", "The Iron Ferry"), ("Northern Lines #7", "Northern Lines")]
            return WidgetData(
                items=[{"title": title, "subtitle": series, "status": "ok"} for title, series in rows],
                secondary=[{"label": "Entries", "value": len(rows)}],
            )
        books = fake.counter("komga-books", tick, 3140, 0.01)
        return WidgetData(
            primary={"label": "Series", "value": 218},
            secondary=[{"label": "Books", "value": books}, {"label": "Libraries", "value": 3}],
            metrics={"series": 218.0, "books": float(books)},
        )


ADAPTER = KomgaAdapter()
