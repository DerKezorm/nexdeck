"""Trilium: how many notes there are, how many changed this week, and the notes changed last.

Measured on 28.10.2026 against TriliumNext 0.106.1 (the official image, the
database made by its setup page, which holds the demo notes) with an ETAPI
token and three invented notes.

⚠️ ETAPI sends the token as the whole ``Authorization`` header, without a
keyword. A wrong or missing token gets 401
``{"status": 401, "code": "NOT_AUTHENTICATED"}``.

⚠️ ``GET /etapi/notes`` needs a search, and a search with no condition at all
is refused, so the card asks ``note.noteId != ''``. It answers every note in
one list (no total, no page), about 0.9 kB each with its attributes, so the
card counts that list once and takes the changed-this-week row out of it
instead of asking again. ``orderBy=utcDateModified`` with ``orderDirection=desc``
and ``limit`` gives the notes changed last. The root note comes back as a
note called ``root``; it is not counted and not listed.

⚠️ Trilium writes its times as ``2026-10-28 01:37:10.661Z`` (a space, not a T).
``utcDateModified`` is the UTC one; ``dateModified`` carries the server's own
offset and is not read.

⚠️ The link into the interface is ``/#<noteId>``, which Trilium resolves to
the note's best path. Not clicked in a browser: unchecked.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
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

URL_HINT = "Check the URL; it is the address of Trilium itself, without /etapi."
EVERYTHING = "note.noteId != ''"


def _when(note: dict[str, Any]) -> datetime | None:
    try:
        return datetime.fromisoformat(str(note.get("utcDateModified") or "").replace("Z", "+00:00"))
    except ValueError:
        return None


class TriliumAdapter(Adapter):
    kind = "trilium"
    label = "Trilium"
    category = "other"
    description = "How many notes Trilium holds, how many changed this week, and the notes changed last."
    icon = "trilium"
    beta = True
    docs_url = "https://docs.triliumnotes.org/user-guide/advanced-usage/etapi"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://trilium:8080"),
        Field("token", "ETAPI token", type="password", secret=True, required=True,
              help="Options > ETAPI > Create new ETAPI token."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(kind="summary", label="Notes", description="How many notes there are, and how many changed this week.",
                   renderer="value", default_size=(3, 2), refresh_seconds=600, metrics=("notes",),
                   parts=(("week", "Changed this week"),)),
        WidgetType(kind="recent", label="Recently changed notes", description="The notes changed last.",
                   renderer="list", default_size=(3, 3), refresh_seconds=300,
                   options=(Field("limit", "Entries", type="number", default=8),)),
    )

    # -- talking to Trilium --------------------------------------------------

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, params: dict[str, Any] | None = None,
                   cache: float = 10) -> Any:
        response = await ctx.request(
            "GET", f"{base_url(config)}/etapi{path}", headers={"Authorization": str(config.get("token") or "")},
            params=params, verify=not config.get("insecure"), cache_seconds=cache, auth_errors=False,
        )
        if response.status_code in (401, 403):
            raise AuthFailed("Trilium rejected the ETAPI token.")
        if response.status_code >= 400:
            raise AdapterError(f"Trilium answered with HTTP {response.status_code}.", code="http_error", hint=URL_HINT)
        try:
            return response.json()
        except ValueError as error:
            raise AdapterError("Trilium did not answer with JSON.", code="not_json",
                               hint="The URL probably points at a login page or a reverse proxy.") from error

    async def _notes(self, config: dict[str, Any], ctx: Context, **params: Any) -> list[dict[str, Any]]:
        answer = await self._get(config, ctx, "/notes", {"search": EVERYTHING, **params}, cache=30)
        if not isinstance(answer, dict) or not isinstance(answer.get("results"), list):
            raise AdapterError("This address answers, but not the way Trilium does.", code="not_trilium", hint=URL_HINT)
        # ⚠️ The root note is in every list; see the top of the file.
        return [note for note in answer["results"] if isinstance(note, dict) and note.get("noteId") != "root"]

    # -- the hooks -----------------------------------------------------------

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        info = await self._get(config, ctx, "/app-info", cache=0)
        if not isinstance(info, dict) or "appVersion" not in info:
            raise AdapterError("This address answers, but not the way Trilium does.", code="not_trilium", hint=URL_HINT)
        notes = await self._notes(config, ctx)
        return f"Trilium {info['appVersion']} answers with {len(notes)} notes."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        base = base_url(config)
        if widget_kind == "recent":
            limit = max(1, min(50, int(options.get("limit") or 8)))
            notes = await self._notes(config, ctx, orderBy="utcDateModified", orderDirection="desc", limit=limit + 1)
            return self._recent(notes[:limit], base)
        return self._summary(await self._notes(config, ctx), base)

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def _summary(notes: list[dict[str, Any]], base: str) -> WidgetData:
        week_ago = datetime.now(UTC) - timedelta(days=7)
        changed = sum(1 for note in notes if (when := _when(note)) is not None and when >= week_ago)
        return WidgetData(
            status="ok",
            primary={"label": "Notes", "value": len(notes)},
            secondary=[{"label": "Changed this week", "value": changed, "part": "week"}],
            link=base,
            metrics={"notes": float(len(notes))},
        )

    @staticmethod
    def _recent(notes: list[dict[str, Any]], base: str) -> WidgetData:
        items = []
        for note in notes:
            if not isinstance(note, dict):
                continue
            row: dict[str, Any] = {
                "title": str(note.get("title") or "?"),
                "value": ago((str(note.get("utcDateModified") or "")).replace(" ", "T")),
            }
            if note.get("noteId"):
                row["url"] = f"{base}/#{note['noteId']}"
            items.append(row)
        return WidgetData(status="ok", items=items, link=base, meta={"empty": "No notes yet."})

    # -- demo ----------------------------------------------------------------

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        base = "https://trilium.example.com"
        now = time.time()
        stamp = lambda seconds: time.strftime("%Y-%m-%d %H:%M:%S.000Z", time.gmtime(now - seconds))  # noqa: E731
        if widget_kind == "summary":
            fresh = 1 if fake.flicker("trilium-new", tick, 0.3) else 0
            notes = [{"noteId": f"n{n}", "utcDateModified": stamp(86400 * (1 + n % 20))} for n in range(318 + tick % 3 + fresh)]
            return self._summary(notes, base)
        notes = [
            {"noteId": "a1", "title": "Backup plan", "utcDateModified": stamp(1300)},
            {"noteId": "a2", "title": "DNS notes", "utcDateModified": stamp(6 * 3600)},
            {"noteId": "a3", "title": "Tomato soup", "utcDateModified": stamp(2 * 86400)},
        ]
        return self._recent(notes, base)


ADAPTER = TriliumAdapter()
