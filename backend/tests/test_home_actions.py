"""Scenes, scripts and switches on a home page.

What is offered (a Hue scene with its room, a script that runs, a switch
with what its device draws), what a page keeps of each of the four
elements, and that setting one off calls nothing but its own service: a
scene, a script started or stopped, a switch on or off, for one element,
one of a card, or every switch of a card. The demo house stands in for a
real one, and respx for its REST API.
"""

from __future__ import annotations

import datetime as dt
import json

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.adapters.base import AdapterError
from app.db import db_session
from app.models import ActionLog
from app.services import hass_registry, hass_switches, home, home_control
from app.services.collector import collector
from app.services.home_control import home_live
from app.services.sse import board_topic, hub

from .conftest import CSRF, create_user, login, setup_admin
from .test_home_page import _board, _demo_page, _hass, _made
from .test_home_switch import HA, _drain, _Recording

COZY = {"rid": "r-scene-cozy", "entity_id": "scene.living_room_cozy", "name": "Cozy"}
CINEMA = {"rid": "r-scene-cinema", "entity_id": "scene.living_room_cinema", "name": "Cinema"}
ROUTINE = {"rid": "r-script-night", "entity_id": "script.goodnight_routine", "name": "Good night routine"}
COFFEE = {"rid": "r-plug-coffee", "entity_id": "switch.coffee_machine", "name": "Coffee machine"}
ROUTER = {"rid": "r-plug-router", "entity_id": "switch.router", "name": "Router"}
GUESTS = {"rid": "r-guests", "entity_id": "input_boolean.guests", "name": "Guests here"}
DARK = {"rid": "r-garden-light", "entity_id": "switch.garden_light", "name": "Garden light"}
GONE = {"rid": "r-gone", "entity_id": "switch.thrown_away", "name": "Old plug"}
ELEMENTS = [
    {"id": "cozy", "type": "scene", "x": 16, "y": 16, **COZY, "style": "tile", "colour": "sunset"},
    {"id": "routine", "type": "scene", "x": 16, "y": 140, **ROUTINE, "style": "pill"},
    {"id": "room", "type": "scenes", "x": 300, "y": 16, "style": "bar", "title": "Living room", "sensors": [COZY, CINEMA]},
    {"id": "coffee", "type": "switch", "x": 16, "y": 200, **COFFEE, "style": "outlet"},
    {"id": "router", "type": "switch", "x": 16, "y": 340, **ROUTER, "style": "toggle", "confirm": True},
    {"id": "office", "type": "switches", "x": 300, "y": 200, "title": "Office", "sensors": [COFFEE, GUESTS, DARK, GONE]},
]


def _page(client: TestClient) -> tuple[dict, dict, dict]:
    board, hass, page = _demo_page(client)
    saved = client.put(f"/api/v1/pages/{page['id']}/home", json={"elements": ELEMENTS}, headers=CSRF)
    assert saved.status_code == 200, saved.text
    return board, hass, page


def _scene(client: TestClient, page: dict, element: str, body: object) -> httpx.Response:
    return client.post(f"/api/v1/pages/{page['id']}/home/scenes/{element}", json=body, headers=CSRF)


def _switch(client: TestClient, page: dict, element: str, body: object) -> httpx.Response:
    return client.post(f"/api/v1/pages/{page['id']}/home/switches/{element}", json=body, headers=CSRF)


def _logged() -> list[tuple[str, str, bool]]:
    with db_session() as db:
        return [(row.action, row.params["entity_id"], row.ok) for row in db.scalars(select(ActionLog).order_by(ActionLog.id))]


# ---------------------------------------------------------------------------
# What is offered
# ---------------------------------------------------------------------------


def test_scenes_come_with_their_room_and_when_they_were_last_set_off_and_scripts_with_whether_they_run() -> None:
    entities, devices, areas, states = hass_registry.demo_registry()
    offered = {one["entity_id"]: one for one in hass_switches.pick_actions(entities, devices, areas, states, hass_switches.TRIGGERS)}
    assert offered["scene.living_room_cozy"]["area"] == "Living room", "a Hue scene names its room"
    assert offered["scene.goodnight"]["area"] == ""
    assert offered["scene.living_room_cinema"]["last"] is None, "never set off"
    assert dt.datetime.now(dt.UTC).timestamp() * 1000 - offered["scene.living_room_cozy"]["last"] == pytest.approx(10 * 60_000, abs=60_000)
    assert (offered["script.goodnight_routine"]["running"], offered["script.evening_shutters"]["running"]) == (True, False)
    assert not any(one.startswith("switch.") for one in offered)


