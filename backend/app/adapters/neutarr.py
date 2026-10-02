"""NeutArr: the hunter that searches the Arr apps for what is missing and what could be better.

NeutArr is the maintained continuation of Huntarr, whose repositories were
taken down in February 2026. Measured on 02.10.2026 against
iampuid0/neutarr 1.11.1, set up through the API with a setup token, with
one Sonarr behind it, with a right, a wrong and no key.

The key comes from NeutArr's settings (``GET /api/auth/apikey`` once signed
in) and is sent as ``X-Api-Key``; NeutArr refuses keys in the query. A wrong
key and none at all both answer 401 "Authentication required".

What the cards read, all measured:

* ``/api/configured-apps``: ``{"sonarr": true, "radarr": false, ...,
  "general": false}``.
* ``/api/stats``: ``{"stats": {"sonarr": {"hunted": 0, "upgraded": 0},
  ...}, "success": true}``, counted since the last reset.
* ``/api/cycles``: ``{"cycles": {"sonarr": {"state": "waiting",
  "remaining_seconds": 45, "interval_seconds": 60, ...}}}``; an app that has
  not started has no entry, a broken one ``state: "error"`` with a
  ``reason``.
* ``/api/status/<app>``: ``{"connected_count": 1, "total_configured": 1}``,
  NeutArr checking each instance live, up to five seconds each.
* ``/api/hourly-caps``: ``{"caps": {"sonarr": {"api_hits": 0}}, "limits":
  {"sonarr": 20}}``.
* ``/api/version``: the version as plain text.
"""

from __future__ import annotations

import asyncio
from typing import Any

from . import demo as fake
from .base import (
    Adapter,
    AdapterError,
    Context,
    Field,
    WidgetData,
    WidgetType,
    base_url,
)

#: The apps NeutArr hunts in, as it names them, and as a card shows them.
APPS = {
    "sonarr": "Sonarr",
    "radarr": "Radarr",
    "lidarr": "Lidarr",
    "readarr": "Readarr",
    "whisparr": "Whisparr",
    "eros": "Eros",
}


class NeutarrAdapter(Adapter):
    kind = "neutarr"
    label = "NeutArr"
    category = "media"
    description = "What the hunter found missing and upgraded in Sonarr, Radarr and the other Arr apps, and when it looks next."
    icon = "neutarr"
    beta = True
    docs_url = "https://github.com/iampuid0/neutarr"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://neutarr:9705"),
        Field("api_key", "API key", type="password", secret=True, required=True,
              help="NeutArr shows it on the User page, under API key."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(
            kind="overview",
            label="NeutArr overview",
            description="Items hunted and upgraded across every app, and how many apps are connected.",
            renderer="value",
            default_size=(3, 2),
            refresh_seconds=120,
            metrics=("hunted",),
        ),
        WidgetType(
            kind="apps",
            label="Hunted apps",
            description="Each app NeutArr hunts in: connected or not, what it found, its calls this hour and when it looks next.",
            renderer="list",
            default_size=(4, 3),
            refresh_seconds=60,
            bars=True,
        ),
    )

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, *, text: bool = False, cache: int = 15) -> Any:
        response = await ctx.request(
            "GET", f"{base_url(config)}{path}", cache_seconds=cache,
            headers={"X-Api-Key": str(config.get("api_key") or ""), "Accept": "application/json"},
            verify=not config.get("insecure"),
        )
        if response.status_code >= 400:
            raise AdapterError(f"NeutArr answered with HTTP {response.status_code}.", code="http_error")
        if text:
            return response.text.strip()
        try:
            return response.json()
        except ValueError:
            raise AdapterError("NeutArr did not answer with JSON; is this the address of NeutArr?", code="bad_answer") from None

    async def _apps(self, config: dict[str, Any], ctx: Context, *, live: bool) -> list[dict[str, Any]]:
        configured = await self._get(config, ctx, "/api/configured-apps")
        stats = await self._get(config, ctx, "/api/stats")
        names = [name for name in APPS if isinstance(configured, dict) and configured.get(name)]
        cycles: dict[str, Any] = {}
        caps: dict[str, Any] = {}
        status: dict[str, Any] = {}
        if live and names:
            cycles_answer, caps_answer, *states = await asyncio.gather(
                self._get(config, ctx, "/api/cycles", cache=10),
                self._get(config, ctx, "/api/hourly-caps"),
                # NeutArr checks every instance itself, up to five seconds each.
                *(self._get(config, ctx, f"/api/status/{name}", cache=60) for name in names),
            )
            cycles = (cycles_answer or {}).get("cycles") or {} if isinstance(cycles_answer, dict) else {}
            caps = caps_answer if isinstance(caps_answer, dict) else {}
            status = {name: state for name, state in zip(names, states, strict=True)}
        counts = (stats or {}).get("stats") or {} if isinstance(stats, dict) else {}
        return [
            {
                "name": name,
                "counts": counts.get(name) if isinstance(counts.get(name), dict) else {},
                "cycle": cycles.get(name) if isinstance(cycles.get(name), dict) else None,
                "status": status.get(name) if isinstance(status.get(name), dict) else None,
                "hits": ((caps.get("caps") or {}).get(name) or {}).get("api_hits"),
                "limit": (caps.get("limits") or {}).get(name),
            }
            for name in names
        ]

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        version = await self._get(config, ctx, "/api/version", text=True, cache=0)
        apps = await self._apps(config, ctx, live=False)
        return f"NeutArr {version or '?'} answers and hunts in {len(apps)} app(s)."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        apps = await self._apps(config, ctx, live=True)
        return apps_of(apps) if widget_kind == "apps" else overview_of(apps)

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        lidarr_down = fake.flicker("neutarr-lidarr", tick, 0.2)
        hunted = int(fake.walk("neutarr-hunted", tick, 30, 60))
        apps = [
            {"name": "sonarr", "counts": {"hunted": hunted, "upgraded": 12}, "cycle": {"state": "waiting", "remaining_seconds": 420},
             "status": {"connected_count": 2, "total_configured": 2}, "hits": 7, "limit": 20},
            {"name": "radarr", "counts": {"hunted": 18, "upgraded": 5}, "cycle": {"state": "running"},
             "status": {"connected_count": 1, "total_configured": 1}, "hits": 12, "limit": 20},
            {"name": "lidarr", "counts": {"hunted": 4, "upgraded": 0},
             "cycle": {"state": "error", "reason": "Connection refused"} if lidarr_down else {"state": "waiting", "remaining_seconds": 1500},
             "status": {"connected_count": 0 if lidarr_down else 1, "total_configured": 1}, "hits": 2, "limit": 20},
        ]
        return apps_of(apps) if widget_kind == "apps" else overview_of(apps)


