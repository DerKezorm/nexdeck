"""nextasks: what is due in a family's or a small group's tasks, read through its API tokens.

Written against nextasks' ``docs/api.md`` (branch ``neu``, 07.11.2026) and its ``/api/v1``: ``GET /me``,
``/dashboard``, ``/lists`` and ``/tasks``. Out of beta since 09.11.2026, released by its maintainer.

- The token (``ntk_…``) goes in ``Authorization: Bearer``, never in the address. nextasks refuses any request that
  carries an ``Origin`` header (403 ``origin_refused``), so it is only ever called from nexdeck's server.
- API tokens are off until nextasks' operator switches them on: 401 ``api_off``. A wrong, run-out or blocked token
  answers 401 ``token_invalid``. More than 600 requests a minute answer 429 ``slow_down``. A list the token may not
  see answers like one that does not exist, 404 ``not_found``.
- A read token is enough. It sees the spaces picked for it when it was made; the connection test names them.
- ``/me`` says in ``features`` what the server offers; the connection test turns down a nextasks without
  ``dashboard``. ``/me`` also answers with ``spaces``, as nexcanvas' does, so ``features`` is what tells the two
  apart.
- The cards Today and Due read the one ``/dashboard`` answer, which nexdeck keeps for 30 seconds. Assigned to me takes
  its number from there too; its rows come from ``/tasks?assigned=me``, because the dashboard names only how many.
  The List card reads ``/tasks?list_id=…``. ``/lists`` (kept five minutes) names the lists for the card's settings
  and tells which lie in a space the account has hidden, which the dashboard leaves out and so does this card.
- Days are the account's: ``due_date`` is a day in its time zone, and "today" is counted in that zone (from the
  dashboard's ``time_zone``, or ``/me``'s).

What the cards leave out on purpose: notes, attachments, tags, subtasks and repeats. A task shows by its title, when it
is due, whether it is flagged and who has it.
"""

from __future__ import annotations

import zlib
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import demo as fake
from .base import (
    Adapter,
    AdapterError,
    Context,
    Field,
    WidgetData,
    WidgetType,
    base_url,
)
from .nexapp_base import NexappApi, count_of

#: The dashboard answer is the same for three cards; this is how long nexdeck keeps it.
KEEP_SECONDS = 30
#: The lists change seldom: kept for five minutes.
KEEP_LISTS = 300
#: How many tasks of each kind the dashboard is asked for. One number for every card, so they share one answer.
DASHBOARD_LIMIT = 20
#: How many tasks a list card or the card of assigned tasks is asked for; nextasks pages at 100 by default.
PAGE = 100
#: The Today card turns yellow at this many tasks due today.
WARN_TODAY = 5
#: The feature a nextasks names in ``/me`` when it has ``/dashboard``.
FEATURE = "dashboard"


