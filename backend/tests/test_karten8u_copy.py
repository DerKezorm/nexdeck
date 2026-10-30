"""H2 of a review of 1.0.2: copying a custom card is checked like placing it (KARTEN-11 AC-3).

A member who may edit a board on which an administrator placed a card nobody released for users cannot copy it onto a
board of his own; a released card he can.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.services.collector import collector

from .conftest import CSRF, setup_admin
from .test_cards_router import add, as_admin, as_user, connection, place


@pytest.fixture
def stand(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, int]:
    """The administrator's board, shared for editing with every user, with the sample card on it."""
    setup_admin(client)
    monkeypatch.setattr(collector, "running", False)
    add(client)
    board = client.post("/api/v1/boards", json={"name": "Wall"}, headers=CSRF).json()
    client.put(f"/api/v1/boards/{board['slug']}/shares", json={"shares": [{"user_id": None, "role": "user", "level": "edit"}]}, headers=CSRF)
    placed = place(client, int(board["pages"][0]["id"]), connection(client))
    assert placed.status_code == 201, placed.text
    return client, int(placed.json()["widget"]["id"])


def copy_to_own_board(client: TestClient, widget: int):  # noqa: ANN201
    as_user(client)
    mine = client.post("/api/v1/boards", json={"name": "Mine"}, headers=CSRF).json()
    return client.post("/api/v1/widgets/copy", json={"ids": [widget], "page_id": int(mine["pages"][0]["id"])}, headers=CSRF)


def test_karten8u_h2_a_member_cannot_copy_a_card_nobody_released(stand: tuple[TestClient, int]) -> None:
    client, widget = stand
    answer = copy_to_own_board(client, widget)
    assert answer.status_code == 400 and answer.json()["detail"]["code"] == "unknown_card", answer.text


def test_karten8u_h2_a_released_card_is_copied(stand: tuple[TestClient, int]) -> None:
    client, widget = stand
    assert client.put("/api/v1/cards/queue-size/users", json={"allowed": True}, headers=CSRF).json()["users_may_place"] is True
    answer = copy_to_own_board(client, widget)
    assert answer.status_code in (200, 201), answer.text


def test_karten8u_h2_an_administrator_copies_it_as_he_places_it(stand: tuple[TestClient, int]) -> None:
    client, widget = stand
    as_user(client)
    as_admin(client)
    mine = client.post("/api/v1/boards", json={"name": "Mine"}, headers=CSRF).json()
    answer = client.post("/api/v1/widgets/copy", json={"ids": [widget], "page_id": int(mine["pages"][0]["id"])}, headers=CSRF)
    assert answer.status_code in (200, 201), answer.text