def test_switches_and_helpers_come_with_what_their_device_draws() -> None:
    entities, devices, areas, states = hass_registry.demo_registry()
    offered = {one["entity_id"]: one for one in hass_switches.pick_actions(entities, devices, areas, states, hass_switches.SWITCHES)}
    assert "switch.old_plug" not in offered and "scene.goodnight" not in offered
    coffee = offered["switch.coffee_machine"]
    assert (coffee["on"], coffee["power"], coffee["energy_entity"], coffee["device_class"]) == (True, 1240.0, "sensor.coffee_machine_energy", "outlet")
    assert offered["switch.garden_pump"]["power"] is None and offered["switch.garden_pump"]["power_entity"] is None
    assert (offered["input_boolean.guests"]["on"], offered["switch.garden_light"]["unavailable"]) == (True, True)
    kilowatts = hass_switches._power_of("sensor.x", {"sensor.x": {"state": "1.5", "attributes": {"unit_of_measurement": "kW"}}})
    assert kilowatts == 1500.0


@pytest.mark.parametrize(("entity_id", "asked", "expected"), [
    ("scene.a", {}, ("scene", "turn_on")),
    ("script.a", {}, ("script", "turn_on")),
    ("script.a", {"stop": True}, ("script", "turn_off")),
    ("switch.a", {"on": True}, ("switch", "turn_on")),
    ("switch.a", {"on": False}, ("switch", "turn_off")),
    ("input_boolean.a", {"on": False}, ("input_boolean", "turn_off")),
])
def test_each_is_sent_its_own_service(entity_id: str, asked: dict, expected: tuple) -> None:
    assert hass_switches.service_for({"entity_id": entity_id}, **asked) == (*expected, {})


# ---------------------------------------------------------------------------
# What a page keeps
# ---------------------------------------------------------------------------


def test_a_page_keeps_scenes_and_switches_of_their_own_kind() -> None:
    tile = home.clean_element({"id": "a", "type": "scene", "x": 0, "y": 0, **COZY, "style": "tile", "colour": "sunset", "confirm": True})
    assert tile == {"id": "a", "type": "scene", "x": 0, "y": 0, **COZY, "style": "tile", "colour": "sunset"}, "a scene is not asked before"
    assert "colour" not in home.clean_element({"id": "a", "type": "scene", "x": 0, "y": 0, **COZY, "colour": "plaid"})  # type: ignore[operator]
    assert home.clean_element({"id": "a", "type": "scene", "x": 0, "y": 0, **COFFEE}) is None, "a switch is no scene"
    assert home.clean_element({"id": "a", "type": "switch", "x": 0, "y": 0, **COZY}) is None
    plug = home.clean_element({"id": "a", "type": "switch", "x": 0, "y": 0, **ROUTER, "style": "lever", "confirm": True})
    assert plug is not None and (plug["style"], plug["confirm"]) == ("pill", True)
    assert "confirm" not in home.clean_element({"id": "a", "type": "switch", "x": 0, "y": 0, **ROUTER, "confirm": "yes"})  # type: ignore[operator]
    many = [{"rid": f"r{i}", "entity_id": f"switch.s{i}", "name": f"S{i}"} for i in range(30)]
    card = home.clean_element({"id": "a", "type": "switches", "x": 0, "y": 0, "sensors": [many[0], many[0], COZY, *many[1:]], "confirm": True})
    assert card is not None and len(card["sensors"]) == 24 and card["sensors"][1]["entity_id"] == "switch.s1" and card["confirm"] is True
    room = home.clean_element({"id": "a", "type": "scenes", "x": 0, "y": 0, "style": "carousel", "sensors": [COZY, ROUTINE]})
    assert room is not None and room["style"] == "bar" and [one["entity_id"] for one in room["sensors"]] == ["scene.living_room_cozy", "script.goodnight_routine"]
    assert home.clean_element({"id": "a", "type": "scenes", "x": 0, "y": 0, "sensors": [COFFEE]}) is None


def test_a_page_reads_its_scenes_and_switches_by_the_ids_they_were_placed_with(client: TestClient) -> None:
    setup_admin(client)
    _board_, _hass_, page = _page(client)
    actions = client.get(f"/api/v1/pages/{page['id']}/home").json()["actions"]
    assert set(actions) == {"scene.living_room_cozy", "scene.living_room_cinema", "script.goodnight_routine", "switch.coffee_machine", "switch.router",
                            "input_boolean.guests", "switch.garden_light", "switch.thrown_away"}
    assert actions["switch.thrown_away"] == {"missing": True}
    assert actions["switch.coffee_machine"]["power"] == 1240.0


# ---------------------------------------------------------------------------
# Setting them off
# ---------------------------------------------------------------------------


