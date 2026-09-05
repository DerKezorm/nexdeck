"""Sign in with Plex for the Plex integration: a PIN at plex.tv instead of a copied token."""

from __future__ import annotations

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from ..deps import MemberUser, error
from ..services import plex_auth

router = APIRouter(prefix="/api/v1/plex", tags=["plex"])


class ServersBody(BaseModel):
    token: str = Field(min_length=1, max_length=400)


def _plex_failure(failure: plex_auth.PlexTvError):
    return error(failure.code, failure.message, status.HTTP_502_BAD_GATEWAY)


@router.post("/pin", summary="Start a sign-in with Plex")
async def start_pin(user: MemberUser) -> dict:
    """Returns the PIN and the plex.tv address the browser opens; poll the PIN afterwards."""
    try:
        return await plex_auth.begin_login()
    except plex_auth.PlexTvError as failure:
        raise _plex_failure(failure) from failure


@router.get("/pin/{pin_id}", summary="Check whether the Plex sign-in is complete")
async def poll_pin(pin_id: str, code: str, user: MemberUser) -> dict:
    """``token`` stays null until the person has agreed at plex.tv."""
    try:
        token = await plex_auth.poll_login(pin_id, code)
        username = await plex_auth.account_name(token) if token else None
    except plex_auth.PlexTvError as failure:
        raise _plex_failure(failure) from failure
    return {"token": token, "username": username}


@router.post("/servers", summary="List the Plex servers an account may use")
async def list_servers(body: ServersBody, user: MemberUser) -> list[dict]:
    """The token travels in the body, never in the address, so it stays out of logs."""
    try:
        return await plex_auth.servers(body.token)
    except plex_auth.PlexTvError as failure:
        raise _plex_failure(failure) from failure
