"""Sign in with Plex for the Plex integration: a PIN at plex.tv instead of a copied token."""

from __future__ import annotations

import logging

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from ..deps import MemberUser, error
from ..services import plex_auth

router = APIRouter(prefix="/api/v1/plex", tags=["plex"])

logger = logging.getLogger("nexdeck.plex")


class ServersBody(BaseModel):
    token: str = Field(min_length=1, max_length=400)


def _plex_failure(failure: plex_auth.PlexTvError):
    return error(failure.code, failure.message, status.HTTP_502_BAD_GATEWAY)


class PlexPinBody(BaseModel):
    """The code that claims a PIN, in the body so it stays out of every log."""

    code: str = Field(min_length=1, max_length=64)


@router.post("/pin", summary="Start a sign-in with Plex")
async def start_pin(user: AdminUser) -> dict:
    """Returns the PIN and the plex.tv address the browser opens; poll the PIN afterwards.

    ⚠️ Administrators only. These three routes exist to fill in a Plex
    connection, and only an administrator may create one; leaving them open to
    every member let anybody start sign-ins at plex.tv from this server and
    read back which servers an account can reach.
    """
    try:
        return await plex_auth.begin_login()
    except plex_auth.PlexTvError as failure:
        raise _plex_failure(failure) from failure


@router.post("/pin/{pin_id}", summary="Check whether the Plex sign-in is complete")
async def poll_pin(pin_id: str, body: PlexPinBody, user: AdminUser) -> dict:
    """``token`` stays null until the person has agreed at plex.tv.

    ⚠️ POST with the code in the body, not GET with it in the address. The
    code claims the PIN, and the browser polls this every two seconds: as a
    query parameter it was written into nexdeck's own log and into every line
    of the reverse proxy in front of it, where it stays long after the sign-in.
    """
    code = body.code
    try:
        token = await plex_auth.poll_login(pin_id, code)
        username = await plex_auth.account_name(token) if token else None
    except plex_auth.PlexTvError as failure:
        raise _plex_failure(failure) from failure
    if token:
        # Somebody linked a Plex account to nexdeck. The token is never
        # written down here; that it happened, and to whom, is.
        logger.info("A Plex account (%s) was linked by %s.", username or "unknown", user.username)
    return {"token": token, "username": username}


@router.post("/servers", summary="List the Plex servers an account may use")
async def list_servers(body: ServersBody, user: MemberUser) -> list[dict]:
    """The token travels in the body, never in the address, so it stays out of logs."""
    try:
        return await plex_auth.servers(body.token)
    except plex_auth.PlexTvError as failure:
        raise _plex_failure(failure) from failure
