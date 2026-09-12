"""Tandoor Recipes, against the answers of a live Tandoor 2.6.15 (11.09.2026)."""

from __future__ import annotations

import json
from datetime import date
from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context, Unreachable
from app.adapters.tandoor import TandoorAdapter

TD = "http://tandoor.example.com"
CONFIG = {"url": TD, "token": "tda_made_up_token"}
TODAY = date(2026, 9, 11)
USER = {"id": 1, "username": "cook", "first_name": "", "last_name": "", "display_name": "cook", "is_staff": False, "is_superuser": False, "is_active": True}
DINNER = {"id": 2, "name": "Dinner", "order": 2, "time": "18:30:00", "color": None, "created_by": 1}
LUNCH = {"id": 1, "name": "Lunch", "order": 1, "time": "12:00:00", "color": None, "created_by": 1}
FORBIDDEN = {"detail": "Authentication credentials were not provided."}


def recipe(identifier: int, name: str) -> dict[str, Any]:
    return {"id": identifier, "name": name, "description": None, "image": None, "keywords": [], "working_time": 0, "waiting_time": 0,
            "created_by": USER, "internal": False, "private": False, "servings": 2, "servings_text": "", "rating": None, "last_cooked": None, "new": True}


def plan(identifier: int, day: str, meal: dict[str, Any], dish: dict[str, Any] | None, title: str = "") -> dict[str, Any]:
    """⚠️ from_date is the day with the meal type's time, as measured."""
    return {"id": identifier, "title": title, "recipe": dish, "servings": 2.0, "note": "", "note_markdown": "",
            "from_date": f"{day}T{meal['time']}Z", "to_date": f"{day}T{meal['time']}Z", "meal_type": meal, "created_by": 1,
            "meal_type_name": meal["name"], "shopping": False}


#: As asked for from today to two days ahead, which is also the order they came in.
PLANS = [plan(2, "2026-09-11", DINNER, recipe(1, "Tomato Soup")), plan(3, "2026-09-12", LUNCH, None, "Leftovers"),
         plan(4, "2026-09-13", DINNER, recipe(2, "Bean Chili"))]


def entry(identifier: int, food: str, amount: float, unit: str | None, checked: bool, category: str | None = None) -> dict[str, Any]:
    return {"id": identifier, "list_recipe": None, "shopping_lists": [],
            "food": {"id": identifier + 3, "name": food, "plural_name": None, "shopping_lists": [],
                     "supermarket_category": {"id": 1, "name": category} if category else None},
            "unit": {"id": 2, "name": unit, "plural_name": unit} if unit else None, "amount": amount, "order": 0, "checked": checked,
            "ingredient": None, "list_recipe_data": None, "created_by": USER, "created_at": "2026-09-11T20:48:49.179648Z",
            "updated_at": "2026-09-11T20:48:49.179656Z", "completed_at": "2026-09-11T20:48:49.232389Z" if checked else None, "delay_until": None}


#: ⚠️ Bread was ticked off a minute before and still came back.
ENTRIES = [entry(1, "Milk", 1.0, "l", False, "Dairy"), entry(2, "Bread", 1.0, None, True), entry(3, "Eggs", 6.0, None, False)]


def page(results: list[dict[str, Any]]) -> dict[str, Any]:
    return {"count": len(results), "next": None, "previous": None, "timestamp": "2026-09-11T20:49:24.079393+00:00", "results": results}


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


def test_the_meal_plan_day_by_day() -> None:
    data = TandoorAdapter._plan(list(reversed(PLANS)), TODAY, TD)
    assert [(row["title"], row["subtitle"], row["value"], row.get("url")) for row in data.items] == [
        ("Tomato Soup", "Today · Dinner", "18:30", f"{TD}/recipe/1"),
        ("Leftovers", "Tomorrow · Lunch", "12:00", None),
        ("Bean Chili", "2026-09-13 · Dinner", "18:30", f"{TD}/recipe/2"),
    ]
    assert TandoorAdapter._plan([], TODAY, TD).meta["empty"] == "Nothing planned yet."


def test_the_time_on_the_right_is_the_meal_types_own() -> None:
    """from_date was only measured on a server in UTC, where both times agree; the card keeps to the meal type."""
    shifted = {**PLANS[0], "from_date": "2026-09-11T16:30:00Z", "to_date": "2026-09-11T16:30:00Z"}
    assert TandoorAdapter._plan([shifted], TODAY, TD).items[0]["value"] == "18:30"


@respx.mock
async def test_the_plan_is_asked_for_in_plain_dates(ctx: Context) -> None:
    route = respx.get(f"{TD}/api/meal-plan/").mock(return_value=httpx.Response(200, json=page(PLANS)))
    data = await get_adapter("tandoor").fetch("plan", CONFIG, {"days": 3}, ctx)
    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer tda_made_up_token"
    first, last = date.fromisoformat(request.url.params["from_date"]), date.fromisoformat(request.url.params["to_date"])
    assert (last - first).days == 2 and request.url.params["page_size"] == "100"
    assert len(data.items) == 3


