"""Tracearr: who streams from Plex, Jellyfin and Emby, and whose account is shared.

Measured on 01.10.2026 against ghcr.io/connorgallopo/tracearr 2.5.1 (the
supervised image with its own TimescaleDB and Redis), set up through the
API with a claim code, with a right, a wrong and no public key. No media
server was connected, so every count was 0 and every list empty: the shape
of a violation follows Tracearr's own OpenAPI description
(``apps/server/src/routes/public.openapi.ts``) and is read leniently.

The public key (``trr_pub_…``) comes from Settings > API and is sent as
``Authorization: Bearer``. A wrong key answers 401 "Invalid API key", none
at all 401 "Missing or invalid Authorization header".

⚠️ ``totalBitrate`` in the stream summary came back as a broken character
with no stream running; it is not read.
"""

from __future__ import annotations

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

#: Tracearr's severities, as a card shows them.
SEVERITY = {"high": "bad", "warning": "warn", "low": "unknown"}


class TracearrAdapter(Adapter):
    kind = "tracearr"
    label = "Tracearr"
    category = "media"
    description = "Streams across Plex, Jellyfin and Emby, and the accounts that look shared."
    icon = "tracearr"
    beta = True
    docs_url = "https://github.com/connorgallopo/Tracearr"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://tracearr:3000"),
        Field("api_key", "API key", type="password", secret=True, required=True,
              help="Settings > API in Tracearr; it starts with trr_pub_."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(
            kind="overview",
            label="Tracearr overview",
            description="Streams now, plays and hours watched today, and the alerts of the last day.",
            renderer="value",
            default_size=(3, 2),
            refresh_seconds=30,
            metrics=("streams",),
        ),
        WidgetType(
            kind="violations",
            label="Violations",
            description="What Tracearr flagged and nobody has looked at yet: shared accounts, too many streams, far-apart places.",
            renderer="list",
            default_size=(4, 3),
            refresh_seconds=120,
            options=(Field("limit", "Entries", type="number", default=8),),
        ),
    )

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, params: dict[str, Any] | None = None) -> Any:
        response = await ctx.request(
            "GET", f"{base_url(config)}/api/v1/public{path}", params=params, cache_seconds=10,
            headers={"Authorization": f"Bearer {config.get('api_key') or ''}", "Accept": "application/json"},
            verify=not config.get("insecure"),
        )
        if response.status_code >= 400:
            raise AdapterError(f"Tracearr answered with HTTP {response.status_code}.", code="http_error")
        try:
            return response.json()
        except ValueError:
            raise AdapterError("Tracearr did not answer with JSON; is this the address of Tracearr?", code="bad_answer") from None

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        health = await self._get(config, ctx, "/health")
        servers = health.get("servers") if isinstance(health, dict) else None
        return f"Tracearr {health.get('version', '?') if isinstance(health, dict) else '?'} answers and watches {len(servers or [])} media server(s)."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "violations":
            answer = await self._get(config, ctx, "/violations", {"acknowledged": "false", "pageSize": max(1, min(100, int(options.get("limit") or 8)))})
            return violations_of(answer, int(options.get("limit") or 8))
        stats = await self._get(config, ctx, "/stats")
        today = await self._get(config, ctx, "/stats/today")
        return overview_of(stats if isinstance(stats, dict) else {}, today if isinstance(today, dict) else {})

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        if widget_kind == "violations":
            flagged = fake.flicker("tracearr-flag", tick, 0.6)
            rows = [
                {"id": "1", "severity": "high", "acknowledged": False, "createdAt": "2026-10-01T19:12:00Z",
                 "rule": {"name": "Too many streams at once"}, "user": {"username": "family"}},
                {"id": "2", "severity": "warning", "acknowledged": False, "createdAt": "2026-10-01T08:40:00Z",
                 "rule": {"name": "Two places far apart"}, "user": {"username": "Robin"}},
            ]
            return violations_of({"data": rows if flagged else rows[1:], "meta": {"total": 2 if flagged else 1}}, int(options.get("limit") or 8))
        streams = int(fake.walk("tracearr-streams", tick, 0, 5))
        return overview_of(
            {"activeStreams": streams, "totalUsers": 9, "recentViolations": 1},
            {"todayPlays": 14, "watchTimeHours": 6.5, "alertsLast24h": 1 if fake.flicker("tracearr-alert", tick, 0.4) else 0, "activeUsersToday": 4},
        )


def overview_of(stats: dict[str, Any], today: dict[str, Any]) -> WidgetData:
    streams = int(stats.get("activeStreams") or 0)
    alerts = int(today.get("alertsLast24h") or 0)
    return WidgetData(
        status="warn" if alerts else "ok",
        primary={"label": "Streams", "value": streams},
        secondary=[
            {"label": "Plays today", "value": int(today.get("todayPlays") or 0)},
            {"label": "Hours today", "value": round(float(today.get("watchTimeHours") or 0), 1)},
            {"label": "Alerts", "value": alerts},
            {"label": "Users", "value": int(stats.get("totalUsers") or 0)},
        ],
        metrics={"streams": float(streams)},
        meta={"status_reason": f"{alerts} alert(s) in the last day" if alerts else ""},
    )


def violations_of(answer: Any, limit: int) -> WidgetData:
    """Each unacknowledged violation: the rule as the row, who it was in the line under it."""
    rows = answer.get("data") if isinstance(answer, dict) else None
    items: list[dict[str, Any]] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict) or row.get("acknowledged"):
            continue
        rule = row.get("rule") if isinstance(row.get("rule"), dict) else {}
        user = row.get("user") if isinstance(row.get("user"), dict) else {}
        who = str(user.get("username") or user.get("name") or user.get("friendlyName") or "")
        items.append({
            "id": row.get("id"),
            "title": str(rule.get("name") or "Violation"),
            "subtitle": who,
            # The person apart from the line: showcase mode makes them up.
            "user": who,
            "status": SEVERITY.get(str(row.get("severity") or "").lower(), "unknown"),
        })
    total = int((answer.get("meta") or {}).get("total") or len(items)) if isinstance(answer, dict) else len(items)
    worst = "bad" if any(item["status"] == "bad" for item in items) else "warn" if items else "ok"
    return WidgetData(
        status=worst,
        items=items[:limit],
        secondary=[{"label": "Open", "value": total}],
        meta={"empty": "Nothing flagged."},
    )


ADAPTER = TracearrAdapter()
