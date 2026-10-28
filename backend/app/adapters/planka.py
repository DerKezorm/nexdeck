"""Planka: the open cards, those overdue or due soon, and the lists of a board.

Measured on 28.10.2026 against Planka 2 (ghcr.io/plankanban/planka, with
PostgreSQL) with an API key of the admin, one project, one board of three
lists and four invented cards, two of them with a due date.

⚠️ Planka 2 has API keys, made with ``POST /api/users/<id>/api-key`` (the
profile's "API key" button), and they go in the header ``X-API-Key``.
``Authorization: Bearer <key>`` is a 401. The sign-in token is not for this:
an account that has not accepted the terms gets no token at all but a
``pendingToken`` and ``E_FORBIDDEN "Terms acceptance required"``. A missing or
wrong key is 401 ``{"code": "E_UNAUTHORIZED", ...}``.

⚠️ ``/api/projects`` answers the projects in ``items`` and every board the user
may see in ``included.boards``. Cards are not there: they come per board from
``/api/boards/<id>`` (``included.cards`` and ``included.lists``), so the card
asks once for every board, up to twenty-five.

⚠️ A board has two lists with no name and no position beside its own: the
types ``archive`` and ``trash``. A card in the "closed" list has
``isClosed: true``. The card counts only cards in lists of the type
``active``, so what was archived or thrown away is not "open".

A card's ``dueDate`` is null without one, and ``isDueCompleted`` is null then
too. It opens at ``/cards/<id>``, a board at ``/boards/<id>``.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
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

URL_HINT = "Check the URL; it is the address of Planka itself, without /api."
MAX_BOARDS = 25


def _due(card: dict[str, Any]) -> datetime | None:
    try:
        return datetime.fromisoformat(str(card.get("dueDate") or "").replace("Z", "+00:00"))
    except ValueError:
        return None


class PlankaAdapter(Adapter):
    kind = "planka"
    label = "Planka"
    category = "other"
    description = "The open cards of your boards, those overdue or due soon, and the lists of a board."
    icon = "planka"
    beta = True
    docs_url = "https://docs.planka.cloud/"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://planka:1337"),
        Field("api_key", "API key", type="password", secret=True, required=True,
              help="Profile > API key (Planka 2). Sent as X-API-Key; the cards see the boards of that account."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(kind="summary", label="Cards", description="How many cards are open, with those overdue and the boards.",
                   renderer="value", default_size=(3, 2), refresh_seconds=600, metrics=("open", "overdue"),
                   parts=(("overdue", "Overdue"), ("soon", "Due in a week"), ("boards", "Boards"))),
        WidgetType(kind="due", label="Due cards", description="The cards with a due date, overdue ones first, with their board.",
                   renderer="list", default_size=(3, 3), refresh_seconds=600, metrics=("overdue",),
                   options=(Field("limit", "Entries", type="number", default=8),)),
        WidgetType(kind="board", label="Board", description="The lists of a board with the number of cards in each.",
                   renderer="list", default_size=(3, 3), refresh_seconds=600, bars=True,
                   options=(Field("board", "Board", help="The name of one board. Empty uses the first."),)),
    )

    # -- talking to Planka ---------------------------------------------------

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, cache: float = 30) -> dict[str, Any]:
        response = await ctx.request(
            "GET", f"{base_url(config)}/api{path}", headers={"X-API-Key": str(config.get("api_key") or "")},
            verify=not config.get("insecure"), cache_seconds=cache, auth_errors=False,
        )
        if response.status_code in (401, 403):
            raise AuthFailed("Planka rejected the API key.")
        if response.status_code >= 400:
            raise AdapterError(f"Planka answered with HTTP {response.status_code}.", code="http_error", hint=URL_HINT)
        try:
            answer = response.json()
        except ValueError as error:
            raise AdapterError("Planka did not answer with JSON.", code="not_json",
                               hint="The URL probably points at a login page or a reverse proxy.") from error
        if not isinstance(answer, dict) or not isinstance(answer.get("included"), dict):
            raise AdapterError("This address answers, but not the way Planka does.", code="not_planka", hint=URL_HINT)
        return answer

    async def _boards(self, config: dict[str, Any], ctx: Context) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """The projects and the boards the key may see, in the order Planka gave them."""
        answer = await self._get(config, ctx, "/projects")
        boards = [one for one in answer["included"].get("boards") or [] if isinstance(one, dict)]
        return [one for one in answer.get("items") or [] if isinstance(one, dict)], boards

    async def _cards(self, config: dict[str, Any], ctx: Context, boards: list[dict[str, Any]]) -> list[tuple[dict[str, Any], dict[str, Any], str]]:
        """Every open card as (card, board, name of its list). Open: in a list of the type active."""
        found = []
        for board in boards[:MAX_BOARDS]:
            included = (await self._get(config, ctx, f"/boards/{board['id']}"))["included"]
            lists = {str(one.get("id")): one for one in included.get("lists") or [] if isinstance(one, dict)}
            for card in included.get("cards") or []:
                if not isinstance(card, dict):
                    continue
                parent = lists.get(str(card.get("listId")), {})
                if parent.get("type") == "active":
                    found.append((card, board, str(parent.get("name") or "")))
        return found

    # -- the hooks -----------------------------------------------------------

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        projects, boards = await self._boards(config, ctx)
        return f"Planka answers with {len(projects)} projects and {len(boards)} boards."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        base = base_url(config)
        projects, boards = await self._boards(config, ctx)
        if widget_kind == "board":
            wanted = str(options.get("board") or "").strip().lower()
            chosen = [one for one in boards if not wanted or str(one.get("name") or "").lower() == wanted]
            if not chosen:
                if wanted:
                    raise AdapterError(f"Planka has no board named {str(options.get('board')).strip()!r}.", code="no_such_board")
                return self._board(None, [], base)
            included = (await self._get(config, ctx, f"/boards/{chosen[0]['id']}"))["included"]
            return self._board(chosen[0], included.get("lists") or [], base, included.get("cards") or [])
        cards = await self._cards(config, ctx, boards)
        now = datetime.now(UTC)
        if widget_kind == "due":
            return self._due(cards, now, max(1, int(options.get("limit") or 8)), base)
        return self._summary(cards, len(boards), now, base)

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def _pending(cards: list[tuple[dict[str, Any], dict[str, Any], str]], now: datetime) -> list[tuple[datetime, dict[str, Any], dict[str, Any], str]]:
        """Open cards with a due date that is not ticked off, the nearest first."""
        pending = [(due, card, board, name) for card, board, name in cards
                   if (due := _due(card)) is not None and not card.get("isDueCompleted")]
        return sorted(pending, key=lambda entry: entry[0])

    @classmethod
    def _summary(cls, cards: list[tuple[dict[str, Any], dict[str, Any], str]], boards: int, now: datetime, base: str) -> WidgetData:
        pending = cls._pending(cards, now)
        overdue = sum(1 for due, *_ in pending if due < now)
        soon = sum(1 for due, *_ in pending if 0 <= (due - now).total_seconds() < 7 * 86400)
        return WidgetData(
            status="bad" if overdue else "ok",
            primary={"label": "Open", "value": len(cards)},
            secondary=[
                {"label": "Overdue", "value": overdue, "part": "overdue"},
                {"label": "Due in a week", "value": soon, "part": "soon"},
                {"label": "Boards", "value": boards, "part": "boards"},
            ],
            link=base,
            metrics={"open": float(len(cards)), "overdue": float(overdue)},
        )

    @classmethod
    def _due(cls, cards: list[tuple[dict[str, Any], dict[str, Any], str]], now: datetime, limit: int, base: str) -> WidgetData:
        pending = cls._pending(cards, now)
        items = []
        for due, card, board, name in pending[:limit]:
            days = int((due - now).total_seconds() / 86400)  # whole days, toward zero: two days and a minute late is -2
            items.append({
                "title": str(card.get("name") or "?"),
                "subtitle": " · ".join(part for part in (str(board.get("name") or ""), name) if part),
                "value": f"{days} d",
                "status": "bad" if due < now else "warn" if days < 2 else "ok",
                "url": f"{base}/cards/{card['id']}",
            })
        overdue = sum(1 for due, *_ in pending if due < now)
        return WidgetData(status="bad" if overdue else "ok", items=items, link=base,
                          meta={"empty": "No card has a due date."}, metrics={"overdue": float(overdue)})

    @staticmethod
    def _board(board: dict[str, Any] | None, lists: list[Any], base: str, cards: list[Any] | None = None) -> WidgetData:
        counts: dict[str, int] = {}
        for card in cards or []:
            if isinstance(card, dict):
                counts[str(card.get("listId"))] = counts.get(str(card.get("listId")), 0) + 1
        # ⚠️ The archive and the trash are lists too, and have no name.
        shown = sorted((one for one in lists if isinstance(one, dict) and one.get("type") in ("active", "closed") and one.get("name")),
                       key=lambda one: one.get("position") or 0)
        return WidgetData(
            status="ok",
            items=[{"title": str(one["name"]), "value": counts.get(str(one.get("id")), 0)} for one in shown],
            link=f"{base}/boards/{board['id']}" if board else base,
            meta={"empty": "No boards yet."},
        )

    # -- demo ----------------------------------------------------------------

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        base = "https://planka.example.com"
        now = datetime.now(UTC)
        stamp = lambda hours: datetime.fromtimestamp(time.time() + hours * 3600, UTC).isoformat()  # noqa: E731
        board = {"id": "b1", "name": "Chores"}
        cards = [
            ({"id": "c1", "name": "Replace the UPS battery", "dueDate": stamp(-50)}, board, "To do"),
            ({"id": "c2", "name": "Renew the certificate", "dueDate": stamp(72)}, board, "To do"),
            ({"id": "c3", "name": "Label the patch panel", "dueDate": stamp(24 * 12)}, board, "Doing"),
            ({"id": "c4", "name": "Order a spare disk"}, board, "To do"),
        ]
        if widget_kind == "due":
            return self._due(cards, now, 8, base)
        if widget_kind == "board":
            lists = [{"id": "l1", "name": "To do", "type": "active", "position": 1}, {"id": "l2", "name": "Doing", "type": "active", "position": 2},
                     {"id": "l3", "name": "Done", "type": "closed", "position": 3}]
            placed = [{"listId": "l1"}] * (3 + tick % 2) + [{"listId": "l2"}] * 2 + [{"listId": "l3"}] * 9
            return self._board(board, lists, base, placed)
        extra = [({"id": f"x{n}", "name": "Card"}, board, "To do") for n in range(10 + fake.counter("planka-open", tick, 0, 0.02) % 3)]
        return self._summary(cards + extra, 4, now, base)


ADAPTER = PlankaAdapter()
