"""Thermostats on a home page.

What is offered (thermostats, and temperature sensors to read a room by),
what a page keeps of one, how it is shown when its sensor is gone, and that
setting one calls nothing but its own three services with what it says it
takes. The demo house of ``hass_registry`` stands in for a real one, and
respx for its REST API.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.adapters.base import AdapterError
from app.db import db_session
from app.models import ActionLog
from app.services import hass_registry, home, home_control
from app.services.collector import collector
from app.services.home_control import home_live
from app.services.sse import board_topic, hub

from .conftest import CSRF, create_user, login, setup_admin
from .test_home_page import _board, _demo_page, _hass, _made
from .test_home_switch import HA, _drain, _Recording

HEATERS = [
    {"id": "living", "type": "climate", "x": 16, "y": 16, "rid": "r-heat-living", "entity_id": "climate.living_room", "name": "Living room",
     "sensor": {"rid": "r-temp-living", "entity_id": "sensor.living_room_temperature", "name": "Living room temperature"}},
    {"id": "bed", "type": "climate", "x": 16, "y": 72, "rid": "r-heat-bed", "entity_id": "climate.bedroom", "name": "Bedroom",
     "sensor": {"rid": "r-gone", "entity_id": "sensor.thrown_away", "name": "Old sensor"}},
    {"id": "bath", "type": "climate", "x": 16, "y": 128, "rid": "r-heat-bath", "entity_id": "climate.bathroom", "name": "Bathroom"},
    {"id": "valve", "type": "climate", "x": 16, "y": 184, "rid": "r-heat-old", "entity_id": "climate.old_valve", "name": "Old valve"},
    {"id": "lamp", "type": "light", "x": 400, "y": 16, "rid": "r-ceiling", "entity_id": "light.ceiling", "name": "Ceiling light"},
]


def _heaters_page(client: TestClient) -> tuple[dict, dict, dict]:
    board, hass, page = _demo_page(client)
    saved = client.put(f"/api/v1/pages/{page['id']}/home", json={"elements": HEATERS}, headers=CSRF)
    assert saved.status_code == 200, saved.text
    return board, hass, page


def _set(client: TestClient, page: dict, element: str, body: object, **headers: str) -> httpx.Response:
    return client.post(f"/api/v1/pages/{page['id']}/home/climates/{element}", json=body, headers={**CSRF, **headers})


def _logged() -> list[tuple[str, dict, bool]]:
    with db_session() as db:
        return [(row.action, row.params, row.ok) for row in db.scalars(select(ActionLog).order_by(ActionLog.id))]


# ---------------------------------------------------------------------------
# What is offered, and how a thermostat stands
# ---------------------------------------------------------------------------


def test_only_thermostats_and_real_room_temperatures_are_offered() -> None:
    entities, devices, areas, states = hass_registry.demo_registry()
    thermostats = hass_registry.pick_climates(entities, devices, areas, states)
    assert [one["entity_id"] for one in thermostats] == ["climate.bathroom", "climate.bedroom", "climate.living_room"], "hidden stays out"
    sensors = hass_registry.pick_temperature_sensors(entities, devices, areas, states)
    assert [one["entity_id"] for one in sensors] == ["sensor.bedroom_temperature", "sensor.living_room_temperature", "sensor.outdoor_temperature"], \
        "a humidity sensor is no temperature, a server's own one is a diagnostic"
    assert sensors[1]["current"] == 21.3 and sensors[1]["area"] == "Living room"


def test_a_thermostat_says_what_it_lets_one_set() -> None:
    def stands(value: str = "heat", unit: str = "°C", **attributes: object) -> dict:
        return hass_registry.climate_state({"state": value, "attributes": attributes}, unit)

    living = stands(hvac_modes=["off", "heat"], current_temperature="20.5", temperature=21, hvac_action="heating",
                    preset_modes=["eco"], preset_mode="eco", supported_features=17, target_temp_step=0.1, min_temp=5, max_temp=28)
    assert (living["current"], living["target"], living["step"], living["min"], living["max"]) == (20.5, 21.0, 0.1, 5.0, 28.0)
    assert living["presets"] == ["eco"] and living["preset"] == "eco" and living["action"] == "heating" and living["settable"] is True
    bare = stands(preset_modes=["eco"], preset_mode="eco", supported_features=1)
    assert bare["presets"] == [] and bare["preset"] is None, "presets only with the preset feature"
    assert bare["action"] is None, "no action shown that the device does not report"
    assert (bare["step"], bare["min"], bare["max"]) == (0.5, *hass_registry.DEFAULT_TEMPERATURES)
    assert stands(unit="°F")["step"] == 1.0
    assert stands(supported_features=2)["settable"] is False, "a range of two is shown, not set"
    off = stands("off")
    assert off["on"] is False and off["mode"] == "off"
    gone = stands("unavailable")
    assert gone["unavailable"] is True and gone["on"] is False and gone["mode"] is None


def test_a_thermostat_is_kept_with_the_sensor_it_reads_its_room_by() -> None:
    raw = {"elements": [
        {**HEATERS[0], "style": "neon"},
        {**HEATERS[1], "sensor": {"rid": "r-x", "entity_id": "light.ceiling"}},
        {**HEATERS[2], "sensor": "sensor.bathroom"},
        {**HEATERS[0], "id": "lamp-ish", "entity_id": "light.ceiling"},
        {**HEATERS[0], "id": "other", "entity_id": "lock.front_door"},
    ]}
    kept = home.clean_layout(raw, None)["elements"]
    assert [element["id"] for element in kept] == ["living", "bed", "bath"]
    assert kept[0]["style"] == "pill" and kept[0]["sensor"] == {"rid": "r-temp-living", "entity_id": "sensor.living_room_temperature", "name": "Living room temperature"}
    assert kept[1]["sensor"] is None, "a lamp is no sensor"
    assert kept[2]["sensor"] is None


def test_a_page_reads_each_room_by_its_sensor_and_says_when_it_cannot(client: TestClient) -> None:
    setup_admin(client)
    _board, _hass, page = _heaters_page(client)
    climates = client.get(f"/api/v1/pages/{page['id']}/home").json()["climates"]
    living = climates["living"]
    assert living["reading"] == 21.3 and living["current"] == 20.5 and living["sensor"] == {"name": "Living room temperature", "state": "ok"}
    assert living["target"] == 21.5 and living["action"] == "heating" and living["presets"] == ["comfort", "eco", "away"]
    bed = climates["bed"]
    assert bed["reading"] == 18.2 and bed["sensor"] == {"name": "Old sensor", "state": "missing"}, "the thermostat's own reading, and why"
    assert climates["bath"]["unavailable"] is True and climates["bath"]["sensor"] is None
    assert climates["valve"] == {"missing": True}, "hidden in Home Assistant is gone from the page"


def test_the_thermostats_and_sensors_are_offered_to_those_who_arrange_the_page(client: TestClient) -> None:
    setup_admin(client)
    board, _hass, page = _demo_page(client)
    offer = client.get(f"/api/v1/pages/{page['id']}/home/climates").json()
    assert offer["problem"] is None
    assert [one["name"] for one in offer["climates"]] == ["Bathroom", "Bedroom", "Living room"]
    assert [one["entity_id"] for one in offer["sensors"]] == ["sensor.bedroom_temperature", "sensor.living_room_temperature", "sensor.outdoor_temperature"]
    client.put(f"/api/v1/boards/{board['slug']}/shares", json={"shares": [{"role": "user", "level": "view"}]}, headers=CSRF)
    create_user(client, "kim")
    login(client, "kim", "another-long-password")
    assert client.get(f"/api/v1/pages/{page['id']}/home/climates").status_code == 403


# ---------------------------------------------------------------------------
# Setting one
# ---------------------------------------------------------------------------


def test_a_target_is_put_on_the_thermostats_step_and_inside_its_bounds(client: TestClient) -> None:
    setup_admin(client)
    _board, _hass, page = _heaters_page(client)
    answer = _set(client, page, "living", {"target": 22.3})
    assert answer.status_code == 200, answer.text
    climate = answer.json()["climate"]
    assert answer.json()["confirmed"] is True and climate["target"] == 22.5 and climate["action"] == "heating"
    assert climate["reading"] == 21.3, "still read by its sensor"
    assert _set(client, page, "living", {"target": 40}).json()["climate"]["target"] == 30
    assert _set(client, page, "living", {"target": -10}).json()["climate"]["target"] == 7
    assert [entry[1].get("temperature") for entry in _logged()] == [22.5, 30, 7]
    assert _logged()[0] == ("climate.set_temperature", {"entity_id": "climate.living_room", "page_id": page["id"], "temperature": 22.5}, True)
    assert client.get(f"/api/v1/pages/{page['id']}/home").json()["climates"]["living"]["target"] == 7


def test_a_mode_and_a_preset_have_to_be_ones_the_thermostat_names(client: TestClient) -> None:
    setup_admin(client)
    _board, _hass, page = _heaters_page(client)
    heating = _set(client, page, "bed", {"mode": "heat"}).json()["climate"]
    assert heating["on"] is True and heating["mode"] == "heat"
    assert _set(client, page, "living", {"preset": "eco"}).json()["climate"]["preset"] == "eco"
    for element, body in (("bed", {"mode": "cool"}), ("bed", {"preset": "eco"}), ("living", {"preset": "turbo"})):
        refused = _set(client, page, element, body)
        assert (refused.status_code, refused.json()["detail"]["code"]) == (409, "not_supported"), body
    assert [entry[0] for entry in _logged()] == ["climate.set_hvac_mode", "climate.set_preset_mode"]


@pytest.mark.parametrize("body", [
    {},
    {"target": 21, "mode": "heat"},
    {"mode": "heat", "preset": "eco"},
    {"target": "21"},
    {"target": True},
    {"target": 500},
    {"mode": "Heat!"},
    {"mode": ""},
    {"preset": "<script>"},
    {"target": 21, "entity_id": "climate.other"},
    {"target": 21, "service": "lock.unlock"},
])
def test_a_thermostat_is_asked_one_thing_and_never_named_a_service(client: TestClient, body: object) -> None:
    setup_admin(client)
    _board, _hass, page = _heaters_page(client)
    assert _set(client, page, "living", body).status_code == 422
    assert _logged() == []


def test_what_is_not_a_thermostat_of_the_page_or_cannot_be_reached_is_not_set(client: TestClient) -> None:
    setup_admin(client)
    _board, _hass, page = _heaters_page(client)
    for element, status, code in (
        ("bath", 409, "climate_unavailable"),
        ("valve", 409, "climate_missing"),
        ("lamp", 404, "not_found"),
        ("nothing", 404, "not_found"),
    ):
        refused = _set(client, page, element, {"target": 20})
        assert (refused.status_code, refused.json()["detail"]["code"]) == (status, code), element
    assert client.post(f"/api/v1/pages/{page['id']}/home/lights/living", json={"on": True}, headers=CSRF).status_code == 404, \
        "a thermostat is not switched as a lamp"
    assert _logged() == []


def test_only_who_may_act_on_the_board_sets_a_thermostat(client: TestClient) -> None:
    setup_admin(client)
    board, _hass, page = _heaters_page(client)
    kim = create_user(client, "kim")
    member = TestClient(client.app)
    login(member, "kim", "another-long-password")
    for level, expected in (("view", 403), ("edit", 403), ("act", 200)):
        client.put(f"/api/v1/boards/{board['slug']}/shares", json={"shares": [{"user_id": kim["id"], "level": level}]}, headers=CSRF)
        assert _set(member, page, "living", {"target": 21}).status_code == expected, level


# ---------------------------------------------------------------------------
# A real house
# ---------------------------------------------------------------------------


def _real_house(client: TestClient, monkeypatch) -> dict:
    entities, devices, areas, states = hass_registry.demo_registry()

    async def ask(config, commands):
        return [entities, devices, areas, {"unit_system": {"temperature": "°C"}}] + ([list(states.values())] if len(commands) > 4 else [])

    monkeypatch.setattr(hass_registry, "_ask", ask)
    setup_admin(client)
    page = _made(client, _board(client), _hass(client)["id"])
    client.put(f"/api/v1/pages/{page['id']}/home", json={"elements": HEATERS}, headers=CSRF)
    return page


@respx.mock
def test_a_real_house_is_sent_the_target_and_the_mode_and_nothing_else(client: TestClient, monkeypatch) -> None:
    page = _real_house(client, monkeypatch)
    target = respx.post(f"{HA}/api/services/climate/set_temperature").mock(return_value=httpx.Response(200, json=[]))
    mode = respx.post(f"{HA}/api/services/climate/set_hvac_mode").mock(return_value=httpx.Response(500))
    answered = _set(client, page, "living", {"target": 19.76})
    assert answered.status_code == 200 and answered.json()["confirmed"] is False
    assert json.loads(target.calls[0].request.content) == {"entity_id": "climate.living_room", "temperature": 20.0}
    failed = _set(client, page, "bed", {"mode": "heat"})
    assert failed.status_code == 502 and json.loads(mode.calls[0].request.content) == {"entity_id": "climate.bedroom", "hvac_mode": "heat"}
    assert [entry[2] for entry in _logged()] == [True, False]


@pytest.mark.parametrize(("service", "data"), [
    ("set_temperature", {"temperature": 21, "hvac_mode": "heat"}),
    ("set_temperature", {"target_temp_low": 18}),
    ("set_hvac_mode", {"hvac_mode": "heat", "temperature": 30}),
    ("turn_off", {}),
    ("set_fan_mode", {"fan_mode": "high"}),
])
async def test_a_thermostats_services_carry_nothing_but_their_own_data(service: str, data: dict) -> None:
    ctx = _Recording()
    with pytest.raises(AdapterError) as refused:
        await home_control.call({"url": HA}, ctx, "climate", service, "climate.living_room", data)  # type: ignore[arg-type]
    assert refused.value.code == "service_refused" and ctx.calls == []


# ---------------------------------------------------------------------------
# Live
# ---------------------------------------------------------------------------


def test_a_page_hears_when_its_room_gets_warmer_and_when_the_thermostat_changes(client: TestClient) -> None:
    setup_admin(client)
    board, hass, page = _heaters_page(client)
    client.get(f"/api/v1/pages/{page['id']}/home")  # the demo states are in the connection's cache now
    cache = collector._caches[hass["id"]]
    states = cache["hass_demo_states"]
    listener = hub.subscribe({board_topic(board["id"])})
    try:
        warmer = {**states["sensor.living_room_temperature"], "state": "23.4"}
        states["sensor.living_room_temperature"] = warmer
        home_live.touched(hass["id"], cache, "sensor.living_room_temperature", warmer)
        home_live._last.clear()
        colder = {**states["climate.bedroom"], "attributes": {**states["climate.bedroom"]["attributes"], "current_temperature": 16.0}}
        home_live.touched(hass["id"], cache, "climate.bedroom", colder)
        home_live._last.clear()
        home_live.touched(hass["id"], cache, "sensor.living_room_humidity", {"entity_id": "sensor.living_room_humidity", "state": "70"})
        events = _drain(listener)
    finally:
        hub.unsubscribe(listener)
    assert [list(event.get("climates", {})) for event in events] == [["living"], ["bed"]]
    living, bed = events[0]["climates"]["living"], events[1]["climates"]["bed"]
    assert living["reading"] == 23.4 and living["sensor"]["state"] == "ok" and living["target"] == 21.5
    assert bed["reading"] == 16.0 and bed["sensor"]["state"] == "missing"
    assert "lights" not in events[0]


def test_a_thermostat_with_a_range_of_two_takes_no_single_target() -> None:
    both = hass_registry.climate_state({"state": "heat_cool", "attributes": {"supported_features": 2, "target_temp_low": 19, "target_temp_high": 24}})
    with pytest.raises(AdapterError) as refused:
        home_control.climate_service_for({**both, "name": "Hall"}, target=21)
    assert refused.value.code == "not_supported"
    assert home_control.climate_service_for({**both, "modes": ["heat_cool"]}, mode="heat_cool")[1] == "set_hvac_mode"


def test_a_sensor_that_is_there_but_not_answering_leaves_the_thermostats_reading() -> None:
    thermostat = hass_registry.climate_state({"state": "heat", "attributes": {"current_temperature": 19.5, "supported_features": 1}})
    wanted = {"rid": "r-s", "entity_id": "sensor.hall", "name": "Hall temperature"}
    for reads in ({"state": "unavailable"}, {"state": "unknown"}, {"state": "warm"}):
        view = home_control.climate_view(thermostat, {**hass_registry.sensor_state(reads), "name": "Hall temperature"}, wanted)
        assert view["reading"] == 19.5 and view["sensor"] == {"name": "Hall temperature", "state": "unavailable"}, reads
    answering = home_control.climate_view(thermostat, {**hass_registry.sensor_state({"state": "22.1"}), "name": "Hall temperature"}, wanted)
    assert answering["reading"] == 22.1 and answering["sensor"]["state"] == "ok"


# ---------------------------------------------------------------------------
# Export, import and the board as YAML
# ---------------------------------------------------------------------------

FURNISHED = [
    {"id": "down", "type": "heading", "x": 16, "y": 16, "text": "Downstairs"},
    {"id": "floor", "type": "light", "x": 16, "y": 56, "rid": "r-floor", "entity_id": "light.floor_lamp", "name": "Floor lamp", "style": "knob"},
    {"id": "strip", "type": "light", "x": 120, "y": 56, "rid": "r-tv", "entity_id": "light.tv_strip", "name": "LED strip", "style": "pill"},
    HEATERS[0],
    {**HEATERS[2], "y": 200},
]


def test_a_furnished_home_page_travels_with_its_board_and_works_where_it_lands(client: TestClient) -> None:
    import yaml

    setup_admin(client)
    board, _hass, page = _demo_page(client)
    client.put(f"/api/v1/pages/{page['id']}/home", json={"elements": FURNISHED}, headers=CSRF)
    text = client.get(f"/api/v1/boards/{board['slug']}/export").text
    assert "a-token" not in text
    document = yaml.safe_load(text)
    exported = next(one for one in document["pages"] if one.get("kind") == "home")["home"]
    assert exported["integration"] == "Home Assistant" and [element["id"] for element in exported["elements"]] == ["down", "floor", "strip", "living", "bath"]

    # Another house names its lamps the same, under registry ids of its own: the entity id finds them.
    for element in exported["elements"]:
        if "rid" in element:
            element["rid"] = "elsewhere-" + element["rid"]
    copy = client.post("/api/v1/boards/import", json={"yaml_text": yaml.safe_dump(document), "slug": "house-copy"}, headers=CSRF)
    assert copy.status_code == 201, copy.text
    copied = next(one for one in copy.json()["pages"] if one["kind"] == "home")
    answer = client.get(f"/api/v1/pages/{copied['id']}/home").json()
    elements = {element["id"]: element for element in answer["layout"]["elements"]}
    assert elements["floor"]["style"] == "knob" and elements["living"]["sensor"]["entity_id"] == "sensor.living_room_temperature"
    assert answer["lights"]["floor"]["missing"] is False and answer["lights"]["floor"]["on"] is True
    assert answer["climates"]["living"]["reading"] == 21.3, "its sensor found again by its entity id"
    assert answer["climates"]["living"]["sensor"]["state"] == "ok"
    assert _set(client, copied, "living", {"target": 20}).status_code == 200


def test_editing_the_board_as_yaml_keeps_what_stands_on_a_home_page(client: TestClient) -> None:
    import yaml

    setup_admin(client)
    board, _hass, page = _demo_page(client)
    client.put(f"/api/v1/pages/{page['id']}/home", json={"elements": FURNISHED}, headers=CSRF)
    document = yaml.safe_load(client.get(f"/api/v1/boards/{board['slug']}/export?ids=true").text)
    home_doc = next(one for one in document["pages"] if one.get("kind") == "home")["home"]
    home_doc["elements"][1]["style"] = "ring"
    home_doc["elements"].append({"id": "sneaky", "type": "light", "x": 0, "y": 0, "rid": "r-x", "entity_id": "lock.front_door"})
    saved = client.put(f"/api/v1/boards/{board['slug']}/yaml", json={"yaml_text": yaml.safe_dump(document, sort_keys=False)}, headers=CSRF)
    assert saved.status_code == 200, saved.text
    pages = client.get(f"/api/v1/boards/{board['slug']}").json()["pages"]
    home_page = next(one for one in pages if one["kind"] == "home")
    elements = client.get(f"/api/v1/pages/{home_page['id']}/home").json()["layout"]["elements"]
    assert [element["id"] for element in elements] == ["down", "floor", "strip", "living", "bath"], "a lock passed off as a lamp stays out"
    assert elements[1]["style"] == "ring"
    assert elements[3]["sensor"]["rid"] == "r-temp-living"
    # Checked on the way in, not only when read: the live map reads what is stored.
    from app.models import Page

    with db_session() as db:
        stored = db.get(Page, home_page["id"]).home
    assert [element["id"] for element in stored["elements"]] == ["down", "floor", "strip", "living", "bath"]
