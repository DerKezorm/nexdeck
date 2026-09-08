"""Uptime Kuma through its Prometheus metrics endpoint.

Uptime Kuma has no REST API for monitors; ``/metrics`` (protected by the
API key as the basic-auth password) lists every monitor with its state and
response time, which is exactly what a dashboard needs.
"""

from __future__ import annotations

import re
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
    ring_of,
)

LINE = re.compile(r'^(?P<name>[a-zA-Z_:][a-zA-Z0-9_:]*)\{(?P<labels>[^}]*)\}\s+(?P<value>[-+0-9.eEnaN]+)')
LABEL = re.compile(r'(\w+)="((?:[^"\\]|\\.)*)"')


def parse_metrics(text: str) -> list[tuple[str, dict[str, str], float]]:
    rows = []
    for line in text.splitlines():
        if line.startswith("#"):
            continue
        match = LINE.match(line)
        if not match:
            continue
        labels = {k: v.replace('\\"', '"') for k, v in LABEL.findall(match.group("labels"))}
        try:
            value = float(match.group("value"))
        except ValueError:
            continue
        rows.append((match.group("name"), labels, value))
    return rows


class UptimeKumaAdapter(Adapter):
    kind = "uptimekuma"
    label = "Uptime Kuma"
    category = "monitoring"
    description = "Every monitor with state and response time."
    icon = "uptime-kuma"
    docs_url = "https://github.com/louislam/uptime-kuma/wiki/API-Keys"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://uptime-kuma:3001"),
        Field("api_key", "API key", type="password", secret=True, required=True, help="Settings > API Keys"),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(kind="monitors", label="Monitors", description="All monitors, down ones first.", renderer="list", default_size=(3, 3), refresh_seconds=30, metrics=("down",), options=(Field("limit", "Entries", type="number", default=12), Field("filter", "Name filter"))),
        WidgetType(kind="summary", label="Up and down", description="How many monitors are up and down.", renderer="value", default_size=(2, 1), min_size=(1, 1), refresh_seconds=30, ring=True, metrics=("down",)),
    )

    async def _metrics(self, config: dict[str, Any], ctx: Context, cache: float = 10) -> list[tuple[str, dict[str, str], float]]:
        response = await ctx.request("GET", f"{base_url(config)}/metrics", auth=("", str(config.get("api_key") or "")), verify=not config.get("insecure"), cache_seconds=cache)
        if response.status_code == 401:
            raise AuthFailed("Uptime Kuma rejected the API key.")
        if response.status_code >= 400:
            raise AdapterError(f"Uptime Kuma answered with HTTP {response.status_code}.", code="http_error")
        return parse_metrics(response.text)

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        rows = await self._metrics(config, ctx, cache=0)
        monitors = {labels.get("monitor_name") for name, labels, _ in rows if name == "monitor_status"}
        return f"Uptime Kuma answers with {len(monitors)} monitors."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        rows = await self._metrics(config, ctx)
        monitors: dict[str, dict[str, Any]] = {}
        for name, labels, value in rows:
            key = labels.get("monitor_name") or labels.get("monitor_url") or "?"
            entry = monitors.setdefault(key, {"name": key, "type": labels.get("monitor_type", ""), "url": labels.get("monitor_url", ""), "status": None, "latency": None})
            if name == "monitor_status":
                entry["status"] = int(value)
            elif name == "monitor_response_time":
                entry["latency"] = int(value)
        down = [m for m in monitors.values() if m["status"] == 0]
        if widget_kind == "summary":
            return WidgetData(status="bad" if down else "ok", primary={"label": "Monitors up", "value": len(monitors) - len(down), "unit": f"/ {len(monitors)}"},
                              secondary=[{"label": "Down", "value": len(down)}],
                              meta={"ring": ring_of(("Up", len(monitors) - len(down)), ("Down", len(down)))},
                              metrics={"down": float(len(down))})
        needle = str(options.get("filter") or "").lower()
        ordered = sorted(monitors.values(), key=lambda m: (m["status"] != 0, m["status"] != 2, m["name"].lower()))
        items = []
        for monitor in ordered:
            if needle and needle not in monitor["name"].lower():
                continue
            status = {1: "ok", 0: "bad", 2: "warn", 3: "unknown"}.get(monitor["status"], "unknown")
            items.append({"title": monitor["name"], "subtitle": monitor["type"] or monitor["url"], "status": status,
                          "value": f"{monitor['latency']} ms" if monitor["latency"] is not None and status != "bad" else ("down" if status == "bad" else "")})
        return WidgetData(status="bad" if down else "ok", items=items[: int(options.get("limit") or 12)],
                          secondary=[{"label": "Up", "value": len(monitors) - len(down)}, {"label": "Down", "value": len(down)}], metrics={"down": float(len(down))})

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        names = ["Reverse proxy", "Nexview", "Jellyfin", "SABnzbd", "Home Assistant", "NAS", "Pi-hole", "Proxmox"]
        down = {"SABnzbd"} if fake.flicker("uk-sab", tick, 0.7) else set()
        if widget_kind == "summary":
            return WidgetData(status="bad" if down else "ok", primary={"label": "Monitors up", "value": len(names) - len(down), "unit": f"/ {len(names)}"}, secondary=[{"label": "Down", "value": len(down)}],
                              meta={"ring": ring_of(("Up", len(names) - len(down)), ("Down", len(down)))},
                              metrics={"down": float(len(down))})
        items = [{"title": n, "subtitle": "http", "status": "bad" if n in down else "ok", "value": "down" if n in down else f"{int(fake.walk(n, tick, 4, 90))} ms"} for n in names]
        items.sort(key=lambda i: i["status"] != "bad")
        return WidgetData(status="bad" if down else "ok", items=items, secondary=[{"label": "Up", "value": len(names) - len(down)}, {"label": "Down", "value": len(down)}], metrics={"down": float(len(down))})


ADAPTER = UptimeKumaAdapter()
