"""UptimeRobot: which monitors are up and which are down, with their uptime of the last 30 days.

Written on 27.10.2026 from the documentation of the API v2
(https://uptimerobot.com/api/), without an account to measure against.
Nothing here is confirmed against UptimeRobot, so the adapter is a beta.

- One address for everyone, ``https://api.uptimerobot.com/v2/getMonitors``,
  asked with a POST and a form body. The key goes in the body (``api_key``),
  never in the address, which is what the documentation shows and a proxy
  would log. A read-only key of the account is enough.
- ``status`` of a monitor: 0 paused, 1 not checked yet, 2 up, 8 seems down,
  9 down. ``type``: 1 HTTP(s), 2 keyword, 3 ping, 4 port, 5 heartbeat.
- ``custom_uptime_ratios=30`` answers ``custom_uptime_ratio`` as a string
  with the percentage of the last 30 days. ``response_times=1`` with
  ``response_times_limit=1`` answers the newest response time in milliseconds.
- A refusal is ``{"stat": "fail", "error": {"type", "message", ...}}`` with
  status 200; a wrong key is ``invalid_parameter`` about ``api_key``. The free
  plan allows ten requests a minute for the whole account, so the cards are
  asked every two minutes and share one answer.
- Pages of 50 monitors; the cards read up to four pages.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from . import demo as fake
from .base import (
    Adapter,
    AdapterError,
    AuthFailed,
    Context,
    Field,
    WidgetData,
    WidgetType,
    ring_of,
)

API = "https://api.uptimerobot.com/v2/getMonitors"
PAGE = 50
PAGES = 4
TYPES = {1: "HTTP", 2: "Keyword", 3: "Ping", 4: "Port", 5: "Heartbeat"}
#: The state of a monitor as a card colours it.
COLOUR = {0: "unknown", 1: "unknown", 2: "ok", 8: "warn", 9: "bad"}


def _number(value: Any) -> float | None:
    try:
        return float(str(value).split("-")[0])
    except (TypeError, ValueError):
        return None


class UptimeRobotAdapter(Adapter):
    kind = "uptimerobot"
    label = "UptimeRobot"
    category = "monitoring"
    description = "Which UptimeRobot monitors are up and which are down, with their uptime of the last 30 days."
    icon = "uptimerobot"
    #: Built from the documentation of API v2 on 2026-10-27, never run against an account.
    beta = True
    docs_url = "https://uptimerobot.com/api/"
    fields = (
        Field("api_key", "API key", type="password", secret=True, required=True,
              help="A read-only API key or the main one, from My Settings > API Settings at uptimerobot.com. UptimeRobot allows ten requests a minute on the free plan."),
    )
    widgets = (
        WidgetType(kind="monitors", label="Monitors", description="Every monitor with its state and its uptime of the last 30 days, down ones first.",
                   renderer="list", default_size=(3, 3), refresh_seconds=120, metrics=("down",),
                   options=(Field("filter", "Name contains", help="Only the monitors whose name has this text."),
                            Field("limit", "Entries", type="number", default=12))),
        WidgetType(kind="summary", label="Monitors up", description="How many monitors are up, and which ones are down.",
                   renderer="value", default_size=(2, 2), refresh_seconds=120, metrics=("down",), ring=True,
                   options=(Field("filter", "Name contains", help="Only the monitors whose name has this text."),)),
    )

    async def _monitors(self, config: dict[str, Any], ctx: Context) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []
        for page in range(PAGES):
            response = await ctx.request(
                "POST", API, data={"api_key": str(config.get("api_key") or ""), "format": "json", "limit": PAGE, "offset": page * PAGE,
                                   "custom_uptime_ratios": "30", "response_times": 1, "response_times_limit": 1},
                headers={"Cache-Control": "no-cache"}, auth_errors=False,
            )
            if response.status_code == 429:
                raise AdapterError("UptimeRobot asks for fewer requests.", code="rate_limited",
                                   hint="The free plan allows ten requests a minute for the whole account, all apps together.")
            if response.status_code >= 400:
                raise AdapterError(f"UptimeRobot answered with HTTP {response.status_code}.", code="http_error")
            try:
                answer = response.json()
            except ValueError as error:
                raise AdapterError("UptimeRobot did not answer with JSON.", code="not_json") from error
            if not isinstance(answer, dict):
                raise AdapterError("UptimeRobot answered with something unexpected.", code="bad_answer")
            if answer.get("stat") != "ok":
                refusal = answer.get("error") if isinstance(answer.get("error"), dict) else {}
                message = " ".join(str(refusal.get("message") or "").split())[:160]
                if refusal.get("parameter_name") == "api_key" or "api_key" in message:
                    raise AuthFailed("UptimeRobot rejected the API key.")
                raise AdapterError(f"UptimeRobot refused: {message}" if message else "UptimeRobot refused the request.", code="refused")
            monitors = [one for one in answer.get("monitors") or [] if isinstance(one, dict)]
            found += monitors
            total = (answer.get("pagination") or {}).get("total")
            if len(monitors) < PAGE or (isinstance(total, int) and len(found) >= total):
                break
        return found

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        return f"UptimeRobot answers with {len(await self._monitors(config, ctx))} monitors."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        return self._card(widget_kind, await self._monitors(config, ctx), options)

    @staticmethod
    def _card(widget_kind: str, monitors: list[dict[str, Any]], options: dict[str, Any]) -> WidgetData:
        needle = str(options.get("filter") or "").lower()
        chosen = [one for one in monitors if not needle or needle in str(one.get("friendly_name") or "").lower()]
        down = [one for one in chosen if one.get("status") in (8, 9)]
        paused = [one for one in chosen if one.get("status") == 0]
        # "Seems down" is UptimeRobot's own doubt, before it has told anybody: yellow, not red.
        sure = [one for one in chosen if one.get("status") == 9]
        status = "bad" if sure else "warn" if down else "ok" if chosen else "unknown"
        up = sum(1 for one in chosen if one.get("status") == 2)
        if widget_kind == "summary":
            return WidgetData(
                status=status,
                primary={"label": "Monitors up", "value": up, "unit": f"/ {len(chosen) - len(paused)}"},
                secondary=[{"label": "Down", "value": len(down)}] + ([{"label": "Paused", "value": len(paused)}] if paused else []),
                meta={"ring": ring_of(("Up", up), ("Down", len(down))),
                      "status_reason": f"Down: {', '.join(sorted(str(one.get('friendly_name') or '?') for one in down))}" if down else ""},
                metrics={"down": float(len(down))},
            )
        rows = []
        for one in sorted(chosen, key=lambda one: ({9: 0, 8: 1, 1: 2, 0: 3, 2: 4}.get(one.get("status"), 5), str(one.get("friendly_name") or "").lower())):
            code = one.get("status")
            ratio = _number(one.get("custom_uptime_ratio"))
            host = urlsplit(str(one.get("url") or "")).hostname or ""
            rows.append({
                "title": str(one.get("friendly_name") or "?"),
                "subtitle": " · ".join(part for part in (TYPES.get(one.get("type"), ""), host, "Paused" if code == 0 else "Not checked yet" if code == 1 else "") if part),
                "status": COLOUR.get(code, "unknown"),
                "value": "down" if code in (8, 9) else f"{ratio:g}%" if ratio is not None and code == 2 else "",
            })
        return WidgetData(status=status, items=rows[: max(1, int(options.get("limit") or 12))],
                          secondary=[{"label": "Up", "value": up}, {"label": "Down", "value": len(down)}],
                          meta={"empty": "No monitors yet."}, metrics={"down": float(len(down))})

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        failing = fake.flicker("uptimerobot-blog", tick, 0.6)
        names = [("Main site", 1, "example.com"), ("Blog", 1, "blog.example.com"), ("Mail server", 4, "mail.example.com"),
                 ("Nightly backup", 5, ""), ("Router", 3, "198.51.100.7")]
        monitors = [{"friendly_name": name, "type": kind, "url": host, "status": 9 if failing and name == "Blog" else 2,
                     "custom_uptime_ratio": f"{fake.walk('ur-' + name, tick, 99.2, 100):.2f}"} for name, kind, host in names]
        monitors.append({"friendly_name": "Staging", "type": 1, "url": "staging.example.com", "status": 0})
        return self._card(widget_kind, monitors, options)


ADAPTER = UptimeRobotAdapter()
