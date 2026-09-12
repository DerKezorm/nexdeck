"""A board file whose layout cannot be read changes nothing.

⚠️ The check before the delete looked at kinds, options and intervals, not at
``layout``. A replacing file with ``layout: nope`` on one card got past it, the
old cards were deleted, the new ones half written, and ``_load`` caught the
error inside a database session that then committed whatever was there.
Reproduced on a copy on 12.09.2026: a wall board with two cards came back with
the cards of the broken file. Through the interface the same file answered
HTTP 500 instead of saying what is wrong.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import db_session
from app.models import Board, Page, Widget
from app.services import provisioning

from .conftest import CSRF, setup_admin

GOOD = """
board: {name: The wall, icon: layout}
pages:
  - name: one
    widgets:
      - {kind: core.clock, title: time}
      - {kind: core.markdown, title: a note}
"""

BROKEN_LAYOUTS = [
    "nope",
    "[1, 2]",
    "{lg: nope}",
    "{lg: {x: abc, y: 0}}",
    "{lg: {x: 0, y: 0, w: [4], h: 2}}",
]


def _replacement(layout: str) -> str:
    return f"""
board: {{name: The wall, icon: layout}}
pages:
  - name: one
    widgets:
      - {{kind: core.clock, title: time2}}
      - {{kind: core.markdown, title: note2, layout: {layout}}}
"""


def _cards(slug: str) -> list[str]:
    with db_session() as db:
        board = db.scalar(select(Board).where(Board.slug == slug))
        if board is None:
            return ["<no board>"]
        return sorted(db.scalars(select(Widget.title).join(Page).where(Page.board_id == board.id)))


def _provisioned(data_dir: Path) -> Path:
    directory = data_dir / "boards"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "wall.yaml"
    path.write_text(GOOD, encoding="utf-8")
    provisioning.load_all()
    assert _cards("the-wall") == ["a note", "time"], "the good file did not import, so this proves nothing"
    return path


@pytest.mark.parametrize("layout", BROKEN_LAYOUTS)
def test_a_replacing_file_with_a_broken_layout_leaves_the_board_alone(client: TestClient, data_dir: Path, layout: str) -> None:
    setup_admin(client)
    path = _provisioned(data_dir)
    path.write_text(_replacement(layout), encoding="utf-8")
    provisioning._load(path)
    assert _cards("the-wall") == ["a note", "time"]


def test_a_replacing_file_with_a_readable_layout_still_goes_through(client: TestClient, data_dir: Path) -> None:
    setup_admin(client)
    path = _provisioned(data_dir)
    path.write_text(_replacement("{lg: {x: 0, y: 0, w: 4, h: 3}}"), encoding="utf-8")
    provisioning._load(path)
    assert _cards("the-wall") == ["note2", "time2"]


@pytest.mark.parametrize("card", [
    "{kind: core.markdown, title: note2, layout: nope}",  # comes apart as an AttributeError
    "{kind: no-such-service.card, title: note2}",  # comes apart as an ImportError_
])
def test_a_file_that_fails_while_writing_is_rolled_back(client: TestClient, data_dir: Path, monkeypatch: pytest.MonkeyPatch, card: str) -> None:
    """The check before the delete will miss something again one day; then nothing may be half written."""
    from app.services import boards as board_service

    setup_admin(client)
    path = _provisioned(data_dir)
    monkeypatch.setattr(board_service, "_read_the_whole_thing_first", lambda *args, **kwargs: None)
    path.write_text(f"""
board: {{name: The wall, icon: layout}}
pages:
  - name: one
    widgets:
      - {{kind: core.clock, title: time2}}
      - {card}
""", encoding="utf-8")
    provisioning._load(path)
    assert _cards("the-wall") == ["a note", "time"]


@pytest.mark.parametrize("layout", BROKEN_LAYOUTS)
def test_an_import_with_a_broken_layout_says_why(client: TestClient, layout: str) -> None:
    setup_admin(client)
    answer = client.post("/api/v1/boards/import", json={"yaml_text": _replacement(layout)}, headers=CSRF)
    assert answer.status_code == 400, answer.text
    assert answer.json()["detail"]["code"] == "bad_import"
    assert "layout" in answer.json()["detail"]["message"]
