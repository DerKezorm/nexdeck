"""The look of the installation: theme, accent, cards and its own style sheet."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request, status

from ..deps import AdminUser, DbSession, OptionalUser, error, kiosk_from_request
from ..schemas import AppearanceBody
from ..services import appearance

router = APIRouter(prefix="/api/v1/settings/appearance", tags=["system"])

logger = logging.getLogger("nexdeck.appearance")


@router.get("", summary="Read the look of the installation")
def read(request: Request, user: OptionalUser, db: DbSession) -> dict:
    """Everyone signed in reads it: every page is painted with it.

    ⚠️ A wall display too. It has no session, so this answered 401 and every
    kiosk stood in nexdeck's own cyan, whatever the operator had chosen, on
    the one screen that hangs in a room. The search targets had the same hole.
    """
    if user is None and kiosk_from_request(request, db) is None:
        raise error("unauthenticated", "Sign in first.", status.HTTP_401_UNAUTHORIZED)
    config = appearance.stored(db)
    return {**config, "colour": appearance.colour_of(config)}


@router.put("", summary="Change the look of the installation")
def write(body: AppearanceBody, admin: AdminUser, db: DbSession) -> dict:
    try:
        config = appearance.save(db, body.model_dump())
        logger.info("The look of the installation was changed by %s.", admin.username)
    except appearance.AppearanceError as failure:
        raise error(failure.code, failure.message) from failure
    return {**config, "colour": appearance.colour_of(config)}
