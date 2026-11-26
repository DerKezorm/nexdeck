"""Home Assistant: several entities as one number, and several as lines over a period (#82).

The summary card reads every state in one call (or from the live connection)
and counts a group as the entities in it. The history card reads Home
Assistant's own history, so the chart is full the moment it is placed.
"""

from __future__ import annotations

import datetime as dt
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import Context
from app.adapters.homeassistant import aggregate, history_points

HA = "http://ha.example.com:8123"
CONFIG = {"url": HA, "token": "t"}


def state(name: str, value: str, unit: str = "", **attributes) -> dict:
    return {"entity_id": name, "state": value, "attributes": {"unit_of_measurement": unit, **attributes} if unit else attributes,
            "last_changed": "2026-11-26T10:00:00+00:00"}


PLUGS = [state("sensor.plug_1", "40.5", "W"), state("sensor.plug_2", "12", "W"), state("sensor.plug_3", "unavailable", "W"),
         state("binary_sensor.window_kitchen", "on"), state("binary_sensor.window_bath", "off"), state("cover.garage", "open"),
         state("group.windows", "on", entity_id=["binary_sensor.window_kitchen", "binary_sensor.window_bath"]),
         state("sensor.indoor", "21.4", "°C", friendly_name="Indoor"), state("sensor.outdoor", "6.2", "°C", friendly_name="Outdoor")]


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


def summary(ctx: Context, **options):
    return get_adapter("homeassistant").fetch("summary", CONFIG, options, ctx)


@respx.mock
async def test_the_sum_leaves_out_what_is_unavailable_and_says_so(ctx: Context) -> None:
    respx.get(f"{HA}/api/states").mock(return_value=httpx.Response(200, json=PLUGS))
    shown = await summary(ctx, entity_ids="sensor.plug_1\nsensor.plug_2\nsensor.plug_3", aggregation="sum")
    assert shown.primary["value"] == 52.5 and shown.primary["unit"] == "W"
    assert shown.metrics["value"] == 52.5
    assert shown.status == "warn", "one plug did not answer"
    assert {"label": "Entities", "value": "2 of 3"} in shown.secondary


@respx.mock
async def test_average_lowest_and_highest(ctx: Context) -> None:
    respx.get(f"{HA}/api/states").mock(return_value=httpx.Response(200, json=PLUGS))
    ids = "sensor.plug_1\nsensor.plug_2"
    assert (await summary(ctx, entity_ids=ids, aggregation="mean")).primary["value"] == 26.25
    assert (await summary(ctx, entity_ids=ids, aggregation="min")).primary["value"] == 12
    assert (await summary(ctx, entity_ids=ids, aggregation="max")).primary["value"] == 40.5
    whole = await summary(ctx, entity_ids=ids, aggregation="sum", decimals=0)
    assert whole.primary["value"] == 52 and whole.primary["decimals"] == 0


@respx.mock
async def test_a_group_counts_as_its_members_and_count_on_counts_what_is_on_or_open(ctx: Context) -> None:
    respx.get(f"{HA}/api/states").mock(return_value=httpx.Response(200, json=PLUGS))
    shown = await summary(ctx, entity_ids="group.windows\ncover.garage", aggregation="count_on", label="Open")
    assert shown.primary["value"] == 2 and shown.primary["unit"] == "" and shown.primary["label"] == "Open"
    assert {"label": "Entities", "value": "3 of 3"} in shown.secondary
    counted = await summary(ctx, entity_ids="group.windows", aggregation="count")
    assert counted.primary["value"] == 2 and shown.status == "ok"


@respx.mock
async def test_an_entity_that_is_not_there_is_named(ctx: Context) -> None:
    respx.get(f"{HA}/api/states").mock(return_value=httpx.Response(200, json=PLUGS))
    shown = await summary(ctx, entity_ids="sensor.plug_1\nsensor.gone", aggregation="sum", unit="watts")
    assert shown.primary["value"] == 40.5 and shown.primary["unit"] == "watts"
    assert shown.status == "warn" and {"label": "Not found", "value": "sensor.gone"} in shown.secondary


@respx.mock
async def test_mixed_units_show_none_and_words_make_no_sum(ctx: Context) -> None:
    respx.get(f"{HA}/api/states").mock(return_value=httpx.Response(200, json=PLUGS))
    mixed = await summary(ctx, entity_ids="sensor.plug_1\nsensor.indoor", aggregation="sum")
    assert mixed.primary["unit"] == ""
    words = await summary(ctx, entity_ids="cover.garage", aggregation="sum")
    assert words.primary["value"] is None and words.status == "unknown" and words.metrics == {}


