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
    ReadCommands,
    WidgetData,
    WidgetType,
    allowed,
    base_url,
    ring_of,
)

#: A slug as Uptime Kuma makes them: lower case letters, digits and dashes.
SLUG = re.compile(r"^[a-z0-9-]{1,64}$")

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


def status_page_field() -> Field:
    """Which status page the card keeps to.

    ⚠️ Typed, not picked from a list. Uptime Kuma lists its status pages only
    to a signed-in user over its socket, and a connection here has an API
    key, nothing more (measured on 1.23.17 and 2.x, 24.10.2026). The page
    itself answers without a key, so a slug that is wrong is said as such.
    """
    return Field("status_page", "Status page", placeholder="home",
                 help="Only the monitors of one status page: the last part of its address, as in /status/home. Empty means every monitor.")


class UptimeKumaAdapter(Adapter):
    kind = "uptimekuma"
    label = "Uptime Kuma"
    category = "monitoring"
    # Seen against a real instance (1.23.17) on 24.10.2026, the status pages against 1.23.17 and 2.x.
    beta = False
    description = "Every monitor with state and response time."
    icon = "uptime-kuma"
    docs_url = "https://github.com/louislam/uptime-kuma/wiki/API-Keys"
    #: ⚠️ ``GET /api/push/<token>?status=up`` records a heartbeat of a push monitor (the URL a push monitor shows, and the
    #: wiki of Uptime Kuma). Not for a card (B1 of a review of 1.0.2).
    raw_read_commands = ReadCommands(after={"push": allowed()})
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://uptime-kuma:3001"),
        Field("api_key", "API key", type="password", secret=True, required=True, help="Settings > API Keys"),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(kind="monitors", label="Monitors", description="All monitors, down ones first.", renderer="list", default_size=(3, 3), refresh_seconds=30, metrics=("down",),
                   options=(Field("limit", "Entries", type="number", default=12), Field("filter", "Name filter"), status_page_field())),
        WidgetType(kind="summary", label="Up and down", description="How many monitors are up and down, and which ones are down.", renderer="value", default_size=(2, 1), min_size=(1, 1), refresh_seconds=30, ring=True, metrics=("down",),
                   options=(Field("filter", "Name filter"), status_page_field())),
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

    async def _page(self, config: dict[str, Any], ctx: Context, slug: str, *, names: bool) -> tuple[set[str], set[str]]:
        """The numbers of the monitors on one status page, and their names when ``names`` asks.

        The names, because the metrics of Uptime Kuma 1 carry no number: there
        the name is all a monitor and its line in ``/metrics`` share.

        ⚠️ The heartbeats first. Uptime Kuma 1.23 never answers
        ``/api/status-page/<slug>`` for a slug it does not know (measured
        24.10.2026: no answer in 15 s), while the heartbeats answer at once,
        empty. Both answer without a key.
        """
        if not SLUG.match(slug):
            raise AdapterError(f"{slug} is not the slug of a status page.", code="bad_status_page",
                               hint="Lower case letters, digits and dashes, as in the address /status/home.")
        verify = not config.get("insecure")
        beats = await ctx.request("GET", f"{base_url(config)}/api/status-page/heartbeat/{slug}", verify=verify, cache_seconds=60)
        if beats.status_code >= 400:
            raise AdapterError(f"Uptime Kuma answered with HTTP {beats.status_code}.", code="http_error")
        try:
            numbers = {str(number) for number in (beats.json().get("heartbeatList") or {})}
        except (ValueError, AttributeError):
            raise AdapterError("Uptime Kuma answered with something that is not a status page.", code="bad_answer") from None
        if not numbers:
            raise AdapterError(f"Uptime Kuma has no status page {slug}, or none of its monitors is on it.", code="no_status_page",
                               hint="Check the slug: the last part of the status page's address.")
        if not names:
            return numbers, set()
        response = await ctx.request("GET", f"{base_url(config)}/api/status-page/{slug}", verify=verify, cache_seconds=60)
        if response.status_code >= 400:
            raise AdapterError(f"Uptime Kuma answered with HTTP {response.status_code}.", code="http_error")
        try:
            groups = response.json().get("publicGroupList") or []
        except (ValueError, AttributeError):
            raise AdapterError("Uptime Kuma answered with something that is not a status page.", code="bad_answer") from None
        named = {str(monitor["name"]) for group in groups for monitor in (group or {}).get("monitorList") or []
                 if monitor.get("name") and str(monitor.get("id")) in numbers}
        return numbers, named

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        rows = await self._metrics(config, ctx)
        monitors: dict[str, dict[str, Any]] = {}
        for name, labels, value in rows:
            # ⚠️ Monitor lines only. Node's own lines carry labels too
            # (nodejs_version_info{version=...}), and every one of them used
            # to become a monitor called "?" that counted as up.
            key = labels.get("monitor_id") or labels.get("monitor_name") or labels.get("monitor_url")
            if not name.startswith("monitor_") or not key:
                continue
            entry = monitors.setdefault(key, {"id": labels.get("monitor_id"), "name": labels.get("monitor_name") or labels.get("monitor_url") or "?",
                                              "type": labels.get("monitor_type", ""), "url": labels.get("monitor_url", ""), "status": None, "latency": None})
            if name == "monitor_status":
                entry["status"] = int(value)
            elif name == "monitor_response_time" and value >= 0:
                # ⚠️ -1 means none: a group, a push monitor, one that is down.
                # Rows read "-1 ms" on a real instance until 24.10.2026.
                entry["latency"] = int(value)
        slug = str(options.get("status_page") or "").strip().strip("/").lower()
        link = None
        if slug:
            numbered = any(m["id"] for m in monitors.values())
            numbers, names = await self._page(config, ctx, slug, names=not numbered)
            # By number where the metrics name it (Uptime Kuma 2), else by name.
            monitors = {key: m for key, m in monitors.items() if (m["id"] in numbers if m["id"] else m["name"] in names)}
            link = f"{base_url(config)}/status/{slug}"
        needle = str(options.get("filter") or "").lower()
        # ⚠️ The counts and the colour follow the monitors the card is about.
        # They used to count every monitor, so a name filter for one service
        # still went red over another one nobody had asked about.
        chosen = [m for m in monitors.values() if not needle or needle in m["name"].lower()]
        down = [m for m in chosen if m["status"] == 0]
        pending = [m for m in chosen if m["status"] == 2]
        status = "bad" if down else "warn" if pending else "ok"
        up = len(chosen) - len(down)
        if widget_kind == "summary":
            return WidgetData(status=status, primary={"label": "Monitors up", "value": up, "unit": f"/ {len(chosen)}"},
                              secondary=[{"label": "Down", "value": len(down)}],
                              meta={"ring": ring_of(("Up", up), ("Down", len(down))),
                                    "status_reason": f"Down: {', '.join(sorted(m['name'] for m in down))}" if down else ""},
                              metrics={"down": float(len(down))}, link=link)
        ordered = sorted(chosen, key=lambda m: (m["status"] != 0, m["status"] != 2, m["name"].lower()))
        items = []
        for monitor in ordered:
            state = {1: "ok", 0: "bad", 2: "warn", 3: "unknown"}.get(monitor["status"], "unknown")
            items.append({"title": monitor["name"], "subtitle": monitor["type"] or monitor["url"], "status": state,
                          "value": f"{monitor['latency']} ms" if monitor["latency"] is not None and state != "bad" else ("down" if state == "bad" else "")})
        return WidgetData(status=status, items=items[: int(options.get("limit") or 12)],
                          secondary=[{"label": "Up", "value": up}, {"label": "Down", "value": len(down)}], metrics={"down": float(len(down))}, link=link)

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        names = ["Reverse proxy", "Nexview", "Jellyfin", "SABnzbd", "Home Assistant", "NAS", "Pi-hole", "Proxmox"]
        down = {"SABnzbd"} if fake.flicker("uk-sab", tick, 0.7) else set()
        if widget_kind == "summary":
            return WidgetData(status="bad" if down else "ok", primary={"label": "Monitors up", "value": len(names) - len(down), "unit": f"/ {len(names)}"}, secondary=[{"label": "Down", "value": len(down)}],
                              meta={"ring": ring_of(("Up", len(names) - len(down)), ("Down", len(down))), "status_reason": "Down: SABnzbd" if down else ""},
                              metrics={"down": float(len(down))})
        items = [{"title": n, "subtitle": "http", "status": "bad" if n in down else "ok", "value": "down" if n in down else f"{int(fake.walk(n, tick, 4, 90))} ms"} for n in names]
        items.sort(key=lambda i: i["status"] != "bad")
        return WidgetData(status="bad" if down else "ok", items=items, secondary=[{"label": "Up", "value": len(names) - len(down)}, {"label": "Down", "value": len(down)}], metrics={"down": float(len(down))})


ADAPTER = UptimeKumaAdapter()