def test_the_shopping_list_leaves_out_what_was_ticked_off() -> None:
    data = TandoorAdapter._shopping(ENTRIES, {})
    assert [(row["title"], row["subtitle"]) for row in data.items] == [("Milk", "1 l · Dairy"), ("Eggs", "6")]
    tick = data.items[0]["actions"][0]
    assert (tick.id, tick.params, tick.icon) == ("check", {"id": "1"}, "check")
    assert data.secondary == [{"label": "To buy", "value": 2}] and data.metrics == {"to_buy": 2.0}
    assert data.meta["actions_visible"] is True
    assert TandoorAdapter._shopping(ENTRIES, {"limit": 1}).secondary == [{"label": "To buy", "value": 2}]


@respx.mock
async def test_the_shopping_card_reads_the_entries(ctx: Context) -> None:
    route = respx.get(f"{TD}/api/shopping-list-entry/").mock(return_value=httpx.Response(200, json=page(ENTRIES)))
    data = await get_adapter("tandoor").fetch("shopping", CONFIG, {}, ctx)
    assert route.calls.last.request.url.params["page_size"] == "200"
    assert [row["title"] for row in data.items] == ["Milk", "Eggs"]


@respx.mock
async def test_ticking_an_entry_off(ctx: Context) -> None:
    tick = respx.patch(f"{TD}/api/shopping-list-entry/3/").mock(return_value=httpx.Response(200, json={**ENTRIES[2], "checked": True}))
    assert await get_adapter("tandoor").action("shopping", "check", {"id": "3"}, CONFIG, {}, ctx) == "Ticked off."
    assert json.loads(tick.calls.last.request.content) == {"checked": True}
    assert tick.calls.last.request.headers["Authorization"] == "Bearer tda_made_up_token"


@respx.mock
async def test_ticking_off_that_does_not_happen(ctx: Context) -> None:
    adapter = get_adapter("tandoor")
    # ⚠️ Measured: a token with the scope read gets exactly this.
    respx.patch(f"{TD}/api/shopping-list-entry/1/").mock(return_value=httpx.Response(403, json={"detail": "You do not have permission to perform this action."}))
    with pytest.raises(AuthFailed) as refused:
        await adapter.action("shopping", "check", {"id": "1"}, CONFIG, {}, ctx)
    assert "read write" in refused.value.message
    respx.patch(f"{TD}/api/shopping-list-entry/99/").mock(return_value=httpx.Response(404, json={"detail": "No ShoppingListEntry matches the given query."}))
    with pytest.raises(AdapterError) as gone:
        await adapter.action("shopping", "check", {"id": "99"}, CONFIG, {}, ctx)
    assert gone.value.code == "action_failed"
    respx.patch(f"{TD}/api/shopping-list-entry/2/").mock(return_value=httpx.Response(200, json={**ENTRIES[2], "checked": False}))
    with pytest.raises(AdapterError) as unchanged:
        await adapter.action("shopping", "check", {"id": "2"}, CONFIG, {}, ctx)
    assert unchanged.value.code == "action_failed"
    with pytest.raises(AdapterError) as unknown:
        await adapter.action("shopping", "delete", {"id": "3"}, CONFIG, {}, ctx)
    assert unknown.value.code == "no_such_action"
    with pytest.raises(AdapterError) as walked:
        await adapter.action("shopping", "check", {"id": "../meal-plan/1"}, CONFIG, {}, ctx)
    assert walked.value.code == "bad_param"


@respx.mock
async def test_a_rejected_token(ctx: Context) -> None:
    """⚠️ Measured: a missing and a made-up token both get 403."""
    respx.get(f"{TD}/api/shopping-list-entry/").mock(return_value=httpx.Response(403, json=FORBIDDEN))
    with pytest.raises(AuthFailed):
        await get_adapter("tandoor").fetch("shopping", CONFIG, {}, ctx)


@respx.mock
async def test_an_unreachable_server(ctx: Context) -> None:
    respx.get(f"{TD}/api/meal-plan/").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(Unreachable):
        await get_adapter("tandoor").fetch("plan", CONFIG, {}, ctx)


@respx.mock
async def test_the_connection_test(ctx: Context) -> None:
    """⚠️ The server settings answer without a token, so the test reads the shopping list as well."""
    respx.get(f"{TD}/api/server-settings/current/").mock(return_value=httpx.Response(200, json={"version": "2.6.15", "hosted": False, "debug": False}))
    respx.get(f"{TD}/api/shopping-list-entry/").mock(return_value=httpx.Response(200, json=page(ENTRIES)))
    assert await get_adapter("tandoor").test(CONFIG, ctx) == "Tandoor 2.6.15 answers with 2 entries to buy."
