"""Where a new card lands, and what an import may bring in.

The placement was rewritten for speed on 07.09.2026: it used to copy the whole
layout dictionary and scan every card of every breakpoint for each card placed,
and it reassigned ``page.layouts`` every time, which rewrote the JSON column at
the next flush. Measured with YAML anchors, which make the file tiny and the
board huge: 500 cards took 5.9 s, 1000 took 17.8 s, 2000 took 59.3 s.

The point of the rewrite was that nothing about the result changes. The first
test here is the proof: the old algorithm stands in the file as a reference and
both are run side by side.
"""

from __future__ import annotations

import pytest

from app.models import Page
from app.services.boards import COLUMNS, MAX_PAGES, MAX_WIDGETS, ImportError_, Placer, import_board


def reference_place(page: Page, widget_id: int, size: tuple[int, int], min_size: tuple[int, int]) -> None:
    """The placement exactly as it stood before the rewrite. Do not tidy this up."""
    layouts = dict(page.layouts or {})
    for key, cols in COLUMNS.items():
        items = list(layouts.get(key) or [])
        w = min(cols, max(1, size[0] if key == "lg" else max(1, round(size[0] * cols / 12)) or 1))
        h = size[1]
        if key == "sm":
            w = min(cols, max(2, w))
        bottom = max((item["y"] + item["h"] for item in items), default=0)
        x = 0
        row_items = [item for item in items if item["y"] + item["h"] == bottom]
        if row_items:
            right = max(item["x"] + item["w"] for item in row_items)
            top = min(item["y"] for item in row_items)
            if right + w <= cols:
                x, bottom = right, top
        items.append({"i": str(widget_id), "x": x, "y": bottom, "w": w, "h": h, "minW": min_size[0], "minH": min_size[1]})
        layouts[key] = items
    page.layouts = layouts


#: Sizes that between them hit every branch: wide cards that never fit beside
#: anything, narrow ones that do, and cards shorter than the row they join.
SIZES = [(3, 2), (6, 3), (12, 1), (2, 4), (4, 2), (1, 1), (8, 5), (5, 2), (2, 2), (7, 3)]


def test_the_new_placement_lands_every_card_where_the_old_one_did() -> None:
    alt = Page(board_id=1, name="alt", slug="alt", position=0, layouts={key: [] for key in COLUMNS})
    neu = Page(board_id=1, name="neu", slug="neu", position=0, layouts={key: [] for key in COLUMNS})
    placer = Placer(neu)
    for number in range(60):
        size = SIZES[number % len(SIZES)]
        min_size = (max(1, size[0] // 2), max(1, size[1] // 2))
        reference_place(alt, number, size, min_size)
        placer.add(number, size, min_size)
    placer.finish()
    assert neu.layouts == alt.layouts, "the rewritten placement puts a card somewhere else than the old one"
    assert sum(len(items) for items in alt.layouts.values()) == 60 * len(COLUMNS), "the reference placed nothing, so this proves nothing"


def test_a_card_placed_by_hand_still_moves_the_edge() -> None:
    """An imported card with its own coordinates counts for what follows it."""
    page = Page(board_id=1, name="p", slug="p", position=0, layouts={key: [] for key in COLUMNS})
    placer = Placer(page)
    placer.add_at(1, {key: {"x": 0, "y": 0, "w": 2, "h": 9} for key in COLUMNS})
    placer.add(2, (12, 2), (1, 1))
    placer.finish()
    second = next(item for item in page.layouts["lg"] if item["i"] == "2")
    assert second["y"] == 9, "a card placed by hand was ignored, and the next one landed on top of it"


def test_the_layout_is_written_once_at_the_end() -> None:
    """Not per card: reassigning the column rewrites the whole page on flush."""
    page = Page(board_id=1, name="p", slug="p", position=0, layouts={key: [] for key in COLUMNS})
    placer = Placer(page)
    for number in range(5):
        placer.add(number, (3, 2), (1, 1))
    assert page.layouts["lg"] == [], "the page was written to before finish()"
    placer.finish()
    assert len(page.layouts["lg"]) == 5


def test_an_import_refuses_more_cards_than_it_will_show(data_dir) -> None:  # noqa: ANN001
    """YAML anchors make the file tiny and the board enormous."""
    from app.db import db_session

    head = ["board:", "  name: Too much", "pages:", "  - name: P", "    widgets:", "      - &k", "        kind: core.clock", "        title: K"]
    text = "\n".join(head + ["      - *k"] * MAX_WIDGETS) + "\n"
    with db_session() as db, pytest.raises(ImportError_) as refused:
        import_board(db, text, owner_id=1, slug="too-much", trusted=False, allow_locked=False)
    assert str(MAX_WIDGETS) in str(refused.value)

    pages = "\n".join(["board:", "  name: Many pages", "pages:"] + [f"  - name: P{i}" for i in range(MAX_PAGES + 1)]) + "\n"
    with db_session() as db, pytest.raises(ImportError_) as refused:
        import_board(db, pages, owner_id=1, slug="many-pages", trusted=False, allow_locked=False)
    assert str(MAX_PAGES) in str(refused.value)
