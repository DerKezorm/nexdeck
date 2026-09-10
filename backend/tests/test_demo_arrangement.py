"""The demo board comes with its arrangement.

⚠️ It did not. The demo appended each card's place to the lists the session
keeps as the stored value, so the new value compared equal to the old one and
nothing was written. Every fresh setup showed each card three columns by two,
in the order it was made. Found on 10.09.2026 in the database of a fresh setup:
the Media page had eleven cards and not one saved position.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.services.demo_board import DEMO_PAGES

from .conftest import setup_admin


def test_every_card_of_the_demo_has_its_place_saved(client: TestClient) -> None:
    setup_admin(client, demo=True)
    board = client.get("/api/v1/boards").json()[0]
    view = client.get(f"/api/v1/boards/{board['slug']}").json()
    assert [page["name"] for page in view["pages"]] == [name for name, _ in DEMO_PAGES]

    checked = 0
    for page, (name, specs) in zip(view["pages"], DEMO_PAGES, strict=True):
        described = {(kind, title): spot for kind, title, _integration, _options, spot in specs}
        saved = {item["i"]: item for item in page["layouts"]["lg"]}
        assert len(page["widgets"]) == len(specs), f"{name}: the page has other cards than the demo describes"
        for widget in page["widgets"]:
            item = saved.get(str(widget["id"]))
            assert item is not None, f"{name}: {widget['title']} has no saved place"
            assert (item["x"], item["y"], item["w"], item["h"]) == described[(widget["kind"], widget["title"])]
            checked += 1

    # A demo without cards would pass the loop above without looking at anything.
    assert checked == sum(len(specs) for _, specs in DEMO_PAGES) > 20
