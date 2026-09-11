"""Mealie, against the answers of a live Mealie 3.25.1 (11.09.2026)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context

ME = "http://mealie.example.com"
CONFIG = {"url": ME, "token": "made-up-token"}
TODAY = datetime.now(UTC).date()


def page(items: list[dict[str, Any]], total: int | None = None) -> dict[str, Any]:
    return {"page": 1, "per_page": 50, "total": len(items) if total is None else total, "total_pages": 1, "next": None, "previous": None, "items": items}


def plan(day_offset: int, meal: str, **extra: Any) -> dict[str, Any]:
    return {"date": (TODAY + timedelta(days=day_offset)).isoformat(), "entryType": meal, "title": "", "text": "", "recipeId": None,
            "id": day_offset + 1, "groupId": "made-up-group", "userId": "made-up-user", "householdId": "made-up-household", **extra}


def item(display: str, checked: bool, list_id: str = "l1") -> dict[str, Any]:
    return {"quantity": 1.0, "unit": None, "food": None, "note": display, "display": display, "checked": checked, "shoppingListId": list_id}


LISTS = page([{"id": "l1", "name": "Weekly shop"}, {"id": "l2", "name": "Hardware store"}])


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


@respx.mock
async def test_the_plan_is_sorted_by_day_and_meal_and_links_recipes(ctx: Context) -> None:
    """⚠️ Measured: the range comes in the order it was entered, tomorrow before today."""
    route = respx.get(f"{ME}/api/households/mealplans").mock(return_value=httpx.Response(200, json=page([
        plan(1, "lunch", title="Leftovers", text="Whatever is in the fridge"),
        plan(0, "dinner", recipeId="r1", recipe={"id": "r1", "name": "Tomato soup", "slug": "tomato-soup"}),
        plan(0, "breakfast", title="Porridge"),
        plan(3, "dinner", recipe={"name": "Bean chili", "slug": "bean-chili"}),
    ])))
    respx.get(f"{ME}/api/users/self").mock(return_value=httpx.Response(200, json={"username": "someone", "groupSlug": "home"}))
    data = await get_adapter("mealie").fetch("plan", CONFIG, {"days": 7}, ctx)
    assert dict(route.calls.last.request.url.params) == {"start_date": TODAY.isoformat(), "end_date": (TODAY + timedelta(days=6)).isoformat(), "perPage": "100"}
    assert [(row["title"], row["subtitle"]) for row in data.items] == [
        ("Porridge", "Today · Breakfast"), ("Tomato soup", "Today · Dinner"), ("Leftovers", "Tomorrow · Lunch"),
        ("Bean chili", f"{(TODAY + timedelta(days=3)).isoformat()} · Dinner")]
    assert data.items[1]["url"] == f"{ME}/g/home/r/tomato-soup" and "url" not in data.items[0]


@respx.mock
async def test_the_shopping_list_leaves_out_what_is_ticked_off(ctx: Context) -> None:
    respx.get(f"{ME}/api/households/shopping/items").mock(return_value=httpx.Response(200, json=page([
        item("1 Bread", True), item("6 Tomatoes", False), item("2 Milk", False), item("Wall plugs", False, "l2")])))
    respx.get(f"{ME}/api/households/shopping/lists").mock(return_value=httpx.Response(200, json=LISTS))
    everything = await get_adapter("mealie").fetch("shopping", CONFIG, {"limit": 12}, ctx)
    assert [(row["title"], row["subtitle"]) for row in everything.items] == [("6 Tomatoes", "Weekly shop"), ("2 Milk", "Weekly shop"), ("Wall plugs", "Hardware store")]
    assert everything.secondary == [{"label": "To buy", "value": 3}]
    one = await get_adapter("mealie").fetch("shopping", CONFIG, {"list": "weekly SHOP", "limit": 12}, ctx)
    assert [(row["title"], row["subtitle"]) for row in one.items] == [("6 Tomatoes", ""), ("2 Milk", "")]
    with pytest.raises(AdapterError) as missing:
        await get_adapter("mealie").fetch("shopping", CONFIG, {"list": "Nope"}, ctx)
    assert missing.value.code == "no_such_list"


@respx.mock
async def test_the_summary_and_the_connection_test(ctx: Context) -> None:
    respx.get(f"{ME}/api/households/shopping/items").mock(return_value=httpx.Response(200, json=page([item("1 Bread", True), item("2 Milk", False)])))
    respx.get(f"{ME}/api/households/shopping/lists").mock(return_value=httpx.Response(200, json=LISTS))
    respx.get(f"{ME}/api/households/mealplans").mock(return_value=httpx.Response(200, json=page([plan(0, "dinner")], total=5)))
    respx.get(f"{ME}/api/recipes").mock(return_value=httpx.Response(200, json=page([{"name": "Tomato soup"}], total=86)))
    respx.get(f"{ME}/api/app/about").mock(return_value=httpx.Response(200, json={"version": "v3.25.1", "production": True}))
    data = await get_adapter("mealie").fetch("summary", CONFIG, {}, ctx)
    assert data.primary == {"label": "To buy", "value": 1}
    assert data.secondary == [{"label": "Planned", "value": 5}, {"label": "Recipes", "value": 86}]
    assert await get_adapter("mealie").test(CONFIG, ctx) == "Mealie v3.25.1 answers with 86 recipes."


@respx.mock
async def test_a_wrong_token_and_another_service(ctx: Context) -> None:
    respx.get(f"{ME}/api/app/about").mock(return_value=httpx.Response(401, json={"detail": "Could not validate credentials"}))
    with pytest.raises(AuthFailed):
        await get_adapter("mealie").test(CONFIG, ctx)
    respx.get(f"{ME}/api/households/shopping/items").mock(return_value=httpx.Response(200, json=[]))
    with pytest.raises(AdapterError) as wrong:
        await get_adapter("mealie").fetch("shopping", CONFIG, {}, ctx)
    assert wrong.value.code == "not_mealie"
