"""Own kinds of connection: describe a service nexdeck does not know, keep the description, change it, delete it (KARTEN-3).

Everything here is for administrators. The description is kept as the text its author wrote
(``cards/integration_store``); the connections made from it run through the ordinary routes of connections with the kind
``custom:<short>``. This router decides who may touch a description and writes it down in the log.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..cards import integration, integration_schema, load
from ..cards import integration_store as store
from ..deps import AdminUser, DbSession, error
from ..models import Integration, OwnIntegration, User, Widget
from ..services import chronicle
from ..services.collector import collector

router = APIRouter(prefix="/api/v1/own-integrations", tags=["own-integrations"])
logger = logging.getLogger("nexdeck.own_integrations")


class Text(BaseModel):
    yaml: str = Field(max_length=integration_schema.MAX_TEXT * 2)


class ReplaceBody(Text):
    base: str | None = Field(default=None, max_length=64, description="The updated_at that was read; a different one means somebody saved meanwhile.")
    overwrite: bool = Field(default=False, description="Save over what somebody saved meanwhile.")


def _invalid(failure: load.CardInvalid) -> HTTPException:
    detail = failure.detail()
    first = failure.problems[0].code
    if first == "card_integration_short_exists":
        return HTTPException(status.HTTP_409_CONFLICT, {**detail, "code": "integration_exists"})
    return HTTPException(status.HTTP_400_BAD_REQUEST, {**detail, "code": "integration_invalid"})


def _too_many() -> HTTPException:
    return error("integration_limit", f"There are {store.MAX_INTEGRATIONS} own connections already, which is the most nexdeck keeps. Delete one first.", status.HTTP_400_BAD_REQUEST)


def _row(db: Session, short: str) -> OwnIntegration:
    row = store.get(db, short)
    if row is None:
        raise error("integration_not_found", "There is no such own connection.", status.HTTP_404_NOT_FOUND)
    return row


def _name_of(db: Session, number: int | None) -> str | None:
    found = db.get(User, number) if number is not None else None
    return found.username if found is not None else None


def _view(db: Session, row: OwnIntegration, *, text: bool) -> dict[str, Any]:
    data = row.definition or {}
    view: dict[str, Any] = {
        "short": row.short,
        "kind": store.kind_of(row.short),
        "name": data.get("name", row.short),
        "logo": data.get("logo", ""),
        "description": data.get("description", ""),
        "connections": store.connections(db, row.short),
        "updated_at": row.updated_at,
        "updated_by": _name_of(db, row.updated_by if row.updated_by is not None else row.created_by),
    }
    if text:
        view["yaml"] = row.yaml_source
    return view


def _tell(db: Session, short: str) -> None:
    """Every card on a connection of the kind fetches again: the change shows at once (AC-11)."""
    kind = store.kind_of(short)
    for widget in db.scalars(select(Widget).join(Integration, Integration.id == Widget.integration_id).where(Integration.kind == kind)):
        collector.schedule(widget.id)


@router.get("", summary="The own kinds of connection")
def listing(user: AdminUser, db: DbSession) -> list[dict[str, Any]]:
    return [_view(db, row, text=False) for row in store.listing(db)]


@router.get("/template", summary="A description to begin with")
def template(user: AdminUser) -> dict[str, str]:
    return {"yaml": integration.TEMPLATE}


@router.post("/check", summary="Check a description without keeping it")
def check(body: Text, user: AdminUser) -> dict[str, Any]:
    try:
        integration.load_integration(body.yaml)
    except load.CardInvalid as failure:
        return {"ok": False, "problems": [problem.as_dict() for problem in failure.problems]}
    return {"ok": True}


@router.get("/{short}", summary="One own kind of connection, with its text")
def read(short: str, user: AdminUser, db: DbSession) -> dict[str, Any]:
    return _view(db, _row(db, short), text=True)


@router.post("", status_code=status.HTTP_201_CREATED, summary="Keep a new description")
def create(body: Text, user: AdminUser, db: DbSession) -> dict[str, Any]:
    with store.saving:
        try:
            row = store.create(db, body.yaml, user_id=user.id)
        except load.CardInvalid as failure:
            raise _invalid(failure) from failure
        except store.TooManyIntegrations:
            raise _too_many() from None
        logger.info("Own connection %r made by %s.", row.short, user.username)
        chronicle.record("card_definition_added", user_id=user.id, name=store.kind_of(row.short), detail="own connection made", db=db)
        db.commit()
    _tell(db, row.short)
    return _view(db, row, text=True)


def _moment(text: str) -> datetime:
    try:
        found = datetime.fromisoformat(text)
    except ValueError:
        raise error("bad_base", "The time the description was read at is not a time.") from None
    return found.astimezone(UTC) if found.tzinfo else found.replace(tzinfo=UTC)


@router.put("/{short}", summary="Replace the description; every connection of the kind follows at once")
def replace(short: str, body: ReplaceBody, user: AdminUser, db: DbSession) -> dict[str, Any]:
    with store.saving:
        row = _row(db, short)
        if body.base is not None and not body.overwrite and _moment(body.base) != row.updated_at:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                {
                    "code": "integration_changed_meanwhile",
                    "message": "This description was saved by somebody else while you had it open.",
                    "by": _name_of(db, row.updated_by if row.updated_by is not None else row.created_by),
                    "at": row.updated_at.isoformat().replace("+00:00", "Z"),
                },
            )
        try:
            store.update(db, row, body.yaml, user_id=user.id)
        except load.CardInvalid as failure:
            raise _invalid(failure) from failure
        logger.info("Own connection %r changed by %s.", short, user.username)
        chronicle.record("card_definition_changed", user_id=user.id, name=store.kind_of(short), detail="own connection changed", db=db)
        db.commit()
    _tell(db, short)
    return _view(db, row, text=True)


@router.delete("/{short}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a description; its connections stay and say it is missing")
def delete(short: str, user: AdminUser, db: DbSession) -> None:
    with store.saving:
        row = _row(db, short)
        kind = store.kind_of(short)
        widgets = [w.id for w in db.scalars(select(Widget).join(Integration, Integration.id == Widget.integration_id).where(Integration.kind == kind))]
        connections = store.connections(db, short)
        store.delete(db, row)
        logger.info("Own connection %r deleted by %s; %d connection(s) stay.", short, user.username, connections)
        chronicle.record("card_definition_removed", user_id=user.id, name=kind, detail=f"{connections} connection(s) stay", db=db)
        db.commit()
    for number in widgets:
        collector.schedule(number)