class NextasksAdapter(NexappApi, Adapter):
    kind = "nextasks"
    label = "nextasks"
    category = "other"
    description = "The tasks of a family or a small group in nextasks: what is overdue, due today and coming up, what is assigned to you, and the open tasks of one list."
    icon = "nextasks"
    #: Measured against a fresh nextasks on 07.11.2026, out of beta by its maintainer's word on 09.11.2026.
    beta = False
    #: Empty while nextasks' repository is private: a link there would end at a 404 for everybody else.
    docs_url = ""
    app = "nextasks"
    thing = "token"
    own_fields = ("features", "spaces")
    where_on = "nextasks' operator switches API tokens on under Settings > Server > API"
    where_make = "Make a token under My account > Connections in nextasks; reading is enough."
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://nextasks:8510"),
        Field("api_key", "API token", type="password", secret=True, required=True,
              help="My account > Connections in nextasks, after the operator has switched on API tokens under Settings > Server > API. It starts with ntk_; Read is enough, and it sees only the spaces picked for it."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(
            kind="today",
            label="Today in nextasks",
            description="How many tasks are overdue, due today and due in the next 7 days. Red when something is overdue, yellow when many are due today.",
            renderer="value",
            default_size=(3, 2),
            refresh_seconds=120,
            metrics=("today", "overdue"),
            options=(
                Field("warn_today", "Yellow from (due today)", type="number", default=WARN_TODAY,
                      help="Yellow when at least this many tasks are due today. 0 switches this off."),
            ),
        ),
        WidgetType(
            kind="due",
            label="Due tasks",
            description="The next tasks with a due date, overdue first, then today and the next 7 days, each opening in nextasks. Red when something is overdue.",
            renderer="list",
            default_size=(4, 3),
            refresh_seconds=120,
            options=(Field("limit", "Entries", type="number", default=8),),
        ),
        WidgetType(
            kind="assigned",
            label="Assigned to me",
            description="How many open tasks are assigned to the token's account, and the first of them, soonest due first.",
            renderer="list",
            default_size=(4, 3),
            refresh_seconds=300,
            metrics=("assigned",),
            options=(Field("limit", "Entries", type="number", default=8),),
        ),
        WidgetType(
            kind="list",
            label="Task list",
            description="The open tasks of one list, such as the shopping list, in the order nextasks shows them.",
            renderer="list",
            default_size=(3, 3),
            refresh_seconds=120,
            options=(
                Field("list", "List", type="choices", required=True),
                Field("limit", "Entries", type="number", default=12),
            ),
        ),
    )

    def default_link(self, config: dict[str, Any]) -> str:
        return base_url(config)

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        me = await self._me(config, ctx)
        features = me.get("features") if isinstance(me.get("features"), list) else []
        if FEATURE not in features:
            raise AdapterError(
                "This nextasks has no dashboard route yet; it needs a newer version.", code="too_old",
                hint="Update nextasks; the route came with the version that has cards for nexdeck.",
            )
        spaces = [str(one.get("name") or "?") for one in me.get("spaces") or [] if isinstance(one, dict)]
        does = "reads and writes; the cards only read" if me.get("level") == "write" else "reads"
        who = me.get("display_name") or me.get("name") or "?"
        sees = f"{len(spaces)} space{'' if len(spaces) == 1 else 's'}: {', '.join(spaces)}" if spaces else "no space"
        return f"nextasks {me.get('version') or '?'} answers; the token of {who} {does} and sees {sees}."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        base = base_url(config)
        if widget_kind == "list":
            return await self._list(config, options, ctx, base)
        if widget_kind == "assigned":
            # The rows first, then the number: the dashboard is the one that tells an answer of another app apart.
            rows, _as_of = await self._tasks(config, ctx, {"assigned": "me"})
            hidden = await self._hidden_lists(config, ctx)
            numbers = await self._dashboard(config, ctx)
            return assigned_of(numbers, [row for row in rows if row.get("list_id") not in hidden],
                               _today_in(numbers, ctx_today=_today()), _limit(options, 8), base)
        numbers = await self._dashboard(config, ctx)
        if widget_kind == "due":
            return due_of(numbers, _today_in(numbers, ctx_today=_today()), _limit(options, 8), base)
        return today_of(numbers, _threshold(options, "warn_today", WARN_TODAY), base)

    async def choices(self, field: str, config: dict[str, Any], ctx: Context) -> list[tuple[str, str]]:
        if field != "list":
            return await super().choices(field, config, ctx)
        return [(str(one["id"]), _list_label(one)) for one in await self._lists(config, ctx)]

    def demo_choices(self, field: str) -> list[tuple[str, str]]:
        if field != "list":
            return []
        return [(str(one["id"]), _list_label(one)) for one in DEMO_LISTS]

    async def _dashboard(self, config: dict[str, Any], ctx: Context) -> dict[str, Any]:
        answer = await self._get(config, ctx, "/dashboard", {"limit": DASHBOARD_LIMIT}, cache=KEEP_SECONDS, missing=(
            "This nextasks has no dashboard route yet; it needs a newer version.", "too_old",
            "Update nextasks; the route came with the version that has cards for nexdeck. Or the address has a path: use the one you open nextasks with."))
        return self._expect(answer, "counts", "overdue", "today", "upcoming")

    async def _lists(self, config: dict[str, Any], ctx: Context) -> list[dict[str, Any]]:
        answer = await self._get(config, ctx, "/lists", cache=KEEP_LISTS)
        lists = answer.get("lists") if isinstance(answer, dict) else None
        return [one for one in lists or [] if isinstance(one, dict) and one.get("id")]

    async def _hidden_lists(self, config: dict[str, Any], ctx: Context) -> set[str]:
        return {str(one["id"]) for one in await self._lists(config, ctx) if one.get("hidden") is True}

    async def _tasks(self, config: dict[str, Any], ctx: Context, wanted: dict[str, Any],
                     missing: tuple[str, str, str] | None = None) -> tuple[list[dict[str, Any]], Any]:
        """The open tasks asked for, and the server's moment of the answer (``as_of``)."""
        answer = await self._get(config, ctx, "/tasks", {**wanted, "state": "open", "limit": PAGE}, cache=KEEP_SECONDS,
                                 missing=missing)
        answer = answer if isinstance(answer, dict) else {}
        # A task gone for good comes as {"id", "gone": true}; an open filter should never bring one, nor a trashed one.
        tasks = [one for one in answer.get("tasks") or [] if isinstance(one, dict) and not one.get("gone") and not one.get("trashed")]
        return tasks, answer.get("as_of")

    async def _list(self, config: dict[str, Any], options: dict[str, Any], ctx: Context, base: str) -> WidgetData:
        wanted = str(options.get("list") or "").strip()
        if not wanted:
            raise AdapterError("Pick a list in the card's settings.", code="bad_param")
        rows, as_of = await self._tasks(config, ctx, {"list_id": wanted}, missing=(
            "nextasks has no such list, or the token may not see it.", "no_list",
            "Pick the list again in the card's settings; the token sees only the spaces picked for it."))
        # The zone is the account's (``/me``), the moment the server's when it read the list.
        me = await self._get(config, ctx, "/me", cache=KEEP_LISTS)
        zone = me.get("time_zone") if isinstance(me, dict) else None
        return list_of(rows, _today_in({"time_zone": zone, "as_of": as_of}, ctx_today=_today()), _limit(options, 12), base)

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        today = _today()
        base = "http://nextasks.example.com"
        if widget_kind == "list":
            rows = [_demo_task(title, None) for title in ("Bread", "Milk", "Apples", "Coffee", "Washing-up liquid")]
            if fake.flicker("nextasks-shop", tick, 0.5):
                rows.insert(2, _demo_task("Batteries, AA", None))
            return list_of(rows, today, _limit(options, 12), base)
        numbers = demo_dashboard(today, tick)
        if widget_kind == "due":
            return due_of(numbers, today, _limit(options, 8), base)
        if widget_kind == "assigned":
            mine = [task for key in ("overdue", "today", "upcoming") for task in numbers[key] if task.get("assignees")]
            return assigned_of(numbers, [*mine, _demo_task("Sort the photos of the summer", None, mine=True)], today, _limit(options, 8), base)
        return today_of(numbers, _threshold(options, "warn_today", WARN_TODAY), base)


