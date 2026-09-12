"""Sportarr: the sports events of the next days, and the ones that took place without a file.

Measured against Sportarr 4.1.7.1117 on 11.09.2026, without an indexer or a
download client, with two leagues added from Sportarr's own metadata and
their current season monitored.

⚠️ A made-up key gets the same 401 as none at all:
``{"error": "Unauthorized", "message": "API key required"}``. The key also
works as a bearer token and as ``?apikey=``; the adapter sends ``X-Api-Key``.
``/api/health`` answers without any key, so the connection test asks
``/api/system/status`` instead.

⚠️ ``wanted`` in ``/api/stats`` counts every monitored event without a file,
the coming ones too: 56 there against the 40 that ``/api/wanted/missing``
lists, which counts only events that have taken place. The cards say
"missing" and take the list's ``totalRecords``.

⚠️ ``/api/wanted/missing`` wants ``page`` and ``pageSize``; without them it
answers 400.

⚠️ ``eventDate`` is the start in UTC. ``broadcastDate`` is a date at midnight
and says nothing about the hour.

⚠️ There is no queue card. Without a download client the queue stays empty,
so nothing about its rows could be confirmed.
"""

from __future__ import annotations

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

SPORTARR_TIME = "%Y-%m-%dT%H:%M:%SZ"


def _not_sportarr() -> AdapterError:
    return AdapterError("This address answers, but not the way Sportarr does.", code="not_sportarr",
                        hint="Check the URL; Sportarr listens on port 1867 unless told otherwise.")


