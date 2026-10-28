"""GoatCounter: visits, the pages people read and where they came from.

Measured on 27.10.2026 against arp242/goatcounter (build of 2025-12-15,
SQLite) with one site and four visits sent through ``/api/v0/count``.

- ``Authorization: Bearer <token>``. The statistics need the permission
  ``stats``, which is **not** among the ones the command line offers for
  ``goatcounter db create apitoken`` (count, export, site_read, site_create,
  site_update); the settings page of the site has it. A token without it is
  answered **403** with an HTML page ("requires 'stats' permissions"), a wrong
  or missing one **401** with an HTML page as well.
- Four requests a second per address (``X-Rate-Limit-*``), answered with 429.
- ``/api/v0/stats/total`` has one entry per day from ``start`` to ``end`` with
  ``daily`` and 24 ``hourly`` counts, and the sum in ``total``.
  ``/stats/hits`` is the same for each page, ``/stats/toprefs`` the referrers
  (an empty ``name`` is a visit without one).
- GoatCounter counts visits (one per session), not every page view.
- ``/status`` answers without a token with a build identifier, not a version
  number, so the test does not print one.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
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

PERIODS = (("today", "Today"), ("week", "The last 7 days"), ("month", "The last 30 days"))
DAYS = {"today": 1, "week": 7, "month": 30}

PERIOD_FIELD = Field("period", "Period", type="select", default="week", options=PERIODS)


def _period(options: dict[str, Any]) -> int:
    return DAYS.get(str(options.get("period") or "week"), 7)


def _window(days: int, now: datetime | None = None) -> dict[str, str]:
    """``start`` and ``end`` for the last ``days`` days including today, in UTC."""
    today = (now or datetime.now(UTC)).replace(hour=0, minute=0, second=0, microsecond=0)
    return {"start": (today - timedelta(days=days - 1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end": (today + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")}


class GoatcounterAdapter(Adapter):
    kind = "goatcounter"
    label = "GoatCounter"
    category = "monitoring"
    description = "Visits to your sites, the pages people read and where they came from, from GoatCounter."
    icon = "goatcounter"
    docs_url = "https://www.goatcounter.com/api"
    #: Measured against one self-hosted GoatCounter with four visits.
    beta = True
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="https://stats.example.com",
              help="The address of the site in GoatCounter, the one it answers to; with GoatCounter's own hosting that is https://yourcode.goatcounter.com."),
        Field("token", "API token", type="password", secret=True, required=True,
              help="Settings > API on the site. The permission to read statistics is the only one it needs."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(
            kind="visits",
            label="Visits",
            description="Visits today, yesterday and over the last week and month.",
            renderer="stats",
            default_size=(3, 2),
            refresh_seconds=300,
            metrics=("today", "week"),
        ),
        WidgetType(
            kind="pages",
            label="Top pages",
            description="The pages with the most visits in a period.",
            renderer="list",
            default_size=(4, 3),
            min_size=(3, 2),
            refresh_seconds=600,
            options=(PERIOD_FIELD, Field("limit", "Entries", type="number", default=8)),
        ),
        WidgetType(
            kind="referrers",
            label="Top referrers",
            description="Where visits came from in a period, and how many arrived without one.",
            renderer="list",
            default_size=(4, 3),
            min_size=(3, 2),
            refresh_seconds=600,
            options=(PERIOD_FIELD, Field("limit", "Entries", type="number", default=8)),
        ),
    )

    # -- asking GoatCounter ----------------------------------------------------

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, params: dict[str, Any] | None = None, cache: float = 30) -> Any:
        token = str(config.get("token") or "").strip()
        response = await ctx.request(
            "GET", f"{base_url(config)}/api/v0{path}", params=params, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            verify=not config.get("insecure"), cache_seconds=cache, timeout=20, auth_errors=False)
        if response.status_code == 401:
            raise AuthFailed("GoatCounter rejected the token.")
        if response.status_code == 403:
            failure = AuthFailed("This token may not read statistics.")
            failure.hint = "Make the token in the site's Settings > API with the permission to read statistics; one made with goatcounter db create apitoken cannot have it."
            raise failure
        if response.status_code == 429:
            raise AdapterError(f"GoatCounter allows four requests a second; try again in {response.headers.get('retry-after') or 1} s.", code="rate_limited",
                               hint="Give the cards a longer interval.")
        if response.status_code == 404:
            raise AdapterError("This address answers, but not the way GoatCounter does.", code="not_goatcounter",
                               hint="The URL is the address of the site in GoatCounter, without /api.")
        if response.status_code >= 400:
            raise AdapterError(f"GoatCounter answered with HTTP {response.status_code}.", code="http_error")
        try:
            return response.json()
        except ValueError as error:
            raise AdapterError("GoatCounter did not answer with JSON.", code="not_json",
                               hint="The URL probably points at something else than GoatCounter.") from error

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        window = _window(1)
        total = await self._get(config, ctx, "/stats/total", window, cache=0)
        if not isinstance(total, dict) or "total" not in total:
            raise AdapterError("This address answers, but not the way GoatCounter does.", code="not_goatcounter")
        return f"GoatCounter accepts the token: {int(total.get('total') or 0)} visits today."

    # -- the cards ---------------------------------------------------------------

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        link = base_url(config)
        if widget_kind == "visits":
            return self.visits_card(await self._get(config, ctx, "/stats/total", _window(30)), link)
        days = _period(options)
        limit = max(1, min(50, int(options.get("limit") or 8)))
        if widget_kind == "pages":
            answer = await self._get(config, ctx, "/stats/hits", {**_window(days), "limit": limit})
            return self.pages_card(answer, limit, link)
        answer = await self._get(config, ctx, "/stats/toprefs", {**_window(days), "limit": limit})
        return self.referrers_card(answer, limit, link)

    @staticmethod
    def visits_card(total: Any, link: str | None = None, now: datetime | None = None) -> WidgetData:
        days = {str(one.get("day")): int(one.get("daily") or 0) for one in (total or {}).get("stats") or [] if isinstance(one, dict)}
        today = (now or datetime.now(UTC)).date()
        count = lambda back: days.get((today - timedelta(days=back)).isoformat(), 0)  # noqa: E731
        week = sum(count(back) for back in range(7))
        month = sum(days.values())
        return WidgetData(
            status="ok",
            primary={"label": "Today", "value": count(0)},
            secondary=[{"label": "Yesterday", "value": count(1)}, {"label": "Last 7 days", "value": week}, {"label": "Last 30 days", "value": month}],
            metrics={"today": float(count(0)), "week": float(week)},
            link=link,
        )

    @staticmethod
    def pages_card(answer: Any, limit: int, link: str | None = None) -> WidgetData:
        hits = [one for one in (answer or {}).get("hits") or [] if isinstance(one, dict) and not one.get("event")]
        top = max((int(one.get("count") or 0) for one in hits), default=0)
        items = []
        for one in hits[:limit]:
            count = int(one.get("count") or 0)
            title = str(one.get("title") or "")
            items.append({
                "title": str(one.get("path") or "?"),
                "subtitle": title if title and title != one.get("path") else "",
                "value": str(count),
                "progress": round(100 * count / top, 1) if top else 0.0,
            })
        return WidgetData(
            status="ok",
            items=items,
            # The sum of the visits to every page, the pages that are shown or not.
            secondary=[{"label": "Visits", "value": int((answer or {}).get("total") or 0)}],
            link=link,
            meta={"empty": "No visits in this period."},
        )

    @staticmethod
    def referrers_card(answer: Any, limit: int, link: str | None = None) -> WidgetData:
        stats = [one for one in (answer or {}).get("stats") or [] if isinstance(one, dict)]
        top = max((int(one.get("count") or 0) for one in stats), default=0)
        items = []
        for one in stats[:limit]:
            count = int(one.get("count") or 0)
            name = str(one.get("name") or "")
            items.append({
                "title": name or "Direct",
                "subtitle": "" if name else "No referrer",
                "value": str(count),
                "progress": round(100 * count / top, 1) if top else 0.0,
            })
        return WidgetData(status="ok", items=items, link=link, meta={"empty": "No visits in this period."})

    # -- demo --------------------------------------------------------------------

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        now = datetime.fromtimestamp(time.time() - tick % 60, UTC)
        if widget_kind == "visits":
            today = now.date()
            stats = [{"day": (today - timedelta(days=back)).isoformat(),
                      "daily": int(fake.walk(f"goat-day-{back}", 0, 40, 120)) + (int(tick / 40) if back == 0 else 0)} for back in range(29, -1, -1)]
            return self.visits_card({"stats": stats}, None, now)
        limit = int(options.get("limit") or 8)
        scale = DAYS.get(str(options.get("period") or "week"), 7)
        if widget_kind == "pages":
            paths = [("/", "Home", 118), ("/blog/self-hosting-notes", "Self-hosting notes", 87), ("/about", "About", 41),
                     ("/projects/dashboard", "The dashboard", 36), ("/blog/backups", "Backups that work", 22)]
            hits = [{"path": path, "title": title, "count": int(base * scale / 4 + fake.walk(f"goat-{path}", tick, 0, 6))} for path, title, base in paths]
            return self.pages_card({"total": len(hits), "hits": sorted(hits, key=lambda one: -one["count"])}, limit)
        refs = [("", 64), ("https://news.example.org/", 31), ("https://search.example.net/", 22), ("https://social.example.com/", 9)]
        stats = [{"name": name, "count": int(base * scale / 4 + fake.walk(f"goat-ref-{name}", tick, 0, 4))} for name, base in refs]
        return self.referrers_card({"stats": sorted(stats, key=lambda one: -one["count"])}, limit)


ADAPTER = GoatcounterAdapter()
