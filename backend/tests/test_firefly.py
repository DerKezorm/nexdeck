"""Firefly III, against the answers of a live Firefly III 6.6.6 (11.09.2026).

A small household was made there through the API: two accounts, a salary,
two expenses, two subscriptions (switched on, see the adapter) and a budget
of 400 with 42.50 spent.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context
from app.adapters.firefly import _period

FF = "http://firefly.example.com"
CONFIG = {"url": FF, "token": "not-a-real-token"}


def summary_entry(key: str, title: str, parsed: str, monetary: str, sub_title: str = "") -> dict[str, Any]:
    return {"key": key, "title": title, "monetary_value": monetary, "currency_id": "1", "currency_code": "EUR",
            "currency_symbol": "€", "currency_decimal_places": 2, "value_parsed": parsed, "local_icon": "balance-scale", "sub_title": sub_title}


#: Measured, with the two subscriptions switched on.
SUMMARY = {
    "balance-in-EUR": summary_entry("balance-in-EUR", "Balance (€)", "€2,917.51", "2917.510000000000", "-€82.49 + €3,000.00"),
    "spent-in-EUR": summary_entry("spent-in-EUR", "Spent (€)", "-€82.49", "-82.490000000000"),
    "earned-in-EUR": summary_entry("earned-in-EUR", "Earned (€)", "€3,000.00", "3000.000000000000"),
    "bills-paid-in-EUR": summary_entry("bills-paid-in-EUR", "Subscriptions paid (€)", "€39.99", "39.990000000000"),
    "bills-unpaid-in-EUR": summary_entry("bills-unpaid-in-EUR", "Subscriptions unpaid (€)", "-€90.00", "-90.000000000000"),
    "left-to-spend-in-EUR": {**summary_entry("left-to-spend-in-EUR", "Spent", "-€82.49", "-82.490000000000", "-€2.95"), "no_available_budgets": True},
    "net-worth-in-EUR": summary_entry("net-worth-in-EUR", "Net worth (€)", "€15,417.51", "15417.510000000000"),
}


def bill(name: str, low: str, high: str, *, paid: list[str], expected: str | None, pay_dates: list[str], active: bool = True) -> dict[str, Any]:
    return {"type": "bills", "id": name, "attributes": {
        "name": name, "amount_min": low, "amount_max": high, "active": active, "currency_code": "EUR", "currency_symbol": "€",
        "next_expected_match": expected, "pay_dates": pay_dates,
        "paid_dates": [{"transaction_group_id": "5", "transaction_journal_id": "5", "date": when, "subscription_id": "1",
                        "currency_code": "EUR", "currency_symbol": "€", "amount": low} for when in paid],
    }}


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


@respx.mock
async def test_the_overview_shows_firefly_s_own_amounts(ctx: Context) -> None:
    route = respx.get(f"{FF}/api/v1/summary/basic").mock(return_value=httpx.Response(200, json=SUMMARY))
    data = await get_adapter("firefly").fetch("overview", CONFIG, {"period": "month", "currency": ""}, ctx)
    sent = route.calls.last.request
    # ⚠️ Measured: without asking for JSON, a missing token is a redirect to the sign-in page.
    assert sent.headers["Accept"] == "application/json"
    assert sent.headers["Authorization"] == "Bearer not-a-real-token"
    start, end = _period({"period": "month"})
    assert dict(sent.url.params) == {"start": start, "end": end}
    assert data.primary == {"label": "Net worth", "value": "€15,417.51"}
    assert data.secondary == [{"label": "Balance", "value": "€2,917.51"}, {"label": "Spent", "value": "-€82.49"},
                              {"label": "Earned", "value": "€3,000.00"}, {"label": "Subscriptions due", "value": "-€90.00"},
                              {"label": "Left to spend", "value": "-€82.49"}]
    assert data.metrics == {"net_worth": 15417.51, "spent": 82.49}


@respx.mock
async def test_a_currency_firefly_does_not_report_is_named(ctx: Context) -> None:
    usd = {key.replace("EUR", "USD"): {**value, "value_parsed": value["value_parsed"].replace("€", "$")} for key, value in SUMMARY.items()}
    respx.get(f"{FF}/api/v1/summary/basic").mock(return_value=httpx.Response(200, json={**SUMMARY, **usd}))
    chosen = await get_adapter("firefly").fetch("overview", CONFIG, {"currency": "usd"}, ctx)
    assert chosen.primary == {"label": "Net worth", "value": "$15,417.51"}
    with pytest.raises(AdapterError) as missing:
        await get_adapter("firefly").fetch("overview", CONFIG, {"currency": "CHF"}, ctx)
    assert missing.value.code == "no_such_currency" and "EUR" in missing.value.hint


def test_the_period_covers_the_whole_month_or_year() -> None:
    start, end = _period({"period": "month"})
    assert start.endswith("-01") and end[8:] in {"28", "29", "30", "31"} and start[:7] == end[:7]
    year_start, year_end = _period({"period": "year"})
    assert year_start.endswith("-01-01") and year_end.endswith("-12-31")


@respx.mock
async def test_subscriptions_due_first_then_upcoming_then_paid(ctx: Context) -> None:
    start, _end = _period({"period": "month"})
    respx.get(f"{FF}/api/v1/bills").mock(return_value=httpx.Response(200, json={"data": [
        bill("Internet", "39.99", "39.99", paid=[f"{start}T00:00:00+02:00"], expected=None, pay_dates=["2099-10-01T00:00:00+02:00"]),
        bill("Electricity", "85.00", "95.00", paid=[], expected=f"{start}T00:00:00+02:00", pay_dates=[f"{start}T00:00:00+02:00"]),
        # Far enough ahead that the test does not change its mind on the last day of a month.
        bill("Streaming", "13.99", "13.99", paid=[], expected=None, pay_dates=["2099-12-01T00:00:00+01:00"]),
        bill("Old gym", "30.00", "30.00", paid=[], expected=None, pay_dates=[], active=False),
    ]}))
    data = await get_adapter("firefly").fetch("subscriptions", CONFIG, {"limit": 8, "period": "month"}, ctx)
    assert [row["title"] for row in data.items] == ["Electricity", "Internet", "Streaming"]
    by_name = {row["title"]: row for row in data.items}
    assert by_name["Streaming"]["subtitle"] == "Next · 2099-12-01"
    assert "Old gym" not in by_name
    assert (by_name["Electricity"]["subtitle"], by_name["Electricity"]["status"], by_name["Electricity"]["value"]) == (f"Due · {start}", "warn", "€85.00 - €95.00")
    assert (by_name["Internet"]["subtitle"], by_name["Internet"]["value"]) == (f"Paid · {start}", "€39.99")
    assert data.secondary == [{"label": "Due", "value": 1}] and data.status == "warn"


@respx.mock
async def test_budgets_as_bars_the_fullest_first(ctx: Context) -> None:
    respx.get(f"{FF}/api/v1/budgets").mock(return_value=httpx.Response(200, json={"data": [
        {"type": "budgets", "id": "1", "attributes": {"name": "Food", "active": True}},
        {"type": "budgets", "id": "2", "attributes": {"name": "Hardware", "active": True}},
    ]}))
    respx.get(f"{FF}/api/v1/budget-limits").mock(return_value=httpx.Response(200, json={"data": [
        {"type": "budget_limits", "id": "1", "attributes": {"budget_id": "1", "amount": "400.00", "currency_symbol": "€",
                                                            "spent": [{"sum": "-42.500000000000", "currency_code": "EUR"}]}},
        {"type": "budget_limits", "id": "2", "attributes": {"budget_id": "2", "amount": "100.00", "currency_symbol": "€",
                                                            "spent": [{"sum": "-119.99", "currency_code": "EUR"}]}},
    ]}))
    data = await get_adapter("firefly").fetch("budgets", CONFIG, {"limit": 8}, ctx)
    assert [(row["title"], row["progress"], row["status"], row["value"]) for row in data.items] == [
        ("Hardware", 100.0, "bad", "€119.99 / €100.00"),
        ("Food", 10.6, "ok", "€42.50 / €400.00"),
    ]
    assert data.secondary == [{"label": "Over budget", "value": 1}] and data.status == "bad"


@respx.mock
async def test_the_connection_test_and_a_wrong_token(ctx: Context) -> None:
    respx.get(f"{FF}/api/v1/about").mock(return_value=httpx.Response(200, json={"data": {"version": "6.6.6", "api_version": "6.6.6", "driver": "mysql"}}))
    assert await get_adapter("firefly").test(CONFIG, ctx) == "Firefly III 6.6.6 answers."
    respx.get(f"{FF}/api/v1/about").mock(return_value=httpx.Response(401, json={"message": "Unauthenticated.", "exception": "AuthenticationException"}))
    with pytest.raises(AuthFailed):
        await get_adapter("firefly").test(CONFIG, ctx)


@respx.mock
async def test_a_sign_in_redirect_is_named_as_such(ctx: Context) -> None:
    respx.get(f"{FF}/api/v1/bills").mock(return_value=httpx.Response(302, headers={"Location": f"{FF}/login"}))
    with pytest.raises(AdapterError) as redirected:
        await get_adapter("firefly").fetch("subscriptions", CONFIG, {}, ctx)
    assert redirected.value.code == "not_signed_in"
