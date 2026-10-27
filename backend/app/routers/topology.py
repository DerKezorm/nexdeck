"""Topology pages: the network plan of a UniFi connection, and who stands where on it."""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Request, status

from ..adapters.base import AdapterError
from ..deps import (
    CurrentUser,
    DbSession,
    OptionalUser,
    board_for_viewer_id,
    error,
    kiosk_from_request,
    read_only_token,
    require_board_id,
)
from ..models import Integration, Page
from ..schemas import TopologyLayoutBody
from ..services import topology as topology_service
from ..services.collector import collector
from ..services.sse import board_topic, hub

router = APIRouter(prefix="/api/v1", tags=["topology"])

logger = logging.getLogger("nexdeck.topology")


def _topology_page(db: DbSession, page_id: int) -> Page:
    page = db.get(Page, page_id)
    if page is None or page.kind != "topology":
        raise error("not_found", "There is no such topology page.", status.HTTP_404_NOT_FOUND)
    return page


def _problem(code: str, message: str, hint: str = "") -> dict:
    return {"code": code, "message": message, "hint": hint}


@router.get("/pages/{page_id}/topology", summary="Read the network plan of a topology page")
async def read_topology(page_id: int, request: Request, user: OptionalUser, db: DbSession) -> dict:
    """The plan as the console reports it, the page's arrangement, and what went wrong if anything.

    A failure at the console is an answer, not an error: the page keeps its
    arrangement and says what the console said, the way a card does.
    """
    page = _topology_page(db, page_id)
    board_for_viewer_id(db, page.board_id, user, kiosk_from_request(request, db))
    stored = page.topology or {}
    layout = topology_service.clean_layout(stored, stored.get("integration_id"))
    answer: dict = {"layout": layout, "version": page.layout_version or 0, "data": None, "problem": None}
    integration = db.get(Integration, layout["integration_id"]) if layout["integration_id"] else None
    if integration is None or integration.kind != "unifi":
        answer["problem"] = _problem("no_integration", "The UniFi connection of this page is gone.",
                                     "Delete the page and add it again with another connection.")
        return answer
    if not integration.enabled:
        answer["problem"] = _problem("integration_disabled", f"The connection {integration.name!r} is switched off.",
                                     "Switch it on under Settings, Connections.")
        return answer
    try:
        adapter, config, ctx = await collector.resolve_integration(integration.id)
        data = await topology_service.snapshot(adapter, config, ctx, demo=collector.is_demo(integration))
    except AdapterError as failure:
        answer["problem"] = _problem(failure.code, failure.message, failure.hint)
        return answer
    except Exception:  # noqa: BLE001 - the page says so instead of going blank
        logger.exception("Reading the plan of page %s failed.", page_id)
        answer["problem"] = _problem("unexpected", "Reading the console failed unexpectedly.", "The server log has the details.")
        return answer
    if not layout["seeded"]:
        # The first look at a new page decides what stands on it: every network
        # device, or the gateway only. Later arrivals go to "found", never
        # onto the plan by themselves.
        layout = topology_service.seed(layout, data)
        # A token that only reads sees the first arrangement and leaves it unwritten.
        if not read_only_token(request):
            page.topology = layout
            db.commit()
    answer["layout"] = layout
    answer["data"] = topology_service.with_ages(data, time.time())
    return answer


@router.put("/pages/{page_id}/topology", summary="Save who stands where on a topology page")
def save_topology(page_id: int, body: TopologyLayoutBody, user: CurrentUser, db: DbSession) -> dict:
    """Refused when it started from an older version, like the card layouts (``put_layouts``)."""
    page = _topology_page(db, page_id)
    board, _ = require_board_id(db, page.board_id, user, "edit")
    if body.version is not None and body.version != (page.layout_version or 0):
        raise error(
            "layout_moved_on",
            "Somebody else changed this page while you were arranging it. Reload to see their version.",
            status.HTTP_409_CONFLICT,
        )
    stored = page.topology or {}
    layout = topology_service.clean_layout(
        {**stored, "placed": body.placed, "clients": body.clients, "hidden": body.hidden, "positions": body.positions, "seeded": True},
        stored.get("integration_id"),
    )
    page.topology = layout
    page.layout_version = (page.layout_version or 0) + 1
    db.commit()
    hub.publish(board_topic(board.id), "topology", {"page_id": page.id, "version": page.layout_version})
    return {"layout": layout, "version": page.layout_version}
