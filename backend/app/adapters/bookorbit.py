"""BookOrbit: what is being read, what came into the library last, and how big it is.

Measured against BookOrbit v2.9.0 (ghcr.io/bookorbit/bookorbit) on 11.09.2026,
with five EPUB files in one library, two of them read part of the way through
and one marked as read.

⚠️ There is no API key. The API signs in with a user name and a password at
``/api/v1/auth/login`` and hands back a JWT that lasts fifteen minutes, plus a
refresh cookie. Signing in is limited to five times a minute, so the token is
kept and asked for again only when it runs out or is refused.

⚠️ A missing token, a made-up one and an expired one all get 401
``Unauthorized``; a wrong password gets 401 ``Invalid credentials``.

⚠️ The dashboard widgets of the web interface are cached per user: "currently
reading" for two minutes, the library overview for five. Progress saved a
second ago showed up at once on the ``continue-reading`` shelf and not in the
widget, so the reading card asks the shelf.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from typing import Any

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

#: The access token lasts 15 minutes (measured: ``exp`` minus ``iat`` is 900 s).
TOKEN_SECONDS = 12 * 60
#: A shelf takes at most 50 books; the web interface never asks for more.
SHELF_MAX = 50


def _authors(book: dict[str, Any]) -> str:
    return ", ".join(str(name) for name in book.get("authors") or [] if name)


def _progress(book: dict[str, Any]) -> float | None:
    try:
        return max(0.0, min(100.0, float(book.get("readingProgress"))))
    except (TypeError, ValueError):
        return None


class BookOrbitAdapter(Adapter):
    kind = "bookorbit"
    label = "BookOrbit"
    category = "media"
    description = "What is being read, what came into the library last, and how big it is."
    icon = "bookorbit"
    #: Confirmed against a live instance on 2026-09-11.
    beta = False
    docs_url = "https://github.com/bookorbit/bookorbit"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://bookorbit:3000"),
        Field("username", "User name", required=True),
        Field("password", "Password", type="password", secret=True, required=True,
              help="BookOrbit has no API keys. The cards see what this user may see."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(kind="reading", label="Reading now", description="The books that are part of the way through, the one read last first.",
                   renderer="list", default_size=(3, 3), refresh_seconds=300, metrics=("reading",),
                   options=(Field("limit", "Entries", type="number", default=6),)),
        WidgetType(kind="recent", label="Recently added", description="The books that came into the library last.",
                   renderer="list", default_size=(3, 3), refresh_seconds=900,
                   options=(Field("limit", "Entries", type="number", default=8),)),
        WidgetType(kind="summary", label="Library", description="Books in the library, how many are being read and how many authors.",
                   renderer="value", default_size=(3, 2), refresh_seconds=900, metrics=("books",)),
    )

    # -- talking to BookOrbit ------------------------------------------------

    async def _token(self, config: dict[str, Any], ctx: Context, force: bool = False) -> str:
        kept = ctx.cache.get("bookorbit_token")
        if kept and not force and kept[0] > time.time():
            return str(kept[1])
        response = await ctx.request(
            "POST", f"{base_url(config)}/api/v1/auth/login",
            json_body={"username": str(config.get("username") or ""), "password": str(config.get("password") or "")},
            headers={"Accept": "application/json"}, verify=not config.get("insecure"), auth_errors=False,
        )
        if response.status_code in (400, 401, 403):
            raise AuthFailed("BookOrbit rejected the user name or the password.")
        if response.status_code == 429:
            raise AdapterError("BookOrbit refused to sign in again so soon.", code="rate_limited",
                               hint="It allows five sign-ins a minute. The card tries again at its next refresh.")
        if response.status_code >= 400:
            raise AdapterError(f"BookOrbit answered the sign-in with HTTP {response.status_code}.", code="http_error",
                               hint="Check the URL; it is the address of BookOrbit itself, without /api.")
        try:
            token = str((response.json() or {}).get("accessToken") or "")
        except (ValueError, AttributeError) as error:
            raise AdapterError("BookOrbit did not answer the sign-in with JSON.", code="not_json",
                               hint="The URL probably points at something else than BookOrbit.") from error
        if not token:
            raise AdapterError("This address answers, but not the way BookOrbit does.", code="not_bookorbit")
        ctx.cache["bookorbit_token"] = (time.time() + TOKEN_SECONDS, token)
        return token

    async def _json(self, config: dict[str, Any], ctx: Context, path: str, params: dict[str, Any] | None = None,
                    cache: float = 30) -> Any:
        for attempt in (0, 1):
            token = await self._token(config, ctx, force=attempt == 1)
            response = await ctx.request(
                "GET", f"{base_url(config)}/api/v1{path}",
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                params=params, verify=not config.get("insecure"), cache_seconds=cache if attempt == 0 else 0, auth_errors=False,
            )
            # A token that ran out early (a restart with a new secret) is refused like a made-up one: sign in once more.
            if response.status_code != 401 or attempt == 1:
                break
            ctx.forget_answers()
        if response.status_code in (401, 403):
            raise AuthFailed("BookOrbit refused the signed-in user.")
        if response.status_code >= 400:
            raise AdapterError(f"BookOrbit answered with HTTP {response.status_code}.", code="http_error",
                               hint="Check the URL; it is the address of BookOrbit itself, without /api.")
        try:
            return response.json()
        except ValueError as error:
            raise AdapterError("BookOrbit did not answer with JSON.", code="not_json",
                               hint="The URL probably points at something else than BookOrbit.") from error

    async def _shelf(self, config: dict[str, Any], ctx: Context, shelf: str, limit: int) -> list[dict[str, Any]]:
        books = await self._json(config, ctx, f"/dashboard/scrollers/{shelf}", {"limit": max(1, min(SHELF_MAX, limit))})
        if not isinstance(books, list):
            raise AdapterError("This address answers, but not the way BookOrbit does.", code="not_bookorbit")
        return [one for one in books if isinstance(one, dict)]

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        info = await self._json(config, ctx, "/app-info", cache=0)
        overview = await self._json(config, ctx, "/dashboard/widgets/library-overview", cache=0)
        if not isinstance(info, dict) or not isinstance(overview, dict):
            raise AdapterError("This address answers, but not the way BookOrbit does.", code="not_bookorbit")
        return f"BookOrbit {info.get('version') or '?'} answers with {int(overview.get('totalBooks') or 0)} books."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "summary":
            overview = await self._json(config, ctx, "/dashboard/widgets/library-overview")
            if not isinstance(overview, dict) or "totalBooks" not in overview:
                raise AdapterError("This address answers, but not the way BookOrbit does.", code="not_bookorbit")
            reading = await self._shelf(config, ctx, "continue-reading", SHELF_MAX)
            return self._summary(overview, len(reading))
        limit = max(1, int(options.get("limit") or (6 if widget_kind == "reading" else 8)))
        if widget_kind == "recent":
            return self._recent(await self._shelf(config, ctx, "recently-added", limit), time.time())
        return self._reading(await self._shelf(config, ctx, "continue-reading", limit))

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def _reading(books: list[dict[str, Any]]) -> WidgetData:
        items = []
        for book in books:
            share = _progress(book)
            row: dict[str, Any] = {"title": str(book.get("title") or "?"), "subtitle": _authors(book), "status": "ok",
                                   "value": f"{share:.0f}%" if share is not None else ""}
            if share is not None:
                row["progress"] = share
            items.append(row)
        return WidgetData(status="ok", items=items, meta={"empty": "Nothing is being read."},
                          metrics={"reading": float(len(items))})

    @staticmethod
    def _recent(books: list[dict[str, Any]], now: float) -> WidgetData:
        items = [{"title": str(book.get("title") or "?"), "subtitle": _authors(book), "value": ago(book.get("addedAt"), now=now)}
                 for book in books]
        return WidgetData(status="ok", items=items, meta={"empty": "No books yet."})

    @staticmethod
    def _summary(overview: dict[str, Any], reading: int) -> WidgetData:
        books = int(overview.get("totalBooks") or 0)
        secondary: list[dict[str, Any]] = [{"label": "Being read", "value": reading},
                                           {"label": "Authors", "value": int(overview.get("totalAuthors") or 0)}]
        return WidgetData(status="ok", primary={"label": "Books", "value": books}, secondary=secondary,
                          metrics={"books": float(books)})

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        now = datetime.now(UTC)
        shelf = [
            {"title": "The Quiet Harbour", "authors": ["Ada Example"], "readingProgress": 42 + tick % 5,
             "addedAt": (now - timedelta(hours=5)).isoformat()},
            {"title": "Notes on Copper Wire", "authors": ["Ben Sample"], "readingProgress": 73,
             "addedAt": (now - timedelta(days=2)).isoformat()},
            {"title": "A Garden of Small Machines", "authors": ["Cara Placeholder", "Dan Invented"], "readingProgress": 8,
             "addedAt": (now - timedelta(days=9)).isoformat()},
        ]
        if widget_kind == "summary":
            return self._summary({"totalBooks": 1_284 + tick % 3, "totalAuthors": 612, "totalStorageBytes": 18_400_000_000}, 3)
        if widget_kind == "recent":
            return self._recent(shelf, now.timestamp())
        return self._reading(shelf[: int(options.get("limit") or 6)])


ADAPTER = BookOrbitAdapter()
