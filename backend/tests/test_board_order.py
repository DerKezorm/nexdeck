"""The order the boards appear in, and who may change it.

⚠️ The order is a property of the installation, not of the person looking.
Everyone sees the same menu, so moving a board is editing it and the same
permission decides.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from .conftest import CSRF, create_user, login, setup_admin


def _board(client: TestClient, name: str) -> dict:
    made = client.post("/api/v1/boards", json={"name": name}, headers=CSRF)
    assert made.status_code == 201, made.text
    return made.json()


def _order(client: TestClient) -> list[str]:
    return [board["slug"] for board in client.get("/api/v1/boards").json()]


def test_the_order_can_be_turned_around(client: TestClient) -> None:
    setup_admin(client)
    for name in ("Media", "Network", "Home lab"):
        _board(client, name)
    before = _order(client)

    answer = client.put("/api/v1/boards/order", json={"slugs": list(reversed(before))}, headers=CSRF)
    assert answer.status_code == 200, answer.text
    assert _order(client) == list(reversed(before))
    assert [board["slug"] for board in answer.json()] == list(reversed(before)), "the answer is the new order"


def test_boards_that_all_sit_at_zero_come_out_in_a_defined_order(client: TestClient) -> None:
    """⚠️ Every installation made before this has every board at position 0,
    so the menu fell back to the order they happened to be created in."""
    from sqlalchemy import select, update

    from app.db import db_session
    from app.models import Board

    setup_admin(client)
    for name in ("Media", "Network"):
        _board(client, name)
    with db_session() as db:
        db.execute(update(Board).values(position=0))
        db.commit()

    slugs = _order(client)
    client.put("/api/v1/boards/order", json={"slugs": [slugs[-1], *slugs[:-1]]}, headers=CSRF)
    assert _order(client) == [slugs[-1], *slugs[:-1]]
    with db_session() as db:
        positions = sorted(board.position for board in db.scalars(select(Board)))
    assert positions == list(range(len(positions))), "renumbered, not left at zero"


def test_a_board_that_was_not_named_keeps_its_place_behind_the_others(client: TestClient) -> None:
    """⚠️ A user who cannot see somebody else's board never sends its name.
    That must not push it to the front."""
    setup_admin(client)
    for name in ("Media", "Network", "Home lab"):
        _board(client, name)
    slugs = _order(client)

    client.put("/api/v1/boards/order", json={"slugs": [slugs[2], slugs[0]]}, headers=CSRF)
    after = _order(client)
    assert after[:2] == [slugs[2], slugs[0]]
    assert after[2] == slugs[1], "the one nobody moved sits behind them"


def test_the_same_board_twice_is_refused(client: TestClient) -> None:
    setup_admin(client)
    board = _board(client, "Media")
    answer = client.put("/api/v1/boards/order", json={"slugs": [board["slug"], board["slug"]]}, headers=CSRF)
    assert answer.status_code == 400
    assert answer.json()["detail"]["code"] == "duplicate_board"


def test_a_board_that_does_not_exist_is_refused(client: TestClient) -> None:
    setup_admin(client)
    _board(client, "Media")
    answer = client.put("/api/v1/boards/order", json={"slugs": ["nope"]}, headers=CSRF)
    assert answer.status_code == 404


def test_somebody_who_may_not_edit_a_board_may_not_move_it(client: TestClient) -> None:
    setup_admin(client)
    mine = _board(client, "Media")
    create_user(client, "kim")
    kim = TestClient(client.app)
    login(kim, "kim", "another-long-password")
    refused = kim.put("/api/v1/boards/order", json={"slugs": [mine["slug"]]}, headers=CSRF)
    assert refused.status_code in (403, 404)


def test_nothing_moves_when_one_name_is_wrong(client: TestClient) -> None:
    """All or nothing: half a reorder is an order nobody chose."""
    setup_admin(client)
    for name in ("Media", "Network"):
        _board(client, name)
    before = _order(client)
    client.put("/api/v1/boards/order", json={"slugs": [before[1], "nope"]}, headers=CSRF)
    assert _order(client) == before


def test_a_board_named_by_its_number_is_refused(client: TestClient) -> None:
    """⚠️ A board is looked up by slug, and a lookup that misses falls back to
    reading the text as an id. Let that through here and the renumbering that
    follows asks for a slug that is not in its own list, which is a 500 where
    a 404 belongs."""
    setup_admin(client)
    board = _board(client, "Media")
    before = _order(client)
    with_number = client.put("/api/v1/boards/order", json={"slugs": [str(board["id"])]}, headers=CSRF)
    assert with_number.status_code == 404, with_number.text
    assert _order(client) == before


def test_tidying_your_own_menu_leaves_other_peoples_boards_where_they_were(client: TestClient) -> None:
    """⚠️ "Anything not named" used to mean every board of the installation.

    A member pressing save on their own two boards renumbered the boards of
    everyone else, and the permission check above only covered the slugs they
    had actually sent.
    """
    setup_admin(client)
    from sqlalchemy import select

    from app.db import db_session
    from app.models import Board

    hidden = [_board(client, name) for name in ("Admin one", "Admin two")]
    create_user(client, "kim")
    kim = TestClient(client.app)
    login(kim, "kim", "another-long-password")
    mine = [_board(kim, name) for name in ("Kim one", "Kim two")]

    def positions() -> dict[str, int]:
        with db_session() as db:
            return {board.slug: board.position for board in db.scalars(select(Board))}

    before = positions()
    moved = kim.put("/api/v1/boards/order", json={"slugs": [mine[1]["slug"], mine[0]["slug"]]}, headers=CSRF)
    assert moved.status_code == 200, moved.text
    after = positions()

    assert after[mine[1]["slug"]] < after[mine[0]["slug"]], "the person's own boards did not move"
    for board in hidden:
        assert after[board["slug"]] == before[board["slug"]], f"{board['slug']} was renumbered by somebody who cannot see it"
