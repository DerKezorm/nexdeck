"""Cards copied beside themselves or onto a page of another board.

What matters: the copy is a new card that looks and reads like the old one,
in the columns of the board it lands on, without the old one's history,
chronicle or check; nobody copies onto or off a board they may only look
at; a card on a connection reserved for administrators is copied by nobody
who could not have made it; and a card that holds others never ends up
sharing them with the original.
"""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

from app.db import db_session
from app.services import history

from .conftest import CSRF, create_user, login, setup_admin
from .test_moving_cards import _arrange, _board, _page, _spots


def _card(client: TestClient, page_id: int, kind: str = "core.clock", **extra: object) -> dict:
    answer = client.post(f"/api/v1/pages/{page_id}/widgets", json={"kind": kind, **extra}, headers=CSRF)
    assert answer.status_code == 201, answer.text
    return answer.json()["widget"]


def _copy(client: TestClient, ids: list[int], page_id: int):  # noqa: ANN202
    return client.post("/api/v1/widgets/copy", json={"ids": ids, "page_id": page_id}, headers=CSRF)


def _widget(client: TestClient, slug: str, page_id: int, widget_id: int) -> dict:
    return next(one for one in _page(client, slug, page_id)["widgets"] if one["id"] == widget_id)


def _member(client: TestClient, name: str = "kim") -> TestClient:
    create_user(client, name)
    member = TestClient(client.app)
    login(member, name, "another-long-password")
    return member


def test_a_copy_on_another_board_reads_like_the_card_and_keeps_its_share_of_the_width(client: TestClient) -> None:
    setup_admin(client)
    wide = _board(client, "Wide")
    narrow = _board(client, "Narrow")
    client.put(f"/api/v1/boards/{narrow['slug']}/grid", json={"columns": 12}, headers=CSRF)
    look = {"card_colour": "violet", "card_effect": "tint", "level_warn": 70, "level_bad": 90, "view": "gauge"}
    card = _card(client, wide["pages"][0]["id"], "core.host", title="NAS", icon="synology", link="https://nas.example.com",
                 options=look, refresh_seconds=45)
    _arrange(client, wide["pages"][0]["id"], {card["id"]: (12, 0, 12, 2)})
    there = narrow["pages"][0]["id"]
    _arrange(client, there, {_card(client, there)["id"]: (0, 0, 6, 3)})

    answer = _copy(client, [card["id"]], there)
    assert answer.status_code == 200, answer.text
    assert answer.json()["copied"] == 1 and answer.json()["notes"] == []
    [new] = answer.json()["ids"]
    assert new != card["id"]
    copied = _widget(client, narrow["slug"], there, new)
    assert (copied["kind"], copied["title"], copied["icon"], copied["link"], copied["refresh_seconds"]) == ("core.host", "NAS", "synology", "https://nas.example.com", 45)
    assert {key: copied["options"].get(key) for key in look} == look
    # Half of 24 columns is half of 12, below what was on the page already.
    assert _spots(_page(client, narrow["slug"], there))[new] == (6, 3, 6, 2)
    # The card itself stays where it was.
    assert _spots(_page(client, wide["slug"], wide["pages"][0]["id"])) == {card["id"]: (12, 0, 12, 2)}


def test_a_card_duplicated_here_lands_below_and_several_keep_their_arrangement(client: TestClient) -> None:
    setup_admin(client)
    board = _board(client, "Home")
    here = board["pages"][0]["id"]
    a, b = _card(client, here)["id"], _card(client, here)["id"]
    _arrange(client, here, {a: (4, 0, 6, 2), b: (10, 0, 6, 3)})

    answer = _copy(client, [a, b], here)
    assert answer.status_code == 200, answer.text
    one, two = answer.json()["ids"]
    spots = _spots(_page(client, board["slug"], here))
    assert spots[a] == (4, 0, 6, 2) and spots[b] == (10, 0, 6, 3)
    assert spots[one] == (4, 3, 6, 2) and spots[two] == (10, 3, 6, 3), "side by side, below the last row"


def test_the_copy_starts_without_history_and_with_a_check_of_its_own(client: TestClient) -> None:
    setup_admin(client)
    board = _board(client, "Home")
    here = board["pages"][0]["id"]
    tile = _card(client, here, "core.app", title="Wiki", link="https://wiki.example.com", options={"check_target": "192.0.2.10:443"})
    changed = client.put(f"/api/v1/widgets/{tile['id']}/health", json={
        "kind": "tcp", "target": "192.0.2.10:443", "interval_seconds": 300, "timeout_seconds": 9, "expect_status": 0, "insecure": True, "enabled": True,
    }, headers=CSRF)
    assert changed.status_code == 200, changed.text
    with db_session() as db:
        history.record(db, tile["id"], {"latency": 12.0}, ts=int(time.time()) - 60)

    [new] = _copy(client, [tile["id"]], here).json()["ids"]
    assert client.get(f"/api/v1/widgets/{tile['id']}/history?metric=latency").json()["latency"], "the original keeps its history"
    assert client.get(f"/api/v1/widgets/{new}/history?metric=latency").json()["latency"] == []
    check = client.get(f"/api/v1/widgets/{new}/health").json()
    assert (check["kind"], check["target"], check["insecure"]) == ("http", "https://wiki.example.com", False), "the check a new tile gets"
    assert check["interval_seconds"] != 300
    assert "check_target" not in _widget(client, board["slug"], here, new)["options"]


