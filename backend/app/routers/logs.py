"""Container logs: recent lines and a live stream per log widget."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Request, status
from fastapi.responses import StreamingResponse

from ..deps import (
    DbSession,
    OptionalUser,
    board_for_viewer_id,
    error,
    kiosk_from_request,
    require_integration,
)
from ..models import Page, Widget
from ..services.logs import log_tailer, recent_lines
from ..services.sse import board_topic, hub

router = APIRouter(prefix="/api/v1/widgets", tags=["logs"])


def _log_widget(db: DbSession, widget_id: int, request: Request, user: OptionalUser) -> tuple[Widget, int, str]:
    widget = db.get(Widget, widget_id)
    if widget is None or widget.kind != "docker.logs":
        raise error("not_found", "There is no such log widget.", status.HTTP_404_NOT_FOUND)
    page = db.get(Page, widget.page_id)
    if page is None:
        raise error("not_found", "There is no such log widget.", status.HTTP_404_NOT_FOUND)
    # ⚠️ A container log is not board furniture. It carries paths, tokens in
    # tracebacks and whatever the service prints, so looking at the board is
    # not enough: this needs the same right as pressing a button on it.
    _board, permission = board_for_viewer_id(db, page.board_id, user, kiosk_from_request(request, db))
    if permission not in ("act", "owner"):
        raise error("forbidden", "You may not read container logs on this board.", status.HTTP_403_FORBIDDEN)
    if widget.integration_id is None:
        raise error("no_integration", "This log widget has no Docker integration.")
    require_integration(db, widget.integration_id, user)
    source = f"{widget.integration_id}:{(widget.options or {}).get('container', '')}"
    return widget, page.board_id, source


@router.get("/{widget_id}/logs", summary="Read the recent lines of a container log")
def logs(widget_id: int, request: Request, user: OptionalUser, db: DbSession, limit: int = 200) -> dict:
    widget, _board_id, source = _log_widget(db, widget_id, request, user)
    log_tailer.ensure(widget.id)
    return {"lines": recent_lines(source, max(10, min(2000, limit)))}


@router.get("/{widget_id}/logs/stream", summary="Follow a container log live")
async def log_stream(widget_id: int, request: Request, user: OptionalUser, db: DbSession) -> StreamingResponse:
    widget, board_id, source = _log_widget(db, widget_id, request, user)
    log_tailer.ensure(widget.id)
    subscriber = hub.subscribe({board_topic(board_id)})

    async def events() -> AsyncIterator[str]:
        try:
            for entry in recent_lines(source, 200):
                yield f"event: log\ndata: {json.dumps({'widget_id': widget.id, **entry})}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    message = await asyncio.wait_for(subscriber.queue.get(), timeout=25)
                except TimeoutError:
                    yield ": ping\n\n"
                    continue
                if message.startswith("event: log") and f'"widget_id": {widget.id},' in message:
                    yield message
        finally:
            hub.unsubscribe(subscriber)

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
