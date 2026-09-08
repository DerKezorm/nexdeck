"""Uploaded files: where each one is used, and what deleting one costs.

⚠️ There was no way to take a file off the server. The quota's own message
says "delete a file you no longer need", and the only delete button in the
whole interface was the one for icons; the nightly sweeper leaves anything
with a row alone on purpose. So files piled up with nothing to say how many,
how large, or whether anything still drew them.

Two halves, and both matter: the list says where a file is used, and the
delete refuses while something still draws it unless the caller says to do it
anyway. A file deleted out from under a wall display leaves a hole nobody is
standing next to.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import db_session
from app.models import Asset, Board, Page, Widget

from .conftest import CSRF, create_user, login, setup_admin

PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
       b"\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82")


def _upload(client: TestClient, name: str = "rack.png", tail: bytes = b"", kind: str = "picture") -> dict:
    answer = client.post(f"/api/v1/assets?kind={kind}", files={"file": (name, PNG + tail, "image/png")}, headers=CSRF)
    assert answer.status_code == 201, answer.text
    return answer.json()


def _first_page(client: TestClient) -> int:
    with db_session() as db:
        page = db.scalar(select(Page))
        assert page is not None
        return page.id


def test_the_same_picture_twice_is_one_file(client: TestClient) -> None:
    """⚠️ It made two, and both counted against the quota. Nobody notices
    until the quota bites, and then there are two files with one name."""
    setup_admin(client)
    first = _upload(client)
    again = _upload(client, name="another-name.png")
    assert again["id"] == first["id"]
    with db_session() as db:
        assert len(list(db.scalars(select(Asset)))) == 1


def test_two_different_pictures_stay_two(client: TestClient) -> None:
    setup_admin(client)
    one = _upload(client, name="a.png")
    two = _upload(client, name="b.png", tail=b"different")
    assert one["id"] != two["id"]


def test_the_list_says_which_cards_draw_a_file(client: TestClient) -> None:
    setup_admin(client)
    asset = _upload(client)
    page = _first_page(client)
    made = client.post(f"/api/v1/pages/{page}/widgets", headers=CSRF, json={
        "kind": "core.image", "title": "The rack",
        "options": {"pictures": [{"url": asset["url"], "caption": ""}]},
    })
    assert made.status_code == 201, made.text

    listed = client.get("/api/v1/assets").json()
    mine = next(one for one in listed if one["id"] == asset["id"])
    assert mine["used_by"] == [{"what": "widget", "name": "The rack"}]


def test_a_file_used_as_a_background_is_found_too(client: TestClient) -> None:
    """⚠️ Over the whole stored value as text, not over the fields we happen
    to know. A background lives somewhere else entirely from a card's options,
    and the next card to hold an address has not been written yet."""
    setup_admin(client)
    asset = _upload(client, kind="background")
    with db_session() as db:
        board = db.scalar(select(Board))
        assert board is not None
        board.background = {"kind": "upload", "value": asset["url"], "blur": 18}
        name = board.name

    listed = client.get("/api/v1/assets").json()
    mine = next(one for one in listed if one["id"] == asset["id"])
    assert mine["used_by"] == [{"what": "board", "name": name}]


def test_a_file_nobody_draws_says_so(client: TestClient) -> None:
    setup_admin(client)
    asset = _upload(client)
    listed = client.get("/api/v1/assets").json()
    assert next(one for one in listed if one["id"] == asset["id"])["used_by"] == []


def test_deleting_a_file_in_use_is_refused_and_says_where(client: TestClient) -> None:
    setup_admin(client)
    asset = _upload(client)
    page = _first_page(client)
    client.post(f"/api/v1/pages/{page}/widgets", headers=CSRF, json={
        "kind": "core.image", "title": "The rack",
        "options": {"pictures": [{"url": asset["url"], "caption": ""}]},
    })

    refused = client.request("DELETE", f"/api/v1/assets/{asset['id']}", headers=CSRF)
    assert refused.status_code == 409, refused.text
    assert refused.json()["detail"]["code"] == "still_in_use"
    assert "The rack" in refused.json()["detail"]["message"]
    with db_session() as db:
        assert db.get(Asset, asset["id"]) is not None


def test_it_can_be_deleted_anyway_once_that_is_said(client: TestClient) -> None:
    setup_admin(client)
    asset = _upload(client)
    page = _first_page(client)
    client.post(f"/api/v1/pages/{page}/widgets", headers=CSRF, json={
        "kind": "core.image", "title": "The rack",
        "options": {"pictures": [{"url": asset["url"], "caption": ""}]},
    })

    gone = client.request("DELETE", f"/api/v1/assets/{asset['id']}?anyway=true", headers=CSRF)
    assert gone.status_code == 204, gone.text
    with db_session() as db:
        assert db.get(Asset, asset["id"]) is None
        # The card is left alone. It draws a placeholder now, which is the
        # honest outcome; silently rewriting somebody's card would be worse.
        widget = db.scalar(select(Widget).where(Widget.title == "The rack"))
        assert widget is not None


def test_a_file_nobody_draws_needs_no_second_word(client: TestClient) -> None:
    setup_admin(client)
    asset = _upload(client)
    gone = client.request("DELETE", f"/api/v1/assets/{asset['id']}", headers=CSRF)
    assert gone.status_code == 204, gone.text


def test_only_the_uploader_or_an_administrator_deletes_one(client: TestClient) -> None:
    setup_admin(client)
    asset = _upload(client)
    create_user(client, "kim")
    kim = TestClient(client.app)
    login(kim, "kim", "another-long-password")

    refused = kim.request("DELETE", f"/api/v1/assets/{asset['id']}", headers=CSRF)
    assert refused.status_code == 403, refused.text
    with db_session() as db:
        assert db.get(Asset, asset["id"]) is not None


def test_another_account_gets_its_own_copy(client: TestClient) -> None:
    """⚠️ Per account, not across the installation. Handing Kim the very file
    the administrator uploaded would tell Kim that it exists, and leave Kim
    with a file Kim cannot delete because somebody else uploaded it.
    """
    setup_admin(client)
    mine = _upload(client)
    create_user(client, "kim")
    kim = TestClient(client.app)
    login(kim, "kim", "another-long-password")

    theirs = _upload(kim)
    assert theirs["id"] != mine["id"]
    with db_session() as db:
        assert len(list(db.scalars(select(Asset)))) == 2
