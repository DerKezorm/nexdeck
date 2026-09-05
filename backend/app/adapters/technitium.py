"""Technitium DNS: queries, the blocked share and the loudest domains.

The third DNS blocker beside Pi-hole and AdGuard Home. Its API takes a token
that is created in the web interface; every address answers
``{"status": "ok", "response": {...}}``.

⚠️ Measured against a live 15.4: a freshly started server answers the day
and week ranges with zeros while the hour range already has the numbers.
Technitium rolls the hourly figures up later, so a new installation looks
empty on the default range for a while. That is the server, not this card.
"""

from __future__ import annotations

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

RANGES = (("LastHour", "Last hour"), ("LastDay", "Last day"), ("LastWeek", "Last week"))


class TechnitiumAdapter(Adapter):
    kind = "technitium"
    label = "Technitium DNS"
    category = "network"
    description = "Queries, the blocked share, clients and the domains blocked most."
    icon = "technitium"
    docs_url = "https://github.com/TechnitiumSoftware/DnsServer/blob/master/APIDOCS.md"
    #: Seen against a live Technitium 15.4 (05.09.2026).
    beta = False
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://technitium:5380"),
        Field("token", "API token", type="password", secret=True, required=True, help="Administration > Sessions > Create Token."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(
            kind="summary",
            label="Blocking",
            description="The blocked share with queries and clients beside it.",
            renderer="gauge",
            default_size=(2, 2),
            refresh_seconds=60,
            metrics=("blocked_percent", "queries"),
            options=(Field("range", "Range", type="select", default="LastDay", options=RANGES),),
        ),
        WidgetType(
            kind="top",
            label="Top blocked",
            description="The domains blocked most often.",
            renderer="list",
            default_size=(3, 3),
            refresh_seconds=300,
            options=(
                Field("range", "Range", type="select", default="LastDay", options=RANGES),
                Field("limit", "Entries", type="number", default=8),
            ),
        ),
    )

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, params: dict[str, Any], cache: float = 30) -> Any:
        payload = await ctx.get_json(
            f"{base_url(config)}{path}",
            params={"token": str(config.get("token") or ""), **params},
            verify=not config.get("insecure"),
            cache_seconds=cache,
        )
        status = str((payload or {}).get("status") or "")
        if status == "invalid-token":
            raise AuthFailed("Technitium rejected the token.")
        if status != "ok":
            raise AdapterError(str((payload or {}).get("errorMessage") or "Technitium refused the request."), code="http_error")
        return (payload or {}).get("response") or {}

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        response = await self._get(config, ctx, "/api/dashboard/stats/get", {"type": "LastHour", "utc": "true"}, cache=0)
        stats = response.get("stats") or {}
        return f"Technitium answers with {int(stats.get('totalQueries') or 0)} queries in the last hour."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        window = str(options.get("range") or "LastDay")
        if widget_kind == "top":
            limit = int(options.get("limit") or 8)
            response = await self._get(
                config, ctx, "/api/dashboard/stats/getTop",
                {"type": window, "statsType": "TopBlockedDomains", "limit": limit, "utc": "true"},
                cache=300,
            )
            domains = response.get("topBlockedDomains") or []
            items = [{"title": entry.get("name") or "?", "value": int(entry.get("hits") or 0), "status": "bad"} for entry in domains[:limit]]
            return WidgetData(items=items, secondary=[{"label": "Entries", "value": len(items)}])

        response = await self._get(config, ctx, "/api/dashboard/stats/get", {"type": window, "utc": "true"}, cache=60)
        stats = response.get("stats") or {}
        total = float(stats.get("totalQueries") or 0)
        blocked = float(stats.get("totalBlocked") or 0)
        share = round(100.0 * blocked / total, 1) if total else 0.0
        return WidgetData(
            primary={"label": "Blocked", "value": share, "unit": "%"},
            secondary=[
                {"label": "Queries", "value": int(total)},
                {"label": "Blocked", "value": int(blocked)},
                {"label": "Clients", "value": int(stats.get("totalClients") or 0)},
            ],
            metrics={"blocked_percent": share, "queries": total},
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        if widget_kind == "top":
            domains = ["ads.example.net", "tracking.example.org", "metrics.example.com", "beacon.example.io", "telemetry.example.dev"]
            return WidgetData(
                items=[{"title": domain, "value": fake.counter(domain, tick, 700, 0.3) - index * 120, "status": "bad"} for index, domain in enumerate(domains)],
                secondary=[{"label": "Entries", "value": len(domains)}],
            )
        total = fake.counter("technitium-total", tick, 41000, 0.7)
        share = fake.walk("technitium-share", tick, 11, 19, period=700)
        return WidgetData(
            primary={"label": "Blocked", "value": share, "unit": "%"},
            secondary=[
                {"label": "Queries", "value": total},
                {"label": "Blocked", "value": int(total * share / 100)},
                {"label": "Clients", "value": 26},
            ],
            metrics={"blocked_percent": share, "queries": float(total)},
        )


ADAPTER = TechnitiumAdapter()
