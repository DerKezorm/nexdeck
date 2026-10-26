"""Statistics cards and a thermostat's history on a home page.

What a page keeps of a card, which sensors are offered for one, how Home
Assistant's statistics and history become points (by the house's calendar,
weighed by time), and that a card asks Home Assistant about its own sensors
and nothing else. The demo house of ``hass_registry`` stands in for a real
one; for a real one, ``_ask`` is replaced by a recorder of commands.
"""

from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient

from app.services import hass_registry, hass_stats, home

from .clock import midday  # noqa: F401 - a fixture, used by name
from .conftest import CSRF, create_user, login, setup_admin
from .test_home_page import _board, _demo_page, _hass, _made

BERLIN = hass_stats.tz("Europe/Berlin")
LIVING = {"rid": "r-temp-living", "entity_id": "sensor.living_room_temperature", "name": "Living room temperature"}
ENERGY = {"rid": "r-energy", "entity_id": "sensor.house_energy", "name": "House energy"}
CARDS = [
    {"id": "line", "type": "stat", "x": 16, "y": 16, "style": "line", "sensors": [LIVING]},
    {"id": "rooms", "type": "stat", "x": 16, "y": 220, "style": "rooms", "width": 520, "height": 210,
     "sensors": [LIVING, {"rid": "r-gone", "entity_id": "sensor.thrown_away", "name": "Old sensor"}]},
    {"id": "bars", "type": "stat", "x": 400, "y": 16, "style": "bars", "sensors": [ENERGY]},
    {"id": "both", "type": "stat", "x": 400, "y": 220, "style": "compare", "sensors": [LIVING]},
    {"id": "heat", "type": "climate", "x": 16, "y": 460, "rid": "r-heat-living", "entity_id": "climate.living_room", "name": "Living room",
     "sensor": LIVING},
    {"id": "bed", "type": "climate", "x": 16, "y": 520, "rid": "r-heat-bed", "entity_id": "climate.bedroom", "name": "Bedroom"},
]


def _at(*parts: int) -> dt.datetime:
    return dt.datetime(*parts, tzinfo=BERLIN)


def _ms(moment: dt.datetime) -> int:
    return int(moment.timestamp() * 1000)


def _cards_page(client: TestClient) -> tuple[dict, dict, dict]:
    board, hass, page = _demo_page(client)
    saved = client.put(f"/api/v1/pages/{page['id']}/home", json={"elements": CARDS}, headers=CSRF)
    assert saved.status_code == 200, saved.text
    return board, hass, page


# ---------------------------------------------------------------------------
# What a page keeps of a card
# ---------------------------------------------------------------------------


def test_a_card_keeps_up_to_six_sensors_once_each_and_a_size_inside_its_bounds() -> None:
    sensors = [{"rid": f"r{i}", "entity_id": f"sensor.s{i}", "name": f"S{i}"} for i in range(8)]
    kept = home.clean_element({"id": "a", "type": "stat", "x": 0, "y": 0, "style": "rooms", "title": " Rooms\x00 ",
                               "sensors": [sensors[0], sensors[0], {"rid": "r-l", "entity_id": "light.ceiling"}, *sensors[1:]],
                               "width": 5000, "height": 10, "colour": "red"})
    assert kept is not None
    assert [one["entity_id"] for one in kept["sensors"]] == [f"sensor.s{i}" for i in range(6)], "twice and a lamp stay out, six at most"
    assert (kept["width"], kept["height"], kept["title"], kept["style"]) == (1200, 80, "Rooms", "rooms")
    assert "colour" not in kept


@pytest.mark.parametrize("raw", [
    {"id": "a", "type": "stat", "x": 0, "y": 0, "sensors": []},
    {"id": "a", "type": "stat", "x": 0, "y": 0, "sensors": [{"rid": "r", "entity_id": "climate.living_room"}]},
    {"id": "a", "type": "stat", "x": 0, "y": 0, "sensors": "sensor.a"},
])
def test_a_card_without_a_sensor_is_not_kept(raw: dict) -> None:
    assert home.clean_element(raw) is None


def test_a_card_of_an_unknown_style_is_a_line_and_a_size_that_is_no_number_is_left_out() -> None:
    kept = home.clean_element({"id": "a", "type": "stat", "x": 0, "y": 0, "style": "pie", "sensors": [LIVING], "width": True, "height": float("nan")})
    assert kept is not None and kept["style"] == "line" and "width" not in kept and "height" not in kept


# ---------------------------------------------------------------------------
# Which sensors are offered
# ---------------------------------------------------------------------------


