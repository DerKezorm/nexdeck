"""Where a card of a page stands: on the grid, in a group, or in the page's side bar.

A group keeps its cards by number in ``options["cards"]`` (``boards.clean_cards``);
the side bar of a page keeps them in ``page.side["cards"]``. A card in either is
not on the grid. Inside, each card has a size of its own, kept on the card as
``options["held_size"]``: columns of twelve across the group, rows down, and in
the side bar only rows. Kept on the card and not on the holder, so a card
carries its size into a file and back without numbers that change on import.

``place`` moves one card in one step, taken out of wherever it was. A drag
between grid, group and side bar is one request, so nothing is left half done
when the second of two requests fails.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from ..deps import error
from ..models import Page, Widget

#: Where the side bar stands, and how wide it is.
PLACES = ("off", "left", "right")
WIDTHS = ("narrow", "wide")
#: More than this in a side bar is a second page.
MOST_SIDE = 12
#: A size inside a holder: up to twelve columns, up to twelve rows.
MOST_HELD = 12
#: Cards that hold others. A holder goes on the grid only, never into another.
HOLDER_KINDS = frozenset({"core.tabs", "core.group"})


def side_of(page: Page, present: set[int] | None = None) -> dict[str, Any]:
    """The side bar as it is kept, cards that are gone left out."""
    stored = page.side if isinstance(page.side, dict) else {}
    place = stored.get("place") if stored.get("place") in PLACES else "off"
    width = stored.get("width") if stored.get("width") in WIDTHS else "narrow"
    ids = present if present is not None else {widget.id for widget in page.widgets}
    cards = [number for number in stored.get("cards") or [] if isinstance(number, int) and number in ids]
    return {"place": place, "width": width, "cards": cards}


def set_side(page: Page, place: Any = None, width: Any = None) -> None:
    current = side_of(page)
    if place is not None:
        if place not in PLACES:
            raise error("bad_side", "The side bar stands left, right or nowhere.")
        current["place"] = place
        # Switched off, its cards go back onto the grid for good, rather than
        # being pulled off it again whenever the bar comes back.
        if place == "off":
            current["cards"] = []
    if width is not None:
        if width not in WIDTHS:
            raise error("bad_side", "The side bar is narrow or wide.")
        current["width"] = width
    page.side = current


def held_size(raw: Any) -> dict[str, int] | None:
    """A size inside a holder, or None for anything that is not one."""
    if not isinstance(raw, dict):
        return None
    try:
        w, h = int(raw.get("w", 0)), int(raw.get("h", 0))
    except (TypeError, ValueError):
        return None
    if not (1 <= w <= MOST_HELD and 1 <= h <= MOST_HELD):
        return None
    return {"w": w, "h": h}


def take_out(page: Page, widget_id: int) -> None:
    """Out of every group of the page and out of its side bar."""
    for holder in page.widgets:
        cards = (holder.options or {}).get("cards")
        if holder.kind in HOLDER_KINDS and isinstance(cards, list) and widget_id in cards:
            holder.options = {**holder.options, "cards": [number for number in cards if number != widget_id]}
    side = side_of(page)
    if widget_id in side["cards"]:
        side["cards"] = [number for number in side["cards"] if number != widget_id]
        page.side = side


def _insert(cards: list[int], widget_id: int, before: int | None) -> list[int]:
    if before is not None and before in cards:
        index = cards.index(before)
        return [*cards[:index], widget_id, *cards[index:]]
    return [*cards, widget_id]


def place(db: Session, page: Page, widget: Widget, into: str, *, group: Widget | None = None, before: int | None = None,
          spot: dict[str, int] | None = None, size: dict[str, int] | None = None, columns: int = 12) -> None:
    """Put ``widget`` on the grid at ``spot``, into ``group``, or into the side bar, before ``before``."""
    from .boards import MOST_TUCKED

    if widget.kind in HOLDER_KINDS and into != "board":
        raise error("bad_place", "A group or a tabs card stands on the board, not inside another.")
    if into == "group":
        if group is None or group.page_id != page.id or group.kind != "core.group" or group.id == widget.id:
            raise error("bad_place", "That is not a group on this page.")
        held = [number for number in (group.options or {}).get("cards") or [] if number != widget.id]
        if len(held) >= MOST_TUCKED:
            raise error("group_full", f"A group holds at most {MOST_TUCKED} cards.")
    elif into == "side":
        if side_of(page)["place"] == "off":
            raise error("side_off", "This page has no side bar. Switch it on above the board first.")
        if len([number for number in side_of(page)["cards"] if number != widget.id]) >= MOST_SIDE:
            raise error("side_full", f"A side bar holds at most {MOST_SIDE} cards.")
    elif into == "board":
        if spot is None:
            raise error("bad_place", "Say where on the board the card goes.")
        if spot["x"] + spot["w"] > columns:
            raise error("bad_place", f"This board has {columns} columns, and the card would stand past its edge.")
    else:
        raise error("bad_place", "A card goes onto the board, into a group or into the side bar.")

    take_out(page, widget.id)
    if size is not None:
        widget.options = {**(widget.options or {}), "held_size": size}
    if into == "group" and group is not None:
        group.options = {**(group.options or {}), "cards": _insert((group.options or {}).get("cards") or [], widget.id, before)}
    elif into == "side":
        side = side_of(page)
        side["cards"] = _insert(side["cards"], widget.id, before)
        page.side = side
    elif spot is not None:
        layouts = dict(page.layouts or {})
        others = [item for item in layouts.get("lg") or [] if item.get("i") != str(widget.id)]
        layouts["lg"] = [*others, {"i": str(widget.id), **spot}]
        page.layouts = layouts
    page.layout_version = (page.layout_version or 0) + 1
    db.flush()
