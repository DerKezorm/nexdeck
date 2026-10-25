"""Why is this broken (roadmap M6): one page per service, its container's log, its runbook.

Administrators only: the page shows how everything hangs together, every
check's address and a container's log.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, Field

from ..adapters.base import AdapterError
from ..deps import AdminUser, DbSession, error
from ..services import diagnosis

router = APIRouter(prefix="/api/v1", tags=["diagnosis"])
logger = logging.getLogger("nexdeck.diagnosis")

#: Lines of a container's log the button reads.
LOG_LINES = 100


class LogAsked(BaseModel):
    ref: str = Field(min_length=3, max_length=200)


class RunbookIn(BaseModel):
    ref: str = Field(min_length=3, max_length=200)
    text: str = Field(default="", max_length=diagnosis.RUNBOOK_TEXT)
    link: str = Field(default="", max_length=diagnosis.RUNBOOK_LINK)


def _missing() -> Exception:
    return error("not_found", "There is no such service, container or guest.", status.HTTP_404_NOT_FOUND)


@router.get("/diagnosis", summary="Why a service is in trouble: since when, what came before, what it hangs on")
def read(user: AdminUser, db: DbSession, ref: str = Query(min_length=3, max_length=200),
         at: float | None = Query(default=None, description="A moment of a past trouble, in epoch seconds")) -> dict:
    moment = datetime.fromtimestamp(at, UTC) if at is not None else None
    page = diagnosis.build(db, ref, moment)
    if page is None:
        raise _missing()
    return page


@router.post("/diagnosis/log", summary="The last lines of the log of the container a service runs in")
async def read_log(body: LogAsked, user: AdminUser, db: DbSession) -> dict:
    if diagnosis.subject(db, body.ref) is None:
        raise _missing()
    place = diagnosis.log_place(db, body.ref)
    if not place["available"]:
        raise error(place["why"], "There is no log to read for this.", status.HTTP_409_CONFLICT)
    thing = diagnosis.container_of(db, body.ref)
    integration_id, name = thing.integration_id, thing.name
    db.rollback()
    from ..services.assistant.tools import log_redact
    from ..services.collector import collector
    from ..services.journal import redact

    adapter, config, ctx = await collector.resolve_integration(integration_id)
    try:
        found = await adapter.container_log(config, ctx, name, LOG_LINES) or []
    except AdapterError as failure:
        raise error(failure.code or "log_failed", failure.message, status.HTTP_502_BAD_GATEWAY) from None
    lines = [log_redact(redact(line))[:400] for line in found if line.strip()][-LOG_LINES:]
    logger.info("%s read the last %d lines of the log of %s.", user.username, len(lines), name)
    return {"container": place["container"], "engine": place["engine"], "lines": lines, "read": datetime.now(UTC).timestamp()}


@router.put("/diagnosis/runbook", summary="Write what to do when this service breaks; empty removes it")
def write_runbook(body: RunbookIn, user: AdminUser, db: DbSession) -> dict:
    if diagnosis.subject(db, body.ref) is None:
        raise _missing()
    try:
        kept = diagnosis.write_runbook(db, body.ref, body.text, body.link, user)
    except ValueError:
        raise error("bad_link", "A link starts with http:// or https://.") from None
    logger.info("%s %s the runbook of %s.", user.username, "wrote" if kept["text"] or kept["link"] else "removed", body.ref)
    return kept
