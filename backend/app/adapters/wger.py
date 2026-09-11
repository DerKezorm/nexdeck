"""wger: your weight, how it changed over the last 30 days, and the latest weigh-ins.

Measured against wger 2.7.0 on 11.09.2026, with seven weight entries over two
months and a REST framework token, the kind of key the API key page of the
profile hands out.

⚠️ The key goes as ``Authorization: Token <key>``. Sent as ``Bearer`` it got
500 Internal Server Error: the JWT check behind it raises on a key that is
not a JWT. A wrong key gets 403 "Invalid token.", none at all 403 as well.

⚠️ The weight is a string (``"81.90"``), and an entry made for a date comes
back as that date at midnight UTC. The unit is in ``/userprofile/`` as
``weight_unit``.

⚠️ ``/api/v2/login/`` is gone in 2.7 (404); wger signs in with JWT and OIDC
now, and the permanent key of the profile page still works for the API.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from .base import (
    Adapter,
    AdapterError,
    AuthFailed,
    Context,
    Field,
    WidgetData,
    WidgetType,
    base_url,
)


def _weight(entry: dict[str, Any]) -> float | None:
    try:
        return float(entry.get("weight"))
    except (TypeError, ValueError):
        return None


def _day(entry: dict[str, Any]) -> str:
    return str(entry.get("date") or "")[:10]


def _signed(change: float, unit: str) -> str:
    return f"{change:+.1f} {unit}".replace("+0.0", "0.0").replace("-0.0", "0.0")


class WgerAdapter(Adapter):
    kind = "wger"
    label = "wger"
    category = "other"
    description = "Your weight, how it changed over the last 30 days, and the latest weigh-ins."
    icon = "wger"
    beta = False
    docs_url = "https://wger.readthedocs.io/en/latest/api/api.html"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://wger:8000"),
        Field("token", "API key", type="password", secret=True, required=True, help="The key from the API key page of your profile."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(kind="weight", label="Weight", description="The latest weight, the change over 30 days and when you last weighed in.",
                   renderer="value", default_size=(3, 2), refresh_seconds=3600, metrics=("weight",)),
        WidgetType(kind="entries", label="Weigh-ins", description="The latest weight entries with the change from the one before.",
                   renderer="list", default_size=(3, 3), refresh_seconds=3600,
                   options=(Field("limit", "Entries", type="number", default=8),)),
    )

    async def _json(self, config: dict[str, Any], ctx: Context, path: str, params: dict[str, Any] | None = None, cache: float = 60) -> Any:
        response = await ctx.request(
            "GET", f"{base_url(config)}/api/v2{path}", headers={"Authorization": f"Token {config.get('token') or ''}"},
            params=params, verify=not config.get("insecure"), cache_seconds=cache, auth_errors=False,
        )
        if response.status_code in (401, 403):
            raise AuthFailed("wger rejected the API key.")
        if response.status_code >= 400:
            raise AdapterError(f"wger answered with HTTP {response.status_code}.", code="http_error",
                               hint="Check the URL; it is the address of wger itself, without /api.")
        try:
            return response.json()
        except ValueError as error:
            raise AdapterError("wger did not answer with JSON.", code="not_json",
                               hint="The URL probably points at the sign-in page or a reverse proxy.") from error

    async def _entries(self, config: dict[str, Any], ctx: Context, limit: int) -> tuple[list[dict[str, Any]], int]:
        page = await self._json(config, ctx, "/weightentry/", {"ordering": "-date", "limit": limit})
        if not isinstance(page, dict) or not isinstance(page.get("results"), list):
            raise AdapterError("This address answers, but not the way wger does.", code="not_wger")
        return [one for one in page["results"] if isinstance(one, dict)], int(page.get("count") or 0)

    async def _unit(self, config: dict[str, Any], ctx: Context) -> str:
        profile = await self._json(config, ctx, "/userprofile/", cache=3600)
        return str(profile.get("weight_unit") or "kg") if isinstance(profile, dict) else "kg"

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        version = await self._json(config, ctx, "/version/", cache=0)
        _entries, count = await self._entries(config, ctx, 1)
        return f"wger {version} answers with {count} weight entries."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        unit = await self._unit(config, ctx)
        if widget_kind == "entries":
            limit = max(1, int(options.get("limit") or 8))
            # One more than shown, so the last row has an entry to compare with.
            entries, _count = await self._entries(config, ctx, limit + 1)
            return self._list(entries, unit, limit)
        # The newest entries, back to a little over 30 days.
        entries, _count = await self._entries(config, ctx, 100)
        return self._weight(entries, unit, datetime.now(UTC))

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def _weight(entries: list[dict[str, Any]], unit: str, now: datetime) -> WidgetData:
        known = [(one, weight) for one in entries if (weight := _weight(one)) is not None]
        if not known:
            return WidgetData(status="unknown", primary={"label": "Weight", "value": None, "unit": unit}, meta={"empty": "No weight entries yet."})
        latest, weight = known[0]
        month_ago = (now - timedelta(days=30)).date().isoformat()
        before = next(((one, value) for one, value in known if _day(one) <= month_ago), None)
        secondary: list[dict[str, Any]] = []
        if before:
            secondary.append({"label": "30 days", "value": _signed(weight - before[1], unit)})
        # A date, not "13 h ago": an entry is made for a day, and wger keeps it at midnight UTC.
        secondary.append({"label": "Last weigh-in", "value": _day(latest)})
        return WidgetData(
            status="ok",
            # Text, not a number: the card draws numbers from 10 up without decimals, and 81.9 would read 82.
            primary={"label": "Weight", "value": f"{weight:.1f}", "unit": unit},
            secondary=secondary,
            metrics={"weight": weight},
        )

    @staticmethod
    def _list(entries: list[dict[str, Any]], unit: str, limit: int) -> WidgetData:
        items = []
        for index, entry in enumerate(entries[:limit]):
            weight = _weight(entry)
            earlier = _weight(entries[index + 1]) if index + 1 < len(entries) else None
            items.append({
                "title": _day(entry),
                "subtitle": _signed(weight - earlier, unit) if weight is not None and earlier is not None else "",
                "status": "ok",
                "value": f"{weight:.1f} {unit}" if weight is not None else "?",
            })
        return WidgetData(status="ok", items=items, meta={"empty": "No weight entries yet."})

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        now = datetime.now(UTC)
        entries = [{"date": (now - timedelta(days=days)).strftime("%Y-%m-%dT00:00:00Z"), "weight": f"{weight:.2f}"}
                   for days, weight in ((0, 81.9 - tick % 2 / 10), (2, 81.7), (7, 82.0), (14, 82.4), (30, 83.1), (45, 83.6))]
        if widget_kind == "entries":
            return self._list(entries, "kg", int(options.get("limit") or 8))
        return self._weight(entries, "kg", now)


ADAPTER = WgerAdapter()
