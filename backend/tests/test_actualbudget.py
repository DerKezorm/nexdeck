"""Actual 26.10.0 behind actual-http-api 26.10.0, measured on 05.10.2026 on docker-dev with a made-up household
budget: the shapes are the measured ones, names and amounts made up."""

from __future__ import annotations

import httpx
import pytest
import respx

from app.adapters import actualbudget as module
from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context, outbound_client

SYNC = "b4c1894d-36f8-45ec-ba10-70780dbd38a3"
CONFIG = {"url": "http://actual-http-api:5007", "api_key": "example-key", "sync_id": SYNC, "currency": "€"}
BASE = f"http://actual-http-api:5007/v1/budgets/{SYNC}"

ACCOUNTS = [
    {"id": "8763", "name": "Checking", "offbudget": False, "closed": False, "account_group_id": None,
     "clearedBalance": 0, "unclearedBalance": 413041, "workingBalance": 413041},
    {"id": "cae0", "name": "Credit card", "offbudget": False, "closed": False, "account_group_id": None,
     "clearedBalance": 0, "unclearedBalance": -12840, "workingBalance": -12840},
    {"id": "ea37", "name": "Old account", "offbudget": False, "closed": True, "account_group_id": None,
     "clearedBalance": 0, "unclearedBalance": 0, "workingBalance": 0},
    {"id": "1fe7", "name": "Savings", "offbudget": True, "closed": False, "account_group_id": None,
     "clearedBalance": 0, "unclearedBalance": 800000, "workingBalance": 800000},
]


def category(name: str, budgeted: int, spent: int, balance: int) -> dict:
    return {"id": name, "name": name, "is_income": False, "hidden": False, "group_id": "g",
            "budgeted": budgeted, "spent": spent, "balance": balance, "carryover": False}


MONTH = {
    "month": "2026-10", "incomeAvailable": 525000, "lastMonthOverspent": 0, "forNextMonth": 0,
    "totalBudgeted": -164000, "toBudget": 361000, "fromLastMonth": 0, "totalIncome": 525000,
    "totalSpent": -124799, "totalBalance": 39201,
    "categoryGroups": [
        {"id": "home", "name": "Home", "is_income": False, "hidden": False, "budgeted": 103000, "spent": -103000, "balance": 0,
         "categories": [category("Rent", 95000, -95000, 0), category("Power", 8000, -8000, 0)]},
        {"id": "fun", "name": "Fun", "is_income": False, "hidden": False, "budgeted": 9000, "spent": -10289, "balance": -1289,
         "categories": [category("Streaming", 3000, -1299, 1701), category("Hobbies", 6000, -8990, -2990)]},
        {"id": "food", "name": "Food", "is_income": False, "hidden": False, "budgeted": 52000, "spent": -11510, "balance": 40490,
         "categories": [category("Groceries", 40000, -7660, 32340), category("General", 0, 0, 0),
                        {**category("Old hobby", 1000, 0, 1000), "hidden": True}]},
        {"id": "income", "name": "Income", "is_income": True, "hidden": False, "received": 525000,
         "categories": [{"id": "salary", "name": "Salary", "is_income": True, "hidden": False, "group_id": "income", "received": 280000}]},
    ],
}


@pytest.fixture
def ctx() -> Context:
    return Context(outbound_client(guard=False), integration_id=1, widget_id=1, cache={})