def test_sensors_with_statistics_or_a_number_are_offered_and_text_and_diagnostics_are_not() -> None:
    entities, devices, areas, states = hass_registry.demo_registry()
    catalogue = hass_stats.demo_catalogue()
    del catalogue["sensor.bedroom_temperature"]
    offered = {one["entity_id"]: one for one in hass_stats.pick_sensors(entities, devices, areas, states, catalogue)}
    assert "sensor.washing_machine_programme" not in offered, "a programme is no number"
    assert "sensor.home_server_cpu_temperature" not in offered, "a diagnostic"
    assert (offered["sensor.house_energy"]["kind"], offered["sensor.house_energy"]["source"]) == ("sum", "statistics")
    assert (offered["sensor.bedroom_temperature"]["kind"], offered["sensor.bedroom_temperature"]["source"]) == ("mean", "history"), \
        "without statistics, from the history"
    assert offered["sensor.living_room_humidity"]["unit"] == "%" and offered["sensor.outdoor_temperature"]["area"] == "Garden"


def test_the_sensors_are_offered_to_those_who_arrange_the_page_and_nobody_else(client: TestClient) -> None:
    setup_admin(client)
    board, _hass_, page = _cards_page(client)
    answer = client.get(f"/api/v1/pages/{page['id']}/home/sensors")
    assert answer.status_code == 200 and answer.json()["problem"] is None
    assert len(answer.json()["sensors"]) == 14
    kim = create_user(client, "kim")
    client.put(f"/api/v1/boards/{board['slug']}/shares", json={"shares": [{"user_id": kim["id"], "level": "view"}]}, headers=CSRF)
    member = TestClient(client.app)
    login(member, "kim", "another-long-password")
    assert member.get(f"/api/v1/pages/{page['id']}/home/sensors").status_code == 403
    assert member.get(f"/api/v1/pages/{page['id']}/home/stats/line").status_code == 200, "but they may look at the cards"


# ---------------------------------------------------------------------------
# Time by the house's calendar
# ---------------------------------------------------------------------------


def test_a_day_is_a_calendar_day_of_the_house_also_when_the_clocks_change() -> None:
    days = hass_stats.steps(_at(2026, 10, 24, 15), _at(2026, 10, 27, 1), "day", BERLIN)
    assert days == [_at(2026, 10, 24), _at(2026, 10, 25), _at(2026, 10, 26), _at(2026, 10, 27)]
    assert days[2] - days[1] == dt.timedelta(hours=25), "the night the clocks go back"
    assert hass_stats.floor(_at(2026, 10, 21, 13, 37), "week", BERLIN) == _at(2026, 10, 19), "a week begins on Monday"
    assert hass_stats.floor(_at(2026, 10, 21, 13, 37), "month", BERLIN) == _at(2026, 10, 1)
    assert hass_stats.following(_at(2026, 12, 1), "month", BERLIN) == _at(2027, 1, 1)
    assert hass_stats.floor(_at(2026, 10, 21, 13, 37), "5minute", BERLIN) == _at(2026, 10, 21, 13, 35)


def test_a_comparison_shows_the_whole_day_against_the_one_before_from_midnight_of_the_house() -> None:
    now = dt.datetime(2026, 10, 20, 22, 30, tzinfo=dt.UTC)  # half past midnight in Berlin
    start, end, before = hass_stats.window("day", now, BERLIN)
    assert (start, end, before) == (_at(2026, 10, 21), _at(2026, 10, 22), _at(2026, 10, 20))
    start, end, before = hass_stats.window("week", now, BERLIN)
    assert (start, end, before) == (_at(2026, 10, 19), _at(2026, 10, 26), _at(2026, 10, 12))
    start, end, before = hass_stats.window("7d", now, BERLIN)
    assert (end - start, before) == (dt.timedelta(days=7), None)