def _events(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        raise _not_sportarr()
    return [one for one in payload if isinstance(one, dict)]


class SportarrAdapter(Adapter):
    kind = "sportarr"
    label = "Sportarr"
    category = "media"
    description = "The sports events of the next days, and the ones that took place without a file."
    icon = "sportarr"
    #: Confirmed against a live instance on 2026-09-11.
    beta = False
    docs_url = "https://wiki.sportarr.net/api/"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://sportarr:1867"),
        Field("api_key", "API key", type="password", secret=True, required=True, help="Settings > General > Security."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(kind="upcoming", label="Upcoming", description="Monitored events of the next days.",
                   renderer="calendar", default_size=(3, 3), refresh_seconds=600, metrics=("upcoming",),
                   options=(Field("days", "Days ahead", type="number", default=7),)),
        WidgetType(kind="missing", label="Missing events",
                   description="Monitored events that have taken place without a file, the latest first.",
                   renderer="list", default_size=(3, 3), refresh_seconds=900, metrics=("missing",),
                   options=(Field("limit", "Entries", type="number", default=8),)),
        WidgetType(kind="summary", label="Sports events",
                   description="How many events are missing, how many come in the next seven days, and how many leagues there are.",
                   renderer="value", default_size=(3, 2), refresh_seconds=600, metrics=("missing", "upcoming")),
    )

    async def _json(self, config: dict[str, Any], ctx: Context, path: str, params: dict[str, Any] | None = None, cache: float = 60) -> Any:
        response = await ctx.request(
            "GET", f"{base_url(config)}/api{path}", headers={"X-Api-Key": str(config.get("api_key") or "")},
            params=params, verify=not config.get("insecure"), cache_seconds=cache, auth_errors=False,
        )
        if response.status_code in (401, 403):
            raise AuthFailed("Sportarr rejected the API key.")
        if response.status_code >= 400:
            raise AdapterError(f"Sportarr answered with HTTP {response.status_code}.", code="http_error",
                               hint="Check the URL; it is the address of Sportarr itself, with its URL base if one is set.")
        try:
            return response.json()
        except ValueError as error:
            raise AdapterError("Sportarr did not answer with JSON.", code="not_json",
                               hint="The URL probably points at something else than Sportarr.") from error

    async def _upcoming(self, config: dict[str, Any], ctx: Context, days: int, now: datetime) -> list[dict[str, Any]]:
        window = {"start": now.strftime(SPORTARR_TIME), "end": (now + timedelta(days=days)).strftime(SPORTARR_TIME)}
        return _events(await self._json(config, ctx, "/calendar", window, cache=300))

    async def _missing(self, config: dict[str, Any], ctx: Context, size: int) -> dict[str, Any]:
        page = await self._json(config, ctx, "/wanted/missing", {"page": 1, "pageSize": size}, cache=120)
        if not isinstance(page, dict) or not isinstance(page.get("events"), list):
            raise _not_sportarr()
        return page

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        status = await self._json(config, ctx, "/system/status", cache=0)
        if not isinstance(status, dict) or status.get("appName") != "Sportarr":
            raise _not_sportarr()
        stats = await self._json(config, ctx, "/stats", cache=0)
        leagues = int(stats.get("leagues") or 0) if isinstance(stats, dict) else 0
        return f"Sportarr {status.get('version') or '?'} answers with {leagues} leagues."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        # To the minute, so two cards asking in the same minute share one answer.
        now = datetime.now(UTC).replace(second=0, microsecond=0)
        if widget_kind == "upcoming":
            return self._calendar(await self._upcoming(config, ctx, max(1, int(options.get("days") or 7)), now))
        if widget_kind == "missing":
            return self._missing_list(await self._missing(config, ctx, max(1, int(options.get("limit") or 8))), now)
        missing = await self._missing(config, ctx, 1)
        upcoming = await self._upcoming(config, ctx, 7, now)
        stats = await self._json(config, ctx, "/stats", cache=300)
        if not isinstance(stats, dict):
            raise _not_sportarr()
        return self._summary(missing, upcoming, stats)

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def _calendar(events: list[dict[str, Any]]) -> WidgetData:
        items = []
        for event in events:
            start = str(event.get("eventDate") or "")
            if len(start) < 10:
                continue
            items.append({
                # The day in UTC, like the other calendars; eventDate is the start in UTC.
                "date": start[:10],
                "title": str(event.get("title") or "?"),
                "subtitle": str(event.get("leagueName") or event.get("sport") or ""),
                "status": "ok" if event.get("hasFile") else "unknown",
            })
        return WidgetData(status="ok", items=items, secondary=[{"label": "Next days", "value": len(items)}],
                          metrics={"upcoming": float(len(items))})

    @staticmethod
    def _missing_list(page: dict[str, Any], now: datetime) -> WidgetData:
        events = [one for one in page.get("events") or [] if isinstance(one, dict)]
        total = int(page.get("totalRecords") or len(events))
        items = [{
            "title": str(event.get("title") or "?"),
            "subtitle": str(event.get("leagueName") or event.get("sport") or ""),
            "status": "warn",
            "value": ago(event.get("eventDate"), now=now.timestamp()),
        } for event in events]
        return WidgetData(status="ok", items=items, secondary=[{"label": "Missing", "value": total}],
                          metrics={"missing": float(total)}, meta={"empty": "Nothing is missing."})

    @staticmethod
    def _summary(missing: dict[str, Any], upcoming: list[dict[str, Any]], stats: dict[str, Any]) -> WidgetData:
        total = int(missing.get("totalRecords") or 0)
        return WidgetData(
            status="ok",
            primary={"label": "Missing", "value": total},
            secondary=[{"label": "Upcoming", "value": len(upcoming)}, {"label": "Leagues", "value": int(stats.get("leagues") or 0)}],
            metrics={"missing": float(total), "upcoming": float(len(upcoming))},
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        now = datetime.now(UTC).replace(second=0, microsecond=0)

        def at(hours: float) -> str:
            return (now + timedelta(hours=hours)).strftime(SPORTARR_TIME)

        coming = [
            {"title": "Fight Night Example vs Sample", "leagueName": "UFC", "eventDate": at(20), "hasFile": False},
            {"title": "Grand Prix of Example", "leagueName": "Formula 1", "eventDate": at(50), "hasFile": False},
            {"title": "Premier Example Derby", "leagueName": "English Premier League", "eventDate": at(96), "hasFile": False},
        ]
        past = [
            {"title": "Contender Series Week 5", "leagueName": "UFC", "eventDate": at(-60)},
            {"title": "Qualifying at Example Park", "leagueName": "Formula 1", "eventDate": at(-130)},
            {"title": "Fight Night Model vs Pattern", "leagueName": "UFC", "eventDate": at(-150)},
        ]
        missing = {"events": past, "totalRecords": 38 + tick % 3}
        if widget_kind == "upcoming":
            return self._calendar(coming)
        if widget_kind == "missing":
            return self._missing_list(missing, now)
        return self._summary(missing, coming, {"leagues": 4})


ADAPTER = SportarrAdapter()
