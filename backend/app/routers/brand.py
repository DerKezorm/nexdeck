"""The name and the logo of the installation (``services/brand.py``)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, UploadFile, status
from fastapi.responses import FileResponse

from ..deps import AdminUser, DbSession, error
from ..schemas import BrandBody
from ..services import appearance, brand
from ..uploads import read_at_most

router = APIRouter(tags=["system"])

logger = logging.getLogger("nexdeck.brand")

#: The answer of a logo or an icon. The address carries the logo's stamp, so a
#: day of caching never shows an old one; the sandbox is the one every
#: uploaded picture gets.
_SERVED = {
    "Cache-Control": "public, max-age=86400",
    "Content-Security-Policy": "sandbox; default-src 'none'; style-src 'unsafe-inline'; img-src data:",
    "X-Content-Type-Options": "nosniff",
}


@router.get("/api/v1/brand", summary="Read the name and the logo of the installation")
def read_public(db: DbSession) -> dict:
    """Public on purpose: the sign-in page and the browser tab need them before anyone signs in.

    With them the part of the look the sign-in page is drawn in, so an
    installation in 1984 greets in 1984 and not in nexdeck's glass.
    """
    return {**brand.public(db), "look": appearance.public(db)}


@router.get("/api/v1/brand/logo", summary="The logo of the installation", response_class=FileResponse)
def serve_logo(db: DbSession) -> FileResponse:
    found = brand.logo_file(db)
    if found is None or not found[0].is_file():
        raise error("not_found", "This installation has no logo of its own.", status.HTTP_404_NOT_FOUND)
    return FileResponse(found[0], media_type=found[1], headers=_SERVED)


@router.get("/api/v1/brand/icon-{size}.png", summary="An app icon drawn from the logo", response_class=FileResponse)
def serve_icon(size: int, db: DbSession) -> FileResponse:
    path = brand.icon_file(db, size)
    if path is None:
        raise error("not_found", "There is no such icon.", status.HTTP_404_NOT_FOUND)
    return FileResponse(path, media_type="image/png", headers=_SERVED)


@router.get("/api/v1/settings/brand", summary="Read the name and the logo settings")
def read(admin: AdminUser, db: DbSession) -> dict:
    return {**brand.stored(db), **{"urls": brand.public(db)}}


@router.put("/api/v1/settings/brand", summary="Change the name and where the logo is shown")
def write(body: BrandBody, admin: AdminUser, db: DbSession) -> dict:
    try:
        brand.save(db, body.model_dump())
    except brand.BrandError as failure:
        raise error(failure.code, failure.message) from failure
    logger.info("The name of the installation was changed by %s.", admin.username)
    return {**brand.stored(db), **{"urls": brand.public(db)}}


@router.post("/api/v1/settings/brand/logo", summary="Upload a logo and the app icons drawn from it")
async def upload_logo(logo: UploadFile, icon192: UploadFile, icon512: UploadFile, admin: AdminUser, db: DbSession) -> dict:
    data = await read_at_most(logo, brand.MAX_BYTES * 2, "logo")
    icons = {192: await read_at_most(icon192, brand.MAX_BYTES * 2, "icon"), 512: await read_at_most(icon512, brand.MAX_BYTES * 2, "icon")}
    try:
        brand.save_logo(db, data, logo.content_type or "", icons)
    except brand.BrandError as failure:
        raise error(failure.code, failure.message) from failure
    # Shown to everybody, signed in or not: worth a line in the log.
    logger.info("A logo (%d bytes) was uploaded by %s.", len(data), admin.username)
    return {**brand.stored(db), **{"urls": brand.public(db)}}


@router.delete("/api/v1/settings/brand/logo", summary="Remove the logo")
def delete_logo(admin: AdminUser, db: DbSession) -> dict:
    brand.remove_logo(db)
    logger.info("The logo was removed by %s.", admin.username)
    return {**brand.stored(db), **{"urls": brand.public(db)}}
