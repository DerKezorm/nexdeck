"""The grid of a board: how many columns it has, how wide it is drawn, and
whether its rows stretch to fill the window.

Adapters declare their sizes in twelfths, as every board had twelve columns
until 0.17.0. A board may now have 24 or 36, which lets a card be half a
column wider or narrower on a large screen. The adapters stay as they are;
their sizes are multiplied where they meet a board (``widen``), and
``widget_view`` hands the browser sizes that are already in the board's
columns, so nothing in the frontend has to remember the conversion.
"""

from __future__ import annotations

from typing import Any

#: The unit adapters declare sizes in, and what a board without the setting has.
BASE = 12
CHOICES = (12, 24, 36)
#: What a board made from the menu starts with.
NEW_BOARD = 24
WIDTHS = ("normal", "wide", "full")


def columns(settings: dict[str, Any] | None) -> int:
    value = (settings or {}).get("columns")
    return value if isinstance(value, int) and not isinstance(value, bool) and value in CHOICES else BASE


def widen(twelfths: int, cols: int) -> int:
    """A width in twelfths, in the columns of a board."""
    return twelfths * cols // BASE


def clean(settings: dict[str, Any] | None, cols: int) -> dict[str, Any]:
    """The settings as sent, with the grid's keys valid and the columns as they are.

    ⚠️ The columns are set here, never taken from what was sent. Changing them
    means rescaling every page (``rescale``), and a settings form that sent an
    old value, or none, would otherwise have turned a 24-column board into a
    12-column one with every card now twice as wide as the grid.
    """
    result = {key: value for key, value in (settings or {}).items() if key != "columns"}
    if result.get("width") not in WIDTHS:
        result.pop("width", None)
    if "fit_height" in result and not isinstance(result["fit_height"], bool):
        result.pop("fit_height")
    if cols != BASE:
        result["columns"] = cols
    return result


def _edge(value: int, factor: float) -> int:
    # Half up, not Python's half to even: two cards meeting at an edge must
    # map that edge to the same place, whichever of them is converted.
    return int(value * factor + 0.5)


def rescale(items: list[dict[str, Any]], before: int, after: int, floors: dict[str, int] | None = None) -> list[dict[str, Any]]:
    """The same arrangement on a grid of ``after`` columns.

    Every card's left and right edge is converted, not its position and its
    width: cards that stood side by side still meet, and the gaps between
    them shrink or grow with the rest. A card is at least its floor wide
    (``floors``, already in ``after`` columns) and stays inside the grid.
    Where shrinking still makes two cards share a cell, the lower one moves
    down until it does not, so no card ends up hidden under another.
    """
    if before == after:
        return [dict(item) for item in items]
    factor = after / before
    placed: list[dict[str, Any]] = []
    for item in sorted(items, key=lambda one: (one["y"], one["x"])):
        left = _edge(item["x"], factor)
        right = _edge(item["x"] + item["w"], factor)
        width = max(1, (floors or {}).get(str(item["i"]), 1), right - left)
        width = min(width, after)
        left = min(left, after - width)
        spot = {key: value for key, value in item.items() if key not in ("minW", "maxW")}
        spot.update({"x": left, "w": width})
        while any(_overlap(spot, other) for other in placed):
            spot["y"] += 1
        placed.append(spot)
    return placed


def _overlap(one: dict[str, Any], other: dict[str, Any]) -> bool:
    return (one["x"] < other["x"] + other["w"] and other["x"] < one["x"] + one["w"]
            and one["y"] < other["y"] + other["h"] and other["y"] < one["y"] + one["h"])
