"""The heading card: a title or a line across the page, between groups of cards."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.adapters import get_adapter

from .conftest import CSRF, setup_admin


def test_a_new_heading_takes_the_whole_row_in_the_boards_own_columns(client: TestClient) -> None:
    setup_admin(client)
    board = client.post("/api/v1/boards", json={"name": "Sections", "settings": {"columns": 24}}, headers=CSRF).json()
    page = board["pages"][0]["id"]
    first = client.post(f"/api/v1/pages/{page}/widgets", json={"kind": "core.markdown"}, headers=CSRF)
    assert first.status_code == 201, first.text
    made = client.post(f"/api/v1/pages/{page}/widgets", json={"kind": "core.heading", "title": "Network"}, headers=CSRF)
    assert made.status_code == 201, made.text
    widget = made.json()["widget"]
    assert widget["renderer"] == "heading" and widget["title"] == "Network" and widget["client_only"] is True
    spots = {item["i"]: item for item in made.json()["layouts"]["lg"]}
    note, heading = spots[str(first.json()["widget"]["id"])], spots[str(widget["id"])]
    columns = client.get(f"/api/v1/boards/{board['slug']}").json()["settings"].get("columns", 12)
    assert (heading["x"], heading["w"], heading["h"]) == (0, columns, 1)
    # Under what was there, never beside it: a heading opens its own row.
    assert heading["y"] >= note["y"] + note["h"]


def test_a_heading_asks_nothing_of_a_service() -> None:
    heading = get_adapter("core").widget("heading")
    assert heading.client_only and heading.min_size == (1, 1)
    assert {field.name for field in heading.options} == {"style", "align", "size", "colour"}
    assert [value for value, _label in next(f for f in heading.options if f.name == "style").options] == ["both", "title", "line"]
