"""Scenes, scripts and switches of Home Assistant, for a home page.

A scene and a script are set off, not switched: a scene has no state but
when it was last set off (Home Assistant keeps that time as its state), a
script runs or does not. A switch (``switch``) and a helper
(``input_boolean``) are on or off; an outlet that measures what it draws has
a sensor of the class ``power`` on its device, and its draw goes with it.

A house of 232 lamps had 112 scenes (104 from Hue, with their room in
``group_name``), one script, 108 switches to be seen (30 outlets) and 18
helpers; 49 of 66 devices with a switch measured their power (20.10.2026).
"""

from __future__ import annotations

from typing import Any

from . import hass_registry
from .hass_sensors import _class_of, _since

#: The domains that are set off, and those that are switched.
TRIGGERS = ("scene", "script")
SWITCHES = ("switch", "input_boolean")


def action_state(entity_id: str, state: dict[str, Any] | None) -> dict[str, Any]:
    """How a scene, a script or a switch stands, in the words of the page.

    A scene says ``last``, when it was set off, in milliseconds, or None when
    Home Assistant does not know; a script whether it is ``running``; a switch
    whether it is ``on`` and since when.
    """
    state = state or {}
    value = state.get("state")
    domain = entity_id.split(".", 1)[0]
    if domain == "scene":
        unavailable = value == "unavailable"
        return {"kind": "scene", "unavailable": unavailable, "last": None if unavailable else _since({"last_changed": value}) if value not in (None, "unknown") else None}
    if domain == "script":
        return {"kind": "script", "unavailable": value not in ("on", "off"), "running": value == "on"}
    unavailable = value not in ("on", "off")
    return {"kind": "switch", "unavailable": unavailable, "on": None if unavailable else value == "on", "since": _since(state)}


def powers(entities: list[dict[str, Any]], states: dict[str, dict[str, Any]], kind: str = "power") -> dict[str, str]:
    """The sensor of each device that measures its ``power`` (or its ``energy``), by device id."""
    found: dict[str, str] = {}
    for entry in entities:
        entity_id = str(entry.get("entity_id") or "")
        device = entry.get("device_id")
        if not device or not entity_id.startswith("sensor.") or entry.get("disabled_by") or str(device) in found:
            continue
        state = states.get(entity_id)
        if state is not None and _class_of(entry, state) == kind:
            found[str(device)] = entity_id
    return found


def _power_of(entity_id: str | None, states: dict[str, dict[str, Any]]) -> float | None:
    if not entity_id:
        return None
    state = states.get(entity_id) or {}
    value = hass_registry._number(state.get("state"))
    if value is None:
        return None
    unit = str((state.get("attributes") or {}).get("unit_of_measurement") or "W")
    return round(value * 1000 if unit == "kW" else value, 1)


def pick_actions(entities: list[dict[str, Any]], devices: list[dict[str, Any]], areas: list[dict[str, Any]],
                 states: dict[str, dict[str, Any]], domains: tuple[str, ...]) -> list[dict[str, Any]]:
    """The scenes and scripts, or the switches and helpers, worth offering, sorted by name.

    A scene of Hue names its room (``group_name``) where Home Assistant gives
    it none. A switch brings the sensors that measure its device's power and
    energy, and what it draws now.
    """
    watts = powers(entities, states)
    energy = powers(entities, states, "energy")
    found = []
    for domain in domains:
        for entry, state, named in hass_registry._offered(entities, devices, areas, states, domain):
            attributes = state.get("attributes") or {}
            shown = {**named, **action_state(named["entity_id"], state)}
            if domain == "scene" and not shown["area"] and attributes.get("group_name"):
                shown["area"] = str(attributes["group_name"])
            if domain in SWITCHES:
                device = str(entry.get("device_id") or "")
                shown.update(device_class=str(attributes.get("device_class") or entry.get("device_class") or entry.get("original_device_class") or ""),
                             power_entity=watts.get(device), energy_entity=energy.get(device), power=_power_of(watts.get(device), states))
            found.append(shown)
    return hass_registry._by_name(found)


async def offered(config: dict[str, Any], cache: dict[str, Any], domains: tuple[str, ...], *, demo: bool = False) -> list[dict[str, Any]]:
    entities, devices, areas, states, _unit = await hass_registry.house(config, cache, demo=demo)
    return pick_actions(entities, devices, areas, states, domains)


def service_for(thing: dict[str, Any], *, on: bool | None = None, stop: bool = False) -> tuple[str, str, dict[str, Any]]:
    """The one service for what was asked: set a scene or a script off, stop a script, switch a switch."""
    domain = thing["entity_id"].split(".", 1)[0]
    if domain == "scene":
        return "scene", "turn_on", {}
    if domain == "script":
        return "script", "turn_off" if stop else "turn_on", {}
    return domain, "turn_on" if on else "turn_off", {}


def switch_demo(states: dict[str, dict[str, Any]], state: dict[str, Any], service: str, now_iso: str) -> dict[str, Any]:
    """The demo house: a scene remembers when it was set off, a script runs until it is stopped, a switch switches."""
    entity_id = state["entity_id"]
    if entity_id.startswith("scene."):
        value = now_iso
    elif entity_id.startswith("script."):
        value = "off" if service == "turn_off" else "on"
    else:
        value = "on" if service == "turn_on" else "off"
    states[entity_id] = {**state, "state": value, "last_changed": now_iso}
    return states[entity_id]
