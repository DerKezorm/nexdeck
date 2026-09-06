"""The look of the installation: the accent colour and its own style sheet."""

from __future__ import annotations

from fastapi import APIRouter

from ..deps import AdminUser, CurrentUser, DbSession, error
from ..schemas import AppearanceBody
from ..services import appearance

router = APIRouter(prefix="/api/v1/settings/appearance", tags=["system"])


@router.get("", summary="Read the look of the installation")
def read(user: CurrentUser, db: DbSession) -> dict:
    """Everyone signed in reads it: every page is painted with it."""
    config = appearance.stored(db)
    return {**config, "colour": appearance.colour_of(config)}


@router.put("", summary="Change the look of the installation")
def write(body: AppearanceBody, admin: AdminUser, db: DbSession) -> dict:
    try:
        config = appearance.save(db, body.model_dump())
    except appearance.AppearanceError as failure:
        raise error(failure.code, failure.message) from failure
    return {**config, "colour": appearance.colour_of(config)}
