"""Switching, dimming and colouring a lamp on a home page.

The browser names an element and what it wants (on or off, a brightness, a
white, a colour); everything else is the server's:
which entity that is today, which of the lamp's own two services, who may
press it, and which open pages hear of it. The demo house of
``hass_registry`` stands in for a real one, and respx for its REST API.
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.adapters.base import AdapterError
from app.db import db_session
from app.models import ActionLog
from app.services import hass_registry, home_control
from app.services.sse import board_topic, hub

from .conftest import CSRF, create_user, login, setup_admin
from .test_home_page import _board, _demo_page, _hass, _heading, _made

LAMPS = [
    {"id": "ceiling", "type": "light", "x": 16, "y": 48, "rid": "r-ceiling", "entity_id": "light.ceiling", "name": "Ceiling light"},
    {"id": "counter", "type": "light", "x": 288, "y": 48, "rid": "r-counter", "entity_id": "light.kitchen_counter", "name": "Kitchen counter"},
    # Placed under a name Home Assistant has changed since; the registry id still finds it.
    {"id": "floor", "type": "light", "x": 560, "y": 48, "rid": "r-floor", "entity_id": "light.renamed_since", "name": "Floor lamp"},
    {"id": "bed", "type": "light", "x": 16, "y": 104, "rid": "r-bed", "entity_id": "light.bedside", "name": "Bedside lamp"},
    {"id": "gone", "type": "light", "x": 288, "y": 104, "rid": "r-unknown", "entity_id": "light.thrown_away", "name": "Thrown away"},
    {"id": "hidden", "type": "light", "x": 560, "y": 104, "rid": "r-hidden", "entity_id": "light.old_bulb", "name": "Old bulb"},
    {"id": "strip", "type": "light", "x": 16, "y": 160, "rid": "r-tv", "entity_id": "light.tv_strip", "name": "LED strip"},
    {"id": "path", "type": "light", "x": 288, "y": 160, "rid": "r-path", "entity_id": "light.garden_path", "name": "Garden path"},
    _heading("living", "Living room"),
]
HA = "http://ha.example.com:8123"


def _lamps_page(client: TestClient) -> tuple[dict, dict, dict]:
    board, hass, page = _demo_page(client)
    saved = client.put(f"/api/v1/pages/{page['id']}/home", json={"elements": LAMPS}, headers=CSRF)
    assert saved.status_code == 200, saved.text
    return board, hass, page


def _switch(client: TestClient, page: dict, element: str, body: object, **headers: str) -> httpx.Response:
    return client.post(f"/api/v1/pages/{page['id']}/home/lights/{element}", json=body, headers={**CSRF, **headers})


def _logged() -> list[tuple[str, str, dict, bool]]:
    with db_session() as db:
        return [(row.actor, row.action, row.params, row.ok) for row in db.scalars(select(ActionLog).order_by(ActionLog.id))]


def _drain(listener) -> list[dict]:
    """The ``home`` events a subscriber of the hub has received, as their payloads."""
    found = []
    while not listener.queue.empty():
        message = listener.queue.get_nowait()
        if message.startswith("event: home\n"):
            found.append(json.loads(message.split("data: ", 1)[1]))
    return found


# ---------------------------------------------------------------------------
# The demo house
# ---------------------------------------------------------------------------


def test_a_lamp_is_switched_and_the_page_shows_how_it_stands_now(client: TestClient) -> None:
    setup_admin(client)
    _board, _hass, page = _lamps_page(client)
    off = _switch(client, page, "ceiling", {"on": False})
    assert off.status_code == 200, off.text
    assert off.json()["confirmed"] is True
    assert off.json()["light"]["on"] is False and off.json()["light"]["name"] == "Ceiling light"
    on = _switch(client, page, "counter", {"on": True}).json()["light"]
    assert on["on"] is True and on["pct"] == 100, "a dimmable lamp that never had a brightness comes on full"
    lights = client.get(f"/api/v1/pages/{page['id']}/home").json()["lights"]
    assert lights["ceiling"]["on"] is False and lights["counter"]["on"] is True
    assert [entry[1:] for entry in _logged()] == [
        ("light.turn_off", {"entity_id": "light.ceiling", "page_id": page["id"]}, True),
        ("light.turn_on", {"entity_id": "light.kitchen_counter", "page_id": page["id"]}, True),
    ]


def test_a_renamed_lamp_is_switched_under_its_name_of_today(client: TestClient) -> None:
    setup_admin(client)
    _board, _hass, page = _lamps_page(client)
    assert _switch(client, page, "floor", {"on": False}).status_code == 200
    assert [entry[1:] for entry in _logged()] == [("light.turn_off", {"entity_id": "light.floor_lamp", "page_id": page["id"]}, True)]


@pytest.mark.parametrize("body", [
    {"on": True, "service": "lock.unlock"},
    {"on": True, "entity_id": "lock.front_door"},
    {"on": True, "domain": "script"},
    {"on": "true"},
    {"on": 1},
    {},
    {"on": False, "brightness_pct": 50},
    {"kelvin": 2700, "hs": [10, 10]},
    {"brightness_pct": 0},
    {"brightness_pct": 101},
    {"brightness_pct": 50.5},
    {"brightness_pct": "50"},
    {"kelvin": "2700"},
    {"kelvin": 500},
    {"hs": [361, 50]},
    {"hs": [10, -1]},
    {"hs": ["12", 80]},
    {"hs": [10]},
    {"hs": [10, 20], "rgb": [1, 2, 3]},
])
def test_the_browser_names_neither_a_service_nor_an_entity(client: TestClient, body: object) -> None:
    setup_admin(client)
    _board, _hass, page = _lamps_page(client)
    assert _switch(client, page, "ceiling", body).status_code == 422
    assert _logged() == []


def test_what_is_not_a_lamp_of_the_page_or_cannot_be_reached_is_not_switched(client: TestClient) -> None:
    setup_admin(client)
    board, _hass, page = _lamps_page(client)
    for element, status, code in (
        ("gone", 409, "lamp_missing"),
        ("hidden", 409, "lamp_missing"),
        ("bed", 409, "lamp_unavailable"),
        ("living", 404, "not_found"),
        ("nothing-here", 404, "not_found"),
    ):
        refused = _switch(client, page, element, {"on": True})
        assert (refused.status_code, refused.json()["detail"]["code"]) == (status, code), element
    cards = next(other for other in client.get(f"/api/v1/boards/{board['slug']}").json()["pages"] if other["kind"] == "cards")
    assert client.post(f"/api/v1/pages/{cards['id']}/home/lights/ceiling", json={"on": True}, headers=CSRF).status_code == 404
    assert _logged() == []


def test_only_who_may_act_on_the_board_switches(client: TestClient) -> None:
    setup_admin(client)
    board, _hass, page = _lamps_page(client)
    kim = create_user(client, "kim")
    member = TestClient(client.app)
    login(member, "kim", "another-long-password")
    for level, expected in (("view", 403), ("edit", 403), ("act", 200)):
        client.put(f"/api/v1/boards/{board['slug']}/shares", json={"shares": [{"user_id": kim["id"], "level": level}]}, headers=CSRF)
        assert _switch(member, page, "ceiling", {"on": False}).status_code == expected, level
    for allowed, expected in ((False, 403), (True, 200)):
        made = client.post(f"/api/v1/boards/{board['slug']}/kiosk-tokens", json={"name": f"hall {allowed}", "allow_actions": allowed}, headers=CSRF)
        display = TestClient(client.app)
        assert _switch(display, page, "ceiling", {"on": True}, **{"X-Kiosk-Token": made.json()["token"]}).status_code == expected, allowed
    assert [entry[0] for entry in _logged()] == ["kim", "kiosk:hall True"]


def test_a_switch_tells_every_open_page_of_the_board(client: TestClient) -> None:
    setup_admin(client)
    board, _hass, page = _lamps_page(client)
    listener = hub.subscribe({board_topic(board["id"])})
    try:
        _switch(client, page, "ceiling", {"on": False})
        [event] = _drain(listener)
    finally:
        hub.unsubscribe(listener)
    assert event["page_id"] == page["id"]
    assert event["lights"]["ceiling"]["on"] is False and event["lights"]["ceiling"]["missing"] is False


def test_a_light_switch_rings_no_bell_and_a_failed_one_does(client: TestClient, monkeypatch) -> None:
    rung: list[str] = []
    monkeypatch.setattr("app.routers.home.emit", lambda event, *args, **kwargs: rung.append(event))
    setup_admin(client)
    _board, _hass, page = _lamps_page(client)
    assert _switch(client, page, "ceiling", {"on": False}).status_code == 200
    assert rung == [], "the lamp on the page is the answer"

    async def refused(*args, **kwargs):
        raise AdapterError("Home Assistant answered with HTTP 500.", code="http_error")

    async def the_demo_lamps(integration):
        return hass_registry.pick_lights(*hass_registry.demo_registry())

    monkeypatch.setattr("app.services.collector.collector.is_demo", lambda integration: False)
    monkeypatch.setattr("app.routers.home._offered", the_demo_lamps)
    monkeypatch.setattr(home_control, "call", refused)
    assert _switch(client, page, "ceiling", {"on": True}).status_code == 502
    assert rung == ["action_failed"]


# ---------------------------------------------------------------------------
# A real house
# ---------------------------------------------------------------------------


def _real_house(client: TestClient, monkeypatch) -> tuple[dict, dict]:
    """A Home Assistant that is not the demo: its registry from ``demo_registry``, its services through respx."""
    entities, devices, areas, states = hass_registry.demo_registry()

    async def ask(config, commands):
        return [entities, devices, areas] + ([list(states.values())] if len(commands) > 3 else [])

    monkeypatch.setattr(hass_registry, "_ask", ask)
    setup_admin(client)
    board = _board(client)
    page = _made(client, board, _hass(client)["id"])
    client.put(f"/api/v1/pages/{page['id']}/home", json={"elements": LAMPS}, headers=CSRF)
    return board, page


@respx.mock
def test_a_real_house_is_asked_for_the_lamps_own_service_and_its_answer_shown(client: TestClient, monkeypatch) -> None:
    board, page = _real_house(client, monkeypatch)
    floor_off = {**hass_registry.demo_registry()[3]["light.floor_lamp"], "state": "off"}
    called = respx.post(f"{HA}/api/services/light/turn_off").mock(return_value=httpx.Response(200, json=[floor_off]))
    listener = hub.subscribe({board_topic(board["id"])})
    try:
        answer = _switch(client, page, "floor", {"on": False})
        pushed = _drain(listener)
    finally:
        hub.unsubscribe(listener)
    assert answer.status_code == 200, answer.text
    assert answer.json()["confirmed"] is True and answer.json()["light"]["on"] is False
    [request] = [call.request for call in called.calls]
    assert json.loads(request.content) == {"entity_id": "light.floor_lamp"}
    assert request.headers["authorization"] == "Bearer a-token"
    assert [list(event["lights"]) for event in pushed] == [["floor"]], "found under its new name, though placed under the old one"


@respx.mock
def test_a_house_that_refuses_or_has_nothing_to_change_says_so(client: TestClient, monkeypatch) -> None:
    _board, page = _real_house(client, monkeypatch)
    respx.post(f"{HA}/api/services/light/turn_on").mock(return_value=httpx.Response(200, json=[]))
    respx.post(f"{HA}/api/services/light/turn_off").mock(return_value=httpx.Response(500))
    already = _switch(client, page, "ceiling", {"on": True})
    assert already.status_code == 200 and already.json()["confirmed"] is False, "on already: Home Assistant names nothing that changed"
    failed = _switch(client, page, "ceiling", {"on": False})
    assert failed.status_code == 502 and failed.json()["detail"]["code"] == "http_error"
    assert [entry[3] for entry in _logged()] == [True, False], "a call that failed is in the log as well"


class _Recording:
    """Stands in for the collector's context: writes down what would have gone out."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, object]] = []

    async def request(self, method, url, **options):
        self.calls.append((method, url, options.get("json_body")))
        return httpx.Response(200, json=[{"entity_id": "light.desk", "state": "on"}])


