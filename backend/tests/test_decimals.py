"""Decimals on a Home Assistant entity and a JSON API value (#78).

The front end wrote every number below 10 with one decimal and every other
with none, whatever the card was set to: a rate of 0.07 per kWh read 0.1. A
card now says how many decimals it was asked for; one that was not asked keeps
the old way, so boards already set up read as they did.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import Context
from app.adapters.homeassistant import decimals


def _entity(state: str, unit: str = "GBP/kWh") -> dict:
    return {"entity_id": "sensor.octopus_rate", "state": state, "attributes": {"unit_of_measurement": unit, "friendly_name": "Rate"},
            "last_changed": "2026-11-26T10:00:00+00:00"}


def test_the_entity_card_offers_decimals_and_leaves_them_empty() -> None:
    entity = next(w for w in get_adapter("homeassistant").widgets if w.kind == "entity")
    field = next(f for f in entity.options if f.name == "decimals")
    assert field.type == "number" and field.default in (None, "")


def test_an_entity_with_decimals_set_tells_the_card_how_many() -> None:
    adapter = get_adapter("homeassistant")
    shown = adapter._entity_widget(_entity("0.0712"), {"entity_id": "sensor.octopus_rate", "decimals": 2.0})
    assert shown.primary["value"] == 0.07 and shown.primary["decimals"] == 2
    assert shown.metrics["value"] == pytest.approx(0.0712), "the history keeps the reading as it came"
    three = adapter._entity_widget(_entity("0.0712"), {"entity_id": "sensor.octopus_rate", "decimals": "3"})
    assert three.primary["value"] == 0.071 and three.primary["decimals"] == 3
    whole = adapter._entity_widget(_entity("5.004"), {"entity_id": "sensor.octopus_rate", "decimals": 0})
    assert whole.primary["value"] == 5 and whole.primary["decimals"] == 0


def test_an_entity_without_decimals_reads_as_before() -> None:
    adapter = get_adapter("homeassistant")
    for options in ({}, {"decimals": None}, {"decimals": ""}):
        shown = adapter._entity_widget(_entity("5.0412"), {"entity_id": "sensor.octopus_rate", **options})
        assert shown.primary["value"] == 5.04 and "decimals" not in shown.primary, options


def test_a_word_is_left_alone_whatever_the_decimals() -> None:
    shown = get_adapter("homeassistant")._entity_widget(_entity("on", ""), {"entity_id": "x", "decimals": 2})
    assert shown.primary["value"] == "on" and "decimals" not in shown.primary


def test_decimals_are_kept_between_none_and_six() -> None:
    assert decimals({"decimals": -3}) == 0 and decimals({"decimals": 40}) == 6 and decimals({"decimals": "two"}) is None


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


@respx.mock
async def test_the_json_api_value_tells_the_card_its_decimals(ctx: Context) -> None:
    respx.get("https://api.example.com/").mock(return_value=httpx.Response(200, json={"rate": 0.0712, "name": "x"}))
    adapter = get_adapter("jsonapi")
    shown = await adapter.fetch("value", {"url": "https://api.example.com/"}, {"value_path": "rate", "decimals": 2}, ctx)
    assert shown.primary["value"] == 0.07 and shown.primary["decimals"] == 2
    word = await adapter.fetch("value", {"url": "https://api.example.com/"}, {"value_path": "name", "decimals": 2}, ctx)
    assert "decimals" not in word.primary, "a word has no decimals"