async def test_the_live_connection_is_used_when_it_is_there() -> None:
    live = Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={"hass_states": {one["entity_id"]: one for one in PLUGS}})
    with respx.mock(assert_all_called=False) as router:
        asked = router.get(f"{HA}/api/states").mock(return_value=httpx.Response(500))
        shown = await get_adapter("homeassistant").fetch("summary", CONFIG, {"entity_ids": "sensor.plug_1\nsensor.plug_2"}, live)
    assert shown.primary["value"] == 52.5 and not asked.called


def test_aggregate_by_itself() -> None:
    assert aggregate("sum", ["1", "2", "x"]) == 3
    assert aggregate("count", ["1", "x"]) == 2
    assert aggregate("count_on", ["on", "off", "open", "closed", "unlocked"]) == 3
    assert aggregate("mean", ["x"]) is None


# -- the history chart ---------------------------------------------------------------------


NOW = dt.datetime(2026, 11, 26, 12, 0, tzinfo=dt.UTC)


def at(hours_ago: float) -> str:
    return (NOW - dt.timedelta(hours=hours_ago)).isoformat()


HISTORY = [
    # Listed outdoor first: the card goes by the entity, not by the order.
    [{"entity_id": "sensor.outdoor", "state": "5.0", "last_changed": at(30)}, {"state": "7.0", "last_changed": at(6)}],
    [{"entity_id": "sensor.indoor", "state": "20.0", "last_changed": at(24)}, {"state": "unavailable", "last_changed": at(12)},
     {"state": "22.0", "last_changed": at(11.9)}],
]


@respx.mock
async def test_the_history_draws_one_line_per_entity_over_the_period(ctx: Context) -> None:
    respx.get(f"{HA}/api/states").mock(return_value=httpx.Response(200, json=PLUGS))
    route = respx.get(url__startswith=f"{HA}/api/history/period/").mock(return_value=httpx.Response(200, json=HISTORY))
    shown = await get_adapter("homeassistant")._history(CONFIG, {"entity_ids": "sensor.indoor | Inside\nsensor.outdoor", "range": "24h"}, ctx,
                                                     now=NOW.timestamp())
    asked = urlsplit(str(route.calls[0].request.url))
    assert asked.path.endswith((NOW - dt.timedelta(hours=24)).isoformat(timespec="seconds"))
    query = parse_qs(asked.query, keep_blank_values=True)
    assert query["filter_entity_id"] == ["sensor.indoor,sensor.outdoor"] and "minimal_response" in query
    lines = shown.meta["lines"]
    assert [line["label"] for line in lines] == ["Inside", "Outdoor"] and shown.meta["unit"] == "°C"
    assert all(len(line["points"]) == 120 for line in lines)
    inside = [value for _, value in lines[0]["points"]]
    assert inside[0] == 20.0 and inside[-1] == 22.0, "a state holds until it changes"
    outdoor = [value for _, value in lines[1]["points"]]
    assert outdoor[0] == 5.0 and outdoor[-1] == 7.0, "the state from before the period carries in"
    assert shown.primary == {"label": "Inside", "value": 21.4, "unit": "°C"} and shown.status == "ok"


@respx.mock
async def test_an_entity_without_history_is_named_and_none_at_all_is_said(ctx: Context) -> None:
    respx.get(f"{HA}/api/states").mock(return_value=httpx.Response(200, json=PLUGS))
    respx.get(url__startswith=f"{HA}/api/history/period/").mock(return_value=httpx.Response(200, json=HISTORY[:1]))
    shown = await get_adapter("homeassistant")._history(CONFIG, {"entity_ids": "sensor.outdoor\nsensor.gone"}, ctx, now=NOW.timestamp())
    assert len(shown.meta["lines"]) == 1 and shown.status == "warn"
    assert {"label": "Not found", "value": "sensor.gone"} in shown.secondary
    respx.get(url__startswith=f"{HA}/api/history/period/").mock(return_value=httpx.Response(200, json=[]))
    ctx.cache.clear()
    empty = await get_adapter("homeassistant")._history(CONFIG, {"entity_ids": "sensor.gone2"}, ctx, now=NOW.timestamp())
    assert empty.status == "unknown" and empty.meta["empty"] == "No history in this period"


def test_history_points_carry_a_state_and_leave_a_gap_where_it_was_no_number() -> None:
    points = history_points([(0, 1.0), (50, None), (75, 3.0)], start=0, end=100, count=4)
    assert [value for _, value in points] == [1.0, None, 3.0, 3.0]
    assert [at for at, _ in points] == [25, 50, 75, 100]
    assert [value for _, value in history_points([(60, 2.0)], start=0, end=100, count=4)] == [None, None, 2.0, 2.0]


def test_a_state_from_before_the_period_is_not_averaged_into_its_first_step() -> None:
    # It only says where the line starts; a change inside the first step is what that step shows.
    points = history_points([(-10, 100.0), (10, 2.0)], start=0, end=100, count=4)
    assert [value for _, value in points] == [2.0, 2.0, 2.0, 2.0]
