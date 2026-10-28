"""Readeck: how many bookmarks there are, unread, favourites and archived, and the ones saved last.

Measured on 28.10.2026 against Readeck 0.23.5 (the official image) with an
API token of an administrator and three bookmarks of example.com, example.org
and iana.org, one archived, one favourite, one read.

⚠️ Every request has to say ``Accept: application/json``. Without it a missing
or wrong token is answered with 303 to the login page instead of 401, and a
card would call that an answer. With it: 401 ``{"status": 401, "message":
"Unauthorized"}``.

⚠️ The list carries the number of bookmarks in the header ``Total-Count``
(and ``Total-Pages``), not in the body, which is a bare array. Asking for one
entry is enough to count.

⚠️ Archived bookmarks are in the list unless ``is_archived=false`` is asked:
three bookmarks counted three with one of them archived, and ``read_status=unread``
counted two, the archived one among them. So the card counts the total with
the archive in it, and its reading list leaves the archive out.

``read_status`` takes ``unread``, ``reading`` and ``read``; ``is_marked`` is
the favourite. A bookmark has ``title``, ``site_name``, ``url``, ``created``
and, once Readeck has read the page, ``reading_time`` in minutes (absent
otherwise). It opens at ``/bookmarks/<id>`` in the interface. The version
stands in ``/api/info`` without a token.
"""

from __future__ import annotations

import time
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
    ago,
    base_url,
)

URL_HINT = "Check the URL; it is the address of Readeck itself, without /api."


