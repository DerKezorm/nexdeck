"""Sharing a card in the Card shop from nexdeck: the GitHub sign-in, the submission and "My submissions" (KARTEN-16).

Administrators only. The sign-in is the Device Flow of a GitHub App (``workshop/github_login.py``); nothing here asks
GitHub until an administrator starts to sign in or to share.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, Field

from ..deps import AdminUser, DbSession
from ..workshop import github_login, submit

router = APIRouter(prefix="/api/v1/workshop", tags=["workshop"])
logger = logging.getLogger("nexdeck.workshop")


def failure(problem: github_login.GithubError | submit.SubmitError) -> HTTPException:
    return HTTPException(problem.status, {"code": problem.code, "message": problem.message, **problem.more})


# -- the sign-in to GitHub -------------------------------------------------------------------------


@router.get("/github", summary="Whether you are signed in to GitHub, as whom, and until when")
def read_github(user: AdminUser, db: DbSession) -> dict[str, Any]:
    """Asks nobody. A code that is waiting to be typed on github.com is part of the answer."""
    return github_login.status(db, user.id)


@router.post("/github/login", summary="Start signing in to GitHub: a code and a link")
async def start_github_login(user: AdminUser, db: DbSession) -> dict[str, Any]:
    """Every call hands out a new code, so a code that ran out after fifteen minutes is replaced by asking again (EC-1)."""
    try:
        return await github_login.start(db, user.id)
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


# -- sharing ---------------------------------------------------------------------------------------


class ShareBody(BaseModel):
    """What the dialog of "Share in the Card shop" sends: which card or connection, and what the administrator wrote."""

    type: Literal["card", "integration"]
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,59}$")
    category: str = Field(default="", max_length=20)
    description: str = Field(default="", max_length=submit.MAX_TEXT * 2)
    changes: str = Field(default="", max_length=submit.MAX_TEXT * 2)
    license: bool = False

    def form(self) -> submit.Form:
        return submit.Form(self.category, self.description, self.changes, self.license)


class ResendBody(BaseModel):
    issue: int = Field(ge=1, le=10**9)


@router.post("/submit/check", summary="What the dialog of sharing shows: what is wrong, what to be warned of, new or update, how many today")
async def check_submission(body: ShareBody, user: AdminUser, db: DbSession) -> dict[str, Any]:
    """Asks GitHub only when the administrator is signed in, and then for the issues of his own account (KARTEN-16 AC-2, AC-7, AC-8, EC-4, EC-9)."""
    try:
        return await submit.check(db, user, body.type, body.slug, body.form())
    except (submit.SubmitError, github_login.GithubError) as problem:
        raise failure(problem) from problem


@router.post("/submit", summary="Share a card or an own connection in the Card shop: an issue in the Workshop under your GitHub name")
async def share(body: ShareBody, user: AdminUser, db: DbSession) -> dict[str, Any]:
    """Sent once however often it is asked: an open issue of this account under the same short name is updated, not doubled (EC-6, EC-7)."""
    try:
        return await submit.submit(db, user, body.type, body.slug, body.form())
    except (submit.SubmitError, github_login.GithubError) as problem:
        raise failure(problem) from problem


@router.post("/submit/resend", summary="Send a corrected card into the issue it was handed in with")
async def resend(body: ResendBody, user: AdminUser, db: DbSession) -> dict[str, Any]:
    """"Fix and resend": the card as it is saved now replaces the definition in that issue (KARTEN-16 AC-10)."""
    try:
        return await submit.resend(db, user, body.issue)
    except (submit.SubmitError, github_login.GithubError) as problem:
        raise failure(problem) from problem


@router.post("/submit/file", summary="The submission as a file and a link to the form on GitHub, for somebody who does not sign in")
async def submission_file(body: ShareBody, user: AdminUser, db: DbSession) -> dict[str, Any]:
    """Asks GitHub nothing (KARTEN-16 AC-9)."""
    try:
        return await submit.offline(db, user, body.type, body.slug, body.form())
    except (submit.SubmitError, github_login.GithubError) as problem:
        raise failure(problem) from problem


@router.get("/submissions", summary="What became of the cards you shared: in review, failed with the reasons, in the shop, removed")
async def my_submissions(user: AdminUser, db: DbSession) -> dict[str, Any]:
    """Read from the issues of your GitHub account and the comments of the action each time (KARTEN-16 AC-6, EC-6)."""
    try:
        return await submit.submissions(db, user)
    except (submit.SubmitError, github_login.GithubError) as problem:
        raise failure(problem) from problem
