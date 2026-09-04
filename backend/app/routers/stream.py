"""Server-Sent Events: one connection per open board."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from ..deps import DbSession, OptionalUser, board_for_viewer, kiosk_from_request
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

    async def events() -> AsyncIterator[str]:
        try:
            yield "event: hello\ndata: {}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    message = await asyncio.wait_for(subscriber.queue.get(), timeout=HEARTBEAT_SECONDS)
                except TimeoutError:
                    yield ": ping\n\n"
                    continue
                yield message
        finally:
            hub.unsubscribe(subscriber)

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
