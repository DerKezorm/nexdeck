"""Ghostfolio, against the answers of a live Ghostfolio 3.69.0 (11.09.2026)."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AuthFailed, Context, Unreachable
from app.adapters.ghostfolio import GhostfolioAdapter

GF = "http://ghostfolio.example.com"
CONFIG = {"url": GF, "security_token": "made-up-security-token"}


def point(day: str, value: float, investment: float, change: float) -> dict[str, Any]:
    return {"date": day, "netPerformanceInPercentage": 0, "netPerformanceInPercentageWithCurrencyEffect": 0, "investmentValueWithCurrencyEffect": 0,
            "netPerformance": change, "netPerformanceWithCurrencyEffect": change, "netWorth": value, "totalCashInBaseCurrency": 0,
            "totalInvestment": investment, "totalInvestmentValueWithCurrencyEffect": investment, "value": value, "valueWithCurrencyEffect": value}


def performance(chart: list[dict[str, Any]], value: float, change: float, share: float, investment: float) -> dict[str, Any]:
    return {"chart": chart, "errors": [], "hasErrors": False, "dateOfFirstActivity": "2026-03-01T00:00:00.000Z", "performance": {
        "netPerformance": change, "netPerformanceWithCurrencyEffect": change, "totalInvestment": investment, "totalInvestmentValueWithCurrencyEffect": investment,
        "currentNetWorth": value, "currentValueInBaseCurrency": value, "netPerformancePercentage": share, "netPerformancePercentageWithCurrencyEffect": share}}


#: range=1d thirty seconds after the import: yesterday has a price.
TODAY = performance([point("2026-09-10", 9584.960097531899, 6900.56851142824, 0), point("2026-09-11", 9672.76089453533, 6900.56851142824, 85.24819880699579)],
                    9672.76089453533, 85.24819880699579, 0.012454998149407542, 6900.56851142824)
#: ⚠️ range=1d right after the import: yesterday stands at the amount invested, and "today" is the gain since March.
BEFORE_HISTORY = performance([point("2026-09-10", 6500, 6500, 0), point("2026-09-11", 9138.05, 6500, 2638.05)], 9138.05, 2638.05, 0.4058538461538462, 6500)
OVERALL = performance([point("2026-09-11", 9672.76089453533, 6900.56851142824, 2823.988189392879)], 9672.76089453533, 2823.988189392879, 0.6435130203713838, 6900.56851142824)
EMPTY = {"chart": [], "hasErrors": False, "performance": {"currentNetWorth": 0, "currentValueInBaseCurrency": 0, "netPerformance": 0, "netPerformancePercentage": 0,
                                                          "netPerformancePercentageWithCurrencyEffect": 0, "netPerformanceWithCurrencyEffect": 0, "totalInvestment": 0,
                                                          "totalInvestmentValueWithCurrencyEffect": 0}}


def holding(name: str, symbol: str, currency: str, worth: float, share: float) -> dict[str, Any]:
    return {"activitiesCount": 1, "marketPrice": 100.0, "tags": [], "allocationInPercentage": 0.3,
            "assetProfile": {"assetClass": "EQUITY", "assetSubClass": "STOCK", "countries": [], "currency": currency, "dataSource": "YAHOO", "holdings": [],
                             "isin": None, "name": name, "sectors": [], "symbol": symbol, "url": None},
            "dateOfFirstActivity": "2026-03-02T00:00:00.000Z", "dividend": 0, "investment": 1900, "netPerformancePercentWithCurrencyEffect": share,
            "netPerformanceWithCurrencyEffect": worth * share, "quantity": 10, "valueInBaseCurrency": worth}


#: range=1d, in the order they came: not by value.
HOLDINGS = {"holdings": [holding("Example Computers Inc.", "EXCMP", "USD", 3322.7, 0.017454121774637732),
                         holding("Example Software Corporation", "EXSFT", "USD", 2478.15, 0.006477941561973973),
                         holding("Example All-World ETF", "EXWLD", "EUR", 3871.910894535329, 0.0031864037917849982)]}
USER = {"activitiesCount": 3, "id": "made-up-user", "settings": {"currency": "USD", "baseCurrency": "USD", "dateRange": "max", "viewMode": "DEFAULT"}}


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


def _signin() -> respx.Route:
    return respx.post(f"{GF}/api/v1/auth/anonymous").mock(return_value=httpx.Response(201, json={"authToken": "made-up-jwt"}))


def _performance(today: dict[str, Any] = TODAY) -> respx.Route:
    return respx.get(f"{GF}/api/v2/portfolio/performance").mock(
        side_effect=lambda request: httpx.Response(200, json=today if request.url.params["range"] == "1d" else OVERALL))


def test_the_portfolio_value_and_todays_change() -> None:
    data = GhostfolioAdapter._portfolio(TODAY, OVERALL, "USD")
    assert data.status == "ok"
    assert data.primary == {"label": "Portfolio value", "value": "9,672.76", "unit": "USD"}
    assert data.secondary == [{"label": "Today", "value": "+85.25 (+1.25%)"}, {"label": "Since start", "value": "+64.35%"}]
    assert data.metrics == {"value": 9672.76089453533}


def test_right_after_an_import_today_is_not_known() -> None:
    data = GhostfolioAdapter._portfolio(BEFORE_HISTORY, OVERALL, "USD")
    assert data.status == "unknown"
    assert data.secondary[0] == {"label": "Today", "value": "?"}
    # Today's value itself was right: the prices of today were there, only yesterday's were missing.
    assert data.primary["value"] == "9,138.05"


def test_a_portfolio_without_a_chart_is_not_recorded_as_zero() -> None:
    """⚠️ Measured: seconds after an import, before any price, the portfolio stood at 0.00 without a chart."""
    data = GhostfolioAdapter._portfolio(EMPTY, EMPTY, "USD")
    assert data.status == "ok" and data.primary["value"] == "0.00"
    assert data.secondary == [{"label": "Today", "value": "+0.00 (+0.00%)"}, {"label": "Since start", "value": "+0.00%"}]
    assert data.metrics == {}
    assert GhostfolioAdapter._holdings({"holdings": []}, True, "USD", {}).meta["empty"] == "No holdings yet."


def test_the_holdings_biggest_first_with_todays_move() -> None:
    data = GhostfolioAdapter._holdings(HOLDINGS, True, "USD", {})
    assert [(row["title"], row["subtitle"], row["value"]) for row in data.items] == [
        ("Example All-World ETF", "EXWLD · 3,871.91 USD", "+0.32%"),
        ("Example Computers Inc.", "EXCMP · 3,322.70 USD", "+1.75%"),
        ("Example Software Corporation", "EXSFT · 2,478.15 USD", "+0.65%"),
    ]
    assert len(GhostfolioAdapter._holdings(HOLDINGS, True, "USD", {"limit": 2}).items) == 2
    unknown = GhostfolioAdapter._holdings(HOLDINGS, False, "USD", {})
    assert unknown.status == "unknown" and [row["value"] for row in unknown.items] == ["", "", ""]


@respx.mock
async def test_signing_in_with_the_security_token_and_keeping_the_jwt(ctx: Context) -> None:
    signin = _signin()
    user = respx.get(f"{GF}/api/v1/user").mock(return_value=httpx.Response(200, json=USER))
    perf = _performance()
    adapter = get_adapter("ghostfolio")
    data = await adapter.fetch("portfolio", CONFIG, {}, ctx)
    assert json.loads(signin.calls.last.request.content) == {"accessToken": "made-up-security-token"}
    assert user.calls.last.request.headers["Authorization"] == "Bearer made-up-jwt"
    assert sorted(call.request.url.params["range"] for call in perf.calls) == ["1d", "max"]
    assert data.primary["unit"] == "USD"
    holdings = respx.get(f"{GF}/api/v1/portfolio/holdings").mock(return_value=httpx.Response(200, json=HOLDINGS))
    rows = await adapter.fetch("holdings", CONFIG, {}, ctx)
    assert holdings.calls.last.request.url.params["range"] == "1d"
    assert signin.call_count == 1 and rows.items[0]["value"] == "+0.32%"


@respx.mock
async def test_the_holdings_card_asks_whether_yesterday_has_prices(ctx: Context) -> None:
    _signin()
    respx.get(f"{GF}/api/v1/user").mock(return_value=httpx.Response(200, json=USER))
    _performance(BEFORE_HISTORY)
    respx.get(f"{GF}/api/v1/portfolio/holdings").mock(return_value=httpx.Response(200, json=HOLDINGS))
    data = await get_adapter("ghostfolio").fetch("holdings", CONFIG, {}, ctx)
    assert data.status == "unknown" and data.items[0]["value"] == ""


@respx.mock
async def test_a_refused_jwt_is_renewed_once(ctx: Context) -> None:
    signin = _signin()
    answers = iter([httpx.Response(401, json={"message": "Unauthorized", "statusCode": 401}), httpx.Response(200, json=USER)])
    respx.get(f"{GF}/api/v1/user").mock(side_effect=lambda request: next(answers))
    assert await get_adapter("ghostfolio").test(CONFIG, ctx) == "Ghostfolio answers for an account with 3 activities."
    assert signin.call_count == 2


@respx.mock
async def test_a_jwt_refused_twice_is_a_refusal(ctx: Context) -> None:
    _signin()
    respx.get(f"{GF}/api/v1/user").mock(return_value=httpx.Response(401, json={"message": "Unauthorized", "statusCode": 401}))
    with pytest.raises(AuthFailed):
        await get_adapter("ghostfolio").fetch("portfolio", CONFIG, {}, ctx)


@respx.mock
async def test_a_wrong_security_token(ctx: Context) -> None:
    """⚠️ Measured: 403, where a missing or made-up JWT gets 401."""
    respx.post(f"{GF}/api/v1/auth/anonymous").mock(return_value=httpx.Response(403, json={"statusCode": 403, "message": "Forbidden"}))
    with pytest.raises(AuthFailed) as refused:
        await get_adapter("ghostfolio").fetch("holdings", CONFIG, {}, ctx)
    assert "security token" in refused.value.message


@respx.mock
async def test_an_unreachable_server(ctx: Context) -> None:
    respx.post(f"{GF}/api/v1/auth/anonymous").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(Unreachable):
        await get_adapter("ghostfolio").fetch("portfolio", CONFIG, {}, ctx)
