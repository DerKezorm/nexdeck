"""A card left out of the phone's stack: two switches, kept with the card and in its file.

The leaving out itself happens in the browser, which alone knows how wide
the screen is (``lib/phone.ts``); the server keeps the switches and lets
nothing else in.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from .conftest import CSRF, setup_admin


def _page(client: TestClient) -> tuple[str, int]:
    board = client.post("/api/v1/boards", json={"name": "Phone"}, headers=CSRF).json()
    return board["slug"], board["pages"][0]["id"]


def test_the_switches_are_kept_and_travel_with_the_board_file(client: TestClient) -> None:
    setup_admin(client)
    slug, page = _page(client)
    made = client.post(f"/api/v1/pages/{page}/widgets", json={"kind": "core.clock", "options": {"phone_hide": True, "phone_show_red": False}}, headers=CSRF)
    assert made.status_code == 201, made.text
    card = made.json()["widget"]
    assert (card["options"]["phone_hide"], card["options"]["phone_show_red"]) == (True, False)

    exported = client.get(f"/api/v1/boards/{slug}/export")
    assert exported.status_code == 200, exported.text
    assert "phone_hide: true" in exported.text and "phone_show_red: false" in exported.text
    again = client.post("/api/v1/boards/import", json={"yaml_text": exported.text}, headers=CSRF)
    assert again.status_code in (200, 201), again.text
    imported = client.get(f"/api/v1/boards/{again.json()['slug']}").json()["pages"][0]["widgets"][0]
    assert (imported["options"]["phone_hide"], imported["options"]["phone_show_red"]) == (True, False)


@pytest.mark.parametrize("options", [{"phone_hide": "yes"}, {"phone_show_red": 1}, {"phone_hide": [True]}])
def test_nothing_but_on_and_off_gets_in(client: TestClient, options: dict) -> None:
    setup_admin(client)
    _slug, page = _page(client)
    made = client.post(f"/api/v1/pages/{page}/widgets", json={"kind": "core.clock", "options": options}, headers=CSRF)
    assert made.status_code == 400, made.text
    assert made.json()["detail"]["code"] == "bad_phone"
