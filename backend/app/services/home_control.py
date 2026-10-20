"""Switching what stands on a home page, and telling open pages when it changed.

The browser names an element of a page and what it wants, never a service and
never an entity. The server reads the element from the page, finds the lamp
or the thermostat in Home Assistant by its registry id, and calls one of
``SERVICES`` for exactly that entity. Whatever else Home Assistant offers (a script, an alarm panel, a
lock) cannot be reached through a home page, whatever a browser sends.

Changes travel back as a ``home`` event on the board's stream, for the lamp
switched here and for the one switched at the wall, and for a thermostat and
the sensor it reads its room by: the WebSocket listener (``hass_ws``) hands
every state change to ``touched``.
"""

from __future__ import annotations

import asyncio
import colorsys
import time
from typing import Any

from sqlalchemy import select

from ..adapters.base import AdapterError, Context, base_url
from ..db import db_session
from ..models import Page
from . import hass_covers, hass_registry, hass_sensors, hass_switches
from .sse import board_topic, hub

#: The only services a home page calls, with the only data each may carry; anything else is
#: refused before Home Assistant hears of it.
SERVICES: dict[tuple[str, str], frozenset[str]] = {
    ("light", "turn_on"): frozenset({"brightness_pct", "color_temp_kelvin", "hs_color"}),
    ("light", "turn_off"): frozenset(),
    ("climate", "set_temperature"): frozenset({"temperature"}),
    ("climate", "set_hvac_mode"): frozenset({"hvac_mode"}),
    ("climate", "set_preset_mode"): frozenset({"preset_mode"}),
    ("cover", "open_cover"): frozenset(),
    ("cover", "close_cover"): frozenset(),
    ("cover", "stop_cover"): frozenset(),
    ("cover", "set_cover_position"): frozenset({"position"}),
    ("cover", "set_cover_tilt_position"): frozenset({"tilt_position"}),
    ("scene", "turn_on"): frozenset(),
    ("script", "turn_on"): frozenset(),
    ("script", "turn_off"): frozenset(),
    ("switch", "turn_on"): frozenset(),
    ("switch", "turn_off"): frozenset(),
    ("input_boolean", "turn_on"): frozenset(),
    ("input_boolean", "turn_off"): frozenset(),
}
#: The floor between two ``home`` events of one page; the last change always goes out.
PUSH_INTERVAL = 0.25
#: How long the map of lamps to pages is kept at most, for pages that came in by an import.
MAP_SECONDS = 60


def service_for(lamp: dict[str, Any], *, on: bool | None = None, brightness_pct: int | None = None,
                kelvin: int | None = None, hs: tuple[float, float] | None = None) -> tuple[str, str, dict[str, Any]]:
    """The service and its data for what was asked, or ``not_supported`` when the lamp cannot do it.

    What a lamp can do is what Home Assistant says (``light_state``): a lamp that
    only switches is not dimmed, a white lamp gets no colour. A white is kept
    inside the lamp's own range rather than refused, since a slider's end and
    the lamp's end are seldom the same number.
    """
    if on is False:
        return "light", "turn_off", {}
    data: dict[str, Any] = {}
    if brightness_pct is not None:
        if not lamp.get("dims"):
            raise AdapterError(f"{lamp.get('name', 'This lamp')} only switches on and off.", code="not_supported")
        data["brightness_pct"] = brightness_pct
    if kelvin is not None:
        if not lamp.get("temperature"):
            raise AdapterError(f"{lamp.get('name', 'This lamp')} has no whites to choose from.", code="not_supported")
        low, high = lamp.get("kelvin_min") or 2000, lamp.get("kelvin_max") or 6535
        data["color_temp_kelvin"] = min(high, max(low, kelvin))
    if hs is not None:
        if not lamp.get("colour"):
            raise AdapterError(f"{lamp.get('name', 'This lamp')} has no colours.", code="not_supported")
        data["hs_color"] = [round(hs[0], 1), round(hs[1], 1)]
    return "light", "turn_on", data


