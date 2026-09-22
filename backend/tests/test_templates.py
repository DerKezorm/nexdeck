"""Ready-made boards.

The first half guards the template files themselves: a template names widget
kinds for every service a slot can take, lays its cards out on its own
columns, and ships words the German interface has to know. None of that is
checked when the file is written, and a template that does not import is
found by the first person who presses the button.

The second half makes boards from them through the API.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.adapters import split_widget_kind
from app.services import grid, templates

from .conftest import CSRF, create_user, login, setup_admin

GERMAN = Path(__file__).resolve().parents[2] / "frontend" / "src" / "i18n" / "texts.de.json"
ALL = list(templates._all().values())
IDS = [document["template"]["id"] for document in ALL]


def _overlap(one: dict, other: dict) -> bool:
    return (one["x"] < other["x"] + other["w"] and other["x"] < one["x"] + one["w"]
            and one["y"] < other["y"] + other["h"] and other["y"] < one["y"] + one["h"])


def test_there_are_templates_to_guard() -> None:
    assert len(ALL) >= 6, "no templates were found, so the guards below look at nothing"
    assert len(set(IDS)) == len(IDS)


@pytest.mark.parametrize("document", ALL, ids=IDS)
def test_every_card_exists_for_every_service_its_slot_takes(document: dict) -> None:
    missing = []
    for kind in templates.kinds_used(document):
        try:
            templates.check(kind)
        except KeyError:
            missing.append(kind)
    assert missing == [], f"{document['template']['id']} names widget kinds that do not exist"
    slots = {slot["name"] for slot in document["template"].get("slots") or []}
    for page in document["pages"]:
        for card in page["cards"]:
            assert ("slot" in card) != ("kind" in card), card
            assert card.get("slot") in slots | {None}, card
            assert card["title"], card


@pytest.mark.parametrize("document", ALL, ids=IDS)
def test_every_page_is_laid_out_inside_its_columns_without_overlaps_or_holes(document: dict) -> None:
    columns = grid.columns(document["template"].get("settings"))
    assert columns in grid.CHOICES
    kinds = {slot["name"]: slot["kinds"] for slot in document["template"].get("slots") or []}
    for page in document["pages"]:
        spots = []
        for number, card in enumerate(page["cards"]):
            x, y, w, h = card["at"]
            spot = {"i": str(number), "x": x, "y": y, "w": w, "h": h}
            assert x >= 0 and y >= 0 and x + w <= columns, f"{card['title']} reaches past {columns} columns"
            # Wide enough for the widest floor among the services the slot takes.
            for kind in ([f"{k}.{card['widget']}" for k in kinds[card["slot"]]] if card.get("slot") else [card["kind"]]):
                adapter, widget_kind = split_widget_kind(kind)
                floor = adapter.widget(widget_kind).min_size
                assert w >= grid.widen(floor[0], columns) and h >= floor[1], f"{card['title']} is smaller than {kind} can be drawn"
            spots.append(spot)
        assert not any(_overlap(a, b) for n, a in enumerate(spots) for b in spots[n + 1:]), f"{page['name']}: cards overlap"
        # A hole in the template would be closed at once when a slot stays
        # empty, and the other cards would move for no reason anybody sees.
        assert sorted((s["i"], s["y"]) for s in grid.close_gaps(spots)) == sorted((s["i"], s["y"]) for s in spots), f"{page['name']}: a hole"


def test_every_word_of_a_template_has_a_german_entry() -> None:
    german = json.loads(GERMAN.read_text(encoding="utf-8"))["adapter"]
    missing = sorted({word for document in ALL for word in templates.words(document) if word not in german})
    assert missing == [], f"template words without a German entry: {missing}"


# -- through the API ----------------------------------------------------------


def _connection(client: TestClient, kind: str, name: str, **extra) -> int:
    answer = client.post("/api/v1/integrations", json={"kind": kind, "name": name, "config": {}, "demo": True, **extra}, headers=CSRF)
    assert answer.status_code == 201, answer.text
    return int(answer.json()["id"])


def _spots(view: dict) -> dict[str, tuple[int, int, int, int]]:
    page = view["pages"][0]
    titles = {str(w["id"]): w["title"] for w in page["widgets"]}
    return {titles[s["i"]]: (s["x"], s["y"], s["w"], s["h"]) for s in page["layouts"]["lg"]}


def test_the_list_comes_in_order_with_what_a_tile_needs(client: TestClient) -> None:
    setup_admin(client)
    answer = client.get("/api/v1/templates").json()
    assert [entry["id"] for entry in answer] == ["homelab", "media", "network", "servers", "nexapps", "wall"]
    media = answer[1]
    assert [slot["name"] for slot in media["slots"]][0] == "Media server"
    assert [kind["kind"] for kind in media["slots"][0]["kinds"]] == ["jellyfin", "plex", "emby"]
    assert media["cards"] == len(media["sketch"]) == 12
    assert "Now playing" in media["words"]


def test_a_template_with_every_slot_filled_is_the_board_it_describes(client: TestClient) -> None:
    setup_admin(client)
    slots = {
        "Containers": _connection(client, "portainer", "Portainer"),
        "Uptime": _connection(client, "uptimekuma", "Kuma"),
        "DNS filter": _connection(client, "adguard", "AdGuard"),
        "Speed test": _connection(client, "nexpulse", "nexpulse"),
    }
    made = client.post("/api/v1/templates/homelab", json={"slots": slots}, headers=CSRF)
    assert made.status_code == 201, made.text
    view = made.json()
    assert view["name"] == "Homelab overview" and view["settings"] == {"columns": 24}
    placed = _spots(view)
    for card in templates.get("homelab")["pages"][0]["cards"]:
        assert placed[card["title"]] == tuple(card["at"]), card["title"]
    kinds = {w["title"]: w["kind"] for w in view["pages"][0]["widgets"]}
    assert kinds["Running containers"] == "portainer.containers" and kinds["Most blocked"] == "adguard.top"


def test_an_empty_slot_takes_its_cards_and_only_their_holes_close(client: TestClient) -> None:
    setup_admin(client)
    slots = {
        "Media server": _connection(client, "jellyfin", "Jellyfin"),
        "Requests": _connection(client, "seerr", "Seerr"),
        "Series": _connection(client, "sonarr", "Sonarr"),
        "Films": _connection(client, "radarr", "Radarr"),
        "Downloads": None,
    }
    view = client.post("/api/v1/templates/media", json={"slots": slots}, headers=CSRF).json()
    placed = _spots(view)
    assert "Download speed" not in placed and "Downloading" not in placed
    assert len(placed) == 10
    # Where nothing was taken away, nothing moved.
    for title in ("Now playing", "Recently added", "Library", "Requests", "Series calendar", "Film calendar", "Series queue", "Film queue"):
        at = next(card["at"] for card in templates.get("media")["pages"][0]["cards"] if card["title"] == title)
        assert placed[title] == tuple(at), title
    spots = [{"x": x, "y": y, "w": w, "h": h} for x, y, w, h in placed.values()]
    assert not any(_overlap(a, b) for n, a in enumerate(spots) for b in spots[n + 1:])


def test_a_card_under_a_left_out_one_comes_up_into_its_place(client: TestClient) -> None:
    setup_admin(client)
    slots = {"Containers": _connection(client, "docker", "Docker"), "Uptime": _connection(client, "uptimekuma", "Kuma"),
             "DNS filter": _connection(client, "pihole", "Pi-hole"), "Speed test": None}
    placed = _spots(client.post("/api/v1/templates/homelab", json={"slots": slots}, headers=CSRF).json())
    # The line speed stood at 18, 2 above the bookmarks; without it they come up.
    assert placed["Bookmarks"] == (18, 2, 6, 2)
    assert placed["Notes"] == (12, 6, 12, 3), "blocked above by the DNS card, it stays"


def test_the_board_speaks_the_language_of_whoever_made_it(client: TestClient) -> None:
    setup_admin(client)
    made = client.post("/api/v1/templates/wall", json={
        "slots": {"Calendar": None, "Media server": None},
        "texts": {"Wall display": "Wandanzeige", "Clock": "Uhr", "Overview": "Übersicht", "Weather": "Wetter"},
    }, headers=CSRF).json()
    assert made["name"] == "Wandanzeige"
    assert made["pages"][0]["name"] == "Übersicht"
    assert {w["title"] for w in made["pages"][0]["widgets"]} == {"Uhr", "Wetter", "Problems"}
    assert made["settings"] == {"columns": 24, "width": "full", "fit_height": True}


def test_a_slot_takes_only_the_services_it_names(client: TestClient) -> None:
    setup_admin(client)
    sonarr = _connection(client, "sonarr", "Sonarr")
    # Sonarr has a calendar and a queue as Radarr does, so only the slot says no.
    wrong = client.post("/api/v1/templates/media", json={"slots": {"Films": sonarr}}, headers=CSRF)
    assert wrong.status_code == 400 and wrong.json()["detail"]["code"] == "bad_template"
    assert "Radarr" in wrong.json()["detail"]["message"]
    stray = client.post("/api/v1/templates/media", json={"slots": {"Nonsense": None}}, headers=CSRF)
    assert stray.status_code == 400
    assert client.post("/api/v1/templates/nothing", json={}, headers=CSRF).status_code == 400
    assert len(client.get("/api/v1/boards").json()) == 0 or all(b["name"] != "Media" for b in client.get("/api/v1/boards").json())


def test_a_reserved_connection_is_neither_offered_nor_taken_for_a_member(client: TestClient) -> None:
    setup_admin(client)
    locked = _connection(client, "radarr", "Radarr 4K", admin_only=True)
    open_one = _connection(client, "radarr", "Radarr")
    create_user(client, "kim")
    kim = TestClient(client.app)
    login(kim, "kim", "another-long-password")
    offered = kim.get("/api/v1/templates/media").json()["choices"]["Films"]
    assert [entry["id"] for entry in offered] == [open_one]
    refused = kim.post("/api/v1/templates/media", json={"slots": {"Films": locked}}, headers=CSRF)
    assert refused.status_code == 400, refused.text
    allowed = kim.post("/api/v1/templates/media", json={"slots": {"Films": open_one}}, headers=CSRF)
    assert allowed.status_code == 201, allowed.text
    assert allowed.json()["owner_id"] != 1


def test_a_guest_makes_no_boards(client: TestClient) -> None:
    setup_admin(client)
    create_user(client, "visitor", role="guest")
    guest = TestClient(client.app)
    login(guest, "visitor", "another-long-password")
    assert guest.get("/api/v1/templates").status_code == 200
    assert guest.post("/api/v1/templates/homelab", json={}, headers=CSRF).status_code == 403
