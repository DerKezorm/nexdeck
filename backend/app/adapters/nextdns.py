"""NextDNS: the blocked share of a profile.

The resolver in the cloud, so the address is theirs, not yours. The key comes
from the account page and rides in ``X-Api-Key``.
"""

from __future__ import annotations

from typing import Any

from . import demo as fake
from .base import Adapter, Context, Field, WidgetData, WidgetType

API = "https://api.nextdns.io"
WINDOWS = (("-1h", "Last hour"), ("-24h", "Last day"), ("-7d", "Last week"), ("-30d", "Last month"))


class NextdnsAdapter(Adapter):
    kind = "nextdns"
    label = "NextDNS"
    category = "network"
    description = "Queries, the blocked share and the domains blocked most, per profile."
    icon = "nextdns"
    docs_url = "https://nextdns.github.io/api/"
    fields = (
        Field("api_key", "API key", type="password", secret=True, required=True, help="my.nextdns.io > Account > API key."),
        Field("profile", "Profile", required=True, help="The ID of the profile, six characters, from its address."),
    )
    widgets = (
        WidgetType(
            kind="summary",
            label="Blocking",
            description="The blocked share with the query counts beside it.",
            renderer="gauge",
            default_size=(2, 2),
            refresh_seconds=300,
            metrics=("blocked_percent", "queries"),
            options=(Field("window", "Range", type="select", default="-24h", options=WINDOWS),),
        ),
        WidgetType(
            kind="top",
            label="Top blocked",
            description="The domains blocked most often.",
            renderer="list",
            default_size=(3, 3),
            refresh_seconds=900,
            options=(
                Field("window", "Range", type="select", default="-24h", options=WINDOWS),
                Field("limit", "Entries", type="number", default=8),
            ),
        ),
    )

    def default_link(self, config: dict[str, Any]) -> str:
        return f"https://my.nextdns.io/{config.get('profile') or ''}/analytics"

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, params: dict[str, Any], cache: float = 300) -> Any:
        return await ctx.get_json(
            f"{API}/profiles/{str(config.get('profile') or '').strip()}{path}",
            headers={"X-Api-Key": str(config.get("api_key") or "")},
            params=params,
            cache_seconds=cache,
        )

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        payload = await self._get(config, ctx, "/analytics/status", {"from": "-1h"}, cache=0)
        total = sum(int(entry.get("queries") or 0) for entry in (payload or {}).get("data") or [])
        return f"NextDNS answers with {total} queries in the last hour."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        window = str(options.get("window") or "-24h")
        if widget_kind == "top":
            limit = int(options.get("limit") or 8)
            payload = await self._get(config, ctx, "/analytics/domains", {"from": window, "status": "blocked", "limit": limit}, cache=900)
            items = [
                {"title": entry.get("domain") or "?", "value": int(entry.get("queries") or 0), "status": "bad"}
                for entry in ((payload or {}).get("data") or [])[:limit]
            ]
            return WidgetData(items=items, secondary=[{"label": "Entries", "value": len(items)}])

        payload = await self._get(config, ctx, "/analytics/status", {"from": window})
        counts = {str(entry.get("status")): int(entry.get("queries") or 0) for entry in (payload or {}).get("data") or []}
        total = sum(counts.values())
        blocked = counts.get("blocked", 0)
        share = round(100.0 * blocked / total, 1) if total else 0.0
        return WidgetData(
            primary={"label": "Blocked", "value": share, "unit": "%"},
            secondary=[
                {"label": "Queries", "value": total},
                {"label": "Blocked", "value": blocked},
                {"label": "Allowed", "value": counts.get("allowed", 0)},
            ],
            metrics={"blocked_percent": share, "queries": float(total)},
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        if widget_kind == "top":
            domains = ["ads.example.net", "tracking.example.org", "metrics.example.com", "beacon.example.io"]
            return WidgetData(
                items=[{"title": domain, "value": fake.counter(domain, tick, 400, 0.2) - index * 70, "status": "bad"} for index, domain in enumerate(domains)],
                secondary=[{"label": "Entries", "value": len(domains)}],
            )
        total = fake.counter("nextdns-total", tick, 12800, 0.4)
        share = fake.walk("nextdns-share", tick, 8, 17, period=900)
        return WidgetData(
            primary={"label": "Blocked", "value": share, "unit": "%"},
            secondary=[
                {"label": "Queries", "value": total},
                {"label": "Blocked", "value": int(total * share / 100)},
                {"label": "Allowed", "value": 214},
            ],
            metrics={"blocked_percent": share, "queries": float(total)},
        )


ADAPTER = NextdnsAdapter()
