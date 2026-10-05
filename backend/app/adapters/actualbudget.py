"""Actual Budget: this month's budget, the accounts and the categories.

Measured on 05.10.2026 against Actual 26.10.0 and actual-http-api 26.10.0 on
docker-dev, with a made-up household budget: three open accounts, one off
budget, one closed, and one category overspent.

- Actual has no HTTP API of its own. Its server only stores the budget file;
  every number is worked out by Actual's own library, which downloads and
  opens the file. The way in from outside is the community wrapper
  actual-http-api (github.com/jhonderson/actual-http-api), a second container
  that runs that library and answers in JSON. This adapter talks to the
  wrapper, never to Actual's server: the URL is the wrapper's.
- The wrapper's key goes in ``x-api-key``. A missing or wrong one answers 403
  ``{"error": "Forbidden"}``; an unknown sync id 404 with a sentence that says
  where to find the right one.
- Every answer is ``{"data": ...}``. Amounts are whole cents: 413041 is
  4,130.41. Spending is negative.
- The wrapper downloads and syncs the budget on each request, so the cards
  refresh every ten minutes and the two that read the month share one answer.
- An end-to-end encrypted budget needs its password in the header
  ``budget-encryption-password``.
- Nothing is ever written: no transaction, no budget amount.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from urllib.parse import quote

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

SHOW = (("all", "Every category"), ("over", "Only overspent"))
#: Seconds an answer is kept: each request makes the wrapper download and sync the budget.
CACHE = 300


class ActualBudgetAdapter(Adapter):
    kind = "actualbudget"
    label = "Actual Budget"
    category = "other"
    description = "This month's budget, the balances of the accounts and what each category has left, through actual-http-api."
    icon = "actual-budget"
    beta = True
    docs_url = "https://github.com/jhonderson/actual-http-api"
    keywords = ("Budget", "Money", "Finance", "Envelope", "YNAB")
    fields = (
        Field("url", "actual-http-api URL", type="url", required=True, placeholder="http://actual-http-api:5007",
              help="The address of actual-http-api, the container that reads Actual for other programs. Actual's own address does not answer here."),
        Field("api_key", "API key", type="password", secret=True, required=True,
              help="The API_KEY set on actual-http-api."),
        Field("sync_id", "Sync ID", required=True, placeholder="b4c1894d-36f8-45ec-ba10-70780dbd38a3",
              help="In Actual: Settings > Show advanced settings > Sync ID."),
        Field("encryption_password", "Encryption password", type="password", secret=True,
              help="Only for a budget with end-to-end encryption."),
        Field("currency", "Currency symbol", placeholder="€", help="Put in front of every amount. Empty shows the numbers alone."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(
            kind="month",
            label="This month",
            description="What is left to budget this month, what is budgeted and spent, and how many categories are overspent.",
            renderer="value",
            default_size=(3, 2),
            refresh_seconds=600,
            metrics=("spent",),
        ),
        WidgetType(
            kind="accounts",
            label="Accounts",
            description="Each open account with its balance, and the sums on and off budget.",
            renderer="list",
            default_size=(3, 3),
            refresh_seconds=600,
            options=(
                Field("offbudget", "Show accounts off budget", type="bool", default=True),
                Field("limit", "Entries", type="number", default=8),
            ),
        ),
        WidgetType(
            kind="categories",
            label="Categories",
            description="What each category of this month has spent of its budget, the overspent first.",
            renderer="list",
            default_size=(3, 3),
            refresh_seconds=600,
            options=(
                Field("show", "Show", type="select", default="all", options=SHOW),
                Field("limit", "Entries", type="number", default=8),
            ),
        ),
    )

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, *,
                   params: dict[str, Any] | None = None, cache: int = CACHE) -> Any:
        sync_id = str(config.get("sync_id") or "").strip()
        if not sync_id:
            raise AdapterError("The connection has no sync ID.", code="bad_param",
                               hint="In Actual: Settings > Show advanced settings > Sync ID.")
        headers = {"x-api-key": str(config.get("api_key") or ""), "Accept": "application/json"}
        secret = str(config.get("encryption_password") or "")
        if secret:
            headers["budget-encryption-password"] = secret
        response = await ctx.request(
            "GET", f"{base_url(config)}/v1/budgets/{quote(sync_id, safe='')}{path}", params=params,
            cache_seconds=cache, auth_errors=False, headers=headers, verify=not config.get("insecure"),
        )
        said = _error_of(response)
        if response.status_code in (401, 403):
            raise AuthFailed("actual-http-api refused the API key.")
        if response.status_code == 404 and "not found" in said.lower():
            raise AdapterError("actual-http-api knows no budget with this sync ID.", code="not_found",
                               hint="In Actual: Settings > Show advanced settings > Sync ID.")
        if response.status_code >= 400:
            detail = f": {said[:200]}" if said else "."
            raise AdapterError(f"actual-http-api answered with HTTP {response.status_code}{detail}", code="http_error")
        try:
            answer = response.json()
        except ValueError:
            raise AdapterError("This address did not answer with JSON; is it the address of actual-http-api?",
                               code="bad_answer") from None
        if not isinstance(answer, dict) or "data" not in answer:
            raise AdapterError("This address answered, but not as actual-http-api does.", code="bad_answer")
        return answer["data"]

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        accounts = await self._get(config, ctx, "/accounts", cache=0)
        accounts = accounts if isinstance(accounts, list) else []
        open_ones = sum(1 for one in accounts if isinstance(one, dict) and not one.get("closed"))
        return f"actual-http-api answers; the budget has {open_ones} open account(s)."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        symbol = str(config.get("currency") or "").strip()
        if widget_kind == "accounts":
            accounts = await self._get(config, ctx, "/accounts", params={"include_balances": "true"})
            return accounts_of(accounts if isinstance(accounts, list) else [], symbol, options)
        month = await self._get(config, ctx, f"/months/{_this_month()}")
        month = month if isinstance(month, dict) else {}
        if widget_kind == "categories":
            return categories_of(month, symbol, options)
        return month_of(month, symbol)

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        groceries = int(fake.walk("actual-groceries", tick, 21000, 29000))
        if widget_kind == "accounts":
            return accounts_of([
                {"name": "Checking", "offbudget": False, "closed": False, "workingBalance": 413041 - groceries},
                {"name": "Credit card", "offbudget": False, "closed": False, "workingBalance": -12840},
                {"name": "Old account", "offbudget": False, "closed": True, "workingBalance": 0},
                {"name": "Savings", "offbudget": True, "closed": False, "workingBalance": 800000},
            ], "€", options)
        month = {
            "toBudget": 361000, "totalBudgeted": -164000, "totalSpent": -(103000 + 10289 + groceries + 3850),
            "totalBalance": 164000 - (103000 + 10289 + groceries + 3850),
            "categoryGroups": [
                {"name": "Home", "is_income": False, "categories": [
                    {"name": "Rent", "budgeted": 95000, "spent": -95000, "balance": 0},
                    {"name": "Power", "budgeted": 8000, "spent": -8000, "balance": 0}]},
                {"name": "Food", "is_income": False, "categories": [
                    {"name": "Groceries", "budgeted": 40000, "spent": -groceries, "balance": 40000 - groceries},
                    {"name": "Restaurants", "budgeted": 12000, "spent": -3850, "balance": 8150}]},
                {"name": "Fun", "is_income": False, "categories": [
                    {"name": "Streaming", "budgeted": 3000, "spent": -1299, "balance": 1701},
                    {"name": "Hobbies", "budgeted": 6000, "spent": -8990, "balance": -2990}]},
                {"name": "Income", "is_income": True, "categories": [{"name": "Salary", "is_income": True, "received": 280000}]},
            ],
        }
        if widget_kind == "categories":
            return categories_of(month, "€", options)
        return month_of(month, "€")


def _this_month() -> str:
    """This month on nexdeck's clock, which is the clock of the people looking at the board."""
    return datetime.now().astimezone().strftime("%Y-%m")


