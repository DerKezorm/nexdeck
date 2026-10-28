"""The card editor asks the provider of the assistant for a card (KARTEN-17).

Administrators only, like the editor itself. One request per administrator at a time, and it can be cancelled. The
provider is the one of "Ask nexdeck"; with none set up, or after it is taken away, every call answers ``assistant_off``.
What leaves for the provider is decided in :mod:`..cards.ai`, nowhere else.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field, StringConstraints, ValidationError

from ..adapters.base import AdapterError
from ..cards import ai, credentials, schema
from ..db import db_session
from ..deps import AdminUser, DbSession, error
from ..models import Integration
from ..services import chronicle
from ..services.assistant import settings
from .cards import _ask, _connection, _connection_number, _failed

router = APIRouter(prefix="/api/v1/cards", tags=["cards"])
logger = logging.getLogger("nexdeck.cards")

#: Code of the answer to a request that was cancelled, and the HTTP answer of each code of :class:`ai.AiError`.
CANCELLED = "ai_cancelled"
_HTTP = {"assistant_off": 409, "ai_busy": 409, CANCELLED: 409, "bad_request": 400}


class AiBody(BaseModel):
    mode: str = Field(max_length=12)
    description: str = Field(default="", max_length=2000)
    yaml: str = Field(default="", max_length=schema.MAX_DEFINITION * 2)
    kind: Annotated[str, StringConstraints(pattern=r"^(custom:)?[a-z0-9][a-z0-9_-]{0,59}$")] | None = None
    connection_id: int | None = None
    path: str | None = Field(default=None, max_length=500)
    include_values: bool = False


def _refused(failure: ai.AiError) -> HTTPException:
    return error(failure.code, failure.message, _HTTP.get(failure.code, status.HTTP_502_BAD_GATEWAY))


def _check(body: AiBody) -> schema.Request | None:
    """The request the answer is asked for, or ``None`` when no connection is named; refuses what cannot be asked."""
    if body.mode not in ai.MODES:
        raise error("bad_request", "Say whether to write a new card, change one or translate one.", status.HTTP_400_BAD_REQUEST)
    if body.mode == "new" and (body.connection_id is None or not body.path):
        raise error("bad_request", "A new card needs the connection and the path it reads.", status.HTTP_400_BAD_REQUEST)
    if body.mode != "new" and not body.yaml.strip():
        raise error("bad_request", "Give the text of the card.", status.HTTP_400_BAD_REQUEST)
    _connection_number(body.connection_id)
    if body.connection_id is None or not body.path:
        return None
    try:
        request = schema.Request(id="probe", path=body.path)
    except ValidationError:
        raise error("bad_path", "The path must start with a single / and name no host; it is always underneath the connection's address.", status.HTTP_400_BAD_REQUEST) from None
    # ⚠️ As in a probe: a secret in the path is refused before anything is asked or written down.
    if next(credentials.find(body.path), None) is not None:
        raise error("card_secret_value", "This looks like a key. A card holds no secrets: the connection sends its own.", status.HTTP_400_BAD_REQUEST)
    return request


async def _asked(body: AiBody, request: schema.Request | None, userid: int, username: str) -> tuple[str, Any]:
    """The kind of the connection and what the service answered at the path, asked the way the editor's probe asks."""
    if request is None:
        return body.kind or "", ai.MISSING
    assert body.connection_id is not None
    adapter, config, ctx = await _connection(body.connection_id)
    answer = await _ask(adapter, config, ctx, request)
    with db_session() as db:
        name = db.get(Integration, body.connection_id)
        chronicle.record("card_probe", user_id=userid, integration_id=body.connection_id, name=name.name if name else "", detail=f"{request.path} (card help)", db=db)
        db.commit()
    logger.info("%s asked %s for a card at %s.", username, body.connection_id, request.path)
    return adapter.kind, answer


@router.post("/ai", summary="Have the provider of the assistant write, change or translate a card")
async def card_with_ai(body: AiBody, user: AdminUser, db: DbSession) -> dict[str, Any]:
    if not settings.ready(db):
        raise error("assistant_off", "The assistant is not set up.", status.HTTP_409_CONFLICT)
    request = _check(body)
    config, key = settings.stored(db), settings.key_of(db)
    userid, username = user.id, user.username
    db.rollback()  # the provider may take minutes; a read transaction should not wait with it

    async def work() -> ai.Outcome:
        kind, answer = await _asked(body, request, userid, username)
        return await ai.generate(
            ai.Ask(mode=body.mode, description=body.description, yaml=body.yaml, connection_kind=kind, path=body.path or "", answer=answer, include_values=body.include_values),
            config, key,
        )

    try:
        finished, outcome = await ai.supervised(userid, work())
    except ai.Busy:
        raise error("ai_busy", "A card is being written already. Wait for it or cancel it.", status.HTTP_409_CONFLICT) from None
    except AdapterError as failure:
        raise _failed(failure) from failure
    except ai.AiError as failure:
        raise _refused(failure) from None
    if not finished:
        with db_session() as fresh:
            gone = not settings.ready(fresh)
        raise _refused(ai.AiError("assistant_off", "The assistant was switched off.") if gone else ai.AiError(CANCELLED, "The request was cancelled."))
    logger.info("%s had a card %s by the assistant (%s).", username, "written" if outcome.ok else "tried", body.mode)
    return outcome.body()


@router.delete("/ai", summary="Cancel the card being written for you")
def cancel(user: AdminUser) -> dict[str, bool]:
    return {"cancelled": ai.cancel(user.id)}
