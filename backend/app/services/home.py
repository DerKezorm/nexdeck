"""Home pages: a free surface of Home Assistant controls.

A home page is not arranged on the card grid. What stands on it, and where,
is a short list of elements with a position in pixels. The browser writes the
list; this module decides what of it is kept.

An element is a heading over a group, or a lamp of the page's Home Assistant
connection. A lamp is kept by its registry id, which stays when the entity is
renamed in Home Assistant, with its entity id and name as they were when it
was placed, for when Home Assistant cannot be asked.
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

KINDS = ("heading", "light")
#: How a lamp is drawn. The first is the default; more follow.
STYLES = ("pill",)
#: How long a lamp's remembered name may be.
MAX_NAME = 80

_ID = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
_REGISTRY_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_LIGHT = re.compile(r"^light\.[a-z0-9_]{1,200}$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def _coordinate(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value != value or value in (float("inf"), float("-inf")):
        return None
    number = round(value)
    return number if 0 <= number <= MAX_COORD else None


def _text(value: Any, limit: int = MAX_TEXT) -> str:
    if not isinstance(value, str):
        return ""
    return _CONTROL.sub("", value).strip()[:limit]


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
    if kind == "light":
        rid, entity_id = raw.get("rid"), raw.get("entity_id")
        if not (isinstance(rid, str) and _REGISTRY_ID.match(rid)) or not (isinstance(entity_id, str) and _LIGHT.match(entity_id)):
            return None
        style = raw.get("style") if raw.get("style") in STYLES else STYLES[0]
        return {"id": element_id, "type": kind, "x": x, "y": y, "rid": rid, "entity_id": entity_id,
                "name": _text(raw.get("name"), MAX_NAME), "style": style}
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
