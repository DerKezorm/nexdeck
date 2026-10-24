"""The pages of a board put in a new order, in one call (issue #50)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from .conftest import CSRF, create_user, login, setup_admin
from .test_groups import _board


def _pages(client: TestClient, slug: str) -> list[str]:
    return [page["name"] for page in client.get(f"/api/v1/boards/{slug}").json()["pages"]]


def _three(client: TestClient) -> tuple[dict, dict[str, int]]:
    board = _board(client, "Home")
    for name in ("Media", "Network"):
        client.post(f"/api/v1/boards/{board['slug']}/pages", json={"name": name}, headers=CSRF)
    pages = client.get(f"/api/v1/boards/{board['slug']}").json()["pages"]
    return board, {page["name"]: page["id"] for page in pages}


def test_the_pages_take_the_order_they_are_put_in(client: TestClient) -> None:
    setup_admin(client)
    board, ids = _three(client)
    first = next(name for name in ids if name not in ("Media", "Network"))
    answer = client.put(f"/api/v1/boards/{board['slug']}/pages/order", json={"ids": [ids["Network"], ids[first], ids["Media"]]}, headers=CSRF)
    assert answer.status_code == 200, answer.text
    assert [page["name"] for page in answer.json()["pages"]] == ["Network", first, "Media"]
    # Kept, not only answered.
    assert _pages(client, board["slug"]) == ["Network", first, "Media"]


def test_every_page_once_and_no_other(client: TestClient) -> None:
    setup_admin(client)
    board, ids = _three(client)
    _other, foreign = _three(client)
    every = list(ids.values())
    for wrong in (every[:2], [*every, every[0]], [*every[:2], next(iter(foreign.values()))], []):
        answer = client.put(f"/api/v1/boards/{board['slug']}/pages/order", json={"ids": wrong}, headers=CSRF)
        assert answer.status_code == 400, wrong
        assert answer.json()["detail"]["code"] == "bad_page_order"
    assert _pages(client, board["slug"]) == list(ids)


def test_only_who_may_edit_the_board_puts_its_pages_in_order(client: TestClient) -> None:
    setup_admin(client)
    board, ids = _three(client)
    viewer = create_user(client, "viewer")
    # Shared to look at: the board is seen, and its order stays as it is.
    client.put(f"/api/v1/boards/{board['slug']}/shares", json={"shares": [{"user_id": viewer["id"], "level": "view"}]}, headers=CSRF)
    login(client, "viewer", "another-long-password")
    assert _pages(client, board["slug"]) == list(ids)
    answer = client.put(f"/api/v1/boards/{board['slug']}/pages/order", json={"ids": list(reversed(ids.values()))}, headers=CSRF)
    assert answer.status_code == 403, answer.text
    assert _pages(client, board["slug"]) == list(ids)