def _down(app: dict[str, Any]) -> bool:
    """An app none of whose instances answer, or whose cycle broke."""
    status = app.get("status") or {}
    cycle = app.get("cycle") or {}
    total = int(status.get("total_configured") or 0)
    return (total > 0 and int(status.get("connected_count") or 0) == 0) or cycle.get("state") == "error"


def overview_of(apps: list[dict[str, Any]]) -> WidgetData:
    hunted = sum(int((app.get("counts") or {}).get("hunted") or 0) for app in apps)
    upgraded = sum(int((app.get("counts") or {}).get("upgraded") or 0) for app in apps)
    down = [APPS.get(app["name"], app["name"]) for app in apps if _down(app)]
    return WidgetData(
        status="warn" if down else "ok" if apps else "unknown",
        primary={"label": "Hunted", "value": hunted},
        secondary=[
            {"label": "Upgraded", "value": upgraded},
            {"label": "Apps", "value": f"{len(apps) - len(down)} / {len(apps)}"},
        ],
        metrics={"hunted": float(hunted)},
        meta={"status_reason": f"Not reached: {', '.join(down)}" if down else "" if apps else "No app is set up in NeutArr yet."},
    )


def _next(cycle: dict[str, Any] | None) -> str:
    """When the app is hunted next, or why not."""
    if not cycle:
        return "not started"
    state = str(cycle.get("state") or "")
    if state == "error":
        return str(cycle.get("reason") or "error")
    if state == "running":
        return "hunting now"
    remaining = cycle.get("remaining_seconds")
    if isinstance(remaining, (int, float)):
        return f"next in {max(1, round(remaining / 60))} min"
    return state or "?"


def apps_of(apps: list[dict[str, Any]]) -> WidgetData:
    """One row per app: what it hunted on the right, so the rows can be bars; the rest in the line under it."""
    items: list[dict[str, Any]] = []
    for app in apps:
        counts = app.get("counts") or {}
        status = app.get("status") or {}
        total = int(status.get("total_configured") or 0)
        parts = [_next(app.get("cycle")), f"{int(counts.get('upgraded') or 0)} upgraded"]
        if total:
            parts.append(f"{int(status.get('connected_count') or 0)} / {total} connected")
        if app.get("limit"):
            parts.append(f"{int(app.get('hits') or 0)} / {int(app['limit'])} calls this hour")
        items.append({
            "id": app["name"],
            "title": APPS.get(app["name"], app["name"]),
            "subtitle": " · ".join(parts),
            "value": int(counts.get("hunted") or 0),
            "status": "bad" if _down(app) else "ok",
        })
    return WidgetData(
        status="bad" if any(item["status"] == "bad" for item in items) else "ok" if items else "unknown",
        items=items,
        meta={"empty": "No app is set up in NeutArr yet."},
    )


ADAPTER = NeutarrAdapter()
