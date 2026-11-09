"""'Calculate' on the JSON API cards (#67): a formula over what the path found.

The formulas are those of the custom cards, with one word more: ``value``.
Without a formula every card reads exactly as it did.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, Context

API = "https://api.example.com"
CONFIG = {"url": API}
#: The shape of aviationweather.gov's METAR as GeoJSON, which the issue reads.
METAR = {"features": [{"properties": {"id": "KLQK", "temp": 21.5, "dewp": "12,0", "wspd": 8}}]}
JOBS = {"jobs": [{"name": "photos", "kb": 2048, "files": 4}, {"name": "music", "kb": "512", "files": 0}, {"name": "empty"}]}


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


def test_both_cards_offer_calculate_and_it_starts_empty() -> None:
    for widget in get_adapter("jsonapi").widgets:
        field = next((one for one in widget.options if one.name == "calculate"), None)
        assert field is not None, widget.kind
        assert not field.default and not field.required


@respx.mock
async def test_the_value_turns_celsius_into_fahrenheit_and_the_rest_follows(ctx: Context) -> None:
    respx.get(API).mock(return_value=httpx.Response(200, json=METAR))
    options = {"value_path": "features[0].properties.temp", "calculate": "value * 9 / 5 + 32", "decimals": 1,
               "unit": "°F", "warn_above": 70}
    data = await get_adapter("jsonapi").fetch("value", CONFIG, options, ctx)
    assert data.primary["value"] == 70.7
    assert data.metrics == {"value": pytest.approx(70.7)}, "the history keeps the converted number"
    assert data.status == "warn", "the thresholds are read against the converted number"


@respx.mock
async def test_without_a_formula_nothing_changes(ctx: Context) -> None:
    respx.get(API).mock(return_value=httpx.Response(200, json=METAR))
    data = await get_adapter("jsonapi").fetch("value", CONFIG, {"value_path": "features[0].properties.temp", "decimals": 1, "calculate": "  "}, ctx)
    assert data.primary["value"] == 21.5


@respx.mock
async def test_a_formula_reads_other_fields_and_a_number_written_with_a_comma(ctx: Context) -> None:
    respx.get(API).mock(return_value=httpx.Response(200, json=METAR))
    options = {"value_path": "features[0].properties.dewp", "calculate": "value - {features[0].properties.temp}", "decimals": 1}
    data = await get_adapter("jsonapi").fetch("value", CONFIG, options, ctx)
    assert data.primary["value"] == -9.5


@respx.mock
async def test_a_value_the_formula_cannot_use_shows_nothing_rather_than_the_raw_one(ctx: Context) -> None:
    respx.get(API).mock(return_value=httpx.Response(200, json=METAR))
    options = {"value_path": "features[0].properties.id", "calculate": "value * 9 / 5 + 32"}
    data = await get_adapter("jsonapi").fetch("value", CONFIG, options, ctx)
    assert data.primary["value"] is None
    assert data.metrics == {}


@respx.mock
@pytest.mark.parametrize("formula", ["value ** 2", "import os", "__import__('os')", "value +", "{features[0"])
async def test_a_formula_that_is_not_one_is_refused_with_its_reason(ctx: Context, formula: str) -> None:
    respx.get(API).mock(return_value=httpx.Response(200, json=METAR))
    with pytest.raises(AdapterError) as refused:
        await get_adapter("jsonapi").fetch("value", CONFIG, {"value_path": "features[0].properties.temp", "calculate": formula}, ctx)
    assert refused.value.code == "formula_error"
    assert refused.value.message.startswith("The formula in Calculate cannot be read: ")


@respx.mock
async def test_a_field_named_value_inside_braces_stays_a_field(ctx: Context) -> None:
    respx.get(API).mock(return_value=httpx.Response(200, json={"value": 3, "data": {"value": 5, "n": 10}}))
    options = {"value_path": "data.n", "calculate": "value * {value} + {data.value}"}
    data = await get_adapter("jsonapi").fetch("value", CONFIG, options, ctx)
    assert data.primary["value"] == 35


@respx.mock
async def test_each_badge_may_carry_its_own_formula(ctx: Context) -> None:
    respx.get(API).mock(return_value=httpx.Response(200, json=METAR))
    options = {"value_path": "features[0].properties.temp", "decimals": 1,
               "badges": "Dew point | features[0].properties.dewp | °F | value * 9 / 5 + 32\nWind | features[0].properties.wspd | kt"}
    data = await get_adapter("jsonapi").fetch("value", CONFIG, options, ctx)
    assert data.secondary == [{"label": "Dew point", "value": 53.6, "unit": "°F"}, {"label": "Wind", "value": 8, "unit": "kt"}]
    assert data.primary["value"] == 21.5, "the badge's formula is the badge's alone"


@respx.mock
async def test_the_list_calculates_each_entry_with_its_own_fields(ctx: Context) -> None:
    respx.get(API).mock(return_value=httpx.Response(200, json=JOBS))
    options = {"items_path": "jobs", "title_path": "name", "value_path": "kb", "calculate": "value / 1024"}
    data = await get_adapter("jsonapi").fetch("list", CONFIG, options, ctx)
    assert [item["value"] for item in data.items] == [2, 0.5, None]
    options = {"items_path": "jobs", "title_path": "name", "calculate": "{kb} / max({files}, 1)"}
    data = await get_adapter("jsonapi").fetch("list", CONFIG, options, ctx)
    assert [item["value"] for item in data.items] == [512, 512, None]


def test_the_preview_shows_the_converted_number() -> None:
    adapter = get_adapter("jsonapi")
    plain = adapter.demo("value", {}, tick=3).primary["value"]
    converted = adapter.demo("value", {"calculate": "value * 9 / 5 + 32"}, tick=3).primary["value"]
    assert converted == pytest.approx(plain * 9 / 5 + 32, abs=0.1)
