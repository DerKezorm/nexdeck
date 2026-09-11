"""Mealie: what is on the meal plan, and what is still on the shopping list.

Measured against Mealie 3.25.1 on 11.09.2026, with two recipes, a dinner
planned for today, a lunch note for tomorrow and a shopping list of three
items, one of them ticked off.

⚠️ The meal plan for a range comes in the order it was entered, not by date:
tomorrow's lunch was listed before today's dinner.

⚠️ A recipe's page lives under its group, ``/g/<group>/r/<recipe>``. The
group's slug is not in the meal plan; it comes from ``/users/self``.
"""

from __future__ import annotations

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

#: Mealie's meal types, in the order of a day.
MEALS = {"breakfast": "Breakfast", "lunch": "Lunch", "dinner": "Dinner", "side": "Side", "snack": "Snack", "drink": "Drink", "dessert": "Dessert"}


class MealieAdapter(Adapter):
    kind = "mealie"
    label = "Mealie"
    category = "other"
    description = "What is on the meal plan, and what is still on the shopping list."
    icon = "mealie"
    beta = False
    docs_url = "https://docs.mealie.io/documentation/getting-started/api-usage/"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://mealie:9000"),
        Field("token", "API token", type="password", secret=True, required=True, help="Profile > Manage your API tokens > Generate."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(kind="plan", label="Meal plan", description="What is planned from today on, day by day.",
                   renderer="list", default_size=(3, 3), refresh_seconds=900,
                   options=(Field("days", "Days", type="number", default=7),)),
        WidgetType(kind="shopping", label="Shopping list", description="What is not ticked off yet.",
                   renderer="list", default_size=(3, 3), refresh_seconds=300, metrics=("to_buy",),
                   options=(Field("list", "List", help="The name of one shopping list. Empty shows all."),
                            Field("limit", "Entries", type="number", default=12))),
        WidgetType(kind="summary", label="Kitchen", description="Items to buy, meals planned this week and recipes.",
                   renderer="value", default_size=(3, 2), refresh_seconds=900, metrics=("to_buy",)),
    )

    async def _json(self, config: dict[str, Any], ctx: Context, path: str, params: dict[str, Any] | None = None, cache: float = 30) -> Any:
        response = await ctx.request(
            "GET", f"{base_url(config)}/api{path}", headers={"Authorization": f"Bearer {config.get('token') or ''}"},
            params=params, verify=not config.get("insecure"), cache_seconds=cache, auth_errors=False,
        )
        # Measured: a missing and a wrong token both get 401 "Could not validate credentials".
        if response.status_code in (401, 403):
            raise AuthFailed("Mealie rejected the API token.")
        if response.status_code >= 400:
            raise AdapterError(f"Mealie answered with HTTP {response.status_code}.", code="http_error",
                               hint="Check the URL; it is the address of Mealie itself, without /api.")
        try:
            return response.json()
        except ValueError as error:
            raise AdapterError("Mealie did not answer with JSON.", code="not_json",
                               hint="The URL probably points at a login page or a reverse proxy.") from error

    async def _page(self, config: dict[str, Any], ctx: Context, path: str, params: dict[str, Any]) -> dict[str, Any]:
        answer = await self._json(config, ctx, path, params)
        if not isinstance(answer, dict) or not isinstance(answer.get("items"), list):
            raise AdapterError("This address answers, but not the way Mealie does.", code="not_mealie")
        return answer

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        about = await self._json(config, ctx, "/app/about", cache=0)
        recipes = await self._page(config, ctx, "/recipes", {"perPage": 1})
        if not isinstance(about, dict):
            raise AdapterError("This address answers, but not the way Mealie does.", code="not_mealie")
        return f"Mealie {about.get('version', '?')} answers with {recipes.get('total', 0)} recipes."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        today = datetime.now(UTC).date()
        if widget_kind == "plan":
            days = max(1, min(31, int(options.get("days") or 7)))
            week = await self._page(config, ctx, "/households/mealplans",
                                    {"start_date": today.isoformat(), "end_date": (today + timedelta(days=days - 1)).isoformat(), "perPage": 100})
            me = await self._json(config, ctx, "/users/self", cache=3600)
            group = str(me.get("groupSlug") or "") if isinstance(me, dict) else ""
            return self._plan(week["items"], today, base_url(config), group)
        items = await self._page(config, ctx, "/households/shopping/items", {"perPage": -1})
        lists = await self._page(config, ctx, "/households/shopping/lists", {"perPage": -1})
        if widget_kind == "shopping":
            return self._shopping(items["items"], lists["items"], options)
        week = await self._page(config, ctx, "/households/mealplans",
                                {"start_date": today.isoformat(), "end_date": (today + timedelta(days=6)).isoformat(), "perPage": 100})
        recipes = await self._page(config, ctx, "/recipes", {"perPage": 1})
        return self._summary(items["items"], int(week.get("total") or len(week["items"])), int(recipes.get("total") or 0))

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def _plan(entries: list[Any], today: date, base: str, group: str) -> WidgetData:
        order = list(MEALS)
        planned = sorted((entry for entry in entries if isinstance(entry, dict)),
                         key=lambda entry: (str(entry.get("date") or ""), order.index(entry.get("entryType")) if entry.get("entryType") in order else 99))
        items = []
        for entry in planned:
            recipe = entry.get("recipe") if isinstance(entry.get("recipe"), dict) else {}
            day = str(entry.get("date") or "")
            when = "Today" if day == today.isoformat() else "Tomorrow" if day == (today + timedelta(days=1)).isoformat() else day
            row: dict[str, Any] = {
                "title": str(recipe.get("name") or entry.get("title") or "?"),
                "subtitle": " · ".join(part for part in (when, MEALS.get(str(entry.get("entryType")), str(entry.get("entryType") or "").capitalize())) if part),
                "status": "ok",
            }
            if recipe.get("slug") and group:
                row["url"] = f"{base}/g/{group}/r/{recipe['slug']}"
            items.append(row)
        return WidgetData(status="ok", items=items, meta={"empty": "Nothing planned yet."})

    @staticmethod
    def _shopping(items: list[Any], lists: list[Any], options: dict[str, Any]) -> WidgetData:
        names = {str(one.get("id")): str(one.get("name") or "") for one in lists if isinstance(one, dict)}
        wanted = str(options.get("list") or "").strip().lower()
        if wanted and wanted not in {name.lower() for name in names.values()}:
            raise AdapterError(f"Mealie has no shopping list named {str(options.get('list')).strip()!r}.", code="no_such_list")
        open_items = [item for item in items if isinstance(item, dict) and not item.get("checked")
                      and (not wanted or names.get(str(item.get("shoppingListId")), "").lower() == wanted)]
        several = len(names) > 1 and not wanted
        rows = [{
            "title": str(item.get("display") or item.get("note") or "?"),
            "subtitle": names.get(str(item.get("shoppingListId")), "") if several else "",
        } for item in open_items]
        return WidgetData(
            status="ok",
            items=rows[: int(options.get("limit") or 12)],
            secondary=[{"label": "To buy", "value": len(open_items)}],
            meta={"empty": "Nothing left to buy."},
            metrics={"to_buy": float(len(open_items))},
        )

    @staticmethod
    def _summary(items: list[Any], planned: int, recipes: int) -> WidgetData:
        to_buy = sum(1 for item in items if isinstance(item, dict) and not item.get("checked"))
        return WidgetData(
            status="ok",
            primary={"label": "To buy", "value": to_buy},
            secondary=[{"label": "Planned", "value": planned}, {"label": "Recipes", "value": recipes}],
            metrics={"to_buy": float(to_buy)},
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        today = datetime.now(UTC).date()
        lists = [{"id": "l1", "name": "Weekly shop"}, {"id": "l2", "name": "Hardware store"}]
        items = [
            {"display": "2 Milk", "checked": False, "shoppingListId": "l1"},
            {"display": "6 Tomatoes", "checked": False, "shoppingListId": "l1"},
            {"display": "1 Bread", "checked": tick % 2 == 0, "shoppingListId": "l1"},
            {"display": "Wall plugs, 8 mm", "checked": False, "shoppingListId": "l2"},
        ]
        if widget_kind == "plan":
            entries = [
                {"date": (today + timedelta(days=1)).isoformat(), "entryType": "lunch", "title": "Leftovers"},
                {"date": today.isoformat(), "entryType": "dinner", "recipe": {"name": "Tomato soup", "slug": "tomato-soup"}},
                {"date": (today + timedelta(days=2)).isoformat(), "entryType": "dinner", "recipe": {"name": "Bean chili", "slug": "bean-chili"}},
            ]
            return self._plan(entries, today, "https://mealie.example.com", "home")
        if widget_kind == "shopping":
            return self._shopping(items, lists, options)
        return self._summary(items, 5, 86)


ADAPTER = MealieAdapter()
