"""Serving the profile pictures."""

from __future__ import annotations

from fastapi import APIRouter, status
from fastapi.responses import Response

from ..deps import CurrentUser, error
from ..services import avatars

router = APIRouter(prefix="/api/v1/avatars", tags=["users"])


@router.get("/{name}", summary="Serve a profile picture")
def serve(name: str, user: CurrentUser) -> Response:
    """Signed-in only, unlike the board backgrounds: a kiosk display shows
    boards, never faces. The file name changes with every new picture, so the
    answer may be cached for a week."""
    try:
        data, content_type = avatars.read(name)
    except avatars.AvatarError as failure:
        raise error(failure.code, failure.message, status.HTTP_404_NOT_FOUND) from failure
    return Response(data, media_type=content_type, headers={"Cache-Control": "private, max-age=604800"})
