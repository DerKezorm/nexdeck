"""Shutters, blinds and awnings on a home page.

What a cover can do (Home Assistant's features), what a page keeps of a
cover and of a card of them with positions of its own, and that moving one
calls nothing but the five cover services with what the cover takes; a card
moves its covers, one of them, or each to a position of the card. The demo
house of ``hass_registry`` stands in for a real one, and respx for its REST API.
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
from app.services import hass_covers, hass_registry, home, home_control
from app.services.collector import collector
from app.services.home_control import home_live
from app.services.sse import board_topic, hub

from .conftest import CSRF, create_user, login, setup_admin
from .test_home_page import _board, _demo_page, _hass, _made
from .test_home_switch import HA, _drain, _Recording

TERRACE = {"rid": "r-cover-terrace", "entity_id": "cover.living_room_terrace", "name": "Living room terrace"}
KITCHEN = {"rid": "r-cover-kitchen", "entity_id": "cover.kitchen", "name": "Kitchen"}
OFFICE = {"rid": "r-cover-office", "entity_id": "cover.office_blind", "name": "Office blind"}
GARAGE = {"rid": "r-cover-garage", "entity_id": "cover.garage_door", "name": "Garage door"}
GUEST = {"rid": "r-cover-guest", "entity_id": "cover.guest_room", "name": "Guest room"}
GONE = {"rid": "r-gone", "entity_id": "cover.thrown_away", "name": "Old shutter"}
ELEMENTS = [
    {"id": "terrace", "type": "cover", "x": 16, "y": 16, **TERRACE, "style": "pill"},
    {"id": "office", "type": "cover", "x": 16, "y": 72, **OFFICE, "style": "tilt"},
    {"id": "garage", "type": "cover", "x": 16, "y": 128, **GARAGE, "style": "tile"},
    {"id": "down", "type": "covers", "x": 400, "y": 16, "style": "group", "title": "Downstairs", "sensors": [TERRACE, KITCHEN, GUEST, GONE]},
    {"id": "all", "type": "covers", "x": 400, "y": 300, "style": "scenes", "title": "", "sensors": [TERRACE, KITCHEN],
     "scenes": [{"name": "Morning", "position": 100}, {"name": "Shade", "position": 30}]},
]


def _covers_page(client: TestClient) -> tuple[dict, dict, dict]:
    board, hass, page = _demo_page(client)
    saved = client.put(f"/api/v1/pages/{page['id']}/home", json={"elements": ELEMENTS}, headers=CSRF)
    assert saved.status_code == 200, saved.text
    return board, hass, page


def _move(client: TestClient, page: dict, element: str, body: object) -> httpx.Response:
    return client.post(f"/api/v1/pages/{page['id']}/home/covers/{element}", json=body, headers=CSRF)


def _logged() -> list[tuple[str, dict, bool]]:
    with db_session() as db:
        return [(row.action, row.params, row.ok) for row in db.scalars(select(ActionLog).order_by(ActionLog.id))]


# ---------------------------------------------------------------------------
# What a cover can do
# ---------------------------------------------------------------------------


def test_a_cover_says_where_it_stands_and_what_it_lets_one_do() -> None:
    def stands(value: str, features: int, **attributes: object) -> dict:
        return hass_covers.cover_state({"state": value, "attributes": {"supported_features": features, **attributes}})

    shutter = stands("closing", 15, current_position=70.4)
    assert (shutter["position"], shutter["moving"], shutter["settable"], shutter["stoppable"], shutter["tiltable"]) == (70, "down", True, True, False)
    blind = stands("open", 255, current_position=100, current_tilt_position="45")
    assert (blind["tilt"], blind["tiltable"]) == (45, True)
    door = stands("closed", 3)
    assert (door["position"], door["settable"], door["can_open"], door["can_close"]) == (0, False, True, True), "no position: closed is 0"
    assert stands("opening", 3)["position"] == 0 and stands("opening", 3)["moving"] == "up"
    assert stands("open", 3)["position"] == 100
    gone = hass_covers.cover_state({"state": "unavailable", "attributes": {}})
    assert (gone["unavailable"], gone["position"]) == (True, None)
    assert stands("open", 15, current_position=140)["position"] == 100


def test_covers_are_offered_with_their_class_and_nothing_hidden() -> None:
    entities, devices, areas, states = hass_registry.demo_registry()
    offered = {one["entity_id"]: one for one in hass_covers.pick_covers(entities, devices, areas, states)}
    assert "cover.old_shutter" not in offered
    assert offered["cover.office_blind"]["device_class"] == "blind" and offered["cover.kitchen"]["area"] == "Kitchen"
    assert len(offered) == 6


@pytest.mark.parametrize(("cover", "asked", "expected"), [
    ({"settable": True}, {"position": 140}, ("set_cover_position", {"position": 100})),
    ({"settable": False, "can_open": True}, {"position": 100}, ("open_cover", {})),
    ({"settable": False, "can_close": True}, {"position": 0}, ("close_cover", {})),
    ({"can_open": True}, {"action": "open"}, ("open_cover", {})),
    ({"can_close": True}, {"action": "close"}, ("close_cover", {})),
    ({"stoppable": True}, {"action": "stop"}, ("stop_cover", {})),
    ({"tiltable": True}, {"tilt": -5}, ("set_cover_tilt_position", {"tilt_position": 0})),
])
def test_a_cover_is_sent_what_it_takes(cover: dict, asked: dict, expected: tuple) -> None:
    domain, service, data = hass_covers.service_for(cover, **asked)
    assert (domain, service, data) == ("cover", *expected)


@pytest.mark.parametrize(("cover", "asked"), [
    ({"settable": False, "can_open": True, "can_close": True}, {"position": 40}),
    ({"stoppable": False}, {"action": "stop"}),
    ({"tiltable": False}, {"tilt": 50}),
    ({"can_open": False}, {"action": "open"}),
    ({"can_close": False}, {"action": "close"}),
    ({}, {}),
])
def test_a_cover_is_not_asked_what_it_cannot(cover: dict, asked: dict) -> None:
    with pytest.raises(AdapterError) as refused:
        hass_covers.service_for({"name": "Door", **cover}, **asked)
    assert refused.value.code == "not_supported"


# ---------------------------------------------------------------------------
# What a page keeps
# ---------------------------------------------------------------------------


def test_a_page_keeps_a_cover_and_a_card_of_them_with_positions_of_its_own() -> None:
    kept = home.clean_element({"id": "a", "type": "cover", "x": 0, "y": 0, **OFFICE, "style": "venetian", "label": "Study"})
    assert kept == {"id": "a", "type": "cover", "x": 0, "y": 0, **OFFICE, "style": "pill", "label": "Study"}
    assert home.clean_element({"id": "a", "type": "cover", "x": 0, "y": 0, "rid": "r", "entity_id": "light.ceiling"}) is None
    many = [{"rid": f"r{i}", "entity_id": f"cover.c{i}", "name": f"C{i}"} for i in range(30)]
    card = home.clean_element({"id": "a", "type": "covers", "x": 0, "y": 0, "style": "scenes", "sensors": [many[0], many[0], *many[1:]],
                               "scenes": [{"name": " Morning ", "position": 100.4}, {"name": "", "position": 10}, {"name": "Shade", "position": True},
                                          {"name": "Night", "position": -20}, *({"name": f"S{i}", "position": i} for i in range(10))]})
    assert card is not None and len(card["sensors"]) == 24 and card["sensors"][1]["entity_id"] == "cover.c1"
    assert card["scenes"][:2] == [{"name": "Morning", "position": 100}, {"name": "Night", "position": 0}] and len(card["scenes"]) == 6
    group = home.clean_element({"id": "a", "type": "covers", "x": 0, "y": 0, "style": "group", "sensors": many[:2], "scenes": [{"name": "X", "position": 1}]})
    assert group is not None and "scenes" not in group, "a group has no positions of its own"
    plain = home.clean_element({"id": "a", "type": "covers", "x": 0, "y": 0, "style": "scenes", "sensors": many[:2]})
    assert plain is not None and plain["scenes"] == list(home.DEFAULT_SCENES)
    assert home.clean_element({"id": "a", "type": "covers", "x": 0, "y": 0, "sensors": []}) is None


def test_a_page_reads_its_covers_by_the_ids_they_were_placed_with(client: TestClient) -> None:
    setup_admin(client)
    _board_, _hass_, page = _covers_page(client)
    covers = client.get(f"/api/v1/pages/{page['id']}/home").json()["covers"]
    assert set(covers) == {"cover.living_room_terrace", "cover.office_blind", "cover.garage_door", "cover.kitchen", "cover.guest_room", "cover.thrown_away"}
    assert covers["cover.thrown_away"] == {"missing": True}
    assert (covers["cover.kitchen"]["position"], covers["cover.office_blind"]["tilt"]) == (45, 45)


# ---------------------------------------------------------------------------
# Moving them
# ---------------------------------------------------------------------------


def test_a_cover_goes_where_it_is_sent_and_into_the_log(client: TestClient) -> None:
    setup_admin(client)
    _board_, _hass_, page = _covers_page(client)
    answer = _move(client, page, "terrace", {"position": 40})
    assert answer.status_code == 200, answer.text
    assert answer.json()["covers"]["cover.living_room_terrace"]["position"] == 40
    assert _move(client, page, "office", {"tilt": 80}).json()["covers"]["cover.office_blind"]["tilt"] == 80
    assert _move(client, page, "garage", {"action": "open"}).json()["covers"]["cover.garage_door"]["position"] == 100
    refused = _move(client, page, "garage", {"position": 50})
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "not_supported"
    assert [(action, params["entity_id"], ok) for action, params, ok in _logged()] == [
        ("cover.set_cover_position", "cover.living_room_terrace", True), ("cover.set_cover_tilt_position", "cover.office_blind", True),
        ("cover.open_cover", "cover.garage_door", True)]


def test_a_card_moves_its_covers_or_the_one_it_names_and_says_which_could_not(client: TestClient) -> None:
    setup_admin(client)
    _board_, _hass_, page = _covers_page(client)
    all_down = _move(client, page, "down", {"action": "close"}).json()
    assert set(all_down["covers"]) == {"cover.living_room_terrace", "cover.kitchen"}
    assert all(one["position"] == 0 for one in all_down["covers"].values())
    assert {(one["entity_id"], one["code"]) for one in all_down["refused"]} == {("cover.guest_room", "cover_unavailable"), ("cover.thrown_away", "cover_missing")}
    one = _move(client, page, "down", {"position": 60, "member": "cover.kitchen"}).json()
    assert list(one["covers"]) == ["cover.kitchen"] and one["refused"] == []
    assert _move(client, page, "down", {"action": "open", "member": "cover.office_blind"}).status_code == 404, "not on this card"
    alone = _move(client, page, "down", {"action": "open", "member": "cover.guest_room"})
    assert alone.status_code == 409 and alone.json()["detail"]["code"] == "cover_unavailable"
    assert _move(client, page, "terrace", {"action": "open", "member": "cover.living_room_terrace"}).status_code == 404, "a cover is no card"


def test_a_position_of_the_card_sends_each_of_its_covers_there(client: TestClient) -> None:
    setup_admin(client)
    _board_, _hass_, page = _covers_page(client)
    shade = _move(client, page, "all", {"scene": 1}).json()
    assert {entity: one["position"] for entity, one in shade["covers"].items()} == {"cover.living_room_terrace": 30, "cover.kitchen": 30}
    assert _move(client, page, "all", {"scene": 2}).status_code == 404
    assert _move(client, page, "terrace", {"scene": 0}).status_code == 404


@pytest.mark.parametrize("body", [{}, {"action": "open", "position": 10}, {"action": "explode"}, {"position": 101}, {"tilt": "50"},
                                  {"action": "open", "entity_id": "cover.kitchen"}, {"scene": 0, "member": "light.ceiling"}])
def test_a_cover_is_asked_one_thing_and_never_named_a_service(client: TestClient, body: object) -> None:
    setup_admin(client)
    _board_, _hass_, page = _covers_page(client)
    assert _move(client, page, "terrace", body).status_code == 422
    assert _logged() == []


def test_only_who_may_act_on_the_board_moves_a_cover(client: TestClient) -> None:
    setup_admin(client)
    board, _hass_, page = _covers_page(client)
    kim = create_user(client, "kim")
    member = TestClient(client.app)
    login(member, "kim", "another-long-password")
    for level, expected in (("view", 403), ("edit", 403), ("act", 200)):
        client.put(f"/api/v1/boards/{board['slug']}/shares", json={"shares": [{"user_id": kim["id"], "level": level}]}, headers=CSRF)
        assert _move(member, page, "terrace", {"action": "open"}).status_code == expected, level
    client.put(f"/api/v1/boards/{board['slug']}/shares", json={"shares": [{"user_id": kim["id"], "level": "view"}]}, headers=CSRF)
    assert member.get(f"/api/v1/pages/{page['id']}/home/covers").status_code == 403, "the offer is for who arranges"
    assert client.get(f"/api/v1/pages/{page['id']}/home/covers").json()["problem"] is None


@respx.mock
def test_a_real_house_is_sent_the_position_and_nothing_else(client: TestClient, monkeypatch) -> None:
    entities, devices, areas, states = hass_registry.demo_registry()

    async def ask(config, commands):
        return [entities, devices, areas, {"unit_system": {"temperature": "°C"}}] + ([list(states.values())] if len(commands) > 4 else [])

    monkeypatch.setattr(hass_registry, "_ask", ask)
    setup_admin(client)
    page = _made(client, _board(client), _hass(client)["id"])
    client.put(f"/api/v1/pages/{page['id']}/home", json={"elements": ELEMENTS}, headers=CSRF)
    moved = respx.post(f"{HA}/api/services/cover/set_cover_position").mock(return_value=httpx.Response(200, json=[]))
    stopped = respx.post(f"{HA}/api/services/cover/stop_cover").mock(return_value=httpx.Response(500))
    assert _move(client, page, "terrace", {"position": 25}).status_code == 200
    assert json.loads(moved.calls[0].request.content) == {"entity_id": "cover.living_room_terrace", "position": 25}
    failed = _move(client, page, "terrace", {"action": "stop"})
    assert failed.status_code == 502 and json.loads(stopped.calls[0].request.content) == {"entity_id": "cover.living_room_terrace"}
    assert [entry[2] for entry in _logged()] == [True, False]


@pytest.mark.parametrize(("service", "data"), [
    ("set_cover_position", {"position": 20, "tilt_position": 3}),
    ("open_cover", {"position": 100}),
    ("set_cover_tilt_position", {"position": 4}),
    ("toggle", {}),
])
async def test_a_covers_services_carry_nothing_but_their_own_data(service: str, data: dict) -> None:
    ctx = _Recording()
    with pytest.raises(AdapterError) as refused:
        await home_control.call({"url": HA}, ctx, "cover", service, "cover.kitchen", data)  # type: ignore[arg-type]
    assert refused.value.code == "service_refused" and ctx.calls == []


def test_a_page_hears_when_a_cover_moves(client: TestClient) -> None:
    setup_admin(client)
    board, hass, page = _covers_page(client)
    client.get(f"/api/v1/pages/{page['id']}/home")
    cache = collector._caches[hass["id"]]
    listener = hub.subscribe({board_topic(board["id"])})
    try:
        home_live.touched(hass["id"], cache, "cover.kitchen",
                          {"entity_id": "cover.kitchen", "state": "opening", "attributes": {"supported_features": 15, "current_position": 52}})
        events = _drain(listener)
    finally:
        hub.unsubscribe(listener)
    assert [list(event["covers"]) for event in events] == [["cover.kitchen"]], "on two cards of one page: one event"
    kitchen = events[0]["covers"]["cover.kitchen"]
    assert (kitchen["position"], kitchen["moving"], kitchen["missing"]) == (52, "up", False) and "name" not in kitchen
