"""Ghostfolio: what the portfolio is worth, how it moved today, and which holding moved how.

Measured against Ghostfolio 3.69.0 on 11.09.2026, with an invented portfolio
of three purchases (two US shares in dollars and an ETF in euros) and the
market data of Yahoo Finance, which needs no account.

⚠️ There is no API key. The security token of an account is exchanged at
``/api/v1/auth/anonymous`` for a JWT that lasts 180 days; the card keeps it
for a day. A wrong security token gets 403, a missing or made-up JWT 401.
The admin endpoints answer 403 to an ordinary account, so the card uses none.

⚠️ Right after an import the numbers are not settled. Within seconds the
portfolio stood at 0.00 with no holdings. Twenty seconds later yesterday's
point of the ``1d`` chart stood at exactly the amount invested (6500), so
"today" was the whole gain since March, +40.6%. Thirty seconds after that
yesterday had a price and today read +1.25%. While yesterday still equals the
investment the card says it does not know, and a portfolio without any chart
is not written into the history as a zero.

⚠️ The percentages are shares (``0.0125`` is 1.25%) and they are Ghostfolio's
own return on the amount invested, not on yesterday's value: -0.21 on a
portfolio worth 654.87 read -0.07%, because 300 were invested.
``range=1d`` on the holdings turns each holding's performance into today's.
"""

from __future__ import annotations

import time
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

#: The JWT lasts 180 days (measured); asking again once a day costs nothing.
JWT_SECONDS = 24 * 3600


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _settled(today: dict[str, Any]) -> bool:
    """False while the day change still stands on yesterday's missing prices."""
    chart = [point for point in today.get("chart") or [] if isinstance(point, dict)]
    change = _number((today.get("performance") or {}).get("netPerformanceWithCurrencyEffect"))
    if not chart or not change:
        return True
    first = chart[0]
    return _number(first.get("value")) != _number(first.get("totalInvestment"))


