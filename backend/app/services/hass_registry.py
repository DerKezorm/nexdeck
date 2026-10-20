"""What Home Assistant has to offer a home page: its lights, as a person would pick them.

Home Assistant knows thousands of entities; a house of 232 lamps had 6262 in
its entity registry (measured 20.10.2026, Home Assistant 2026.10). A home page
offers only what makes sense to put on a wall, and decides that here, on the
server, before anything reaches a browser:

* lights only, so far; the other domains follow one at a time,
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

import json
import time
from typing import Any

from ..adapters.base import AdapterError, AuthFailed, base_url

#: How long the registries are kept; they change when somebody edits the house.
REGISTRY_SECONDS = 60
#: The colour modes a lamp mixes colours in; ``white`` comes with one of them.
COLOUR_MODES = {"hs", "xy", "rgb", "rgbw", "rgbww"}


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
    return {
        "on": on,
        "unavailable": value in (None, "unavailable", "unknown"),
        "pct": max(1, pct) if pct is not None else None,
        "rgb": [int(channel) for channel in rgb][:3] if on and isinstance(rgb, (list, tuple)) and len(rgb) >= 3 else None,
        "kelvin": int(kelvin) if on and isinstance(kelvin, (int, float)) else None,
        "dims": bool(modes - {"onoff"}),
        "temperature": "color_temp" in modes,
        "colour": bool(modes & COLOUR_MODES),
    }


def pick_lights(entities: list[dict[str, Any]], devices: list[dict[str, Any]], areas: list[dict[str, Any]],
                states: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """The lamps worth offering, with their name, room and device, sorted by name."""
    area_names = {area.get("area_id"): area.get("name") or "" for area in areas}
    by_device = {device.get("id"): device for device in devices}
    lights: list[dict[str, Any]] = []
    for entry in entities:
        entity_id = str(entry.get("entity_id") or "")
        if not entity_id.startswith("light.") or entry.get("entity_category") or entry.get("hidden_by") or entry.get("disabled_by"):
            continue
        state = states.get(entity_id)
        if state is None:
            continue
        device = by_device.get(entry.get("device_id")) or {}
        area_id = entry.get("area_id") or device.get("area_id")
        attributes = state.get("attributes") or {}
        name = attributes.get("friendly_name") or entry.get("name") or entry.get("original_name") or entity_id
        lights.append({
            "rid": str(entry.get("id") or ""),
            "entity_id": entity_id,
            "name": str(name),
            "area": area_names.get(area_id, "") if area_id else "",
            "device": str(device.get("name_by_user") or device.get("name") or ""),
            "group": entry.get("platform") == "group",
            **light_state(state),
        })
    return sorted(lights, key=lambda light: (light["name"].casefold(), light["entity_id"]))


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


async def lights(config: dict[str, Any], cache: dict[str, Any], *, demo: bool = False, now: float | None = None) -> list[dict[str, Any]]:
    """The lamps of one connection, as ``pick_lights`` offers them.

    The registries are kept for a minute in the connection's cache. The states
    come from the live listener when it has them, so a lamp switched a moment
    ago shows how it stands now.
    """
    if demo:
        return pick_lights(*demo_registry())
    now = time.monotonic() if now is None else now
    kept = cache.get("hass_registry")
    live = cache.get("hass_states")
    if kept is None or kept[0] < now:
        commands: list[dict[str, Any]] = [
            {"type": "config/entity_registry/list"},
            {"type": "config/device_registry/list"},
            {"type": "config/area_registry/list"},
        ]
        if not isinstance(live, dict) or not live:
            commands.append({"type": "get_states"})
        answers = await _ask(config, commands)
        fetched = {state["entity_id"]: state for state in answers[3] or []} if len(answers) > 3 else {}
        kept = (now + REGISTRY_SECONDS, answers[0] or [], answers[1] or [], answers[2] or [], fetched)
        cache["hass_registry"] = kept
    _until, entities, devices, areas, fetched = kept
    states = live if isinstance(live, dict) and live else fetched
    return pick_lights(entities, devices, areas, states)


# ---------------------------------------------------------------------------
# The demo house
# ---------------------------------------------------------------------------


def demo_registry() -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """A made-up house, shaped like a real registry, for demo connections and tests."""
    areas = [{"area_id": "living", "name": "Living room"}, {"area_id": "kitchen", "name": "Kitchen"},
             {"area_id": "garden", "name": "Garden"}, {"area_id": "bedroom", "name": "Bedroom"}]
    devices = [{"id": "d-floor", "name": "Floor lamp", "area_id": "living"}, {"id": "d-ceiling", "name": "Ceiling light", "area_id": "living"},
               {"id": "d-tv", "name": "LED strip", "area_id": "living"}, {"id": "d-counter", "name": "Counter light", "area_id": "kitchen"},
               {"id": "d-path", "name": "Path lights", "area_id": "garden"}, {"id": "d-bed", "name": "Bedside lamp", "area_id": "bedroom"},
               {"id": "d-switch", "name": "Wall dimmer", "area_id": "kitchen"}]

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
    ]

    def state(entity_id: str, name: str, value: str, modes: list[str], **attributes: Any) -> dict[str, Any]:
        return {"entity_id": entity_id, "state": value, "attributes": {"friendly_name": name, "supported_color_modes": modes, **attributes}}

    states = {
        "light.floor_lamp": state("light.floor_lamp", "Floor lamp", "on", ["color_temp", "xy"], brightness=158, color_temp_kelvin=2400, rgb_color=[255, 167, 87]),
        "light.ceiling": state("light.ceiling", "Ceiling light", "on", ["color_temp"], brightness=204, color_temp_kelvin=3000),
        "light.tv_strip": state("light.tv_strip", "LED strip", "on", ["hs", "white"], brightness=178, rgb_color=[160, 90, 255]),
        "light.kitchen_counter": state("light.kitchen_counter", "Kitchen counter", "off", ["brightness"]),
        "light.garden_path": state("light.garden_path", "Garden path", "off", ["onoff"]),
        "light.bedside": state("light.bedside", "Bedside lamp", "unavailable", ["color_temp", "xy"]),
        "light.dining_table": state("light.dining_table", "Dining table", "on", ["color_temp"], brightness=140, color_temp_kelvin=2700),
        "light.wall_dimmer_status_led": state("light.wall_dimmer_status_led", "Wall dimmer status LED", "on", ["brightness"], brightness=20),
        "light.old_bulb": state("light.old_bulb", "Old bulb", "off", ["onoff"]),
        "switch.floor_plug": {"entity_id": "switch.floor_plug", "state": "on", "attributes": {"friendly_name": "Floor plug"}},
    }
    return entities, devices, areas, states
