"""Wallos, against the answers of a live Wallos v5.7.1 (11.09.2026)."""

from __future__ import annotations

from datetime import date
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context, Unreachable
from app.adapters.wallos import WallosAdapter

WL = "http://wallos.example.com"
CONFIG = {"url": WL, "api_key": "made-up-key"}
TODAY = date(2026, 9, 11)
NOT_CONVERTED = "You are using multiple currencies, but the exchange rates have not been updated yet. Please check your Fixer API Key."


def sub(identifier: int, name: str, price: float, currency: int, next_payment: str, cycle: int = 3) -> dict[str, Any]:
    """A subscription as get_subscriptions hands it out."""
    return {"id": identifier, "name": name, "logo": "", "price": price, "currency_id": currency, "next_payment": next_payment,
            "cycle": cycle, "frequency": 1, "notes": "", "payment_method_id": 1, "payer_user_id": None, "category_id": 1,
            "notify": 0, "url": "", "inactive": 0, "notify_days_before": None, "user_id": 1, "cancellation_date": None,
            "replacement_subscription_id": None, "start_date": "2026-07-13", "auto_renew": 1, "logo_text_color": None, "logo_variant": None,
            "category_name": "No category", "payer_user_name": "Unknown member", "payment_method_name": "PayPal"}


#: state=0, sort=next_payment: the inactive one is not there, the dollar one is.
ACTIVE = [sub(1, "Music Streaming", 10.99, 1, "2026-09-14"), sub(2, "Cloud Storage", 2.99, 1, "2026-09-23"),
          sub(5, "Video Service", 15.49, 2, "2026-10-01"), sub(3, "Password Manager", 36, 1, "2026-10-21", cycle=4)]
CURRENCIES = {"success": True, "title": "currencies", "main_currency": 1, "currencies": [
    {"id": 1, "name": "Euro", "symbol": "€", "code": "EUR", "rate": "1", "in_use": True},
    {"id": 2, "name": "US Dollar", "symbol": "$", "code": "USD", "rate": "1", "in_use": True}]}


def cost(title: str, amount: str, notes: list[str]) -> dict[str, Any]:
    return {"success": True, "title": title, "monthly_cost": amount, "localized_monthly_cost": f"€{amount}",
            "currency_code": "EUR", "currency_symbol": "€", "notes": notes}


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


def _form(request: httpx.Request) -> dict[str, str]:
    return {name: values[0] for name, values in parse_qs(request.content.decode()).items()}


def test_the_next_payments_with_their_price() -> None:
    soon = [sub(7, "Newspaper", 4.5, 1, "2026-09-11"), sub(8, "Phone", 20, 1, "2026-09-12", cycle=2)]
    data = WallosAdapter._upcoming(list(reversed(ACTIVE)) + soon, CURRENCIES, TODAY, {})
    assert [(row["title"], row["subtitle"], row["status"], row["value"]) for row in data.items] == [
        ("Newspaper", "Today · Monthly", "warn", "€4.50"),
        ("Phone", "Tomorrow · Weekly", "ok", "€20.00"),
        ("Music Streaming", "2026-09-14 · Monthly", "ok", "€10.99"),
        ("Cloud Storage", "2026-09-23 · Monthly", "ok", "€2.99"),
        ("Video Service", "2026-10-01 · Monthly", "ok", "$15.49"),
        ("Password Manager", "2026-10-21 · Yearly", "ok", "€36.00"),
    ]
    assert len(WallosAdapter._upcoming(ACTIVE, CURRENCIES, TODAY, {"limit": 2}).items) == 2


@respx.mock
async def test_the_key_goes_in_the_body_not_the_address(ctx: Context) -> None:
    """⚠️ Measured: a key in a header is "Missing parameters"; in a POST body it works."""
    subscriptions = respx.post(f"{WL}/api/subscriptions/get_subscriptions.php").mock(
        return_value=httpx.Response(200, json={"success": True, "title": "subscriptions", "subscriptions": ACTIVE, "notes": []}))
    currencies = respx.post(f"{WL}/api/currencies/get_currencies.php").mock(return_value=httpx.Response(200, json=CURRENCIES))
    adapter = get_adapter("wallos")
    data = await adapter.fetch("upcoming", CONFIG, {}, ctx)
    request = subscriptions.calls.last.request
    assert str(request.url) == f"{WL}/api/subscriptions/get_subscriptions.php"
    assert _form(request) == {"api_key": "made-up-key", "state": "0", "sort": "next_payment"}
    assert [row["title"] for row in data.items] == ["Music Streaming", "Cloud Storage", "Video Service", "Password Manager"]
    # The currencies are kept for an hour.
    await adapter.fetch("upcoming", CONFIG, {}, ctx)
    assert currencies.call_count == 1 and subscriptions.call_count == 2


