"""Widgets: create, change, refresh, act, reachability checks and history."""

from __future__ import annotations

from fastapi import APIRouter, Request, status
from sqlalchemy import select

from ..adapters import split_widget_kind
from ..adapters.base import AdapterError
from ..deps import (
    CurrentUser,
    DbSession,
    OptionalUser,
    board_for_viewer,
    error,
    kiosk_from_request,
    require_board,
)
from ..models import HealthCheck, Integration, Page, Widget
from ..schemas import ActionBody, HealthBody, WidgetCreate, WidgetPatch, WidgetPreview
from ..services import health as health_service
from ..services import history
from ..services.boards import place_widget, remove_from_layouts, widget_view
from ..services.collector import collector
from ..services.notify import emit
from ..services.sse import board_topic, hub
from ..services.state import live

router = APIRouter(prefix="/api/v1", tags=["widgets"])


def _widget(db: DbSession, widget_id: int) -> tuple[Widget, Page]:
    widget = db.get(Widget, widget_id)
    if widget is None:
        raise error("not_found", "There is no such widget.", status.HTTP_404_NOT_FOUND)
    page = db.get(Page, widget.page_id)
    assert page is not None
    return widget, page


def _validate_kind(db: DbSession, kind: str, integration_id: int | None) -> None:
    try:
        adapter, _ = split_widget_kind(kind)
    except KeyError as failure:
        raise error("unknown_kind", f"There is no widget kind {kind!r}.") from failure
    if integration_id is not None:
        integration = db.get(Integration, integration_id)
        if integration is None:
            raise error("not_found", "There is no such integration.", status.HTTP_404_NOT_FOUND)
        if integration.kind != adapter.kind:
            raise error("kind_mismatch", f"A {kind} widget needs a {adapter.label} integration, not {integration.kind}.")


@router.post("/pages/{page_id}/widgets", status_code=status.HTTP_201_CREATED, summary="Add a widget to a page")
def create_widget(page_id: int, body: WidgetCreate, user: CurrentUser, db: DbSession) -> dict:
    page = db.get(Page, page_id)
    if page is None:
        raise error("not_found", "There is no such page.", status.HTTP_404_NOT_FOUND)
    board, _ = require_board(db, str(page.board_id), user, "edit")
    _validate_kind(db, body.kind, body.integration_id)
    adapter, widget_kind = split_widget_kind(body.kind)
    widget_type = adapter.widget(widget_kind)
    widget = Widget(page_id=page.id, kind=body.kind, title=body.title.strip() or widget_type.label, icon=body.icon or (adapter.icon if adapter.kind != "core" else ""),
                    link=body.link.strip(), integration_id=body.integration_id, options=body.options, refresh_seconds=body.refresh_seconds)
    db.add(widget)
    db.flush()
    size = (body.w or widget_type.default_size[0], body.h or widget_type.default_size[1])
    place_widget(page, widget.id, size, widget_type.min_size)
    health_service.ensure_check_for_widget(db, widget)
    db.commit()
    db.refresh(widget)
    collector.schedule(widget.id)
    hub.publish(board_topic(board.id), "board", {"id": board.id, "changed": True})
    return {"widget": widget_view(db, widget), "layouts": page.layouts}


@router.patch("/widgets/{widget_id}", summary="Change a widget's settings")
def patch_widget(widget_id: int, body: WidgetPatch, user: CurrentUser, db: DbSession) -> dict:
    widget, page = _widget(db, widget_id)
    board, _ = require_board(db, str(page.board_id), user, "edit")
    if body.integration_id is not None or body.clear_integration:
        _validate_kind(db, widget.kind, None if body.clear_integration else body.integration_id)
        widget.integration_id = None if body.clear_integration else body.integration_id
    if body.title is not None:
        widget.title = body.title.strip()
    if body.icon is not None:
        widget.icon = body.icon
    if body.link is not None:
        widget.link = body.link.strip()
    if body.options is not None:
        widget.options = body.options
    if body.refresh_seconds is not None:
        widget.refresh_seconds = body.refresh_seconds
    if body.page_id is not None and body.page_id != page.id:
        target = db.get(Page, body.page_id)
        if target is None or target.board_id != board.id:
            raise error("bad_page", "Widgets move between pages of the same board only.")
        remove_from_layouts(page, widget.id)
        widget.page_id = target.id
        adapter, kind = split_widget_kind(widget.kind)
        place_widget(target, widget.id, adapter.widget(kind).default_size, adapter.widget(kind).min_size)
    health_service.ensure_check_for_widget(db, widget)
    db.commit()
    db.refresh(widget)
    collector.schedule(widget.id)
    if widget.health_check is not None:
        health_service.health.reset(widget.health_check.id)
    hub.publish(board_topic(board.id), "board", {"id": board.id, "changed": True})
    return widget_view(db, widget)


@router.delete("/widgets/{widget_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Remove a widget")
def delete_widget(widget_id: int, user: CurrentUser, db: DbSession) -> None:
    widget, page = _widget(db, widget_id)
    board, _ = require_board(db, str(page.board_id), user, "edit")
    remove_from_layouts(page, widget.id)
    history.forget_widget(db, widget.id)
    db.delete(widget)
    db.commit()
    collector.unschedule(widget_id)
    hub.publish(board_topic(board.id), "board", {"id": board.id, "changed": True})