@pytest.mark.parametrize(("domain", "service", "entity_id"), [
    ("lock", "unlock", "lock.front_door"),
    ("script", "turn_on", "script.everything_off"),
    ("light", "toggle", "light.desk"),
    ("light", "turn_on", "switch.heater"),
    ("light", "turn_on", "light.desk.extra"),
])
async def test_nothing_but_a_lamps_own_two_services_reaches_home_assistant(domain: str, service: str, entity_id: str) -> None:
    ctx = _Recording()
    with pytest.raises(AdapterError) as refused:
        await home_control.call({"url": HA}, ctx, domain, service, entity_id)  # type: ignore[arg-type]
    assert refused.value.code == "service_refused" and ctx.calls == []
    changed = await home_control.call({"url": HA}, ctx, "light", "turn_on", "light.desk")  # type: ignore[arg-type]
    assert ctx.calls == [("POST", f"{HA}/api/services/light/turn_on", {"entity_id": "light.desk"})]
    assert changed == [{"entity_id": "light.desk", "state": "on"}]


async def test_a_page_hears_of_a_lamp_at_most_every_quarter_second_and_always_of_the_last_change(monkeypatch) -> None:
    live = home_control.HomeLive()
    looked: list[int] = []

    def watchers(integration_id, cache):
        looked.append(integration_id)
        return {"light.ceiling": [(5, 9, "ceiling")]}

    monkeypatch.setattr(live, "_watchers", watchers)
    on = hass_registry.demo_registry()[3]["light.ceiling"]
    listener = hub.subscribe({board_topic(5)})
    try:
        live.touched(1, {}, "light.ceiling", {**on, "state": "off"})
        live.touched(1, {}, "light.ceiling", {**on, "attributes": {**on["attributes"], "brightness": 100}})
        live.touched(1, {}, "light.ceiling", on)
        live.touched(1, {}, "switch.floor_plug", on)
        assert listener.queue.qsize() == 1, "the first at once, the rest held back"
        await asyncio.sleep(home_control.PUSH_INTERVAL + 0.15)
        first, last = _drain(listener)
    finally:
        hub.unsubscribe(listener)
    assert looked == [1, 1, 1], "a plug changing is not even looked up: a house sends dozens of changes a second"
    assert first["lights"]["ceiling"]["on"] is False
    assert last == {"page_id": 9, "lights": {"ceiling": {**hass_registry.light_state(on), "missing": False}}}, "only the last of those held back"