def test_this_month_and_the_next() -> None:
    euros = [one for one in ACTIVE if one["currency_id"] == 1]
    data = WallosAdapter._month(cost("September 2026", "13.98", []), cost("October 2026", "49.98", []), euros, 1)
    assert data.status == "ok"
    assert data.primary == {"label": "This month", "value": "€13.98"}
    assert data.secondary == [{"label": "Next month", "value": "€49.98"}, {"label": "Active", "value": 3}]
    assert data.metrics == {"month_cost": 13.98}


def test_a_sum_across_currencies_without_rates_is_not_recorded() -> None:
    """⚠️ Measured: 15.49 USD went into the September sum as 15.49 EUR."""
    data = WallosAdapter._month(cost("September 2026", "29.47", [NOT_CONVERTED]), cost("October 2026", "65.47", [NOT_CONVERTED]), ACTIVE, 1)
    assert data.status == "warn"
    assert data.secondary == [{"label": "Next month", "value": "€65.47"}, {"label": "Not converted", "value": 1}]
    assert data.metrics == {}


@respx.mock
async def test_the_month_card_asks_for_this_month_and_the_next(ctx: Context) -> None:
    respx.post(f"{WL}/api/subscriptions/get_subscriptions.php").mock(
        return_value=httpx.Response(200, json={"success": True, "title": "subscriptions", "subscriptions": ACTIVE, "notes": []}))
    respx.post(f"{WL}/api/currencies/get_currencies.php").mock(return_value=httpx.Response(200, json=CURRENCIES))
    months = respx.post(f"{WL}/api/subscriptions/get_monthly_cost.php").mock(
        side_effect=lambda request: httpx.Response(200, json=cost(_form(request)["month"], "29.47", [NOT_CONVERTED])))
    data = await get_adapter("wallos").fetch("month", CONFIG, {}, ctx)
    asked = [(_form(call.request)["month"], _form(call.request)["year"]) for call in months.calls]
    assert len(asked) == 2 and asked[0] != asked[1]
    assert data.primary["label"] == "This month" and data.status == "warn"


@respx.mock
async def test_a_wrong_key_comes_back_as_http_200(ctx: Context) -> None:
    """⚠️ Measured: no key and a made-up key both get 200 with success false."""
    route = respx.post(f"{WL}/api/subscriptions/get_subscriptions.php")
    for title in ("Invalid API key", "Missing parameters"):
        route.mock(return_value=httpx.Response(200, json={"success": False, "title": title}))
        with pytest.raises(AuthFailed):
            await get_adapter("wallos").fetch("upcoming", CONFIG, {}, ctx)


@respx.mock
async def test_an_answer_that_is_not_wallos(ctx: Context) -> None:
    respx.post(f"{WL}/api/subscriptions/get_subscriptions.php").mock(return_value=httpx.Response(200, json={"status": "ok"}))
    with pytest.raises(AdapterError) as other:
        await get_adapter("wallos").fetch("upcoming", CONFIG, {}, ctx)
    assert other.value.code == "not_wallos"


@respx.mock
async def test_an_unreachable_server(ctx: Context) -> None:
    respx.post(f"{WL}/api/subscriptions/get_subscriptions.php").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(Unreachable):
        await get_adapter("wallos").fetch("month", CONFIG, {}, ctx)


@respx.mock
async def test_the_connection_test(ctx: Context) -> None:
    respx.post(f"{WL}/api/status/version.php").mock(return_value=httpx.Response(200, json={
        "success": True, "title": "version", "version": "v5.7.1", "version_number": "5.7.1", "notes": []}))
    respx.post(f"{WL}/api/subscriptions/get_subscriptions.php").mock(
        return_value=httpx.Response(200, json={"success": True, "title": "subscriptions", "subscriptions": ACTIVE, "notes": []}))
    assert await get_adapter("wallos").test(CONFIG, ctx) == "Wallos v5.7.1 answers with 4 active subscriptions."
