"""The search targets of the bar: read them, change them, suggest them."""

from __future__ import annotations

from fastapi import APIRouter

from ..deps import AdminUser, CurrentUser, DbSession, error
from ..schemas import SearchBody
from ..services import search

router = APIRouter(prefix="/api/v1/settings/search", tags=["system"])


@router.get("", summary="Read the search targets of the bar")
def read(user: CurrentUser, db: DbSession) -> dict:
    """Everyone signed in may read them: the bar needs them on every page."""
    return search.stored(db)


@router.put("", summary="Change the search targets of the bar")
def write(body: SearchBody, admin: AdminUser, db: DbSession) -> dict:
    try:
        return search.save(db, body.model_dump())
    except search.SearchError as failure:
        raise error(failure.code, failure.message) from failure


@router.get("/suggestions", summary="Search targets built from the connected services")
def suggest(admin: AdminUser, db: DbSession) -> dict:
    return {"targets": search.suggestions(db)}
