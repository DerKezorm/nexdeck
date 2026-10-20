"""Home pages: a free surface of Home Assistant controls.

A home page is not arranged on the card grid. What stands on it, and where,
is a short list of elements with a position in pixels. The browser writes the
list; this module decides what of it is kept.

An element is a heading over a group, a lamp or a thermostat of the page's
Home Assistant connection. Lamps and thermostats are kept by their registry
id, which stays when the entity is renamed in Home Assistant, with the entity
id and name as they were when placed, for when Home Assistant cannot be asked.
A thermostat may name a temperature sensor to read the room by, kept the same
way. A statistics card names one to six sensors and is drawn from what Home
Assistant remembers of them (``hass_stats``); it keeps a width and a height.
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

KINDS = ("heading", "light", "climate", "stat")
#: How a lamp is drawn, the ten of the board of sketches; the first is the default.
#: The browser keeps the same list (``LAMP_STYLES`` in ``lib/home.ts``).
STYLES = ("pill", "round", "chip", "tile", "slider", "ring", "rocker", "dots", "bulb", "knob")
#: How a thermostat is drawn, the ten of its board of sketches; the first is the default.
#: The browser keeps the same list (``CLIMATE_STYLES`` in ``lib/home.ts``).
CLIMATE_STYLES = ("pill", "round", "chip", "tile", "slider", "dial", "valve", "thermometer", "radiator", "digits")
#: How a statistics card is drawn, the six of its board of sketches; the first is the default.
#: The browser keeps the same list (``STAT_STYLES`` in ``lib/home.ts``).
STAT_STYLES = ("line", "rooms", "band", "bars", "small", "compare")
#: How many sensors one statistics card shows at most.
MAX_SENSORS = 6
#: The bounds of a statistics card's size, in pixels (``STAT_SIZES`` in the browser).
STAT_WIDTHS = (150, 1200)
STAT_HEIGHTS = (80, 800)
#: How long a lamp's remembered name may be.
MAX_NAME = 80
#: The bounds of a width dragged by hand, in pixels (``MIN_WIDTH``, ``MAX_WIDTH`` in the browser).
WIDTHS = (96, 640)

_ID = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
_REGISTRY_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_LIGHT = re.compile(r"^light\.[a-z0-9_]{1,200}$")
_CLIMATE = re.compile(r"^climate\.[a-z0-9_]{1,200}$")
_SENSOR = re.compile(r"^sensor\.[a-z0-9_]{1,200}$")
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


def _sensor(raw: Any) -> dict[str, Any] | None:
    """The sensor a thermostat reads its room by, or None for the thermostat's own reading."""
    if not isinstance(raw, dict):
        return None
    rid, entity_id = raw.get("rid"), raw.get("entity_id")
    if not (isinstance(rid, str) and _REGISTRY_ID.match(rid)) or not (isinstance(entity_id, str) and _SENSOR.match(entity_id)):
        return None
    return {"rid": rid, "entity_id": entity_id, "name": _text(raw.get("name"), MAX_NAME)}


def _size(value: Any, bounds: tuple[int, int]) -> int | None:
    """A size dragged by hand, kept inside its bounds rather than dropped: an edge dragged a little too far is still a size."""
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value == value and abs(value) < 1e6:
        return min(bounds[1], max(bounds[0], round(value)))
    return None


def _stat(element_id: str, x: int, y: int, raw: dict[str, Any]) -> dict[str, Any] | None:
    sensors: list[dict[str, Any]] = []
    given = raw.get("sensors")
    for item in given if isinstance(given, list) else []:
        sensor = _sensor(item)
        if sensor is not None and all(one["entity_id"] != sensor["entity_id"] for one in sensors):
            sensors.append(sensor)
        if len(sensors) == MAX_SENSORS:
            break
    if not sensors:
        return None
    element = {"id": element_id, "type": "stat", "x": x, "y": y, "style": raw.get("style") if raw.get("style") in STAT_STYLES else STAT_STYLES[0],
               "sensors": sensors, "title": _text(raw.get("title"), MAX_NAME)}
    for key, bounds in (("width", STAT_WIDTHS), ("height", STAT_HEIGHTS)):
        size = _size(raw.get(key), bounds)
        if size is not None:
            element[key] = size
    return element


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
    if kind == "stat":
        return _stat(element_id, x, y, raw)
    if kind in ("light", "climate"):
        rid, entity_id = raw.get("rid"), raw.get("entity_id")
        pattern, styles = (_LIGHT, STYLES) if kind == "light" else (_CLIMATE, CLIMATE_STYLES)
        if not (isinstance(rid, str) and _REGISTRY_ID.match(rid)) or not (isinstance(entity_id, str) and pattern.match(entity_id)):
            return None
        style = raw.get("style") if raw.get("style") in styles else styles[0]
        element = {"id": element_id, "type": kind, "x": x, "y": y, "rid": rid, "entity_id": entity_id,
                   "name": _text(raw.get("name"), MAX_NAME), "style": style}
        width = _size(raw.get("width"), WIDTHS)
        if width is not None:
            element["width"] = width
        if kind == "climate":
            element["sensor"] = _sensor(raw.get("sensor"))
        return element
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
