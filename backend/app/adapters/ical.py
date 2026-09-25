"""iCal feeds and the merged calendar widget.

``ical`` is an integration (the feed URL is often a private link, so it is
stored as a secret). ``calendar`` needs no integration of its own: it merges
the upcoming items of several sources, iCal feeds and *arr instances alike.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta, tzinfo
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .base import Adapter, AdapterError, Context, Field, WidgetData, WidgetType

_FOLD = re.compile(r"\r?\n[ \t]")


def parse_ics(text: str) -> list[dict[str, Any]]:
    """Return VEVENTs as ``{summary, start (date), end, all_day, rrule}``.

    A timed event also carries ``clock``, its time of day as written and
    aware of the zone the file names, and ``length`` to its end. ``start``
    stays the day in the event's own zone, because a rule repeats there: a
    weekly 09:00 in Berlin is 09:00 in winter too, which in UTC it is not.
    """
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
                moment = _moment(value, params)
                if moment is None:
                    continue
                if isinstance(moment, datetime):
                    if name == "DTSTART":
                        current.update(start=moment.date(), all_day=False, clock=moment.timetz())
                    else:
                        current.update(end=moment.date(), until=moment)
                else:
                    current["start" if name == "DTSTART" else "end"] = moment
                    if name == "DTSTART":
                        current["all_day"] = True
            elif name == "RRULE":
                current["rrule"] = dict(part.split("=", 1) for part in value.split(";") if "=" in part)
            elif name == "LOCATION":
                current["location"] = value
    for event in events:
        until = event.pop("until", None)
        clock = event.get("clock")
        if clock is not None and until is not None:
            begun = datetime.combine(event["start"], clock)
            if (until.tzinfo is None) == (begun.tzinfo is None) and until > begun:
                event["length"] = until - begun
    return events


def _moment(value: str, params: str) -> datetime | date | None:
    """A DTSTART or DTEND: a date for an all-day entry, else a datetime.

    The datetime is aware when the file names its zone: ``Z`` for UTC or a
    ``TZID`` this Python knows. A floating time, and a zone it does not know
    (Outlook writes Windows names such as "W. Europe Standard Time"), stay
    naive and are taken as written.
    """
    value = value.strip()
    if len(value) == 8:
        return _parse_date(value)
    try:
        stamp = datetime.strptime(value.rstrip("Z")[:15], "%Y%m%dT%H%M%S")
    except ValueError:
        return None
    zone: tzinfo | None = None
    if value.endswith("Z"):
        zone = UTC
    else:
        named = next((part[5:].strip('"') for part in params.split(";") if part.upper().startswith("TZID=")), "")
        if named:
            try:
                zone = ZoneInfo(named)
            except (ZoneInfoNotFoundError, ValueError, OSError):
                zone = None
    return stamp.replace(tzinfo=zone) if zone is not None else stamp


def on_this_clock(event: dict[str, Any], day: date, here: tzinfo | None = None) -> tuple[date, str | None, datetime | None]:
    """One occurrence as this server shows it: the day, "HH:MM" and when it is over.

    The server's clock is the ``TZ`` of its container. An occurrence written
    in a zone is placed on that clock one by one, so each keeps its own
    daylight saving time; a floating one is taken as written. ``here`` is
    for the tests, which cannot rely on the clock of the machine they run on.
    """
    clock = event.get("clock")
    if clock is None:
        return day, None, None
    begins = datetime.combine(day, clock)
    if begins.tzinfo is not None:
        begins = begins.astimezone(here).replace(tzinfo=None)
    length = event.get("length")
    return begins.date(), f"{begins:%H:%M}", begins + length if length else begins


def drop_what_is_over(items: list[dict[str, Any]], now: datetime | None = None) -> list[dict[str, Any]]:
    """Today's timed entries go once their end has passed, or their start when they name no end.

    All-day entries, and entries without a time such as a release date, stay the whole day.
    """
    now = now or _now()
    today = now.date().isoformat()
    moment = now.isoformat(timespec="minutes")
    return [item for item in items if item.get("date") != today or not item.get("over") or str(item["over"]) > moment]


def _now() -> datetime:
    """This server's clock, in one place the tests can set."""
    return datetime.now()


