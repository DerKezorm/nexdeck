"""Leaving demo mode: the invented data goes, everything real stays.

Switching the demo off used to clear one flag and nothing else. The demo's
own connections carry a demo switch of their own, so they went on inventing
data, the demo board went on showing it, and nothing on the board said so
any more: the notice only asks the flag.

``plan`` says what would go, for the confirmation; ``leave`` does it. The
rules, from what the demo itself creates:

- A connection is *invented* when it is in demo mode and points at
  ``demo.invalid``, the address the demo gives all of its own. It goes, with
  every card that reads it.
- A connection somebody set up for real and put into demo mode to try a card
  stays, and only its demo switch goes off.
- A board goes as a whole when it was nothing but the demo: every card on it
  reads an invented connection or none at all. The demo's clock and weather
  go with it; on a board of the owner's own they stay.
- A page emptied by this goes too, unless it is the last page of its board.
- Nobody is left without a board: if none remains, the starter board comes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Board, Integration, Page, Widget
from . import history
from .boards import remove_from_layouts

#: The address the demo gives every connection it invents.
DEMO_ADDRESS = "http://demo.invalid"


def invented(integration: Integration) -> bool:
    return bool(integration.demo) and str((integration.config or {}).get("url") or "").rstrip("/") == DEMO_ADDRESS


@dataclass
class Plan:
    connections: list[Integration] = field(default_factory=list)
    switched: list[Integration] = field(default_factory=list)
    boards: list[Board] = field(default_factory=list)
    cards: list[Widget] = field(default_factory=list)
    pages: list[Page] = field(default_factory=list)

    def view(self, flag: bool) -> dict[str, Any]:
        return {
            "flag": flag,
            "connections": sorted(i.name for i in self.connections),
            "switched": sorted(i.name for i in self.switched),
            "boards": [b.name for b in self.boards],
            # Cards on the boards that go count too: the confirmation says
            # how many cards disappear, wherever they sit.
            "cards": len(self.cards),
            "pages": len(self.pages),
        }

    @property
    def anything(self) -> bool:
        return bool(self.connections or self.switched or self.boards or self.cards)


def plan(db: Session) -> Plan:
    result = Plan()
    for integration in db.scalars(select(Integration).where(Integration.demo.is_(True)).order_by(Integration.id)):
        (result.connections if invented(integration) else result.switched).append(integration)
    gone = {integration.id for integration in result.connections}
    if not gone:
        return result
    for board in db.scalars(select(Board).order_by(Board.position, Board.id)):
        cards = [w for page in board.pages for w in page.widgets]
        reading = [w for w in cards if w.integration_id in gone]
        if not reading:
            continue
        if all(w.integration_id is None or w.integration_id in gone for w in cards):
            result.boards.append(board)
            result.cards.extend(cards)
            continue
        result.cards.extend(reading)
        emptied = [page for page in board.pages if page.widgets and all(w.integration_id in gone for w in page.widgets)]
        # The last page of a board stays, empty or not: a board has one.
        if len(emptied) == len(board.pages):
            emptied = emptied[1:]
        result.pages.extend(emptied)
    return result


def leave(db: Session, owner_id: int | None) -> tuple[Plan, list[int], Board | None]:
    """Remove what ``plan`` names. Returns the plan, the ids of the removed
    cards (for the collector) and the starter board if one had to be made.
    The caller commits."""
    from .demo_board import create_starter

    what = plan(db)
    removed = [w.id for w in what.cards]
    doomed_boards = {b.id for b in what.boards}
    doomed_pages = {p.id for p in what.pages}
    for widget in what.cards:
        # The history is kept by number, and SQLite hands numbers out again.
        history.forget_widget(db, widget.id)
        page = widget.page
        # A card on a board or page that goes, goes with it.
        if page.board_id not in doomed_boards and page.id not in doomed_pages:
            remove_from_layouts(page, widget.id)
            db.delete(widget)
    for page in what.pages:
        db.delete(page)
    for board in what.boards:
        db.delete(board)
    for integration in what.connections:
        db.delete(integration)
    for integration in what.switched:
        integration.demo = False
    db.flush()
    starter = None
    if what.boards and db.scalar(select(Board.id).limit(1)) is None:
        starter = create_starter(db, owner_id=owner_id)
    return what, removed, starter
