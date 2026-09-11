"""Dawarich: how far you went this month and this year, and when the last point came in.

Measured against Dawarich 1.14.3 on 11.09.2026, with an account, 144 points of
a made-up walk over ten days of this month and two days of last month, sent
as an Overland batch.

⚠️ The distances lag behind the points. Right after the import the points
were counted (144) and the distance stood at 0 km for more than five minutes,
with no yearly breakdown at all; the job that fills them runs every hour
(``config/schedule.yml``). Run by hand it gave 53 km. The card therefore
shows when the last point arrived, which is current at once.

⚠️ The monthly distances come as whole kilometres, the months as English
names in lower case.

⚠️ The API key works as ``?api_key=`` and as a bearer header. The card sends
the header, so the key stays out of addresses and logs. A missing and a wrong
key both get 401 with an empty body.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
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

MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december")


class DawarichAdapter(Adapter):
    kind = "dawarich"
    label = "Dawarich"
    category = "other"
    description = "How far you went this month and this year, and when the last point came in."
    icon = "dawarich"
    beta = False
    docs_url = "https://dawarich.app/docs/"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://dawarich:3000"),
        Field("api_key", "API key", type="password", secret=True, required=True, help="The API key of your Dawarich account, from its settings."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(kind="summary", label="Distance", description="Kilometres this month and this year, and when the last point arrived.",
                   renderer="value", default_size=(3, 2), refresh_seconds=600, metrics=("month_km",),
                   options=(Field("stale_hours", "Warn after hours without a point", type="number", default=24,
                                  help="A phone that stopped sending shows up here. 0 never warns."),)),
        WidgetType(kind="months", label="Distance by month", description="The kilometres of every month of this year so far.",
                   renderer="list", default_size=(3, 3), refresh_seconds=3600),
    )

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, params: dict[str, Any] | None = None) -> Any:
        response = await ctx.request(
            "GET", f"{base_url(config)}/api/v1{path}", headers={"Authorization": f"Bearer {config.get('api_key') or ''}"},
            params=params, verify=not config.get("insecure"), cache_seconds=30, auth_errors=False,
        )
        if response.status_code in (401, 403):
            raise AuthFailed("Dawarich rejected the API key.")
        if response.status_code >= 400:
            raise AdapterError(f"Dawarich answered with HTTP {response.status_code}.", code="http_error",
                               hint="Check the URL; it is the address of Dawarich itself, without /api.")
        return response

    async def _json(self, config: dict[str, Any], ctx: Context, path: str, params: dict[str, Any] | None = None) -> Any:
        response = await self._get(config, ctx, path, params)
        try:
            return response.json()
        except ValueError as error:
            raise AdapterError("Dawarich did not answer with JSON.", code="not_json",
                               hint="The URL probably points at the sign-in page or a reverse proxy.") from error

    async def _stats(self, config: dict[str, Any], ctx: Context) -> dict[str, Any]:
        stats = await self._json(config, ctx, "/stats")
        if not isinstance(stats, dict) or "totalPointsTracked" not in stats:
            raise AdapterError("This address answers, but not the way Dawarich does.", code="not_dawarich")
        return stats

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        health = await self._get(config, ctx, "/health")
        stats = await self._stats(config, ctx)
        version = health.headers.get("x-dawarich-version") or "?"
        return f"Dawarich {version} answers: {int(stats.get('totalPointsTracked') or 0)} points tracked."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        stats = await self._stats(config, ctx)
        now = datetime.now(UTC)
        if widget_kind == "months":
            return self._months(stats, now)
        points = await self._json(config, ctx, "/points", {"order": "desc", "per_page": 1})
        last = points[0] if isinstance(points, list) and points and isinstance(points[0], dict) else None
        return self._summary(stats, last, now, options)

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def _year(stats: dict[str, Any], year: int) -> dict[str, Any]:
        for entry in stats.get("yearlyStats") or []:
            if isinstance(entry, dict) and int(entry.get("year") or 0) == year:
                return entry
        return {}

    def _summary(self, stats: dict[str, Any], last: dict[str, Any] | None, now: datetime, options: dict[str, Any]) -> WidgetData:
        year = self._year(stats, now.year)
        month_km = float((year.get("monthlyDistanceKm") or {}).get(MONTHS[now.month - 1]) or 0)
        secondary: list[dict[str, Any]] = [{"label": "This year", "value": f"{int(year.get('totalDistanceKm') or 0)} km"}]
        if stats.get("totalCountriesVisited"):
            secondary.append({"label": "Countries", "value": int(stats["totalCountriesVisited"])})
        seen = float(last.get("timestamp") or 0) if last else 0.0
        if seen:
            secondary.append({"label": "Last point", "value": ago(seen, now.timestamp())})
        stale_hours = float(options.get("stale_hours") if options.get("stale_hours") is not None else 24)
        stale = bool(stale_hours) and (not seen or now.timestamp() - seen > stale_hours * 3600)
        return WidgetData(
            status="warn" if stale else "ok",
            primary={"label": "This month", "value": int(month_km), "unit": "km"},
            secondary=secondary,
            metrics={"month_km": month_km},
        )

    def _months(self, stats: dict[str, Any], now: datetime) -> WidgetData:
        year = self._year(stats, now.year)
        distances = year.get("monthlyDistanceKm") or {}
        so_far = [(name, float(distances.get(name) or 0)) for name in MONTHS[: now.month]]
        # Months before the first one with a distance are months nothing was tracked in yet.
        first = next((index for index, (_name, km) in enumerate(so_far) if km), len(so_far))
        so_far = so_far[first:]
        longest = max((km for _name, km in so_far), default=0.0)
        # The list draws a title as it came; the month's name goes where words are translated.
        items = [{
            "title": f"{now.year}-{MONTHS.index(name) + 1:02d}",
            "subtitle": name.capitalize(),
            "status": "ok",
            "value": f"{int(km)} km",
            "progress": round(100 * km / longest) if longest else 0.0,
        } for name, km in reversed(so_far)]
        return WidgetData(
            status="ok",
            items=items,
            # Dawarich's own total: the months are whole kilometres, and adding them up comes out lower.
            secondary=[{"label": "This year", "value": f"{int(year.get('totalDistanceKm') or 0)} km"}] if so_far else [],
            meta={"empty": "No distance calculated yet."},
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        now = datetime.now(UTC)
        monthly = {name: [112, 96, 140, 180, 233, 260, 301, 288, 154, 0, 0, 0][index] for index, name in enumerate(MONTHS)}
        stats = {"totalPointsTracked": 812_004, "totalCountriesVisited": 3,
                 "yearlyStats": [{"year": now.year, "totalDistanceKm": sum(monthly.values()), "monthlyDistanceKm": monthly}]}
        if widget_kind == "months":
            return self._months(stats, now)
        return self._summary(stats, {"timestamp": time.time() - 600 - tick * 60}, now, options)


ADAPTER = DawarichAdapter()