# ---------------------------------------------------------------------------
# Dimming, a white, a colour
# ---------------------------------------------------------------------------


def _light(client: TestClient, page: dict, element: str, body: dict) -> dict:
    answer = _switch(client, page, element, body)
    assert answer.status_code == 200, answer.text
    return answer.json()["light"]


def test_a_lamp_is_dimmed_and_an_off_one_comes_on_at_that_brightness(client: TestClient) -> None:
    setup_admin(client)
    _board, _hass, page = _lamps_page(client)
    assert _light(client, page, "ceiling", {"brightness_pct": 30})["pct"] == 30
    counter = _light(client, page, "counter", {"brightness_pct": 40})
    assert counter["on"] is True and counter["pct"] == 40
    assert [entry[1:] for entry in _logged()] == [
        ("light.turn_on", {"entity_id": "light.ceiling", "page_id": page["id"], "brightness_pct": 30}, True),
        ("light.turn_on", {"entity_id": "light.kitchen_counter", "page_id": page["id"], "brightness_pct": 40}, True),
    ]


def test_a_white_stays_inside_what_the_lamp_has(client: TestClient) -> None:
    setup_admin(client)
    _board, _hass, page = _lamps_page(client)
    warm = _light(client, page, "ceiling", {"kelvin": 2000})
    assert (warm["kelvin"], warm["kelvin_min"], warm["kelvin_max"]) == (2700, 2700, 5000)
    assert _light(client, page, "ceiling", {"kelvin": 9000})["kelvin"] == 5000
    assert [entry[2]["color_temp_kelvin"] for entry in _logged()] == [2700, 5000]


