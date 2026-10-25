"""The inventory and the relations (roadmap M5): what runs on what, for administrators.

Read and changed by administrators only: the inventory lists every
connection and every address, and a relation decides which outages are told.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..deps import AdminUser, DbSession, error
from ..models import Integration, Relation, Thing, Widget
from ..services import dependencies

router = APIRouter(prefix="/api/v1", tags=["inventory"])
logger = logging.getLogger("nexdeck.dependencies")

class RelationIn(BaseModel):
    child: str = Field(min_length=3, max_length=200)
    parent: str = Field(min_length=3, max_length=200)


def _exists(db: DbSession, ref: str) -> bool:
    kind, _, rest = ref.partition(":")
    if kind == "integration" and rest.isdigit():
        return db.get(Integration, int(rest)) is not None
    if kind == "tile" and rest.isdigit():
        row = db.get(Widget, int(rest))
        return row is not None and row.kind == "core.app"
    if kind in ("container", "guest"):
        return db.scalar(select(Thing.id).where(Thing.ref == ref)) is not None
    return False


@router.get("/inventory", summary="Every connection, app tile, container and guest, and what runs on what")
def inventory(user: AdminUser, db: DbSession) -> dict:
    return dependencies.view(db)


@router.post("/inventory/refresh", summary="Ask the engines and hypervisors now what they run")
async def refresh(user: AdminUser, db: DbSession) -> dict:
    db.rollback()
    count = await dependencies.discover()
    logger.info("%s asked what runs where: %d things known.", user.username, count)
    db.expire_all()
    return dependencies.view(db)


@router.post("/relations", status_code=status.HTTP_201_CREATED, summary="Say that one thing runs on or needs another")
def add_relation(body: RelationIn, user: AdminUser, db: DbSession) -> dict:
    if body.child == body.parent:
        raise error("same", "A thing cannot run on itself.")
    if not _exists(db, body.child) or not _exists(db, body.parent):
        raise error("not_found", "No such connection, tile, container or guest.", status.HTTP_404_NOT_FOUND)
    if body.child.startswith(("container:", "guest:")) and body.parent == f"integration:{body.child.split(':')[1]}":
        raise error("already", "It runs there already.")
    # ⚠️ A circle would make everything in it the cause of everything else.
    if body.child in dependencies.ancestors(db, body.parent):
        raise error("circle", "That would go round in a circle.")
    row = db.scalar(select(Relation).where(Relation.child == body.child, Relation.parent == body.parent))
    if row is None:
        row = Relation(child=body.child, parent=body.parent, origin="manual", state="on")
        db.add(row)
    else:
        row.origin, row.state = ("manual" if row.origin != "auto" else row.origin), "on"
    db.commit()
    return {"id": row.id, "child": row.child, "parent": row.parent, "origin": row.origin, "state": row.state}


@router.post("/relations/{relation_id}/confirm", summary="Say yes to a proposed relation")
def confirm(relation_id: int, user: AdminUser, db: DbSession) -> dict:
    row = db.get(Relation, relation_id)
    if row is None:
        raise error("not_found", "No such relation.", status.HTTP_404_NOT_FOUND)
    row.state = "on"
    db.commit()
    return {"id": row.id, "state": row.state}


@router.delete("/relations/{relation_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Take a relation away, or say no to a proposed one")
def remove(relation_id: int, user: AdminUser, db: DbSession) -> None:
    """One set by hand goes. One found or proposed is kept as a no, so it is not found or proposed again."""
    row = db.get(Relation, relation_id)
    if row is None:
        raise error("not_found", "No such relation.", status.HTTP_404_NOT_FOUND)
    if row.origin == "manual":
        db.delete(row)
    else:
        row.state = "rejected"
    db.commit()