def in_order(item: dict[str, Any]) -> tuple[str, str]:
    """By day, the day's all-day entries first, then by the clock."""
    return (str(item.get("date") or ""), str(item.get("time") or ""))


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


HIDE_PAST = Field("hide_past", "Hide what is over", type="bool", default=True,
                  help="Today's appointments leave the card once they have ended. All-day entries stay the whole day.")


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
        WidgetType(kind="events", label="Events", description="Upcoming events of this calendar.", renderer="calendar", default_size=(3, 3), refresh_seconds=900, options=(Field("days", "Days ahead", type="number", default=14), Field("limit", "Entries", type="number", default=20), HIDE_PAST)),
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
        # ⚠️ Today on this server's clock, not in UTC: between midnight and
        # two in the morning in Berlin, UTC is still on yesterday.
        start = _now().date()
        end = start + timedelta(days=max(1, days))
        items = []
        for event in await self._events(config, ctx):
            # A day either side: an evening in UTC can be tomorrow here, a morning in Sydney yesterday.
            for day in occurrences(event, start - timedelta(days=1), end + timedelta(days=1)):
                shown, clock, over = on_this_clock(event, day)
                if not start <= shown <= end:
                    continue
                item = {"date": shown.isoformat(), "title": event.get("summary", "(untitled)"), "subtitle": event.get("location", "") or ("all day" if event.get("all_day") else ""), "status": "ok", "source": config.get("name") or "Calendar"}
                if clock is not None:
                    item.update(time=clock, over=over.isoformat(timespec="minutes") if over else None)
                items.append(item)
        items.sort(key=in_order)
        return items

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        items = await self.upcoming(config, ctx, int(options.get("days") or 14))
        if options.get("hide_past", True):
            items = drop_what_is_over(items)
        return WidgetData(items=items[: int(options.get("limit") or 20)])

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        today = datetime.now(UTC).date()
        names = [("Dentist", "Main street 1", "08:30"), ("Team call", "", "14:00"), ("Garbage collection", "all day", None), ("Birthday party", "Home", "18:00")]
        return WidgetData(items=[{"date": (today + timedelta(days=i * 2)).isoformat(), "title": n, "subtitle": s, "status": "ok", "source": "Family", **({"time": c} if c else {})} for i, (n, s, c) in enumerate(names)])


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
                Field("sources", "Sources", type="integrations", options=(("ical", "iCal"), ("radarr", "Radarr"), ("sonarr", "Sonarr"), ("lidarr", "Lidarr"), ("readarr", "Readarr")), help="Pick the calendars and instances to merge.", default=[]),
                Field("days", "Days ahead", type="number", default=7),
                Field("limit", "Entries", type="number", default=20),
                HIDE_PAST,
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
        # The numbers in here were checked when the card was saved. Anything
        # that is not a number is left alone rather than guessed at.
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
        items.sort(key=in_order)
        if options.get("hide_past", True):
            items = drop_what_is_over(items)
        return WidgetData(status="warn" if failures else "ok", items=items[: int(options.get("limit") or 20)], error=("; ".join(failures) if failures and not items else None))

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        today = datetime.now(UTC).date()
        rows = [("Harbour Lights", "S03E05", "Sonarr", 0, None), ("Copper Sky", "Digital release", "Radarr", 0, None), ("Dentist", "Main street 1", "Family", 1, "08:30"), ("Orbital Decay", "S01E09", "Sonarr", 1, None), ("Nightshift", "Digital release", "Radarr", 2, None), ("Team call", "", "Work", 3, "14:00")]
        return WidgetData(items=[{"date": (today + timedelta(days=d)).isoformat(), "title": t, "subtitle": s, "source": src, "status": "ok" if src not in ("Sonarr", "Radarr") else "warn", **({"time": c} if c else {})} for t, s, src, d, c in rows])


ADAPTER = IcalAdapter()
CALENDAR = CalendarAdapter()