def test_a_scene_is_set_off_and_a_running_script_stopped(client: TestClient) -> None:
    setup_admin(client)
    _board_, _hass_, page = _page(client)
    cozy = _scene(client, page, "cozy", {})
    assert cozy.status_code == 200, cozy.text
    assert dt.datetime.now(dt.UTC).timestamp() * 1000 - cozy.json()["actions"]["scene.living_room_cozy"]["last"] < 5000
    stopped = _scene(client, page, "routine", {"stop": True})
    assert stopped.json()["actions"]["script.goodnight_routine"]["running"] is False
    assert _scene(client, page, "routine", {}).json()["actions"]["script.goodnight_routine"]["running"] is True
    assert [entry[:2] for entry in _logged()] == [("scene.turn_on", "scene.living_room_cozy"), ("script.turn_off", "script.goodnight_routine"),
                                                    ("script.turn_on", "script.goodnight_routine")]


def test_a_card_of_scenes_sets_off_the_one_it_is_asked_for_and_never_all(client: TestClient) -> None:
    setup_admin(client)
    _board_, _hass_, page = _page(client)
    assert _scene(client, page, "room", {}).status_code == 404, "all scenes of a room at once would end in the last of them"
    one = _scene(client, page, "room", {"member": "scene.living_room_cinema"})
    assert list(one.json()["actions"]) == ["scene.living_room_cinema"]
    assert _scene(client, page, "room", {"member": "scene.goodnight"}).status_code == 404, "not on this card"
    assert _scene(client, page, "cozy", {"member": "scene.living_room_cozy"}).status_code == 404, "a scene is no card"
    assert _switch(client, page, "cozy", {"on": True}).status_code == 404, "a scene is no switch"


def test_a_switch_goes_on_and_off_and_its_device_draws_accordingly(client: TestClient) -> None:
    setup_admin(client)
    _board_, _hass_, page = _page(client)
    off = _switch(client, page, "coffee", {"on": False}).json()["actions"]["switch.coffee_machine"]
    assert (off["on"], off["power"]) == (False, 0.0)
    on = _switch(client, page, "coffee", {"on": True}).json()["actions"]["switch.coffee_machine"]
    assert (on["on"], on["power"]) == (True, 1240.0)


def test_a_card_switches_its_switches_or_the_one_it_names_and_says_which_could_not(client: TestClient) -> None:
    setup_admin(client)
    _board_, _hass_, page = _page(client)
    all_off = _switch(client, page, "office", {"on": False}).json()
    assert set(all_off["actions"]) == {"switch.coffee_machine", "input_boolean.guests"}
    assert {(one["entity_id"], one["code"]) for one in all_off["refused"]} == {("switch.garden_light", "action_unavailable"), ("switch.thrown_away", "action_missing")}
    one = _switch(client, page, "office", {"on": True, "member": "input_boolean.guests"}).json()
    assert list(one["actions"]) == ["input_boolean.guests"] and one["actions"]["input_boolean.guests"]["on"] is True
    alone = _switch(client, page, "office", {"on": True, "member": "switch.garden_light"})
    assert alone.status_code == 409 and alone.json()["detail"]["code"] == "action_unavailable"
    assert _switch(client, page, "office", {"on": True, "member": "switch.router"}).status_code == 404


@pytest.mark.parametrize("body", [{}, {"on": "yes"}, {"on": True, "entity_id": "switch.router"}, {"on": True, "member": "lock.front_door"}, {"on": 1}])
def test_a_switch_is_asked_on_or_off_and_never_named_a_service(client: TestClient, body: object) -> None:
    setup_admin(client)
    _board_, _hass_, page = _page(client)
    assert _switch(client, page, "coffee", body).status_code == 422
    assert _scene(client, page, "cozy", {"stop": "now"}).status_code == 422
    assert _logged() == []


def test_only_who_may_act_on_the_board_sets_anything_off(client: TestClient) -> None:
    setup_admin(client)
    board, _hass_, page = _page(client)
    kim = create_user(client, "kim")
    member = TestClient(client.app)
    login(member, "kim", "another-long-password")
    for level, expected in (("view", 403), ("edit", 403), ("act", 200)):
        client.put(f"/api/v1/boards/{board['slug']}/shares", json={"shares": [{"user_id": kim["id"], "level": level}]}, headers=CSRF)
        assert _switch(member, page, "coffee", {"on": True}).status_code == expected, level
        assert _scene(member, page, "cozy", {}).status_code == expected, level
    client.put(f"/api/v1/boards/{board['slug']}/shares", json={"shares": [{"user_id": kim["id"], "level": "view"}]}, headers=CSRF)
    assert member.get(f"/api/v1/pages/{page['id']}/home/switches").status_code == 403
    assert member.get(f"/api/v1/pages/{page['id']}/home/scenes").status_code == 403
    assert len(client.get(f"/api/v1/pages/{page['id']}/home/scenes").json()["scenes"]) == 7


