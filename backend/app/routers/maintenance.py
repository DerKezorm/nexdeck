"""Maintenance windows: a connection or an app tile is away on purpose for a while.

Administrators only. A window holds back what everybody is told, so it is
not something a member can switch on for the whole house.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..deps import AdminUser, DbSession, error
from ..models import Maintenance, utcnow
from ..services import chronicle, maintenance
from ..services.sse import board_topic, hub

router = APIRouter(prefix="/api/v1/maintenance", tags=["maintenance"])
logger = logging.getLogger("nexdeck.maintenance")


class MaintenanceStart(BaseModel):
    integration_id: int | None = None
    widget_id: int | None = None
    #: Either a length from now or an end; the end wins when both are sent.
    minutes: int | None = Field(default=None, ge=1, le=7 * 24 * 60)
    ends_at: datetime | None = None


def _tell(db: DbSession, row: Maintenance) -> None:
    for board_id in maintenance.boards_touched(db, row):
        hub.publish(board_topic(board_id), "board", {"id": board_id, "changed": True})


@router.get("", summary="List running and recent maintenance")
def list_maintenance(user: AdminUser, db: DbSession) -> list[dict]:
    since = utcnow() - timedelta(days=7)
    rows = db.scalars(select(Maintenance).where(Maintenance.ends_at > since).order_by(Maintenance.ends_at.desc()).limit(50))
    return [maintenance.view(db, row) for row in rows]


@router.post("", status_code=status.HTTP_201_CREATED, summary="Start maintenance, or move the end of the running one")
def start_maintenance(body: MaintenanceStart, user: AdminUser, db: DbSession) -> dict:
    if body.ends_at is not None:
        ends_at = body.ends_at
    elif body.minutes is not None:
        ends_at = utcnow() + timedelta(minutes=body.minutes)
    else:
        raise error("missing_end", "Say how long, or until when.")
    try:
        row = maintenance.start(db, integration_id=body.integration_id, widget_id=body.widget_id,
                                ends_at=ends_at, user_id=user.id)
    except maintenance.Refused as refused:
        code = status.HTTP_404_NOT_FOUND if refused.code == "not_found" else status.HTTP_400_BAD_REQUEST
        raise error(refused.code, refused.message, code) from None
    view = maintenance.view(db, row)
    chronicle.record("maintenance", level="info", integration_id=row.integration_id, widget_id=row.widget_id,
                     user_id=user.id, name=view["name"], after=view["ends_at"], db=db)
    db.commit()
    logger.info("Maintenance for %r until %s, set by %s.", view["name"], view["ends_at"], user.username)
    _tell(db, row)
    return view


@router.delete("/{maintenance_id}", summary="End maintenance now")
def end_maintenance(maintenance_id: int, user: AdminUser, db: DbSession) -> dict:
    row = db.get(Maintenance, maintenance_id)
    if row is None:
        raise error("not_found", "No such maintenance.", status.HTTP_404_NOT_FOUND)
    running = row.ends_at > utcnow()
    maintenance.end(row)
    if running:
        chronicle.record("maintenance_end", level="info", integration_id=row.integration_id, widget_id=row.widget_id,
                         user_id=user.id, name=maintenance.view(db, row)["name"], db=db)
    db.commit()
    logger.info("Maintenance %d ended by %s.", row.id, user.username)
    _tell(db, row)
    return maintenance.view(db, row)
