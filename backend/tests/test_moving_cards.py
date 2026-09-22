"""Cards carried to another page, of the same board or of another one.

What matters: the cards arrive together and as they stood, in the columns of
the board they land on; nobody moves a card off a board they may only look
at, or onto one; and a card on a connection reserved for administrators is
not carried by a member to a board of their own.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from .conftest import CSRF, create_user, login, setup_admin


def _board(client: TestClient, name: str) -> dict:
    answer = client.post("/api/v1/boards", json={"name": name}, headers=CSRF)
    assert answer.status_code == 201, answer.text
    return answer.json()


def _card(client: TestClient, page_id: int, **extra) -> int:
    answer = client.post(f"/api/v1/pages/{page_id}/widgets", json={"kind": "core.clock", **extra}, headers=CSRF)
    assert answer.status_code == 201, answer.text
    return int(answer.json()["widget"]["id"])


def _arrange(client: TestClient, page_id: int, spots: dict[int, tuple[int, int, int, int]]) -> None:
    answer = client.put(f"/api/v1/pages/{page_id}/layouts", json={"lg": [
        {"i": str(i), "x": x, "y": y, "w": w, "h": h} for i, (x, y, w, h) in spots.items()
    ]}, headers=CSRF)
    assert answer.status_code == 200, answer.text


def _page(client: TestClient, slug: str, page_id: int) -> dict:
    view = client.get(f"/api/v1/boards/{slug}").json()
    return next(page for page in view["pages"] if page["id"] == page_id)


def _spots(page: dict) -> dict[int, tuple[int, int, int, int]]:
    return {int(item["i"]): (item["x"], item["y"], item["w"], item["h"]) for item in page["layouts"]["lg"]}


def test_a_group_arrives_as_it_stood_below_what_is_there(client: TestClient) -> None:
    setup_admin(client)
    board = _board(client, "Home")
    here = board["pages"][0]["id"]
    a, b, c = (_card(client, here) for _ in range(3))
    _arrange(client, here, {a: (4, 2, 6, 2), b: (10, 2, 6, 3), c: (0, 0, 6, 2)})
    there = client.post(f"/api/v1/boards/{board['slug']}/pages", json={"name": "There"}, headers=CSRF).json()
    there_id = next(page["id"] for page in there["pages"] if page["name"] == "There")
    d = _card(client, there_id)
    _arrange(client, there_id, {d: (0, 0, 6, 4)})

    answer = client.post("/api/v1/widgets/move", json={"ids": [a, b], "page_id": there_id}, headers=CSRF)
    assert answer.status_code == 200, answer.text
    assert answer.json()["moved"] == 2

    landed = _spots(_page(client, board["slug"], there_id))
    # Below the card that was there (it ends at row 4), side by side as before.
    assert landed[a] == (4, 4, 6, 2) and landed[b] == (10, 4, 6, 3)
    assert landed[d] == (0, 0, 6, 4)
    left = _spots(_page(client, board["slug"], here))
    assert set(left) == {c}


def test_a_card_carried_to_a_board_of_other_columns_keeps_its_share_of_the_width(client: TestClient) -> None:
    setup_admin(client)
    wide = _board(client, "Wide")
    narrow = _board(client, "Narrow")
    client.put(f"/api/v1/boards/{narrow['slug']}/grid", json={"columns": 12}, headers=CSRF)
    card = _card(client, wide["pages"][0]["id"])
    _arrange(client, wide["pages"][0]["id"], {card: (12, 0, 12, 2)})

    answer = client.post("/api/v1/widgets/move", json={"ids": [card], "page_id": narrow["pages"][0]["id"]}, headers=CSRF)
    assert answer.status_code == 200, answer.text
    view = client.get(f"/api/v1/boards/{narrow['slug']}").json()
    assert _spots(view["pages"][0])[card] == (6, 0, 6, 2), "half of 24 columns is half of 12"
    assert view["pages"][0]["widgets"][0]["id"] == card


def test_cards_of_two_pages_do_not_land_on_one_another(client: TestClient) -> None:
    setup_admin(client)
    board = _board(client, "Home")
    one = board["pages"][0]["id"]
    two = client.post(f"/api/v1/boards/{board['slug']}/pages", json={"name": "Two"}, headers=CSRF).json()
    two_id = next(page["id"] for page in two["pages"] if page["name"] == "Two")
    three = client.post(f"/api/v1/boards/{board['slug']}/pages", json={"name": "Three"}, headers=CSRF).json()
    three_id = next(page["id"] for page in three["pages"] if page["name"] == "Three")
    a, b = _card(client, one), _card(client, two_id)
    _arrange(client, one, {a: (0, 0, 8, 2)})
    _arrange(client, two_id, {b: (0, 0, 8, 2)})

    client.post("/api/v1/widgets/move", json={"ids": [a, b], "page_id": three_id}, headers=CSRF)
    landed = _spots(_page(client, board["slug"], three_id))
    assert landed[a][1] != landed[b][1], "both stood at the top left of their page and may not share it now"


def test_neither_board_may_be_one_the_member_only_looks_at(client: TestClient) -> None:
    setup_admin(client)
    admins = _board(client, "Admin's")
    card = _card(client, admins["pages"][0]["id"])
    client.put(f"/api/v1/boards/{admins['slug']}/shares", json={"shares": [{"user_id": None, "role": "user", "level": "view"}]}, headers=CSRF)
    create_user(client, "kim")
    kim = TestClient(client.app)
    login(kim, "kim", "another-long-password")
    kims = _board(kim, "Kim's")

    taken = kim.post("/api/v1/widgets/move", json={"ids": [card], "page_id": kims["pages"][0]["id"]}, headers=CSRF)
    assert taken.status_code == 403, taken.text
    own = _card(kim, kims["pages"][0]["id"])
    given = kim.post("/api/v1/widgets/move", json={"ids": [own], "page_id": admins["pages"][0]["id"]}, headers=CSRF)
    assert given.status_code == 403, given.text
    assert len(client.get(f"/api/v1/boards/{admins['slug']}").json()["pages"][0]["widgets"]) == 1


def test_a_card_on_a_locked_connection_stays_on_the_administrators_boards(client: TestClient) -> None:
    """Carried to a member's own board, it would be shown to whoever that board is shared with."""
    setup_admin(client)
    locked = client.post("/api/v1/integrations", json={"kind": "docker", "name": "Engine", "config": {}, "demo": True, "admin_only": True}, headers=CSRF).json()
    admins = _board(client, "Admin's")
    card = client.post(f"/api/v1/pages/{admins['pages'][0]['id']}/widgets", json={"kind": "docker.containers", "integration_id": locked["id"]}, headers=CSRF).json()["widget"]["id"]
    client.put(f"/api/v1/boards/{admins['slug']}/shares", json={"shares": [{"user_id": None, "role": "user", "level": "edit"}]}, headers=CSRF)
    create_user(client, "kim")
    kim = TestClient(client.app)
    login(kim, "kim", "another-long-password")
    kims = _board(kim, "Kim's")

    carried = kim.post("/api/v1/widgets/move", json={"ids": [card], "page_id": kims["pages"][0]["id"]}, headers=CSRF)
    assert carried.status_code == 403, carried.text
    assert carried.json()["detail"]["code"] == "integration_locked"
    # Within the administrator's own board the member may still arrange it.
    second = kim.post(f"/api/v1/boards/{admins['slug']}/pages", json={"name": "More"}, headers=CSRF)
    assert second.status_code == 201, second.text
    more = next(page["id"] for page in second.json()["pages"] if page["name"] == "More")
    assert kim.post("/api/v1/widgets/move", json={"ids": [card], "page_id": more}, headers=CSRF).status_code == 200
    # And an administrator may put it anywhere.
    assert client.post("/api/v1/widgets/move", json={"ids": [card], "page_id": kims["pages"][0]["id"]}, headers=CSRF).status_code == 200


def test_the_versions_of_both_pages_count_up(client: TestClient) -> None:
    """A browser still arranging either page must reload before it saves."""
    setup_admin(client)
    board = _board(client, "Home")
    here = board["pages"][0]["id"]
    card = _card(client, here)
    there = client.post(f"/api/v1/boards/{board['slug']}/pages", json={"name": "There"}, headers=CSRF).json()
    there_id = next(page["id"] for page in there["pages"] if page["name"] == "There")
    before = {page["id"]: page["layout_version"] for page in client.get(f"/api/v1/boards/{board['slug']}").json()["pages"]}
    client.post("/api/v1/widgets/move", json={"ids": [card], "page_id": there_id}, headers=CSRF)
    after = {page["id"]: page["layout_version"] for page in client.get(f"/api/v1/boards/{board['slug']}").json()["pages"]}
    assert after[here] == before[here] + 1 and after[there_id] == before[there_id] + 1
