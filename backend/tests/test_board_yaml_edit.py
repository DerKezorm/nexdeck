"""A board edited as YAML (issue #36): what stays keeps its row, its check and its history."""

from __future__ import annotations

import yaml
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import db_session
from app.models import HealthCheck, Widget

from .conftest import CSRF, create_user, login, setup_admin


def _board(client: TestClient, name: str) -> dict:
    answer = client.post("/api/v1/boards", json={"name": name}, headers=CSRF)
    assert answer.status_code == 201, answer.text
    return answer.json()


def _card(client: TestClient, page_id: int, kind: str, **extra: object) -> dict:
    answer = client.post(f"/api/v1/pages/{page_id}/widgets", json={"kind": kind, **extra}, headers=CSRF)
    assert answer.status_code == 201, answer.text
    return answer.json()["widget"]


def _text(client: TestClient, slug: str) -> dict:
    answer = client.get(f"/api/v1/boards/{slug}/export?ids=true")
    assert answer.status_code == 200, answer.text
    return yaml.safe_load(answer.text)


def _save(client: TestClient, slug: str, document: dict):  # noqa: ANN202
    return client.put(f"/api/v1/boards/{slug}/yaml", json={"yaml_text": yaml.safe_dump(document, sort_keys=False)}, headers=CSRF)


def _check_of(widget_id: int) -> int | None:
    with db_session() as db:
        return db.scalar(select(HealthCheck.id).where(HealthCheck.widget_id == widget_id))


def test_editing_keeps_what_stays_and_changes_it_in_place(client: TestClient) -> None:
    setup_admin(client)
    board = _board(client, "Home")
    first = board["pages"][0]["id"]
    grown = client.post(f"/api/v1/boards/{board['slug']}/pages", json={"name": "Second"}, headers=CSRF).json()
    second = next(page["id"] for page in grown["pages"] if page["name"] == "Second")
    app = _card(client, first, "core.app", title="Router", link="http://router.example.com")
    note = _card(client, first, "core.markdown", title="Notes", options={"content": "old"})
    clock = _card(client, first, "core.clock", title="Clock")
    check = _check_of(app["id"])
    assert check is not None, "an app tile is checked on its link"

    document = _text(client, board["slug"])
    assert [page["id"] for page in document["pages"]] == [first, second]
    cards = {card["title"]: card for card in document["pages"][0]["widgets"]}
    assert cards["Router"]["id"] == app["id"]
    cards["Notes"]["title"] = "Shopping"
    cards["Notes"]["options"] = {"content": "milk"}
    # The clock goes, the app tile moves to the second page, and a card without a number is new.
    document["pages"][0]["widgets"] = [cards["Notes"], {"kind": "core.clock", "title": "New clock"}]
    document["pages"][1]["widgets"] = [cards["Router"]]
    document["pages"][1]["name"] = "Network"
    document["board"]["name"] = "House"
    answer = _save(client, board["slug"], document)
    assert answer.status_code == 200, answer.text

    view = client.get(f"/api/v1/boards/{board['slug']}").json()
    assert view["name"] == "House" and view["slug"] == board["slug"]
    assert [(page["id"], page["name"]) for page in view["pages"]] == [(first, board["pages"][0]["name"]), (second, "Network")]
    on_first = {card["title"]: card for card in view["pages"][0]["widgets"]}
    on_second = {card["title"]: card for card in view["pages"][1]["widgets"]}
    assert on_first["Shopping"]["id"] == note["id"] and on_first["Shopping"]["options"]["content"] == "milk"
    assert "Clock" not in on_first and on_first["New clock"]["id"] not in (app["id"], note["id"], clock["id"])
    assert on_second["Router"]["id"] == app["id"], "the moved tile is the same card"
    assert _check_of(app["id"]) == check, "and keeps its check, with the history hanging on it"
    with db_session() as db:
        assert db.get(Widget, clock["id"]) is None, "what the text no longer names is gone"
    for page in view["pages"]:
        placed = {item["i"] for item in page["layouts"]["lg"]}
        assert placed == {str(card["id"]) for card in page["widgets"]}, "every card has a place on its own page"


def test_a_number_from_another_board_only_makes_a_new_card(client: TestClient) -> None:
    setup_admin(client)
    mine = _board(client, "Mine")
    other = _board(client, "Other")
    stranger = _card(client, other["pages"][0]["id"], "core.markdown", title="Theirs", options={"content": "keep"})
    document = _text(client, mine["slug"])
    document["pages"][0]["widgets"] = [{"id": stranger["id"], "kind": "core.markdown", "title": "Taken", "options": {"content": "gone"}}]
    assert _save(client, mine["slug"], document).status_code == 200

    taken = client.get(f"/api/v1/boards/{mine['slug']}").json()["pages"][0]["widgets"]
    assert len(taken) == 1 and taken[0]["id"] != stranger["id"]
    theirs = client.get(f"/api/v1/boards/{other['slug']}").json()["pages"][0]["widgets"]
    assert [(card["id"], card["title"], card["options"]["content"]) for card in theirs] == [(stranger["id"], "Theirs", "keep")]


def test_a_text_that_will_not_do_leaves_the_board_alone(client: TestClient) -> None:
    setup_admin(client)
    board = _board(client, "Home")
    note = _card(client, board["pages"][0]["id"], "core.markdown", title="Notes")
    document = _text(client, board["slug"])
    document["pages"][0]["widgets"].append({"kind": "nothing.like-this"})
    answer = _save(client, board["slug"], document)
    assert answer.status_code == 400 and "nothing.like-this" in answer.text
    bad = client.put(f"/api/v1/boards/{board['slug']}/yaml", json={"yaml_text": "board: [nope"}, headers=CSRF)
    assert bad.status_code == 400
    after = client.get(f"/api/v1/boards/{board['slug']}").json()["pages"][0]["widgets"]
    assert [card["id"] for card in after] == [note["id"]]


def test_a_group_keeps_its_cards_through_an_edit(client: TestClient) -> None:
    setup_admin(client)
    board = _board(client, "Home")
    page = board["pages"][0]["id"]
    note = _card(client, page, "core.markdown", title="Notes")
    clock = _card(client, page, "core.clock", title="Clock")
    tabs = _card(client, page, "core.tabs", title="Both", options={"cards": [clock["id"], note["id"]]})
    assert _save(client, board["slug"], _text(client, board["slug"])).status_code == 200
    widgets = {card["title"]: card for card in client.get(f"/api/v1/boards/{board['slug']}").json()["pages"][0]["widgets"]}
    assert widgets["Both"]["id"] == tabs["id"]
    assert widgets["Both"]["options"]["cards"] == [clock["id"], note["id"]]


def test_only_who_may_edit_the_board_reads_and_writes_it_as_text(client: TestClient) -> None:
    setup_admin(client)
    board = _board(client, "Home")
    robin = create_user(client, "robin")
    shared = client.put(f"/api/v1/boards/{board['slug']}/shares", json={"shares": [{"user_id": robin["id"], "level": "view"}]}, headers=CSRF)
    assert shared.status_code == 200, shared.text
    document = _text(client, board["slug"])
    login(client, "robin", "another-long-password")
    assert client.get(f"/api/v1/boards/{board['slug']}/export").status_code == 200, "looking may export, as before"
    assert client.get(f"/api/v1/boards/{board['slug']}/export?ids=true").status_code == 403
    assert _save(client, board["slug"], document).status_code == 403