@pytest.fixture(autouse=True)
def in_october(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(module, "_this_month", lambda: "2026-10")


@respx.mock
async def test_the_month_leads_with_what_is_left_to_budget_and_names_the_overspent(ctx: Context) -> None:
    route = respx.get(f"{BASE}/months/2026-10").mock(return_value=httpx.Response(200, json={"data": MONTH}))
    data = await get_adapter("actualbudget").fetch("month", CONFIG, {}, ctx)
    assert data.primary == {"label": "To budget", "value": "€3,610.00"}
    assert {row["label"]: row["value"] for row in data.secondary} == {
        "Budgeted": "€1,640.00", "Spent": "€1,247.99", "Left": "€392.01", "Overspent": 1}
    assert data.status == "warn" and data.meta["status_reason"] == "1 category is overspent: Hobbies."
    assert data.metrics == {"spent": 1247.99}
    request = route.calls.last.request
    assert request.headers["x-api-key"] == "example-key" and "example-key" not in str(request.url)
    assert "budget-encryption-password" not in request.headers


@respx.mock
async def test_more_budgeted_than_there_is_turns_the_month_red(ctx: Context) -> None:
    respx.get(f"{BASE}/months/2026-10").mock(return_value=httpx.Response(200, json={"data": {**MONTH, "toBudget": -5000}}))
    data = await get_adapter("actualbudget").fetch("month", CONFIG, {}, ctx)
    assert data.status == "bad" and data.primary["value"] == "-€50.00"
    assert data.meta["status_reason"].startswith("€50.00 more is budgeted than there is.")


@respx.mock
async def test_a_tracking_budget_without_to_budget_leads_with_the_spending(ctx: Context) -> None:
    tracking = {key: value for key, value in MONTH.items() if key != "toBudget"}
    respx.get(f"{BASE}/months/2026-10").mock(return_value=httpx.Response(200, json={"data": tracking}))
    data = await get_adapter("actualbudget").fetch("month", CONFIG, {}, ctx)
    assert data.primary == {"label": "Spent", "value": "€1,247.99"}


@respx.mock
async def test_the_accounts_leave_the_closed_out_and_sum_on_and_off_budget(ctx: Context) -> None:
    route = respx.get(f"{BASE}/accounts").mock(return_value=httpx.Response(200, json={"data": ACCOUNTS}))
    data = await get_adapter("actualbudget").fetch("accounts", CONFIG, {}, ctx)
    assert [(row["title"], row["subtitle"], row["value"]) for row in data.items] == [
        ("Checking", "", "€4,130.41"), ("Credit card", "", "-€128.40"), ("Savings", "Off budget", "€8,000.00")]
    assert data.secondary == [{"label": "On budget", "value": "€4,002.01"}, {"label": "Off budget", "value": "€8,000.00"}]
    assert route.calls.last.request.url.params["include_balances"] == "true"
    only_on = await get_adapter("actualbudget").fetch("accounts", CONFIG, {"offbudget": False}, ctx)
    assert [row["title"] for row in only_on.items] == ["Checking", "Credit card"]
    assert only_on.secondary == [{"label": "On budget", "value": "€4,002.01"}]


@respx.mock
async def test_the_categories_come_overspent_first_and_leave_out_what_has_nothing_to_say(ctx: Context) -> None:
    respx.get(f"{BASE}/months/2026-10").mock(return_value=httpx.Response(200, json={"data": MONTH}))
    data = await get_adapter("actualbudget").fetch("categories", CONFIG, {}, ctx)
    rows = [(row["title"], row["subtitle"], row["value"], row["status"]) for row in data.items]
    assert rows[0] == ("Hobbies", "€29.90 over", "€89.90 / €60.00", "bad")
    assert ("Rent", "€0.00 left", "€950.00 / €950.00", "ok") in rows, "spent to the last cent is the plan working"
    assert {row[0] for row in rows} == {"Hobbies", "Rent", "Power", "Streaming", "Groceries"}, "no income, no hidden, no empty"
    assert data.status == "bad"
    over = await get_adapter("actualbudget").fetch("categories", CONFIG, {"show": "over"}, ctx)
    assert [row["title"] for row in over.items] == ["Hobbies"]


@respx.mock
async def test_a_wrong_key_an_unknown_budget_and_a_wrong_address_are_said_plainly(ctx: Context) -> None:
    respx.get(f"{BASE}/accounts").mock(return_value=httpx.Response(403, json={"error": "Forbidden"}))
    with pytest.raises(AuthFailed, match="refused the API key"):
        await get_adapter("actualbudget").test(CONFIG, ctx)
    respx.get(f"{BASE}/accounts").mock(return_value=httpx.Response(404, json={
        "error": f'Budget "{SYNC}" not found. Check the sync id of your budget in the Advanced section of the settings page.'}))
    with pytest.raises(AdapterError, match="no budget with this sync ID"):
        await get_adapter("actualbudget").test(CONFIG, ctx)
    respx.get(f"{BASE}/accounts").mock(return_value=httpx.Response(200, json=[{"looks": "like something else"}]))
    with pytest.raises(AdapterError, match="not as actual-http-api does"):
        await get_adapter("actualbudget").test(CONFIG, ctx)


@respx.mock
async def test_an_encrypted_budget_sends_its_password_in_the_header(ctx: Context) -> None:
    route = respx.get(f"{BASE}/accounts").mock(return_value=httpx.Response(200, json={"data": ACCOUNTS}))
    assert await get_adapter("actualbudget").test({**CONFIG, "encryption_password": "example-secret"}, ctx) == (
        "actual-http-api answers; the budget has 3 open account(s).")
    assert route.calls.last.request.headers["budget-encryption-password"] == "example-secret"


def test_amounts_are_whole_cents() -> None:
    assert module.money("€", 413041) == "€4,130.41"
    assert module.money("", -1299) == "-12.99"
    assert module.money("$", None) == "?"
