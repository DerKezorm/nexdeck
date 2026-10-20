"""What Home Assistant has to offer a home page: its lights and thermostats, as a person would pick them.

Home Assistant knows thousands of entities; a house of 232 lamps had 6262 in
its entity registry (measured 20.10.2026, Home Assistant 2026.10). A home page
offers only what makes sense to put on a wall, and decides that here, on the
server, before anything reaches a browser:

* lights and thermostats (``climate``), and temperature sensors to read a room by;
  the other domains follow one at a time,
* no settings and no diagnostics (``entity_category``): the brightness of a
  switch's status LED is not a lamp,
* nothing hidden or disabled in Home Assistant: hidden is how Home Assistant
  itself says "not this one", and ``switch_as_x`` hides the switch it wraps,
* nothing without a state: a registry entry whose device is gone.

⚠️ The display list of the entity registry (``list_for_display``) has neither
the registry's own id nor the area. The full list has both, and the id is what
a page keeps: it stays the same when an entity is renamed in Home Assistant,
where the entity id does not.
"""

from __future__ import annotations

import datetime as dt
import json
import time
from typing import Any

from ..adapters.base import AdapterError, AuthFailed, base_url

#: How long the registries are kept; they change when somebody edits the house.
REGISTRY_SECONDS = 60
#: The colour modes a lamp mixes colours in; ``white`` comes with one of them.
COLOUR_MODES = {"hs", "xy", "rgb", "rgbw", "rgbww"}
#: The whites Home Assistant assumes for a lamp that names none (``DEFAULT_MIN_KELVIN``, ``DEFAULT_MAX_KELVIN``).
DEFAULT_KELVIN = (2000, 6535)
#: ``ClimateEntityFeature``: one target temperature, a range of two, presets.
CLIMATE_TARGET = 1
CLIMATE_RANGE = 2
CLIMATE_PRESET = 16
#: What Home Assistant assumes for a thermostat that names no bounds (``DEFAULT_MIN_TEMP``, ``DEFAULT_MAX_TEMP``).
DEFAULT_TEMPERATURES = (7.0, 35.0)


# ---------------------------------------------------------------------------
# What a lamp can do and how it stands
# ---------------------------------------------------------------------------


def light_state(state: dict[str, Any] | None) -> dict[str, Any]:
    """How a lamp stands and what it can do, in the words the page uses.

    ``dims``, ``temperature``, ``colour``: what ``supported_color_modes`` says
    it can. In Home Assistant ``brightness`` stands alone; ``color_temp`` and
    the colour modes bring the brightness with them.
    """
    state = state or {}
    attributes = state.get("attributes") or {}
    modes = {str(mode) for mode in attributes.get("supported_color_modes") or []}
    value = state.get("state")
    on = value == "on"
    brightness = attributes.get("brightness")
    pct = round(brightness / 255 * 100) if on and isinstance(brightness, (int, float)) else None
    rgb = attributes.get("rgb_color")
    kelvin = attributes.get("color_temp_kelvin")
    hs = attributes.get("hs_color")
    temperature = "color_temp" in modes
    return {
        "on": on,
        "unavailable": value in (None, "unavailable", "unknown"),
        "pct": max(1, pct) if pct is not None else None,
        "rgb": [int(channel) for channel in rgb][:3] if on and isinstance(rgb, (list, tuple)) and len(rgb) >= 3 else None,
        "kelvin": int(kelvin) if on and isinstance(kelvin, (int, float)) else None,
        "hs": [round(float(hs[0]), 1), round(float(hs[1]), 1)] if on and isinstance(hs, (list, tuple)) and len(hs) >= 2 else None,
        "dims": bool(modes - {"onoff"}),
        "temperature": temperature,
        "colour": bool(modes & COLOUR_MODES),
        # The whites this lamp has; Home Assistant's own defaults when it does not say.
        "kelvin_min": _kelvin(attributes.get("min_color_temp_kelvin"), DEFAULT_KELVIN[0]) if temperature else None,
        "kelvin_max": _kelvin(attributes.get("max_color_temp_kelvin"), DEFAULT_KELVIN[1]) if temperature else None,
    }


def _kelvin(value: Any, fallback: int) -> int:
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and 1000 <= value <= 12000 else fallback


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and number not in (float("inf"), float("-inf")) else None


