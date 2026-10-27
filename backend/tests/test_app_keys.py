"""Number keys for app tiles: one digit opens one tile of a board, wherever on the board it stands.

What matters: a key given twice on one board is refused with the name of the
tile that has it, by every way a tile can arrive (made, changed, moved, in a
file); a copy beside its original comes without the key and says so; and a
key means nothing to another board.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from .conftest import CSRF, setup_admin


def _board(client: TestClient, name: str) -> dict:
    return client.post("/api/v1/boards", json={"name": name}, headers=CSRF).json()


def _tile(client: TestClient, page_id: int, title: str, key: str = ""):  # noqa: ANN202
    return client.post(f"/api/v1/pages/{page_id}/widgets", json={
        "kind": "core.app", "title": title, "link": f"https://{title.lower()}.example.com", "options": {"key": key, "check": False},
    }, headers=CSRF)


def _second_page(client: TestClient, slug: str) -> int:
    answer = client.post(f"/api/v1/boards/{slug}/pages", json={"name": "More"}, headers=CSRF)
    return next(page["id"] for page in answer.json()["pages"] if page["name"] == "More")


def test_a_key_opens_one_tile_of_a_board_and_any_tile_of_another(client: TestClient) -> None:
    setup_admin(client)
    home = _board(client, "Home")
    lab = _board(client, "Lab")
    made = _tile(client, home["pages"][0]["id"], "Wiki", "3")
    assert made.status_code == 201, made.text
    assert made.json()["widget"]["options"]["key"] == "3"

    # Another page of the same board is the same board.
    twice = _tile(client, _second_page(client, home["slug"]), "Films", "3")
    assert twice.status_code == 400, twice.text
    detail = twice.json()["detail"]
    assert (detail["code"], detail["key"], detail["name"]) == ("key_taken", "3", "Wiki")
    assert "Wiki" in detail["message"]
    assert _tile(client, lab["pages"][0]["id"], "Films", "3").status_code == 201
    assert _tile(client, home["pages"][0]["id"], "Music", "4").status_code == 201
    assert _tile(client, home["pages"][0]["id"], "Books").status_code == 201, "no key is no key, however many"
    assert _tile(client, home["pages"][0]["id"], "Notes").status_code == 201


def test_a_tile_keeps_its_own_key_and_cannot_take_another_ones(client: TestClient) -> None:
    setup_admin(client)
    home = _board(client, "Home")
    page = home["pages"][0]["id"]
    wiki = _tile(client, page, "Wiki", "1").json()["widget"]
    films = _tile(client, page, "Films", "2").json()["widget"]

    kept = client.patch(f"/api/v1/widgets/{wiki['id']}", json={"title": "Wiki", "options": {"key": "1", "check": False}}, headers=CSRF)
    assert kept.status_code == 200, kept.text
    taken = client.patch(f"/api/v1/widgets/{films['id']}", json={"options": {"key": "1", "check": False}}, headers=CSRF)
    assert taken.status_code == 400 and taken.json()["detail"]["code"] == "key_taken"
    assert client.patch(f"/api/v1/widgets/{films['id']}", json={"options": {"key": "", "check": False}}, headers=CSRF).status_code == 200
    assert client.patch(f"/api/v1/widgets/{wiki['id']}", json={"options": {"key": "2", "check": False}}, headers=CSRF).status_code == 200


@pytest.mark.parametrize("key", ["0", "10", "a", "F1"])
def test_a_key_is_one_digit_from_one_to_nine(client: TestClient, key: str) -> None:
    setup_admin(client)
    home = _board(client, "Home")
    refused = _tile(client, home["pages"][0]["id"], "Wiki", key)
    assert refused.status_code == 400, refused.text
    assert refused.json()["detail"]["code"] == "bad_key"


def test_a_tile_does_not_bring_its_key_to_a_board_where_another_has_it(client: TestClient) -> None:
    setup_admin(client)
    home = _board(client, "Home")
    lab = _board(client, "Lab")
    wiki = _tile(client, home["pages"][0]["id"], "Wiki", "5").json()["widget"]
    _tile(client, lab["pages"][0]["id"], "Films", "5")

    moved = client.post("/api/v1/widgets/move", json={"ids": [wiki["id"]], "page_id": lab["pages"][0]["id"]}, headers=CSRF)
    assert moved.status_code == 400, moved.text
    assert (moved.json()["detail"]["code"], moved.json()["detail"]["name"]) == ("key_taken", "Films")
    assert len(client.get(f"/api/v1/boards/{home['slug']}").json()["pages"][0]["widgets"]) == 1, "nothing moved"
    # Within its own board it goes anywhere.
    within = client.post("/api/v1/widgets/move", json={"ids": [wiki["id"]], "page_id": _second_page(client, home["slug"])}, headers=CSRF)
    assert within.status_code == 200, within.text


def test_a_copy_beside_its_original_comes_without_the_key_and_says_so(client: TestClient) -> None:
    setup_admin(client)
    home = _board(client, "Home")
    lab = _board(client, "Lab")
    page = home["pages"][0]["id"]
    wiki = _tile(client, page, "Wiki", "7").json()["widget"]

    here = client.post("/api/v1/widgets/copy", json={"ids": [wiki["id"]], "page_id": page}, headers=CSRF).json()
    assert here["notes"] == [{"code": "key_dropped", "name": "Wiki", "key": "7"}]
    shown = {one["id"]: one for one in client.get(f"/api/v1/boards/{home['slug']}").json()["pages"][0]["widgets"]}
    assert "key" not in shown[here["ids"][0]]["options"] and shown[wiki["id"]]["options"]["key"] == "7"

    there = client.post("/api/v1/widgets/copy", json={"ids": [wiki["id"]], "page_id": lab["pages"][0]["id"]}, headers=CSRF).json()
    assert there["notes"] == []
    assert client.get(f"/api/v1/boards/{lab['slug']}").json()["pages"][0]["widgets"][0]["options"]["key"] == "7", "a free key comes along"


def test_a_board_file_gives_a_key_once(client: TestClient) -> None:
    setup_admin(client)
    tile = "    - kind: core.app\n      title: {title}\n      link: https://{title}.example.com\n      options:\n        key: '{key}'\n"
    twice = "nexdeck: 1\nboard:\n  name: Keys\npages:\n- name: One\n  widgets:\n" + tile.format(title="wiki", key="2") + "- name: Two\n  widgets:\n" + tile.format(title="films", key="2")
    refused = client.post("/api/v1/boards/import", json={"yaml_text": twice}, headers=CSRF)
    assert refused.status_code == 400, refused.text
    assert "Key 2" in refused.text
    wrong = "nexdeck: 1\nboard:\n  name: Keys\npages:\n- name: One\n  widgets:\n" + tile.format(title="wiki", key="0")
    assert client.post("/api/v1/boards/import", json={"yaml_text": wrong}, headers=CSRF).status_code == 400
    fine = "nexdeck: 1\nboard:\n  name: Keys\npages:\n- name: One\n  widgets:\n" + tile.format(title="wiki", key="2") + tile.format(title="films", key="3")
    made = client.post("/api/v1/boards/import", json={"yaml_text": fine}, headers=CSRF)
    assert made.status_code == 201, made.text
