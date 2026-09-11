"""Grocy: what in the pantry has to go soon, what went off, and what ran out.

Measured against Grocy 4.7.1 (the linuxserver image) on 11.09.2026, with milk
past its best-before date, butter past its expiration date, yoghurt due in
two days, rice due next spring and coffee below its minimum stock.

⚠️ A product past its expiration date is listed in ``expired_products`` and
in ``overdue_products`` as well. Adding up both lists counts it twice; the
list card shows it once, as expired.

⚠️ ``missing_products`` has a shape of its own: ``id``, ``name`` and
``amount_missing`` at the top and no ``product_id``.

⚠️ A missing and a wrong key both get 401 with an empty body.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
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


def _amount(value: Any) -> str:
    number = float(value or 0)
    return str(int(number)) if number.is_integer() else f"{number:g}"


def _name(entry: dict[str, Any]) -> str:
    product = entry.get("product") if isinstance(entry.get("product"), dict) else {}
    return str(product.get("name") or entry.get("name") or "?")


class GrocyAdapter(Adapter):
    kind = "grocy"
    label = "Grocy"
    category = "other"
    description = "What in the pantry has to go soon, what went off, and what ran out."
    icon = "grocy"
    beta = False
    docs_url = "https://demo.grocy.info/api"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://grocy"),
        Field("api_key", "API key", type="password", secret=True, required=True, help="Manage API keys, in the settings menu, then Add."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    DAYS = Field("days", "Due soon within days", type="number", default=5)
    widgets = (
        WidgetType(kind="stock", label="Stock to watch", description="Expired, overdue and soon due products, and what is below its minimum.",
                   renderer="list", default_size=(3, 3), refresh_seconds=900, metrics=("overdue",),
                   options=(DAYS, Field("limit", "Entries", type="number", default=12))),
        WidgetType(kind="summary", label="Pantry", description="How many products are overdue, expired, due soon and below their minimum.",
                   renderer="value", default_size=(3, 2), refresh_seconds=900, metrics=("overdue",), options=(DAYS,)),
    )

    async def _json(self, config: dict[str, Any], ctx: Context, path: str, params: dict[str, Any] | None = None) -> Any:
        response = await ctx.request(
            "GET", f"{base_url(config)}/api{path}", headers={"GROCY-API-KEY": str(config.get("api_key") or "")},
            params=params, verify=not config.get("insecure"), cache_seconds=30, auth_errors=False,
        )
        if response.status_code in (401, 403):
            raise AuthFailed("Grocy rejected the API key.")
        if response.status_code >= 400:
            raise AdapterError(f"Grocy answered with HTTP {response.status_code}.", code="http_error",
                               hint="Check the URL; it is the address of Grocy itself, without /api.")
        try:
            return response.json()
        except ValueError as error:
            raise AdapterError("Grocy did not answer with JSON.", code="not_json",
                               hint="The URL probably points at the sign-in page or a reverse proxy.") from error

    async def _volatile(self, config: dict[str, Any], ctx: Context, options: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
        days = max(1, min(60, int(options.get("days") or 5)))
        answer = await self._json(config, ctx, "/stock/volatile", {"due_soon_days": days})
        if not isinstance(answer, dict) or "missing_products" not in answer:
            raise AdapterError("This address answers, but not the way Grocy does.", code="not_grocy")
        return {key: [one for one in answer.get(key) or [] if isinstance(one, dict)]
                for key in ("due_products", "overdue_products", "expired_products", "missing_products")}

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        info = await self._json(config, ctx, "/system/info")
        version = (info.get("grocy_version") or {}).get("Version") if isinstance(info, dict) else None
        if not version:
            raise AdapterError("This address answers, but not the way Grocy does.", code="not_grocy")
        stock = await self._json(config, ctx, "/stock")
        return f"Grocy {version} answers with {len(stock) if isinstance(stock, list) else 0} products in stock."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        volatile = await self._volatile(config, ctx, options)
        if widget_kind == "summary":
            return self._summary(volatile)
        return self._stock(volatile, options)

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def _stock(volatile: dict[str, list[dict[str, Any]]], options: dict[str, Any]) -> WidgetData:
        expired_ids = {entry.get("product_id") for entry in volatile["expired_products"]}
        items = []
        groups = (
            ("expired_products", "Expired", "bad", lambda entry: True),
            ("overdue_products", "Overdue", "warn", lambda entry: entry.get("product_id") not in expired_ids),
            ("due_products", "Due soon", "unknown", lambda entry: True),
        )
        for key, word, state, keep in groups:
            for entry in sorted(volatile[key], key=lambda one: str(one.get("best_before_date") or "")):
                if not keep(entry):
                    continue
                items.append({
                    "title": _name(entry),
                    "subtitle": " · ".join(part for part in (word, str(entry.get("best_before_date") or "")) if part),
                    "status": state,
                    "value": _amount(entry.get("amount")),
                })
        for entry in volatile["missing_products"]:
            items.append({"title": _name(entry), "subtitle": "Below minimum", "status": "unknown", "value": _amount(entry.get("amount_missing"))})
        expired, overdue = len(volatile["expired_products"]), len(volatile["overdue_products"])
        return WidgetData(
            status="bad" if expired else "warn" if overdue else "ok",
            items=items[: int(options.get("limit") or 12)],
            secondary=[{"label": "Overdue", "value": overdue}],
            meta={"empty": "Nothing is due and nothing is missing."},
            metrics={"overdue": float(overdue)},
        )

    @staticmethod
    def _summary(volatile: dict[str, list[dict[str, Any]]]) -> WidgetData:
        expired, overdue = len(volatile["expired_products"]), len(volatile["overdue_products"])
        secondary = [{"label": label, "value": value} for label, value in (
            ("Expired", expired), ("Due soon", len(volatile["due_products"])), ("Below minimum", len(volatile["missing_products"]))) if value]
        return WidgetData(
            status="bad" if expired else "warn" if overdue else "ok",
            # As the API lists them: an expired product counts as overdue too.
            primary={"label": "Overdue", "value": overdue},
            secondary=secondary,
            metrics={"overdue": float(overdue)},
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        today = datetime.now(UTC).date()

        def day(offset: int) -> str:
            return (today + timedelta(days=offset)).isoformat()

        volatile = {
            "expired_products": [{"product_id": 5, "amount": 1, "best_before_date": day(-1), "product": {"name": "Minced meat"}}],
            "overdue_products": [{"product_id": 5, "amount": 1, "best_before_date": day(-1), "product": {"name": "Minced meat"}},
                                 {"product_id": 1, "amount": 1, "best_before_date": day(-2), "product": {"name": "Milk"}}],
            "due_products": [{"product_id": 2, "amount": 2 + tick % 2, "best_before_date": day(2), "product": {"name": "Yoghurt"}}],
            "missing_products": [{"id": 4, "name": "Coffee", "amount_missing": 2}],
        }
        if widget_kind == "summary":
            return self._summary(volatile)
        return self._stock(volatile, options)


ADAPTER = GrocyAdapter()
