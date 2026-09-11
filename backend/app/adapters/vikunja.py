"""Vikunja: which tasks are overdue or due today, across every project.

Measured against Vikunja 2.6.0 on 11.09.2026, with an API token that may read
tasks and projects, and six tasks in two projects: one overdue, one due later
today, one due at half past ten at night in UTC, one due in three days, one
without a date and one done.

⚠️ ``/tasks/all`` is gone. An API token asking there gets 401 "missing,
malformed, expired or otherwise invalid token provided", although the token
is fine; a login token gets 400. The list of all tasks is ``/tasks`` now.

⚠️ "Today" in a filter depends on ``filter_timezone``. The task due at 22:30
UTC counted as today in UTC and as tomorrow in Europe/Berlin. An API token
cannot read ``/user``, so the user's own zone is out of reach; the
integration has a field for it.

⚠️ A task without a due date carries ``0001-01-01T00:00:00Z``, not null.

⚠️ A count needs no paging: with ``per_page=1`` the header
``x-pagination-total-pages`` is the number of matching tasks, and 0 for none.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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

NO_DATE = "0001-01-01T00:00:00Z"
#: Vikunja's own words for the priorities worth pointing out.
PRIORITY = {3: "High", 4: "Urgent", 5: "Do now"}


def _zone(config: dict[str, Any]) -> ZoneInfo:
    try:
        return ZoneInfo(str(config.get("timezone") or "UTC").strip() or "UTC")
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise AdapterError(f"{config.get('timezone')!r} is not a time zone.", code="bad_timezone",
                           hint="An IANA name such as Europe/Berlin, or empty for UTC.") from error


def _due(task: dict[str, Any]) -> datetime | None:
    raw = str(task.get("due_date") or "")
    if not raw or raw == NO_DATE:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


class VikunjaAdapter(Adapter):
    kind = "vikunja"
    label = "Vikunja"
    category = "other"
    description = "Which tasks are overdue or due today, across every project."
    icon = "vikunja"
    beta = False
    docs_url = "https://vikunja.io/docs/api-tokens/"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://vikunja:3456"),
        Field("token", "API token", type="password", secret=True, required=True,
              help="Settings > API Tokens, with read_all for tasks and for projects."),
        Field("timezone", "Time zone", type="timezone", placeholder="Europe/Berlin",
              help="Where the day begins for today and overdue. Empty means UTC."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(kind="due", label="Due tasks", description="Open tasks that are overdue or due soon, the earliest first.",
                   renderer="list", default_size=(3, 3), refresh_seconds=300, metrics=("overdue",),
                   options=(Field("days", "Days ahead", type="number", default=0, help="0 shows what is overdue or due today."),
                            Field("limit", "Entries", type="number", default=10))),
        WidgetType(kind="summary", label="Tasks", description="How many open tasks are overdue, due today and open at all.",
                   renderer="value", default_size=(3, 2), refresh_seconds=300, metrics=("overdue",)),
    )

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, params: dict[str, Any] | None = None, cache: float = 10) -> Any:
        response = await ctx.request(
            "GET", f"{base_url(config)}/api/v1{path}", headers={"Authorization": f"Bearer {config.get('token') or ''}"},
            params=params, verify=not config.get("insecure"), cache_seconds=cache, auth_errors=False,
        )
        if response.status_code in (401, 403):
            raise AuthFailed("Vikunja rejected the API token. It needs read_all for tasks and for projects.")
        if response.status_code >= 400:
            raise AdapterError(f"Vikunja answered with HTTP {response.status_code}.", code="http_error",
                               hint="Check the URL; it is the address of Vikunja itself, without /api.")
        return response

    async def _json(self, config: dict[str, Any], ctx: Context, path: str, params: dict[str, Any] | None = None) -> Any:
        response = await self._get(config, ctx, path, params)
        try:
            return response.json()
        except ValueError as error:
            raise AdapterError("Vikunja did not answer with JSON.", code="not_json",
                               hint="The URL probably points at a login page or a reverse proxy.") from error

    async def _count(self, config: dict[str, Any], ctx: Context, flt: str) -> int:
        response = await self._get(config, ctx, "/tasks", {"filter": flt, "filter_timezone": _zone(config).key, "per_page": 1})
        try:
            return int(response.headers.get("x-pagination-total-pages") or 0)
        except ValueError:
            return 0

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        info = await self._json(config, ctx, "/info")
        if not isinstance(info, dict) or "version" not in info:
            raise AdapterError("This address answers, but not the way Vikunja does.", code="not_vikunja")
        open_tasks = await self._count(config, ctx, "done = false")
        return f"Vikunja {str(info['version']).lstrip('v')} answers with {open_tasks} open tasks."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        zone = _zone(config)
        if widget_kind == "summary":
            overdue = await self._count(config, ctx, "done = false && due_date < now")
            today = await self._count(config, ctx, "done = false && due_date >= now && due_date < now/d+1d")
            open_tasks = await self._count(config, ctx, "done = false")
            return self._summary(overdue, today, open_tasks)
        days = max(0, min(60, int(options.get("days") or 0)))
        tasks = await self._json(config, ctx, "/tasks", {"filter": f"done = false && due_date < now/d+{days + 1}d", "filter_timezone": zone.key,
                                                         "sort_by": "due_date", "order_by": "asc", "per_page": 50})
        if not isinstance(tasks, list):
            raise AdapterError("This address answers, but not the way Vikunja does.", code="not_vikunja")
        projects = await self._json(config, ctx, "/projects", {"per_page": 50})
        names = {int(one.get("id") or 0): str(one.get("title") or "") for one in projects if isinstance(one, dict)} if isinstance(projects, list) else {}
        return self._due(tasks, names, datetime.now(UTC), zone, base_url(config), options)

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def _due(tasks: list[Any], names: dict[int, str], now: datetime, zone: ZoneInfo, base: str, options: dict[str, Any]) -> WidgetData:
        today = now.astimezone(zone).date()
        items = []
        overdue = 0
        for task in tasks:
            if not isinstance(task, dict) or task.get("done"):
                continue
            due = _due(task)
            if due is None:
                continue
            local = due.astimezone(zone)
            if due < now:
                overdue += 1
                state, when, value = "bad", "Overdue", ago(due.timestamp())
            elif local.date() == today:
                state, when, value = "warn", "Today", local.strftime("%H:%M")
            elif local.date() == today + timedelta(days=1):
                state, when, value = "ok", "Tomorrow", local.strftime("%H:%M")
            else:
                state, when, value = "ok", local.date().isoformat(), ""
            items.append({
                "title": str(task.get("title") or "?"),
                "subtitle": " · ".join(part for part in (when, PRIORITY.get(int(task.get("priority") or 0), ""), names.get(int(task.get("project_id") or 0), "")) if part),
                "status": state,
                "value": value,
                "url": f"{base}/tasks/{task.get('id')}",
            })
        return WidgetData(
            status="bad" if overdue else "ok",
            items=items[: int(options.get("limit") or 10)],
            secondary=[{"label": "Overdue", "value": overdue}],
            meta={"empty": "Nothing is due."},
            metrics={"overdue": float(overdue)},
        )

    @staticmethod
    def _summary(overdue: int, today: int, open_tasks: int) -> WidgetData:
        return WidgetData(
            status="bad" if overdue else "ok",
            primary={"label": "Overdue", "value": overdue},
            secondary=[{"label": "Due today", "value": today}, {"label": "Open", "value": open_tasks}],
            metrics={"overdue": float(overdue)},
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        now = datetime.now(UTC)
        if widget_kind == "summary":
            return self._summary(1, 2 + tick % 2, 23)

        def due(hours: float) -> str:
            return (now + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")

        tasks = [
            {"id": 11, "title": "Renew the certificate", "due_date": due(-20), "priority": 4, "project_id": 2},
            {"id": 12, "title": "Swap the backup disk", "due_date": due(3), "priority": 0, "project_id": 2},
            {"id": 13, "title": "Pay the electricity bill", "due_date": due(5), "priority": 3, "project_id": 3},
        ]
        return self._due(tasks, {2: "Homelab", 3: "Household"}, now, ZoneInfo("UTC"), "https://vikunja.example.com", options)


ADAPTER = VikunjaAdapter()
