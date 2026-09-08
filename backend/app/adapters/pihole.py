"""Pi-hole v6 API: queries, blocking and a pause button."""

from __future__ import annotations

from typing import Any

from . import demo as fake
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
    ring_of,
)


class PiholeAdapter(Adapter):
    kind = "pihole"
    label = "Pi-hole"
    category = "network"
    description = "Queries, blocked share, top domains, and blocking on or off."
    icon = "pi-hole"
    #: Seen against a live Pi-hole v6.4.3 (06.09.2026).
    beta = False
    docs_url = "https://docs.pi-hole.net/api/"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://pi.hole"),
        Field("password", "App password", type="password", secret=True, required=True, help="Settings > Web interface / API > App password (Pi-hole v6)."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(kind="summary", label="Blocking", description="Blocked share, queries, clients and a pause button.", renderer="gauge", default_size=(2, 2), refresh_seconds=30, ring=True, metrics=("blocked_percent", "queries")),
        WidgetType(kind="top", label="Top blocked", description="The domains blocked most often today.", renderer="list", default_size=(3, 3), refresh_seconds=120, options=(Field("limit", "Entries", type="number", default=8),)),
    )

    async def _session(self, config: dict[str, Any], ctx: Context, force: bool = False) -> str:
        sid = ctx.cache.get("pihole_sid")
        if sid and not force:
            return sid
        response = await ctx.request("POST", f"{base_url(config)}/api/auth", json_body={"password": config.get("password", "")}, verify=not config.get("insecure"))
        payload = response.json() if response.status_code < 500 else {}
        session = (payload.get("session") or {})
        if response.status_code >= 400 or not session.get("valid"):
            raise AuthFailed("Pi-hole rejected the app password.")
        ctx.cache["pihole_sid"] = session.get("sid", "")
        return ctx.cache["pihole_sid"]

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, cache: float = 10, retry: bool = True) -> Any:
        sid = await self._session(config, ctx)
        response = await ctx.request("GET", f"{base_url(config)}/api{path}", headers={"sid": sid}, verify=not config.get("insecure"), cache_seconds=cache)
        if response.status_code == 401 and retry:
            await self._session(config, ctx, force=True)
            return await self._get(config, ctx, path, cache, retry=False)
        if response.status_code >= 400:
            raise AdapterError(f"Pi-hole answered with HTTP {response.status_code}.", code="http_error")
        return response.json()

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        info = await self._get(config, ctx, "/info/version", cache=0)
        core = ((info.get("version") or {}).get("core") or {}).get("local", {}).get("version", "?")
        return f"Pi-hole {core} answers."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "top":
            payload = await self._get(config, ctx, f"/stats/top_domains?blocked=true&count={int(options.get('limit') or 8)}", cache=60)
            items = [{"title": d.get("domain", "?"), "value": d.get("count", 0), "status": "bad"} for d in payload.get("domains") or []]
            return WidgetData(items=items)
        summary = await self._get(config, ctx, "/stats/summary")
        blocking = await self._get(config, ctx, "/dns/blocking", cache=5)
        queries = summary.get("queries") or {}
        total = float(queries.get("total") or 0)
        blocked = float(queries.get("blocked") or 0)
        share = round(float(queries.get("percent_blocked") or (100 * blocked / total if total else 0)), 1)
        enabled = blocking.get("blocking") == "enabled"
        return WidgetData(
            status="ok" if enabled else "warn",
            primary={"label": "Blocked today" if enabled else "Blocking paused", "value": share, "unit": "%"},
            secondary=[{"label": "Queries", "value": int(total)}, {"label": "Blocked", "value": int(blocked)}, {"label": "Clients", "value": (summary.get("clients") or {}).get("active", 0)}],
            meta={"ring": ring_of(("Blocked", blocked), ("Allowed", total - blocked))},
            metrics={"blocked_percent": share, "queries": total},
            actions=[Action(id="enable", label="Enable", icon="play")] if not enabled else [Action(id="disable", label="Pause 5 min", icon="pause", params={"timer": 300})],
        )

    async def action(self, widget_kind: str, action_id: str, params: dict[str, Any], config: dict[str, Any], options: dict[str, Any], ctx: Context) -> str:
        if action_id not in ("enable", "disable"):
            raise AdapterError("Unknown action.", code="no_such_action")
        sid = await self._session(config, ctx)
        body: dict[str, Any] = {"blocking": action_id == "enable"}
        if action_id == "disable":
            body["timer"] = int(params.get("timer") or 300)
        response = await ctx.request("POST", f"{base_url(config)}/api/dns/blocking", json_body=body, headers={"sid": sid}, verify=not config.get("insecure"))
        if response.status_code >= 400:
            raise AdapterError(f"Pi-hole answered with HTTP {response.status_code}.", code="http_error")
        return "Blocking enabled." if action_id == "enable" else "Blocking paused for five minutes."

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        if widget_kind == "top":
            domains = ["ads.example.net", "tracking.example.org", "metrics.example.com", "beacon.example.io", "telemetry.example.dev"]
            return WidgetData(items=[{"title": d, "value": fake.counter(d, tick, 900, 0.4) - i * 150, "status": "bad"} for i, d in enumerate(domains)])
        total = fake.counter("pihole-total", tick, 38000, 0.6)
        share = fake.walk("pihole-share", tick, 14, 23, period=800)
        paused = fake.flicker("pihole-paused", tick, 0.08)
        return WidgetData(
            status="warn" if paused else "ok",
            primary={"label": "Blocking paused" if paused else "Blocked today", "value": share, "unit": "%"},
            secondary=[{"label": "Queries", "value": total}, {"label": "Blocked", "value": int(total * share / 100)}, {"label": "Clients", "value": 23}],
            meta={"ring": ring_of(("Blocked", int(total * share / 100)),
                                  ("Allowed", total - int(total * share / 100)))},
            metrics={"blocked_percent": share, "queries": float(total)},
            actions=[Action(id="enable", label="Enable", icon="play")] if paused else [Action(id="disable", label="Pause 5 min", icon="pause", params={"timer": 300})],
        )


ADAPTER = PiholeAdapter()