#: The lists the demo offers in the card's settings.
DEMO_LISTS = (
    {"id": "demo-shopping", "space_name": "Family", "name": "Shopping"},
    {"id": "demo-house", "space_name": "Family", "name": "House"},
    {"id": "demo-club", "space_name": "Club", "name": "Summer party"},
)


def _demo_task(title: str, due: date | None, *, time: str | None = None, flagged: bool = False, mine: bool = False) -> dict[str, Any]:
    number = zlib.crc32(title.encode()) % 10_000
    return {
        "id": f"demo-{number}", "list_id": "demo-house", "title": title,
        "due_date": due.isoformat() if due else None, "due_time": time, "flagged": flagged,
        "assignees": [{"id": 1, "name": "alex", "display_name": "Alex"}] if mine else [],
        "link": f"http://nextasks.example.com/lists/demo-house?task=demo-{number}",
    }


def demo_dashboard(today: date, tick: int) -> dict[str, Any]:
    """A day in a made-up family: a little overdue now and then, a few things today, a week ahead."""
    overdue = [_demo_task("Return the library books", today - timedelta(days=2), mine=True)] if fake.flicker("nextasks-late", tick, 0.4) else []
    due_today = [
        _demo_task("Water the plants", today, mine=True),
        _demo_task("Pay the piano lessons", today, time="18:00", flagged=True),
    ]
    if fake.flicker("nextasks-today", tick, 0.5):
        due_today.append(_demo_task("Call the plumber", today, time="10:00", mine=True))
    upcoming = [
        _demo_task("Take out the paper bin", today + timedelta(days=1)),
        _demo_task("Birthday present for Grandma", today + timedelta(days=4), flagged=True),
        _demo_task("Change the bed linen", today + timedelta(days=6), mine=True),
    ]
    return {
        "counts": {"overdue": len(overdue), "today": len(due_today), "upcoming": len(upcoming) + 2,
                   "assigned_to_me": 1 + sum(bool(task["assignees"]) for task in [*overdue, *due_today, *upcoming]),
                   "flagged": 2, "open": 23 + len(overdue)},
        "overdue": overdue, "today": due_today, "upcoming": upcoming,
        "link": "http://nextasks.example.com/today", "time_zone": None,
    }


