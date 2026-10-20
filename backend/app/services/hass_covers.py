"""Shutters, blinds and awnings of Home Assistant (``cover``), for a home page.

What a cover can do is what Home Assistant says (``CoverEntityFeature`` in
``supported_features``): open, close, a position, stop, and the slats of a
venetian blind. A house of 232 lamps had 8 covers, all shutters with a
position and stop and none with slats (measured 20.10.2026, Bosch Smart Home
Controller). 0 is closed, 100 open, as in Home Assistant.
"""

from __future__ import annotations

from typing import Any

from ..adapters.base import AdapterError
from . import hass_registry

#: ``CoverEntityFeature``.
OPEN, CLOSE, SET_POSITION, STOP, OPEN_TILT, CLOSE_TILT, STOP_TILT, SET_TILT = 1, 2, 4, 8, 16, 32, 64, 128
#: What a page may ask of a cover: open, close, stop, or a position or slat angle as a number.
ACTIONS = ("open", "close", "stop")


def _percent(value: Any) -> int | None:
    number = hass_registry._number(value)
    return None if number is None else max(0, min(100, round(number)))


def cover_state(state: dict[str, Any] | None) -> dict[str, Any]:
    """How a cover stands and what it lets one do, in the words of the page.

    ``moving`` is ``up`` while it opens and ``down`` while it closes. A cover
    without a position is still open or closed: its position is then 100 or 0,
    as Home Assistant's own card shows it, and ``settable`` says it takes no
    other.
    """
    state = state or {}
    attributes = state.get("attributes") or {}
    value = state.get("state")
    unavailable = value not in ("open", "closed", "opening", "closing")
    features = int(hass_registry._number(attributes.get("supported_features")) or 0)
    position = _percent(attributes.get("current_position"))
    if position is None and not unavailable:
        position = 0 if value in ("closed", "opening") else 100
    return {
        "unavailable": unavailable,
        "position": None if unavailable else position,
        "tilt": None if unavailable else _percent(attributes.get("current_tilt_position")),
        "moving": "up" if value == "opening" else "down" if value == "closing" else None,
        "can_open": bool(features & OPEN),
        "can_close": bool(features & CLOSE),
        "settable": bool(features & SET_POSITION),
        "stoppable": bool(features & STOP),
        "tiltable": bool(features & SET_TILT),
    }


def pick_covers(entities: list[dict[str, Any]], devices: list[dict[str, Any]], areas: list[dict[str, Any]],
                states: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """The covers worth offering, sorted by name, each with its device class (shutter, blind, awning …)."""
    found = []
    for entry, state, named in hass_registry._offered(entities, devices, areas, states, "cover"):
        kind = str((state.get("attributes") or {}).get("device_class") or entry.get("device_class") or entry.get("original_device_class") or "")
        found.append({**named, "device_class": kind, **cover_state(state)})
    return hass_registry._by_name(found)


async def covers(config: dict[str, Any], cache: dict[str, Any], *, demo: bool = False) -> list[dict[str, Any]]:
    entities, devices, areas, states, _unit = await hass_registry.house(config, cache, demo=demo)
    return pick_covers(entities, devices, areas, states)


def service_for(cover: dict[str, Any], *, action: str | None = None, position: int | None = None,
                tilt: int | None = None) -> tuple[str, str, dict[str, Any]]:
    """The service and its data for what was asked of a cover, or ``not_supported`` when it cannot.

    A cover without a position is opened or closed for 100 and 0 and refused
    anything between; one without slats is refused an angle.
    """
    name = cover.get("name", "This cover")
    if tilt is not None:
        if not cover.get("tiltable"):
            raise AdapterError(f"{name} has no slats to turn.", code="not_supported")
        return "cover", "set_cover_tilt_position", {"tilt_position": max(0, min(100, int(tilt)))}
    if position is not None:
        position = max(0, min(100, int(position)))
        if cover.get("settable"):
            return "cover", "set_cover_position", {"position": position}
        if position in (0, 100):
            action = "open" if position == 100 else "close"
        else:
            raise AdapterError(f"{name} only opens and closes all the way.", code="not_supported")
    if action == "stop":
        if not cover.get("stoppable"):
            raise AdapterError(f"{name} cannot be stopped on its way.", code="not_supported")
        return "cover", "stop_cover", {}
    if action == "open":
        if not cover.get("can_open"):
            raise AdapterError(f"{name} does not open.", code="not_supported")
        return "cover", "open_cover", {}
    if action == "close":
        if not cover.get("can_close"):
            raise AdapterError(f"{name} does not close.", code="not_supported")
        return "cover", "close_cover", {}
    raise AdapterError("Ask a cover to open, close, stop or go to a position.", code="not_supported")


def switch_demo(states: dict[str, dict[str, Any]], state: dict[str, Any], service: str, data: dict[str, Any]) -> dict[str, Any]:
    """A demo cover goes where it is sent at once; a real one takes its time, and its page shows it moving."""
    attributes = dict(state.get("attributes") or {})
    position = attributes.get("current_position", 100 if state.get("state") == "open" else 0)
    if service == "open_cover":
        position = 100
    elif service == "close_cover":
        position = 0
    elif service == "set_cover_position":
        position = data["position"]
    elif service == "set_cover_tilt_position":
        attributes["current_tilt_position"] = data["tilt_position"]
    attributes["current_position"] = position
    states[state["entity_id"]] = {**state, "state": "closed" if position == 0 else "open", "attributes": attributes}
    return states[state["entity_id"]]
