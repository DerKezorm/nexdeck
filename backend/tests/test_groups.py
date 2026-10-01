"""Cards that hold other cards: tabs and groups, and what they may hold."""

from __future__ import annotations

from fastapi.testclient import TestClient

from .conftest import CSRF, setup_admin


def _board(client: TestClient, name: str) -> dict:
    return client.post("/api/v1/boards", json={"name": name}, headers=CSRF).json()


def _card(client: TestClient, page_id: int, kind: str, **extra: object) -> dict:
    answer = client.post(f"/api/v1/pages/{page_id}/widgets", json={"kind": kind, **extra}, headers=CSRF)
    assert answer.status_code == 201, answer.text
    return answer.json()["widget"]


def test_a_group_keeps_only_cards_of_its_own_page_and_no_holder(client: TestClient) -> None:
    setup_admin(client)
    board = _board(client, "Home")
    page = board["pages"][0]["id"]
    grown = client.post(f"/api/v1/boards/{board['slug']}/pages", json={"name": "Other"}, headers=CSRF).json()
    other = next(one["id"] for one in grown["pages"] if one["name"] == "Other")
    note = _card(client, page, "core.markdown")
    clock = _card(client, page, "core.clock")
    elsewhere = _card(client, other, "core.clock")
    tabs = _card(client, page, "core.tabs")
    group = _card(client, page, "core.group", options={"cards": [note["id"], tabs["id"], elsewhere["id"], 999_999, "x", note["id"]]})
    assert group["options"]["cards"] == [note["id"]], "another page, a holder, a stranger, a word and a repeat are left out"

    changed = client.patch(f"/api/v1/widgets/{tabs['id']}", json={"options": {"cards": [clock["id"], tabs["id"], note["id"]], "turn": "10"}}, headers=CSRF)
    assert changed.status_code == 200, changed.text
    assert changed.json()["options"] == {"cards": [clock["id"], note["id"]], "turn": "10"}, "not itself"


def test_a_group_survives_export_and_import_with_its_cards(client: TestClient) -> None:
    setup_admin(client)
    board = _board(client, "Home")
    page = board["pages"][0]["id"]
    note = _card(client, page, "core.markdown", title="Notes")
    clock = _card(client, page, "core.clock", title="Clock")
    _card(client, page, "core.tabs", title="Both", options={"cards": [clock["id"], note["id"]]})

    text = client.get(f"/api/v1/boards/{board['slug']}/export").text
    assert "'#1'" in text or "#1" in text, "places, not numbers, in the file"
    imported = client.post("/api/v1/boards/import", json={"yaml_text": text, "slug": "home-copy"}, headers=CSRF)
    assert imported.status_code in (200, 201), imported.text
    copy = client.get("/api/v1/boards/home-copy").json()
    widgets = {one["title"]: one for one in copy["pages"][0]["widgets"]}
    assert widgets["Both"]["options"]["cards"] == [widgets["Clock"]["id"], widgets["Notes"]["id"]]
