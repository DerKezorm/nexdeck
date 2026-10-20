"""Doors, windows, temperatures and humidity on a home page.

What is offered (contacts by their device class, readings with their device
to pair them by, a device's battery with them), what a page keeps of each
of the five elements, how the page reads them, with the trend of the last
hour, and that the board's stream tells of a window opening. The demo house
of ``hass_registry`` stands in for a real one.
"""

from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient

from app.services import hass_registry, hass_sensors, hass_stats, home
from app.services.collector import collector
from app.services.home_control import home_live
from app.services.sse import board_topic, hub

from .conftest import CSRF, create_user, login, setup_admin
from .test_home_page import _board, _demo_page, _hass, _made
from .test_home_switch import _drain

KITCHEN = {"rid": "r-win-kitchen", "entity_id": "binary_sensor.kitchen_window", "name": "Kitchen window"}
CELLAR = {"rid": "r-win-cellar", "entity_id": "binary_sensor.cellar_window", "name": "Cellar window"}
GONE = {"rid": "r-gone", "entity_id": "binary_sensor.thrown_away", "name": "Old window"}
BATH_T = {"rid": "r-temp-bath", "entity_id": "sensor.bathroom_temperature", "name": "Bathroom temperature"}
BATH_H = {"rid": "r-hum-bath", "entity_id": "sensor.bathroom_humidity", "name": "Bathroom humidity"}
LIVING_T = {"rid": "r-temp-living", "entity_id": "sensor.living_room_temperature", "name": "Living room temperature"}
ELEMENTS = [
    {"id": "k", "type": "contact", "x": 16, "y": 16, **KITCHEN, "style": "window"},
    {"id": "all", "type": "contacts", "x": 300, "y": 16, "style": "house", "title": "Windows", "sensors": [KITCHEN, CELLAR, GONE]},
    {"id": "bath", "type": "reading", "x": 16, "y": 200, "style": "ring", "name": "Bathroom", "temperature": BATH_T, "humidity": BATH_H},
    {"id": "rooms", "type": "readings", "x": 300, "y": 200, "title": "Rooms",
     "rows": [{"name": "Living room", "temperature": LIVING_T, "humidity": None}, {"name": "Bathroom", "temperature": BATH_T, "humidity": BATH_H}]},
    {"id": "tips", "type": "hints", "x": 16, "y": 400, "checks": ["humid"]},
]


def _sensors_page(client: TestClient) -> tuple[dict, dict, dict]:
    board, hass, page = _demo_page(client)
    saved = client.put(f"/api/v1/pages/{page['id']}/home", json={"elements": ELEMENTS}, headers=CSRF)
    assert saved.status_code == 200, saved.text
    return board, hass, page


# ---------------------------------------------------------------------------
# What is offered
# ---------------------------------------------------------------------------


def test_doors_windows_and_openings_are_offered_with_the_battery_of_their_device() -> None:
    entities, devices, areas, states = hass_registry.demo_registry()
    contacts = {one["entity_id"]: one for one in hass_sensors.pick_contacts(entities, devices, areas, states)}
    assert "binary_sensor.hall_motion" not in contacts, "a motion sensor is no door"
    assert "binary_sensor.old_window" not in contacts, "hidden in Home Assistant"
    assert (contacts["binary_sensor.kitchen_window"]["open"], contacts["binary_sensor.front_door"]["open"]) == (True, False)
    assert contacts["binary_sensor.kitchen_window"]["area"] == "Kitchen" and contacts["binary_sensor.front_door"]["device_class"] == "door"
    assert contacts["binary_sensor.cellar_window"]["battery"] == 8, "the battery is a diagnostic, and still told"
    assert contacts["binary_sensor.kitchen_window"]["battery"] is None
    guest = contacts["binary_sensor.guest_room_window"]
    assert (guest["open"], guest["unavailable"]) == (None, True)
    opened = contacts["binary_sensor.kitchen_window"]["since"] / 1000
    assert 11 * 60 <= dt.datetime.now(dt.UTC).timestamp() - opened <= 13 * 60


@pytest.mark.parametrize(("state", "expected"), [
    ({"state": "on", "last_changed": "2026-10-20T16:00:00+00:00"}, (True, 1792512000000, False)),
    ({"state": "off", "last_changed": 1792512000.5}, (False, 1792512000500, False)),
    ({"state": "off", "last_updated": "2026-10-20T16:00:00"}, (False, 1792512000000, False)),
    ({"state": "unavailable"}, (None, None, True)),
    ({"state": "unknown", "last_changed": "not a time"}, (None, None, True)),
])
def test_a_contact_is_open_when_on_since_it_last_changed(state: dict, expected: tuple) -> None:
    said = hass_sensors.contact_state(state)
    assert (said["open"], said["since"], said["unavailable"]) == expected


