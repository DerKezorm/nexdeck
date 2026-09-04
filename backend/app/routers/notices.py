"""The in-app notice centre."""

from __future__ import annotations

from fastapi import APIRouter, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, select, update

from ..deps import CurrentUser, DbSession, error
from ..models import Notice, utcnow
from ..services.notify import notice_payload

router = APIRouter(prefix="/api/v1/notices", tags=["notices"])


class ReadBody(BaseModel):
    ids: list[int] = Field(default_factory=list)
    all: bool = False


@router.get("", summary="List my notices")
def list_notices(user: CurrentUser, db: DbSession, unread: bool = False, limit: int = 100) -> list[dict]:
    query = select(Notice).where(Notice.user_id == user.id).order_by(Notice.created_at.desc()).limit(max(1, min(500, limit)))
    if unread:
        query = query.where(Notice.read_at.is_(None))
    return [notice_payload(n) for n in db.scalars(query)]


@router.post("/read", summary="Mark notices as read")
def mark_read(body: ReadBody, user: CurrentUser, db: DbSession) -> dict:
    query = update(Notice).where(Notice.user_id == user.id, Notice.read_at.is_(None)).values(read_at=utcnow())
    if not body.all:
        query = query.where(Notice.id.in_(body.ids))
    result = db.execute(query)
    db.commit()
    return {"marked": result.rowcount}


@router.delete("/{notice_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete one notice")
def delete_notice(notice_id: int, user: CurrentUser, db: DbSession) -> None:
    notice = db.get(Notice, notice_id)
    if notice is None or notice.user_id != user.id:
        raise error("not_found", "There is no such notice.", status.HTTP_404_NOT_FOUND)
    db.delete(notice)
    db.commit()


@router.delete("", status_code=status.HTTP_204_NO_CONTENT, summary="Delete all read notices")
def clear_read(user: CurrentUser, db: DbSession) -> None:
    db.execute(delete(Notice).where(Notice.user_id == user.id, Notice.read_at.is_not(None)))
    db.commit()
