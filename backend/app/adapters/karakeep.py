"""Karakeep: what was saved lately, and how much is still waiting to be read.

Measured against Karakeep 0.33.2 on 11.09.2026, with an account made through
its sign-up call, an API key traded for email and password the way the
browser extension does it, and four bookmarks: three links (one tagged, one
a favourite) and a note that was archived.

⚠️ Counting needs no paging. ``/api/v1/users/me/stats`` answers with the
number of bookmarks, favourites, archived ones, lists and tags, and with how
many were saved this week. The bookmark list itself only pages by cursor.

⚠️ A missing and a wrong key both get 401 ``Unauthorized`` as plain text.
"""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import urlsplit

from .base import (
    Adapter,
    AdapterError,
    AuthFailed,
    Context,
    Field,
    WidgetData,
    WidgetType,
    ago,
    base_url,
)


class KarakeepAdapter(Adapter):
    kind = "karakeep"
    label = "Karakeep"
    category = "feeds"
    description = "What was saved lately, and how much is still waiting to be read."
    icon = "karakeep"
    beta = False
    docs_url = "https://docs.karakeep.app/API/karakeep-api"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://karakeep:3000"),
        Field("api_key", "API key", type="password", secret=True, required=True, help="Settings > API Keys > New API key."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(kind="recent", label="Recent bookmarks", description="The latest saved links and notes that are not archived.",
                   renderer="list", default_size=(3, 3), refresh_seconds=300,
                   options=(Field("limit", "Entries", type="number", default=8),
                            Field("favourites", "Only favourites", type="bool", default=False))),
        WidgetType(kind="summary", label="Reading list", description="How much is not archived yet, and what came in this week.",
                   renderer="value", default_size=(3, 2), refresh_seconds=600, metrics=("to_read",)),
    )

    async def _json(self, config: dict[str, Any], ctx: Context, path: str, params: dict[str, Any] | None = None, cache: float = 10) -> Any:
        response = await ctx.request(
            "GET", f"{base_url(config)}/api/v1{path}", headers={"Authorization": f"Bearer {config.get('api_key') or ''}"},
            params=params, verify=not config.get("insecure"), cache_seconds=cache, auth_errors=False,
        )
        if response.status_code in (401, 403):
            raise AuthFailed("Karakeep rejected the API key.")
        if response.status_code >= 400:
            raise AdapterError(f"Karakeep answered with HTTP {response.status_code}.", code="http_error",
                               hint="Check the URL; it is the address of Karakeep itself, without /api.")
        try:
            answer = response.json()
        except ValueError as error:
            raise AdapterError("Karakeep did not answer with JSON.", code="not_json",
                               hint="The URL probably points at a login page or a reverse proxy.") from error
        if not isinstance(answer, dict):
            raise AdapterError("This address answers, but not the way Karakeep does.", code="not_karakeep")
        return answer

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        stats = await self._json(config, ctx, "/users/me/stats", cache=0)
        if "numBookmarks" not in stats:
            raise AdapterError("This address answers, but not the way Karakeep does.", code="not_karakeep")
        return f"Karakeep answers with {stats['numBookmarks']} bookmarks."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "summary":
            return self._summary(await self._json(config, ctx, "/users/me/stats"))
        params: dict[str, Any] = {"limit": max(1, int(options.get("limit") or 8))}
        params.update({"favourited": "true"} if options.get("favourites") else {"archived": "false"})
        answer = await self._json(config, ctx, "/bookmarks", params=params)
        if not isinstance(answer.get("bookmarks"), list):
            raise AdapterError("This address answers, but not the way Karakeep does.", code="not_karakeep")
        return self._recent(answer["bookmarks"], bool(options.get("favourites")), base_url(config))

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def _summary(stats: dict[str, Any]) -> WidgetData:
        def count(key: str) -> int:
            return int(stats.get(key) or 0)

        to_read = max(0, count("numBookmarks") - count("numArchived"))
        activity = stats.get("bookmarkingActivity") if isinstance(stats.get("bookmarkingActivity"), dict) else {}
        this_week = int(activity.get("thisWeek") or 0)
        secondary: list[dict[str, Any]] = [{"label": "Bookmarks", "value": count("numBookmarks")}]
        secondary += [{"label": label, "value": value} for label, value in (("This week", this_week), ("Favourites", count("numFavorites"))) if value]
        return WidgetData(
            status="ok",
            primary={"label": "To read", "value": to_read},
            secondary=secondary,
            metrics={"to_read": float(to_read)},
        )

    @staticmethod
    def _recent(bookmarks: list[Any], favourites: bool, base: str) -> WidgetData:
        items = []
        for bookmark in bookmarks:
            if not isinstance(bookmark, dict):
                continue
            content = bookmark.get("content") if isinstance(bookmark.get("content"), dict) else {}
            kind = str(content.get("type") or "")
            link = str(content.get("url") or "")
            if kind == "text":
                text = " ".join(str(content.get("text") or "").split())
                title = bookmark.get("title") or (text[:80] + ("…" if len(text) > 80 else ""))
                where = "Note"
            else:
                title = bookmark.get("title") or content.get("title") or link or content.get("fileName") or "?"
                where = urlsplit(link).hostname or ("File" if kind == "asset" else "")
            tags = [str(tag.get("name")) for tag in bookmark.get("tags") or [] if isinstance(tag, dict) and tag.get("name")]
            row: dict[str, Any] = {
                "title": str(title),
                "subtitle": " · ".join(part for part in (where, ", ".join(tags[:3])) if part),
                "value": ago(bookmark.get("createdAt")),
                # A link opens where it points; a note or a file opens in Karakeep.
                "url": link if kind == "link" and link else f"{base}/dashboard/preview/{bookmark.get('id')}",
            }
            items.append(row)
        return WidgetData(
            status="ok",
            items=items,
            meta={"empty": "No favourites yet." if favourites else "Nothing waiting to be read."},
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        if widget_kind == "summary":
            return self._summary({"numBookmarks": 412, "numArchived": 371 - tick % 3, "numFavorites": 23, "bookmarkingActivity": {"thisWeek": 6}})

        def saved(hours: float) -> str:
            return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(time.time() - hours * 3600))

        bookmarks = [
            {"id": "a1", "createdAt": saved(1), "tags": [{"name": "homelab"}], "content": {"type": "link", "url": "https://blog.example.com/zfs-small", "title": "ZFS on a small machine"}},
            {"id": "b2", "createdAt": saved(5), "tags": [], "content": {"type": "text", "text": "Remember to rotate the backup disks before the holidays."}},
            {"id": "c3", "createdAt": saved(28), "tags": [{"name": "network"}, {"name": "vpn"}], "content": {"type": "link", "url": "https://news.example.com/wireguard", "title": "WireGuard without the headaches"}},
        ]
        return self._recent(bookmarks, bool(options.get("favourites")), "https://karakeep.example.com")


ADAPTER = KarakeepAdapter()