def test_temperatures_and_humidities_are_offered_with_their_device_to_pair_them_by() -> None:
    entities, devices, areas, states = hass_registry.demo_registry()
    readings = {one["entity_id"]: one for one in hass_sensors.pick_readings(entities, devices, areas, states)}
    assert "sensor.home_server_cpu_temperature" not in readings and "sensor.cellar_window_battery" not in readings, "diagnostics stay out"
    assert "sensor.house_energy" not in readings
    assert readings["sensor.bathroom_temperature"]["device_id"] == readings["sensor.bathroom_humidity"]["device_id"] == "d-climate-bath"
    assert (readings["sensor.bathroom_humidity"]["device_class"], readings["sensor.bathroom_humidity"]["current"]) == ("humidity", 71.0)


def test_the_house_is_offered_to_those_who_arrange_the_page_and_nobody_else(client: TestClient) -> None:
    setup_admin(client)
    board, _hass_, page = _sensors_page(client)
    contacts = client.get(f"/api/v1/pages/{page['id']}/home/contacts").json()
    readings = client.get(f"/api/v1/pages/{page['id']}/home/readings").json()
    assert contacts["problem"] is None and len(contacts["contacts"]) == 7
    assert readings["problem"] is None and len(readings["readings"]) == 8
    kim = create_user(client, "kim")
    client.put(f"/api/v1/boards/{board['slug']}/shares", json={"shares": [{"user_id": kim["id"], "level": "view"}]}, headers=CSRF)
    member = TestClient(client.app)
    login(member, "kim", "another-long-password")
    assert member.get(f"/api/v1/pages/{page['id']}/home/contacts").status_code == 403
    assert member.get(f"/api/v1/pages/{page['id']}/home/readings").status_code == 403
    assert member.get(f"/api/v1/pages/{page['id']}/home").json()["sensors"]["binary_sensor.kitchen_window"]["open"] is True, "but they see them"


# ---------------------------------------------------------------------------
# What a page keeps
# ---------------------------------------------------------------------------


def test_each_element_keeps_its_sensors_of_the_right_kind_and_nothing_else() -> None:
    contact = home.clean_element({"id": "a", "type": "contact", "x": 0, "y": 0, **KITCHEN, "style": "door", "width": 50, "colour": "red"})
    assert contact == {"id": "a", "type": "contact", "x": 0, "y": 0, **KITCHEN, "style": "door", "width": 96}
    assert home.clean_element({"id": "a", "type": "contact", "x": 0, "y": 0, **BATH_T}) is None, "a temperature is no door"
    many = [{"rid": f"r{i}", "entity_id": f"binary_sensor.w{i}", "name": f"W{i}"} for i in range(70)]
    card = home.clean_element({"id": "a", "type": "contacts", "x": 0, "y": 0, "style": "garden", "sensors": [many[0], many[0], LIVING_T, *many[1:]]})
    assert card is not None and len(card["sensors"]) == 60 and card["sensors"][1]["entity_id"] == "binary_sensor.w1" and card["style"] == "list"
    reading = home.clean_element({"id": "a", "type": "reading", "x": 0, "y": 0, "style": "dial", "humidity": BATH_H, "temperature": KITCHEN})
    assert reading is not None and (reading["temperature"], reading["humidity"], reading["style"]) == (None, BATH_H, "pill")
    assert home.clean_element({"id": "a", "type": "reading", "x": 0, "y": 0, "temperature": None}) is None
    rows = [{"name": "Empty"}] + [{"name": f"R{i}", "temperature": BATH_T} for i in range(14)]
    listed = home.clean_element({"id": "a", "type": "readings", "x": 0, "y": 0, "rows": rows})
    assert listed is not None and len(listed["rows"]) == 12 and listed["rows"][0]["name"] == "R0", "a row without a sensor is left out"
    assert home.clean_element({"id": "a", "type": "readings", "x": 0, "y": 0, "rows": [{"name": "Empty"}]}) is None


