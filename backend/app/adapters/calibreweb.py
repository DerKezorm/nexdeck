"""Calibre-Web: the book shelf.

⚠️ Calibre-Web has no API. It answers the address its own table view uses,
``/ajax/listbooks``, after a sign-in with the form; nexdeck keeps the session
cookie. That makes this adapter the most fragile of the family: an update of
Calibre-Web may move the address, and then the card says so.
"""

from __future__ import annotations

from typing import Any

from . import demo as fake
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


class CalibreWebAdapter(Adapter):
    kind = "calibreweb"
    label = "Calibre-Web"
    category = "media"
    description = "How many books are on the shelf, and which arrived last."
    icon = "calibre-web"
    docs_url = "https://github.com/janeczku/calibre-web/wiki"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://calibre-web:8083"),
        Field("username", "User name", required=True),
        Field("password", "Password", type="password", secret=True, required=True),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(
            kind="library",
            label="Library",
            description="The number of books on the shelf.",
            renderer="value",
            default_size=(2, 2),
            min_size=(1, 1),
            refresh_seconds=900,
            metrics=("books",),
        ),
        WidgetType(
            kind="latest",
            label="Recently added",
            description="The books that arrived last.",
            renderer="list",
            default_size=(3, 3),
            refresh_seconds=900,
            options=(Field("limit", "Entries", type="number", default=6),),
        ),
    )

    async def _cookie(self, config: dict[str, Any], ctx: Context, force: bool = False) -> str:
        cached = ctx.cache.get("calibreweb_cookie")
        if cached and not force:
            return cached
        response = await ctx.request(
            "POST",
            f"{base_url(config)}/login",
            data={"username": str(config.get("username") or ""), "password": str(config.get("password") or ""), "submit": ""},
            verify=not config.get("insecure"),
        )
        # ⚠️ From the sign-in itself. Calibre-Web answers with a redirect, the
        # session cookie stands in that redirect, and the last answer in the
        # chain is the page after it. Reading only that worked while the shared
        # client kept cookies and carried the session there. Found on 12.09.2026.
        cookie = next((answer.cookies.get("session") for answer in (*response.history, response) if answer.cookies.get("session")), "")
        if not cookie:
            raise AuthFailed("Calibre-Web did not open a session; check the account.")
        ctx.cache["calibreweb_cookie"] = f"session={cookie}"
        return ctx.cache["calibreweb_cookie"]

    async def _books(self, config: dict[str, Any], ctx: Context, count: int, retry: bool = True) -> dict[str, Any]:
        cookie = await self._cookie(config, ctx)
        response = await ctx.request(
            "GET",
            f"{base_url(config)}/ajax/listbooks",
            params={"page": 1, "per_page": count, "sort": "new", "order": "desc"},
            headers={"Cookie": cookie, "X-Requested-With": "XMLHttpRequest"},
            verify=not config.get("insecure"),
        )
        if response.status_code in (401, 403) and retry:
            await self._cookie(config, ctx, force=True)
            return await self._books(config, ctx, count, retry=False)
        if response.status_code >= 400:
            raise AdapterError(f"Calibre-Web answered with HTTP {response.status_code}.", code="http_error")
        try:
            payload = response.json()
        except ValueError as failure:
            raise AdapterError(
                "Calibre-Web did not answer with data.",
                code="not_json",
                hint="This adapter uses the address of Calibre-Web's own table view; a newer version may have moved it.",
            ) from failure
        return payload if isinstance(payload, dict) else {}

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        payload = await self._books(config, ctx, 1)
        return f"Calibre-Web answers with {int(payload.get('totalNotFiltered') or 0)} books."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        limit = int(options.get("limit") or 6)
        payload = await self._books(config, ctx, limit if widget_kind == "latest" else 1)
        total = int(payload.get("totalNotFiltered") or payload.get("recordsTotal") or 0)
        if widget_kind == "latest":
            items = [
                {"title": row.get("title") or "?", "subtitle": ", ".join(row.get("authors") or [])[:60], "status": "ok"}
                for row in (payload.get("rows") or [])[:limit]
            ]
            return WidgetData(items=items, secondary=[{"label": "Books", "value": total}])
        return WidgetData(primary={"label": "Books", "value": total}, metrics={"books": float(total)})

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        total = fake.counter("calibre-books", tick, 2480, 0.004)
        if widget_kind == "latest":
            rows = [("A History of Harbours", "R. Meyer"), ("The Long Way Home", "T. Bright"), ("Northern Lines", "S. Vance")]
            return WidgetData(
                items=[{"title": title, "subtitle": author, "status": "ok"} for title, author in rows],
                secondary=[{"label": "Books", "value": total}],
            )
        return WidgetData(primary={"label": "Books", "value": total}, metrics={"books": float(total)})


ADAPTER = CalibreWebAdapter()