def test_what_a_switchs_device_used_today_comes_from_its_energy_statistics(client: TestClient) -> None:
    setup_admin(client)
    _board_, _hass_, page = _page(client)
    today = client.get(f"/api/v1/pages/{page['id']}/home/switches/coffee/energy").json()
    assert today["problem"] is None and isinstance(today["today"], float)
    assert client.get(f"/api/v1/pages/{page['id']}/home/switches/router/energy").json()["today"] is None, "no energy sensor"
    card = client.get(f"/api/v1/pages/{page['id']}/home/switches/office/energy", params={"member": "switch.coffee_machine"}).json()
    assert card["today"] == today["today"]
    assert client.get(f"/api/v1/pages/{page['id']}/home/switches/office/energy", params={"member": "switch.router"}).status_code == 404


@respx.mock
def test_a_real_house_is_sent_the_service_and_nothing_else(client: TestClient, monkeypatch) -> None:
    entities, devices, areas, states = hass_registry.demo_registry()

    async def ask(config, commands):
        return [entities, devices, areas, {"unit_system": {"temperature": "°C"}}] + ([list(states.values())] if len(commands) > 4 else [])

    monkeypatch.setattr(hass_registry, "_ask", ask)
    setup_admin(client)
    page = _made(client, _board(client), _hass(client)["id"])
    client.put(f"/api/v1/pages/{page['id']}/home", json={"elements": ELEMENTS}, headers=CSRF)
    scene = respx.post(f"{HA}/api/services/scene/turn_on").mock(return_value=httpx.Response(200, json=[]))
    off = respx.post(f"{HA}/api/services/switch/turn_off").mock(return_value=httpx.Response(500))
    assert _scene(client, page, "cozy", {}).status_code == 200
    assert json.loads(scene.calls[0].request.content) == {"entity_id": "scene.living_room_cozy"}
    failed = _switch(client, page, "coffee", {"on": False})
    assert failed.status_code == 502 and json.loads(off.calls[0].request.content) == {"entity_id": "switch.coffee_machine"}
    assert [entry[2] for entry in _logged()] == [True, False]


@pytest.mark.parametrize(("domain", "service", "data"), [
    ("scene", "turn_on", {"transition": 3}),
    ("scene", "apply", {}),
    ("script", "reload", {}),
    ("switch", "toggle", {}),
    ("input_boolean", "toggle", {}),
])
async def test_their_services_carry_nothing_and_no_other_reaches_home_assistant(domain: str, service: str, data: dict) -> None:
    ctx = _Recording()
    with pytest.raises(AdapterError) as refused:
        await home_control.call({"url": HA}, ctx, domain, service, f"{domain}.a", data)  # type: ignore[arg-type]
    assert refused.value.code == "service_refused" and ctx.calls == []


def test_a_page_hears_when_a_switch_flips_and_when_its_device_draws_more(client: TestClient) -> None:
    setup_admin(client)
    board, hass, page = _page(client)
    client.get(f"/api/v1/pages/{page['id']}/home")
    cache = collector._caches[hass["id"]]
    listener = hub.subscribe({board_topic(board["id"])})
    try:
        home_live.touched(hass["id"], cache, "switch.coffee_machine", {"entity_id": "switch.coffee_machine", "state": "off", "last_changed": "2026-10-20T16:00:00+00:00"})
        home_live._last.clear()
        home_live.touched(hass["id"], cache, "sensor.coffee_machine_power", {"entity_id": "sensor.coffee_machine_power", "state": "17", "attributes": {"unit_of_measurement": "W"}})
        events = _drain(listener)
    finally:
        hub.unsubscribe(listener)
    assert [list(event["actions"]) for event in events] == [["switch.coffee_machine"], ["switch.coffee_machine"]]
    flipped, drawn = events[0]["actions"]["switch.coffee_machine"], events[1]["actions"]["switch.coffee_machine"]
    assert (flipped["on"], flipped["since"]) == (False, 1792512000000) and "name" not in flipped
    assert drawn == {"power": 17.0, "missing": False}, "the power alone, the rest stays"


def test_a_device_whose_energy_sensor_keeps_no_statistics_has_no_use_today(client: TestClient, monkeypatch) -> None:
    from app.services import hass_stats

    kept = hass_stats.demo_catalogue()
    monkeypatch.setattr(hass_stats, "demo_catalogue", lambda: {key: value for key, value in kept.items() if key != "sensor.coffee_machine_energy"})
    setup_admin(client)
    _board_, _hass_, page = _page(client)
    assert client.get(f"/api/v1/pages/{page['id']}/home/switches/coffee/energy").json() == {"today": None, "problem": None}
