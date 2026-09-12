"""Tandoor Recipes: what is planned to eat, and what is still to buy.

Measured against Tandoor 2.6.15 (vabene1111/recipes) on 11.09.2026, with two
recipes, meal plans from yesterday to the day after tomorrow and three
shopping entries, one of them ticked off.

⚠️ The shopping list hands back what was ticked off in the last days as well
(``shopping_recent_days`` of the user, at most 14): a milk bought an hour ago
came back with ``checked: true``. The card leaves those out itself.

⚠️ A meal plan's ``from_date`` is a moment, not a day: the date with the meal
type's time, ``2026-09-11T18:30:00Z`` for a dinner at 18:30. The filter takes
plain dates.

⚠️ A missing and a made-up token both get 403, not 401. A token with the scope
``read`` reads everything here and gets 403 "You do not have permission to
perform this action." when it ticks an entry off; that needs ``read write``.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from .base import (
    Action,
    Adapter,
    AdapterError,
    AuthFailed,
    Context,
    Field,
    WidgetData,
    WidgetType,
    base_url,
    path_segment,
)


def _amount(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    return str(int(number)) if number.is_integer() else f"{number:g}"


def _clock(value: Any) -> str:
    """``18:30:00`` as ``18:30``; anything else as nothing."""
    text = str(value or "")
    return text[:5] if len(text) >= 5 and text[2] == ":" else ""


class TandoorAdapter(Adapter):
    kind = "tandoor"
    label = "Tandoor Recipes"
    category = "other"
    description = "What is planned to eat, and what is still on the shopping list."
    icon = "tandoor-recipes"
    #: Confirmed against a live instance on 2026-09-11.
    beta = False
    docs_url = "https://docs.tandoor.dev/"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://tandoor:8080"),
        Field("token", "API token", type="password", secret=True, required=True,
              help="Settings > API > New. The scope read is enough to look; ticking off needs read write."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(kind="plan", label="Meal plan", description="What is planned for today and the days after it, meal by meal.",
                   renderer="list", default_size=(3, 3), refresh_seconds=900,
                   options=(Field("days", "Days", type="number", default=3, help="1 shows today only."),)),
        WidgetType(kind="shopping", label="Shopping list", description="What is not ticked off yet, with a button to tick it off.",
                   renderer="list", default_size=(3, 3), refresh_seconds=120, metrics=("to_buy",),
                   options=(Field("limit", "Entries", type="number", default=12),)),
    )

    def _headers(self, config: dict[str, Any]) -> dict[str, str]:
        return {"Authorization": f"Bearer {config.get('token') or ''}", "Accept": "application/json"}

    async def _page(self, config: dict[str, Any], ctx: Context, path: str, params: dict[str, Any], cache: float = 30) -> dict[str, Any]:
        response = await ctx.request(
            "GET", f"{base_url(config)}/api{path}", headers=self._headers(config), params=params,
            verify=not config.get("insecure"), cache_seconds=cache, auth_errors=False,
        )
        if response.status_code in (401, 403):
            raise AuthFailed("Tandoor rejected the API token.")
        if response.status_code >= 400:
            raise AdapterError(f"Tandoor answered with HTTP {response.status_code}.", code="http_error",
                               hint="Check the URL; it is the address of Tandoor itself, without /api.")
        try:
            answer = response.json()
        except ValueError as error:
            raise AdapterError("Tandoor did not answer with JSON.", code="not_json",
                               hint="The URL probably points at the sign-in page or a reverse proxy.") from error
        if not isinstance(answer, dict) or not isinstance(answer.get("results"), list):
            raise AdapterError("This address answers, but not the way Tandoor does.", code="not_tandoor")
        return answer

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        response = await ctx.request("GET", f"{base_url(config)}/api/server-settings/current/", headers=self._headers(config),
                                     verify=not config.get("insecure"), auth_errors=False)
        try:
            version = str((response.json() or {}).get("version") or "?") if response.status_code == 200 else "?"
        except (ValueError, AttributeError):
            version = "?"
        entries = await self._page(config, ctx, "/shopping-list-entry/", {"page_size": 200}, cache=0)
        to_buy = sum(1 for one in entries["results"] if isinstance(one, dict) and not one.get("checked"))
        return f"Tandoor {version} answers with {to_buy} entries to buy."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        today = datetime.now(UTC).date()
        if widget_kind == "shopping":
            entries = await self._page(config, ctx, "/shopping-list-entry/", {"page_size": 200})
            return self._shopping(entries["results"], options)
        days = max(1, min(14, int(options.get("days") or 3)))
        plans = await self._page(config, ctx, "/meal-plan/",
                                 {"from_date": today.isoformat(), "to_date": (today + timedelta(days=days - 1)).isoformat(), "page_size": 100})
        return self._plan(plans["results"], today, base_url(config))

    async def action(self, widget_kind: str, action_id: str, params: dict[str, Any],
                     config: dict[str, Any], options: dict[str, Any], ctx: Context) -> str:
        if action_id != "check":
            raise AdapterError("Unknown shopping list action.", code="no_such_action")
        entry = path_segment(params.get("id"), "The shopping list entry")
        response = await ctx.request("PATCH", f"{base_url(config)}/api/shopping-list-entry/{entry}/", headers=self._headers(config),
                                     json_body={"checked": True}, verify=not config.get("insecure"), auth_errors=False)
        if response.status_code in (401, 403):
            raise AuthFailed("Tandoor refused to tick the entry off. That needs a token with the scope read write.")
        if response.status_code == 404:
            raise AdapterError("Tandoor has no such shopping list entry any more.", code="action_failed")
        if response.status_code >= 400:
            raise AdapterError(f"Tandoor answered with HTTP {response.status_code}.", code="action_failed")
        try:
            ticked = (response.json() or {}).get("checked") is True
        except (ValueError, AttributeError):
            ticked = False
        if not ticked:
            raise AdapterError("Tandoor answered, but the entry is not ticked off.", code="action_failed")
        ctx.forget_answers()
        return "Ticked off."

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def _plan(plans: list[Any], today: date, base: str) -> WidgetData:
        entries = [one for one in plans if isinstance(one, dict)]
        entries.sort(key=lambda one: (str(one.get("from_date") or "")[:10],
                                      int((one.get("meal_type") or {}).get("order") or 0) if isinstance(one.get("meal_type"), dict) else 0))
        items = []
        for entry in entries:
            recipe = entry.get("recipe") if isinstance(entry.get("recipe"), dict) else {}
            meal = entry.get("meal_type") if isinstance(entry.get("meal_type"), dict) else {}
            day = str(entry.get("from_date") or "")[:10]
            when = "Today" if day == today.isoformat() else "Tomorrow" if day == (today + timedelta(days=1)).isoformat() else day
            row: dict[str, Any] = {
                "title": str(recipe.get("name") or entry.get("title") or meal.get("name") or "?"),
                "subtitle": " · ".join(part for part in (when, str(meal.get("name") or entry.get("meal_type_name") or "")) if part),
                "status": "ok",
                # The meal type's own time. from_date carries it as well, but that was only measured on a server running in UTC.
                "value": _clock(meal.get("time")),
            }
            if recipe.get("id"):
                row["url"] = f"{base}/recipe/{recipe['id']}"
            items.append(row)
        return WidgetData(status="ok", items=items, meta={"empty": "Nothing planned yet."})

    @staticmethod
    def _shopping(entries: list[Any], options: dict[str, Any]) -> WidgetData:
        open_entries = [one for one in entries if isinstance(one, dict) and not one.get("checked")]
        rows = []
        for entry in open_entries:
            food = entry.get("food") if isinstance(entry.get("food"), dict) else {}
            unit = entry.get("unit") if isinstance(entry.get("unit"), dict) else {}
            category = food.get("supermarket_category") if isinstance(food.get("supermarket_category"), dict) else {}
            amount = " ".join(part for part in (_amount(entry.get("amount")) if entry.get("amount") else "", str(unit.get("name") or "")) if part)
            rows.append({
                "title": str(food.get("name") or "?"),
                "subtitle": " · ".join(part for part in (amount, str(category.get("name") or "")) if part),
                "status": "ok",
                "actions": [Action(id="check", label="Tick off", icon="check", params={"id": str(entry.get("id") or "")})],
            })
        return WidgetData(
            status="ok",
            items=rows[: int(options.get("limit") or 12)],
            secondary=[{"label": "To buy", "value": len(open_entries)}],
            # A wall display has no hovering, and ticking off is the one thing on this card to press.
            meta={"empty": "Nothing left to buy.", "actions_visible": True},
            metrics={"to_buy": float(len(open_entries))},
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        today = datetime.now(UTC).date()
        if widget_kind == "shopping":
            entries = [
                {"id": 1, "food": {"name": "Milk", "supermarket_category": {"name": "Dairy"}}, "unit": {"name": "l"}, "amount": 1.0, "checked": False},
                {"id": 2, "food": {"name": "Tomatoes"}, "unit": {"name": "g"}, "amount": 800.0, "checked": False},
                {"id": 3, "food": {"name": "Bread"}, "unit": None, "amount": 1.0, "checked": tick % 2 == 0},
                {"id": 4, "food": {"name": "Eggs"}, "unit": None, "amount": 6.0, "checked": False},
            ]
            return self._shopping(entries, options)
        dinner = {"name": "Dinner", "order": 2, "time": "18:30:00"}
        lunch = {"name": "Lunch", "order": 1, "time": "12:00:00"}
        plans = [
            {"from_date": f"{today.isoformat()}T18:30:00Z", "meal_type": dinner, "recipe": {"id": 1, "name": "Tomato soup"}},
            {"from_date": f"{(today + timedelta(days=1)).isoformat()}T12:00:00Z", "meal_type": lunch, "title": "Leftovers", "recipe": None},
            {"from_date": f"{(today + timedelta(days=2)).isoformat()}T18:30:00Z", "meal_type": dinner, "recipe": {"id": 2, "name": "Bean chili"}},
        ]
        return self._plan(plans, today, "https://tandoor.example.com")


ADAPTER = TandoorAdapter()