def climate_state(state: dict[str, Any] | None, unit: str = "°C") -> dict[str, Any]:
    """How a thermostat stands and what it lets one set, in the words the page uses.

    Only what Home Assistant says: modes from ``hvac_modes``, presets only with
    the preset feature, ``action`` only when the device reports one. A target
    is ``settable`` with the single-target feature; one with a range of two
    (heat and cool at once) is shown, not set, so far.
    """
    state = state or {}
    attributes = state.get("attributes") or {}
    value = state.get("state")
    unavailable = value in (None, "unavailable", "unknown")
    features = int(_number(attributes.get("supported_features")) or 0)
    presets = [str(preset) for preset in attributes.get("preset_modes") or []] if features & CLIMATE_PRESET else []
    low, high = _number(attributes.get("min_temp")), _number(attributes.get("max_temp"))
    return {
        "unavailable": unavailable,
        "on": not unavailable and value != "off",
        "mode": None if unavailable else str(value),
        "modes": [str(mode) for mode in attributes.get("hvac_modes") or []],
        "action": str(attributes["hvac_action"]) if attributes.get("hvac_action") else None,
        "current": _number(attributes.get("current_temperature")),
        "target": _number(attributes.get("temperature")),
        "target_low": _number(attributes.get("target_temp_low")),
        "target_high": _number(attributes.get("target_temp_high")),
        "settable": bool(features & CLIMATE_TARGET),
        "min": low if low is not None else DEFAULT_TEMPERATURES[0],
        "max": high if high is not None else DEFAULT_TEMPERATURES[1],
        # Home Assistant's own step when the device names none: a degree in Fahrenheit, half of one in Celsius.
        "step": _number(attributes.get("target_temp_step")) or (1.0 if unit == "°F" else 0.5),
        "preset": str(attributes["preset_mode"]) if presets and attributes.get("preset_mode") else None,
        "presets": presets,
        "unit": unit,
    }


def _offered(entities: list[dict[str, Any]], devices: list[dict[str, Any]], areas: list[dict[str, Any]],
             states: dict[str, dict[str, Any]], domain: str):
    """Each entity of one domain worth offering, with what every offer says about it: name, room, device."""
    area_names = {area.get("area_id"): area.get("name") or "" for area in areas}
    by_device = {device.get("id"): device for device in devices}
    for entry in entities:
        entity_id = str(entry.get("entity_id") or "")
        if not entity_id.startswith(f"{domain}.") or entry.get("entity_category") or entry.get("hidden_by") or entry.get("disabled_by"):
            continue
        state = states.get(entity_id)
        if state is None:
            continue
        device = by_device.get(entry.get("device_id")) or {}
        area_id = entry.get("area_id") or device.get("area_id")
        attributes = state.get("attributes") or {}
        name = attributes.get("friendly_name") or entry.get("name") or entry.get("original_name") or entity_id
        yield entry, state, {
            "rid": str(entry.get("id") or ""),
            "entity_id": entity_id,
            "name": str(name),
            "area": area_names.get(area_id, "") if area_id else "",
            "device": str(device.get("name_by_user") or device.get("name") or ""),
        }


