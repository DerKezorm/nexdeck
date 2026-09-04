"""iCal feeds and the merged calendar widget.

``ical`` is an integration (the feed URL is often a private link, so it is
stored as a secret). ``calendar`` needs no integration of its own: it merges
the upcoming items of several sources, iCal feeds and *arr instances alike.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from typing import Any

from .base import Adapter, AdapterError, Context, Field, WidgetData, WidgetType

_FOLD = re.compile(r"\r?\n[ \t]")


def parse_ics(text: str) -> list[dict[str, Any]]:
    """Return VEVENTs as ``{summary, start (date), end, all_day, rrule}``."""
    text = _FOLD.sub("", text)
    events: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line in text.splitlines():
        if line == "BEGIN:VEVENT":
            current = {}
        elif line == "END:VEVENT":
            if current is not None and current.get("start"):
                events.append(current)
            current = None
        elif current is not None and ":" in line:
            key, value = line.split(":", 1)
            name, _, params = key.partition(";")
            if name == "SUMMARY":
                current["summary"] = value.replace("\\,", ",").replace("\\n", " ")
            elif name in ("DTSTART", "DTEND"):
                parsed = _parse_date(value)
                if parsed is not None:
                    current["start" if name == "DTSTART" else "end"] = parsed
                    current["all_day"] = "VALUE=DATE" in params or len(value) == 8
            elif name == "RRULE":
                current["rrule"] = dict(part.split("=", 1) for part in value.split(";") if "=" in part)
            elif name == "LOCATION":
                current["location"] = value
    return events


def _parse_date(value: str) -> date | None:
    value = value.strip()
    try:
        if len(value) == 8:
            return datetime.strptime(value, "%Y%m%d").date()
        stamp = value.rstrip("Z")[:15]
        return datetime.strptime(stamp, "%Y%m%dT%H%M%S").date()
    except ValueError:
        return None


def occurrences(event: dict[str, Any], start: date, end: date) -> list[date]:
    """Dates on which the event happens inside ``[start, end]``, with simple recurrence."""
    first: date = event["start"]
    rule = event.get("rrule")
    if not rule:
        return [first] if start <= first <= end else []
    freq = rule.get("FREQ", "")
    interval = int(rule.get("INTERVAL", 1) or 1)
    until = _parse_date(rule["UNTIL"]) if rule.get("UNTIL") else None
    count = int(rule["COUNT"]) if rule.get("COUNT") else None
    days: list[date] = []
    current = first
    produced = 0
    for _ in range(2000):
        if current > end or (until and current > until) or (count and produced >= count):
            break
        if current >= start:
            days.append(current)
        produced += 1
        if freq == "DAILY":
            current += timedelta(days=interval)
        elif freq == "WEEKLY":
            current += timedelta(weeks=interval)
        elif freq == "MONTHLY":
            month = current.month - 1 + interval
            year = current.year + month // 12
            month = month % 12 + 1
            try:
                current = current.replace(year=year, month=month)
            except ValueError:
                current = current.replace(year=year, month=month, day=28)
        elif freq == "YEARLY":
            try:
                current = current.replace(year=current.year + interval)
            except ValueError:
                current = current.replace(year=current.year + interval, day=28)
        else:
            break
    return days


class IcalAdapter(Adapter):
    kind = "ical"
    label = "iCal feed"
    category = "basics"
    description = "Events from an iCal (ICS) address: Google, Nextcloud, iCloud or any calendar that exports one."
    icon = "lucide:calendar"
    beta = False
    fields = (
        Field("url", "ICS address", type="url", secret=True, required=True, help="Private addresses stay secret."),
        Field("name", "Calendar name", placeholder="Family"),
    )
    widgets = (
        WidgetType(kind="events", label="Events", description="Upcoming events of this calendar.", renderer="calendar", default_size=(3, 3), refresh_seconds=900, options=(Field("days", "Days ahead", type="number", default=14), Field("limit", "Entries", type="number", default=20))),
    )

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        events = await self._events(config, ctx)
        return f"The feed answers with {len(events)} events."

    async def _events(self, config: dict[str, Any], ctx: Context) -> list[dict[str, Any]]:
        url = str(config.get("url") or "")
        if url.startswith("webcal://"):
            url = "https://" + url[len("webcal://"):]
        response = await ctx.request("GET", url, cache_seconds=600, timeout=30)
        if response.status_code >= 400:
            raise AdapterError(f"The calendar answered with HTTP {response.status_code}.", code="http_error")
        return parse_ics(response.text)

    async def upcoming(self, config: dict[str, Any], ctx: Context, days: int) -> list[dict[str, Any]]:
        start = datetime.now(UTC).date()
        end = start + timedelta(days=max(1, days))
        items = []
        for event in await self._events(config, ctx):
            for day in occurrences(event, start, end):
                items.append({"date": day.isoformat(), "title": event.get("summary", "(untitled)"), "subtitle": event.get("location", "") or ("all day" if event.get("all_day") else ""), "status": "ok", "source": config.get("name") or "Calendar"})
        items.sort(key=lambda i: i["date"])
        return items

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        items = await self.upcoming(config, ctx, int(options.get("days") or 14))
        return WidgetData(items=items[: int(options.get("limit") or 20)])

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        today = datetime.now(UTC).date()
        names = [("Dentist", "Main street 1"), ("Team call", ""), ("Garbage collection", "all day"), ("Birthday party", "Home")]
        return WidgetData(items=[{"date": (today + timedelta(days=i * 2)).isoformat(), "title": n, "subtitle": s, "status": "ok", "source": "Family"} for i, (n, s) in enumerate(names)])


class CalendarAdapter(Adapter):
    kind = "calendar"
    label = "Calendar"
    category = "basics"
    description = "One calendar that merges iCal feeds and the release calendars of Radarr, Sonarr, Lidarr and Readarr."
    icon = "lucide:calendar-days"
    beta = False
    needs_integration = False
    widgets = (
        WidgetType(
            kind="upcoming",
            label="Upcoming",
            description="Everything that is coming up, from every chosen source.",
            renderer="calendar",
            default_size=(3, 3),
            refresh_seconds=600,
            options=(
                Field("sources", "Sources", type="select", options=(("ical", "iCal"), ("radarr", "Radarr"), ("sonarr", "Sonarr"), ("lidarr", "Lidarr"), ("readarr", "Readarr")), help="Pick the integrations to merge.", default=[]),
                Field("days", "Days ahead", type="number", default=7),
                Field("limit", "Entries", type="number", default=20),
            ),
        ),
    )

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        return "Nothing to test."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        sources = options.get("sources") or []
        if isinstance(sources, str):
            sources = [s for s in sources.split(",") if s.strip()]
        if not sources:
            raise AdapterError("No sources are chosen.", code="missing_sources", hint="Open the widget settings and pick calendars.")
        if ctx.resolve_integration is None:
            raise AdapterError("Sources cannot be resolved here.", code="no_resolver")
        days = int(options.get("days") or 7)
        items: list[dict[str, Any]] = []
        failures: list[str] = []
        for source in sources:
            try:
                adapter, config_of, source_ctx = await ctx.resolve_integration(int(source))
                upcoming = getattr(adapter, "upcoming", None)
                if upcoming is None:
                    continue
                items.extend(await upcoming(config_of, source_ctx, days))
            except (AdapterError, ValueError, KeyError) as error:
                failures.append(str(getattr(error, "message", error)))
        items.sort(key=lambda i: i.get("date") or "")
        return WidgetData(status="warn" if failures else "ok", items=items[: int(options.get("limit") or 20)], error=("; ".join(failures) if failures and not items else None))

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        today = datetime.now(UTC).date()
        rows = [("Harbour Lights", "S03E05", "Sonarr", 0), ("Copper Sky", "Digital release", "Radarr", 0), ("Dentist", "Main street 1", "Family", 1), ("Orbital Decay", "S01E09", "Sonarr", 1), ("Nightshift", "Digital release", "Radarr", 2), ("Team call", "", "Work", 3)]
        return WidgetData(items=[{"date": (today + timedelta(days=d)).isoformat(), "title": t, "subtitle": s, "source": src, "status": "ok" if src not in ("Sonarr", "Radarr") else "warn"} for t, s, src, d in rows])


ADAPTER = IcalAdapter()
CALENDAR = CalendarAdapter()
