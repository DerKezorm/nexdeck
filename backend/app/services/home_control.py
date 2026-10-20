"""Switching what stands on a home page, and telling open pages when it changed.

The browser names an element of a page and what it wants, never a service and
never an entity. The server reads the element from the page, finds the lamp in
Home Assistant by its registry id, and calls one of ``SERVICES`` for exactly
that entity. Whatever else Home Assistant offers (a script, an alarm panel, a
lock) cannot be reached through a home page, whatever a browser sends.

Changes travel back as a ``home`` event on the board's stream, for the lamp
switched here and for the one switched at the wall: the WebSocket listener
(``hass_ws``) hands every state change to ``touched``.
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
from . import hass_registry
from .sse import board_topic, hub

#: The only services a home page calls, with the only data each may carry; anything else is
#: refused before Home Assistant hears of it.
SERVICES: dict[tuple[str, str], frozenset[str]] = {
    ("light", "turn_on"): frozenset({"brightness_pct", "color_temp_kelvin", "hs_color"}),
    ("light", "turn_off"): frozenset(),
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


# ---------------------------------------------------------------------------
# Telling open pages
# ---------------------------------------------------------------------------


class HomeLive:
    """Which lamp stands on which home page, and a ``home`` event when one of them changes."""

    def __init__(self) -> None:
        #: integration -> (registry it was built with, when, entity -> [(board, page, element)])
        self._map: dict[int, tuple[Any, float, dict[str, list[tuple[int, int, str]]]]] = {}
        #: (board, page) -> element -> how it stands, waiting to go out
        self._pending: dict[tuple[int, int], dict[str, dict[str, Any]]] = {}
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

    def _watchers(self, integration_id: int, cache: dict[str, Any]) -> dict[str, list[tuple[int, int, str]]]:
        """Read once per integration and kept until a page or the registry changes.

        A lamp is listed under the entity id it was placed with and under the
        one its registry id has now, so a lamp renamed in Home Assistant keeps
        its page current.
        """
        registry = cache.get("hass_registry")
        kept = self._map.get(integration_id)
        now = time.monotonic()
        if kept is not None and kept[0] is registry and now - kept[1] < MAP_SECONDS:
            return kept[2]
        renamed = {str(entry.get("id")): str(entry.get("entity_id")) for entry in (registry[1] if registry else []) if entry.get("id")}
        found: dict[str, list[tuple[int, int, str]]] = {}
        with db_session() as db:
            for page in db.scalars(select(Page).where(Page.kind == "home")):
                home = page.home or {}
                if home.get("integration_id") != integration_id:
                    continue
                for element in home.get("elements") or []:
                    if not isinstance(element, dict) or element.get("type") != "light":
                        continue
                    spot = (page.board_id, page.id, str(element.get("id")))
                    for entity_id in {str(element.get("entity_id") or ""), renamed.get(str(element.get("rid")), "")} - {""}:
                        found.setdefault(entity_id, []).append(spot)
        self._map[integration_id] = (registry, now, found)
        return found

    def touched(self, integration_id: int, cache: dict[str, Any], entity_id: str, state: dict[str, Any]) -> None:
        """A lamp changed: the pages it stands on hear of it, at most every ``PUSH_INTERVAL``."""
        if not entity_id.startswith("light."):
            return
        spots = self._watchers(integration_id, cache).get(entity_id)
        if not spots:
            return
        stands = {**hass_registry.light_state(state), "missing": False}
        for board_id, page_id, element_id in spots:
            key = (board_id, page_id)
            self._pending.setdefault(key, {})[element_id] = stands
            self._schedule(key)

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
        lights = self._pending.pop(key, None)
        if not lights:
            return
        self._last[key] = time.monotonic()
        board_id, page_id = key
        hub.publish(board_topic(board_id), "home", {"page_id": page_id, "lights": lights})


home_live = HomeLive()