def test_the_chronicle_of_the_copy_says_where_it_came_from_and_takes_nothing_of_the_old_card(client: TestClient) -> None:
    setup_admin(client)
    home = _board(client, "Home")
    lab = _board(client, "Lab")
    card = _card(client, home["pages"][0]["id"], title="Clock")
    [new] = _copy(client, [card["id"]], lab["pages"][0]["id"]).json()["ids"]

    lines = client.get("/api/v1/chronicle?group=nexdeck").json()["events"]
    copied = [line for line in lines if line["kind"] == "card_copied"]
    assert len(copied) == 1
    assert copied[0]["name"] == "Clock" and copied[0]["before"] == f"Home › {home['pages'][0]['name']}" and copied[0]["after"] == "Lab"
    # The copy's own lines are that one; "added" belongs to the old card.
    own = [line["kind"] for line in lines if line.get("target", {}).get("widget") == new]
    assert own == ["card_copied"]


def test_neither_board_may_be_one_the_member_only_looks_at(client: TestClient) -> None:
    setup_admin(client)
    admins = _board(client, "Admin's")
    card = _card(client, admins["pages"][0]["id"])
    client.put(f"/api/v1/boards/{admins['slug']}/shares", json={"shares": [{"user_id": None, "role": "user", "level": "view"}]}, headers=CSRF)
    kim = _member(client)
    kims = _board(kim, "Kim's")

    taken = _copy(kim, [card["id"]], kims["pages"][0]["id"])
    assert taken.status_code == 403, taken.text
    own = _card(kim, kims["pages"][0]["id"])
    given = _copy(kim, [own["id"]], admins["pages"][0]["id"])
    assert given.status_code == 403, given.text
    here = _copy(kim, [card["id"]], admins["pages"][0]["id"])
    assert here.status_code == 403, "looking is not enough to duplicate either"
    assert len(_page(client, admins["slug"], admins["pages"][0]["id"])["widgets"]) == 1
    assert len(_page(kim, kims["slug"], kims["pages"][0]["id"])["widgets"]) == 1


def test_a_card_on_a_locked_connection_is_copied_by_nobody_who_could_not_have_made_it(client: TestClient) -> None:
    setup_admin(client)
    locked = client.post("/api/v1/integrations", json={"kind": "docker", "name": "Engine", "config": {}, "demo": True, "admin_only": True}, headers=CSRF).json()
    admins = _board(client, "Admin's")
    page = admins["pages"][0]["id"]
    card = _card(client, page, "docker.containers", integration_id=locked["id"])
    client.put(f"/api/v1/boards/{admins['slug']}/shares", json={"shares": [{"user_id": None, "role": "user", "level": "edit"}]}, headers=CSRF)
    kim = _member(client)
    kims = _board(kim, "Kim's")

    for where in (kims["pages"][0]["id"], page):
        refused = _copy(kim, [card["id"]], where)
        assert refused.status_code == 403, refused.text
        assert refused.json()["detail"]["code"] == "integration_locked"
    assert len(_page(client, admins["slug"], page)["widgets"]) == 1
    # The administrator may.
    assert _copy(client, [card["id"]], page).status_code == 200


def test_key_figures_duplicated_here_start_without_tiles_and_the_original_keeps_them(client: TestClient) -> None:
    setup_admin(client)
    board = _board(client, "Wall")
    page = board["pages"][0]["id"]
    machine = _card(client, page, "core.host", title="NAS")
    figures = _card(client, page, "core.figures", title="Figures", options={"cards": [machine["id"]]})

    answer = _copy(client, [figures["id"]], page)
    assert answer.status_code == 200, answer.text
    [new] = answer.json()["ids"]
    assert answer.json()["notes"] == [{"code": "started_empty", "name": "Figures", "count": 1}]
    assert _widget(client, board["slug"], page, new)["options"]["cards"] == []
    assert _widget(client, board["slug"], page, figures["id"])["options"]["cards"] == [machine["id"]]


def test_a_group_copied_elsewhere_takes_copies_of_its_cards_and_says_what_stayed_behind(client: TestClient) -> None:
    setup_admin(client)
    locked = client.post("/api/v1/integrations", json={"kind": "docker", "name": "Engine", "config": {}, "demo": True, "admin_only": True}, headers=CSRF).json()
    admins = _board(client, "Admin's")
    page = admins["pages"][0]["id"]
    clock = _card(client, page, title="Clock")
    engine = _card(client, page, "docker.containers", integration_id=locked["id"], title="Containers")
    group = _card(client, page, "core.group", title="Box", options={"cards": [clock["id"], engine["id"]]})
    client.put(f"/api/v1/boards/{admins['slug']}/shares", json={"shares": [{"user_id": None, "role": "user", "level": "edit"}]}, headers=CSRF)
    kim = _member(client)
    kims = _board(kim, "Kim's")
    there = kims["pages"][0]["id"]

    answer = _copy(kim, [group["id"]], there)
    assert answer.status_code == 200, answer.text
    assert answer.json()["notes"] == [{"code": "held_left", "name": "Box", "count": 1}]
    [new] = answer.json()["ids"]
    landed = _page(kim, kims["slug"], there)
    held = _widget(kim, kims["slug"], there, new)["options"]["cards"]
    assert len(held) == 1 and held[0] not in (clock["id"], engine["id"])
    inside = next(one for one in landed["widgets"] if one["id"] == held[0])
    assert (inside["kind"], inside["title"]) == ("core.clock", "Clock")
    assert {one["kind"] for one in landed["widgets"]} == {"core.group", "core.clock"}, "the locked card is not on Kim's board"
    # The original group still holds both of its own.
    assert _widget(client, admins["slug"], page, group["id"])["options"]["cards"] == [clock["id"], engine["id"]]


def test_a_copy_onto_a_page_that_is_not_there_is_refused(client: TestClient) -> None:
    setup_admin(client)
    board = _board(client, "Home")
    card = _card(client, board["pages"][0]["id"])
    missing = _copy(client, [card["id"]], 999_999)
    assert missing.status_code == 404