def climate_service_for(thermostat: dict[str, Any], *, target: float | None = None, mode: str | None = None,
                        preset: str | None = None) -> tuple[str, str, dict[str, Any]]:
    """The service and its data for what was asked of a thermostat, or ``not_supported``.

    A target is put on the thermostat's own step and kept inside its bounds,
    as its own buttons would; a mode or a preset has to be one it names.
    """
    name = thermostat.get("name", "This thermostat")
    if target is not None:
        if not thermostat.get("settable"):
            raise AdapterError(f"{name} takes no single target temperature.", code="not_supported")
        step = thermostat.get("step") or 0.5
        low, high = thermostat.get("min", 7.0), thermostat.get("max", 35.0)
        stepped = round(round(target / step) * step, 2)
        return "climate", "set_temperature", {"temperature": min(high, max(low, stepped))}
    if mode is not None:
        if mode not in (thermostat.get("modes") or []):
            raise AdapterError(f"{name} has no mode {mode!r}.", code="not_supported")
        return "climate", "set_hvac_mode", {"hvac_mode": mode}
    if preset is None or preset not in (thermostat.get("presets") or []):
        raise AdapterError(f"{name} has no preset {preset!r}.", code="not_supported")
    return "climate", "set_preset_mode", {"preset_mode": preset}


def climate_view(thermostat: dict[str, Any], sensor: dict[str, Any] | None, wanted: dict[str, Any] | None) -> dict[str, Any]:
    """What a page shows of a thermostat: its own state, the room read by the sensor it names when that one answers.

    A sensor that is gone or not answering does not leave the page without a
    reading: the thermostat's own is shown, and ``sensor.state`` says why.
    """
    view = {**thermostat, "missing": False, "reading": thermostat.get("current"), "sensor": None}
    if wanted:
        named = (sensor or {}).get("name") or wanted.get("name") or wanted.get("entity_id", "")
        if sensor is not None and not sensor.get("unavailable") and sensor.get("current") is not None:
            view["reading"] = sensor["current"]
            view["sensor"] = {"name": named, "state": "ok"}
        else:
            view["sensor"] = {"name": named, "state": "missing" if sensor is None else "unavailable"}
    return view


async def call(config: dict[str, Any], ctx: Context, domain: str, service: str, entity_id: str,
               data: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Call one of ``SERVICES`` for one entity of its domain; the states Home Assistant says changed."""
    allowed = SERVICES.get((domain, service))
    if allowed is None:
        raise AdapterError(f"A home page does not call {domain}.{service}.", code="service_refused")
    if not entity_id.startswith(f"{domain}.") or entity_id.count(".") != 1:
        raise AdapterError(f"{entity_id!r} is not a {domain}.", code="service_refused")
    data = data or {}
    if set(data) - allowed:
        raise AdapterError(f"{domain}.{service} from a home page takes no {', '.join(sorted(set(data) - allowed))}.", code="service_refused")
    response = await ctx.request(
        "POST", f"{base_url(config)}/api/services/{domain}/{service}",
        json_body={"entity_id": entity_id, **data},
        headers={"Authorization": f"Bearer {config.get('token', '')}", "Content-Type": "application/json"},
        verify=not config.get("insecure"),
    )
    if response.status_code >= 400:
        raise AdapterError(f"Home Assistant answered with HTTP {response.status_code}.", code="http_error")
    try:
        changed = response.json()
    except ValueError:
        return []
    return [state for state in changed if isinstance(state, dict)] if isinstance(changed, list) else []


def switch_demo(cache: dict[str, Any], entity_id: str, service: str, data: dict[str, Any]) -> dict[str, Any] | None:
    """The demo house's answer to a service: the lamp changes as a real one would, nothing leaves the server."""
    states = hass_registry.demo_states(cache)
    state = states.get(entity_id)
    if state is None or state.get("state") == "unavailable":
        return None
    if entity_id.startswith("climate."):
        return _demo_climate(states, state, service, data)
    if entity_id.startswith("cover."):
        return hass_covers.switch_demo(states, state, service, data)
    if entity_id.split(".", 1)[0] in hass_switches.TRIGGERS + hass_switches.SWITCHES:
        switched = hass_switches.switch_demo(states, state, service, time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()))
        # A demo outlet draws nothing while it is off, and its own while it is on.
        meter = hass_registry.DEMO_POWER.get(entity_id)
        if meter and meter[0] in states:
            states[meter[0]] = {**states[meter[0]], "state": str(meter[1] if switched["state"] == "on" else 0)}
        return switched
    on = service == "turn_on"
    attributes = dict(state.get("attributes") or {})
    modes = set(attributes.get("supported_color_modes") or [])
    if on and modes - {"onoff"} and not attributes.get("brightness"):
        attributes["brightness"] = 255
    if "brightness_pct" in data:
        attributes["brightness"] = round(data["brightness_pct"] * 255 / 100)
    if "color_temp_kelvin" in data:
        # A white: Home Assistant drops the colour the lamp had.
        attributes["color_temp_kelvin"] = data["color_temp_kelvin"]
        for gone in ("rgb_color", "hs_color"):
            attributes.pop(gone, None)
    if "hs_color" in data:
        hue, saturation = data["hs_color"]
        attributes["hs_color"] = [hue, saturation]
        attributes["rgb_color"] = [round(channel * 255) for channel in colorsys.hsv_to_rgb(hue / 360, saturation / 100, 1)]
        attributes.pop("color_temp_kelvin", None)
    states[entity_id] = {**state, "state": "on" if on else "off", "attributes": attributes}
    return states[entity_id]


