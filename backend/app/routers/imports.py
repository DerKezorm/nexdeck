"""Boards from other dashboards: see the plan, then make it."""

from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from ..deps import DbSession, MemberUser, error
from ..models import Page, Widget
from ..services import dashboard_import
from ..services.boards import board_view
from ..services.collector import collector

router = APIRouter(prefix="/api/v1/imports", tags=["boards"])
logger = logging.getLogger("nexdeck.imports")


class ImportFiles(BaseModel):
    """The other dashboard's files as pasted: Homepage's services, bookmarks and widgets, or Homarr's config."""

    source: Literal["auto", "homepage", "homarr"] = "auto"
    files: dict[Literal["services", "bookmarks", "widgets", "config"], str] = Field(default_factory=dict)

    @field_validator("files")
    @classmethod
    def _bounded(cls, files: dict[str, str]) -> dict[str, str]:
        if not any(text.strip() for text in files.values()):
            raise ValueError("Paste at least one file.")
        if sum(len(text) for text in files.values()) > 2_000_000:
            raise ValueError("The files are larger than two megabytes together.")
        return files


class ImportPlan(BaseModel):
    plan: dict[str, Any]
    name: str = Field(default="", max_length=80)


@router.post("/preview", summary="Read another dashboard's files into a plan, without making anything")
def preview(body: ImportFiles, user: MemberUser, db: DbSession) -> dict:
    try:
        return dashboard_import.preview(db, user, body.source, dict(body.files))
    except dashboard_import.DashboardImportError as failure:
        raise error("bad_import", str(failure)) from failure


@router.post("/apply", status_code=status.HTTP_201_CREATED, summary="Make the board a plan describes")
def apply(body: ImportPlan, user: MemberUser, db: DbSession) -> dict:
    try:
        board = dashboard_import.apply(db, user, body.plan, body.name)
    except dashboard_import.DashboardImportError as failure:
        db.rollback()
        raise error("bad_import", str(failure)) from failure
    db.commit()
    for widget_id in db.scalars(select(Widget.id).join(Page).where(Page.board_id == board.id)):
        collector.schedule(widget_id)
    logger.info("Board %r imported from %s by %s.", board.slug, body.plan.get("source", "another dashboard"), user.username)
    return board_view(db, board, "owner")
