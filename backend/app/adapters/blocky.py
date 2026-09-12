"""Blocky: whether blocking is on, how many queries it answered and what share it blocked, with a pause button.

Measured against Blocky 0.35.0 on 11.09.2026, with two inline deny lists,
statistics switched on, and eleven queries: ten over DNS and one through the
API.

⚠️ The API asks for no credentials. A made-up bearer token gets 200 like none
at all, so whoever reaches the HTTP port may pause blocking.

⚠️ The numbers come from ``/api/stats``, a rolling 24-hour window kept in
memory. It exists only with ``statistics.enable: true`` in the configuration
and answers 503 otherwise; a restart starts it from nothing. A query sent
through ``/api/query`` counts in it like one over DNS.

⚠️ ``summary.blocked`` is deny list and rebinding hits only; ``filtered``
(query types, NOTFQDN) is not a block, so the share leaves it out.

⚠️ Pausing is ``GET /api/blocking/disable?duration=5m`` (POST gets 405) and
answers 200 with an empty body, enabling likewise; the status afterwards reads
``{"enabled": false, "autoEnableInSec": 299, "disabledGroups": [...]}``.
A duration Go cannot read gets 400 ``time: invalid duration``. Because the
body says nothing, the card asks for the status again after pressing.

⚠️ The OpenAPI description is served at ``/docs/openapi.yaml``.
"""

from __future__ import annotations

from typing import Any

from .base import (
    Action,
    Adapter,
    AdapterError,
    Context,
    Field,
    WidgetData,
    WidgetType,
    base_url,
    duration_short,
    percent,
    ring_of,
)

PAUSE = "5m"


