"""Linkding: how many bookmarks there are, and the ones saved last.

Measured on 27.09.2026 against Linkding 1.47.0 (sissbruecker/linkding),
with a superuser and a second account without any rights, an API token
each, five invented bookmarks for the first (two unread, two shared, one
archived, one without a title) and one shared bookmark for the second.
Sharing was measured switched off and on.

⚠️ ``/api/bookmarks/`` leaves the archived ones out: it counted four of
five. The archive is ``/api/bookmarks/archived/``, and the card adds both.
Every list answers ``count`` beside the page (100 by default), so asking
for one entry is enough to know how many there are.

⚠️ Every account sees its own bookmarks and nothing else, a superuser as
much as anybody: the second account counted one, the superuser five.
``/api/bookmarks/shared/`` is the other way round and holds the shared
bookmarks of every account whose profile allows sharing, its own included.
Tags are per account as well: ``/api/tags/`` counted the superuser's seven
and not the second account's one.

⚠️ The flag ``shared`` on a bookmark means nothing while sharing is off in
the profile: ``?shared=yes`` counted two, ``/api/bookmarks/shared/`` none.
The card counts shared bookmarks only when ``enable_sharing`` in
``/api/user/profile/`` is on, and leaves the row out otherwise.

⚠️ Unread is asked for with the search ``!unread``, which older versions
understand too; 1.47.0 also took ``?unread=yes`` and both counted two.

⚠️ A bookmark saved without scraping has the title ``""``; the card falls
back to ``website_title`` (null throughout on 1.47.0) and then to the host.

⚠️ A wrong token gets 401 ``{"detail": "Invalid token."}``, a missing one
401 "Authentication credentials were not provided." 1.47.0 takes the
keyword ``Bearer`` as well as ``Token``; the adapter sends ``Token``,
which is what older versions know. The version stands in the profile.
"""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import urlsplit

from . import demo as fake
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

URL_HINT = "Check the URL; it is the address of Linkding itself, without /api."


