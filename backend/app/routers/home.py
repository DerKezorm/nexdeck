"""Home pages: a free surface of Home Assistant controls, and what stands where on it."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request, status

from ..adapters.base import AdapterError
from ..deps import (
    CurrentUser,
    DbSession,
    OptionalUser,
    board_for_viewer_id,
    error,
    kiosk_from_request,
    require_board_id,
    require_integration,
)
from ..models import ActionLog, Integration, Page
from ..schemas import HomeLayoutBody, HomeSwitchBody
from ..services import hass_registry, home_control
from ..services import home as home_service
from ..services.collector import collector
from ..services.home_control import home_live
from ..services.notify import emit
from ..services.sse import board_topic, hub

router = APIRouter(prefix="/api/v1", tags=["home"])

logger = logging.getLogger("nexdeck.home")


def _home_page(db: DbSession, page_id: int) -> Page:
    page = db.get(Page, page_id)
    if page is None or page.kind != "home":
        raise error("not_found", "There is no such home page.", status.HTTP_404_NOT_FOUND)
    return page


def _problem(code: str, message: str, hint: str = "") -> dict:
    return {"code": code, "message": message, "hint": hint}


def _connection_problem(integration: Integration | None) -> dict | None:
    """What keeps a page from its connection, or None when it may ask it."""
    if integration is None or integration.kind != "homeassistant":
        return _problem("no_integration", "The Home Assistant connection of this page is gone.",
                        "Delete the page and add it again with another connection.")
    if not integration.enabled:
        return _problem("integration_disabled", f"The connection {integration.name!r} is switched off.",
                        "Switch it on under Settings, Connections.")
    return None


async def _offered(integration: Integration) -> list[dict[str, Any]]:
    _adapter, config, ctx = await collector.resolve_integration(integration.id)
    return await hass_registry.lights(config, ctx.cache, demo=collector.is_demo(integration))


def _find(offered: list[dict[str, Any]], element: dict[str, Any]) -> dict[str, Any] | None:
    """The lamp an element stands for: by its registry id, else by the entity id it was placed with."""
    for light in offered:
        if light["rid"] and light["rid"] == element["rid"]:
            return light
    return next((light for light in offered if light["entity_id"] == element["entity_id"]), None)


@router.get("/pages/{page_id}/home", summary="Read what stands on a home page")
async def read_home(page_id: int, request: Request, user: OptionalUser, db: DbSession) -> dict:
    """The arrangement, how its lamps stand, and what is wrong with the connection if anything.

    A connection that is gone, switched off or not answering is an answer, not
    an error: the page keeps what stands on it and says why its controls are
    quiet. A lamp is found by its registry id first, so renaming it in Home
    Assistant does not take it off the page.
    """
    page = _home_page(db, page_id)
    board_for_viewer_id(db, page.board_id, user, kiosk_from_request(request, db))
    stored = page.home or {}
    layout = home_service.clean_layout(stored, stored.get("integration_id"))
    answer: dict = {"layout": layout, "version": page.layout_version or 0, "problem": None, "lights": {}}
    integration = db.get(Integration, layout["integration_id"]) if layout["integration_id"] else None
    answer["problem"] = _connection_problem(integration)
    lamps = [element for element in layout["elements"] if element["type"] == "light"]
    if answer["problem"] is not None or not lamps or integration is None:
        return answer
    try:
        offered = await _offered(integration)
    except AdapterError as failure:
        answer["problem"] = _problem(failure.code, failure.message, failure.hint)
        return answer
    for element in lamps:
        found = _find(offered, element)
        # Gone, hidden or disabled in Home Assistant since it was placed: the page says so.
        answer["lights"][element["id"]] = {**found, "missing": False} if found else {"missing": True}
    return answer


@router.get("/pages/{page_id}/home/lights", summary="The lamps a home page can offer")
async def offer_lights(page_id: int, user: CurrentUser, db: DbSession) -> dict:
    """Every lamp of the page's connection worth putting on a wall (``hass_registry.pick_lights``).

    For those who arrange the page only, and only on a connection they may
    build on: the list names every lamp in the house.
    """
    page = _home_page(db, page_id)
    require_board_id(db, page.board_id, user, "edit")
    stored = page.home or {}
    integration = db.get(Integration, stored["integration_id"]) if stored.get("integration_id") else None
    problem = _connection_problem(integration)
    if problem is not None or integration is None:
        return {"lights": [], "problem": problem}
    require_integration(db, integration.id, user)
    try:
        return {"lights": await _offered(integration), "problem": None}
    except AdapterError as failure:
        return {"lights": [], "problem": _problem(failure.code, failure.message, failure.hint)}


@router.post("/pages/{page_id}/home/lights/{element_id}", summary="Switch a lamp on a home page")
async def switch_light(page_id: int, element_id: str, body: HomeSwitchBody, request: Request, user: OptionalUser, db: DbSession) -> dict:
    """Needs the act permission on the board, or a display that allows actions, like the actions of a card.

    The browser names the element and on or off. Which entity that is, and
    which service, the server decides from the page and Home Assistant's
    registry; only ``home_control.SERVICES`` are ever called. Every call that
    reaches Home Assistant goes into the action log, a failed one too.
    """
    page = _home_page(db, page_id)
    kiosk = kiosk_from_request(request, db)
    board, permission = board_for_viewer_id(db, page.board_id, user, kiosk)
    if permission not in ("act", "owner"):
        raise error("forbidden", "You may look at this page, but not switch anything on it.", status.HTTP_403_FORBIDDEN)
    stored = page.home or {}
    layout = home_service.clean_layout(stored, stored.get("integration_id"))
    element = next((item for item in layout["elements"] if item["id"] == element_id and item["type"] == "light"), None)
    if element is None:
        raise error("not_found", "There is no such lamp on this page.", status.HTTP_404_NOT_FOUND)
    integration = db.get(Integration, layout["integration_id"]) if layout["integration_id"] else None
    problem = _connection_problem(integration)
    if problem is not None or integration is None:
        raise error(problem["code"] if problem else "no_integration", problem["message"] if problem else "", status.HTTP_409_CONFLICT)
    try:
        lamp = _find(await _offered(integration), element)
    except AdapterError as failure:
        raise error(failure.code, failure.message, status.HTTP_502_BAD_GATEWAY) from failure
    if lamp is None:
        raise error("lamp_missing", "This lamp is no longer in Home Assistant, or it is hidden there.", status.HTTP_409_CONFLICT)
    if lamp["unavailable"]:
        raise error("lamp_unavailable", f"Home Assistant cannot reach {lamp['name']} right now.", status.HTTP_409_CONFLICT)

    domain, service = home_control.service_for(body.on)
    entity_id = lamp["entity_id"]
    actor = user.username if user else f"kiosk:{kiosk.name}" if kiosk else "?"
    _adapter, config, ctx = await collector.resolve_integration(integration.id)
    ok, changed = True, []
    try:
        if collector.is_demo(integration):
            switched = home_control.switch_demo(ctx.cache, entity_id, body.on)
            changed = [switched] if switched else []
            message = f"Demo mode: {domain}.{service} for {entity_id}."
        else:
            changed = await home_control.call(config, ctx, domain, service, entity_id)
            message = f"{domain}.{service} called for {entity_id}."
    except AdapterError as failure:
        ok, message, code = False, failure.message, failure.code
    db.add(ActionLog(user_id=user.id if user else None, actor=actor, widget_id=None, integration_id=integration.id,
                     action=f"{domain}.{service}", params={"entity_id": entity_id, "page_id": page.id}, ok=ok, message=message[:400]))
    db.commit()
    title = f"{domain}.{service} on {lamp['name']}"
    if not ok:
        emit("action_failed", f"{title} failed", message, level="warn", user_ids=[user.id] if user else None, integration_id=integration.id)
        logger.warning("Lamp %s on home page %r of board %r could not be switched by %s: %s", entity_id, page.name, board.slug, actor, message)
        raise error(code, message, status.HTTP_502_BAD_GATEWAY)
    logger.info("Lamp %s on home page %r of board %r switched by %s: %s", entity_id, page.name, board.slug, actor, message)
    # No "action_done" notice, unlike a card's action: the lamp on the page is the answer, and a bell
    # that rang at every light switch would drown out what it is for. A failure does ring (above).
    state = next((item for item in changed if item.get("entity_id") == entity_id), None)
    if state is None:
        # Home Assistant names only what changed; a lamp that was on already is not in the list.
        return {"ok": True, "confirmed": False, "light": {**lamp, "missing": False}}
    live = ctx.cache.get("hass_states")
    if isinstance(live, dict):
        live[entity_id] = state
    # Every other page this lamp stands on, open in another browser, hears of it too.
    home_live.touched(integration.id, ctx.cache, entity_id, state)
    return {"ok": True, "confirmed": True, "light": {**lamp, **hass_registry.light_state(state), "missing": False}}


@router.put("/pages/{page_id}/home", summary="Save what stands where on a home page")
def save_home(page_id: int, body: HomeLayoutBody, user: CurrentUser, db: DbSession) -> dict:
    """Refused when it started from an older version, like the card layouts (``put_layouts``)."""
    page = _home_page(db, page_id)
    board, _ = require_board_id(db, page.board_id, user, "edit")
    if body.version is not None and body.version != (page.layout_version or 0):
        raise error(
            "layout_moved_on",
            "Somebody else changed this page while you were arranging it. Reload to see their version.",
            status.HTTP_409_CONFLICT,
        )
    stored = page.home or {}
    # The connection stays the one the page was made with, whatever the browser sends.
    layout = home_service.clean_layout({"elements": body.elements}, stored.get("integration_id"))
    page.home = layout
    page.layout_version = (page.layout_version or 0) + 1
    db.commit()
    home_live.forget(stored.get("integration_id"))
    hub.publish(board_topic(board.id), "board", {"id": board.id, "changed": True})
    logger.info("Home page %r of board %r arranged by %s: %d element(s).", page.name, board.slug, user.username, len(layout["elements"]))
    return {"layout": layout, "version": page.layout_version}