def test_a_colour_and_a_white_take_each_others_place(client: TestClient) -> None:
    setup_admin(client)
    _board, _hass, page = _lamps_page(client)
    blue = _light(client, page, "strip", {"hs": [240, 100], "brightness_pct": 50})
    assert blue["rgb"] == [0, 0, 255] and blue["hs"] == [240.0, 100.0] and blue["pct"] == 50
    floor = _light(client, page, "floor", {"kelvin": 4000})
    assert floor["kelvin"] == 4000 and floor["rgb"] is None, "a white drops the colour the lamp had"
    red = _light(client, page, "floor", {"hs": [0, 100]})
    assert red["rgb"] == [255, 0, 0] and red["kelvin"] is None
    assert _logged()[0][2] == {"entity_id": "light.tv_strip", "page_id": page["id"], "brightness_pct": 50, "hs_color": [240.0, 100.0]}


def test_what_a_lamp_cannot_do_is_not_asked_of_it(client: TestClient) -> None:
    setup_admin(client)
    _board, _hass, page = _lamps_page(client)
    for element, body in (
        ("path", {"brightness_pct": 50}),
        ("ceiling", {"hs": [120, 50]}),
        ("counter", {"kelvin": 3000}),
        ("strip", {"kelvin": 3000}),
    ):
        refused = _switch(client, page, element, body)
        assert (refused.status_code, refused.json()["detail"]["code"]) == (409, "not_supported"), (element, body)
    assert _logged() == []
    assert _light(client, page, "path", {"on": True})["on"] is True, "a lamp that only switches still switches"


