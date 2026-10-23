"""A card dragged between the board, a group and the side bar of its page."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from .conftest import CSRF, create_user, login, setup_admin
from .test_groups import _board, _card


def _place(client: TestClient, page_id: int, **body: Any):  # noqa: ANN202
    return client.post(f"/api/v1/pages/{page_id}/place", json=body, headers=CSRF)


def _page(board: dict, page_id: int) -> dict:
    return next(one for one in board["pages"] if one["id"] == page_id)


def _widget(page: dict, widget_id: int) -> dict:
    return next(one for one in page["widgets"] if one["id"] == widget_id)


def _setup(client: TestClient) -> tuple[dict, int, dict, dict, dict]:
    setup_admin(client)
    board = _board(client, "Home")
    page = board["pages"][0]["id"]
    clock = _card(client, page, "core.clock", title="Clock")
    note = _card(client, page, "core.markdown", title="Notes")
    group = _card(client, page, "core.group", title="Media")
    return board, page, clock, note, group


def test_a_card_goes_into_a_group_with_its_size(client: TestClient) -> None:
    board, page, clock, note, group = _setup(client)
    answer = _place(client, page, widget_id=clock["id"], into="group", group_id=group["id"], held_w=6, held_h=3)
    assert answer.status_code == 200, answer.text
    shown = _page(answer.json(), page)
    assert _widget(shown, group["id"])["options"]["cards"] == [clock["id"]]
    assert _widget(shown, clock["id"])["options"]["held_size"] == {"w": 6, "h": 3}

    # In front of the clock, inside the same group.
    _place(client, page, widget_id=note["id"], into="group", group_id=group["id"], before=clock["id"])
    shown = _page(client.get(f"/api/v1/boards/{board['slug']}").json(), page)
    assert _widget(shown, group["id"])["options"]["cards"] == [note["id"], clock["id"]]


def test_a_card_moves_from_a_group_into_the_side_bar_and_back_onto_the_board(client: TestClient) -> None:
    board, page, clock, _note, group = _setup(client)
    _place(client, page, widget_id=clock["id"], into="group", group_id=group["id"])
    answer = _place(client, page, widget_id=clock["id"], into="side", held_w=12, held_h=2)
    shown = _page(answer.json(), page)
    assert _widget(shown, group["id"])["options"]["cards"] == [], "taken out of the group it stood in"
    assert shown["side"]["cards"] == [clock["id"]]

    answer = _place(client, page, widget_id=clock["id"], into="board", spot={"x": 3, "y": 9, "w": 3, "h": 2})
    shown = _page(answer.json(), page)
    assert shown["side"]["cards"] == []
    assert {"i": str(clock["id"]), "x": 3, "y": 9, "w": 3, "h": 2} in shown["layouts"]["lg"]


def test_a_placed_card_moves_the_page_on(client: TestClient) -> None:
    """⚠️ A browser still arranging from before the drop must be told, as after any other save."""
    board, page, clock, _note, group = _setup(client)
    before = _page(client.get(f"/api/v1/boards/{board['slug']}").json(), page)["layout_version"]
    after = _page(_place(client, page, widget_id=clock["id"], into="group", group_id=group["id"]).json(), page)["layout_version"]
    assert after == before + 1


def test_a_group_does_not_go_into_a_group_or_the_side_bar(client: TestClient) -> None:
    _board_, page, _clock, _note, group = _setup(client)
    other = _card(client, page, "core.group", title="Other")
    for body in ({"into": "group", "group_id": other["id"]}, {"into": "side"}):
        answer = _place(client, page, widget_id=group["id"], **body)
        assert answer.status_code == 400
        assert answer.json()["detail"]["code"] == "bad_place"


def test_only_a_group_of_this_page_takes_a_card(client: TestClient) -> None:
    board, page, clock, _note, _group = _setup(client)
    grown = client.post(f"/api/v1/boards/{board['slug']}/pages", json={"name": "Other"}, headers=CSRF).json()
    other_page = next(one["id"] for one in grown["pages"] if one["name"] == "Other")
    foreign = _card(client, other_page, "core.group", title="Elsewhere")
    tabs = _card(client, page, "core.tabs", title="Tabs")
    for group_id in (foreign["id"], tabs["id"], clock["id"]):
        answer = _place(client, page, widget_id=clock["id"], into="group", group_id=group_id)
        assert answer.status_code == 400, group_id


def test_the_board_edge_holds(client: TestClient) -> None:
    _board_, page, clock, _note, _group = _setup(client)
    # A board made from the menu has 24 columns.
    answer = _place(client, page, widget_id=clock["id"], into="board", spot={"x": 22, "y": 0, "w": 4, "h": 2})
    assert answer.status_code == 400
    assert _place(client, page, widget_id=clock["id"], into="board").status_code == 400, "without a spot"


def test_a_viewer_cannot_rearrange(client: TestClient) -> None:
    board, page, clock, _note, group = _setup(client)
    create_user(client, "viewer")
    client.put(f"/api/v1/boards/{board['slug']}/shares", json={"shares": [{"username": "viewer", "level": "view"}]}, headers=CSRF)
    login(client, "viewer", "another-long-password")
    assert _place(client, page, widget_id=clock["id"], into="group", group_id=group["id"]).status_code in (403, 404)


def test_the_side_bar_stands_left_right_or_nowhere(client: TestClient) -> None:
    board, page, *_ = _setup(client)
    answer = client.patch(f"/api/v1/pages/{page}", json={"side_place": "right", "side_width": "wide"}, headers=CSRF)
    assert answer.status_code == 200, answer.text
    assert _page(answer.json(), page)["side"] == {"place": "right", "width": "wide", "cards": []}
    refused = client.patch(f"/api/v1/pages/{page}", json={"side_place": "top"}, headers=CSRF)
    assert refused.status_code == 400 and refused.json()["detail"]["code"] == "bad_side"


def test_a_held_size_outside_the_twelve_is_refused(client: TestClient) -> None:
    _board_, _page_, clock, *_ = _setup(client)
    answer = client.patch(f"/api/v1/widgets/{clock['id']}", json={"options": {"held_size": {"w": 13, "h": 2}}}, headers=CSRF)
    assert answer.status_code == 400
    assert answer.json()["detail"]["code"] == "bad_held_size"
    fine = client.patch(f"/api/v1/widgets/{clock['id']}", json={"options": {"held_size": {"w": 4, "h": 2}}}, headers=CSRF)
    assert fine.status_code == 200


def test_a_card_moved_to_another_page_leaves_the_side_bar(client: TestClient) -> None:
    board, page, clock, *_ = _setup(client)
    _place(client, page, widget_id=clock["id"], into="side")
    grown = client.post(f"/api/v1/boards/{board['slug']}/pages", json={"name": "Other"}, headers=CSRF).json()
    other_page = next(one["id"] for one in grown["pages"] if one["name"] == "Other")
    moved = client.patch(f"/api/v1/widgets/{clock['id']}", json={"page_id": other_page}, headers=CSRF)
    assert moved.status_code == 200, moved.text
    shown = _page(client.get(f"/api/v1/boards/{board['slug']}").json(), page)
    assert shown["side"]["cards"] == []


def test_the_side_bar_and_held_sizes_survive_export_and_import(client: TestClient) -> None:
    board, page, clock, note, group = _setup(client)
    client.patch(f"/api/v1/pages/{page}", json={"side_place": "left"}, headers=CSRF)
    _place(client, page, widget_id=clock["id"], into="side", held_w=12, held_h=3)
    _place(client, page, widget_id=note["id"], into="group", group_id=group["id"], held_w=8, held_h=2)
    text = client.get(f"/api/v1/boards/{board['slug']}/export").text
    imported = client.post("/api/v1/boards/import", json={"yaml_text": text, "slug": "home-copy"}, headers=CSRF)
    assert imported.status_code in (200, 201), imported.text
    copy = client.get("/api/v1/boards/home-copy").json()["pages"][0]
    widgets = {one["title"]: one for one in copy["widgets"]}
    assert copy["side"] == {"place": "left", "width": "narrow", "cards": [widgets["Clock"]["id"]]}
    assert widgets["Clock"]["id"] != clock["id"], "new numbers, the same card"
    assert widgets["Clock"]["options"]["held_size"] == {"w": 12, "h": 3}
    assert widgets["Media"]["options"]["cards"] == [widgets["Notes"]["id"]]
    assert widgets["Notes"]["options"]["held_size"] == {"w": 8, "h": 2}
