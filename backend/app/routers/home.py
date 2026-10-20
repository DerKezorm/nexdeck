"""Home pages: a free surface of Home Assistant controls, and what stands where on it."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request, status

from ..deps import (
    CurrentUser,
    DbSession,
    OptionalUser,
    board_for_viewer_id,
    error,
    kiosk_from_request,
    require_board_id,
)
from ..models import Integration, Page
from ..schemas import HomeLayoutBody
from ..services import home as home_service
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


@router.get("/pages/{page_id}/home", summary="Read what stands on a home page")
def read_home(page_id: int, request: Request, user: OptionalUser, db: DbSession) -> dict:
    """The arrangement, and what is wrong with the connection if anything.

    A connection that is gone or switched off is an answer, not an error: the
    page keeps what stands on it and says why its controls are quiet.
    """
    page = _home_page(db, page_id)
    board_for_viewer_id(db, page.board_id, user, kiosk_from_request(request, db))
    stored = page.home or {}
    layout = home_service.clean_layout(stored, stored.get("integration_id"))
    answer: dict = {"layout": layout, "version": page.layout_version or 0, "problem": None}
    integration = db.get(Integration, layout["integration_id"]) if layout["integration_id"] else None
    if integration is None or integration.kind != "homeassistant":
        answer["problem"] = _problem("no_integration", "The Home Assistant connection of this page is gone.",
                                     "Delete the page and add it again with another connection.")
    elif not integration.enabled:
        answer["problem"] = _problem("integration_disabled", f"The connection {integration.name!r} is switched off.",
                                     "Switch it on under Settings, Connections.")
    return answer


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
