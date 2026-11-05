"""Maintenance windows: a connection or an app tile is away on purpose for a while.

Administrators only. A window holds back what everybody is told, so it is
not something a member can switch on for the whole house.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..deps import AdminUser, DbSession, error
from ..models import Maintenance, MaintenancePlan, utcnow
from ..services import chronicle, maintenance, maintenance_plans
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


class PlanBody(BaseModel):
    integration_id: int | None = None
    widget_id: int | None = None
    #: Monday 0 to Sunday 6.
    days: list[int] = Field(min_length=1, max_length=7)
    #: "03:00", on the clock of ``zone``.
    starts: str = Field(max_length=5)
    minutes: int = Field(ge=1, le=maintenance_plans.LONGEST_MINUTES)
    #: The browser's time zone, such as "Europe/Berlin"; empty for the server's own clock.
    zone: str = Field(default="", max_length=64)


def _refused(refused: maintenance.Refused) -> HTTPException:
    code = status.HTTP_404_NOT_FOUND if refused.code == "not_found" else status.HTTP_400_BAD_REQUEST
    return error(refused.code, refused.message, code)


def _plan_written(db: DbSession) -> None:
    """A plan made or moved inside its window holds at once, not only from the next round."""
    boards = maintenance_plans.tell_begun(db, maintenance_plans.write_due(db))
    db.commit()
    maintenance_plans.publish(boards)


@router.get("/plans", summary="List weekly maintenance, for one connection or app tile or for all")
def list_plans(user: AdminUser, db: DbSession, integration_id: int | None = None, widget_id: int | None = None) -> list[dict]:
    return [maintenance_plans.view(db, plan) for plan in maintenance_plans.for_target(db, integration_id=integration_id, widget_id=widget_id)]


@router.post("/plans", status_code=status.HTTP_201_CREATED, summary="Plan maintenance that comes back every week")
def create_plan(body: PlanBody, user: AdminUser, db: DbSession) -> dict:
    try:
        plan = maintenance_plans.create(db, integration_id=body.integration_id, widget_id=body.widget_id, days=body.days,
                                        starts=body.starts, minutes=body.minutes, zone=body.zone, user_id=user.id)
    except maintenance.Refused as refused:
        raise _refused(refused) from None
    db.commit()
    logger.info("Weekly maintenance for %r planned by %s: days %s from %s for %d minutes.",
                maintenance_plans.view(db, plan)["name"], user.username, plan.days, plan.starts, plan.minutes)
    _plan_written(db)
    return maintenance_plans.view(db, plan)


@router.put("/plans/{plan_id}", summary="Change the times of a weekly maintenance")
def change_plan(plan_id: int, body: PlanBody, user: AdminUser, db: DbSession) -> dict:
    plan = db.get(MaintenancePlan, plan_id)
    if plan is None:
        raise error("not_found", "No such weekly maintenance.", status.HTTP_404_NOT_FOUND)
    try:
        maintenance_plans.change(db, plan, days=body.days, starts=body.starts, minutes=body.minutes, zone=body.zone)
    except maintenance.Refused as refused:
        raise _refused(refused) from None
    db.commit()
    logger.info("Weekly maintenance %d changed by %s.", plan.id, user.username)
    _plan_written(db)
    return maintenance_plans.view(db, plan)


@router.delete("/plans/{plan_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Stop a weekly maintenance")
def remove_plan(plan_id: int, user: AdminUser, db: DbSession) -> None:
    plan = db.get(MaintenancePlan, plan_id)
    if plan is None:
        raise error("not_found", "No such weekly maintenance.", status.HTTP_404_NOT_FOUND)
    maintenance_plans.remove(db, plan)
    db.commit()
    logger.info("Weekly maintenance %d removed by %s.", plan_id, user.username)


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
        raise _refused(refused) from None
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
