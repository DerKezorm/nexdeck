"""Wallos: when the subscriptions are paid next, and what falls due this month.

Measured against Wallos v5.7.1 (bellamy/wallos) on 11.09.2026, with five
invented subscriptions: three monthly ones in euros, one in US dollars, a
yearly one and an inactive one.

⚠️ The API key is a request parameter and nothing else. Sent in an
``X-API-Key`` header it got "Missing parameters"; as a form field of a POST it
works, so it stays out of the address and out of the access log.

⚠️ A missing and a wrong key both get HTTP 200 with ``success: false`` and the
title "Missing parameters" or "Invalid API key". Only the body says it failed.

⚠️ The monthly cost is what falls due in that month, not an average: a
yearly subscription of 36.00 due in October made October 65.47 and left
September at 29.47.

⚠️ Without exchange rates (a Fixer API key in Wallos) a price in another
currency is added to the total as if it were the main one: 15.49 USD went into
the September sum as 15.49 EUR, with a note saying the rates are missing. The
card says so and does not record that sum.
"""

from __future__ import annotations

import time
from datetime import UTC, date, datetime, timedelta
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

#: Wallos's cycles: 1 days, 2 weeks, 3 months, 4 years.
CYCLES = {1: "Daily", 2: "Weekly", 3: "Monthly", 4: "Yearly"}
#: What Wallos says when the key is missing or unknown.
REFUSALS = ("Invalid API key", "Missing parameters")


def _money(symbol: Any, amount: Any) -> str:
    try:
        return f"{symbol or ''}{float(amount):,.2f}"
    except (TypeError, ValueError):
        return ""


def _following_month(today: date) -> date:
    return (today.replace(day=1) + timedelta(days=32)).replace(day=1)


