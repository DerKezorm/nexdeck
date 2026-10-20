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
from ..models import Integration, Page
from ..schemas import HomeLayoutBody
from ..services import hass_registry
from ..services import home as home_service
from ..services.collector import collector
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
    by_rid = {light["rid"]: light for light in offered if light["rid"]}
    by_entity = {light["entity_id"]: light for light in offered}
    for element in lamps:
        found = by_rid.get(element["rid"]) or by_entity.get(element["entity_id"])
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
    hub.publish(board_topic(board.id), "board", {"id": board.id, "changed": True})
    logger.info("Home page %r of board %r arranged by %s: %d element(s).", page.name, board.slug, user.username, len(layout["elements"]))
    return {"layout": layout, "version": page.layout_version}