class ReadeckAdapter(Adapter):
    kind = "readeck"
    label = "Readeck"
    category = "feeds"
    description = "How many bookmarks Readeck holds, unread, favourites and archived, and the ones saved last."
    icon = "readeck"
    beta = True
    docs_url = "https://readeck.org/en/docs/api"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://readeck:8000"),
        Field("token", "API token", type="password", secret=True, required=True,
              help="Settings > API Tokens > Create a new API token."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(kind="summary", label="Bookmarks", description="How many bookmarks there are, with those unread, favourites and archived.",
                   renderer="value", default_size=(3, 2), refresh_seconds=600, metrics=("bookmarks", "unread"),
                   parts=(("unread", "Unread"), ("marked", "Favourites"), ("archived", "Archived"))),
        WidgetType(kind="recent", label="Recent bookmarks", description="The bookmarks saved last, with their site and reading time.",
                   renderer="list", default_size=(3, 3), refresh_seconds=300,
                   options=(Field("limit", "Entries", type="number", default=8),
                            Field("unread", "Only unread bookmarks", type="bool", default=False))),
    )

    # -- talking to Readeck --------------------------------------------------

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, params: dict[str, Any] | None = None,
                   cache: float = 10) -> Any:
        response = await ctx.request(
            "GET", f"{base_url(config)}/api{path}",
            # ⚠️ Without Accept a refusal is a redirect to the login page; see the top of the file.
            headers={"Authorization": f"Bearer {config.get('token') or ''}", "Accept": "application/json"},
            params=params, verify=not config.get("insecure"), cache_seconds=cache, auth_errors=False,
        )
        if response.status_code in (401, 403):
            raise AuthFailed("Readeck rejected the API token.")
        if response.status_code >= 400:
            raise AdapterError(f"Readeck answered with HTTP {response.status_code}.", code="http_error", hint=URL_HINT)
        if response.status_code >= 300:
            raise AdapterError("Readeck sent the request on to another page.", code="not_json", hint=URL_HINT)
        try:
            answer = response.json()
        except ValueError as error:
            raise AdapterError("Readeck did not answer with JSON.", code="not_json",
                               hint="The URL probably points at a login page or a reverse proxy.") from error
        return answer, response

    async def _count(self, config: dict[str, Any], ctx: Context, **params: Any) -> int:
        answer, response = await self._get(config, ctx, "/bookmarks", {"limit": 1, **params})
        total = response.headers.get("Total-Count")
        if not isinstance(answer, list) or total is None or not total.isdigit():
            raise AdapterError("This address answers, but not the way Readeck does.", code="not_readeck", hint=URL_HINT)
        return int(total)

    # -- the hooks -----------------------------------------------------------

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        info, _ = await self._get(config, ctx, "/info", cache=0)
        if not isinstance(info, dict) or not isinstance(info.get("version"), dict):
            raise AdapterError("This address answers, but not the way Readeck does.", code="not_readeck", hint=URL_HINT)
        # The version is public; the count needs the token.
        count = await self._count(config, ctx)
        return f"Readeck {info['version'].get('canonical') or '?'} answers with {count} bookmarks."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        base = base_url(config)
        if widget_kind == "recent":
            unread = options.get("unread") is True
            params: dict[str, Any] = {"limit": max(1, min(50, int(options.get("limit") or 8))), "sort": "-created", "is_archived": "false"}
            if unread:
                params["read_status"] = "unread"
            answer, _ = await self._get(config, ctx, "/bookmarks", params)
            if not isinstance(answer, list):
                raise AdapterError("This address answers, but not the way Readeck does.", code="not_readeck", hint=URL_HINT)
            return self._recent(answer, unread, base)
        counts = {
            "total": await self._count(config, ctx),
            "unread": await self._count(config, ctx, read_status="unread"),
            "marked": await self._count(config, ctx, is_marked="true"),
            "archived": await self._count(config, ctx, is_archived="true"),
        }
        return self._summary(counts, base)

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def _summary(counts: dict[str, int], base: str) -> WidgetData:
        return WidgetData(
            status="ok",
            primary={"label": "Bookmarks", "value": counts["total"]},
            secondary=[
                {"label": "Unread", "value": counts["unread"], "part": "unread"},
                {"label": "Favourites", "value": counts["marked"], "part": "marked"},
                {"label": "Archived", "value": counts["archived"], "part": "archived"},
            ],
            link=f"{base}/bookmarks",
            metrics={"bookmarks": float(counts["total"]), "unread": float(counts["unread"])},
        )

    @staticmethod
    def _recent(bookmarks: list[Any], unread: bool, base: str) -> WidgetData:
        items = []
        for bookmark in bookmarks:
            if not isinstance(bookmark, dict):
                continue
            minutes = bookmark.get("reading_time")
            row: dict[str, Any] = {
                "title": str(bookmark.get("title") or bookmark.get("url") or "?"),
                "subtitle": " · ".join(part for part in (str(bookmark.get("site_name") or ""), f"{minutes} min" if minutes else "") if part),
                "value": ago(bookmark.get("created")),
            }
            if bookmark.get("id"):
                row["url"] = f"{base}/bookmarks/{bookmark['id']}"
            items.append(row)
        return WidgetData(status="ok", items=items, link=f"{base}/bookmarks",
                          meta={"empty": "Nothing unread." if unread else "No bookmarks saved yet."})

    # -- demo ----------------------------------------------------------------

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        base = "https://readeck.example.com"
        if widget_kind == "summary":
            fresh = 1 if fake.flicker("readeck-new", tick, 0.3) else 0
            return self._summary({"total": 268 + tick % 3 + fresh, "unread": 31 + fresh, "marked": 14, "archived": 92}, base)
        now = time.time()
        stamp = lambda seconds: time.strftime("%Y-%m-%dT%H:%M:%S.000000000Z", time.gmtime(now - seconds))  # noqa: E731
        bookmarks = [
            {"id": "a1", "title": "Backup guide", "site_name": "docs.example.com", "reading_time": 6, "created": stamp(1100)},
            {"id": "a2", "title": "ZFS on a small machine", "site_name": "blog.example.com", "reading_time": 11, "created": stamp(4 * 3600)},
            {"id": "a3", "title": "DNS cheat sheet", "site_name": "wiki.example.org", "created": stamp(2 * 86400)},
        ]
        return self._recent(bookmarks, options.get("unread") is True, base)


ADAPTER = ReadeckAdapter()
