"""Home pages: a free surface of Home Assistant controls.

A home page is not arranged on the card grid. What stands on it, and where,
is a short list of elements with a position in pixels. The browser writes the
list; this module decides what of it is kept.

So far an element is a heading over a group of controls. The controls
themselves follow, one kind at a time.
"""

from __future__ import annotations

import re
from typing import Any

#: The most elements a page keeps; a house with this many lamps has other problems.
MAX_ELEMENTS = 500
#: How far from the corner an element may stand, in pixels.
MAX_COORD = 20000
#: How long a heading may be.
MAX_TEXT = 60

KINDS = ("heading",)

_ID = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def _coordinate(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value != value or value in (float("inf"), float("-inf")):
        return None
    number = round(value)
    return number if 0 <= number <= MAX_COORD else None


def _text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return _CONTROL.sub("", value).strip()[:MAX_TEXT]


def clean_element(raw: Any) -> dict[str, Any] | None:
    """One element as it is kept, or None when it is not one this page knows."""
    if not isinstance(raw, dict):
        return None
    element_id, kind = raw.get("id"), raw.get("type")
    if not (isinstance(element_id, str) and _ID.match(element_id)) or kind not in KINDS:
        return None
    x, y = _coordinate(raw.get("x")), _coordinate(raw.get("y"))
    if x is None or y is None:
        return None
    text = _text(raw.get("text"))
    if not text:
        return None
    return {"id": element_id, "type": kind, "x": x, "y": y, "text": text}


def clean_layout(raw: Any, integration_id: int | None) -> dict[str, Any]:
    """The part of a home page a browser writes: what stands where.

    Elements the page does not know, broken ones and the second of two with
    the same id are left out rather than refusing the whole page: an older
    browser and a newer server should still get along.
    """
    raw = raw if isinstance(raw, dict) else {}
    elements: list[dict[str, Any]] = []
    seen: set[str] = set()
    source = raw.get("elements") if isinstance(raw.get("elements"), list) else []
    for item in source:
        element = clean_element(item)
        if element is None or element["id"] in seen:
            continue
        seen.add(element["id"])
        elements.append(element)
        if len(elements) == MAX_ELEMENTS:
            break
    return {"integration_id": integration_id, "elements": elements}