class WallosAdapter(Adapter):
    kind = "wallos"
    label = "Wallos"
    category = "other"
    description = "When the subscriptions are paid next, and what falls due this month."
    icon = "wallos"
    #: Confirmed against a live instance on 2026-09-11.
    beta = False
    docs_url = "https://github.com/ellite/Wallos"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://wallos:80"),
        Field("api_key", "API key", type="password", secret=True, required=True,
              help="Profile > API Key. It belongs to one user, and the cards see that user's subscriptions."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(kind="upcoming", label="Next payments", description="The active subscriptions, the next payment first.",
                   renderer="list", default_size=(3, 3), refresh_seconds=1800,
                   options=(Field("limit", "Entries", type="number", default=8),)),
        WidgetType(kind="month", label="Subscription costs", description="What falls due this month and next month, added up by Wallos.",
                   renderer="value", default_size=(3, 2), refresh_seconds=1800, metrics=("month_cost",)),
    )

    async def _call(self, config: dict[str, Any], ctx: Context, path: str, **fields: Any) -> dict[str, Any]:
        # A POST with the key in the body: Wallos reads it from there as well, and nothing logs a body.
        response = await ctx.request(
            "POST", f"{base_url(config)}/api/{path}",
            data={"api_key": str(config.get("api_key") or ""), **{name: str(value) for name, value in fields.items()}},
            headers={"Accept": "application/json"}, verify=not config.get("insecure"), auth_errors=False,
        )
        if response.status_code in (401, 403):
            raise AuthFailed("Wallos rejected the API key.")
        if response.status_code >= 400:
            raise AdapterError(f"Wallos answered with HTTP {response.status_code}.", code="http_error",
                               hint="Check the URL; it is the address of Wallos itself, without /api.")
        try:
            answer = response.json()
        except ValueError as error:
            raise AdapterError("Wallos did not answer with JSON.", code="not_json",
                               hint="The URL probably points at the sign-in page or a reverse proxy.") from error
        if not isinstance(answer, dict) or "success" not in answer:
            raise AdapterError("This address answers, but not the way Wallos does.", code="not_wallos")
        if answer.get("success") is not True:
            title = str(answer.get("title") or "")
            if title in REFUSALS:
                raise AuthFailed("Wallos rejected the API key.")
            raise AdapterError(f"Wallos refused the request: {title or 'no reason given'}.", code="wallos_error")
        return answer

    async def _currencies(self, config: dict[str, Any], ctx: Context) -> dict[str, Any]:
        kept = ctx.cache.get("wallos_currencies")
        if kept and kept[0] > time.time():
            return kept[1]
        answer = await self._call(config, ctx, "currencies/get_currencies.php")
        ctx.cache["wallos_currencies"] = (time.time() + 3600, answer)
        return answer

    async def _subscriptions(self, config: dict[str, Any], ctx: Context) -> list[dict[str, Any]]:
        answer = await self._call(config, ctx, "subscriptions/get_subscriptions.php", state=0, sort="next_payment")
        return [one for one in answer.get("subscriptions") or [] if isinstance(one, dict)]

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        version = await self._call(config, ctx, "status/version.php")
        active = await self._subscriptions(config, ctx)
        return f"Wallos {version.get('version') or '?'} answers with {len(active)} active subscriptions."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        today = datetime.now(UTC).date()
        active = await self._subscriptions(config, ctx)
        currencies = await self._currencies(config, ctx)
        if widget_kind == "month":
            following = _following_month(today)
            this_month = await self._call(config, ctx, "subscriptions/get_monthly_cost.php", month=today.month, year=today.year)
            next_month = await self._call(config, ctx, "subscriptions/get_monthly_cost.php", month=following.month, year=following.year)
            return self._month(this_month, next_month, active, currencies.get("main_currency"))
        return self._upcoming(active, currencies, today, options)

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def _upcoming(active: list[dict[str, Any]], currencies: dict[str, Any], today: date, options: dict[str, Any]) -> WidgetData:
        symbols = {str(one.get("id")): one.get("symbol") or "" for one in currencies.get("currencies") or [] if isinstance(one, dict)}
        items = []
        for sub in sorted(active, key=lambda one: str(one.get("next_payment") or "9999")):
            day = str(sub.get("next_payment") or "")[:10]
            when = "Today" if day == today.isoformat() else "Tomorrow" if day == (today + timedelta(days=1)).isoformat() else day
            try:
                cycle = CYCLES.get(int(sub.get("cycle") or 0), "") if int(sub.get("frequency") or 0) == 1 else ""
            except (TypeError, ValueError):
                cycle = ""
            items.append({
                "title": str(sub.get("name") or "?"),
                "subtitle": " · ".join(part for part in (when, cycle) if part),
                "status": "warn" if day and day <= today.isoformat() else "ok",
                "value": _money(symbols.get(str(sub.get("currency_id")), ""), sub.get("price")),
            })
        return WidgetData(status="ok", items=items[: int(options.get("limit") or 8)], meta={"empty": "No active subscriptions."})

    @staticmethod
    def _month(this_month: dict[str, Any], next_month: dict[str, Any], active: list[dict[str, Any]], main_currency: Any) -> WidgetData:
        foreign = sum(1 for sub in active if str(sub.get("currency_id")) != str(main_currency))
        # Wallos says in its notes when it could not convert; the count is the card's own.
        unconverted = foreign if foreign and this_month.get("notes") else 0
        secondary: list[dict[str, Any]] = [{"label": "Next month", "value": str(next_month.get("localized_monthly_cost") or "")}]
        secondary.append({"label": "Not converted", "value": unconverted} if unconverted else {"label": "Active", "value": len(active)})
        metrics: dict[str, float] = {}
        if not unconverted:
            try:
                metrics["month_cost"] = float(this_month.get("monthly_cost"))
            except (TypeError, ValueError):
                pass
        return WidgetData(
            status="warn" if unconverted else "ok",
            primary={"label": "This month", "value": str(this_month.get("localized_monthly_cost") or "")},
            secondary=secondary,
            metrics=metrics,
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        today = datetime.now(UTC).date()

        def due(days: int) -> str:
            return (today + timedelta(days=days)).isoformat()

        active = [
            {"name": "Music Streaming", "price": 10.99, "currency_id": 1, "next_payment": due(1), "cycle": 3, "frequency": 1},
            {"name": "Cloud Storage", "price": 2.99, "currency_id": 1, "next_payment": due(12), "cycle": 3, "frequency": 1},
            {"name": "Password Manager", "price": 36.0, "currency_id": 1, "next_payment": due(40), "cycle": 4, "frequency": 1},
        ]
        if widget_kind == "month":
            cost = 13.98 + tick % 2 * 36
            return self._month({"monthly_cost": f"{cost:.2f}", "localized_monthly_cost": f"€{cost:.2f}", "notes": []},
                               {"monthly_cost": "49.98", "localized_monthly_cost": "€49.98", "notes": []}, active, 1)
        return self._upcoming(active, {"main_currency": 1, "currencies": [{"id": 1, "symbol": "€", "code": "EUR"}]}, today, options)


ADAPTER = WallosAdapter()
