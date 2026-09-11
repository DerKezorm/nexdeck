"""Dawarich, against the answers of a live Dawarich 1.14.3 (11.09.2026)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AuthFailed, Context
from app.adapters.dawarich import MONTHS, DawarichAdapter

DW = "http://dawarich.example.com"
CONFIG = {"url": DW, "api_key": "made-up-key"}
#: 33 minutes after the last point, and far enough from any real clock that an age counted from it shows.
NOW = datetime(2026, 9, 11, 12, 30, tzinfo=UTC)
MONTHLY = {name: {"august": 8, "september": 44}.get(name, 0) for name in MONTHS}
#: Measured after the hourly job had run: whole kilometres a month, a yearly total that is not their sum.
STATS = {"totalDistanceKm": 53, "totalPointsTracked": 144, "totalReverseGeocodedPoints": 0, "totalCountriesVisited": 0, "totalCitiesVisited": 0,
         "yearlyStats": [{"year": 2026, "totalDistanceKm": 53, "totalCountriesVisited": 0, "totalCitiesVisited": 0, "monthlyDistanceKm": MONTHLY}]}
#: ⚠️ Measured right after the import: the points are counted, the distance is not yet.
FRESH = {"totalDistanceKm": 0, "totalPointsTracked": 144, "totalReverseGeocodedPoints": 0, "totalCountriesVisited": 0, "totalCitiesVisited": 0, "yearlyStats": []}
LAST_POINT: dict[str, Any] = {"id": 12, "timestamp": 1789127799, "latitude": "52.5396", "longitude": "13.39900000979345", "velocity": "1.3", "city": None}


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


def test_this_month_this_year_and_the_last_point() -> None:
    data = DawarichAdapter()._summary(STATS, LAST_POINT, NOW, {})
    assert data.primary == {"label": "This month", "value": 44, "unit": "km"}
    assert data.secondary == [{"label": "This year", "value": "53 km"}, {"label": "Last point", "value": "33 min"}]
    assert data.status == "ok" and data.metrics == {"month_km": 44.0}


def test_a_phone_that_stopped_sending_warns() -> None:
    assert DawarichAdapter()._summary(STATS, LAST_POINT, NOW, {"stale_hours": 0.5}).status == "warn"
    assert DawarichAdapter()._summary(STATS, LAST_POINT, NOW, {"stale_hours": 1}).status == "ok"
    assert DawarichAdapter()._summary(STATS, None, NOW, {}).status == "warn"
    assert DawarichAdapter()._summary(STATS, None, NOW, {"stale_hours": 0}).status == "ok"


def test_before_the_hourly_job_the_distance_is_zero_and_says_so() -> None:
    data = DawarichAdapter()._summary(FRESH, LAST_POINT, NOW, {})
    assert data.primary["value"] == 0 and data.secondary[0] == {"label": "This year", "value": "0 km"}
    assert DawarichAdapter()._months(FRESH, NOW).items == []


def test_the_months_from_the_first_one_tracked() -> None:
    data = DawarichAdapter()._months(STATS, NOW)
    assert [(row["title"], row["subtitle"], row["value"], row["progress"]) for row in data.items] == [
        ("2026-09", "September", "44 km", 100), ("2026-08", "August", "8 km", 18)]
    # Dawarich's own total, not the sum of the rounded months (52).
    assert data.secondary == [{"label": "This year", "value": "53 km"}]


@respx.mock
async def test_the_key_goes_in_a_header_not_in_the_address(ctx: Context) -> None:
    stats = respx.get(f"{DW}/api/v1/stats").mock(return_value=httpx.Response(200, json=STATS))
    points = respx.get(f"{DW}/api/v1/points").mock(return_value=httpx.Response(200, headers={"x-total-pages": "144"}, json=[LAST_POINT]))
    await get_adapter("dawarich").fetch("summary", CONFIG, {}, ctx)
    for route in (stats, points):
        assert route.calls.last.request.headers["Authorization"] == "Bearer made-up-key"
        assert "api_key" not in route.calls.last.request.url.params
    assert dict(points.calls.last.request.url.params) == {"order": "desc", "per_page": "1"}


@respx.mock
async def test_a_rejected_key(ctx: Context) -> None:
    respx.get(f"{DW}/api/v1/stats").mock(return_value=httpx.Response(401, text=""))
    with pytest.raises(AuthFailed):
        await get_adapter("dawarich").fetch("months", CONFIG, {}, ctx)


@respx.mock
async def test_the_connection_test(ctx: Context) -> None:
    respx.get(f"{DW}/api/v1/health").mock(return_value=httpx.Response(200, headers={"x-dawarich-version": "1.14.3"}, json={"status": "ok"}))
    respx.get(f"{DW}/api/v1/stats").mock(return_value=httpx.Response(200, json=STATS))
    assert await get_adapter("dawarich").test(CONFIG, ctx) == "Dawarich 1.14.3 answers: 144 points tracked."