def _error_of(response: Any) -> str:
    try:
        body = response.json()
    except (ValueError, AttributeError):
        return ""
    return str(body.get("error") or "") if isinstance(body, dict) else ""


def _cents(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def money(symbol: str, cents: int | None) -> str:
    """Whole cents as an amount with two places: 413041 is 4,130.41."""
    if cents is None:
        return "?"
    sign = "-" if cents < 0 else ""
    return f"{sign}{symbol}{abs(cents) / 100:,.2f}"


def _limit(options: dict[str, Any]) -> int:
    try:
        return max(1, min(50, int(options.get("limit") or 8)))
    except (TypeError, ValueError):
        return 8


def _spending(month: dict[str, Any]) -> list[dict[str, Any]]:
    """The categories that are budgeted: not income, not hidden, neither the category nor its group."""
    out = []
    for group in month.get("categoryGroups") or []:
        if not isinstance(group, dict) or group.get("is_income") or group.get("hidden"):
            continue
        for category in group.get("categories") or []:
            if isinstance(category, dict) and not category.get("is_income") and not category.get("hidden"):
                out.append({**category, "group": str(group.get("name") or "")})
    return out


def month_of(month: dict[str, Any], symbol: str) -> WidgetData:
    over = [one for one in _spending(month) if (_cents(one.get("balance")) or 0) < 0]
    to_budget = _cents(month.get("toBudget"))
    spent = _cents(month.get("totalSpent"))
    budgeted = _cents(month.get("totalBudgeted"))
    reasons = []
    if to_budget is not None and to_budget < 0:
        reasons.append(f"{money(symbol, -to_budget)} more is budgeted than there is.")
    if over:
        reasons.append(f"{len(over)} categor{'y is' if len(over) == 1 else 'ies are'} overspent: "
                       + ", ".join(str(one.get("name") or "?") for one in over[:3]) + ".")
    # A tracking budget has no "to budget"; then the month's spending leads.
    primary = ({"label": "To budget", "value": money(symbol, to_budget)} if to_budget is not None
               else {"label": "Spent", "value": money(symbol, -spent if spent is not None else None)})
    return WidgetData(
        status="bad" if to_budget is not None and to_budget < 0 else "warn" if over else "ok",
        primary=primary,
        secondary=[
            {"label": "Budgeted", "value": money(symbol, abs(budgeted) if budgeted is not None else None)},
            {"label": "Spent", "value": money(symbol, -spent if spent is not None else None)},
            {"label": "Left", "value": money(symbol, _cents(month.get("totalBalance")))},
            {"label": "Overspent", "value": len(over)},
        ],
        metrics={"spent": abs(spent) / 100} if spent is not None else {},
        meta={"status_reason": " ".join(reasons)},
    )


def accounts_of(accounts: list[Any], symbol: str, options: dict[str, Any]) -> WidgetData:
    shown = [one for one in accounts if isinstance(one, dict) and not one.get("closed")]
    on = sum(_cents(one.get("workingBalance")) or 0 for one in shown if not one.get("offbudget"))
    off = sum(_cents(one.get("workingBalance")) or 0 for one in shown if one.get("offbudget"))
    if not options.get("offbudget", True):
        shown = [one for one in shown if not one.get("offbudget")]
    shown.sort(key=lambda one: (bool(one.get("offbudget")), str(one.get("name") or "").casefold()))
    items = []
    for one in shown:
        balance = _cents(one.get("workingBalance"))
        items.append({
            "title": str(one.get("name") or "?"),
            "subtitle": "Off budget" if one.get("offbudget") else "",
            "worded": True,
            "value": money(symbol, balance),
            # No colour for a negative balance: a credit card is negative by nature, and Actual does not say which is one.
            "status": "ok",
        })
    secondary = [{"label": "On budget", "value": money(symbol, on)}]
    if options.get("offbudget", True):
        secondary.append({"label": "Off budget", "value": money(symbol, off)})
    return WidgetData(status="ok", items=items[:_limit(options)], secondary=secondary, meta={"empty": "No open account."})


def categories_of(month: dict[str, Any], symbol: str, options: dict[str, Any]) -> WidgetData:
    rows = []
    over = 0
    for one in _spending(month):
        budgeted = _cents(one.get("budgeted")) or 0
        spent = abs(_cents(one.get("spent")) or 0)
        balance = _cents(one.get("balance"))
        if balance is None:
            balance = budgeted - spent
        if not budgeted and not spent and not balance:
            # Nothing budgeted, nothing spent: a category that has nothing to say this month.
            continue
        if balance < 0:
            over += 1
        elif options.get("show") == "over":
            continue
        share = round(100.0 * spent / budgeted, 1) if budgeted > 0 else None
        rows.append({
            "title": str(one.get("name") or "?"),
            "subtitle": f"{money(symbol, balance)} left" if balance >= 0 else f"{money(symbol, -balance)} over",
            "progress": min(100.0, share) if share is not None else (100.0 if spent else None),
            # ⚠️ Not amber when spent to the last cent: rent budgeted at 950 and paid at 950 is the plan working.
            "status": "bad" if balance < 0 else "ok",
            "value": f"{money(symbol, spent)} / {money(symbol, budgeted)}",
        })
    rows.sort(key=lambda row: (row["status"] != "bad", -(row["progress"] or 0)))
    return WidgetData(
        status="bad" if over else "ok",
        items=rows[:_limit(options)],
        secondary=[{"label": "Overspent", "value": over}],
        meta={"empty": "Nothing is overspent." if options.get("show") == "over" else "No category has a budget this month."},
    )


ADAPTER = ActualBudgetAdapter()