@pytest.mark.parametrize("now", [
    dt.datetime(2026, 10, 26, 13, 0, tzinfo=dt.UTC),  # the day after the clocks went back: yesterday had 25 hours
    dt.datetime(2026, 3, 30, 13, 0, tzinfo=dt.UTC),  # the day after they went forward: 23
])
@pytest.mark.parametrize("period", ["day", "week"])
async def test_the_period_before_lies_on_the_same_clock_times_when_the_clocks_changed(now: dt.datetime, period: str) -> None:
    """Both dates are Mondays, so the week before holds the Sunday the clocks changed."""
    sensor = {**LIVING, "unit": "°C", "kind": "mean", "source": "statistics", "current": 21.0, "unavailable": False}
    start, end, before = hass_stats.window(period, now, BERLIN)
    assert before is not None
    line = (await hass_stats.series({}, {}, [sensor], period, demo=True, now=now))["series"][0]
    assert line["previous"]
    assert all(hass_stats._ms(start) <= point[0] < hass_stats._ms(end) for point in line["previous"]), "moved off this period"
    # Noon of the last day before, after the change, lands on noon of the same day of this period.
    last = 0 if period == "day" else 6
    then = before.astimezone(BERLIN).replace(hour=12) + dt.timedelta(days=last)
    there = start.astimezone(BERLIN).replace(hour=12) + dt.timedelta(days=last)
    assert hass_stats.onto(hass_stats._ms(then), before, start, BERLIN) == hass_stats._ms(there)


# ---------------------------------------------------------------------------
# From answers to points
# ---------------------------------------------------------------------------


def test_statistics_become_points_and_a_step_without_a_value_is_left_out() -> None:
    rows = [{"start": 1792411200000, "mean": 21.04, "min": 20.5, "max": 21.5},
            {"start": "2026-10-19T13:00:00+00:00", "mean": None, "min": 20.0, "max": 21.0},
            {"start": 1792418400000, "mean": None, "min": None, "max": None},
            {"start": None, "mean": 3}]
    assert hass_stats.from_statistics(rows, "mean") == [[1792411200000, 21.04, 20.5, 21.5], [1792414800000, 20.5, 20.0, 21.0]]
    assert hass_stats.from_statistics([{"start": 1792411200000, "change": 0.4567}, {"start": 1792414800000}], "sum") == [[1792411200000, 0.457]]


def test_a_history_is_weighed_by_how_long_each_value_stood_and_holds_until_it_changes() -> None:
    found = [(_at(2026, 10, 20, 8, 50), 20.0), (_at(2026, 10, 20, 9, 45), 22.0), (_at(2026, 10, 20, 10, 30), None)]
    points = hass_stats.from_history(found, _at(2026, 10, 20, 9), _at(2026, 10, 20, 12), "hour", BERLIN)
    # 9 to 10: 45 minutes of 20 and 15 of 22; 10 to 11: 22 until half past, then unavailable; 11 to 12: nothing to tell.
    assert points == [[_ms(_at(2026, 10, 20, 9)), 20.5, 20.0, 22.0], [_ms(_at(2026, 10, 20, 10)), 22.0, 22.0, 22.0]]
    assert hass_stats.from_history([], _at(2026, 10, 20, 9), _at(2026, 10, 20, 12), "hour", BERLIN) == []


def test_a_summary_names_the_lowest_and_highest_with_when_and_a_counter_its_total() -> None:
    points = [[1, 20.0, 19.0, 21.0], [2, 22.0, 21.5, 23.5], [3, 21.0, 18.5, 22.0]]
    assert hass_stats.summary(points, "mean") == {"low": [18.5, 3], "high": [23.5, 2], "mean": 21.0, "total": None}
    assert hass_stats.summary([[1, 1.5], [2, 2.5]], "sum") == {"low": None, "high": None, "mean": 2.0, "total": 4.0}
    assert hass_stats.summary([], "mean")["low"] is None


def test_heating_times_are_the_spans_the_thermostat_said_it_heats_cut_at_midnight() -> None:
    found = [(_at(2026, 10, 19, 23), "heating"), (_at(2026, 10, 20, 0, 30), "idle"), (_at(2026, 10, 20, 6), "preheating"),
             (_at(2026, 10, 20, 7), "heating"), (_at(2026, 10, 20, 7, 15), "off"), (_at(2026, 10, 20, 9), "heating")]
    spans = hass_stats.heating_spans(found, _at(2026, 10, 19), _at(2026, 10, 20, 10))
    assert spans == [[_ms(_at(2026, 10, 19, 23)), _ms(_at(2026, 10, 20, 0, 30))], [_ms(_at(2026, 10, 20, 6)), _ms(_at(2026, 10, 20, 7, 15))],
                     [_ms(_at(2026, 10, 20, 9)), _ms(_at(2026, 10, 20, 10))]]
    assert hass_stats._heated(spans, _at(2026, 10, 20), _at(2026, 10, 20, 10)) == (30 + 75 + 60) * 60
    assert hass_stats._heated(spans, _at(2026, 10, 19), _at(2026, 10, 20)) == 60 * 60


# ---------------------------------------------------------------------------
# A card on a page
# ---------------------------------------------------------------------------