@respx.mock
def test_a_real_house_is_sent_the_brightness_and_the_white_and_nothing_else(client: TestClient, monkeypatch) -> None:
    _board, page = _real_house(client, monkeypatch)
    called = respx.post(f"{HA}/api/services/light/turn_on").mock(return_value=httpx.Response(200, json=[]))
    _switch(client, page, "ceiling", {"brightness_pct": 30, "kelvin": 6000})
    _switch(client, page, "strip", {"hs": [12.345, 67.891]})
    assert [json.loads(call.request.content) for call in called.calls] == [
        {"entity_id": "light.ceiling", "brightness_pct": 30, "color_temp_kelvin": 5000},
        {"entity_id": "light.tv_strip", "hs_color": [12.3, 67.9]},
    ]


@pytest.mark.parametrize(("service", "data"), [
    ("turn_on", {"effect": "colorloop"}),
    ("turn_on", {"brightness_pct": 50, "flash": "long"}),
    ("turn_off", {"brightness_pct": 5}),
    ("turn_off", {"transition": 600}),
])
async def test_a_lamps_services_carry_nothing_but_their_own_data(service: str, data: dict) -> None:
    ctx = _Recording()
    with pytest.raises(AdapterError) as refused:
        await home_control.call({"url": HA}, ctx, "light", service, "light.desk", data)  # type: ignore[arg-type]
    assert refused.value.code == "service_refused" and ctx.calls == []


def test_a_lamp_says_which_whites_it_has_and_its_colour() -> None:
    def stands(**attributes: object) -> dict:
        return hass_registry.light_state({"state": "on", "attributes": {"supported_color_modes": ["color_temp", "hs"], **attributes}})

    named = stands(min_color_temp_kelvin=2202, max_color_temp_kelvin=6535, hs_color=[30.04, 65.55])
    assert (named["kelvin_min"], named["kelvin_max"], named["hs"]) == (2202, 6535, [30.0, 65.5])
    assert (stands()["kelvin_min"], stands()["kelvin_max"]) == hass_registry.DEFAULT_KELVIN, "Home Assistant's own when the lamp names none"
    for odd in ("warm", True, 50, 99999):
        assert stands(min_color_temp_kelvin=odd)["kelvin_min"] == hass_registry.DEFAULT_KELVIN[0], odd
    white = hass_registry.light_state({"state": "on", "attributes": {"supported_color_modes": ["brightness"]}})
    assert white["kelvin_min"] is None and white["hs"] is None