def _by_name(found: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(found, key=lambda one: (one["name"].casefold(), one["entity_id"]))


def pick_lights(entities: list[dict[str, Any]], devices: list[dict[str, Any]], areas: list[dict[str, Any]],
                states: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """The lamps worth offering, with their name, room and device, sorted by name."""
    return _by_name([{**named, "group": entry.get("platform") == "group", **light_state(state)}
                     for entry, state, named in _offered(entities, devices, areas, states, "light")])


def pick_climates(entities: list[dict[str, Any]], devices: list[dict[str, Any]], areas: list[dict[str, Any]],
                  states: dict[str, dict[str, Any]], unit: str = "°C") -> list[dict[str, Any]]:
    """The thermostats worth offering, sorted by name."""
    return _by_name([{**named, **climate_state(state, unit)} for _entry, state, named in _offered(entities, devices, areas, states, "climate")])


def pick_temperature_sensors(entities: list[dict[str, Any]], devices: list[dict[str, Any]], areas: list[dict[str, Any]],
                             states: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """The sensors that measure a temperature, to read a room by instead of its thermostat.

    By device class, from the state or the registry; a humidity or a power
    sensor is not one, and a device's own temperature (diagnostic) is left out
    with every other diagnostic entity.
    """
    found = []
    for entry, state, named in _offered(entities, devices, areas, states, "sensor"):
        attributes = state.get("attributes") or {}
        kind = attributes.get("device_class") or entry.get("device_class") or entry.get("original_device_class")
        if kind != "temperature":
            continue
        found.append({**named, **sensor_state(state)})
    return _by_name(found)


def sensor_state(state: dict[str, Any] | None) -> dict[str, Any]:
    """What a temperature sensor reads now."""
    state = state or {}
    value = state.get("state")
    return {
        "current": _number(value),
        "unit": str((state.get("attributes") or {}).get("unit_of_measurement") or ""),
        "unavailable": value in (None, "unavailable", "unknown") or _number(value) is None,
    }


# ---------------------------------------------------------------------------
# Asking Home Assistant
# ---------------------------------------------------------------------------


async def _ask(config: dict[str, Any], commands: list[dict[str, Any]]) -> list[Any]:
    """One short WebSocket conversation: sign in, ask, collect the answers in order."""
    import websockets

    from .hass_ws import ssl_options

    url = base_url(config).replace("http://", "ws://", 1).replace("https://", "wss://", 1) + "/api/websocket"
    try:
        async with websockets.connect(url, max_size=64 * 1024 * 1024, open_timeout=15, **ssl_options(url, config)) as socket:
            await socket.recv()  # auth_required
            await socket.send(json.dumps({"type": "auth", "access_token": config.get("token", "")}))
            if json.loads(await socket.recv()).get("type") != "auth_ok":
                raise AuthFailed("Home Assistant rejected the token.")
            for number, command in enumerate(commands, start=1):
                await socket.send(json.dumps({"id": number, **command}))
            answers: dict[int, Any] = {}
            while len(answers) < len(commands):
                message = json.loads(await socket.recv())
                if message.get("type") != "result":
                    continue
                if not message.get("success"):
                    code = (message.get("error") or {}).get("code")
                    if code == "unauthorized":
                        raise AdapterError(
                            "Home Assistant lets only an administrator read which lamps there are.",
                            code="not_admin",
                            hint="Use a long-lived token of an administrator for this connection.",
                        )
                    raise AdapterError(f"Home Assistant refused {commands[message['id'] - 1]['type']}.", code="refused")
                answers[message["id"]] = message.get("result")
            return [answers[number] for number in range(1, len(commands) + 1)]
    except AdapterError:
        raise
    except Exception as failure:  # noqa: BLE001 - said, not shown as a trace
        raise AdapterError(f"Home Assistant could not be reached ({failure.__class__.__name__}).", code="unreachable",
                           hint="Check the address of the connection.") from failure


async def house(config: dict[str, Any], cache: dict[str, Any], *, demo: bool = False,
                now: float | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, dict[str, Any]], str]:
    """The registries, the states and the unit of temperature of one connection.

    The registries and the configuration are kept for a minute in the
    connection's cache. The states come from the live listener when it has
    them, so a lamp switched a moment ago shows how it stands now.
    """
    if demo:
        entities, devices, areas, _states = demo_registry()
        return entities, devices, areas, demo_states(cache), "°C"
    now = time.monotonic() if now is None else now
    kept = cache.get("hass_registry")
    live = cache.get("hass_states")
    if kept is None or kept[0] < now:
        commands: list[dict[str, Any]] = [
            {"type": "config/entity_registry/list"},
            {"type": "config/device_registry/list"},
            {"type": "config/area_registry/list"},
            {"type": "get_config"},
        ]
        if not isinstance(live, dict) or not live:
            commands.append({"type": "get_states"})
        answers = await _ask(config, commands)
        fetched = {state["entity_id"]: state for state in answers[4] or []} if len(answers) > 4 else {}
        unit = str(((answers[3] or {}).get("unit_system") or {}).get("temperature") or "°C")
        zone = str((answers[3] or {}).get("time_zone") or "UTC")
        kept = (now + REGISTRY_SECONDS, answers[0] or [], answers[1] or [], answers[2] or [], fetched, unit, zone)
        cache["hass_registry"] = kept
    _until, entities, devices, areas, fetched, unit = kept[:6]
    states = live if isinstance(live, dict) and live else fetched
    return entities, devices, areas, states, unit


def zone(cache: dict[str, Any]) -> str:
    """The time zone of the house, as its configuration names it; a day of statistics begins at its midnight."""
    kept = cache.get("hass_registry")
    return str(kept[6]) if kept and len(kept) > 6 and kept[6] else "UTC"


async def lights(config: dict[str, Any], cache: dict[str, Any], *, demo: bool = False, now: float | None = None) -> list[dict[str, Any]]:
    """The lamps of one connection, as ``pick_lights`` offers them."""
    entities, devices, areas, states, _unit = await house(config, cache, demo=demo, now=now)
    return pick_lights(entities, devices, areas, states)


async def climates(config: dict[str, Any], cache: dict[str, Any], *, demo: bool = False,
                   now: float | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The thermostats of one connection and the temperature sensors to read a room by."""
    entities, devices, areas, states, unit = await house(config, cache, demo=demo, now=now)
    return pick_climates(entities, devices, areas, states, unit), pick_temperature_sensors(entities, devices, areas, states)


# ---------------------------------------------------------------------------
# The demo house
# ---------------------------------------------------------------------------


#: The demo outlets that measure their power: the sensor, and what it reads while the outlet is on.
DEMO_POWER = {"switch.coffee_machine": ("sensor.coffee_machine_power", 1240), "switch.washing_machine": ("sensor.washing_machine_power", 520),
              "switch.router": ("sensor.router_power", 9), "switch.tv": ("sensor.tv_power", 85)}


def demo_states(cache: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """The demo house's lamps as they stand now, kept with the connection so switching them sticks."""
    return cache.setdefault("hass_demo_states", demo_registry()[3])


def demo_registry() -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """A made-up house, shaped like a real registry, for demo connections and tests."""
    areas = [{"area_id": "living", "name": "Living room"}, {"area_id": "kitchen", "name": "Kitchen"},
             {"area_id": "garden", "name": "Garden"}, {"area_id": "bedroom", "name": "Bedroom"},
             {"area_id": "bathroom", "name": "Bathroom"}, {"area_id": "hall", "name": "Hall"}, {"area_id": "cellar", "name": "Cellar"}]
    devices = [{"id": "d-floor", "name": "Floor lamp", "area_id": "living"}, {"id": "d-ceiling", "name": "Ceiling light", "area_id": "living"},
               {"id": "d-tv", "name": "LED strip", "area_id": "living"}, {"id": "d-counter", "name": "Counter light", "area_id": "kitchen"},
               {"id": "d-path", "name": "Path lights", "area_id": "garden"}, {"id": "d-bed", "name": "Bedside lamp", "area_id": "bedroom"},
               {"id": "d-switch", "name": "Wall dimmer", "area_id": "kitchen"},
               {"id": "d-heat-living", "name": "Living room thermostat", "area_id": "living"},
               {"id": "d-heat-bed", "name": "Bedroom radiator", "area_id": "bedroom"},
               {"id": "d-heat-bath", "name": "Bathroom radiator", "area_id": "bathroom"},
               {"id": "d-climate-living", "name": "Living room climate sensor", "area_id": "living"},
               {"id": "d-climate-bed", "name": "Bedroom climate sensor", "area_id": "bedroom"},
               {"id": "d-server", "name": "Home server", "area_id": None},
               {"id": "d-weather", "name": "Weather station", "area_id": "garden"},
               {"id": "d-meter", "name": "Electricity meter", "area_id": None},
               {"id": "d-climate-bath", "name": "Bathroom climate sensor", "area_id": "bathroom"},
               {"id": "d-window-kitchen", "name": "Kitchen window contact", "area_id": "kitchen"},
               {"id": "d-window-bath", "name": "Bathroom roof window contact", "area_id": "bathroom"},
               {"id": "d-door-front", "name": "Front door contact", "area_id": "hall"},
               {"id": "d-door-terrace", "name": "Terrace door contact", "area_id": "living"},
               {"id": "d-window-bed", "name": "Bedroom window contact", "area_id": "bedroom"},
               {"id": "d-window-cellar", "name": "Cellar window contact", "area_id": "cellar"},
               {"id": "d-window-guest", "name": "Guest room window contact", "area_id": None},
               {"id": "d-cover-terrace", "name": "Terrace shutter", "area_id": "living"},
               {"id": "d-cover-kitchen", "name": "Kitchen shutter", "area_id": "kitchen"},
               {"id": "d-cover-bed", "name": "Bedroom shutter", "area_id": "bedroom"},
               {"id": "d-cover-office", "name": "Office blind", "area_id": "hall"},
               {"id": "d-cover-garage", "name": "Garage door", "area_id": "garden"},
               {"id": "d-plug-coffee", "name": "Coffee machine plug", "area_id": "kitchen"},
               {"id": "d-plug-washer", "name": "Washing machine plug", "area_id": "cellar"},
               {"id": "d-plug-router", "name": "Router plug", "area_id": "hall"},
               {"id": "d-plug-tv", "name": "TV plug", "area_id": "living"},
               {"id": "d-pump", "name": "Garden pump", "area_id": "garden"}]

    def entry(rid: str, entity_id: str, device: str | None, **extra: Any) -> dict[str, Any]:
        return {"id": rid, "entity_id": entity_id, "device_id": device, "area_id": None, "entity_category": None,
                "hidden_by": None, "disabled_by": None, "platform": "demo", "name": None, "original_name": None, **extra}

    entities = [
        entry("r-floor", "light.floor_lamp", "d-floor"),
        entry("r-ceiling", "light.ceiling", "d-ceiling"),
        entry("r-tv", "light.tv_strip", "d-tv"),
        entry("r-counter", "light.kitchen_counter", "d-counter"),
        entry("r-path", "light.garden_path", "d-path"),
        entry("r-bed", "light.bedside", "d-bed"),
        entry("r-dining", "light.dining_table", None, platform="group", area_id="living"),
        entry("r-led", "light.wall_dimmer_status_led", "d-switch", entity_category="config"),
        entry("r-hidden", "light.old_bulb", None, hidden_by="user"),
        entry("r-off", "light.attic", None, disabled_by="user"),
        # In the registry, but its device is gone: no state, so not offered.
        entry("r-orphan", "light.cellar", None),
        entry("r-plug", "switch.floor_plug", "d-floor"),
        entry("r-heat-living", "climate.living_room", "d-heat-living"),
        entry("r-heat-bed", "climate.bedroom", "d-heat-bed"),
        entry("r-heat-bath", "climate.bathroom", "d-heat-bath"),
        entry("r-heat-old", "climate.old_valve", None, hidden_by="user"),
        entry("r-temp-living", "sensor.living_room_temperature", "d-climate-living"),
        entry("r-temp-bed", "sensor.bedroom_temperature", "d-climate-bed", original_device_class="temperature"),
        entry("r-hum-living", "sensor.living_room_humidity", "d-climate-living"),
        entry("r-cpu", "sensor.home_server_cpu_temperature", "d-server", entity_category="diagnostic"),
        entry("r-outdoor", "sensor.outdoor_temperature", "d-weather"),
        entry("r-energy", "sensor.house_energy", "d-meter"),
        # A text sensor: neither statistics nor a number, so no statistics card offers it.
        entry("r-washer", "sensor.washing_machine_programme", None),
        entry("r-temp-bath", "sensor.bathroom_temperature", "d-climate-bath"),
        entry("r-hum-bath", "sensor.bathroom_humidity", "d-climate-bath"),
        entry("r-hum-bed", "sensor.bedroom_humidity", "d-climate-bed"),
        entry("r-hum-outdoor", "sensor.outdoor_humidity", "d-weather"),
        entry("r-win-kitchen", "binary_sensor.kitchen_window", "d-window-kitchen"),
        entry("r-win-bath", "binary_sensor.bathroom_roof_window", "d-window-bath"),
        entry("r-door-front", "binary_sensor.front_door", "d-door-front"),
        entry("r-door-terrace", "binary_sensor.terrace_door", "d-door-terrace"),
        entry("r-win-bed", "binary_sensor.bedroom_window", "d-window-bed"),
        entry("r-win-cellar", "binary_sensor.cellar_window", "d-window-cellar"),
        # A battery is a diagnostic, and still told with its window.
        entry("r-bat-cellar", "sensor.cellar_window_battery", "d-window-cellar", entity_category="diagnostic"),
        entry("r-win-guest", "binary_sensor.guest_room_window", "d-window-guest"),
        # A motion sensor is no door: not offered.
        entry("r-motion-hall", "binary_sensor.hall_motion", None, area_id="hall"),
        entry("r-win-old", "binary_sensor.old_window", None, hidden_by="user"),
        entry("r-cover-terrace", "cover.living_room_terrace", "d-cover-terrace"),
        entry("r-cover-kitchen", "cover.kitchen", "d-cover-kitchen"),
        entry("r-cover-bed", "cover.bedroom", "d-cover-bed"),
        entry("r-cover-office", "cover.office_blind", "d-cover-office"),
        entry("r-cover-garage", "cover.garage_door", "d-cover-garage"),
        entry("r-cover-guest", "cover.guest_room", None),
        entry("r-cover-old", "cover.old_shutter", None, hidden_by="user"),
        entry("r-scene-cozy", "scene.living_room_cozy", None, platform="hue"),
        entry("r-scene-bright", "scene.living_room_bright", None, platform="hue"),
        entry("r-scene-cinema", "scene.living_room_cinema", None, platform="hue"),
        entry("r-scene-cooking", "scene.kitchen_cooking", None, platform="hue"),
        entry("r-scene-night", "scene.goodnight", None, platform="homeassistant"),
        entry("r-script-evening", "script.evening_shutters", None),
        entry("r-script-night", "script.goodnight_routine", None),
        entry("r-plug-coffee", "switch.coffee_machine", "d-plug-coffee"),
        entry("r-power-coffee", "sensor.coffee_machine_power", "d-plug-coffee"),
        entry("r-energy-coffee", "sensor.coffee_machine_energy", "d-plug-coffee"),
        entry("r-plug-washer", "switch.washing_machine", "d-plug-washer"),
        entry("r-power-washer", "sensor.washing_machine_power", "d-plug-washer"),
        entry("r-plug-router", "switch.router", "d-plug-router"),
        entry("r-power-router", "sensor.router_power", "d-plug-router"),
        entry("r-plug-tv", "switch.tv", "d-plug-tv"),
        entry("r-power-tv", "sensor.tv_power", "d-plug-tv"),
        entry("r-pump", "switch.garden_pump", "d-pump"),
        entry("r-garden-light", "switch.garden_light", None),
        entry("r-holiday", "input_boolean.holiday_mode", None),
        entry("r-guests", "input_boolean.guests", None),
        entry("r-switch-old", "switch.old_plug", None, hidden_by="user"),
    ]

    def state(entity_id: str, name: str, value: str, modes: list[str], **attributes: Any) -> dict[str, Any]:
        return {"entity_id": entity_id, "state": value, "attributes": {"friendly_name": name, "supported_color_modes": modes, **attributes}}

    now = dt.datetime.now(dt.UTC)

    def ago(minutes: float) -> str:
        return (now - dt.timedelta(minutes=minutes)).isoformat()

    def contact(entity_id: str, name: str, value: str, kind: str, minutes: float) -> dict[str, Any]:
        return {"entity_id": entity_id, "state": value, "last_changed": ago(minutes), "attributes": {"friendly_name": name, "device_class": kind}}

    def reading(entity_id: str, name: str, value: str, unit: str, kind: str) -> dict[str, Any]:
        return {"entity_id": entity_id, "state": value, "attributes": {"friendly_name": name, "unit_of_measurement": unit, "device_class": kind,
                                                                         "state_class": "measurement"}}

    def cover(entity_id: str, name: str, value: str, kind: str, features: int, **attributes: Any) -> dict[str, Any]:
        return {"entity_id": entity_id, "state": value, "attributes": {"friendly_name": name, "device_class": kind, "supported_features": features, **attributes}}

    def scene(entity_id: str, name: str, room: str | None, minutes: float | None) -> dict[str, Any]:
        attributes: dict[str, Any] = {"friendly_name": name}
        if room:
            attributes.update(group_name=room, group_type="room")
        return {"entity_id": entity_id, "state": ago(minutes) if minutes is not None else "unknown", "attributes": attributes}

    def switch(entity_id: str, name: str, value: str, kind: str | None = None) -> dict[str, Any]:
        return {"entity_id": entity_id, "state": value, "last_changed": ago(95), "attributes": {"friendly_name": name, **({"device_class": kind} if kind else {})}}

    def watts(entity_id: str, name: str, value: float) -> dict[str, Any]:
        return {"entity_id": entity_id, "state": str(value), "attributes": {"friendly_name": name, "unit_of_measurement": "W", "device_class": "power",
                                                                            "state_class": "measurement"}}

    states = {
        # Hue scenes name their room themselves; a scene of Home Assistant has none.
        "scene.living_room_cozy": scene("scene.living_room_cozy", "Cozy", "Living room", 10),
        "scene.living_room_bright": scene("scene.living_room_bright", "Bright", "Living room", 600),
        "scene.living_room_cinema": scene("scene.living_room_cinema", "Cinema", "Living room", None),
        "scene.kitchen_cooking": scene("scene.kitchen_cooking", "Cooking", "Kitchen", 90),
        "scene.goodnight": scene("scene.goodnight", "Good night", None, 1400),
        "script.evening_shutters": {"entity_id": "script.evening_shutters", "state": "off", "attributes": {"friendly_name": "Shutters in the evening"}},
        "script.goodnight_routine": {"entity_id": "script.goodnight_routine", "state": "on", "attributes": {"friendly_name": "Good night routine"}},
        "switch.coffee_machine": switch("switch.coffee_machine", "Coffee machine", "on", "outlet"),
        "sensor.coffee_machine_power": watts("sensor.coffee_machine_power", "Coffee machine power", 1240),
        "sensor.coffee_machine_energy": {"entity_id": "sensor.coffee_machine_energy", "state": "412.6", "attributes": {
            "friendly_name": "Coffee machine energy", "unit_of_measurement": "kWh", "device_class": "energy", "state_class": "total_increasing"}},
        "switch.washing_machine": switch("switch.washing_machine", "Washing machine", "on", "outlet"),
        "sensor.washing_machine_power": watts("sensor.washing_machine_power", "Washing machine power", 520),
        "switch.router": switch("switch.router", "Router", "on", "outlet"),
        "sensor.router_power": watts("sensor.router_power", "Router power", 9),
        "switch.tv": switch("switch.tv", "TV", "off", "outlet"),
        "sensor.tv_power": watts("sensor.tv_power", "TV power", 0),
        "switch.garden_pump": switch("switch.garden_pump", "Garden pump", "on"),
        "switch.garden_light": {"entity_id": "switch.garden_light", "state": "unavailable", "attributes": {"friendly_name": "Garden light"}},
        "input_boolean.holiday_mode": switch("input_boolean.holiday_mode", "Holiday mode", "off"),
        "input_boolean.guests": switch("input_boolean.guests", "Guests here", "on"),
        "switch.old_plug": switch("switch.old_plug", "Old plug", "off"),
        # Shutters as in the measured house: open, close, a position, stop (15); a blind with slats too (255); a door that only opens and closes (3).
        "cover.living_room_terrace": cover("cover.living_room_terrace", "Living room terrace", "closed", "shutter", 15, current_position=0),
        "cover.kitchen": cover("cover.kitchen", "Kitchen", "open", "shutter", 15, current_position=45),
        "cover.bedroom": cover("cover.bedroom", "Bedroom", "closing", "shutter", 15, current_position=70),
        "cover.office_blind": cover("cover.office_blind", "Office blind", "open", "blind", 255, current_position=100, current_tilt_position=45),
        "cover.garage_door": cover("cover.garage_door", "Garage door", "closed", "garage", 3),
        "cover.guest_room": {"entity_id": "cover.guest_room", "state": "unavailable", "attributes": {"friendly_name": "Guest room"}},
        "cover.old_shutter": cover("cover.old_shutter", "Old shutter", "open", "shutter", 15, current_position=100),
        "sensor.bathroom_temperature": reading("sensor.bathroom_temperature", "Bathroom temperature", "23.1", "°C", "temperature"),
        "sensor.bathroom_humidity": reading("sensor.bathroom_humidity", "Bathroom humidity", "71", "%", "humidity"),
        "sensor.bedroom_humidity": reading("sensor.bedroom_humidity", "Bedroom humidity", "54", "%", "humidity"),
        "sensor.outdoor_humidity": reading("sensor.outdoor_humidity", "Outdoor humidity", "91", "%", "humidity"),
        "binary_sensor.kitchen_window": contact("binary_sensor.kitchen_window", "Kitchen window", "on", "window", 12),
        "binary_sensor.bathroom_roof_window": contact("binary_sensor.bathroom_roof_window", "Bathroom roof window", "on", "window", 125),
        "binary_sensor.front_door": contact("binary_sensor.front_door", "Front door", "off", "door", 900),
        "binary_sensor.terrace_door": contact("binary_sensor.terrace_door", "Terrace door", "on", "door", 4),
        "binary_sensor.bedroom_window": contact("binary_sensor.bedroom_window", "Bedroom window", "off", "window", 300),
        "binary_sensor.cellar_window": contact("binary_sensor.cellar_window", "Cellar window", "off", "window", 4000),
        "sensor.cellar_window_battery": {"entity_id": "sensor.cellar_window_battery", "state": "8", "attributes": {
            "friendly_name": "Cellar window battery", "unit_of_measurement": "%", "device_class": "battery"}},
        "binary_sensor.guest_room_window": {"entity_id": "binary_sensor.guest_room_window", "state": "unavailable", "attributes": {
            "friendly_name": "Guest room window", "device_class": "window"}},
        "binary_sensor.hall_motion": contact("binary_sensor.hall_motion", "Hall motion", "on", "motion", 1),
        "binary_sensor.old_window": contact("binary_sensor.old_window", "Old window", "off", "window", 9000),
        "light.floor_lamp": state("light.floor_lamp", "Floor lamp", "on", ["color_temp", "xy"], brightness=158, color_temp_kelvin=2400, rgb_color=[255, 167, 87],
                                  min_color_temp_kelvin=2202, max_color_temp_kelvin=6535),
        "light.ceiling": state("light.ceiling", "Ceiling light", "on", ["color_temp"], brightness=204, color_temp_kelvin=3000,
                               min_color_temp_kelvin=2700, max_color_temp_kelvin=5000),
        "light.tv_strip": state("light.tv_strip", "LED strip", "on", ["hs", "white"], brightness=178, rgb_color=[160, 90, 255], hs_color=[265.5, 64.7]),
        "light.kitchen_counter": state("light.kitchen_counter", "Kitchen counter", "off", ["brightness"]),
        "light.garden_path": state("light.garden_path", "Garden path", "off", ["onoff"]),
        "light.bedside": state("light.bedside", "Bedside lamp", "unavailable", ["color_temp", "xy"]),
        "light.dining_table": state("light.dining_table", "Dining table", "on", ["color_temp"], brightness=140, color_temp_kelvin=2700),
        "light.wall_dimmer_status_led": state("light.wall_dimmer_status_led", "Wall dimmer status LED", "on", ["brightness"], brightness=20),
        "light.old_bulb": state("light.old_bulb", "Old bulb", "off", ["onoff"]),
        "switch.floor_plug": {"entity_id": "switch.floor_plug", "state": "on", "attributes": {"friendly_name": "Floor plug"}},
        "climate.living_room": {"entity_id": "climate.living_room", "state": "heat", "attributes": {
            "friendly_name": "Living room", "hvac_modes": ["off", "heat", "auto"], "current_temperature": 20.5, "temperature": 21.5,
            "min_temp": 7, "max_temp": 30, "target_temp_step": 0.5, "hvac_action": "heating",
            "preset_mode": "comfort", "preset_modes": ["comfort", "eco", "away"], "supported_features": CLIMATE_TARGET | CLIMATE_PRESET}},
        "climate.bedroom": {"entity_id": "climate.bedroom", "state": "off", "attributes": {
            "friendly_name": "Bedroom", "hvac_modes": ["off", "heat"], "current_temperature": 18.2, "temperature": 17,
            "min_temp": 5, "max_temp": 25, "hvac_action": "off", "supported_features": CLIMATE_TARGET}},
        "climate.bathroom": {"entity_id": "climate.bathroom", "state": "unavailable", "attributes": {"friendly_name": "Bathroom"}},
        "climate.old_valve": {"entity_id": "climate.old_valve", "state": "off", "attributes": {"friendly_name": "Old valve"}},
        "sensor.living_room_temperature": {"entity_id": "sensor.living_room_temperature", "state": "21.3", "attributes": {
            "friendly_name": "Living room temperature", "unit_of_measurement": "°C", "device_class": "temperature", "state_class": "measurement"}},
        # The device class only in the registry, as some integrations leave it.
        "sensor.bedroom_temperature": {"entity_id": "sensor.bedroom_temperature", "state": "18.9", "attributes": {
            "friendly_name": "Bedroom temperature", "unit_of_measurement": "°C", "state_class": "measurement"}},
        "sensor.living_room_humidity": {"entity_id": "sensor.living_room_humidity", "state": "48", "attributes": {
            "friendly_name": "Living room humidity", "unit_of_measurement": "%", "device_class": "humidity", "state_class": "measurement"}},
        "sensor.outdoor_temperature": {"entity_id": "sensor.outdoor_temperature", "state": "6.8", "attributes": {
            "friendly_name": "Outdoor temperature", "unit_of_measurement": "°C", "device_class": "temperature", "state_class": "measurement"}},
        "sensor.house_energy": {"entity_id": "sensor.house_energy", "state": "18342.6", "attributes": {
            "friendly_name": "House energy", "unit_of_measurement": "kWh", "device_class": "energy", "state_class": "total_increasing"}},
        "sensor.washing_machine_programme": {"entity_id": "sensor.washing_machine_programme", "state": "Cotton 40", "attributes": {
            "friendly_name": "Washing machine programme"}},
        "sensor.home_server_cpu_temperature": {"entity_id": "sensor.home_server_cpu_temperature", "state": "52", "attributes": {
            "friendly_name": "Home server CPU temperature", "unit_of_measurement": "°C", "device_class": "temperature"}},
    }
    return entities, devices, areas, states