def _today() -> date:
    """Today on nexdeck's clock, for an answer that does not say which zone its days are in."""
    return datetime.now().astimezone().date()


def _today_in(answer: dict[str, Any], *, ctx_today: date) -> date:
    """Today in the account's time zone, which is the one ``due_date`` is written in.

    ``as_of`` (the server's moment) in ``time_zone``; without a zone nexdeck's own day, without ``as_of`` now.
    """
    try:
        zone = ZoneInfo(str(answer.get("time_zone") or ""))
    except (ZoneInfoNotFoundError, ValueError):
        return ctx_today
    moment = _moment(answer.get("as_of"))
    return (moment or datetime.now(UTC)).astimezone(zone).date()


def _moment(value: Any) -> datetime | None:
    try:
        when = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=UTC)


def _list_label(one: dict[str, Any]) -> str:
    space = str(one.get("space_name") or "").strip()
    name = str(one.get("name") or "?")
    return f"{space} › {name}" if space else name


def _limit(options: dict[str, Any], default: int) -> int:
    try:
        return max(1, min(50, int(options.get("limit") or default)))
    except (TypeError, ValueError):
        return default


def _threshold(options: dict[str, Any], name: str, default: int) -> int:
    """A limit the operator set; 0 switches it off, and what is not a number is the default."""
    wanted = options.get(name)
    if wanted is None or wanted == "":
        return default
    try:
        return max(0, int(wanted))
    except (TypeError, ValueError):
        return default


def _due(task: dict[str, Any]) -> date | None:
    try:
        return date.fromisoformat(str(task.get("due_date"))[:10])
    except ValueError:
        return None


def _when(left: int) -> str:
    return "Today" if left == 0 else "Tomorrow" if left == 1 else f"in {left} d" if left > 0 else f"{-left} d overdue"


def _row(task: dict[str, Any], today: date, base: str, *, names: bool = True) -> dict[str, Any]:
    """One task as a row: its title, when it is due and who has it, red when overdue and yellow when due today.

    ``names`` off where every row would name the same account: the card of tasks assigned to it.
    """
    day = _due(task)
    left = (day - today).days if day else None
    time = str(task.get("due_time") or "")[:5]
    people = task.get("assignees") if names and isinstance(task.get("assignees"), list) else []
    who = [str(one.get("display_name") or one.get("name") or "") for one in people if isinstance(one, dict)]
    row: dict[str, Any] = {
        "id": task.get("id"),
        "title": str(task.get("title") or "?"),
        "subtitle": " · ".join(part for part in (
            f"{day.isoformat()} {time}".strip() if day else "",
            ", ".join(name for name in who if name),
            "Flagged" if task.get("flagged") is True else "",
        ) if part),
        "status": "ok" if left is None or left > 0 else "warn" if left == 0 else "bad",
        "url": str(task.get("link") or "") or base,
    }
    if left is not None:
        row["value"] = _when(left)
    return row


