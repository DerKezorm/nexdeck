"""nexlore: the notes of the nexapps family, read and written through its API tokens.

Written against nexlore 0.4.0 and its ``docs/api.md``, and measured against
it on 02.10.2026 on nexlore's own test stand with its made-up vault: a read
and a write token, a wrong one, none, a request with an ``Origin`` header,
and API tokens switched off.

- The token (``nxa_…``) goes in ``Authorization: Bearer``, never in the
  address. nexlore refuses any request that carries an ``Origin`` header
  (403 ``origin_refused``), so it is only ever called from nexdeck's server.
- API tokens are off until nexlore's operator opens them. Then no token can
  even be made (403 ``api_off``), and one made before answers 401
  ``api_off``; a wrong or withdrawn token answers 401 ``token_invalid``. The
  card tells the two apart.
- ``/me`` names the token's ``level``. Ticking a task off and capturing need
  ``write``; with a read token the card offers neither, rather than buttons
  that answer 403 ``read_only_token``.
- Days are counted on nexdeck's clock: every request that counts days sends
  ``today``, every write sends ``now``, as nexlore asks of programs.
- Nothing is ever deleted, moved or renamed: nexlore's API has no route for it.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import quote

from . import demo as fake
from .base import (
    Action,
    Adapter,
    AdapterError,
    Ask,
    AuthFailed,
    Context,
    Field,
    WidgetData,
    WidgetType,
    base_url,
)

SHOW = (("due", "Overdue and today"), ("week", "Due this week"), ("open", "All open"))
#: How long the token's level is believed: it changes only when the token is made anew.
LEVEL_SECONDS = 300


class NexloreAdapter(Adapter):
    kind = "nexlore"
    label = "nexlore"
    category = "other"
    description = "Notes and tasks of nexlore: what is due, what changed last, and a line into the inbox."
    icon = "nexlore"
    beta = True
    docs_url = "https://www.nexlore.de"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://nexlore:8470"),
        Field("api_key", "API token", type="password", secret=True, required=True,
              help="My account > Connections > API tokens in nexlore; it starts with nxa_. Read fills the cards, Write also ticks tasks off and captures."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(
            kind="overview",
            label="nexlore overview",
            description="Open tasks, those due today and overdue, what waits in the inbox, and the notes in all. With a write token, a line goes into the inbox from here.",
            renderer="value",
            default_size=(3, 2),
            refresh_seconds=120,
            metrics=("open",),
        ),
        WidgetType(
            kind="tasks",
            label="Tasks",
            description="The tasks that are due, the overdue first, each with its note. With a write token, a tap ticks one off.",
            renderer="list",
            default_size=(4, 3),
            refresh_seconds=120,
            options=(
                Field("show", "Show", type="select", default="due", options=SHOW),
                Field("limit", "Entries", type="number", default=8),
            ),
        ),
        WidgetType(
            kind="recent",
            label="Changed last",
            description="The notes changed last, newest first, each opening in nexlore.",
            renderer="list",
            default_size=(4, 3),
            refresh_seconds=300,
            options=(Field("limit", "Entries", type="number", default=6),),
        ),
    )

    async def _call(self, method: str, config: dict[str, Any], ctx: Context, path: str, *,
                    params: dict[str, Any] | None = None, body: dict[str, Any] | None = None, cache: int = 30) -> Any:
        response = await ctx.request(
            method, f"{base_url(config)}/api/v1{path}", params=params, json_body=body,
            cache_seconds=cache if method == "GET" else 0, auth_errors=False,
            headers={"Authorization": f"Bearer {config.get('api_key') or ''}", "Accept": "application/json"},
            verify=not config.get("insecure"),
        )
        code = _code_of(response)
        if code == "api_off":
            raise AdapterError(
                "API tokens are switched off in nexlore.", code="auth_failed",
                hint="nexlore's operator opens them under Settings > Server > AI, API and plugins; the token itself stays valid.",
            )
        if response.status_code == 401:
            raise AuthFailed("nexlore does not know this token; it may have run out or been withdrawn.")
        if code == "read_only_token":
            raise AdapterError("This token may only read; ticking off and capturing need a token with the level Write.",
                               code="read_only")
        if code == "task_changed":
            raise AdapterError("The task is no longer where it was; the card shows it anew in a moment.", code="task_changed")
        if code == "note_locked":
            raise AdapterError("Somebody is editing the inbox note right now; try again in a moment.", code="busy")
        if code == "slow_down":
            raise AdapterError("nexlore asks for fewer requests with this token for a minute.", code="rate_limited")
        if response.status_code >= 400:
            raise AdapterError(f"nexlore answered with HTTP {response.status_code}.", code="http_error")
        try:
            return response.json()
        except ValueError:
            raise AdapterError("nexlore did not answer with JSON; is this the address of nexlore?", code="bad_answer") from None

    async def _writes(self, config: dict[str, Any], ctx: Context) -> bool:
        me = await self._call("GET", config, ctx, "/me", cache=LEVEL_SECONDS)
        return isinstance(me, dict) and me.get("level") == "write"

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        me = await self._call("GET", config, ctx, "/me", cache=0)
        me = me if isinstance(me, dict) else {}
        spaces = me.get("spaces")
        reach = "every space of the account" if spaces is None else f"{len(spaces)} chosen space(s)"
        level = "reads and writes" if me.get("level") == "write" else "reads"
        return f"nexlore {me.get('version') or '?'} answers; the token of {me.get('account') or '?'} {level} in {reach}."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        today = _today()
        if widget_kind == "recent":
            limit = _limit(options, 6)
            rows = await self._call("GET", config, ctx, "/recent", params={"limit": limit})
            return recent_of(rows if isinstance(rows, list) else [], base_url(config), limit)
        if widget_kind == "tasks":
            show = str(options.get("show") or "due")
            whens = {"due": ("overdue", "today"), "week": ("overdue", "today", "week")}.get(show)
            limit = _limit(options, 8)
            if whens:
                answers = await asyncio.gather(*(
                    self._call("GET", config, ctx, "/tasks", params={"when": when, "today": today.isoformat(), "limit": limit})
                    for when in whens))
            else:
                answers = [await self._call("GET", config, ctx, "/tasks", params={"today": today.isoformat(), "limit": limit})]
            items = [item for answer in answers if isinstance(answer, dict) for item in answer.get("items") or []]
            return tasks_of(items, today, base_url(config), limit, await self._writes(config, ctx))
        numbers = await self._call("GET", config, ctx, "/dashboard", params={"today": today.isoformat()})
        return overview_of(numbers if isinstance(numbers, dict) else {}, await self._writes(config, ctx))

    async def action(self, widget_kind: str, action_id: str, params: dict[str, Any],
                     config: dict[str, Any], options: dict[str, Any], ctx: Context) -> str:
        if action_id == "capture":
            answer = await self._call("POST", config, ctx, "/inbox", body={
                "text": str(params.get("text") or ""), "now": datetime.now().astimezone().isoformat(timespec="seconds")})
            where = str((answer or {}).get("path") or "") if isinstance(answer, dict) else ""
            return f"In the inbox: {where}." if where else "In the inbox."
        if action_id == "complete":
            body = {key: params.get(key) for key in ("path", "line", "raw", "hash")}
            body["today"] = _today().isoformat()
            answer = await self._call("POST", config, ctx, "/tasks/complete", body=body)
            if isinstance(answer, dict) and answer.get("added"):
                return "Done. The next one of this recurring task is in the note."
            return "Done."
        raise AdapterError("This widget has no such action.", code="no_such_action")

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        today = _today()
        base = "http://nexlore.example.com"
        if widget_kind == "recent":
            now = datetime.now(UTC)
            rows = [
                {"path": "Home/Projects/Garden shed.md", "title": "Garden shed", "space": "Home", "modified": (now - timedelta(minutes=12)).isoformat()},
                {"path": "Home/Daily/" + today.isoformat() + ".md", "title": today.isoformat(), "space": "Home", "modified": (now - timedelta(hours=1)).isoformat()},
                {"path": "Homelab/Backups.md", "title": "Backups", "space": "Homelab", "modified": (now - timedelta(hours=5)).isoformat()},
                {"path": "Homelab/Network plan.md", "title": "Network plan", "space": "Homelab", "modified": (now - timedelta(days=2)).isoformat()},
            ]
            return recent_of(rows, base, _limit(options, 6))
        if widget_kind == "tasks":
            renewed = fake.flicker("nexlore-renew", tick, 0.5)
            items = [
                {"path": "Homelab/Certificates.md", "title": "Certificates", "line": 4, "raw": "- [ ] Renew the certificate",
                 "text": "Renew the certificate", "due": (today - timedelta(days=2)).isoformat(), "file_hash": "a1"},
                {"path": "Home/Projects/Garden shed.md", "title": "Garden shed", "line": 9, "raw": "- [ ] Order the timber",
                 "text": "Order the timber", "due": today.isoformat(), "file_hash": "b2"},
                {"path": "Homelab/Backups.md", "title": "Backups", "line": 12, "raw": "- [ ] Test a restore",
                 "text": "Test a restore", "due": (today + timedelta(days=3)).isoformat(), "file_hash": "c3"},
            ]
            show = str(options.get("show") or "due")
            if show == "due":
                items = [item for item in items if item["due"] <= today.isoformat()]
            if renewed:
                items = items[1:]
            return tasks_of(items, today, base, _limit(options, 8), True)
        return overview_of({"spaces": 3, "notes": 214, "tasks_open": int(fake.walk("nexlore-open", tick, 9, 16)),
                            "tasks_overdue": 1 if fake.flicker("nexlore-late", tick, 0.5) else 0, "tasks_today": 2,
                            "tasks_week": 5, "inbox": 3}, True)


def _today() -> date:
    """Today on nexdeck's clock, which is the clock of the people looking at the board."""
    return datetime.now().astimezone().date()


