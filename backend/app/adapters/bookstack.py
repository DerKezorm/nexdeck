"""BookStack: how many pages, books, chapters and shelves there are, and the pages changed last.

Measured on 28.10.2026 against BookStack v26.09.2 (linuxserver image with
MariaDB), an API token of the admin, two books, one chapter, two pages and
one shelf, all invented.

⚠️ Every list answers ``total`` beside the page, so asking for one entry is
enough to count. Pages, books, chapters and shelves share one numbering: the
first chapter had the id 3 after two books, which is why an id is never a
count.

⚠️ ``/api/pages`` leaves drafts out and counts what the token may see: a role
without the right to view a book does not count its pages.

⚠️ A page in the list carries ``book_slug`` and ``slug`` but not the name of
its book (``book_id`` only), and ``created_by`` and ``updated_by`` are bare
ids there. The card reads the books once to name them.

⚠️ A wrong token and a missing one both get 401 with ``{"error": {"code": 401}}``.
The token is sent as ``Authorization: Token <id>:<secret>``.
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

URL_HINT = "Check the URL; it is the address of BookStack itself, without /api."


class BookStackAdapter(Adapter):
    kind = "bookstack"
    label = "BookStack"
    category = "other"
    description = "How many pages, books, chapters and shelves BookStack holds, and the pages changed last."
    icon = "bookstack"
    beta = True
    docs_url = "https://demo.bookstackapp.com/api/docs"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://bookstack:6875"),
        Field("token_id", "Token ID", type="password", secret=True, required=True,
              help="Profile > API Tokens > Create Token. The role needs the permission Access system API."),
        Field("token_secret", "Token secret", type="password", secret=True, required=True,
              help="Shown once when the token is made."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(kind="summary", label="Library", description="How many pages there are, with the books, chapters and shelves.",
                   renderer="value", default_size=(3, 2), refresh_seconds=600, metrics=("pages",),
                   parts=(("books", "Books"), ("chapters", "Chapters"), ("shelves", "Shelves"))),
        WidgetType(kind="recent", label="Recently changed pages", description="The pages changed last, with their book.",
                   renderer="list", default_size=(3, 3), refresh_seconds=300,
                   options=(Field("limit", "Entries", type="number", default=8),)),
    )

    # -- talking to BookStack ------------------------------------------------

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, params: dict[str, Any] | None = None,
                   cache: float = 10) -> dict[str, Any]:
        token = f"{config.get('token_id') or ''}:{config.get('token_secret') or ''}"
        response = await ctx.request(
            "GET", f"{base_url(config)}/api{path}", headers={"Authorization": f"Token {token}"},
            params=params, verify=not config.get("insecure"), cache_seconds=cache, auth_errors=False,
        )
        if response.status_code in (401, 403):
            raise AuthFailed("BookStack rejected the API token.")
        if response.status_code >= 400:
            raise AdapterError(f"BookStack answered with HTTP {response.status_code}.", code="http_error", hint=URL_HINT)
        try:
            answer = response.json()
        except ValueError as error:
            raise AdapterError("BookStack did not answer with JSON.", code="not_json",
                               hint="The URL probably points at a login page or a reverse proxy.") from error
        if not isinstance(answer, dict):
            raise AdapterError("This address answers, but not the way BookStack does.", code="not_bookstack", hint=URL_HINT)
        return answer

    async def _list(self, config: dict[str, Any], ctx: Context, path: str, **params: Any) -> dict[str, Any]:
        answer = await self._get(config, ctx, path, params)
        if not isinstance(answer.get("data"), list) or "total" not in answer:
            raise AdapterError("This address answers, but not the way BookStack does.", code="not_bookstack", hint=URL_HINT)
        return answer

    async def _count(self, config: dict[str, Any], ctx: Context, path: str) -> int:
        return int((await self._list(config, ctx, path, count=1)).get("total") or 0)

    # -- the hooks -----------------------------------------------------------

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        system = await self._get(config, ctx, "/system", cache=0)
        pages = await self._count(config, ctx, "/pages")
        return f"BookStack {system.get('version') or '?'} answers with {pages} pages."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        base = base_url(config)
        if widget_kind == "recent":
            limit = max(1, min(50, int(options.get("limit") or 8)))
            pages = await self._list(config, ctx, "/pages", count=limit, sort="-updated_at")
            books = await self._list(config, ctx, "/books", count=500)
            return self._recent(pages["data"], books["data"], base)
        counts = {
            "pages": await self._count(config, ctx, "/pages"),
            "books": await self._count(config, ctx, "/books"),
            "chapters": await self._count(config, ctx, "/chapters"),
            "shelves": await self._count(config, ctx, "/shelves"),
        }
        return self._summary(counts, base)

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def _summary(counts: dict[str, int], base: str) -> WidgetData:
        return WidgetData(
            status="ok",
            primary={"label": "Pages", "value": counts["pages"]},
            secondary=[
                {"label": "Books", "value": counts["books"], "part": "books"},
                {"label": "Chapters", "value": counts["chapters"], "part": "chapters"},
                {"label": "Shelves", "value": counts["shelves"], "part": "shelves"},
            ],
            link=base,
            metrics={"pages": float(counts["pages"])},
        )

    @staticmethod
    def _recent(pages: list[Any], books: list[Any], base: str) -> WidgetData:
        names = {str(book.get("id")): str(book.get("name") or "") for book in books if isinstance(book, dict)}
        items = []
        for page in pages:
            if not isinstance(page, dict):
                continue
            row: dict[str, Any] = {
                "title": str(page.get("name") or page.get("slug") or "?"),
                # ⚠️ Only the id of the book stands in the list; see the top of the file.
                "subtitle": names.get(str(page.get("book_id")), ""),
                "value": ago(page.get("updated_at")),
            }
            if page.get("book_slug") and page.get("slug"):
                row["url"] = f"{base}/books/{page['book_slug']}/page/{page['slug']}"
            items.append(row)
        return WidgetData(status="ok", items=items, link=base, meta={"empty": "No pages yet."})

    # -- demo ----------------------------------------------------------------

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        base = "https://bookstack.example.com"
        if widget_kind == "summary":
            fresh = 1 if fake.flicker("bookstack-new", tick, 0.3) else 0
            return self._summary({"pages": 184 + tick % 3 + fresh, "books": 12, "chapters": 31, "shelves": 4}, base)
        now = time.time()
        stamp = lambda seconds: time.strftime("%Y-%m-%dT%H:%M:%S.000000Z", time.gmtime(now - seconds))  # noqa: E731
        books = [{"id": 1, "name": "Homelab guide"}, {"id": 2, "name": "Recipes"}]
        pages = [
            {"name": "Backup plan", "slug": "backup-plan", "book_id": 1, "book_slug": "homelab-guide", "updated_at": stamp(900)},
            {"name": "DNS notes", "slug": "dns-notes", "book_id": 1, "book_slug": "homelab-guide", "updated_at": stamp(4 * 3600)},
            {"name": "Tomato soup", "slug": "tomato-soup", "book_id": 2, "book_slug": "recipes", "updated_at": stamp(2 * 86400)},
        ]
        return self._recent(pages, books, base)


ADAPTER = BookStackAdapter()