def _demo_climate(states: dict[str, dict[str, Any]], state: dict[str, Any], service: str, data: dict[str, Any]) -> dict[str, Any]:
    """A demo thermostat: it takes the target, the mode or the preset, and heats while the room is colder."""
    attributes = dict(state.get("attributes") or {})
    mode = data.get("hvac_mode", state.get("state"))
    if "temperature" in data:
        attributes["temperature"] = data["temperature"]
    if "preset_mode" in data:
        attributes["preset_mode"] = data["preset_mode"]
    current, target = attributes.get("current_temperature"), attributes.get("temperature")
    colder = isinstance(current, (int, float)) and isinstance(target, (int, float)) and current < target
    attributes["hvac_action"] = "off" if mode == "off" else "heating" if mode in ("heat", "auto") and colder else "idle"
    states[state["entity_id"]] = {**state, "state": mode, "attributes": attributes}
    return states[state["entity_id"]]


# ---------------------------------------------------------------------------
# Telling open pages
# ---------------------------------------------------------------------------


#: (board, page, element, kind, for a thermostat: its entity and the sensor it names)
Spot = tuple[int, int, str, str, dict[str, Any]]
#: The domains whose changes a home page shows.
WATCHED = ("light.", "climate.", "sensor.", "binary_sensor.", "cover.", "scene.", "script.", "switch.", "input_boolean.")
#: The elements that show sensors, and where in each the sensors stand.
SENSOR_KINDS = ("contact", "contacts", "reading", "readings")
#: The elements that set off scenes and scripts or switch switches: one, or a card of several.
ACTION_KINDS = ("scene", "scenes", "switch", "switches")


def actions_of(element: dict[str, Any]) -> list[dict[str, Any]]:
    """Every scene, script or switch an element of ``ACTION_KINDS`` names, as it names them."""
    if element.get("type") in ("scene", "switch"):
        return [element]
    if element.get("type") in ("scenes", "switches"):
        return [one for one in element.get("sensors") or [] if isinstance(one, dict)]
    return []


#: The elements that show covers: one, or a card of several.
COVER_KINDS = ("cover", "covers")


def covers_of(element: dict[str, Any]) -> list[dict[str, Any]]:
    """Every cover an element of ``COVER_KINDS`` names, as it names them."""
    if element.get("type") == "cover":
        return [element]
    if element.get("type") == "covers":
        return [one for one in element.get("sensors") or [] if isinstance(one, dict)]
    return []


def sensors_of(element: dict[str, Any]) -> list[dict[str, Any]]:
    """Every sensor an element of ``SENSOR_KINDS`` names, as it names them (registry id, entity id, name)."""
    kind = element.get("type")
    if kind == "contact":
        return [element]
    if kind == "contacts":
        return [one for one in element.get("sensors") or [] if isinstance(one, dict)]
    if kind == "reading":
        return [one for one in (element.get("temperature"), element.get("humidity")) if isinstance(one, dict)]
    if kind == "readings":
        return [one for row in element.get("rows") or [] if isinstance(row, dict)
                for one in (row.get("temperature"), row.get("humidity")) if isinstance(one, dict)]
    return []


