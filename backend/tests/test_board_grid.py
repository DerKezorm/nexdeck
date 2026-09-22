"""A board's own grid: 12, 24 or 36 columns, the width it is drawn at, and
rows that fill the window.

Adapters declare sizes in twelfths and were not touched. What is checked here
is every place a size meets a board: the placement of a new card, the sizes
the browser is handed, an import, a save, and changing the columns of a board
that already has cards on it.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.models import Page
from app.services import grid
from app.services.boards import COLUMNS, Placer
from tests.conftest import CSRF, setup_admin


def _item(i: str, x: int, y: int, w: int, h: int = 2) -> dict:
    return {"i": i, "x": x, "y": y, "w": w, "h": h}


def _overlap(one: dict, other: dict) -> bool:
    return (one["x"] < other["x"] + other["w"] and other["x"] < one["x"] + one["w"]
            and one["y"] < other["y"] + other["h"] and other["y"] < one["y"] + one["h"])


def _no_overlaps(items: list[dict]) -> bool:
    return not any(_overlap(a, b) for index, a in enumerate(items) for b in items[index + 1:])


# -- the arithmetic -----------------------------------------------------------


def test_growing_is_exact() -> None:
    items = [_item("1", 0, 0, 3), _item("2", 3, 0, 5), _item("3", 8, 0, 4), _item("4", 1, 2, 7)]
    scaled = grid.rescale(items, 12, 36)
    assert [(one["x"], one["w"]) for one in scaled] == [(0, 9), (9, 15), (24, 12), (3, 21)]
    assert [one["y"] for one in scaled] == [0, 0, 0, 2]


def test_shrinking_keeps_neighbours_neighbours() -> None:
    """Half-columns that rounded apart used to open a gap or stack two cards.

    Five cards of one column each on 24 columns: 1+1+1+1+1 at x 0..4. Rounded
    one by one, x 1 and x 3 go to 0 and 2 (half to even) or 1 and 2 (half up),
    and two cards meet in one cell. Converted by their edges, and then pushed
    apart where the grid is simply too coarse, none sits on another.
    """
    items = [_item(str(n), n, 0, 1) for n in range(5)] + [_item("wide", 5, 0, 19)]
    scaled = grid.rescale(items, 24, 12)
    assert _no_overlaps(scaled), scaled
    assert all(0 <= one["x"] and one["x"] + one["w"] <= 12 for one in scaled)
    wide = next(one for one in scaled if one["i"] == "wide")
    assert (wide["x"], wide["w"]) == (3, 9), "a card's edges should land where the old ones were, halved"


def test_shrinking_respects_the_floor_of_each_card() -> None:
    items = [_item("list", 0, 0, 6), _item("tile", 6, 0, 2)]
    scaled = grid.rescale(items, 24, 12, {"list": 4, "tile": 1})
    by_id = {one["i"]: one for one in scaled}
    assert by_id["list"]["w"] == 4, "a list three columns wide cannot be drawn in three; its floor is four"
    assert _no_overlaps(scaled)


def test_a_round_trip_through_a_coarser_grid_does_not_scatter_the_board() -> None:
    items = [_item("a", 0, 0, 8), _item("b", 8, 0, 8), _item("c", 16, 0, 8), _item("d", 0, 2, 12), _item("e", 12, 2, 12)]
    there = grid.rescale(items, 24, 12)
    back = grid.rescale(there, 12, 24)
    assert back == [dict(item) for item in items]


def test_the_settings_keep_their_columns_whatever_was_sent() -> None:
    assert grid.clean({"compact": True}, 24) == {"compact": True, "columns": 24}
    assert grid.clean({"columns": 36, "compact": False}, 24) == {"compact": False, "columns": 24}
    assert grid.clean({"columns": 24}, 12) == {}, "twelve is what a board without the key has"
    assert grid.clean({"width": "huge", "fit_height": "yes"}, 12) == {}
    assert grid.clean({"width": "full", "fit_height": True}, 12) == {"width": "full", "fit_height": True}


def test_a_new_card_is_placed_in_the_boards_columns() -> None:
    page = Page(board_id=1, name="p", slug="p", position=0, layouts={key: [] for key in COLUMNS})
    placer = Placer(page, 24)
    placer.add(1, (3, 2), (2, 1))
    placer.add(2, (6, 2), (3, 1))
    placer.finish()
    wide = page.layouts["lg"]
    assert [(one["x"], one["w"], one["minW"]) for one in wide] == [(0, 6, 4), (6, 12, 6)]
    assert page.layouts["md"][0]["w"] == 2 and page.layouts["sm"][0]["w"] == 2, "the dead layouts stay in their old units"


# -- through the API ----------------------------------------------------------


def _board(client: TestClient, name: str = "Grid") -> dict:
    response = client.post("/api/v1/boards", json={"name": name}, headers=CSRF)
    assert response.status_code == 201, response.text
    return response.json()


def _card(client: TestClient, page_id: int, kind: str = "core.clock") -> dict:
    response = client.post(f"/api/v1/pages/{page_id}/widgets", json={"kind": kind}, headers=CSRF)
    assert response.status_code == 201, response.text
    return response.json()


def test_a_new_board_has_24_columns_and_its_cards_come_in_them(client: TestClient) -> None:
    setup_admin(client)
    board = _board(client)
    assert board["settings"]["columns"] == 24
    created = _card(client, board["pages"][0]["id"])
    assert created["widget"]["default_size"][0] % 2 == 0, "sizes come in the board's columns, twice the twelfths"
    view = client.get(f"/api/v1/boards/{board['slug']}").json()
    card = view["pages"][0]["widgets"][0]
    spot = view["pages"][0]["layouts"]["lg"][0]
    assert spot["w"] == card["default_size"][0]
    assert card["min_size"][0] % 2 == 0 and spot["minW"] == card["min_size"][0]


def test_changing_the_columns_takes_every_page_along(client: TestClient) -> None:
    setup_admin(client)
    board = _board(client)
    page_id = board["pages"][0]["id"]
    for _ in range(3):
        _card(client, page_id)
    second = client.post(f"/api/v1/boards/{board['slug']}/pages", json={"name": "Two"}, headers=CSRF).json()
    two_id = next(p["id"] for p in second["pages"] if p["name"] == "Two")
    _card(client, two_id)
    before = client.get(f"/api/v1/boards/{board['slug']}").json()
    versions = {p["id"]: p["layout_version"] for p in before["pages"]}

    answer = client.put(f"/api/v1/boards/{board['slug']}/grid", json={"columns": 36}, headers=CSRF)
    assert answer.status_code == 200, answer.text
    after = answer.json()
    assert after["settings"]["columns"] == 36
    for old, new in zip(before["pages"], after["pages"], strict=True):
        assert [(i["x"] * 3 // 2, i["w"] * 3 // 2) for i in old["layouts"]["lg"]] == [(i["x"], i["w"]) for i in new["layouts"]["lg"]]
        assert new["layout_version"] == versions[new["id"]] + 1, "a browser on the old columns must be told to reload"
        assert all(w["default_size"][0] % 3 == 0 for w in new["widgets"])

    back = client.put(f"/api/v1/boards/{board['slug']}/grid", json={"columns": 12}, headers=CSRF).json()
    assert "columns" not in back["settings"]
    assert all(i["x"] + i["w"] <= 12 for p in back["pages"] for i in p["layouts"]["lg"])


def test_saving_the_other_settings_leaves_the_columns_alone(client: TestClient) -> None:
    """The form sends what it has. A form from before the change sent no columns."""
    setup_admin(client)
    board = _board(client)
    for sent in ({"compact": True}, {"columns": 12, "compact": False}, {"width": "wide", "fit_height": True}):
        answer = client.patch(f"/api/v1/boards/{board['slug']}", json={"settings": sent}, headers=CSRF)
        assert answer.status_code == 200, answer.text
        assert answer.json()["settings"]["columns"] == 24, sent


def test_a_save_wider_than_the_board_is_refused(client: TestClient) -> None:
    setup_admin(client)
    board = _board(client)
    page_id = board["pages"][0]["id"]
    card = _card(client, page_id)["widget"]
    client.put(f"/api/v1/boards/{board['slug']}/grid", json={"columns": 12}, headers=CSRF)
    too_wide = client.put(f"/api/v1/pages/{page_id}/layouts", json={"lg": [{"i": str(card["id"]), "x": 8, "y": 0, "w": 6, "h": 2}]}, headers=CSRF)
    assert too_wide.status_code == 409, too_wide.text
    assert too_wide.json()["detail"]["code"] == "layout_too_wide"
    fits = client.put(f"/api/v1/pages/{page_id}/layouts", json={"lg": [{"i": str(card["id"]), "x": 6, "y": 0, "w": 6, "h": 2}]}, headers=CSRF)
    assert fits.status_code == 200, fits.text


def test_an_import_brings_its_columns_and_stays_inside_them(client: TestClient) -> None:
    setup_admin(client)
    text = """