def test_a_card_shows_its_sensors_points_and_says_which_one_is_gone(client: TestClient) -> None:
    setup_admin(client)
    _board_, _hass_, page = _cards_page(client)
    answer = client.get(f"/api/v1/pages/{page['id']}/home/stats/rooms", params={"period": "7d"})
    assert answer.status_code == 200, answer.text
    living, gone = answer.json()["series"]
    assert gone == {"missing": True}
    assert living["step"] == "hour" and 160 <= len(living["points"]) <= 168 and living["low"][0] <= living["mean"] <= living["high"][0]
    assert living["current"] == 21.3 and answer.json()["zone"] == "Europe/Berlin"
    energy = client.get(f"/api/v1/pages/{page['id']}/home/stats/bars", params={"period": "1y"}).json()["series"][0]
    assert energy["kind"] == "sum" and energy["step"] == "month" and energy["total"] == pytest.approx(sum(point[1] for point in energy["points"]), abs=0.01)
    assert len(energy["points"]) == 12, "twelve months, this one so far the last"
    week = client.get(f"/api/v1/pages/{page['id']}/home/stats/bars", params={"period": "7d"}).json()["series"][0]
    assert len(week["points"]) in (6, 7) and week["latest"] == week["points"][-1][1], "seven days, today's so far the last (none yet just after midnight)"


def test_a_comparison_brings_the_day_before_laid_over_this_one(client: TestClient) -> None:
    setup_admin(client)
    _board_, _hass_, page = _cards_page(client)
    answer = client.get(f"/api/v1/pages/{page['id']}/home/stats/both", params={"period": "day"}).json()
    living = answer["series"][0]
    assert living["previous"] and all(answer["start"] <= point[0] < answer["end"] for point in living["previous"]), "moved onto today"
    assert all(point[0] >= answer["start"] for point in living["points"])
    assert living["previous_summary"]["mean"] is not None


@pytest.mark.parametrize(("card", "period"), [("both", "24h"), ("line", "day"), ("line", "5y"), ("line", "24h; drop")])
def test_a_card_shows_only_the_periods_of_its_style(client: TestClient, card: str, period: str) -> None:
    setup_admin(client)
    _board_, _hass_, page = _cards_page(client)
    assert client.get(f"/api/v1/pages/{page['id']}/home/stats/{card}", params={"period": period}).status_code == 422


def test_only_cards_of_the_page_are_read_and_only_by_who_may_look_at_it(client: TestClient) -> None:
    setup_admin(client)
    _board_, _hass_, page = _cards_page(client)
    assert client.get(f"/api/v1/pages/{page['id']}/home/stats/heat").status_code == 404, "a thermostat is no card"
    assert client.get(f"/api/v1/pages/{page['id']}/home/stats/nothing").status_code == 404
    stranger = TestClient(client.app)
    assert stranger.get(f"/api/v1/pages/{page['id']}/home/stats/line").status_code in (401, 403, 404)


def _real_house(client: TestClient, monkeypatch, zone: str = "America/New_York") -> tuple[dict, list[dict]]:
    entities, devices, areas, states = hass_registry.demo_registry()
    asked: list[dict] = []

    async def ask(config, commands):
        asked.extend(commands)
        kinds = [command["type"] for command in commands]
        if kinds[0] == "config/entity_registry/list":
            return [entities, devices, areas, {"unit_system": {"temperature": "°C"}, "time_zone": zone}] + ([list(states.values())] if len(commands) > 4 else [])
        if kinds == ["recorder/list_statistic_ids"]:
            return [[{"statistic_id": entity_id, **meta} for entity_id, meta in hass_stats.demo_catalogue().items()]]
        return [{} for _ in commands]

    monkeypatch.setattr(hass_registry, "_ask", ask)
    setup_admin(client)
    page = _made(client, _board(client), _hass(client)["id"])
    client.put(f"/api/v1/pages/{page['id']}/home", json={"elements": CARDS}, headers=CSRF)
    return page, asked


def test_a_real_house_is_asked_for_the_cards_own_sensors_by_its_own_calendar(client: TestClient, monkeypatch) -> None:
    page, asked = _real_house(client, monkeypatch)
    answer = client.get(f"/api/v1/pages/{page['id']}/home/stats/both", params={"period": "week"})
    assert answer.status_code == 200 and answer.json()["problem"] is None
    statistics = [command for command in asked if command["type"] == "recorder/statistics_during_period"]
    assert len(statistics) == 1
    command = statistics[0]
    assert (command["statistic_ids"], command["period"], command["types"]) == (["sensor.living_room_temperature"], "hour", ["mean", "min", "max"])
    start = dt.datetime.fromisoformat(command["start_time"]).astimezone(hass_stats.tz("America/New_York"))
    assert (start.weekday(), start.hour, start.minute) == (0, 0, 0), "last Monday at midnight in New York"
    client.get(f"/api/v1/pages/{page['id']}/home/stats/bars", params={"period": "7d"})
    energy = [command for command in asked if command["type"] == "recorder/statistics_during_period"][-1]
    assert (energy["statistic_ids"], energy["period"], energy["types"]) == (["sensor.house_energy"], "day", ["change"])


