"""The chronicle page: what changed, newest first, filtered by kind, time and words.

Administrators see every line. Everybody else sees the lines about cards on
boards they may open and the connections those cards use, nothing about the
installation itself (``chronicle.ADMIN_ONLY``).
"""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Query

from ..deps import CurrentUser, DbSession, error
from ..models import utcnow
from ..services import chronicle

router = APIRouter(prefix="/api/v1/chronicle", tags=["chronicle"])

#: The windows the page offers, in days.
WINDOWS = (1, 7, 30, 365)


@router.get("", summary="Lines of the chronicle, newest first")
def list_chronicle(
    user: CurrentUser,
    db: DbSession,
    days: int = 7,
    group: str = "all",
    q: str = Query(default="", max_length=100),
    before: int | None = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> dict:
    if days not in WINDOWS:
        raise error("bad_window", f"A window is one of {', '.join(map(str, WINDOWS))} days.")
    if group != "all" and group not in chronicle.GROUPS:
        raise error("bad_group", "No such group of lines.")
    kinds = chronicle.GROUPS.get(group)
    # One more than asked: whether there is a page after this one.
    rows = chronicle.query(db, user=user, kinds=kinds, since=utcnow() - timedelta(days=days), words=q,
                           before_id=before, limit=limit + 1)
    return {"events": chronicle.view(db, rows[:limit], user), "more": len(rows) > limit}
