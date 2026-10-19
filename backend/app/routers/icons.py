"""Icon proxy and search."""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from ..deps import CurrentUser, error
from ..services import icons

router = APIRouter(prefix="/api/v1/icons", tags=["icons"])


@router.get("/search", summary="Search service logos by name")
async def search_icons(q: str, user: CurrentUser) -> list[dict]:
    return await icons.search(q)


@router.get("/names", summary="Every logo name the picker can offer")
async def icon_names(user: CurrentUser) -> list[dict]:
    return await icons.all_names()


@router.get("/{name}.{ext}", summary="Serve a service logo from the cache")
async def icon(name: str, ext: str, on: str = "") -> Response:
    """Public, like any image: kiosk displays load icons without a session.

    ``on=dark`` or ``on=light`` names the page the logo stands on: a logo that
    has a variant for that ground is served in it, so a black one does not
    vanish on a dark board.
    """
    wanted = name.lower()
    chosen = icons.variant(wanted, on) if on in icons.VARIANT_FOR and icons.valid_name(wanted) else wanted
    result = await icons.fetch_icon(chosen, ext.lower())
    if result is None and chosen != wanted:
        result = await icons.fetch_icon(wanted, ext.lower())
    if result is None:
        raise error("not_found", "No icon with that name.", status.HTTP_404_NOT_FOUND)
    content, content_type = result
    return Response(content=content, media_type=content_type, headers={"Cache-Control": "public, max-age=604800"})
