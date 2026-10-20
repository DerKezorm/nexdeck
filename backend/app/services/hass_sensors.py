"""What Home Assistant's sensors say, for a home page: doors and windows, temperature and humidity.

Only shown, never switched. A contact is a ``binary_sensor`` of the device
class door, window, opening or garage door: on is open. How long it has
stood so is its ``last_changed``. A house of 232 lamps had 29 of them (16
windows, 7 openings, 6 doors), 55 temperature and 21 humidity sensors, 20
devices with both (measured 20.10.2026, Home Assistant 2026.10).

A device with a battery has a sensor of the class ``battery`` beside the
others, mostly as a diagnostic entity; its value goes with every contact
and reading of that device, so a page can say that a window sensor is
running out.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from . import hass_registry

#: The device classes of a contact; on is open.
CONTACT_CLASSES = ("door", "window", "opening", "garage_door")
#: The classes of a reading.
READING_CLASSES = ("temperature", "humidity")


def _since(state: dict[str, Any]) -> int | None:
    """When a state last changed, in milliseconds, as a page counts "open for 12 minutes" from it."""
    value = state.get("last_changed") or state.get("last_updated")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return int(value * 1000 if value < 1e11 else value)
    if isinstance(value, str):
        try:
            moment = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return int((moment if moment.tzinfo else moment.replace(tzinfo=dt.UTC)).timestamp() * 1000)
    return None


def contact_state(state: dict[str, Any] | None) -> dict[str, Any]:
    """Whether a door or window is open, and since when; ``open`` is None while it cannot be read."""
    state = state or {}
    value = state.get("state")
    unavailable = value not in ("on", "off")
    return {"open": None if unavailable else value == "on", "since": _since(state), "unavailable": unavailable}


def reading_state(state: dict[str, Any] | None) -> dict[str, Any]:
    """What a temperature or humidity sensor reads now."""
    return hass_registry.sensor_state(state)


def _class_of(entry: dict[str, Any], state: dict[str, Any]) -> str:
    return str((state.get("attributes") or {}).get("device_class") or entry.get("device_class") or entry.get("original_device_class") or "")


def batteries(entities: list[dict[str, Any]], states: dict[str, dict[str, Any]]) -> dict[str, int]:
    """The battery of each device that has one, in percent; diagnostics count here, unlike everywhere else."""
    found: dict[str, int] = {}
    for entry in entities:
        entity_id = str(entry.get("entity_id") or "")
        device = entry.get("device_id")
        if not device or not entity_id.startswith("sensor.") or entry.get("disabled_by"):
            continue
        state = states.get(entity_id)
        if state is None or _class_of(entry, state) != "battery":
            continue
        value = hass_registry._number(state.get("state"))
        if value is not None and 0 <= value <= 100:
            found[str(device)] = round(value)
    return found


def _with_battery(named: dict[str, Any], entry: dict[str, Any], charged: dict[str, int]) -> dict[str, Any]:
    device = entry.get("device_id")
    return {**named, "device_id": str(device or ""), "battery": charged.get(str(device)) if device else None}


def pick_contacts(entities: list[dict[str, Any]], devices: list[dict[str, Any]], areas: list[dict[str, Any]],
                  states: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """The doors, windows and openings worth offering, sorted by name."""
    charged = batteries(entities, states)
    found = []
    for entry, state, named in hass_registry._offered(entities, devices, areas, states, "binary_sensor"):
        kind = _class_of(entry, state)
        if kind in CONTACT_CLASSES:
            found.append({**_with_battery(named, entry, charged), "device_class": kind, **contact_state(state)})
    return hass_registry._by_name(found)


def pick_readings(entities: list[dict[str, Any]], devices: list[dict[str, Any]], areas: list[dict[str, Any]],
                  states: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """The temperature and humidity sensors worth offering, each with its device, so the two of one device go together."""
    charged = batteries(entities, states)
    found = []
    for entry, state, named in hass_registry._offered(entities, devices, areas, states, "sensor"):
        kind = _class_of(entry, state)
        if kind in READING_CLASSES:
            found.append({**_with_battery(named, entry, charged), "device_class": kind, **reading_state(state)})
    return hass_registry._by_name(found)


async def offered(config: dict[str, Any], cache: dict[str, Any], *, demo: bool = False) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The contacts and the readings of one connection."""
    entities, devices, areas, states, _unit = await hass_registry.house(config, cache, demo=demo)
    return pick_contacts(entities, devices, areas, states), pick_readings(entities, devices, areas, states)


def live(entity_id: str, state: dict[str, Any]) -> dict[str, Any]:
    """How a sensor stands after a change, for the board's stream: its state, without what only the registry knows.

    Name, room and battery stay as the page had them.
    """
    if entity_id.startswith("binary_sensor."):
        return {**contact_state(state), "missing": False}
    return {**reading_state(state), "missing": False}