def test_a_hints_card_looks_for_what_it_was_told_and_for_everything_unless_told() -> None:
    told = home.clean_element({"id": "a", "type": "hints", "x": 0, "y": 0, "checks": ["humid", "smoke", "humid"]})
    assert told is not None and told["checks"] == ["humid"]
    assert home.clean_element({"id": "a", "type": "hints", "x": 0, "y": 0, "checks": []})["checks"] == []  # type: ignore[index]
    assert home.clean_element({"id": "a", "type": "hints", "x": 0, "y": 0})["checks"] == ["heating", "humid"]  # type: ignore[index]


# ---------------------------------------------------------------------------
# The page
# ---------------------------------------------------------------------------


def test_a_page_reads_its_sensors_by_the_ids_they_were_placed_with_and_says_which_is_gone(client: TestClient) -> None:
    setup_admin(client)
    _board_, _hass_, page = _sensors_page(client)
    sensors = client.get(f"/api/v1/pages/{page['id']}/home").json()["sensors"]
    assert set(sensors) == {"binary_sensor.kitchen_window", "binary_sensor.cellar_window", "binary_sensor.thrown_away",
                            "sensor.bathroom_temperature", "sensor.bathroom_humidity", "sensor.living_room_temperature"}
    assert sensors["binary_sensor.thrown_away"] == {"missing": True}
    assert sensors["binary_sensor.cellar_window"]["battery"] == 8
    assert sensors["sensor.bathroom_humidity"]["current"] == 71.0 and "trend" not in sensors["sensor.bathroom_humidity"], "a trend only for a temperature"
    assert isinstance(sensors["sensor.bathroom_temperature"]["trend"], float)


def test_a_window_opening_is_told_to_the_page_without_what_only_the_registry_knows(client: TestClient) -> None:
    setup_admin(client)
    board, hass, page = _sensors_page(client)
    client.get(f"/api/v1/pages/{page['id']}/home")
    cache = collector._caches[hass["id"]]
    listener = hub.subscribe({board_topic(board["id"])})
    try:
        home_live.touched(hass["id"], cache, "binary_sensor.cellar_window",
                          {"entity_id": "binary_sensor.cellar_window", "state": "on", "last_changed": "2026-10-20T16:00:00+00:00"})
        home_live._last.clear()
        home_live.touched(hass["id"], cache, "sensor.bathroom_humidity", {"entity_id": "sensor.bathroom_humidity", "state": "74"})
        home_live._last.clear()
        home_live.touched(hass["id"], cache, "binary_sensor.front_door", {"entity_id": "binary_sensor.front_door", "state": "on"})
        events = _drain(listener)
    finally:
        hub.unsubscribe(listener)
    assert [list(event["sensors"]) for event in events] == [["binary_sensor.cellar_window"], ["sensor.bathroom_humidity"]], "the front door is on no page"
    window = events[0]["sensors"]["binary_sensor.cellar_window"]
    assert (window["open"], window["since"], window["missing"]) == (True, 1792512000000, False)
    assert "battery" not in window and "name" not in window
    assert events[1]["sensors"]["sensor.bathroom_humidity"]["current"] == 74.0


def test_a_sensor_renamed_in_home_assistant_is_still_heard_by_its_page(client: TestClient, monkeypatch) -> None:
    entities, devices, areas, states = hass_registry.demo_registry()
    renamed = [{**entry, "entity_id": "binary_sensor.kitchen_window_left"} if entry["id"] == "r-win-kitchen" else entry for entry in entities]
    moved = {key: value for key, value in states.items() if key != "binary_sensor.kitchen_window"}
    moved["binary_sensor.kitchen_window_left"] = {**states["binary_sensor.kitchen_window"], "entity_id": "binary_sensor.kitchen_window_left"}

    async def ask(config, commands):
        kinds = [command["type"] for command in commands]
        if kinds[0] == "config/entity_registry/list":
            return [renamed, devices, areas, {"unit_system": {"temperature": "°C"}, "time_zone": "Europe/Berlin"}] + ([list(moved.values())] if len(commands) > 4 else [])
        if kinds == ["recorder/list_statistic_ids"]:
            return [[]]
        return [{} for _ in commands]

    monkeypatch.setattr(hass_registry, "_ask", ask)
    setup_admin(client)
    integration = _hass(client)
    board = _board(client)
    page = _made(client, board, integration["id"])
    client.put(f"/api/v1/pages/{page['id']}/home", json={"elements": ELEMENTS[:1]}, headers=CSRF)
    sensors = client.get(f"/api/v1/pages/{page['id']}/home").json()["sensors"]
    assert sensors["binary_sensor.kitchen_window"]["entity_id"] == "binary_sensor.kitchen_window_left", "found by its registry id"
    cache = collector._caches[integration["id"]]
    listener = hub.subscribe({board_topic(board["id"])})
    try:
        home_live.touched(integration["id"], cache, "binary_sensor.kitchen_window_left", {"entity_id": "binary_sensor.kitchen_window_left", "state": "off"})
        events = _drain(listener)
    finally:
        hub.unsubscribe(listener)
    assert events and events[0]["sensors"]["binary_sensor.kitchen_window"]["open"] is False, "told under the id the page keeps"


