"""Server-Sent Events: one connection per open board."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from ..db import db_session
from ..deps import DbSession, OptionalUser, board_for_viewer, kiosk_from_request, optional_user
from ..services.sse import Recheck, board_topic, hub, user_topic
from .logs import may_read_log

router = APIRouter(prefix="/api/v1", tags=["stream"])

HEARTBEAT_SECONDS = 25


@router.get("/stream", summary="Live updates as Server-Sent Events")
async def stream(request: Request, user: OptionalUser, db: DbSession, board: str = "") -> StreamingResponse:
    """Sends ``widget``, ``health``, ``board``, ``layout`` and ``notice`` events.

    ``board`` names the board to follow. Signed-in users also receive their
    personal notices; kiosk displays receive only the board.
    """
    topics: set[str] = set()
    kiosk = kiosk_from_request(request, db)
    if board:
        board_row, _ = board_for_viewer(db, board, user, kiosk)
        topics.add(board_topic(board_row.id))
    if user is not None:
        topics.add(user_topic(user.id))
    subscriber = hub.subscribe(topics)
    #: Log widget -> whether this connection may read its lines. Forgotten at every recheck.
    log_rights: dict[int, bool] = {}

    async def _passes(message: str) -> bool:
        """⚠️ Container log lines travel on the board's topic, and this stream
        is open to anybody who may look at the board: a guest, a view share, a
        wall display. The log routes ask for the right to act on the board and
        for the Docker connection itself, so a line goes on only to those."""
        if not message.startswith("event: log\n"):
            return True
        try:
            widget_id = int(json.loads(message.split("\ndata: ", 1)[1])["widget_id"])
        except (IndexError, KeyError, TypeError, ValueError):
            return False
        if widget_id not in log_rights:
            log_rights[widget_id] = await asyncio.to_thread(may_read_log, widget_id, request)
        return log_rights[widget_id]

    def _still_allowed() -> bool:
        """Ask again whether this connection may still be here.

        ⚠️ The permission was worked out once, when the stream opened. A
        withdrawn kiosk token, a revoked session, a disabled account or a share
        taken away changed nothing for a stream that was already running: it
        kept sending until the browser closed it, and a wall display never
        closes anything. Asked again at least once a heartbeat, busy or quiet
        (see ``Recheck``), in a session of its own that lives for the length of
        one question.
        """
        log_rights.clear()
        try:
            with db_session() as db_again:
                who = optional_user(request, db_again)
                kiosk_again = kiosk_from_request(request, db_again)
                if board:
                    board_for_viewer(db_again, board, who, kiosk_again)
                elif who is None:
                    return False
        except HTTPException:
            return False
        return True

    recheck = Recheck(_still_allowed, every=HEARTBEAT_SECONDS)

    async def events() -> AsyncIterator[str]:
        try:
            yield "event: hello\ndata: {}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    message = await asyncio.wait_for(subscriber.queue.get(), timeout=HEARTBEAT_SECONDS)
                except TimeoutError:
                    message = ": ping\n\n"
                if await recheck.denied():
                    break
                if await _passes(message):
                    yield message
        finally:
            hub.unsubscribe(subscriber)

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
