"""The weather card's hourly strip, air quality, UV and pollen, against recorded Open-Meteo answers.

The recordings are real answers for a large city (coordinates 52.52, 13.41 and
40.71, -74.01), nothing else. No test here touches the network.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import Context
from app.adapters.weather import aqi_level, pollen_level, uv_level

FIXTURES = Path(__file__).parent / "fixtures"
FORECAST = "https://api.open-meteo.com/v1/forecast"
AIR = "https://air-quality-api.open-meteo.com/v1/air-quality"
PLACE = {"latitude": 52.52, "longitude": 13.41, "place": "Berlin"}


def fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


async def fetch(ctx: Context, **options: Any):
    return await get_adapter("weather").fetch("current", {}, {**PLACE, **options}, ctx)


# -- a card that asks for nothing is not changed -----------------------------


@respx.mock
async def test_a_card_without_the_new_options_sends_the_old_request_and_gets_the_old_answer(ctx: Context) -> None:
    forecast = respx.get(FORECAST).mock(return_value=httpx.Response(200, json=fixture("open_meteo.json")))
    air = respx.get(AIR).mock(return_value=httpx.Response(200, json=fixture("open_meteo_air_berlin.json")))
    data = await fetch(ctx, days=3)
    params = dict(forecast.calls.last.request.url.params)
    assert set(params) == {"latitude", "longitude", "current", "daily", "timezone", "forecast_days"}
    assert params["daily"] == "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max"
    assert params["forecast_days"] == "3"
    assert not air.called
    assert set(data.meta) == {"condition", "is_day", "place"}


# -- the hourly strip --------------------------------------------------------


@respx.mock
async def test_the_strip_starts_at_the_current_hour_and_marks_the_night_and_the_sun(ctx: Context) -> None:
    forecast = respx.get(FORECAST).mock(return_value=httpx.Response(200, json=fixture("open_meteo_hourly.json")))
    data = await fetch(ctx, hours="24", days=1)
    params = forecast.calls.last.request.url.params
    # One forecast day would end at midnight: the strip needs the next day's sunrise too.
    assert params["forecast_days"] == "2" and params["forecast_hours"] == "24"
    assert "precipitation_probability" in params["hourly"] and params["daily"].endswith("sunrise,sunset")
    strip = data.meta["hourly"]
    assert strip["hours"] == 24 and len(strip["items"]) == 24
    first = strip["items"][0]
    assert first["at"] == "2026-10-27T16:00" and first["temperature"] == 15.1 and first["night"] is False
    assert [row["night"] for row in strip["items"][:3]] == [False, True, True]
    # The sun goes down within the first hour and comes up the next morning; times are the place's own.
    assert strip["sun"] == [{"index": 0, "kind": "sunset", "time": "16:46"}, {"index": 14, "kind": "sunrise", "time": "06:55"}]
    assert strip["items"][14]["at"] == "2026-10-28T06:00" and strip["items"][14]["night"] is True and strip["items"][15]["night"] is False
    # The forecast days stay what the card asked for, although two were fetched.
    assert len(data.items) == 1


@respx.mock
async def test_twelve_hours_are_twelve_and_a_foreign_value_means_none(ctx: Context) -> None:
    respx.get(FORECAST).mock(return_value=httpx.Response(200, json=fixture("open_meteo_hourly.json")))
    assert (await fetch(ctx, hours=12)).meta["hourly"]["hours"] == 12
    assert "hourly" not in (await fetch(ctx, hours="7")).meta
    assert "hourly" not in (await fetch(ctx, hours="0")).meta
    assert "hourly" not in (await fetch(ctx, hours="soon")).meta


@respx.mock
async def test_the_strip_follows_the_places_clock_not_the_servers(ctx: Context) -> None:
    """The answer says it is 20:20 there; the strip starts at 20:00 there, whatever time it is here."""
    answer = fixture("open_meteo_hourly.json")
    answer["current"]["time"] = "2026-10-27T20:20"
    respx.get(FORECAST).mock(return_value=httpx.Response(200, json=answer))
    first = (await fetch(ctx, hours=12)).meta["hourly"]["items"][0]
    assert first["at"] == "2026-10-27T20:00"
    assert first["night"] is True


@respx.mock
async def test_a_missing_hour_is_a_gap_not_a_zero(ctx: Context) -> None:
    answer = fixture("open_meteo_hourly.json")
    answer["hourly"]["precipitation_probability"][2] = None
    respx.get(FORECAST).mock(return_value=httpx.Response(200, json=answer))
    rows = (await fetch(ctx, hours=12)).meta["hourly"]["items"]
    assert rows[2]["rain"] is None and rows[1]["rain"] == 0.0


# -- air quality, UV and pollen ----------------------------------------------


@respx.mock
async def test_air_quality_uv_and_pollen_in_europe(ctx: Context) -> None:
    forecast = respx.get(FORECAST).mock(return_value=httpx.Response(200, json=fixture("open_meteo_hourly.json")))
    air = respx.get(AIR).mock(return_value=httpx.Response(200, json=fixture("open_meteo_air_berlin.json")))
    data = await fetch(ctx, aqi=True, uv=True, pollen=True)
    asked = air.calls.last.request.url.params
    assert asked["current"].split(",") == ["european_aqi", "uv_index", *(f"{kind}_pollen" for kind in ("alder", "birch", "grass", "mugwort", "olive", "ragweed"))]
    assert forecast.calls.last.request.url.params["daily"].endswith("uv_index_max")
    found = data.meta["air"]
    assert found["aqi"] == {"value": 31, "level": "fair"}
    assert found["uv"] == {"value": 0.1, "level": "low", "peak": 2.0}
    # Out of season the API says 0.0 for every kind: an answer, shown as "none".
    assert found["pollen"] == {"level": "none", "items": []}


@respx.mock
async def test_pollen_in_season_lists_the_strongest_three(ctx: Context) -> None:
    respx.get(FORECAST).mock(return_value=httpx.Response(200, json=fixture("open_meteo_hourly.json")))
    answer = fixture("open_meteo_air_berlin.json")
    answer["current"].update(alder_pollen=3.0, birch_pollen=240.0, grass_pollen=61.0, mugwort_pollen=12.0, olive_pollen=0.0)
    respx.get(AIR).mock(return_value=httpx.Response(200, json=answer))
    pollen = (await fetch(ctx, pollen=True)).meta["air"]["pollen"]
    assert pollen["level"] == "very-high"
    assert pollen["items"] == [
        {"kind": "birch", "value": 240, "level": "very-high"},
        {"kind": "grass", "value": 61, "level": "high"},
        {"kind": "mugwort", "value": 12, "level": "moderate"},
    ]


@respx.mock
async def test_outside_europe_pollen_is_left_out_without_a_word(ctx: Context) -> None:
    respx.get(FORECAST).mock(return_value=httpx.Response(200, json=fixture("open_meteo_hourly.json")))
    respx.get(AIR).mock(return_value=httpx.Response(200, json=fixture("open_meteo_air_newyork.json")))
    data = await fetch(ctx, aqi=True, pollen=True, latitude=40.71, longitude=-74.01)
    assert data.meta["air"] == {"aqi": {"value": 23, "level": "fair"}}
    assert "air_unavailable" not in data.meta


@respx.mock
async def test_only_what_is_switched_on_is_asked_for_and_shown(ctx: Context) -> None:
    respx.get(FORECAST).mock(return_value=httpx.Response(200, json=fixture("open_meteo_hourly.json")))
    air = respx.get(AIR).mock(return_value=httpx.Response(200, json=fixture("open_meteo_air_berlin.json")))
    data = await fetch(ctx, uv=True)
    assert air.calls.last.request.url.params["current"] == "uv_index"
    assert list(data.meta["air"]) == ["uv"]


@respx.mock
async def test_a_failing_air_service_leaves_the_weather_standing(ctx: Context) -> None:
    respx.get(FORECAST).mock(return_value=httpx.Response(200, json=fixture("open_meteo_hourly.json")))
    respx.get(AIR).mock(return_value=httpx.Response(500, json={"error": True, "reason": "down"}))
    data = await fetch(ctx, aqi=True, hours=12)
    assert data.primary["value"] == 14.8
    assert data.meta["air"] == {} and data.meta["air_unavailable"] is True
    assert data.meta["hourly"]["hours"] == 12


@respx.mock
async def test_an_unreachable_air_service_is_the_same(ctx: Context) -> None:
    respx.get(FORECAST).mock(return_value=httpx.Response(200, json=fixture("open_meteo_hourly.json")))
    respx.get(AIR).mock(side_effect=httpx.ConnectError("no route"))
    data = await fetch(ctx, aqi=True)
    assert data.meta["air_unavailable"] is True


def test_the_bands_follow_the_published_limits() -> None:
    assert [aqi_level(v) for v in (0, 20, 21, 40, 41, 60, 61, 80, 81, 100, 101)] == [
        "good", "good", "fair", "fair", "moderate", "moderate", "poor", "poor", "very-poor", "very-poor", "extremely-poor"]
    assert [uv_level(v) for v in (0, 2.9, 3, 5.9, 6, 7.9, 8, 10.9, 11)] == [
        "low", "low", "moderate", "moderate", "high", "high", "very-high", "very-high", "extreme"]
    assert [pollen_level(v) for v in (0, 1, 9.9, 10, 49, 50, 199, 200)] == [
        "none", "low", "low", "moderate", "moderate", "high", "high", "very-high"]


# -- demo ---------------------------------------------------------------------


def test_demo_has_data_for_everything_switched_on_and_nothing_else() -> None:
    adapter = get_adapter("weather")
    plain = adapter.demo("current", {}, 5).meta
    assert set(plain) == {"condition", "is_day", "place"}
    everything = adapter.demo("current", {"hours": "24", "aqi": True, "uv": True, "pollen": True}, 5).meta
    strip = everything["hourly"]
    assert strip["hours"] == 24 and len(strip["items"]) == 24
    assert {event["kind"] for event in strip["sun"]} == {"sunrise", "sunset"}
    assert any(row["night"] for row in strip["items"]) and any(not row["night"] for row in strip["items"])
    assert set(everything["air"]) == {"aqi", "uv", "pollen"}
    assert adapter.demo("current", {"hours": 12}, 5).meta["hourly"]["hours"] == 12
    # It moves with the tick, like every demo.
    assert adapter.demo("current", {"aqi": True}, 400).meta["air"] != adapter.demo("current", {"aqi": True}, 5).meta["air"]