def test_a_trend_is_the_change_over_the_last_hour_of_five_minute_statistics() -> None:
    now = dt.datetime(2026, 10, 20, 12, tzinfo=dt.UTC)
    wanted = [{"entity_id": "sensor.bathroom_temperature", "source": "statistics", "kind": "mean"},
              {"entity_id": "sensor.bathroom_humidity", "source": "history", "kind": "mean"}]
    found = __import__("asyncio").run(hass_stats.trends({}, {}, wanted, demo=True, now=now))
    assert list(found) == ["sensor.bathroom_temperature"], "a sensor without statistics has no trend"
    rows = hass_stats.demo_answer(hass_stats._statistics_command(["sensor.bathroom_temperature"], now - dt.timedelta(minutes=70), now, "5minute", "mean"), now)
    points = hass_stats.from_statistics(rows["sensor.bathroom_temperature"], "mean")
    assert found["sensor.bathroom_temperature"] == round(points[-1][1] - points[0][1], 1)


# ---------------------------------------------------------------------------
# A name of the page's own
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["light", "climate", "contact"])
def test_a_lamp_a_thermostat_and_a_door_keep_a_name_of_their_own_and_none_when_it_is_empty(kind: str) -> None:
    placed = {"light": {"rid": "r-floor", "entity_id": "light.floor_lamp", "name": "Floor lamp"},
              "climate": {"rid": "r-heat-living", "entity_id": "climate.living_room", "name": "Living room"},
              "contact": KITCHEN}[kind]
    kept = home.clean_element({"id": "a", "type": kind, "x": 0, "y": 0, **placed, "label": "  Stairs\x07, ground floor  "})
    assert kept is not None and kept["label"] == "Stairs, ground floor" and kept["name"] == placed["name"], "Home Assistant's name stays beside it"
    for empty in ("", "   ", None, 7):
        assert "label" not in home.clean_element({"id": "a", "type": kind, "x": 0, "y": 0, **placed, "label": empty})  # type: ignore[operator]
    assert len(home.clean_element({"id": "a", "type": kind, "x": 0, "y": 0, **placed, "label": "x" * 200})["label"]) == home.MAX_NAME  # type: ignore[index]


def test_a_name_of_its_own_is_saved_with_the_page(client: TestClient) -> None:
    setup_admin(client)
    _board_, _hass_, page = _demo_page(client)
    door = {"id": "k", "type": "contact", "x": 16, "y": 16, **KITCHEN, "style": "door", "label": "Stairs, ground floor"}
    saved = client.put(f"/api/v1/pages/{page['id']}/home", json={"elements": [door]}, headers=CSRF)
    assert saved.status_code == 200
    assert client.get(f"/api/v1/pages/{page['id']}/home").json()["layout"]["elements"][0]["label"] == "Stairs, ground floor"


# ---------------------------------------------------------------------------
# A size of its own
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["light", "climate", "contact", "reading", "cover"])
def test_a_drawn_element_keeps_a_size_of_its_own_inside_its_bounds(kind: str) -> None:
    placed = {"light": {"rid": "r-floor", "entity_id": "light.floor_lamp", "name": "Floor lamp", "style": "round"},
              "climate": {"rid": "r-heat-living", "entity_id": "climate.living_room", "name": "Living room", "style": "dial"},
              "contact": {**KITCHEN, "style": "door"},
              "reading": {"style": "thermometer", "temperature": LIVING_T},
              "cover": {"rid": "r-cover-kitchen", "entity_id": "cover.kitchen", "name": "Kitchen", "style": "window"}}[kind]

    def kept(scale: object) -> object:
        element = home.clean_element({"id": "a", "type": kind, "x": 0, "y": 0, **placed, "scale": scale})
        assert element is not None
        return element.get("scale")

    assert kept(1.53) == 1.55, "on a twentieth"
    assert kept(0.2) == home.SCALES[0], "not so small that it cannot be read"
    assert kept(40) == home.SCALES[1]
    for left_out in (1, 1.01, True, "2", float("nan"), None):
        assert kept(left_out) is None, left_out