def _card_status(items: list[dict[str, Any]]) -> str:
    return "bad" if any(item["status"] == "bad" for item in items) else "ok"


def today_of(numbers: dict[str, Any], warn_today: int, base: str) -> WidgetData:
    """Due today as the number, overdue and the next 7 days beside it. Red with anything overdue, yellow with many today."""
    counts = numbers.get("counts") if isinstance(numbers.get("counts"), dict) else {}
    overdue = count_of(counts.get("overdue"))
    today = count_of(counts.get("today"))
    status = "bad" if overdue else "warn" if warn_today and today >= warn_today else "ok"
    return WidgetData(
        status=status,
        primary={"label": "Due today", "value": today},
        secondary=[
            {"label": "Overdue", "value": overdue},
            {"label": "Next 7 days", "value": count_of(counts.get("upcoming"))},
            {"label": "Flagged", "value": count_of(counts.get("flagged"))},
            {"label": "Open", "value": count_of(counts.get("open"))},
        ],
        metrics={"today": float(today), "overdue": float(overdue)},
        link=str(numbers.get("link") or "") or base,
        meta={"status_reason": "Overdue" if status == "bad" else "Due today" if status == "warn" else ""},
    )


def due_of(numbers: dict[str, Any], today: date, limit: int, base: str) -> WidgetData:
    """Overdue first, oldest at the top, then today and the next 7 days, soonest first."""
    seen: set[Any] = set()
    tasks: list[dict[str, Any]] = []
    for key in ("overdue", "today", "upcoming"):
        for task in numbers.get(key) or []:
            if not isinstance(task, dict) or (task.get("id") is not None and task.get("id") in seen):
                continue
            seen.add(task.get("id"))
            tasks.append(task)
    tasks.sort(key=lambda task: (_due(task) or date.max, str(task.get("due_time") or "99")))
    items = [_row(task, today, base) for task in tasks[:limit]]
    return WidgetData(
        status=_card_status(items),
        items=items,
        link=str(numbers.get("link") or "") or base,
        meta={"empty": "Nothing is due."},
    )


def assigned_of(numbers: dict[str, Any], tasks: list[dict[str, Any]], today: date, limit: int, base: str) -> WidgetData:
    """The dashboard's count above the account's open tasks, soonest due first and those without a date last."""
    counts = numbers.get("counts") if isinstance(numbers.get("counts"), dict) else {}
    mine = count_of(counts.get("assigned_to_me"))
    ordered = sorted(tasks, key=lambda task: (_due(task) or date.max, str(task.get("due_time") or "99")))
    items = [_row(task, today, base, names=False) for task in ordered[:limit]]
    return WidgetData(
        status=_card_status(items),
        primary={"label": "Assigned to me", "value": mine},
        items=items,
        metrics={"assigned": float(mine)},
        link=str(numbers.get("link") or "") or base,
        meta={"headline": True, "empty": "Nothing is assigned to you."},
    )


def list_of(tasks: list[dict[str, Any]], today: date, limit: int, base: str) -> WidgetData:
    """A list's open tasks in nextasks' own order; red when one of them is overdue."""
    items = [_row(task, today, base) for task in tasks[:limit]]
    return WidgetData(
        status=_card_status(items),
        primary={"label": "Open", "value": len(tasks)},
        items=items,
        meta={"headline": True, "empty": "Nothing is open in this list."},
    )


ADAPTER = NextasksAdapter()
