"""KitchenOwl: the shopping list, the meal plan, and how many recipes there are.

Measured on 28.10.2026 against KitchenOwl (API version 124, the official
image with SQLite), a long-lived token, one household with three items on
its list, two recipes and two planned meals, all invented.

⚠️ The token is a *long-lived token* (the app's Settings > Sessions > Add
long-lived token), sent as ``Authorization: Bearer``. The one that signing in
answers lasts fifteen minutes. A broken token is not 401: ``abc`` got 422
``{"msg": "Not enough segments"}``, and only a missing header 401 ``{"msg":
"Missing Authorization Header"}``. Both mean the token is wrong.

⚠️ Everything lives under a household (``/api/household``, a bare array),
and a user can belong to several. The card takes the one named in its options
or the first. The shopping lists come with their items in
``/api/household/<id>/shoppinglist``: an item on a list is an item to buy,
there is no ticked state (ticking removes it), and ``description`` is its
amount.

⚠️ The planner (``/api/household/<id>/planner``) answers ``cooking_date`` in
milliseconds. A meal planned without a day has the date 0001-01-01
(-62135596800000), which is not a day anybody cooks on: the card lists it
last, without a date.

``/api/health/<key>`` answers the API version as a number, not KitchenOwl's
own; the key in the path is a constant of the server, not a secret.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

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

URL_HINT = "Check the URL; it is the address of KitchenOwl itself, without /api."
HEALTH = "/api/health/8M4F88S8ooi4sMbLBfkkV7ctWwgibW6V"
UNDATED = -62135596800000
HOUSEHOLD = Field("household", "Household", help="The name of one household. Empty uses the first.")


class KitchenOwlAdapter(Adapter):
    kind = "kitchenowl"
    label = "KitchenOwl"
    category = "other"
    description = "What is left to buy on the shopping list, the meals planned from today on, and how many recipes there are."
    icon = "kitchenowl"
    beta = True
    docs_url = "https://docs.kitchenowl.org/latest/"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://kitchenowl:8080"),
        Field("token", "Long-lived token", type="password", secret=True, required=True,
              help="Settings > Sessions > Add long-lived token, in the app or the web page."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(kind="shopping", label="Shopping list", description="What is on the list, with its amount.",
                   renderer="list", default_size=(3, 3), refresh_seconds=300, metrics=("to_buy",),
                   options=(HOUSEHOLD, Field("list", "List", help="The name of one shopping list. Empty shows all."),
                            Field("limit", "Entries", type="number", default=12))),
        WidgetType(kind="plan", label="Meal plan", description="What is planned from today on, day by day.",
                   renderer="list", default_size=(3, 3), refresh_seconds=900,
                   options=(HOUSEHOLD, Field("days", "Days", type="number", default=7))),
        WidgetType(kind="summary", label="Kitchen", description="Items to buy, meals planned and recipes.",
                   renderer="value", default_size=(3, 2), refresh_seconds=900, metrics=("to_buy",),
                   options=(HOUSEHOLD,)),
    )

    # -- talking to KitchenOwl -----------------------------------------------

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, cache: float = 30) -> Any:
        response = await ctx.request(
            "GET", f"{base_url(config)}{path}", headers={"Authorization": f"Bearer {config.get('token') or ''}"},
            verify=not config.get("insecure"), cache_seconds=cache, auth_errors=False,
        )
        # ⚠️ A broken token is 422, not 401; see the top of the file.
        if response.status_code in (401, 403, 422):
            raise AuthFailed("KitchenOwl rejected the token. Use a long-lived token.")
        if response.status_code >= 400:
            raise AdapterError(f"KitchenOwl answered with HTTP {response.status_code}.", code="http_error", hint=URL_HINT)
        try:
            return response.json()
        except ValueError as error:
            raise AdapterError("KitchenOwl did not answer with JSON.", code="not_json",
                               hint="The URL probably points at a login page or a reverse proxy.") from error

    async def _household(self, config: dict[str, Any], ctx: Context, options: dict[str, Any]) -> dict[str, Any]:
        households = await self._get(config, ctx, "/api/household")
        if not isinstance(households, list):
            raise AdapterError("This address answers, but not the way KitchenOwl does.", code="not_kitchenowl", hint=URL_HINT)
        households = [one for one in households if isinstance(one, dict)]
        wanted = str(options.get("household") or "").strip().lower()
        if wanted:
            for one in households:
                if str(one.get("name") or "").lower() == wanted:
                    return one
            raise AdapterError(f"KitchenOwl has no household named {str(options.get('household')).strip()!r}.", code="no_such_household")
        if not households:
            raise AdapterError("This account belongs to no household yet.", code="no_household",
                               hint="Make one in KitchenOwl, or ask to be added to one.")
        return households[0]

    async def _lists(self, config: dict[str, Any], ctx: Context, household: dict[str, Any]) -> list[dict[str, Any]]:
        lists = await self._get(config, ctx, f"/api/household/{household['id']}/shoppinglist")
        if not isinstance(lists, list):
            raise AdapterError("This address answers, but not the way KitchenOwl does.", code="not_kitchenowl", hint=URL_HINT)
        return [one for one in lists if isinstance(one, dict)]

    # -- the hooks -----------------------------------------------------------

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        health = await self._get(config, ctx, HEALTH, cache=0)
        if not isinstance(health, dict) or health.get("msg") != "OK":
            raise AdapterError("This address answers, but not the way KitchenOwl does.", code="not_kitchenowl", hint=URL_HINT)
        user = await self._get(config, ctx, "/api/user", cache=0)
        households = await self._get(config, ctx, "/api/household", cache=0)
        count = len(households) if isinstance(households, list) else 0
        return f"KitchenOwl answers for {(user or {}).get('name') or '?'} with {count} households."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        household = await self._household(config, ctx, options)
        base = base_url(config)
        today = datetime.now(UTC).date()
        if widget_kind == "shopping":
            return self._shopping(await self._lists(config, ctx, household), options, base)
        plan = await self._get(config, ctx, f"/api/household/{household['id']}/planner")
        if not isinstance(plan, list):
            raise AdapterError("This address answers, but not the way KitchenOwl does.", code="not_kitchenowl", hint=URL_HINT)
        if widget_kind == "plan":
            days = max(1, min(31, int(options.get("days") or 7)))
            return self._plan(plan, today, days, base)
        recipes = await self._get(config, ctx, f"/api/household/{household['id']}/recipe")
        lists = await self._lists(config, ctx, household)
        return self._summary(lists, plan, len(recipes) if isinstance(recipes, list) else 0, today, base)

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def _shopping(lists: list[dict[str, Any]], options: dict[str, Any], base: str) -> WidgetData:
        wanted = str(options.get("list") or "").strip().lower()
        if wanted and wanted not in {str(one.get("name") or "").lower() for one in lists}:
            raise AdapterError(f"KitchenOwl has no shopping list named {str(options.get('list')).strip()!r}.", code="no_such_list")
        chosen = [one for one in lists if not wanted or str(one.get("name") or "").lower() == wanted]
        several = len(lists) > 1 and not wanted
        rows = []
        for shopping_list in chosen:
            for item in shopping_list.get("items") or []:
                if not isinstance(item, dict):
                    continue
                rows.append({
                    "title": str(item.get("name") or "?"),
                    "subtitle": " · ".join(part for part in (str(item.get("description") or ""),
                                                             str(shopping_list.get("name") or "") if several else "") if part),
                })
        return WidgetData(
            status="ok",
            items=rows[: max(1, int(options.get("limit") or 12))],
            secondary=[{"label": "To buy", "value": len(rows)}],
            link=base,
            meta={"empty": "Nothing left to buy."},
            metrics={"to_buy": float(len(rows))},
        )

    @staticmethod
    def _dated(plan: list[dict[str, Any]], today: date) -> list[tuple[date | None, dict[str, Any]]]:
        """The planned meals from today on, undated ones last."""
        found: list[tuple[date | None, dict[str, Any]]] = []
        for entry in plan:
            if not isinstance(entry, dict) or not isinstance(entry.get("recipe"), dict):
                continue
            stamp = entry.get("cooking_date")
            # ⚠️ Milliseconds, and the year 1 for a meal without a day.
            day = None if not isinstance(stamp, int | float) or stamp <= UNDATED else datetime.fromtimestamp(stamp / 1000, UTC).date()
            if day is None or day >= today:
                found.append((day, entry))
        return sorted(found, key=lambda pair: (pair[0] is None, pair[0] or today))

    @classmethod
    def _plan(cls, plan: list[dict[str, Any]], today: date, days: int, base: str) -> WidgetData:
        items = []
        for day, entry in cls._dated(plan, today):
            if day is not None and day > today + timedelta(days=days - 1):
                continue
            when = "" if day is None else "Today" if day == today else "Tomorrow" if day == today + timedelta(days=1) else day.isoformat()
            row: dict[str, Any] = {"title": str(entry["recipe"].get("name") or "?"), "subtitle": when, "status": "ok"}
            items.append(row)
        return WidgetData(status="ok", items=items, link=base, meta={"empty": "Nothing planned yet."})

    @classmethod
    def _summary(cls, lists: list[dict[str, Any]], plan: list[dict[str, Any]], recipes: int, today: date, base: str) -> WidgetData:
        to_buy = sum(len(one.get("items") or []) for one in lists)
        return WidgetData(
            status="ok",
            primary={"label": "To buy", "value": to_buy},
            secondary=[{"label": "Planned", "value": len(cls._dated(plan, today))}, {"label": "Recipes", "value": recipes}],
            link=base,
            metrics={"to_buy": float(to_buy)},
        )

    # -- demo ----------------------------------------------------------------

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        base = "https://kitchenowl.example.com"
        today = datetime.now(UTC).date()
        milliseconds = lambda days: int(datetime.combine(today + timedelta(days=days), datetime.min.time(), UTC).timestamp() * 1000)  # noqa: E731
        lists = [{"name": "Default", "items": [
            {"name": "Milk", "description": "2"}, {"name": "Tomatoes", "description": "6"},
            *([{"name": "Bread", "description": ""}] if tick % 2 else []),
        ]}]
        plan = [
            {"cooking_date": milliseconds(1), "recipe": {"id": 2, "name": "Bean chili"}},
            {"cooking_date": milliseconds(0), "recipe": {"id": 1, "name": "Tomato soup"}},
            {"cooking_date": UNDATED, "recipe": {"id": 3, "name": "Pancakes"}},
        ]
        if widget_kind == "shopping":
            return self._shopping(lists, options, base)
        if widget_kind == "plan":
            return self._plan(plan, today, 7, base)
        fresh = 1 if fake.flicker("kitchenowl-new", tick, 0.3) else 0
        return self._summary(lists, plan, 41 + fresh, today, base)


ADAPTER = KitchenOwlAdapter()
