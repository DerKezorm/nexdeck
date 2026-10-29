"""The thumb of an administrator on the discussion of a Card shop entry, set from nexdeck (the "thumb in nexdeck" change).

The discussion of an entry is where GitHub counts the 👍; the action of the Workshop reads the count once a day into the
catalog. This module reads and sets the reaction of one administrator on that discussion with the GraphQL API of GitHub.

⚠️ The reaction is made with the sign-in of the administrator who asked, never with that of another and never with the
key of the shop. The discussion to react to is the one in the catalog entry: nothing from the request names it. Nothing
here puts a token in a log line, an answer or an error message.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from sqlalchemy.orm import Session

from ..models import User
from . import catalog, github_login
from .github_login import GithubError, login_needed

logger = logging.getLogger("nexdeck.workshop")

GRAPHQL = f"{github_login.API}/graphql"
CONTENT = "THUMBS_UP"
NO_DISCUSSIONS = "The Workshop app may not react to discussions yet. Rate it on GitHub instead."

#: ⚠️ With the repository: a catalog may name the id of any discussion, and the thumb goes only on one of the Workshop.
READ = "query($id: ID!) { node(id: $id) { ... on Discussion { id repository { nameWithOwner } reactionGroups { content viewerHasReacted } } } }"
#: For a catalog that names the address of the discussion and not its id.
READ_BY_ADDRESS = (
    "query($url: URI!) { resource(url: $url) { ... on Discussion { id repository { nameWithOwner } reactionGroups { content viewerHasReacted } } } }"
)
ADD = "mutation($id: ID!) { addReaction(input: {subjectId: $id, content: THUMBS_UP}) { reaction { content } } }"
REMOVE = "mutation($id: ID!) { removeReaction(input: {subjectId: $id, content: THUMBS_UP}) { reaction { content } } }"

_locks: dict[tuple[int, str], asyncio.Lock] = {}
#: Locks that nobody holds are dropped once there are this many.
_KEEP = 500


def forget() -> None:
    _locks.clear()


def _lock(user_id: int, entry_id: str) -> asyncio.Lock:
    if len(_locks) > _KEEP:
        for key in [key for key, one in _locks.items() if not one.locked()]:
            del _locks[key]
    return _locks.setdefault((user_id, entry_id), asyncio.Lock())


def target(entry: catalog.Entry, repo: str) -> tuple[str, str] | None:
    """What the catalog names of the discussion: ``("id", node id)`` or ``("url", address in this repository)``; none when it names nothing usable."""
    if entry.discussion_id:
        return "id", entry.discussion_id
    if entry.discussion and re.fullmatch(rf"https://github\.com/{re.escape(repo)}/discussions/\d{{1,9}}", entry.discussion):
        return "url", entry.discussion
    return None


def _rejected(why: str) -> GithubError:
    logger.info("GitHub did not take the thumb (%s).", why)
    return GithubError("github_rejected", "GitHub did not take the thumb. Try again later.")


async def _ask(db: Session, user: User, query: str, variables: dict[str, str]) -> dict[str, Any]:
    """One GraphQL question in the name of this administrator; the ``data`` of the answer."""
    access = await github_login.session(db, user.id)
    response = await github_login.call("POST", GRAPHQL, token=access.token, json={"query": query, "variables": variables})
    code = response.status_code
    if code == 401:
        github_login.drop(db, user.id)
        raise login_needed("revoked")
    if code == 429 or (code == 403 and _asks_to_wait(response)):
        raise GithubError("github_rate_limited", "GitHub asks you to wait a moment before the next request. Try again shortly.")
    if code >= 500:
        raise GithubError("github_unreachable", github_login.UNREACHABLE)
    try:
        reply = response.json()
    except ValueError:
        reply = None
    if not isinstance(reply, dict):
        raise _rejected(f"status {code}")
    problems = [one for one in (reply.get("errors") or []) if isinstance(one, dict)]
    for one in problems:
        words = str(one.get("message") or "")
        if one.get("type") == "FORBIDDEN" or "not accessible by integration" in words:
            raise GithubError("github_no_discussions", NO_DISCUSSIONS, 403)
    if code == 403:
        raise GithubError("github_no_discussions", NO_DISCUSSIONS, 403)
    if problems or code != 200 or not isinstance(reply.get("data"), dict):
        raise _rejected(", ".join(str(one.get("type") or "error") for one in problems) or f"status {code}")
    return reply["data"]


def _asks_to_wait(response: Any) -> bool:
    from .submit import _asks_to_wait as asks  # noqa: PLC0415, SLF001

    return asks(response)


async def _look(db: Session, user: User, named: tuple[str, str], repo: str) -> dict[str, Any] | None:
    """The discussion with this administrator's reactions on it, or none when GitHub has no such discussion for him.

    ⚠️ None as well for a discussion outside the Workshop repository: an id in the catalog could name one anywhere on
    GitHub, and the thumb would be set there in the name of the administrator.
    """
    if named[0] == "id":
        data = await _ask(db, user, READ, {"id": named[1]})
        found = data.get("node")
    else:
        data = await _ask(db, user, READ_BY_ADDRESS, {"url": named[1]})
        found = data.get("resource")
    if not isinstance(found, dict) or not found.get("id"):
        return None
    home = found.get("repository")
    if not isinstance(home, dict) or str(home.get("nameWithOwner") or "").lower() != repo.lower():
        logger.info("The catalog names a discussion outside the Workshop repository; no thumb is read or set there.")
        return None
    return found


async def read(db: Session, user: User, entry: catalog.Entry, repo: str) -> dict[str, Any]:
    """Whether this administrator is signed in and has put his thumb on the entry. GitHub is asked only when he is signed in and the entry has a discussion."""
    if not github_login.status(db, user.id)["signed_in"]:
        return {"signed_in": False, "on": None}
    named = target(entry, repo)
    if named is None:
        return {"signed_in": True, "on": None}
    try:
        found = await _look(db, user, named, repo)
    except GithubError as problem:
        if problem.code == "github_login_needed":
            return {"signed_in": False, "on": None}
        raise
    if found is None:
        return {"signed_in": True, "on": None}
    groups = found.get("reactionGroups")
    on = any(isinstance(one, dict) and one.get("content") == CONTENT and one.get("viewerHasReacted") is True for one in groups) if isinstance(groups, list) else False
    return {"signed_in": True, "on": on}


async def put(db: Session, user: User, entry: catalog.Entry, repo: str, on: bool) -> dict[str, Any]:
    """Set (or take away) the thumb of this administrator. Asked twice at once, the second waits for the first and then does the same again, which GitHub takes as it is."""
    named = target(entry, repo)
    if named is None:
        raise GithubError("no_discussion", "This entry has no discussion on GitHub to react to.", 409)
    async with _lock(user.id, entry.id):
        found = await _look(db, user, named, repo)
        if found is None:
            raise GithubError("no_discussion", "This entry has no discussion on GitHub to react to.", 409)
        await _ask(db, user, ADD if on else REMOVE, {"id": str(found["id"])})
    logger.info("%s %s the thumb on %s.", user.username, "set" if on else "took away", entry.id)
    return {"on": on}
