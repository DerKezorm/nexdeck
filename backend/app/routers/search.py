"""The search targets of the bar: read them, change them, suggest them."""

from __future__ import annotations

from fastapi import APIRouter, Request, status

from ..deps import AdminUser, DbSession, OptionalUser, error, kiosk_from_request
from ..schemas import SearchBody
from ..services import search

router = APIRouter(prefix="/api/v1/settings/search", tags=["system"])


@router.get("", summary="Read the search targets of the bar")
def read(request: Request, user: OptionalUser, db: DbSession) -> dict:
    """Everyone signed in may read them: the bar needs them on every page.

    ⚠️ A wall display too. It has no session, so this used to answer 401 and
    the search card on a kiosk board drew "no search target is set up yet"
    next to a link into settings that nobody at a wall can open. A target is
    a name and an address with a placeholder in it; there is nothing in one
    that a display may not see.
    """
    if user is None and kiosk_from_request(request, db) is None:
        raise error("unauthenticated", "Sign in first.", status.HTTP_401_UNAUTHORIZED)
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
