"""Kimai: how much time was booked this week and today, and which timer is running.

Measured against Kimai 2.66.0 on 11.09.2026, with an API token, a customer
with a project, three entries (one of them last week) and a running timer.

⚠️ Times are in the Kimai user's own time zone, and so are the filters:
``begin`` with an offset gets 400 Bad Request, a time without one is read in
that zone. The card takes the zone and the first day of the week from
``/users/me``.

⚠️ A running entry has ``end: null`` and ``duration: 0``. What it has run so
far is now minus ``begin``.

⚠️ Stopping rounds to the minute: an entry begun at 10:37:08 was saved as
begun at 10:37:00, and its end had no seconds either. Stopping it a second
time answers 200 and changes nothing.

⚠️ A missing token gets 401 ``{"message": "Unauthorized"}``, a wrong one 401
with an empty body.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .base import (
    Action,
    Adapter,
    AdapterError,
    AuthFailed,
    Context,
    Field,
    WidgetData,
    WidgetType,
    base_url,
    duration_short,
    path_segment,
)

KIMAI_TIME = "%Y-%m-%dT%H:%M:%S"


def _moment(raw: Any) -> datetime | None:
    """``2026-09-11T08:00:00+0000`` as an aware datetime."""
    try:
        return datetime.strptime(str(raw), "%Y-%m-%dT%H:%M:%S%z") if raw else None
    except ValueError:
        return None


def week_start(today: date, first_weekday: str) -> date:
    back = (today.weekday() + 1) % 7 if first_weekday == "sunday" else today.weekday()
    return today - timedelta(days=back)


class KimaiAdapter(Adapter):
    kind = "kimai"
    label = "Kimai"
    category = "other"
    description = "How much time was booked this week and today, and which timer is running."
    icon = "kimai"
    beta = False
    docs_url = "https://www.kimai.org/documentation/rest-api.html"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://kimai:8001"),
        Field("token", "API token", type="password", secret=True, required=True,
              help="Profile > API access > Create. Kimai shows the token only once."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(kind="entries", label="Time entries", description="The running timer first, then this week's entries, the newest first.",
                   renderer="list", default_size=(3, 3), refresh_seconds=60, metrics=("week_hours",),
                   options=(Field("limit", "Entries", type="number", default=8),)),
        WidgetType(kind="summary", label="Booked time", description="Hours booked this week, the time today and whether a timer runs.",
                   renderer="value", default_size=(3, 2), refresh_seconds=60, metrics=("week_hours",)),
    )

    def _headers(self, config: dict[str, Any]) -> dict[str, str]:
        return {"Authorization": f"Bearer {config.get('token') or ''}"}

    async def _json(self, config: dict[str, Any], ctx: Context, path: str, params: dict[str, Any] | None = None, cache: float = 10) -> Any:
        response = await ctx.request(
            "GET", f"{base_url(config)}/api{path}", headers=self._headers(config),
            params=params, verify=not config.get("insecure"), cache_seconds=cache, auth_errors=False,
        )
        if response.status_code in (401, 403):
            raise AuthFailed("Kimai rejected the API token.")
        if response.status_code >= 400:
            raise AdapterError(f"Kimai answered with HTTP {response.status_code}.", code="http_error",
                               hint="Check the URL; it is the address of Kimai itself, without /api.")
        try:
            return response.json()
        except ValueError as error:
            raise AdapterError("Kimai did not answer with JSON.", code="not_json",
                               hint="The URL probably points at the sign-in page or a reverse proxy.") from error

    async def _me(self, config: dict[str, Any], ctx: Context) -> tuple[ZoneInfo, str]:
        me = await self._json(config, ctx, "/users/me", cache=600)
        if not isinstance(me, dict) or "username" not in me:
            raise AdapterError("This address answers, but not the way Kimai does.", code="not_kimai")
        try:
            zone = ZoneInfo(str(me.get("timezone") or "UTC"))
        except (ZoneInfoNotFoundError, ValueError):
            zone = ZoneInfo("UTC")
        preferences = {str(one.get("name")): one.get("value") for one in me.get("preferences") or [] if isinstance(one, dict)}
        return zone, str(preferences.get("first_weekday") or "monday")

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        version = await self._json(config, ctx, "/version", cache=0)
        me = await self._json(config, ctx, "/users/me", cache=0)
        if not isinstance(version, dict) or not isinstance(me, dict):
            raise AdapterError("This address answers, but not the way Kimai does.", code="not_kimai")
        return f"Kimai {version.get('version', '?')} answers for {me.get('username', '?')}."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        zone, first_weekday = await self._me(config, ctx)
        now = datetime.now(UTC)
        start = datetime.combine(week_start(now.astimezone(zone).date(), first_weekday), datetime.min.time())
        entries = await self._json(config, ctx, "/timesheets", {"begin": start.strftime(KIMAI_TIME), "size": 200, "full": "true",
                                                                "orderBy": "begin", "order": "DESC"})
        if not isinstance(entries, list):
            raise AdapterError("This address answers, but not the way Kimai does.", code="not_kimai")
        entries = [one for one in entries if isinstance(one, dict)]
        if widget_kind == "summary":
            return self._summary(entries, now, zone)
        return self._entries(entries, now, options)

    async def action(self, widget_kind: str, action_id: str, params: dict[str, Any],
                     config: dict[str, Any], options: dict[str, Any], ctx: Context) -> str:
        if action_id != "stop":
            raise AdapterError("Unknown time entry action.", code="no_such_action")
        entry = path_segment(params.get("id"), "The time entry")
        response = await ctx.request("PATCH", f"{base_url(config)}/api/timesheets/{entry}/stop", headers=self._headers(config),
                                     verify=not config.get("insecure"), auth_errors=False)
        if response.status_code in (401, 403):
            raise AuthFailed("Kimai refused to stop the timer. May this user edit their own entries?")
        if response.status_code == 404:
            raise AdapterError("Kimai has no such time entry any more.", code="action_failed")
        if response.status_code >= 400:
            raise AdapterError(f"Kimai answered with HTTP {response.status_code}.", code="action_failed")
        return "Timer stopped."

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def _seconds(entry: dict[str, Any], now: datetime) -> float:
        if entry.get("end"):
            return float(entry.get("duration") or 0)
        begun = _moment(entry.get("begin"))
        return max(0.0, (now - begun).total_seconds()) if begun else 0.0

    @staticmethod
    def _place(entry: dict[str, Any]) -> str:
        project = entry.get("project") if isinstance(entry.get("project"), dict) else {}
        customer = project.get("customer") if isinstance(project.get("customer"), dict) else {}
        return " · ".join(part for part in (str(project.get("name") or ""), str(customer.get("name") or "")) if part)

    def _entries(self, entries: list[dict[str, Any]], now: datetime, options: dict[str, Any]) -> WidgetData:
        running = [one for one in entries if not one.get("end")]
        done = [one for one in entries if one.get("end")]
        items = []
        for entry in running + done:
            activity = entry.get("activity") if isinstance(entry.get("activity"), dict) else {}
            row: dict[str, Any] = {
                "title": str(entry.get("description") or activity.get("name") or "?"),
                "subtitle": " · ".join(part for part in ("" if entry.get("end") else "Running", self._place(entry)) if part),
                "status": "ok" if entry.get("end") else "warn",
                "value": duration_short(self._seconds(entry, now)),
            }
            if not entry.get("end"):
                row["actions"] = [Action(id="stop", label="Stop", icon="square", confirm=True, params={"id": str(entry.get("id") or "")})]
            items.append(row)
        week = sum(self._seconds(one, now) for one in entries)
        return WidgetData(
            status="ok",
            items=items[: int(options.get("limit") or 8)],
            secondary=[{"label": "This week", "value": duration_short(week)}],
            # A wall display has no hovering, and the stop button is the one thing on this card to press.
            meta={"empty": "Nothing booked this week.", "actions_visible": True},
            metrics={"week_hours": round(week / 3600, 2)},
        )

    def _summary(self, entries: list[dict[str, Any]], now: datetime, zone: ZoneInfo) -> WidgetData:
        today = now.astimezone(zone).date()
        week = sum(self._seconds(one, now) for one in entries)
        on_the_day = sum(self._seconds(one, now) for one in entries
                         if (begun := _moment(one.get("begin"))) is not None and begun.astimezone(zone).date() == today)
        running = sum(1 for one in entries if not one.get("end"))
        secondary: list[dict[str, Any]] = [{"label": "Today", "value": duration_short(on_the_day)}]
        if running:
            secondary.append({"label": "Running", "value": running})
        return WidgetData(
            status="ok",
            primary={"label": "This week", "value": round(week / 3600, 1), "unit": "h"},
            secondary=secondary,
            metrics={"week_hours": round(week / 3600, 2)},
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        now = datetime.now(UTC)

        def at(hours_ago: float) -> str:
            return (now - timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%S+0000")

        project = {"name": "Website", "customer": {"name": "Example Customer"}}
        entries = [
            {"id": 9, "begin": at(0.6 + tick / 3600), "end": None, "duration": 0, "description": "Review the pull request", "project": project},
            {"id": 8, "begin": at(3), "end": at(1), "duration": 7200, "description": "Fix the login", "project": project},
            {"id": 7, "begin": at(26), "end": at(23.5), "duration": 9000, "description": "Planning", "project": project},
        ]
        if widget_kind == "summary":
            return self._summary(entries, now, ZoneInfo("UTC"))
        return self._entries(entries, now, options)


ADAPTER = KimaiAdapter()