nexdeck: 1
board:
  name: Wide
  settings: {columns: 36, width: full}
pages:
- name: One
  widgets:
  - kind: core.clock
    layout: {lg: {x: 30, y: 0, w: 9, h: 2}}
  - kind: core.clock
"""
    answer = client.post("/api/v1/boards/import", json={"yaml_text": text}, headers=CSRF)
    assert answer.status_code in (200, 201), answer.text
    view = client.get(f"/api/v1/boards/{answer.json()['slug']}").json()
    assert view["settings"] == {"columns": 36, "width": "full"}
    spots = view["pages"][0]["layouts"]["lg"]
    assert spots[0]["x"] + spots[0]["w"] <= 36 and spots[0]["w"] == 9
    # The clock is three twelfths wide, nine of 36 columns.
    assert spots[1]["w"] == 9, "a card without a place is placed in the file's columns"

    old = client.post("/api/v1/boards/import", json={"yaml_text": text.replace("{columns: 36, width: full}", "{columns: 7}")}, headers=CSRF)
    old_view = client.get(f"/api/v1/boards/{old.json()['slug']}").json()
    assert "columns" not in old_view["settings"], "columns nexdeck does not draw are dropped, the board has twelve"
    assert all(i["x"] + i["w"] <= 12 for i in old_view["pages"][0]["layouts"]["lg"])
