"""KitchenOwl, against the answers of a live KitchenOwl (API version 124, 28.10.2026).

One household with three items on its list, two recipes and two planned
meals, all invented. Addresses and tokens are made up; the shapes are the
measured ones: the milliseconds, the year 1 for a meal without a day, and
the 422 for a broken token.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context, Unreachable

KO = "http://kitchenowl.example.com:8080"
TOKEN = "long-lived-token-for-the-cards"
CONFIG = {"url": KO, "token": TOKEN}
ADAPTER = get_adapter("kitchenowl")
HEALTH = "/api/health/8M4F88S8ooi4sMbLBfkkV7ctWwgibW6V"


def milliseconds(days: int) -> int:
    day = datetime.now(UTC).date() + timedelta(days=days)
    return int(datetime.combine(day, datetime.min.time(), UTC).timestamp() * 1000)


def item(identifier: int, name: str, amount: str) -> dict[str, Any]:
    return {"category_id": None, "created_at": 1793152135354, "created_by": 1, "default": False, "description": amount,
            "household_id": 1, "icon": None, "id": identifier, "name": name, "ordering": 0, "support": 0.0}


HOUSEHOLD = {"id": 1, "name": "Home", "default_shopping_list": {"id": 1, "name": "Default"}, "member": [{"id": 1, "name": "Admin"}]}
LISTS = [
    {"id": 1, "household_id": 1, "name": "Default", "items": [item(2, "Bread", ""), item(1, "Milk", "2"), item(3, "Tomatoes", "6")]},
    {"id": 2, "household_id": 1, "name": "Hardware store", "items": [item(4, "Wall plugs", "8 mm")]},
]


def recipe(identifier: int, name: str) -> dict[str, Any]:
    return {"id": identifier, "name": name, "description": "", "household_id": 1, "items": [], "tags": []}


def planned(days: int | None, identifier: int, name: str) -> dict[str, Any]:
    # ⚠️ A meal without a day is the year 1, in milliseconds.
    return {"cooking_date": -62135596800000 if days is None else milliseconds(days), "day": -1, "household_id": 1,
            "recipe": recipe(identifier, name), "recipe_id": identifier, "yields": None}


PLAN = [planned(None, 3, "Pancakes"), planned(3, 2, "Bean chili"), planned(0, 1, "Tomato soup"), planned(-2, 4, "Last week's stew"),
        planned(20, 5, "Far away roast")]


def server(*, households: list[dict[str, Any]] | None = None) -> list[str]:
    """A fake KitchenOwl that answers the way the live one did, and notes the paths."""
    asked: list[str] = []

    def answer(request: httpx.Request) -> httpx.Response:
        asked.append(request.url.path)
        if request.url.path == HEALTH:
            return httpx.Response(200, json={"min_frontend_version": 71, "msg": "OK", "oidc_provider": [], "version": 124})
        header = request.headers.get("Authorization")
        if header is None:
            return httpx.Response(401, json={"msg": "Missing Authorization Header"})
        if header != f"Bearer {TOKEN}":
            return httpx.Response(422, json={"msg": "Not enough segments"})
        routes: dict[str, Any] = {
            "/api/user": {"id": 1, "name": "Admin", "admin": True},
            "/api/household": [HOUSEHOLD] if households is None else households,
            "/api/household/1/shoppinglist": LISTS,
            "/api/household/1/planner": PLAN,
            "/api/household/1/recipe": [recipe(1, "Tomato soup"), recipe(2, "Bean chili")],
        }
        if request.url.path in routes:
            return httpx.Response(200, json=routes[request.url.path])
        return httpx.Response(404, json={"msg": "Not found"})

    respx.get(url__startswith=KO).mock(side_effect=answer)
    return asked


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


@respx.mock
async def test_the_connection_test_names_the_user_and_counts_the_households(ctx: Context) -> None:
    server()
    assert await ADAPTER.test(CONFIG, ctx) == "KitchenOwl answers for Admin with 1 households."


@respx.mock
async def test_the_shopping_list_counts_every_item_and_names_the_list_when_there_are_several(ctx: Context) -> None:
    server()
    card = await ADAPTER.fetch("shopping", CONFIG, {}, ctx)
    assert [row["title"] for row in card.items] == ["Bread", "Milk", "Tomatoes", "Wall plugs"]
    assert [row["subtitle"] for row in card.items] == ["Default", "2 · Default", "6 · Default", "8 mm · Hardware store"]
    assert card.secondary == [{"label": "To buy", "value": 4}]
    assert card.metrics == {"to_buy": 4.0}


@respx.mock
async def test_one_list_by_name_drops_the_list_from_the_rows_and_a_wrong_name_is_refused(ctx: Context) -> None:
    server()
    card = await ADAPTER.fetch("shopping", CONFIG, {"list": "hardware STORE"}, ctx)
    assert [(row["title"], row["subtitle"]) for row in card.items] == [("Wall plugs", "8 mm")]
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.fetch("shopping", CONFIG, {"list": "Garden"}, ctx)
    assert caught.value.code == "no_such_list"


@respx.mock
async def test_the_plan_lists_the_days_to_come_in_order_and_the_undated_meal_last(ctx: Context) -> None:
    server()
    card = await ADAPTER.fetch("plan", CONFIG, {"days": 7}, ctx)
    # Last week's stew is past, the roast is beyond seven days.
    assert [(row["title"], row["subtitle"]) for row in card.items] == [
        ("Tomato soup", "Today"), ("Bean chili", (datetime.now(UTC).date() + timedelta(days=3)).isoformat()), ("Pancakes", "")]


@respx.mock
async def test_the_overview_counts_the_items_the_meals_to_come_and_the_recipes(ctx: Context) -> None:
    server()
    card = await ADAPTER.fetch("summary", CONFIG, {}, ctx)
    assert card.primary == {"label": "To buy", "value": 4}
    # Today, in three days, in twenty days, and the one without a day.
    assert card.secondary == [{"label": "Planned", "value": 4}, {"label": "Recipes", "value": 2}]
    assert card.metrics == {"to_buy": 4.0}


@respx.mock
async def test_a_household_is_found_by_name_and_a_missing_one_is_said(ctx: Context) -> None:
    server()
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.fetch("shopping", CONFIG, {"household": "Cabin"}, ctx)
    assert caught.value.code == "no_such_household"
    ctx.cache.clear()
    server(households=[])
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.fetch("shopping", CONFIG, {}, ctx)
    assert caught.value.code == "no_household"


@respx.mock
async def test_a_broken_token_with_status_422_is_an_authentication_failure(ctx: Context) -> None:
    # ⚠️ The live server answered 422 "Not enough segments" for a token that is not a JWT.
    server()
    with pytest.raises(AuthFailed):
        await ADAPTER.fetch("summary", {**CONFIG, "token": "abc"}, {}, ctx)
    with pytest.raises(AuthFailed):
        await ADAPTER.fetch("summary", {**CONFIG, "token": ""}, {}, ctx)


@respx.mock
async def test_an_unreachable_service_is_reported_as_such(ctx: Context) -> None:
    respx.get(url__startswith=KO).mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(Unreachable):
        await ADAPTER.fetch("plan", CONFIG, {}, ctx)


@respx.mock
async def test_another_service_behind_the_address_is_named(ctx: Context) -> None:
    respx.get(url__startswith=KO).mock(return_value=httpx.Response(200, json={"hello": "world"}))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.test(CONFIG, ctx)
    assert caught.value.code == "not_kitchenowl"


def test_the_demo_has_a_card_for_every_widget() -> None:
    for widget in ADAPTER.widgets:
        data: Any = ADAPTER.demo(widget.kind, {}, 3)
        assert data.primary or data.items