def _limit(options: dict[str, Any], default: int) -> int:
    try:
        return max(1, min(50, int(options.get("limit") or default)))
    except (TypeError, ValueError):
        return default


def _code_of(response: Any) -> str:
    """nexlore's own code of a refusal, from ``{"detail": {"code": …}}``."""
    try:
        detail = response.json().get("detail")
    except (ValueError, AttributeError):
        return ""
    return str(detail.get("code") or "") if isinstance(detail, dict) else ""


def note_url(base: str, path: str) -> str:
    """Where a note opens in nexlore: each part of its path encoded on its own."""
    return f"{base}/note/" + "/".join(quote(part, safe="") for part in path.split("/"))


def _epoch(moment: Any) -> float | None:
    try:
        when = datetime.fromisoformat(str(moment).replace("Z", "+00:00"))
    except ValueError:
        return None
    return (when if when.tzinfo else when.replace(tzinfo=UTC)).timestamp()


def _capture() -> Action:
    return Action(id="capture", label="Capture", icon="plus",
                  asks=[Ask(name="text", label="Into the inbox", kind="text", placeholder="[ ] call the plumber", max_length=2000)])


def overview_of(numbers: dict[str, Any], writes: bool) -> WidgetData:
    open_tasks = int(numbers.get("tasks_open") or 0)
    overdue = int(numbers.get("tasks_overdue") or 0)
    return WidgetData(
        status="warn" if overdue else "ok",
        primary={"label": "Open tasks", "value": open_tasks},
        secondary=[
            {"label": "Today", "value": int(numbers.get("tasks_today") or 0)},
            {"label": "Overdue", "value": overdue},
            {"label": "Inbox", "value": int(numbers.get("inbox") or 0)},
            {"label": "Notes", "value": int(numbers.get("notes") or 0)},
        ],
        metrics={"open": float(open_tasks)},
        actions=[_capture()] if writes else [],
        meta={"status_reason": f"{overdue} task(s) overdue" if overdue else ""},
    )