class HomeLive:
    """Which lamp and thermostat stands on which home page, and a ``home`` event when one of them changes."""

    def __init__(self) -> None:
        #: integration -> (registry it was built with, when, entity -> spots)
        self._map: dict[int, tuple[Any, float, dict[str, list[Spot]]]] = {}
        #: (board, page) -> kind ("lights", "climates") -> element -> how it stands, waiting to go out
        self._pending: dict[tuple[int, int], dict[str, dict[str, dict[str, Any]]]] = {}
        self._last: dict[tuple[int, int], float] = {}
        self._scheduled: set[tuple[int, int]] = set()

    def forget(self, integration_id: int | None = None) -> None:
        """Say that the lamps on the pages changed (a page was saved); others are found within ``MAP_SECONDS``."""
        if integration_id is None:
            self._map.clear()
        else:
            self._map.pop(integration_id, None)

    def reset(self) -> None:
        """Everything forgotten, as after a restart; for tests, whose integrations all start at 1."""
        self._map.clear()
        self._pending.clear()
        self._last.clear()
        self._scheduled.clear()

    def _watchers(self, integration_id: int, cache: dict[str, Any]) -> dict[str, list[Spot]]:
        """Read once per integration and kept until a page or the registry changes.

        An entity is listed under the id it was placed with and under the one
        its registry id has now, so one renamed in Home Assistant keeps its
        page current. A thermostat is listed under its own entity and under
        the sensor it reads its room by.
        """
        registry = cache.get("hass_registry")
        kept = self._map.get(integration_id)
        now = time.monotonic()
        if kept is not None and kept[0] is registry and now - kept[1] < MAP_SECONDS:
            return kept[2]
        renamed = {str(entry.get("id")): str(entry.get("entity_id")) for entry in (registry[1] if registry else []) if entry.get("id")}

        def names(thing: dict[str, Any]) -> set[str]:
            return {str(thing.get("entity_id") or ""), renamed.get(str(thing.get("rid")), "")} - {""}

        found: dict[str, list[Spot]] = {}
        # Which power sensor belongs to which switch, by their device.
        states_now = cache.get("hass_states") or cache.get("hass_demo_states") or {}
        watts = hass_switches.powers(registry[1] if registry else hass_registry.demo_registry()[0], states_now) if states_now else {}
        device_of = {str(entry.get("entity_id")): str(entry.get("device_id") or "") for entry in (registry[1] if registry else hass_registry.demo_registry()[0])}
        metered = {entity_id: watts[device] for entity_id, device in device_of.items() if device and device in watts and entity_id.split(".", 1)[0] in hass_switches.SWITCHES}
        with db_session() as db:
            for page in db.scalars(select(Page).where(Page.kind == "home")):
                home = page.home or {}
                if home.get("integration_id") != integration_id:
                    continue
                for element in home.get("elements") or []:
                    if isinstance(element, dict) and element.get("type") in ACTION_KINDS:
                        # Told by the entity id it was placed with; a switch also when its device's power changes.
                        for shown in actions_of(element):
                            placed = str(shown.get("entity_id") or "")
                            for entity_id in names(shown):
                                found.setdefault(entity_id, []).append((page.board_id, page.id, placed, "actions", {}))
                                meter = metered.get(entity_id)
                                if meter:
                                    found.setdefault(meter, []).append((page.board_id, page.id, placed, "actions", {"power": True}))
                        continue
                    if isinstance(element, dict) and element.get("type") in COVER_KINDS:
                        # A cover is told by the entity id it was placed with, as a sensor is.
                        for shown in covers_of(element):
                            placed = str(shown.get("entity_id") or "")
                            for entity_id in names(shown):
                                found.setdefault(entity_id, []).append((page.board_id, page.id, placed, "covers", {}))
                        continue
                    if isinstance(element, dict) and element.get("type") in SENSOR_KINDS:
                        # A sensor is told by the entity id it was placed with: the page keeps its sensors by that.
                        for shown in sensors_of(element):
                            placed = str(shown.get("entity_id") or "")
                            for entity_id in names(shown):
                                found.setdefault(entity_id, []).append((page.board_id, page.id, placed, "sensors", {}))
                        continue
                    if not isinstance(element, dict) or element.get("type") not in ("light", "climate"):
                        continue
                    if element["type"] == "light":
                        for entity_id in names(element):
                            found.setdefault(entity_id, []).append((page.board_id, page.id, str(element.get("id")), "lights", {}))
                        continue
                    climate = renamed.get(str(element.get("rid")), "") or str(element.get("entity_id") or "")
                    sensor = element.get("sensor") if isinstance(element.get("sensor"), dict) else None
                    reading = {**sensor, "entity_id": renamed.get(str(sensor.get("rid")), "") or str(sensor.get("entity_id") or "")} if sensor else None
                    spot = (page.board_id, page.id, str(element.get("id")), "climates", {"climate": climate, "sensor": reading})
                    for entity_id in names(element) | (names(sensor) if sensor else set()):
                        found.setdefault(entity_id, []).append(spot)
        self._map[integration_id] = (registry, now, found)
        return found

    def touched(self, integration_id: int, cache: dict[str, Any], entity_id: str, state: dict[str, Any]) -> None:
        """A lamp, a thermostat or its sensor changed: the pages hear of it, at most every ``PUSH_INTERVAL``.

        Anything else is not even looked up: a house sends dozens of changes a second.
        """
        if not entity_id.startswith(WATCHED):
            return
        spots = self._watchers(integration_id, cache).get(entity_id)
        if not spots:
            return
        touched_pages: list[tuple[int, int]] = []
        for board_id, page_id, element_id, kind, extra in spots:
            if kind == "lights":
                stands = {**hass_registry.light_state(state), "missing": False}
            elif kind == "sensors":
                stands = hass_sensors.live(entity_id, state)
            elif kind == "covers":
                stands = {**hass_covers.cover_state(state), "missing": False}
            elif kind == "actions" and extra.get("power"):
                stands = {"power": hass_switches._power_of(entity_id, {entity_id: state}), "missing": False}
            elif kind == "actions":
                stands = {**hass_switches.action_state(entity_id, state), "missing": False}
            else:
                stands = self._climate(cache, extra, entity_id, state)
            key = (board_id, page_id)
            self._pending.setdefault(key, {}).setdefault(kind, {})[element_id] = stands
            if key not in touched_pages:
                touched_pages.append(key)
        # Once per page, after all its spots: a sensor on two cards of one page is one event, not two.
        for key in touched_pages:
            self._schedule(key)

    @staticmethod
    def _climate(cache: dict[str, Any], extra: dict[str, Any], entity_id: str, state: dict[str, Any]) -> dict[str, Any]:
        """A thermostat as its page shows it, from the live states: the one that changed, and its partner."""
        states = cache.get("hass_states") or cache.get("hass_demo_states") or {}
        registry = cache.get("hass_registry")
        unit = registry[5] if registry and len(registry) > 5 else "°C"
        climate = state if entity_id == extra["climate"] else states.get(extra["climate"])
        wanted = extra.get("sensor")
        sensor_state = None
        if wanted:
            found = state if entity_id == wanted.get("entity_id") else states.get(wanted.get("entity_id", ""))
            sensor_state = hass_registry.sensor_state(found) if found is not None else None
        return climate_view(hass_registry.climate_state(climate, unit), sensor_state, wanted)

    def _schedule(self, key: tuple[int, int]) -> None:
        if key in self._scheduled:
            return
        wait = self._last.get(key, 0.0) + PUSH_INTERVAL - time.monotonic()
        if wait <= 0:
            self._flush(key)
            return
        self._scheduled.add(key)
        try:
            asyncio.get_running_loop().call_later(wait, self._flush, key)
        except RuntimeError:
            # No loop (a test calling straight in): send now rather than never.
            self._flush(key)

    def _flush(self, key: tuple[int, int]) -> None:
        self._scheduled.discard(key)
        news = self._pending.pop(key, None)
        if not news:
            return
        self._last[key] = time.monotonic()
        board_id, page_id = key
        hub.publish(board_topic(board_id), "home", {"page_id": page_id, **news})


home_live = HomeLive()
