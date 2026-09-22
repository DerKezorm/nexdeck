"""Ready-made boards: list them, see what a slot can be filled with, make one."""

from __future__ import annotations

import logging

from fastapi import APIRouter, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..deps import CurrentUser, DbSession, MemberUser, error
from ..models import Page, Widget
from ..services import templates
from ..services.boards import board_view
from ..services.collector import collector

router = APIRouter(prefix="/api/v1/templates", tags=["boards"])
logger = logging.getLogger("nexdeck.templates")


class TemplateInstall(BaseModel):
    #: The new board's name; left out, the template's own in the browser's language.
    name: str | None = Field(default=None, max_length=80)
    #: Slot name to the id of a connection, or null to leave its cards out.
    slots: dict[str, int | None] = Field(default_factory=dict)
    #: The template's English words and what they are in the browser's language.
    texts: dict[str, str] = Field(default_factory=dict, max_length=400)


@router.get("", summary="The ready-made boards")
def list_templates(user: CurrentUser) -> list[dict]:
    return [templates.summary(document) for document in templates._all().values()]


@router.get("/{template_id}", summary="One template, with the connections each slot may take here")
def get_template(template_id: str, user: CurrentUser, db: DbSession) -> dict:
    try:
        document = templates.get(template_id)
    except templates.TemplateError as failure:
        raise error("not_found", str(failure), status.HTTP_404_NOT_FOUND) from failure
    return {**templates.summary(document), "choices": templates.choices(db, document, user)}


@router.post("/{template_id}", status_code=status.HTTP_201_CREATED, summary="Make a board from a template")
def install_template(template_id: str, body: TemplateInstall, user: MemberUser, db: DbSession) -> dict:
    try:
        board = templates.install(db, template_id, user=user, name=body.name, slots=body.slots, texts=body.texts)
    except templates.TemplateError as failure:
        raise error("bad_template", str(failure)) from failure
    db.commit()
    for widget_id in db.scalars(select(Widget.id).join(Page).where(Page.board_id == board.id)):
        collector.schedule(widget_id)
    logger.info("Board %r made from the template %r by %s.", board.slug, template_id, user.username)
    return board_view(db, board, "owner")
