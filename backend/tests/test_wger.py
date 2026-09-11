"""wger, against the answers of a live wger 2.7.0 (11.09.2026)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AuthFailed, Context
from app.adapters.wger import WgerAdapter

WG = "http://wger.example.com"
CONFIG = {"url": WG, "token": "made-up-key"}
NOW = datetime(2026, 9, 11, 13, 0, tzinfo=UTC)


def entry(date: str, weight: str) -> dict[str, Any]:
    return {"id": f"made-up-{date}", "date": f"{date}T00:00:00Z", "weight": weight, "user": 1}


#: Newest first, as asked for with ordering=-date. The weight is a string.
ENTRIES = [entry("2026-09-11", "81.90"), entry("2026-09-09", "81.70"), entry("2026-09-04", "82.00"), entry("2026-08-28", "82.40"),
           entry("2026-08-12", "83.10"), entry("2026-07-28", "83.60"), entry("2026-07-13", "84.20")]


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


def _server(entries: list[dict[str, Any]], unit: str = "kg") -> respx.Route:
    respx.get(f"{WG}/api/v2/userprofile/").mock(return_value=httpx.Response(200, json={"username": "admin", "weight_unit": unit, "weight_rounding": None}))
    return respx.get(f"{WG}/api/v2/weightentry/").mock(side_effect=lambda request: httpx.Response(200, json={
        "count": len(entries), "next": None, "previous": None, "results": entries[: int(request.url.params["limit"])]}))


def test_the_weight_and_its_change_over_thirty_days() -> None:
    data = WgerAdapter._weight(ENTRIES, "kg", NOW)
    assert data.primary == {"label": "Weight", "value": "81.9", "unit": "kg"}
    # Against the last entry on or before 12 August.
    assert data.secondary == [{"label": "30 days", "value": "-1.2 kg"}, {"label": "Last weigh-in", "value": "2026-09-11"}]
    assert data.metrics == {"weight": 81.9}


def test_without_a_month_of_entries_there_is_no_change_to_show() -> None:
    data = WgerAdapter._weight(ENTRIES[:3], "kg", NOW)
    assert data.secondary == [{"label": "Last weigh-in", "value": "2026-09-11"}]
    empty = WgerAdapter._weight([], "kg", NOW)
    assert empty.status == "unknown" and empty.primary["value"] is None


@respx.mock
async def test_the_key_goes_as_token_not_bearer(ctx: Context) -> None:
    """⚠️ Measured: the same key as Bearer got 500."""
    route = _server(ENTRIES, unit="lb")
    data = await get_adapter("wger").fetch("weight", CONFIG, {}, ctx)
    assert route.calls.last.request.headers["Authorization"] == "Token made-up-key"
    assert dict(route.calls.last.request.url.params) == {"ordering": "-date", "limit": "100"}
    assert data.primary["unit"] == "lb"


@respx.mock
async def test_weigh_ins_with_the_change_from_the_one_before(ctx: Context) -> None:
    route = _server(ENTRIES)
    data = await get_adapter("wger").fetch("entries", CONFIG, {"limit": 3}, ctx)
    # One more than shown, so the last row has something to compare with.
    assert route.calls.last.request.url.params["limit"] == "4"
    assert [(row["title"], row["subtitle"], row["value"]) for row in data.items] == [
        ("2026-09-11", "+0.2 kg", "81.9 kg"), ("2026-09-09", "-0.3 kg", "81.7 kg"), ("2026-09-04", "-0.4 kg", "82.0 kg")]


@respx.mock
async def test_a_rejected_key(ctx: Context) -> None:
    respx.get(f"{WG}/api/v2/userprofile/").mock(return_value=httpx.Response(403, json={"detail": "Invalid token."}))
    with pytest.raises(AuthFailed):
        await get_adapter("wger").fetch("weight", CONFIG, {}, ctx)


@respx.mock
async def test_the_connection_test(ctx: Context) -> None:
    respx.get(f"{WG}/api/v2/version/").mock(return_value=httpx.Response(200, json="2.7.0"))
    _server(ENTRIES)
    assert await get_adapter("wger").test(CONFIG, ctx) == "wger 2.7.0 answers with 7 weight entries."
