"""Grocy, against the answers of a live Grocy 4.7.1 (11.09.2026)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context

GR = "http://grocy.example.com"
CONFIG = {"url": GR, "api_key": "made-up-key"}


def stocked(product_id: int, name: str, amount: float, best_before: str, due_type: int = 1) -> dict[str, Any]:
    return {"amount": amount, "amount_aggregated": amount, "value": 0, "best_before_date": best_before, "amount_opened": 0,
            "amount_opened_aggregated": 0, "is_aggregated_amount": 0, "due_type": due_type, "product_id": product_id,
            "product": {"id": product_id, "name": name, "location_id": 2, "qu_id_stock": 2, "min_stock_amount": 0, "due_type": due_type, "active": 1}}


BUTTER = stocked(5, "Butter", 1, "2026-09-10", due_type=2)
VOLATILE = {
    "due_products": [stocked(2, "Yoghurt", 2, "2026-09-13")],
    #: ⚠️ Measured: the expired butter is overdue as well.
    "overdue_products": [stocked(1, "Milk", 1, "2026-09-09"), BUTTER],
    "expired_products": [BUTTER],
    "missing_products": [{"id": 4, "name": "Coffee", "amount_missing": 2, "is_partly_in_stock": 0,
                          "product": {"id": 4, "name": "Coffee", "min_stock_amount": 2, "active": 1}}],
}


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


@respx.mock
async def test_every_product_once_the_worst_first(ctx: Context) -> None:
    route = respx.get(f"{GR}/api/stock/volatile").mock(return_value=httpx.Response(200, json=VOLATILE))
    data = await get_adapter("grocy").fetch("stock", CONFIG, {"days": 5, "limit": 12}, ctx)
    assert route.calls.last.request.headers["GROCY-API-KEY"] == "made-up-key"
    assert route.calls.last.request.url.params["due_soon_days"] == "5"
    assert [(row["title"], row["subtitle"], row["status"], row["value"]) for row in data.items] == [
        ("Butter", "Expired · 2026-09-10", "bad", "1"),
        ("Milk", "Overdue · 2026-09-09", "warn", "1"),
        ("Yoghurt", "Due soon · 2026-09-13", "unknown", "2"),
        ("Coffee", "Below minimum", "unknown", "2"),
    ]
    assert data.secondary == [{"label": "Overdue", "value": 2}] and data.status == "bad"


@respx.mock
async def test_overdue_without_anything_expired_is_a_warning(ctx: Context) -> None:
    respx.get(f"{GR}/api/stock/volatile").mock(return_value=httpx.Response(200, json={
        **VOLATILE, "overdue_products": [stocked(1, "Milk", 1.5, "2026-09-09")], "expired_products": []}))
    data = await get_adapter("grocy").fetch("stock", CONFIG, {}, ctx)
    assert data.status == "warn" and data.items[0]["value"] == "1.5"


@respx.mock
async def test_the_summary(ctx: Context) -> None:
    respx.get(f"{GR}/api/stock/volatile").mock(return_value=httpx.Response(200, json=VOLATILE))
    data = await get_adapter("grocy").fetch("summary", CONFIG, {}, ctx)
    assert data.primary == {"label": "Overdue", "value": 2}
    assert data.secondary == [{"label": "Expired", "value": 1}, {"label": "Due soon", "value": 1}, {"label": "Below minimum", "value": 1}]
    assert data.metrics == {"overdue": 2.0} and data.status == "bad"


@respx.mock
async def test_a_rejected_key_and_something_else(ctx: Context) -> None:
    respx.get(f"{GR}/api/stock/volatile").mock(return_value=httpx.Response(401, text=""))
    with pytest.raises(AuthFailed):
        await get_adapter("grocy").fetch("summary", CONFIG, {}, ctx)
    respx.get(f"{GR}/api/stock/volatile").mock(return_value=httpx.Response(200, json={"hello": "world"}))
    with pytest.raises(AdapterError) as other:
        await get_adapter("grocy").fetch("summary", CONFIG, {}, Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={}))
    assert other.value.code == "not_grocy"


@respx.mock
async def test_the_connection_test(ctx: Context) -> None:
    respx.get(f"{GR}/api/system/info").mock(return_value=httpx.Response(200, json={
        "grocy_version": {"Version": "4.7.1", "ReleaseDate": "2026-09-04"}, "php_version": "8.5.6", "db_version": 257}))
    respx.get(f"{GR}/api/stock").mock(return_value=httpx.Response(200, json=[stocked(1, "Milk", 1, "2026-09-09"), BUTTER]))
    assert await get_adapter("grocy").test(CONFIG, ctx) == "Grocy 4.7.1 answers with 2 products in stock."
