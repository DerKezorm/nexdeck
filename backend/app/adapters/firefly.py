"""Firefly III: net worth, this month's money, subscriptions and budgets.

Measured against Firefly III 6.6.6 on 11.09.2026, with a small household made
there through the API: two accounts, a salary, two expenses, two
subscriptions and a budget.

⚠️ Without ``Accept: application/json`` the API does not answer 401 to a
missing token; it redirects to the sign-in page with a 302 and HTML. Every
request here asks for JSON, so a wrong token reads as a wrong token.

⚠️ ``/summary/basic`` hands out one entry per currency, named like
``net-worth-in-EUR``, with the amount already formatted the way the Firefly
account is set up. The cards show that text as it comes, so a German account
reads 2.917,51 € and nexdeck does not guess at number formats.

⚠️ A subscription made through the API without ``active: true`` is inactive,
and the summary then counts it neither as paid nor as unpaid. Measured: both
were 0.00 until the two were switched on.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
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
)

#: What the overview shows, in order: the key in ``/summary/basic`` and the row's label.
OVERVIEW = (("net-worth", "Net worth"), ("balance", "Balance"), ("spent", "Spent"), ("earned", "Earned"),
            ("bills-unpaid", "Subscriptions due"), ("left-to-spend", "Left to spend"))

PERIOD = Field("period", "Period", type="select", default="month", options=(("month", "This month"), ("year", "This year")))
CURRENCY = Field("currency", "Currency", placeholder="EUR", help="The three letters, such as EUR. Empty takes the first Firefly reports.")


def _period(options: dict[str, Any]) -> tuple[str, str]:
    today = datetime.now(UTC).date()
    if options.get("period") == "year":
        return date(today.year, 1, 1).isoformat(), date(today.year, 12, 31).isoformat()
    following = date(today.year + (today.month == 12), today.month % 12 + 1, 1)
    return today.replace(day=1).isoformat(), date.fromordinal(following.toordinal() - 1).isoformat()


def _money(symbol: Any, amount: Any) -> str:
    try:
        return f"{symbol or ''}{float(amount):,.2f}"
    except (TypeError, ValueError):
        return ""


class FireflyAdapter(Adapter):
    kind = "firefly"
    label = "Firefly III"
    category = "other"
    description = "Net worth, this month's money, subscriptions and budgets."
    icon = "firefly-iii"
    beta = False
    docs_url = "https://docs.firefly-iii.org/references/firefly-iii/api/"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://firefly:8080"),
        Field("token", "Personal access token", type="password", secret=True, required=True,
              help="Options > Profile > OAuth > Personal access tokens > Create new token."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(kind="overview", label="Money", description="Net worth, balance, spent and earned in the period.",
                   renderer="stats", default_size=(3, 3), refresh_seconds=900, metrics=("net_worth", "spent"),
                   options=(PERIOD, CURRENCY)),
        WidgetType(kind="subscriptions", label="Subscriptions", description="Which subscriptions are paid in the period and which are due.",
                   renderer="list", default_size=(3, 3), refresh_seconds=1800, metrics=("due",),
                   options=(Field("limit", "Entries", type="number", default=8), PERIOD)),
        WidgetType(kind="budgets", label="Budgets", description="How much of each budget is spent in the period.",
                   renderer="list", default_size=(3, 3), refresh_seconds=900,
                   options=(Field("limit", "Entries", type="number", default=8), PERIOD)),
    )

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, params: dict[str, Any] | None = None,
                   cache: float = 30) -> Any:
        response = await ctx.request(
            "GET", f"{base_url(config)}/api/v1{path}",
            headers={"Authorization": f"Bearer {config.get('token') or ''}", "Accept": "application/json"},
            params=params, verify=not config.get("insecure"), cache_seconds=cache, auth_errors=False,
        )
        # Measured: a wrong and a missing token both get 401 "Unauthenticated.".
        if response.status_code in (401, 403):
            raise AuthFailed("Firefly III rejected the access token.")
        if response.status_code in (301, 302):
            raise AdapterError("Firefly III sent the request to its sign-in page.", code="not_signed_in",
                               hint="Check the URL; it is the address of Firefly III itself, without /api.")
        if response.status_code >= 400:
            raise AdapterError(f"Firefly III answered with HTTP {response.status_code}.", code="http_error")
        try:
            return response.json()
        except ValueError as error:
            raise AdapterError("Firefly III did not answer with JSON.", code="not_json",
                               hint="The URL probably points at a login page or a reverse proxy.") from error

    async def _list(self, config: dict[str, Any], ctx: Context, path: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        answer = await self._get(config, ctx, path, params=params)
        if not isinstance(answer, dict) or not isinstance(answer.get("data"), list):
            raise AdapterError("This address answers, but not the way Firefly III does.", code="not_firefly")
        return [one for one in answer["data"] if isinstance(one, dict)]

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        about = await self._get(config, ctx, "/about", cache=0)
        version = (about.get("data") or {}).get("version") if isinstance(about, dict) else None
        if not version:
            raise AdapterError("This address answers, but not the way Firefly III does.", code="not_firefly")
        return f"Firefly III {version} answers."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        start, end = _period(options)
        if widget_kind == "overview":
            summary = await self._get(config, ctx, "/summary/basic", params={"start": start, "end": end})
            if not isinstance(summary, dict):
                raise AdapterError("This address answers, but not the way Firefly III does.", code="not_firefly")
            return self._overview(summary, str(options.get("currency") or "").strip().upper())
        if widget_kind == "subscriptions":
            bills = await self._list(config, ctx, "/bills", {"start": start, "end": end})
            return self._subscriptions(bills, options, start, end)
        budgets = await self._list(config, ctx, "/budgets", {"start": start, "end": end})
        limits = await self._list(config, ctx, "/budget-limits", {"start": start, "end": end})
        return self._budgets(budgets, limits, options)

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def _overview(summary: dict[str, Any], wanted: str) -> WidgetData:
        currencies = [key.rsplit("-in-", 1)[1] for key in summary if key.startswith("net-worth-in-")]
        if not currencies:
            currencies = sorted({key.rsplit("-in-", 1)[1] for key in summary if "-in-" in key})
        if not currencies:
            return WidgetData(status="unknown", meta={"notice": "Firefly III has no money to report for this period."})
        if wanted and wanted not in currencies:
            raise AdapterError(f"Firefly III reports no amounts in {wanted}.", code="no_such_currency",
                               hint="It reports: " + ", ".join(currencies) + ".")
        code = wanted or currencies[0]
        rows: list[dict[str, Any]] = []
        numbers: dict[str, float] = {}
        for key, label in OVERVIEW:
            entry = summary.get(f"{key}-in-{code}")
            if not isinstance(entry, dict):
                continue
            rows.append({"label": label, "value": str(entry.get("value_parsed") or "")})
            try:
                numbers[key] = float(entry.get("monetary_value"))
            except (TypeError, ValueError):
                pass
        primary, *secondary = rows or [{"label": "Net worth", "value": ""}]
        metrics = {}
        if "net-worth" in numbers:
            metrics["net_worth"] = numbers["net-worth"]
        if "spent" in numbers:
            metrics["spent"] = abs(numbers["spent"])
        return WidgetData(status="ok", primary=primary, secondary=secondary, metrics=metrics)

    @staticmethod
    def _subscriptions(bills: list[dict[str, Any]], options: dict[str, Any], start: str, end: str) -> WidgetData:
        today = datetime.now(UTC).date().isoformat()
        rows: list[tuple[int, str, dict[str, Any]]] = []
        due = 0
        for bill in bills:
            attributes = bill.get("attributes") or {}
            if not attributes.get("active"):
                continue
            symbol = attributes.get("currency_symbol") or ""
            low, high = _money(symbol, attributes.get("amount_min")), _money(symbol, attributes.get("amount_max"))
            amount = low if low == high else f"{low} - {high}"
            paid = [str(one.get("date") or "")[:10] for one in attributes.get("paid_dates") or [] if isinstance(one, dict)]
            expected = str(attributes.get("next_expected_match") or "")[:10]
            if paid:
                order, word, status, when = 2, "Paid", "ok", max(paid)
            elif expected and start <= expected <= end and expected <= today:
                order, word, status, when = 0, "Due", "warn", expected
                due += 1
            elif expected and expected <= end:
                order, word, status, when = 1, "Next", "ok", expected
            else:
                pay_dates = [str(one)[:10] for one in attributes.get("pay_dates") or []]
                order, word, status, when = 3, "Next", "ok", min(pay_dates) if pay_dates else ""
            rows.append((order, when, {
                "title": str(attributes.get("name") or "?"),
                "subtitle": " · ".join(part for part in (word, when) if part),
                "status": status,
                "value": amount,
            }))
        rows.sort(key=lambda entry: (entry[0], entry[1]))
        return WidgetData(
            status="warn" if due else "ok",
            items=[row for _order, _when, row in rows][: int(options.get("limit") or 8)],
            secondary=[{"label": "Due", "value": due}],
            meta={"empty": "No active subscriptions."},
            metrics={"due": float(due)},
        )

    @staticmethod
    def _budgets(budgets: list[dict[str, Any]], limits: list[dict[str, Any]], options: dict[str, Any]) -> WidgetData:
        names = {str(one.get("id")): str((one.get("attributes") or {}).get("name") or "?") for one in budgets}
        items: list[dict[str, Any]] = []
        over = 0
        for limit in limits:
            attributes = limit.get("attributes") or {}
            try:
                amount = float(attributes.get("amount") or 0)
                spent = abs(sum(float(one.get("sum") or 0) for one in attributes.get("spent") or [] if isinstance(one, dict)))
            except (TypeError, ValueError):
                continue
            share = round(100.0 * spent / amount, 1) if amount else None
            if share is not None and share > 100:
                over += 1
            symbol = attributes.get("currency_symbol") or ""
            items.append({
                "title": names.get(str(attributes.get("budget_id")), "?"),
                "progress": min(100.0, share) if share is not None else None,
                "status": "bad" if share is not None and share > 100 else "warn" if share is not None and share >= 85 else "ok",
                "value": f"{_money(symbol, spent)} / {_money(symbol, amount)}",
            })
        items.sort(key=lambda row: -(row["progress"] or 0))
        return WidgetData(
            status="bad" if over else "ok",
            items=items[: int(options.get("limit") or 8)],
            secondary=[{"label": "Over budget", "value": over}],
            meta={"empty": "No budget has a limit in this period."},
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        spent = 1_240.5 + fake.walk("ff-spent", tick, 0, 60)
        if widget_kind == "overview":
            def entry(value: float) -> dict[str, Any]:
                return {"monetary_value": f"{value:.2f}", "value_parsed": f"{value:,.2f} €", "currency_code": "EUR"}

            return self._overview({"net-worth-in-EUR": entry(38_417.2), "balance-in-EUR": entry(1_759.5 - spent + 1_240.5),
                                   "spent-in-EUR": entry(-spent), "earned-in-EUR": entry(3_000.0),
                                   "bills-unpaid-in-EUR": entry(-90.0), "left-to-spend-in-EUR": entry(400.0 - spent / 4)}, "")
        start, end = _period(options)
        if widget_kind == "subscriptions":
            first = start
            bills = [
                {"attributes": {"name": "Internet", "active": True, "amount_min": "39.99", "amount_max": "39.99", "currency_symbol": "€",
                                "paid_dates": [{"date": first}], "next_expected_match": None, "pay_dates": []}},
                {"attributes": {"name": "Electricity", "active": True, "amount_min": "85", "amount_max": "95", "currency_symbol": "€",
                                "paid_dates": [], "next_expected_match": first, "pay_dates": [first]}},
                {"attributes": {"name": "Streaming", "active": True, "amount_min": "13.99", "amount_max": "13.99", "currency_symbol": "€",
                                "paid_dates": [], "next_expected_match": end, "pay_dates": [end]}},
            ]
            return self._subscriptions(bills, options, start, end)
        budgets = [{"id": "1", "attributes": {"name": "Food"}}, {"id": "2", "attributes": {"name": "Going out"}}, {"id": "3", "attributes": {"name": "Hardware"}}]
        limits = [
            {"attributes": {"budget_id": "1", "amount": "400", "currency_symbol": "€", "spent": [{"sum": f"-{212 + tick % 40}"}]}},
            {"attributes": {"budget_id": "2", "amount": "150", "currency_symbol": "€", "spent": [{"sum": "-131.40"}]}},
            {"attributes": {"budget_id": "3", "amount": "100", "currency_symbol": "€", "spent": [{"sum": "-119.99"}]}},
        ]
        return self._budgets(budgets, limits, options)



ADAPTER = FireflyAdapter()
