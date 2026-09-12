"""Gatus: every endpoint with its last check, why it failed and how long it took, and how many are down.

Measured against Gatus 5.36.0 on 12.09.2026, with four endpoints that pointed
only at the test stack: a page nginx serves, a page it does not have, a host
name that exists nowhere, and one endpoint without a group. For a while the
nginx container was stopped and started again.

⚠️ With ``security.basic`` set, the statuses addresses want basic
authentication: no header, a wrong password and a made-up bearer token all got
401 "Unauthorized". The raw uptimes, the raw response times and
``/api/v1/config`` answered without any credentials all the same.

⚠️ ``duration`` is in nanoseconds: 576662 for a page served in half a
millisecond, 7998742098 for the host name that did not resolve. ``status`` is
left out when no HTTP answer came, and ``errors`` when there was none. A failed
condition carries the value it saw, ``[STATUS] (404) == 200``, and a check can
fail with status 200 when another condition did not hold.

⚠️ Results come oldest first, 50 by default and never more than the storage
keeps, 100 unless configured. The list of all endpoints carries no events;
only the address of a single endpoint does.

⚠️ An endpoint is in the list only once it has been checked: after a restart
the host name that did not resolve was missing for more than ten seconds. One
without a group has a key that starts with an underscore (``_no-group``) and no
``group`` field at all.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
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
    ago,
    base_url,
)

#: How many recent checks of each endpoint the cards look at.
RECENT = 20
ORDER = {"bad": 0, "warn": 1, "ok": 2}


def _milliseconds(nanoseconds: Any) -> str:
    """A duration Gatus gives in nanoseconds, as a response time for the eye."""
    try:
        milliseconds = float(nanoseconds) / 1_000_000
    except (TypeError, ValueError):
        return ""
    if milliseconds >= 1000:
        return f"{milliseconds / 1000:.1f} s"
    if milliseconds >= 10:
        return f"{milliseconds:.0f} ms"
    return f"{milliseconds:.1f} ms"


def _reason(result: dict[str, Any]) -> str:
    """Why a check failed: the first error, otherwise the first condition that did not hold."""
    errors = [str(one) for one in result.get("errors") or [] if one]
    if errors:
        return " ".join(errors[0].split())[:140]
    failed = [str(one.get("condition") or "") for one in result.get("conditionResults") or []
              if isinstance(one, dict) and not one.get("success")]
    return failed[0][:140] if failed else ""


def _results(endpoint: dict[str, Any]) -> list[dict[str, Any]]:
    return [one for one in endpoint.get("results") or [] if isinstance(one, dict)]


class GatusAdapter(Adapter):
    kind = "gatus"
    label = "Gatus"
    category = "monitoring"
    description = "Every endpoint with its last check, why it failed and how long it took, and how many are down."
    icon = "gatus"
    #: Confirmed against a live instance on 2026-09-12.
    beta = False
    docs_url = "https://github.com/TwiN/gatus"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://gatus:8080"),
        Field("username", "User", help="The user of security.basic in Gatus's configuration. Leave it empty when Gatus has no security section."),
        Field("password", "Password", type="password", secret=True),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(kind="endpoints", label="Endpoints",
                   description="Every endpoint with its last response time and why it failed, down ones first, then those that failed within the last 20 checks.",
                   renderer="list", default_size=(3, 3), refresh_seconds=60, metrics=("down",),
                   options=(Field("limit", "Entries", type="number", default=10),)),
        WidgetType(kind="summary", label="Endpoint health", description="How many endpoints are up, how many are down, and when Gatus last checked.",
                   renderer="value", default_size=(3, 2), refresh_seconds=60, metrics=("up", "down")),
    )

    async def _statuses(self, config: dict[str, Any], ctx: Context, results: int = RECENT, cache: float = 10) -> list[dict[str, Any]]:
        user = str(config.get("username") or "").strip()
        response = await ctx.request(
            "GET", f"{base_url(config)}/api/v1/endpoints/statuses", params={"pageSize": results},
            auth=(user, str(config.get("password") or "")) if user else None,
            verify=not config.get("insecure"), cache_seconds=cache, auth_errors=False,
        )
        if response.status_code in (401, 403):
            raise AuthFailed("Gatus rejected the user or the password.")
        if response.status_code >= 400:
            raise AdapterError(f"Gatus answered with HTTP {response.status_code}.", code="http_error",
                               hint="Check the URL; it is the address of Gatus itself, port 8080 by default.")
        try:
            answer = response.json()
        except ValueError as error:
            raise AdapterError("Gatus did not answer with JSON.", code="not_json",
                               hint="The URL probably points at a login page or a reverse proxy.") from error
        if not isinstance(answer, list) or not all(isinstance(one, dict) and "key" in one for one in answer):
            raise AdapterError("This address answers, but not the way Gatus does.", code="not_gatus")
        return answer

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        endpoints = await self._statuses(config, ctx, results=1, cache=0)
        return f"Gatus answers with {len(endpoints)} endpoints."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        endpoints = await self._statuses(config, ctx)
        if widget_kind == "summary":
            return self._summary(endpoints)
        return self._endpoints(endpoints, max(1, int(options.get("limit") or 10)))

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def _endpoints(endpoints: list[dict[str, Any]], limit: int) -> WidgetData:
        rows = []
        for endpoint in endpoints:
            results = _results(endpoint)
            if not results:
                continue
            name = str(endpoint.get("name") or endpoint.get("key") or "?")
            group = str(endpoint.get("group") or "")
            last = results[-1]
            if not last.get("success"):
                colour, words = "bad", ("Down", group, _reason(last))
            elif any(not one.get("success") for one in results):
                colour, words = "warn", ("Unstable", group)
            else:
                colour, words = "ok", (group,)
            row: dict[str, Any] = {"title": name, "subtitle": " · ".join(part for part in words if part), "status": colour}
            took = _milliseconds(last.get("duration"))
            if took:
                row["value"] = took
            rows.append(row)
        rows.sort(key=lambda row: (ORDER.get(row["status"], 9), row["title"].lower()))
        down = sum(1 for row in rows if row["status"] == "bad")
        shaky = any(row["status"] == "warn" for row in rows)
        return WidgetData(
            status="bad" if down else "warn" if shaky else "ok" if rows else "unknown",
            items=rows[:limit],
            secondary=[{"label": "Down", "value": down}],
            meta={"empty": "Gatus watches no endpoints yet."},
            metrics={"down": float(down)},
        )

    @staticmethod
    def _summary(endpoints: list[dict[str, Any]], now: float | None = None) -> WidgetData:
        lasts = [results[-1] for results in (_results(one) for one in endpoints) if results]
        down = sum(1 for last in lasts if not last.get("success"))
        up = len(lasts) - down
        newest = max((str(last.get("timestamp") or "") for last in lasts), default="")
        secondary: list[dict[str, Any]] = []
        if down:
            secondary.append({"label": "Down", "value": down})
        checked = ago(newest, now=now) if newest else ""
        if checked:
            secondary.append({"label": "Last check", "value": checked})
        return WidgetData(
            status="bad" if down else "ok" if lasts else "unknown",
            primary={"label": "Endpoints up", "value": up, "unit": f"/ {len(lasts)}"},
            secondary=secondary,
            metrics={"up": float(up), "down": float(down)},
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        now = datetime.now(UTC)
        flapping = fake.flicker("gatus-router", tick, 0.5)

        def endpoint(name: str, group: str, milliseconds: float, outcomes: list[bool], reason: str = "") -> dict[str, Any]:
            results = []
            for index, success in enumerate(outcomes):
                result: dict[str, Any] = {"duration": int(milliseconds * 1_000_000), "success": success,
                                          "timestamp": (now - timedelta(minutes=len(outcomes) - index)).strftime("%Y-%m-%dT%H:%M:%SZ")}
                if success:
                    result["status"] = 200
                elif reason:
                    result["conditionResults"] = [{"condition": reason, "success": False}]
                results.append(result)
            return {"name": name, "group": group, "key": f"{group}_{name}", "results": results}

        endpoints = [
            endpoint("Home Assistant", "home", 42, [True] * 20),
            endpoint("Nextcloud", "cloud", 310, [True] * 17 + [False] * 3, "[STATUS] (502) == 200"),
            endpoint("Router", "network", 3, [True] * 12 + [not flapping] + [True] * 7),
            endpoint("Mail", "cloud", 120, [True] * 20),
        ]
        if widget_kind == "summary":
            return self._summary(endpoints)
        return self._endpoints(endpoints, max(1, int(options.get("limit") or 10)))


ADAPTER = GatusAdapter()