class GhostfolioAdapter(Adapter):
    kind = "ghostfolio"
    label = "Ghostfolio"
    category = "other"
    description = "What the portfolio is worth, how it moved today, and which holding moved how."
    icon = "ghostfolio"
    #: Confirmed against a live instance on 2026-09-11.
    beta = False
    docs_url = "https://github.com/ghostfolio/ghostfolio"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://ghostfolio:3333"),
        Field("security_token", "Security token", type="password", secret=True, required=True,
              help="Settings > Access > Security Token. Ghostfolio has no API keys; the card signs in with this token."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(kind="portfolio", label="Portfolio", description="What the portfolio is worth, today's change and the change since the first activity.",
                   renderer="value", default_size=(3, 2), refresh_seconds=300, metrics=("value",)),
        WidgetType(kind="holdings", label="Holdings", description="Every holding with what it is worth and how it moved today, the biggest first.",
                   renderer="list", default_size=(3, 3), refresh_seconds=300,
                   options=(Field("limit", "Entries", type="number", default=8),)),
    )

    # -- talking to Ghostfolio -----------------------------------------------

    async def _jwt(self, config: dict[str, Any], ctx: Context, force: bool = False) -> str:
        kept = ctx.cache.get("ghostfolio_jwt")
        if kept and not force and kept[0] > time.time():
            return str(kept[1])
        response = await ctx.request(
            "POST", f"{base_url(config)}/api/v1/auth/anonymous", json_body={"accessToken": str(config.get("security_token") or "")},
            headers={"Accept": "application/json"}, verify=not config.get("insecure"), auth_errors=False,
        )
        if response.status_code in (401, 403):
            raise AuthFailed("Ghostfolio rejected the security token.")
        if response.status_code >= 400:
            raise AdapterError(f"Ghostfolio answered the sign-in with HTTP {response.status_code}.", code="http_error",
                               hint="Check the URL; it is the address of Ghostfolio itself, without /api.")
        try:
            token = str((response.json() or {}).get("authToken") or "")
        except (ValueError, AttributeError) as error:
            raise AdapterError("Ghostfolio did not answer the sign-in with JSON.", code="not_json",
                               hint="The URL probably points at something else than Ghostfolio.") from error
        if not token:
            raise AdapterError("This address answers, but not the way Ghostfolio does.", code="not_ghostfolio")
        ctx.cache["ghostfolio_jwt"] = (time.time() + JWT_SECONDS, token)
        return token

    async def _json(self, config: dict[str, Any], ctx: Context, path: str, params: dict[str, Any] | None = None, cache: float = 60) -> Any:
        for attempt in (0, 1):
            token = await self._jwt(config, ctx, force=attempt == 1)
            response = await ctx.request(
                "GET", f"{base_url(config)}/api{path}", headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                params=params, verify=not config.get("insecure"), cache_seconds=cache if attempt == 0 else 0, auth_errors=False,
            )
            # A JWT signed with an older secret is refused like a made-up one: sign in once more.
            if response.status_code != 401 or attempt == 1:
                break
            ctx.forget_answers()
        if response.status_code in (401, 403):
            raise AuthFailed("Ghostfolio refused the account.")
        if response.status_code >= 400:
            raise AdapterError(f"Ghostfolio answered with HTTP {response.status_code}.", code="http_error",
                               hint="Check the URL; it is the address of Ghostfolio itself, without /api.")
        try:
            answer = response.json()
        except ValueError as error:
            raise AdapterError("Ghostfolio did not answer with JSON.", code="not_json",
                               hint="The URL probably points at something else than Ghostfolio.") from error
        if not isinstance(answer, dict):
            raise AdapterError("This address answers, but not the way Ghostfolio does.", code="not_ghostfolio")
        return answer

    async def _currency(self, config: dict[str, Any], ctx: Context) -> str:
        user = await self._json(config, ctx, "/v1/user", cache=3600)
        settings = user.get("settings") if isinstance(user.get("settings"), dict) else {}
        return str(settings.get("baseCurrency") or settings.get("currency") or "")

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        user = await self._json(config, ctx, "/v1/user", cache=0)
        return f"Ghostfolio answers for an account with {int(user.get('activitiesCount') or 0)} activities."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        currency = await self._currency(config, ctx)
        today = await self._json(config, ctx, "/v2/portfolio/performance", {"range": "1d"})
        if widget_kind == "holdings":
            holdings = await self._json(config, ctx, "/v1/portfolio/holdings", {"range": "1d"})
            return self._holdings(holdings, _settled(today), currency, options)
        overall = await self._json(config, ctx, "/v2/portfolio/performance", {"range": "max"})
        return self._portfolio(today, overall, currency)

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def _portfolio(today: dict[str, Any], overall: dict[str, Any], currency: str) -> WidgetData:
        performance = today.get("performance") if isinstance(today.get("performance"), dict) else {}
        value = _number(performance.get("currentValueInBaseCurrency"))
        change = _number(performance.get("netPerformanceWithCurrencyEffect"))
        share = _number(performance.get("netPerformancePercentageWithCurrencyEffect"))
        settled = _settled(today)
        known = settled and change is not None and share is not None
        secondary: list[dict[str, Any]] = [{"label": "Today", "value": f"{change:+,.2f} ({share * 100:+.2f}%)" if known else "?"}]
        since = _number((overall.get("performance") or {}).get("netPerformancePercentageWithCurrencyEffect"))
        if since is not None:
            secondary.append({"label": "Since start", "value": f"{since * 100:+.2f}%"})
        # A portfolio without any chart has nothing to put in a history: measured right after an import, it stood at 0.00.
        charted = any(isinstance(point, dict) for point in today.get("chart") or [])
        return WidgetData(
            status="ok" if settled else "unknown",
            # Text, not a number: the card draws numbers from 10 up without decimals.
            primary={"label": "Portfolio value", "value": f"{value:,.2f}" if value is not None else None, "unit": currency},
            secondary=secondary,
            metrics={"value": value} if value is not None and charted else {},
        )

    @staticmethod
    def _holdings(answer: dict[str, Any], settled: bool, currency: str, options: dict[str, Any]) -> WidgetData:
        rows = [one for one in answer.get("holdings") or [] if isinstance(one, dict)]
        rows.sort(key=lambda one: -(_number(one.get("valueInBaseCurrency")) or 0))
        items = []
        for one in rows[: int(options.get("limit") or 8)]:
            profile = one.get("assetProfile") if isinstance(one.get("assetProfile"), dict) else {}
            worth = _number(one.get("valueInBaseCurrency"))
            share = _number(one.get("netPerformancePercentWithCurrencyEffect"))
            items.append({
                "title": str(profile.get("name") or profile.get("symbol") or "?"),
                "subtitle": " · ".join(part for part in (str(profile.get("symbol") or ""), f"{worth:,.2f} {currency}".strip() if worth is not None else "") if part),
                "status": "ok",
                "value": f"{share * 100:+.2f}%" if settled and share is not None else "",
            })
        return WidgetData(status="ok" if settled else "unknown", items=items, meta={"empty": "No holdings yet."})

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        wobble = (tick % 7 - 3) / 1000
        today = {"chart": [{"value": 9_584.96, "totalInvestment": 6_900.57}, {"value": 9_672.76, "totalInvestment": 6_900.57}],
                 "performance": {"currentValueInBaseCurrency": 9_672.76 * (1 + wobble), "netPerformanceWithCurrencyEffect": 85.25 + 9_672.76 * wobble,
                                 "netPerformancePercentageWithCurrencyEffect": 0.0125 + wobble}}
        if widget_kind == "holdings":
            holdings = {"holdings": [
                {"assetProfile": {"name": "Example All-World ETF", "symbol": "EXWLD"}, "valueInBaseCurrency": 3_871.91, "netPerformancePercentWithCurrencyEffect": 0.0032 + wobble},
                {"assetProfile": {"name": "Example Computers Inc.", "symbol": "EXCMP"}, "valueInBaseCurrency": 3_322.70, "netPerformancePercentWithCurrencyEffect": 0.0175},
                {"assetProfile": {"name": "Example Software Corporation", "symbol": "EXSFT"}, "valueInBaseCurrency": 2_478.15, "netPerformancePercentWithCurrencyEffect": -0.0065},
            ]}
            return self._holdings(holdings, True, "USD", options)
        return self._portfolio(today, {"performance": {"netPerformancePercentageWithCurrencyEffect": 0.6435}}, "USD")


ADAPTER = GhostfolioAdapter()