def tasks_of(items: list[Any], today: date, base: str, limit: int, writes: bool) -> WidgetData:
    """Each task once, the overdue first, then by date; red when overdue, amber when due today."""
    seen: set[tuple[str, int]] = set()
    rows: list[dict[str, Any]] = []
    for item in sorted((one for one in items if isinstance(one, dict)), key=lambda one: str(one.get("due") or "9999")):
        place = (str(item.get("path") or ""), int(item.get("line") or 0))
        if place in seen:
            continue
        seen.add(place)
        due = str(item.get("due") or "")
        state = "bad" if due and due < today.isoformat() else "warn" if due == today.isoformat() else "ok"
        row: dict[str, Any] = {
            "id": f"{place[0]}:{place[1]}",
            "title": str(item.get("text") or item.get("raw") or "?"),
            "subtitle": " · ".join(part for part in (str(item.get("title") or ""), due) if part),
            "status": state,
            "url": note_url(base, place[0]) if place[0] else "",
        }
        if writes and place[0]:
            row["actions"] = [{"id": "complete", "label": "Done", "icon": "check", "params": {
                "path": place[0], "line": place[1], "raw": str(item.get("raw") or ""), "hash": str(item.get("file_hash") or "")}}]
        rows.append(row)
    rows = rows[:limit]
    return WidgetData(
        status="bad" if any(row["status"] == "bad" for row in rows) else "ok",
        items=rows,
        meta={"empty": "Nothing due."},
    )


def recent_of(rows: list[Any], base: str, limit: int) -> WidgetData:
    items = [
        {
            "id": str(row.get("path") or ""),
            "title": str(row.get("title") or row.get("path") or "?"),
            "subtitle": str(row.get("space") or ""),
            "when": _epoch(row.get("modified")),
            "url": note_url(base, str(row.get("path") or "")),
        }
        for row in rows if isinstance(row, dict) and row.get("path")
    ][:limit]
    return WidgetData(status="ok", items=items, meta={"empty": "No note yet."})


ADAPTER = NexloreAdapter()