class LinkdingAdapter(Adapter):
    kind = "linkding"
    label = "Linkding"
    category = "feeds"
    description = "How many bookmarks Linkding holds, unread, archived and shared, and the ones saved last."
    icon = "linkding"
    beta = False
    docs_url = "https://linkding.link/api/"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://linkding:9090"),
        Field("token", "API token", type="password", secret=True, required=True,
              help="Settings > Integrations > REST API in Linkding. Each account sees its own bookmarks only."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(kind="summary", label="Bookmarks", description="How many bookmarks there are, with those unread, archived and shared, and the tags.",
                   renderer="value", default_size=(3, 2), refresh_seconds=600, metrics=("bookmarks",),
                   parts=(("unread", "Unread"), ("archived", "Archived"), ("shared", "Shared"), ("tags", "Tags"))),
        WidgetType(kind="recent", label="Recent bookmarks", description="The bookmarks saved last, with their address and tags.",
                   renderer="list", default_size=(3, 3), refresh_seconds=300,
                   options=(Field("limit", "Entries", type="number", default=8),
                            Field("unread", "Only unread bookmarks", type="bool", default=False))),
    )

    # -- talking to Linkding -------------------------------------------------

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, params: dict[str, Any] | None = None,
                   cache: float = 10) -> dict[str, Any]:
        response = await ctx.request(
            "GET", f"{base_url(config)}/api{path}", headers={"Authorization": f"Token {config.get('token') or ''}"},
            params=params, verify=not config.get("insecure"), cache_seconds=cache, auth_errors=False,
        )
        if response.status_code in (401, 403):
            raise AuthFailed("Linkding rejected the API token.")
        if response.status_code >= 400:
            raise AdapterError(f"Linkding answered with HTTP {response.status_code}.", code="http_error", hint=URL_HINT)
        try:
            answer = response.json()
        except ValueError as error:
            raise AdapterError("Linkding did not answer with JSON.", code="not_json",
                               hint="The URL probably points at a login page or a reverse proxy.") from error
        if not isinstance(answer, dict):
            raise AdapterError("This address answers, but not the way Linkding does.", code="not_linkding", hint=URL_HINT)
        return answer

    async def _page(self, config: dict[str, Any], ctx: Context, path: str, params: dict[str, Any]) -> dict[str, Any]:
        answer = await self._get(config, ctx, path, params)
        if not isinstance(answer.get("results"), list) or "count" not in answer:
            raise AdapterError("This address answers, but not the way Linkding does.", code="not_linkding", hint=URL_HINT)
        return answer

    async def _count(self, config: dict[str, Any], ctx: Context, path: str, **params: Any) -> int:
        answer = await self._page(config, ctx, path, {"limit": 1, **params})
        return int(answer.get("count") or 0)

    # -- the hooks -----------------------------------------------------------

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        profile = await self._get(config, ctx, "/user/profile/", cache=0)
        count = await self._count(config, ctx, "/bookmarks/") + await self._count(config, ctx, "/bookmarks/archived/")
        return f"Linkding {profile.get('version') or '?'} answers with {count} bookmarks."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        base = base_url(config)
        if widget_kind == "recent":
            unread = options.get("unread") is True
            params: dict[str, Any] = {"limit": max(1, int(options.get("limit") or 8))}
            if unread:
                params["q"] = "!unread"
            answer = await self._page(config, ctx, "/bookmarks/", params)
            return self._recent(answer["results"], unread, base)
        profile = await self._get(config, ctx, "/user/profile/", cache=60)
        counts = {
            "active": await self._count(config, ctx, "/bookmarks/"),
            "archived": await self._count(config, ctx, "/bookmarks/archived/"),
            "unread": await self._count(config, ctx, "/bookmarks/", q="!unread"),
            "tags": await self._count(config, ctx, "/tags/"),
        }
        # ⚠️ The flag counts for nothing while sharing is off.
        if profile.get("enable_sharing") is True:
            counts["shared"] = await self._count(config, ctx, "/bookmarks/", shared="yes")
        return self._summary(counts, base)

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def _summary(counts: dict[str, int], base: str) -> WidgetData:
        total = counts["active"] + counts["archived"]
        secondary: list[dict[str, Any]] = [
            {"label": "Unread", "value": counts["unread"], "part": "unread"},
            {"label": "Archived", "value": counts["archived"], "part": "archived"},
        ]
        if "shared" in counts:
            secondary.append({"label": "Shared", "value": counts["shared"], "part": "shared"})
        secondary.append({"label": "Tags", "value": counts["tags"], "part": "tags"})
        return WidgetData(
            status="ok",
            primary={"label": "Bookmarks", "value": total},
            secondary=secondary,
            link=f"{base}/bookmarks",
            metrics={"bookmarks": float(total)},
        )

    @staticmethod
    def _recent(bookmarks: list[Any], unread: bool, base: str) -> WidgetData:
        items = []
        for bookmark in bookmarks:
            if not isinstance(bookmark, dict):
                continue
            address = str(bookmark.get("url") or "")
            host = urlsplit(address).hostname or ""
            tags = ", ".join(str(tag) for tag in (bookmark.get("tag_names") or [])[:3] if tag)
            # ⚠️ An empty title is common; see the top of the file.
            title = str(bookmark.get("title") or bookmark.get("website_title") or "")
            row: dict[str, Any] = {
                "title": title or host or address or "?",
                # The host once, not as the title and again under it.
                "subtitle": " · ".join(part for part in (host if title else "", tags) if part),
                "value": ago(bookmark.get("date_added")),
            }
            if address:
                row["url"] = address
            items.append(row)
        return WidgetData(
            status="ok",
            items=items,
            link=f"{base}/bookmarks",
            meta={"empty": "Nothing unread." if unread else "No bookmarks saved yet."},
        )

    # -- demo ----------------------------------------------------------------

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        base = "https://linkding.example.com"
        if widget_kind == "summary":
            fresh = 1 if fake.flicker("linkding-new", tick, 0.3) else 0
            return self._summary({"active": 412 + tick % 3 + fresh, "archived": 57, "unread": 18 + fresh, "shared": 9, "tags": 64}, base)
        now = time.time()
        stamp = lambda seconds: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - seconds))  # noqa: E731
        bookmarks = [
            {"url": "https://docs.example.com/backup-guide", "title": "Backup guide", "tag_names": ["backup", "homelab"], "date_added": stamp(1200)},
            {"url": "https://blog.example.com/zfs-small-machine", "title": "ZFS on a small machine", "tag_names": ["storage"], "date_added": stamp(3 * 3600)},
            {"url": "https://news.example.com/proxy-notes", "title": "", "tag_names": [], "date_added": stamp(9 * 3600)},
            {"url": "https://wiki.example.org/dns", "title": "DNS cheat sheet", "tag_names": ["network", "dns", "reference"], "date_added": stamp(2 * 86400)},
        ]
        return self._recent(bookmarks, options.get("unread") is True, base)


ADAPTER = LinkdingAdapter()