def test_a_card_read_twice_in_a_minute_asks_home_assistant_once(client: TestClient, monkeypatch) -> None:
    page, asked = _real_house(client, monkeypatch)
    for _ in range(3):
        client.get(f"/api/v1/pages/{page['id']}/home/stats/line", params={"period": "24h"})
    assert sum(command["type"] == "recorder/statistics_during_period" for command in asked) == 1
    assert sum(command["type"] == "recorder/list_statistic_ids" for command in asked) == 1


def test_a_house_that_does_not_answer_is_an_answer_on_the_card(client: TestClient, monkeypatch) -> None:
    page, _asked = _real_house(client, monkeypatch)

    async def silent(config, commands):
        from app.adapters.base import AdapterError
        raise AdapterError("Home Assistant could not be reached (OSError).", code="unreachable")

    monkeypatch.setattr(hass_registry, "_ask", silent)
    answer = client.get(f"/api/v1/pages/{page['id']}/home/stats/line")
    assert answer.status_code == 200 and answer.json()["problem"]["code"] == "unreachable" and answer.json()["series"] == []


# ---------------------------------------------------------------------------
# A thermostat's history
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("midday")
def test_a_thermostats_history_has_its_room_its_target_and_when_it_heated(client: TestClient) -> None:
    setup_admin(client)
    _board_, _hass_, page = _cards_page(client)
    answer = client.get(f"/api/v1/pages/{page['id']}/home/climates/heat/history", params={"period": "24h"})
    assert answer.status_code == 200, answer.text
    history = answer.json()
    assert history["sensor"] == "sensor.living_room_temperature", "the room by the page's sensor"
    assert history["room"] and history["heating"] and {point[1] for point in history["target"]} <= {18.0, 21.5}
    assert history["today"]["heated"] is not None and history["yesterday"]["heated"] > 0
    assert history["today"]["low"] <= history["today"]["high"]
    week = client.get(f"/api/v1/pages/{page['id']}/home/climates/heat/history", params={"period": "7d"}).json()
    assert week["step"] == "hour" and week["yesterday"]["heated"] == history["yesterday"]["heated"], "the same yesterday either way"
    assert client.get(f"/api/v1/pages/{page['id']}/home/climates/heat/history", params={"period": "30d"}).status_code == 422
    assert client.get(f"/api/v1/pages/{page['id']}/home/climates/line/history").status_code == 404


def test_a_thermostat_that_is_off_has_no_target_and_one_that_never_says_has_no_heating_times() -> None:
    now = dt.datetime(2026, 10, 20, 10, tzinfo=dt.UTC)
    rows = [{"s": "heat", "lu": (now - dt.timedelta(hours=30)).timestamp(), "a": {"temperature": 20, "current_temperature": 19.5}},
            {"s": "heat", "lu": (now - dt.timedelta(hours=28)).timestamp(), "a": {"temperature": 21, "current_temperature": 19.5}},
            {"s": "off", "lu": (now - dt.timedelta(hours=2)).timestamp(), "a": {"temperature": 21, "current_temperature": 19.0}},
            {"s": "heat", "lu": (now - dt.timedelta(hours=1)).timestamp()}]

    async def ask(config, commands):
        return [{"climate.x": rows}]

    cache = {"hass_registry": (0, [], [], [], {}, "°C", "Europe/Berlin")}
    original = hass_registry._ask
    hass_registry._ask = ask
    try:
        import asyncio
        history = asyncio.run(hass_stats.climate_history({}, cache, {"entity_id": "climate.x"}, None, "24h", now=now))
    finally:
        hass_registry._ask = original
    assert history["heating"] is None and history["today"]["heated"] is None
    # 20 was set before the 24 hours began and 21 too: only 21 stood at their start. Off for an hour, then on again
    # with a row that has no attributes, which keeps those before it.
    assert [point[1] for point in history["target"]] == [21.0, None, 21.0]
    assert history["target"][0][0] == history["start"] and history["room"][-1][1] == 19.0
