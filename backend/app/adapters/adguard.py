"""AdGuard Home: queries, blocked share and protection on or off."""

from __future__ import annotations

from typing import Any

from . import demo as fake
from .base import Action, Adapter, AdapterError, Context, Field, WidgetData, WidgetType, base_url


class AdguardAdapter(Adapter):
    kind = "adguard"
    label = "AdGuard Home"
    category = "network"
    description = "Queries, blocked share, top blocked domains, protection on or off."
    icon = "adguard-home"
    #: Seen against a live AdGuard Home v0.107.79 (06.09.2026).
    beta = False
    docs_url = "https://github.com/AdguardTeam/AdGuardHome/tree/master/openapi"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://adguard:3000"),
        Field("username", "User name", required=True),
        Field("password", "Password", type="password", secret=True, required=True),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(kind="summary", label="Protection", description="Blocked share, queries and a pause button.", renderer="gauge", default_size=(2, 2), refresh_seconds=30, metrics=("blocked_percent", "queries")),
        WidgetType(kind="top", label="Top blocked", description="The domains blocked most often.", renderer="list", default_size=(3, 3), refresh_seconds=120, options=(Field("limit", "Entries", type="number", default=8),)),
    )

    def _auth(self, config: dict[str, Any]) -> tuple[str, str]:
        return (str(config.get("username") or ""), str(config.get("password") or ""))

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, cache: float = 10) -> Any:
        return await ctx.get_json(f"{base_url(config)}/control{path}", auth=self._auth(config), verify=not config.get("insecure"), cache_seconds=cache)

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        status = await self._get(config, ctx, "/status", cache=0)
        return f"AdGuard Home {status.get('version', '?')} answers."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        stats = await self._get(config, ctx, "/stats")
        if widget_kind == "top":
            limit = int(options.get("limit") or 8)
            items = []
            for entry in (stats.get("top_blocked_domains") or [])[:limit]:
                for domain, count in entry.items():
                    items.append({"title": domain, "value": count, "status": "bad"})
            return WidgetData(items=items)
        status = await self._get(config, ctx, "/status", cache=5)
        total = float(stats.get("num_dns_queries") or 0)
        blocked = float(stats.get("num_blocked_filtering") or 0)
        share = round(100 * blocked / total, 1) if total else 0.0
        enabled = bool(status.get("protection_enabled", True))
        return WidgetData(
            status="ok" if enabled else "warn",
            primary={"label": "Blocked" if enabled else "Protection paused", "value": share, "unit": "%"},
            secondary=[{"label": "Queries", "value": int(total)}, {"label": "Blocked", "value": int(blocked)}, {"label": "Avg", "value": round(float(stats.get("avg_processing_time") or 0) * 1000), "unit": "ms"}],
            metrics={"blocked_percent": share, "queries": total},
            actions=[Action(id="enable", label="Enable", icon="play")] if not enabled else [Action(id="disable", label="Pause 5 min", icon="pause", params={"duration": 300000})],
        )

    async def action(self, widget_kind: str, action_id: str, params: dict[str, Any], config: dict[str, Any], options: dict[str, Any], ctx: Context) -> str:
        if action_id not in ("enable", "disable"):
            raise AdapterError("Unknown action.", code="no_such_action")
        body: dict[str, Any] = {"enabled": action_id == "enable"}
        if action_id == "disable":
            body["duration"] = int(params.get("duration") or 300000)
        response = await ctx.request("POST", f"{base_url(config)}/control/protection", json_body=body, auth=self._auth(config), verify=not config.get("insecure"))
        if response.status_code >= 400:
            raise AdapterError(f"AdGuard Home answered with HTTP {response.status_code}.", code="http_error")
        return "Protection enabled." if action_id == "enable" else "Protection paused for five minutes."

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        if widget_kind == "top":
            domains = ["ads.example.net", "tracking.example.org", "metrics.example.com", "beacon.example.io"]
            return WidgetData(items=[{"title": d, "value": fake.counter(d, tick, 700, 0.3) - i * 120, "status": "bad"} for i, d in enumerate(domains)])
        total = fake.counter("adguard-total", tick, 52000, 0.5)
        share = fake.walk("adguard-share", tick, 9, 16, period=800)
        return WidgetData(primary={"label": "Blocked", "value": share, "unit": "%"},
                          secondary=[{"label": "Queries", "value": total}, {"label": "Blocked", "value": int(total * share / 100)}, {"label": "Avg", "value": 3, "unit": "ms"}],
                          metrics={"blocked_percent": share, "queries": float(total)},
                          actions=[Action(id="disable", label="Pause 5 min", icon="pause", params={"duration": 300000})])


ADAPTER = AdguardAdapter()
