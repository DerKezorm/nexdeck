"""Sharing a card in the Card shop from nexdeck: the GitHub sign-in, the submission and "My submissions" (KARTEN-16).

Administrators only. The sign-in is the Device Flow of a GitHub App (``workshop/github_login.py``); nothing here asks
GitHub until an administrator starts to sign in or to share.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Response, status

from ..deps import AdminUser, DbSession
from ..workshop import github_login

router = APIRouter(prefix="/api/v1/workshop", tags=["workshop"])
logger = logging.getLogger("nexdeck.workshop")


def failure(problem: github_login.GithubError) -> HTTPException:
    return HTTPException(problem.status, {"code": problem.code, "message": problem.message, **problem.more})


# -- the sign-in to GitHub -------------------------------------------------------------------------


@router.get("/github", summary="Whether you are signed in to GitHub, as whom, and until when")
def read_github(user: AdminUser, db: DbSession) -> dict[str, Any]:
    """Asks nobody. A code that is waiting to be typed on github.com is part of the answer."""
    return github_login.status(db, user.id)


@router.post("/github/login", summary="Start signing in to GitHub: a code and a link")
async def start_github_login(user: AdminUser) -> dict[str, Any]:
    """Every call hands out a new code, so a code that ran out after fifteen minutes is replaced by asking again (EC-1)."""
    try:
        return await github_login.start(user.id)
    except github_login.GithubError as problem:
        raise failure(problem) from problem


@router.post("/github/login/poll", summary="Ask whether the code was typed on github.com")
async def poll_github_login(user: AdminUser, db: DbSession) -> dict[str, Any]:
    """``pending`` (with the interval to wait), ``signed_in``, ``expired``, ``denied`` or ``none``. GitHub is asked no faster than it allows."""
    try:
        return await github_login.poll(db, user.id)
    except github_login.GithubError as problem:
        raise failure(problem) from problem


@router.delete("/github", status_code=status.HTTP_204_NO_CONTENT, summary="Sign out of GitHub: the tokens are deleted here")
def sign_out_of_github(user: AdminUser, db: DbSession) -> Response:
    github_login.sign_out(db, user.id)
    logger.info("%s signed out of GitHub.", user.username)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
