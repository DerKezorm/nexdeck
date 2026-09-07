"""Server-Sent Events: one connection per open board."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from ..db import db_session
from ..deps import DbSession, OptionalUser, board_for_viewer, kiosk_from_request, optional_user
from ..services.sse import board_topic, hub, user_topic

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

    def _still_allowed() -> bool:
        """Ask again whether this connection may still be here.

        ⚠️ The permission was worked out once, when the stream opened. A
        withdrawn kiosk token, a revoked session, a disabled account or a share
        taken away changed nothing for a stream that was already running: it
        kept sending until the browser closed it, and a wall display never
        closes anything. Asked again on every heartbeat, in a session of its
        own that lives for the length of one question.
        """
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

    async def events() -> AsyncIterator[str]:
        try:
            yield "event: hello\ndata: {}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    message = await asyncio.wait_for(subscriber.queue.get(), timeout=HEARTBEAT_SECONDS)
                except TimeoutError:
                    if not await asyncio.to_thread(_still_allowed):
                        break
                    yield ": ping\n\n"
                    continue
                yield message
        finally:
            hub.unsubscribe(subscriber)

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
