"""Anchor (ZhFahim/anchor, the self-hosted notes app): how many notes there are, the notes changed last, and the reminders.

Measured on 28.10.2026 against Anchor 0.17.2 (ghcr.io/zhfahim/anchor with its
embedded PostgreSQL) with the account's API token and five invented notes,
one pinned, two with a reminder, one archived. This is the Anchor that
Homarr's "Anchor" widget talks to (a notes app with an API token); it is not
a service with a similar name.

⚠️ The API token is the account's own: the settings page shows it, and
``GET /api/auth/api-token`` answers ``{"apiToken": null}`` until one has been
made with ``POST /api/auth/api-token/regenerate``. It goes in
``Authorization: Bearer``, like the sign-in token that lasts fifteen minutes.
A wrong token is 401 ``{"message": "Invalid authentication token"}``, none
401 ``"Missing authentication token"``.

⚠️ ``GET /api/notes`` answers a bare array of the active notes, newest change
first (the pinned note was not first). Archived notes are not in it: they are
in ``/api/notes/archive``, deleted ones in ``/api/notes/trash``. A note with no
title has the title ``""`` (the apps write "Untitled").

⚠️ A reminder's ``remindAt`` is a wall-clock time without a zone
(``2026-10-29T10:00``), and ``recurrence`` is ``none`` or ``weekly`` (the
source names more). Without the account's zone there is no telling when it is
due, so the card lists the reminders in the order of that clock and shows it
as written.

``/api/health`` answers the version without a token. The pages of the web
interface are not addressed here: a link per note would be a guess.
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

URL_HINT = "Check the URL; it is the address of Anchor itself, without /api."
RECURRENCE = {"daily": "Daily", "weekly": "Weekly", "monthly": "Monthly", "yearly": "Yearly"}


def _first_line(text: Any) -> str:
    for line in str(text or "").splitlines():
        if line.strip():
            return line.strip()[:80]
    return ""


class AnchorAdapter(Adapter):
    kind = "anchor"
    label = "Anchor"
    category = "other"
    description = "How many notes Anchor holds, the notes changed last, and the notes with a reminder."
    icon = "anchor"
    beta = True
    docs_url = "https://github.com/ZhFahim/anchor"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://anchor:3000"),
        Field("token", "API token", type="password", secret=True, required=True,
              help="Profile > API token in Anchor (made with Regenerate). The one from signing in lasts fifteen minutes."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(kind="summary", label="Notes", description="How many notes there are, with those pinned, with a reminder and archived.",
                   renderer="value", default_size=(3, 2), refresh_seconds=600, metrics=("notes",),
                   parts=(("pinned", "Pinned"), ("reminders", "Reminders"), ("archived", "Archived"))),
        WidgetType(kind="recent", label="Recent notes", description="The notes changed last, with their first line.",
                   renderer="list", default_size=(3, 3), refresh_seconds=300,
                   options=(Field("limit", "Entries", type="number", default=8),)),
        WidgetType(kind="reminders", label="Reminders", description="The notes with a reminder, in the order of the reminder's time.",
                   renderer="list", default_size=(3, 3), refresh_seconds=600,
                   options=(Field("limit", "Entries", type="number", default=8),)),
    )

    # -- talking to Anchor ---------------------------------------------------

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, cache: float = 10) -> Any:
        response = await ctx.request(
            "GET", f"{base_url(config)}/api{path}", headers={"Authorization": f"Bearer {config.get('token') or ''}"},
            verify=not config.get("insecure"), cache_seconds=cache, auth_errors=False,
        )
        if response.status_code in (401, 403):
            raise AuthFailed("Anchor rejected the API token.")
        if response.status_code >= 400:
            raise AdapterError(f"Anchor answered with HTTP {response.status_code}.", code="http_error", hint=URL_HINT)
        try:
            return response.json()
        except ValueError as error:
            raise AdapterError("Anchor did not answer with JSON.", code="not_json",
                               hint="The URL probably points at a login page or a reverse proxy.") from error

    async def _notes(self, config: dict[str, Any], ctx: Context, path: str = "/notes") -> list[dict[str, Any]]:
        answer = await self._get(config, ctx, path)
        if not isinstance(answer, list):
            raise AdapterError("This address answers, but not the way Anchor does.", code="not_anchor", hint=URL_HINT)
        return [one for one in answer if isinstance(one, dict)]

    # -- the hooks -----------------------------------------------------------

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        health = await self._get(config, ctx, "/health", cache=0)
        if not isinstance(health, dict) or health.get("app") != "anchor":
            raise AdapterError("This address answers, but not the way Anchor does.", code="not_anchor", hint=URL_HINT)
        notes = await self._notes(config, ctx)
        return f"Anchor {health.get('version') or '?'} answers with {len(notes)} notes."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        notes = await self._notes(config, ctx)
        limit = max(1, min(50, int(options.get("limit") or 8)))
        if widget_kind == "recent":
            return self._recent(notes, limit, base_url(config))
        if widget_kind == "reminders":
            return self._reminders(notes, limit, base_url(config))
        return self._summary(notes, len(await self._notes(config, ctx, "/notes/archive")), base_url(config))

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def _summary(notes: list[dict[str, Any]], archived: int, base: str) -> WidgetData:
        return WidgetData(
            status="ok",
            primary={"label": "Notes", "value": len(notes)},
            secondary=[
                {"label": "Pinned", "value": sum(1 for one in notes if one.get("isPinned") is True), "part": "pinned"},
                {"label": "Reminders", "value": sum(1 for one in notes if isinstance(one.get("reminder"), dict)), "part": "reminders"},
                {"label": "Archived", "value": archived, "part": "archived"},
            ],
            link=base,
            metrics={"notes": float(len(notes))},
        )

    @staticmethod
    def _recent(notes: list[dict[str, Any]], limit: int, base: str) -> WidgetData:
        newest = sorted(notes, key=lambda one: str(one.get("updatedAt") or ""), reverse=True)
        items = [{
            # ⚠️ A blank title is allowed; the apps write "Untitled".
            "title": str(one.get("title") or "").strip() or "Untitled",
            "subtitle": _first_line(one.get("content")),
            "value": ago(one.get("updatedAt")),
        } for one in newest[:limit]]
        return WidgetData(status="ok", items=items, link=base, meta={"empty": "No notes yet."})

    @staticmethod
    def _reminders(notes: list[dict[str, Any]], limit: int, base: str) -> WidgetData:
        with_reminder = sorted((one for one in notes if isinstance(one.get("reminder"), dict) and one["reminder"].get("remindAt")),
                               key=lambda one: str(one["reminder"]["remindAt"]))
        items = [{
            "title": str(one.get("title") or "").strip() or "Untitled",
            "subtitle": RECURRENCE.get(str(one["reminder"].get("recurrence")), ""),
            # As written: a wall-clock time without a zone.
            "value": str(one["reminder"]["remindAt"]).replace("T", " "),
        } for one in with_reminder[:limit]]
        return WidgetData(status="ok", items=items, link=base, meta={"empty": "No note has a reminder."})

    # -- demo ----------------------------------------------------------------

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        base = "https://anchor.example.com"
        now = time.time()
        stamp = lambda seconds: time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(now - seconds))  # noqa: E731
        notes = [
            {"title": "Backup plan", "content": "Nightly to the NAS", "updatedAt": stamp(1400), "isPinned": True, "reminder": None},
            {"title": "Call the dentist", "content": "Ask for a Tuesday", "updatedAt": stamp(5 * 3600),
             "reminder": {"remindAt": "2026-10-29T10:00", "recurrence": "none"}},
            {"title": "", "content": "Milk, bread, eggs", "updatedAt": stamp(2 * 86400), "reminder": None},
            {"title": "Pay the invoice", "content": "", "updatedAt": stamp(3 * 86400),
             "reminder": {"remindAt": "2026-11-02T09:30", "recurrence": "weekly"}},
        ]
        if widget_kind == "recent":
            return self._recent(notes, 8, base)
        if widget_kind == "reminders":
            return self._reminders(notes, 8, base)
        fresh = 1 if fake.flicker("anchor-new", tick, 0.3) else 0
        return self._summary(notes * 20 + [{}] * fresh, 7, base)


ADAPTER = AnchorAdapter()