class BlockyAdapter(Adapter):
    kind = "blocky"
    label = "Blocky"
    category = "network"
    description = "Whether blocking is on, how many queries Blocky answered and what share it blocked, with a pause button."
    icon = "blocky"
    #: Confirmed against a live instance on 2026-09-11.
    beta = False
    docs_url = "https://0xerr0r.github.io/blocky/latest/interfaces/"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://blocky:4000",
              help="The HTTP port from ports.http in Blocky's configuration. The numbers need statistics.enable: true there."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(kind="blocking", label="Blocking", description="The share of queries blocked in the last 24 hours, the queries, and a button to pause blocking for five minutes.",
                   renderer="value", default_size=(3, 2), refresh_seconds=60, ring=True, metrics=("blocked_percent", "queries")),
        WidgetType(kind="top", label="Top blocked", description="The domains blocked most often in the last 24 hours.",
                   renderer="list", default_size=(3, 3), refresh_seconds=300,
                   options=(Field("limit", "Entries", type="number", default=10),)),
    )

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, params: dict[str, Any] | None = None, cache: float = 10) -> Any:
        response = await ctx.request("GET", f"{base_url(config)}/api{path}", params=params,
                                     verify=not config.get("insecure"), cache_seconds=cache, auth_errors=False)
        if response.status_code == 503 and path == "/stats":
            raise AdapterError("Blocky keeps no statistics.", code="no_statistics",
                               hint="Set statistics.enable: true in Blocky's configuration; it needs Blocky 0.35 or newer.")
        if response.status_code >= 400:
            raise AdapterError(f"Blocky answered with HTTP {response.status_code}.", code="http_error",
                               hint="Check the URL; it is the HTTP port of Blocky, 4000 in most examples.")
        try:
            return response.json()
        except ValueError as error:
            raise AdapterError("Blocky did not answer with JSON.", code="not_json",
                               hint="The URL probably points at something else than Blocky's HTTP port.") from error

    async def _status(self, config: dict[str, Any], ctx: Context, cache: float = 5) -> dict[str, Any]:
        status = await self._get(config, ctx, "/blocking/status", cache=cache)
        if not isinstance(status, dict) or not isinstance(status.get("enabled"), bool):
            raise AdapterError("This address answers, but not the way Blocky does.", code="not_blocky")
        return status

    async def _stats(self, config: dict[str, Any], ctx: Context) -> dict[str, Any]:
        stats = await self._get(config, ctx, "/stats")
        if not isinstance(stats, dict) or not isinstance(stats.get("summary"), dict):
            raise AdapterError("This address answers, but not the way Blocky does.", code="not_blocky")
        return stats

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        status = await self._status(config, ctx, cache=0)
        stats = await self._stats(config, ctx)
        state = "on" if status["enabled"] else "paused"
        return f"Blocky answers; blocking is {state}, {int(stats['summary'].get('queries') or 0)} queries in the last 24 hours."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        stats = await self._stats(config, ctx)
        if widget_kind == "top":
            return self._top(stats, options)
        return self._blocking(await self._status(config, ctx), stats)

    async def action(self, widget_kind: str, action_id: str, params: dict[str, Any],
                     config: dict[str, Any], options: dict[str, Any], ctx: Context) -> str:
        if action_id not in ("pause", "enable"):
            raise AdapterError("Unknown blocking action.", code="no_such_action")
        path = "/api/blocking/enable" if action_id == "enable" else "/api/blocking/disable"
        response = await ctx.request("GET", f"{base_url(config)}{path}", params=None if action_id == "enable" else {"duration": PAUSE},
                                     verify=not config.get("insecure"), auth_errors=False)
        if response.status_code >= 400:
            detail = response.text.strip()[:200]
            raise AdapterError(f"Blocky refused: {detail or f'HTTP {response.status_code}'}", code="action_failed")
        # ⚠️ An empty 200 either way; only the status says whether it happened.
        ctx.forget_answers()
        status = await self._status(config, ctx, cache=0)
        if status["enabled"] != (action_id == "enable"):
            raise AdapterError("Blocky answered, but blocking did not change.", code="action_failed")
        return "Blocking enabled." if action_id == "enable" else "Blocking paused for five minutes."

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def _blocking(status: dict[str, Any], stats: dict[str, Any]) -> WidgetData:
        summary = stats.get("summary") or {}
        queries = int(summary.get("queries") or 0)
        blocked = int(summary.get("blocked") or 0)
        share = percent(blocked, queries)
        enabled = bool(status.get("enabled"))
        secondary: list[dict[str, Any]] = [{"label": "Queries", "value": queries}]
        if enabled:
            secondary.append({"label": "Blocked", "value": blocked})
        elif status.get("autoEnableInSec"):
            secondary.append({"label": "Back on in", "value": duration_short(float(status["autoEnableInSec"]))})
        return WidgetData(
            status="ok" if enabled else "warn",
            primary={"label": "Blocked" if enabled else "Blocking paused", "value": share, "unit": "%" if share is not None else ""},
            secondary=secondary,
            actions=[Action(id="pause", label="Pause 5 min", icon="pause")] if enabled else [Action(id="enable", label="Enable", icon="play")],
            meta={"ring": ring_of(("Blocked", blocked), ("Allowed", queries - blocked))} if queries else {},
            metrics={"queries": float(queries), **({"blocked_percent": share} if share is not None else {})},
        )

    @staticmethod
    def _top(stats: dict[str, Any], options: dict[str, Any]) -> WidgetData:
        domains = [one for one in stats.get("topBlockedDomains") or [] if isinstance(one, dict) and one.get("name")]
        domains.sort(key=lambda one: (-int(one.get("count") or 0), str(one.get("name"))))
        items = [{"title": str(one["name"]), "status": "bad", "value": int(one.get("count") or 0)}
                 for one in domains[: int(options.get("limit") or 10)]]
        blocked = int((stats.get("summary") or {}).get("blocked") or 0)
        return WidgetData(status="ok", items=items, secondary=[{"label": "Blocked", "value": blocked}],
                          meta={"empty": "Nothing was blocked in the last 24 hours."})

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        from . import demo as fake

        queries = fake.counter("blocky-queries", tick, 21000, 0.7)
        blocked = int(queries * fake.walk("blocky-share", tick, 11, 19) / 100)
        stats = {"summary": {"queries": queries, "blocked": blocked},
                 "topBlockedDomains": [{"name": name, "count": count - tick % 7}
                                       for name, count in (("ads.example.net", 880), ("metrics.example.com", 512), ("tracker.example.org", 347), ("pixel.example.io", 120))]}
        if widget_kind == "top":
            return self._top(stats, options)
        paused = fake.flicker("blocky-paused", tick, 0.1)
        return self._blocking({"enabled": not paused, **({"autoEnableInSec": 240} if paused else {})}, stats)


ADAPTER = BlockyAdapter()
