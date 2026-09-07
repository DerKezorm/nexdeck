"""TrueNAS SCALE through the REST API v2."""

from __future__ import annotations

from typing import Any

from . import demo as fake
from .base import (
    Adapter,
    Context,
    Detected,
    Field,
    WidgetData,
    WidgetType,
    base_url,
    duration_short,
    human_bytes,
    percent,
    percent_text,
    status_from_percent,
)


class TruenasAdapter(Adapter):
    kind = "truenas"
    label = "TrueNAS"
    category = "nas"
    description = "Pools, alerts, load and uptime."
    icon = "truenas"
    docs_url = "https://www.truenas.com/docs/api/"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="https://truenas.local"),
        Field("api_key", "API key", type="password", secret=True, required=True, help="Top-right user menu > API Keys"),
        Field("insecure", "Ignore TLS errors", type="bool", default=True),
    )
    widgets = (
        WidgetType(kind="system", label="System", description="Load, memory, uptime and open alerts.", renderer="stats", default_size=(4, 2), refresh_seconds=30, metrics=("load",)),
        WidgetType(kind="pools", label="Pools", description="Every pool with usage and health.", renderer="list", default_size=(3, 2), refresh_seconds=120),
        WidgetType(kind="alerts", label="Alerts", description="Open alerts by level.", renderer="list", default_size=(3, 2), refresh_seconds=60),
    )

    def _headers(self, config: dict[str, Any]) -> dict[str, str]:
        return {"Authorization": f"Bearer {config.get('api_key', '')}"}

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, cache: float = 10) -> Any:
        return await ctx.get_json(f"{base_url(config)}/api/v2.0{path}", headers=self._headers(config), verify=not config.get("insecure", True), cache_seconds=cache)

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        info = await self._get(config, ctx, "/system/info", cache=0)
        return f"TrueNAS {info.get('version', '?')} on {info.get('hostname', '?')} answers."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "system":
            info = await self._get(config, ctx, "/system/info")
            alerts = [a for a in await self._get(config, ctx, "/alert/list", cache=60) if not a.get("dismissed")]
            load = float((info.get("loadavg") or [0])[0])
            cores = int(info.get("cores") or 1)
            load_percent = round(100.0 * load / cores, 1)
            memory_total = float(info.get("physmem") or 0)
            return WidgetData(
                status="bad" if any(a.get("level") in ("CRITICAL", "ERROR") for a in alerts) else ("warn" if alerts else status_from_percent(load_percent)),
                primary={"label": "Load", "value": load_percent, "unit": "%"},
                secondary=[{"label": "Memory", "value": human_bytes(memory_total)}, {"label": "Uptime", "value": duration_short(info.get("uptime_seconds"))}, {"label": "Alerts", "value": len(alerts)}],
                metrics={"load": load_percent},
            )
        if widget_kind == "pools":
            items = []
            for pool in await self._get(config, ctx, "/pool", cache=60):
                used = percent(pool.get("allocated"), pool.get("size"))
                items.append({
                    "title": pool.get("name", "?"), "subtitle": f"{human_bytes(pool.get('allocated'))} of {human_bytes(pool.get('size'))} · {pool.get('status', '?')}",
                    "progress": used, "value": percent_text(used),
                    # A pool whose size did not come is not a healthy pool.
                    "status": "unknown" if used is None else ("ok" if pool.get("healthy") and used < 90 else "warn"),
                })
            return WidgetData(items=items)
        alerts = [a for a in await self._get(config, ctx, "/alert/list", cache=60) if not a.get("dismissed")]
        items = [{"title": str(a.get("formatted") or a.get("text", "?"))[:120], "subtitle": str(a.get("datetime", {}).get("$date", ""))[:10] if isinstance(a.get("datetime"), dict) else "", "status": "bad" if a.get("level") in ("CRITICAL", "ERROR") else "warn"} for a in alerts]
        return WidgetData(status="bad" if any(i["status"] == "bad" for i in items) else ("warn" if items else "ok"), items=items or [], secondary=[{"label": "Open", "value": len(items)}])

    #: Above this, a pool has stopped being somebody's problem for later.
    FULL_PERCENT = 90.0

    def detect(self, widget_kind: str, before: WidgetData | None, after: WidgetData,
               options: dict[str, Any]) -> list[Detected]:
        """A pool that crossed into the last tenth of itself.

        ⚠️ Only on the crossing. A pool that sits at 94 per cent for a month
        is not news every five minutes; it became news once.
        """
        if widget_kind not in ("pools", "volumes"):
            return []
        was = {}
        for item in (before.items if before and not before.error else []):
            was[str(item.get("title"))] = _percent(item)
        found = []
        for item in after.items:
            name = str(item.get("title") or "?")
            now = _percent(item)
            if now is None or now < self.FULL_PERCENT:
                continue
            earlier = was.get(name)
            if earlier is not None and earlier >= self.FULL_PERCENT:
                continue
            found.append(Detected(
                event="disk_filling",
                title=f"{name} is {now:.0f}% full",
                body=str(item.get("subtitle") or ""),
                level="warn",
                key=f"disk_filling:{name}",
                quiet_seconds=86400,
            ))
        return found[:5]

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        load = fake.walk("truenas-load", tick, 5, 30)
        if widget_kind == "system":
            return WidgetData(primary={"label": "Load", "value": load, "unit": "%"}, secondary=[{"label": "Memory", "value": "64.0 GB"}, {"label": "Uptime", "value": duration_short(12 * 86400 + tick)}, {"label": "Alerts", "value": 1}], metrics={"load": load}, status="warn")
        if widget_kind == "pools":
            return WidgetData(items=[{"title": "tank", "subtitle": "41.2 TB of 58.0 TB · ONLINE", "progress": 71.0, "value": "71%", "status": "ok"}, {"title": "fast", "subtitle": "1.2 TB of 1.8 TB · ONLINE", "progress": 66.6, "value": "67%", "status": "ok"}])
        return WidgetData(status="warn", items=[{"title": "Scrub of pool tank finished with 0 errors", "subtitle": "2026-09-04", "status": "warn"}], secondary=[{"label": "Open", "value": 1}])


ADAPTER = TruenasAdapter()


def _percent(item: dict[str, Any]) -> float | None:
    """How full, from whichever field the card put it in."""
    for key in ("progress", "percent", "used_percent"):
        value = item.get(key)
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
    raw = str(item.get("value") or "").rstrip("%")
    try:
        return float(raw)
    except ValueError:
        return None
