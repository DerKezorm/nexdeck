"""Home pages: a free surface of Home Assistant controls.

Checked here: who may make one, what a browser may store on it, that it
travels with its board, that cards stay off it, and which lamps of the house
it offers and finds again. The demo house of ``hass_registry`` stands in for
a real one; it is shaped after a registry measured on 20.10.2026.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.services import hass_registry, home

from .conftest import CSRF, create_user, login, setup_admin


def _board(client: TestClient, name: str = "House") -> dict:
    response = client.post("/api/v1/boards", json={"name": name}, headers=CSRF)
    assert response.status_code == 201, response.text
    return response.json()


def _hass(client: TestClient, name: str = "Home Assistant", **extra: object) -> dict:
    response = client.post("/api/v1/integrations", json={"kind": "homeassistant", "name": name, "config": {"url": "http://ha.example.com:8123", "token": "a-token"}, **extra}, headers=CSRF)
    assert response.status_code == 201, response.text
    return response.json()


def _home_page(client: TestClient, board: dict, integration_id: int | None):
    return client.post(f"/api/v1/boards/{board['slug']}/pages", json={"name": "Home", "kind": "home", "integration_id": integration_id}, headers=CSRF)


def _made(client: TestClient, board: dict, integration_id: int) -> dict:
    made = _home_page(client, board, integration_id)
    assert made.status_code == 201, made.text
    return next(page for page in made.json()["pages"] if page["kind"] == "home")


def _heading(element_id: str, text: str, x: float = 16, y: float = 16) -> dict:
    return {"id": element_id, "type": "heading", "x": x, "y": y, "text": text}


# ---------------------------------------------------------------------------
# What a browser may store
# ---------------------------------------------------------------------------


def test_a_heading_is_kept_as_it_was_placed() -> None:
    layout = home.clean_layout({"elements": [_heading("living", "Living room", 24.4, 103.6)]}, 7)
    assert layout == {"integration_id": 7, "elements": [{"id": "living", "type": "heading", "x": 24, "y": 104, "text": "Living room"}]}


def test_what_the_page_does_not_know_is_left_out_and_the_rest_kept() -> None:
    raw = {"elements": [
        _heading("ok", "Kitchen"),
        {"id": "unknown", "type": "camera", "x": 1, "y": 1, "text": "x"},
        _heading("bad id!", "Hall"),
        _heading("", "Hall"),
        _heading("off", "Garden", x=-5),
        _heading("far", "Garden", y=home.MAX_COORD + 1),
        _heading("nan", "Garden", x=float("nan")),
        {"id": "flag", "type": "heading", "x": True, "y": 1, "text": "Flag"},
        _heading("blank", "   "),
        _heading("ok", "A second one with the same id"),
        "not an element",
    ]}
    layout = home.clean_layout(raw, None)
    assert [element["id"] for element in layout["elements"]] == ["ok"]
    assert layout["elements"][0]["text"] == "Kitchen"


def test_a_heading_is_one_line_of_bounded_length() -> None:
    [element] = home.clean_layout({"elements": [_heading("long", "  Up\nstairs\t" + "x" * 200)]}, None)["elements"]
    assert "\n" not in element["text"] and "\t" not in element["text"]
    assert element["text"].startswith("Upstairs") and len(element["text"]) == home.MAX_TEXT


def test_a_page_keeps_a_bounded_number_of_elements() -> None:
    raw = {"elements": [_heading(f"h{index}", f"Heading {index}") for index in range(home.MAX_ELEMENTS + 20)]}
    assert len(home.clean_layout(raw, None)["elements"]) == home.MAX_ELEMENTS


# ---------------------------------------------------------------------------
# The page
# ---------------------------------------------------------------------------


def test_a_home_page_needs_a_home_assistant_connection_this_person_may_use(client: TestClient) -> None:
    setup_admin(client)
    board = _board(client)
    assert _home_page(client, board, None).json()["detail"]["code"] == "integration_required"
    radarr = client.post("/api/v1/integrations", json={"kind": "radarr", "name": "Movies", "config": {"url": "http://radarr:7878", "api_key": "k"}}, headers=CSRF).json()
    assert _home_page(client, board, radarr["id"]).json()["detail"]["code"] == "kind_mismatch"
    locked = _hass(client, "Locked", admin_only=True)
    create_user(client, "kim")
    login(client, "kim", "another-long-password")
    own = _board(client, "Kim")
    refused = _home_page(client, own, locked["id"])
    assert refused.status_code == 403 and refused.json()["detail"]["code"] == "integration_locked"


def test_a_new_home_page_is_empty_and_names_its_connection(client: TestClient) -> None:
    setup_admin(client)
    board = _board(client)
    hass = _hass(client)
    page = _made(client, board, hass["id"])
    assert page["home"] == {"integration_id": hass["id"]} and page["topology"] is None
    answer = client.get(f"/api/v1/pages/{page['id']}/home").json()
    assert answer["layout"] == {"integration_id": hass["id"], "elements": []}
    assert answer["problem"] is None
    cards_page = next(p for p in client.get(f"/api/v1/boards/{board['slug']}").json()["pages"] if p["kind"] == "cards")
    assert cards_page["home"] is None
    assert client.get(f"/api/v1/pages/{cards_page['id']}/home").status_code == 404


def test_what_stands_where_is_saved_refused_when_stale_and_only_by_editors(client: TestClient) -> None:
    setup_admin(client)
    board = _board(client)
    hass = _hass(client)
    page = _made(client, board, hass["id"])
    url = f"/api/v1/pages/{page['id']}/home"
    version = client.get(url).json()["version"]
    saved = client.put(url, json={"elements": [_heading("living", "Living room", 40, 32)], "version": version}, headers=CSRF)
    assert saved.status_code == 200, saved.text
    assert saved.json()["layout"]["elements"] == [{"id": "living", "type": "heading", "x": 40, "y": 32, "text": "Living room"}]
    assert saved.json()["version"] == version + 1
    stale = client.put(url, json={"elements": [], "version": version}, headers=CSRF)
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "layout_moved_on"
    assert client.get(url).json()["layout"]["elements"][0]["text"] == "Living room"
    client.put(f"/api/v1/boards/{board['slug']}/shares", json={"shares": [{"role": "user", "level": "view"}]}, headers=CSRF)
    create_user(client, "viewer")
    login(client, "viewer", "another-long-password")
    assert client.get(url).status_code == 200
    assert client.put(url, json={"elements": []}, headers=CSRF).status_code == 403


def test_the_browser_cannot_move_a_page_to_another_connection(client: TestClient) -> None:
    setup_admin(client)
    board = _board(client)
    first, second = _hass(client, "Downstairs"), _hass(client, "Upstairs")
    page = _made(client, board, first["id"])
    saved = client.put(f"/api/v1/pages/{page['id']}/home", json={"elements": [], "integration_id": second["id"]}, headers=CSRF)
    assert saved.status_code == 200
    assert saved.json()["layout"]["integration_id"] == first["id"]


def test_a_page_whose_connection_went_or_was_switched_off_says_so(client: TestClient) -> None:
    setup_admin(client)
    board = _board(client)
    hass = _hass(client)
    page = _made(client, board, hass["id"])
    url = f"/api/v1/pages/{page['id']}/home"
    client.patch(f"/api/v1/integrations/{hass['id']}", json={"enabled": False}, headers=CSRF)
    assert client.get(url).json()["problem"]["code"] == "integration_disabled"
    assert client.delete(f"/api/v1/integrations/{hass['id']}", headers=CSRF).status_code in (200, 204)
    answer = client.get(url).json()
    assert answer["problem"]["code"] == "no_integration" and answer["layout"]["elements"] == []


def test_export_and_import_keep_what_stands_where_and_the_connection_by_name(client: TestClient) -> None:
    setup_admin(client)
    board = _board(client)
    hass = _hass(client)
    page = _made(client, board, hass["id"])
    client.put(f"/api/v1/pages/{page['id']}/home", json={"elements": [_heading("garden", "Garden", 8, 400)]}, headers=CSRF)
    text = client.get(f"/api/v1/boards/{board['slug']}/export").text
    assert "kind: home" in text and "a-token" not in text
    copy = client.post("/api/v1/boards/import", json={"yaml_text": text, "slug": "house-copy"}, headers=CSRF)
    assert copy.status_code == 201, copy.text
    copied = next(p for p in copy.json()["pages"] if p["kind"] == "home")
    assert copied["home"] == {"integration_id": hass["id"]}
    elements = client.get(f"/api/v1/pages/{copied['id']}/home").json()["layout"]["elements"]
    assert elements == [{"id": "garden", "type": "heading", "x": 8, "y": 400, "text": "Garden"}]


# ---------------------------------------------------------------------------
# Cards stay on card pages
# ---------------------------------------------------------------------------


def test_cards_stay_off_a_home_page_and_off_a_network_plan_however_they_come(client: TestClient) -> None:
    """Made there, moved there by its settings, or carried there with others: refused each way."""
    setup_admin(client)
    board = _board(client)
    hass = _hass(client)
    unifi = client.post("/api/v1/integrations", json={"kind": "unifi", "name": "UniFi", "demo": True, "config": {"url": "https://unifi.example.com", "api_key": "k"}}, headers=CSRF).json()
    home_page = _made(client, board, hass["id"])
    plan = client.post(f"/api/v1/boards/{board['slug']}/pages", json={"name": "Network", "kind": "topology", "integration_id": unifi["id"]}, headers=CSRF)
    plan_page = next(p for p in plan.json()["pages"] if p["kind"] == "topology")
    cards_page = next(p for p in plan.json()["pages"] if p["kind"] == "cards")
    card = client.post(f"/api/v1/pages/{cards_page['id']}/widgets", json={"kind": "core.clock"}, headers=CSRF)
    assert card.status_code == 201, card.text
    card_id = card.json()["widget"]["id"]
    for target, code in ((home_page, "home_page"), (plan_page, "topology_page")):
        made = client.post(f"/api/v1/pages/{target['id']}/widgets", json={"kind": "core.clock"}, headers=CSRF)
        assert made.status_code == 400 and made.json()["detail"]["code"] == code
        moved = client.patch(f"/api/v1/widgets/{card_id}", json={"page_id": target["id"]}, headers=CSRF)
        assert moved.status_code == 400 and moved.json()["detail"]["code"] == code
        carried = client.post("/api/v1/widgets/move", json={"ids": [card_id], "page_id": target["id"]}, headers=CSRF)
        assert carried.status_code == 400 and carried.json()["detail"]["code"] == code
    stays = next(p for p in client.get(f"/api/v1/boards/{board['slug']}").json()["pages"] if p["id"] == cards_page["id"])
    assert [widget["id"] for widget in stays["widgets"]] == [card_id]


# ---------------------------------------------------------------------------
# Lamps from Home Assistant
# ---------------------------------------------------------------------------


def test_only_lamps_worth_a_wall_are_offered() -> None:
    """Settings, hidden and disabled entities, other domains and entries without a state stay out."""
    offered = hass_registry.pick_lights(*hass_registry.demo_registry())
    assert [light["entity_id"] for light in offered] == [
        "light.bedside", "light.ceiling", "light.dining_table", "light.floor_lamp", "light.garden_path", "light.kitchen_counter", "light.tv_strip",
    ]
    by_id = {light["entity_id"]: light for light in offered}
    floor = by_id["light.floor_lamp"]
    assert floor["rid"] == "r-floor" and floor["name"] == "Floor lamp" and floor["area"] == "Living room" and floor["device"] == "Floor lamp"
    assert by_id["light.dining_table"]["area"] == "Living room" and by_id["light.dining_table"]["group"] is True


def test_what_a_lamp_can_do_follows_its_colour_modes() -> None:
    offered = {light["entity_id"]: light for light in hass_registry.pick_lights(*hass_registry.demo_registry())}
    can = {entity_id: (light["dims"], light["temperature"], light["colour"]) for entity_id, light in offered.items()}
    assert can["light.garden_path"] == (False, False, False)
    assert can["light.kitchen_counter"] == (True, False, False)
    assert can["light.ceiling"] == (True, True, False)
    assert can["light.tv_strip"] == (True, False, True) and can["light.floor_lamp"] == (True, True, True)
    floor = offered["light.floor_lamp"]
    assert floor["on"] is True and floor["pct"] == 62 and floor["kelvin"] == 2400 and floor["rgb"] == [255, 167, 87]
    assert offered["light.kitchen_counter"]["on"] is False and offered["light.kitchen_counter"]["pct"] is None
    assert offered["light.bedside"]["unavailable"] is True and offered["light.bedside"]["on"] is False


def test_a_lamp_is_kept_by_registry_id_entity_id_and_name() -> None:
    raw = {"elements": [
        {"id": "a", "type": "light", "x": 8, "y": 8, "rid": "0123abcd", "entity_id": "light.floor_lamp", "name": "Floor lamp", "style": "pill"},
        {"id": "b", "type": "light", "x": 8, "y": 8, "rid": "0123abcd", "entity_id": "light.desk", "style": "neon"},
        {"id": "c", "type": "light", "x": 8, "y": 8, "rid": "0123abcd", "entity_id": "switch.floor_plug"},
        {"id": "d", "type": "light", "x": 8, "y": 8, "rid": "0123abcd", "entity_id": "light.Upper"},
        {"id": "e", "type": "light", "x": 8, "y": 8, "rid": "not an id!", "entity_id": "light.desk"},
        {"id": "f", "type": "light", "x": 8, "y": 8, "entity_id": "light.desk"},
    ]}
    elements = home.clean_layout(raw, None)["elements"]
    assert [element["id"] for element in elements] == ["a", "b"]
    assert elements[0] == {"id": "a", "type": "light", "x": 8, "y": 8, "rid": "0123abcd", "entity_id": "light.floor_lamp", "name": "Floor lamp", "style": "pill"}
    assert elements[1]["style"] == "pill" and elements[1]["name"] == ""


def _demo_page(client: TestClient, **extra: object) -> tuple[dict, dict, dict]:
    board = _board(client)
    hass = _hass(client, demo=True, **extra)
    return board, hass, _made(client, board, hass["id"])


def test_those_who_arrange_the_page_are_offered_its_lamps_and_nobody_else(client: TestClient) -> None:
    setup_admin(client)
    board, _connection, page = _demo_page(client)
    answer = client.get(f"/api/v1/pages/{page['id']}/home/lights")
    assert answer.status_code == 200, answer.text
    assert answer.json()["problem"] is None
    assert len(answer.json()["lights"]) == 7
    client.put(f"/api/v1/boards/{board['slug']}/shares", json={"shares": [{"role": "user", "level": "view"}]}, headers=CSRF)
    create_user(client, "viewer")
    login(client, "viewer", "another-long-password")
    assert client.get(f"/api/v1/pages/{page['id']}/home/lights").status_code == 403


def test_a_connection_reserved_for_administrators_offers_no_lamps_to_a_member(client: TestClient) -> None:
    setup_admin(client)
    board, _connection, page = _demo_page(client, admin_only=True)
    client.put(f"/api/v1/boards/{board['slug']}/shares", json={"shares": [{"role": "user", "level": "edit"}]}, headers=CSRF)
    create_user(client, "kim")
    login(client, "kim", "another-long-password")
    refused = client.get(f"/api/v1/pages/{page['id']}/home/lights")
    assert refused.status_code == 403 and refused.json()["detail"]["code"] == "integration_locked"


def test_a_placed_lamp_is_found_again_after_it_was_renamed_and_a_gone_one_says_so(client: TestClient) -> None:
    setup_admin(client)
    _view, _connection, page = _demo_page(client)
    url = f"/api/v1/pages/{page['id']}/home"
    client.put(url, json={"elements": [
        {"id": "lamp", "type": "light", "x": 16, "y": 48, "rid": "r-floor", "entity_id": "light.renamed_since", "name": "Old name"},
        {"id": "gone", "type": "light", "x": 216, "y": 48, "rid": "r-unknown", "entity_id": "light.thrown_away", "name": "Thrown away"},
        {"id": "hidden", "type": "light", "x": 416, "y": 48, "rid": "r-hidden", "entity_id": "light.old_bulb", "name": "Old bulb"},
    ]}, headers=CSRF)
    answer = client.get(url).json()
    assert answer["problem"] is None
    lamp = answer["lights"]["lamp"]
    assert lamp["missing"] is False and lamp["entity_id"] == "light.floor_lamp" and lamp["name"] == "Floor lamp" and lamp["on"] is True
    assert answer["lights"]["gone"] == {"missing": True}
    assert answer["lights"]["hidden"] == {"missing": True}, "hidden in Home Assistant is gone from the page"


def test_a_house_that_cannot_be_reached_is_said_on_the_page_and_in_the_offer(client: TestClient) -> None:
    setup_admin(client)
    board = _board(client)
    hass = client.post("/api/v1/integrations", json={"kind": "homeassistant", "name": "Away", "config": {"url": "http://127.0.0.1:9", "token": "t"}}, headers=CSRF).json()
    page = _made(client, board, hass["id"])
    offer = client.get(f"/api/v1/pages/{page['id']}/home/lights").json()
    assert offer["lights"] == [] and offer["problem"]["code"] == "unreachable"
    client.put(f"/api/v1/pages/{page['id']}/home", json={"elements": [{"id": "lamp", "type": "light", "x": 0, "y": 0, "rid": "r1", "entity_id": "light.desk", "name": "Desk"}]}, headers=CSRF)
    answer = client.get(f"/api/v1/pages/{page['id']}/home").json()
    assert answer["problem"]["code"] == "unreachable" and answer["layout"]["elements"][0]["name"] == "Desk"


async def test_the_registries_are_asked_once_a_minute_and_the_live_states_win(monkeypatch) -> None:
    entities, devices, areas, states = hass_registry.demo_registry()
    asked: list[list[str]] = []

    async def ask(config, commands):
        asked.append([command["type"] for command in commands])
        answers = [entities, devices, areas, {"unit_system": {"temperature": "°C"}}]
        return answers + ([list(states.values())] if len(commands) > 4 else [])

    monkeypatch.setattr(hass_registry, "_ask", ask)
    cache: dict = {}
    first = await hass_registry.lights({}, cache, now=100.0)
    assert asked == [["config/entity_registry/list", "config/device_registry/list", "config/area_registry/list", "get_config", "get_states"]]
    await hass_registry.lights({}, cache, now=150.0)
    assert len(asked) == 1, "kept for a minute"
    assert {light["entity_id"]: light["on"] for light in first}["light.kitchen_counter"] is False
    counter = states["light.kitchen_counter"]
    cache["hass_states"] = {**states, "light.kitchen_counter": {**counter, "state": "on", "attributes": {**counter["attributes"], "brightness": 255}}}
    now_on = {light["entity_id"]: light for light in await hass_registry.lights({}, cache, now=155.0)}
    assert len(asked) == 1, "a lamp switched a moment ago shows without asking the registries again"
    assert now_on["light.kitchen_counter"]["on"] is True and now_on["light.kitchen_counter"]["pct"] == 100
    await hass_registry.lights({}, cache, now=101.0 + hass_registry.REGISTRY_SECONDS)
    assert len(asked) == 2 and asked[1][-1] == "get_config", "after a minute the registries again, but not the states the listener has"


def test_every_style_of_the_board_of_sketches_is_kept_and_nothing_else() -> None:
    raw = {"elements": [{"id": f"l{index}", "type": "light", "x": 0, "y": 0, "rid": "r1", "entity_id": "light.desk", "style": style}
                        for index, style in enumerate([*home.STYLES, "neon", None, 3])]}
    kept = [element["style"] for element in home.clean_layout(raw, None)["elements"]]
    assert kept == [*home.STYLES, "pill", "pill", "pill"]
    assert len(home.STYLES) == 10 and home.STYLES[0] == "pill"


def test_the_browser_knows_the_same_styles_as_the_server() -> None:
    import re
    from pathlib import Path

    source = (Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "home.ts").read_text(encoding="utf-8")
    found = re.search(r"export const LAMP_STYLES = \[([^\]]*)\] as const", source)
    assert found, "LAMP_STYLES is no longer where this test reads it"
    assert tuple(re.findall(r"'([a-z]+)'", found.group(1))) == home.STYLES
