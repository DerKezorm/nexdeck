"""Widgets: create, change, refresh, act, reachability checks and history."""

from __future__ import annotations

import time
from typing import Any

import httpx
from fastapi import APIRouter, Request, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from ..adapters import split_widget_kind
from ..adapters.base import AdapterError, Context
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
        # An app tile may follow any service; every other widget needs its own kind.
        if integration.kind != adapter.kind and kind != "core.app":
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


# -- images of a widget's service ----------------------------------------------

IMAGE_TTL = 3600
IMAGE_LIMIT = 300
IMAGE_MAX_BYTES = 5 * 1024 * 1024
_images: dict[tuple[int, str], tuple[float, bytes, str]] = {}
_insecure_client: httpx.AsyncClient | None = None


def _image_client(insecure: bool) -> httpx.AsyncClient:
    global _insecure_client
    if not insecure:
        return collector.client
    if _insecure_client is None or _insecure_client.is_closed:
        _insecure_client = httpx.AsyncClient(verify=False, follow_redirects=True, timeout=15.0, headers={"User-Agent": "nexdeck"})
    return _insecure_client


async def _service_of(widget: Widget) -> tuple[Any, dict[str, Any], Context]:
    """The adapter, configuration and shared context behind a widget's integration.

    The context is the collector's, so a session token the adapter already holds
    (Reolink, Synology) serves images and streams too instead of a fresh login.
    """
    if not widget.integration_id:
        raise error("not_found", "This widget has no service to fetch from.", status.HTTP_404_NOT_FOUND)
    try:
        return await collector.resolve_integration(widget.integration_id)
    except AdapterError as failure:
        raise error("not_found", str(failure), status.HTTP_404_NOT_FOUND) from failure


@router.get("/widgets/{widget_id}/image", summary="Serve an image of a widget's service through the server")
async def widget_image(widget_id: int, path: str, request: Request, user: OptionalUser, db: DbSession) -> Response:
    """Posters, thumbnails and snapshots come from the service with the server's credentials; the browser never sees a token.

    ``path`` is relative to the integration's address, so the server only ever
    fetches from the service the widget already talks to. The adapter may
    redirect a path (``/snap/0``) to the real request through ``image_source``.
    """
    widget, page = _widget(db, widget_id)
    board_for_viewer(db, str(page.board_id), user, kiosk_from_request(request, db))
    if not path.startswith("/") or path.startswith("//") or "://" in path:
        raise error("bad_path", "An image path is relative to the service, starting with a slash.")
    hit = _images.get((widget_id, path))
    if hit and hit[0] > time.monotonic():
        return Response(content=hit[1], media_type=hit[2], headers={"Cache-Control": "private, max-age=3600"})
    adapter, config, ctx = await _service_of(widget)
    try:
        source = await adapter.image_source(config, path, ctx)
    except AdapterError as failure:
        code = getattr(failure, "code", "") or "no_image"
        raise error(code, str(failure), status.HTTP_400_BAD_REQUEST if code == "bad_path" else status.HTTP_502_BAD_GATEWAY) from failure
    try:
        response = await _image_client(bool(config.get("insecure"))).get(source.url, headers=source.headers, params=source.params or None)
    except httpx.HTTPError as failure:
        raise error("unreachable", f"The service did not deliver the image: {failure.__class__.__name__}.", status.HTTP_502_BAD_GATEWAY) from failure
    content_type = response.headers.get("content-type", "") or source.media_type
    if response.status_code >= 400 or not content_type.startswith("image/") or len(response.content) > IMAGE_MAX_BYTES:
        raise error("no_image", "The service did not answer with an image.", status.HTTP_404_NOT_FOUND)
    if source.cache_seconds <= 0:
        return Response(content=response.content, media_type=content_type, headers={"Cache-Control": "no-store"})
    if len(_images) >= IMAGE_LIMIT:
        oldest = min(_images, key=lambda key: _images[key][0])
        _images.pop(oldest, None)
    _images[(widget_id, path)] = (time.monotonic() + min(IMAGE_TTL, source.cache_seconds), response.content, content_type)
    return Response(content=response.content, media_type=content_type, headers={"Cache-Control": "private, max-age=3600"})


# -- live video of a widget's service -------------------------------------------

#: How many live streams the server relays at once; every one is an open connection to a camera.
STREAM_LIMIT = 12
_streams_open = 0


@router.get("/widgets/{widget_id}/stream", summary="Relay a widget's live video through the server")
async def widget_stream(widget_id: int, request: Request, user: OptionalUser, db: DbSession) -> StreamingResponse:
    """Live video (HTTP-FLV from a camera or recorder) flows through the server with
    the service's credentials; the browser only ever talks to nexdeck and plays
    the bytes with Media Source Extensions, no transcoder anywhere."""
    global _streams_open
    widget, page = _widget(db, widget_id)
    board_for_viewer(db, str(page.board_id), user, kiosk_from_request(request, db))
    adapter, config, ctx = await _service_of(widget)
    try:
        source = await adapter.stream_source(config, dict(widget.options or {}), ctx)
    except AdapterError as failure:
        raise error(getattr(failure, "code", "") or "no_stream", str(failure), status.HTTP_404_NOT_FOUND) from failure
    if _streams_open >= STREAM_LIMIT:
        raise error("too_many_streams", f"The server relays at most {STREAM_LIMIT} live streams at once.", status.HTTP_503_SERVICE_UNAVAILABLE)
    client = _image_client(bool(config.get("insecure")))
    upstream = client.build_request("GET", source.url, headers=source.headers, params=source.params or None, timeout=httpx.Timeout(15.0, read=60.0))
    try:
        response = await client.send(upstream, stream=True)
    except httpx.HTTPError as failure:
        raise error("unreachable", f"The service did not deliver the stream: {failure.__class__.__name__}.", status.HTTP_502_BAD_GATEWAY) from failure
    if response.status_code >= 400:
        await response.aclose()
        raise error("no_stream", f"The service answered the stream request with HTTP {response.status_code}.", status.HTTP_502_BAD_GATEWAY)
    media_type = source.media_type or response.headers.get("content-type", "video/x-flv")
    _streams_open += 1

    async def relay():
        # Every chunk goes out as it arrives. Collecting 64 kB first would hold
        # up to a second of a small stream back and the player would stutter.
        global _streams_open
        try:
            async for chunk in response.aiter_raw():
                yield chunk
        finally:
            _streams_open -= 1
            await response.aclose()

    return StreamingResponse(relay(), media_type=media_type, headers={"Cache-Control": "no-store"})


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
    if not body.target.strip() and widget.integration_id is None:
        raise error("target_missing", "A check needs a target, or the widget an integration whose address it follows.")
    check = widget.health_check or HealthCheck(widget_id=widget.id, target=body.target)
    check.kind = body.kind
    # An empty target means: the address of the widget's integration, looked up at every check.
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