@router.post("/widgets/{widget_id}/preview", summary="Fetch a widget's data with draft settings, without saving")
async def preview_widget(widget_id: int, body: WidgetPreview, user: CurrentUser, db: DbSession) -> dict:
    """The settings sheet shows what a change would look like before it is saved."""
    widget, page = _widget(db, widget_id)
    require_board(db, str(page.board_id), user, "edit")
    if body.integration_id is not None:
        _validate_kind(db, widget.kind, body.integration_id)
    if body.clear_integration:
        integration_id = None
    elif body.integration_id is not None:
        integration_id = body.integration_id
    else:
        integration_id = widget.integration_id
    data = await collector.preview(widget_id, body.options, integration_id)
    return data.model_dump()


@router.post("/widgets/{widget_id}/refresh", summary="Fetch a widget's data right now")
async def refresh_widget(widget_id: int, request: Request, user: OptionalUser, db: DbSession) -> dict:
    widget, page = _widget(db, widget_id)
    board_for_viewer(db, str(page.board_id), user, kiosk_from_request(request, db))
    data = await collector.refresh_now(widget_id)
    return data.model_dump() if data else {}


@router.get("/widgets/{widget_id}/data", summary="Read a widget's latest data")
def widget_data(widget_id: int, request: Request, user: OptionalUser, db: DbSession) -> dict:
    widget, page = _widget(db, widget_id)
    board_for_viewer(db, str(page.board_id), user, kiosk_from_request(request, db))
    data = live.get(widget_id)
    return data.model_dump() if data else {}


@router.post("/widgets/{widget_id}/actions/{action_id}", summary="Run a widget action")
async def run_action(widget_id: int, action_id: str, body: ActionBody, request: Request, user: OptionalUser, db: DbSession) -> dict:
    """Needs the act permission on the board, or a kiosk token that allows actions. Every call is logged."""
    widget, page = _widget(db, widget_id)
    kiosk = kiosk_from_request(request, db)
    board, permission = board_for_viewer(db, str(page.board_id), user, kiosk)
    if permission not in ("act", "owner"):
        raise error("forbidden", "You may look at this board, but not act on it.", status.HTTP_403_FORBIDDEN)
    actor = user.username if user else f"kiosk:{kiosk.name}" if kiosk else "?"
    try:
        message = await collector.run_action(widget_id, action_id, body.params, actor=actor, user_id=user.id if user else None)
    except AdapterError as failure:
        emit("action_failed", f"{action_id} on {widget.title} failed", failure.message, level="warn", user_ids=[user.id] if user else None)
        raise error(failure.code, failure.message) from failure
    return {"ok": True, "message": message}


# -- reachability checks -----------------------------------------------------


@router.get("/widgets/{widget_id}/health", summary="Read a widget's reachability check")
def get_health(widget_id: int, request: Request, user: OptionalUser, db: DbSession) -> dict:
    widget, page = _widget(db, widget_id)
    board_for_viewer(db, str(page.board_id), user, kiosk_from_request(request, db))
    if widget.health_check is None:
        return {}
    payload = health_service.check_payload(widget.health_check)
    payload["bars"] = health_service.uptime_bars(db, widget.id, health_service.bars_window(widget.options))
    return payload


@router.put("/widgets/{widget_id}/health", summary="Set a widget's reachability check")
def put_health(widget_id: int, body: HealthBody, user: CurrentUser, db: DbSession) -> dict:
    widget, page = _widget(db, widget_id)
    require_board(db, str(page.board_id), user, "edit")
    check = widget.health_check or HealthCheck(widget_id=widget.id, target=body.target)
    check.kind = body.kind
    check.target = body.target.strip()
    check.interval_seconds = body.interval_seconds
    check.timeout_seconds = body.timeout_seconds
    check.expect_status = body.expect_status
    check.insecure = body.insecure
    check.enabled = body.enabled
    db.add(check)
    db.commit()
    health_service.health.reset(check.id)
    return health_service.check_payload(check)


@router.delete("/widgets/{widget_id}/health", status_code=status.HTTP_204_NO_CONTENT, summary="Remove a widget's reachability check")
def delete_health(widget_id: int, user: CurrentUser, db: DbSession) -> None:
    widget, page = _widget(db, widget_id)
    require_board(db, str(page.board_id), user, "edit")
    if widget.health_check is not None:
        db.delete(widget.health_check)
        db.commit()


# -- history -----------------------------------------------------------------


@router.get("/widgets/{widget_id}/history", summary="Read a widget's metric history")
def widget_history(widget_id: int, request: Request, user: OptionalUser, db: DbSession, metric: str = "", hours: float = 24) -> dict:
    """``metric`` empty returns every metric the widget has recorded."""
    widget, page = _widget(db, widget_id)
    board_for_viewer(db, str(page.board_id), user, kiosk_from_request(request, db))
    hours = max(0.1, min(24.0, hours))
    if metric:
        names = [metric]
    else:
        data = live.get(widget_id)
        names = list(data.metrics.keys()) if data and data.metrics else []
        if widget.health_check is not None:
            names.extend(["latency", "up"])
    return {name: history.series(db, widget_id, name, hours=hours) for name in names}


@router.get("/history/prune", include_in_schema=False)
def prune_history(db: DbSession, user: CurrentUser) -> dict:
    history.condense(db)
    db.commit()
    return {"ok": True}


def _unused(select_=select) -> None:  # keeps the import for type checkers
    return None
