"""Signing in to GitHub from nexdeck, so that an administrator can share a card in his own name (KARTEN-16 AC-3, AC-4, EC-1, EC-2, EC-8).

The Device Flow of a GitHub App: nexdeck asks GitHub for a code, the administrator types it on github.com, and nexdeck
asks until GitHub says yes. There is no Client Secret anywhere: the Client ID is public (``state.client_id``).

⚠️ The two tokens (the one that works for about eight hours, the one that renews it) are encrypted under a context of
the account they belong to, and the row goes when the account goes. Nothing here puts a token in a log line, an
answer or an error message. The sign-in lasts six months at most, whatever GitHub would allow.

⚠️ The code waits for GitHub's own pace: GitHub names the interval, ``slow_down`` makes it longer, and a request of the
interface that comes earlier than that is answered "still waiting" without asking GitHub at all.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy.orm import Session

from .. import crypto
from ..models import GithubLogin, User
from . import catalog, state

logger = logging.getLogger("nexdeck.workshop")

CODE_URL = "https://github.com/login/device/code"
TOKEN_URL = "https://github.com/login/oauth/access_token"
API = "https://api.github.com"
DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"
#: A sign-in is good for this long at most (about six months).
MAX_DAYS = 183
#: Never ask GitHub faster than this, whatever it said.
MIN_INTERVAL = 5
#: What ``slow_down`` adds when GitHub does not name a new interval.
SLOW_DOWN_BY = 5
#: An access token that ends within this many seconds is renewed first.
RENEW_BEFORE = 60
UNREACHABLE = "GitHub cannot be reached. Try again in a moment."


class GithubError(Exception):
    """Something an administrator is told in a sentence. ``status`` is the HTTP status it becomes."""

    def __init__(self, code: str, message: str, status: int = 502, **more: Any) -> None:
        super().__init__(message)
        self.code, self.message, self.status, self.more = code, message, status, more


def login_needed(why: str = "") -> GithubError:
    return GithubError(
        "github_login_needed",
        "Sign in to GitHub again to go on. What you wrote is kept.",
        409,
        reason=why or "signed_out",
    )


def now() -> float:
    """The clock of the sign-in; a test sets it."""
    return time.time()


def _moment(seconds: float) -> datetime:
    return datetime.fromtimestamp(seconds, UTC)


def _aware(moment: datetime | None) -> datetime | None:
    return moment if moment is None or moment.tzinfo else moment.replace(tzinfo=UTC)


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


@dataclass
class Pending:
    """A code that was handed out and is waited for."""

    device_code: str
    user_code: str
    verification_uri: str
    expires_at: float
    interval: int
    next_at: float
    #: Whose it is (``state.account_of``): a new account that got the number of a deleted one does not inherit the code.
    account: str = ""


_pending: dict[int, Pending] = {}
_locks: dict[int, asyncio.Lock] = {}
_asking: dict[int, asyncio.Lock] = {}


def _account(db: Session, user_id: int) -> str | None:
    user = db.get(User, user_id)
    return state.account_of(user) if user is not None else None


def _waiting(db: Session, user_id: int) -> Pending | None:
    """The code that waits for this account, if there is one that belongs to it."""
    one = _pending.get(user_id)
    if one is not None and one.account != _account(db, user_id):
        _pending.pop(user_id, None)
        return None
    return one


def forget() -> None:
    """Start over (a test, or a new process)."""
    _pending.clear()
    _locks.clear()
    _asking.clear()


# -- asking GitHub ---------------------------------------------------------------------------------


async def call(
    method: str,
    url: str,
    *,
    token: str | None = None,
    data: dict[str, str] | None = None,
    json: Any = None,
    params: dict[str, Any] | None = None,
    form: bool = False,
) -> httpx.Response:
    """One request to GitHub. The answer is the caller's to read; a broken connection is ``github_unreachable``."""
    headers = {
        "Accept": "application/json" if form else "application/vnd.github+json",
        "User-Agent": "nexdeck",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        return await catalog.http_client().request(method, url, headers=headers, data=data, json=json, params=params, timeout=15)
    except httpx.HTTPError as failure:
        # ⚠️ The class of the failure only: the text of an httpx error can carry the address.
        logger.info("GitHub could not be reached (%s %s): %s", method, url.split("?", 1)[0], failure.__class__.__name__)
        raise GithubError("github_unreachable", UNREACHABLE) from None


def _json(response: httpx.Response) -> dict[str, Any]:
    try:
        found = response.json()
    except ValueError:
        found = None
    return found if isinstance(found, dict) else {}


# -- the code ---------------------------------------------------------------------------------------


def view_pending(one: Pending) -> dict[str, Any]:
    return {
        "user_code": one.user_code,
        "verification_uri": one.verification_uri,
        "expires_in": max(0, int(one.expires_at - now())),
        "interval": one.interval,
    }


async def start(db: Session, user_id: int) -> dict[str, Any]:
    """A code and a link for the administrator. Asking again hands out a new code (EC-1)."""
    response = await call("POST", CODE_URL, data={"client_id": state.client_id()}, form=True)
    reply = _json(response)
    if reply.get("error") == "device_flow_disabled":
        raise GithubError("device_flow_off", "The GitHub App of the Workshop has the Device Flow turned off.")
    try:
        one = Pending(
            device_code=str(reply["device_code"]),
            user_code=str(reply["user_code"]),
            verification_uri=str(reply.get("verification_uri") or "https://github.com/login/device"),
            expires_at=now() + int(reply.get("expires_in") or 900),
            interval=max(MIN_INTERVAL, int(reply.get("interval") or MIN_INTERVAL)),
            next_at=0.0,
            account=_account(db, user_id) or "",
        )
    except (KeyError, TypeError, ValueError):
        logger.info("GitHub did not hand out a code (status %s).", response.status_code)
        raise GithubError("github_login_failed", "GitHub did not hand out a code. Try again in a moment.") from None
    one.next_at = now() + one.interval
    _pending[user_id] = one
    return view_pending(one)


async def poll(db: Session, user_id: int) -> dict[str, Any]:
    """Whether the administrator has typed the code yet. Asks GitHub no faster than GitHub allows.

    ⚠️ One question at a time for one account: two requests of the interface at the same moment (two tabs, a slow answer
    and the next tick) would both reach GitHub inside one interval, GitHub would say ``slow_down``, and after the first
    had signed in the second would ask for a code that is gone and report an error. The second waits for the first and
    then finds the answer in its place.
    """
    async with _asking.setdefault(user_id, asyncio.Lock()):
        db.expire_all()
        return await _poll(db, user_id)


async def _poll(db: Session, user_id: int) -> dict[str, Any]:
    one = _waiting(db, user_id)
    if one is None:
        if db.get(GithubLogin, user_id) is not None:
            return {"status": "signed_in", **status(db, user_id)}
        return {"status": "none"}
    if now() >= one.expires_at:
        _pending.pop(user_id, None)
        return {"status": "expired"}
    if now() < one.next_at:
        return {"status": "pending", "interval": one.interval}
    one.next_at = now() + one.interval
    reply = _json(
        await call(
            "POST",
            TOKEN_URL,
            data={"client_id": state.client_id(), "device_code": one.device_code, "grant_type": DEVICE_GRANT},
            form=True,
        )
    )
    one.next_at = now() + one.interval
    error = reply.get("error")
    if error == "authorization_pending":
        return {"status": "pending", "interval": one.interval}
    if error == "slow_down":
        try:
            one.interval = max(one.interval + SLOW_DOWN_BY, int(reply.get("interval") or 0))
        except (TypeError, ValueError):
            one.interval += SLOW_DOWN_BY
        one.next_at = now() + one.interval
        return {"status": "pending", "interval": one.interval}
    if error == "expired_token":
        _pending.pop(user_id, None)
        return {"status": "expired"}
    if error == "access_denied":
        _pending.pop(user_id, None)
        return {"status": "denied"}
    if error or not reply.get("access_token"):
        _pending.pop(user_id, None)
        logger.info("GitHub did not give an access token (%s).", error or "no token")
        raise GithubError("github_login_failed", "GitHub did not complete the sign-in. Start again.")
    who = await _who(str(reply["access_token"]))
    _save(db, user_id, reply, who)
    _pending.pop(user_id, None)
    logger.info("User %s signed in to GitHub as %s.", user_id, who["login"])
    return {"status": "signed_in", **status(db, user_id)}


async def _who(token: str) -> dict[str, str]:
    response = await call("GET", f"{API}/user", token=token)
    reply = _json(response)
    if response.status_code != 200 or "id" not in reply:
        raise GithubError("github_login_failed", "GitHub did not say who signed in. Start again.")
    return {"id": str(reply["id"]), "login": str(reply.get("login") or "")[:100]}


# -- keeping it ------------------------------------------------------------------------------------


def _context(user_id: int) -> str:
    return f"github-login:{user_id}"


def _save(db: Session, user_id: int, reply: dict[str, Any], who: dict[str, str], since: datetime | None = None) -> None:
    """Keep what GitHub handed out. The six months run from the sign-in (``since``), not from the last renewal."""
    moment = now()
    begun = since.timestamp() if since else moment
    limit = begun + MAX_DAYS * 86400
    try:
        lasting = float(reply.get("refresh_token_expires_in") or 0)
    except (TypeError, ValueError):
        lasting = 0.0
    until = min(limit, moment + lasting) if lasting > 0 else limit
    try:
        access_for = float(reply.get("expires_in") or 0)
    except (TypeError, ValueError):
        access_for = 0.0
    row = db.get(GithubLogin, user_id)
    if row is None:
        row = GithubLogin(user_id=user_id)
        db.add(row)
    row.github_id, row.login = who["id"], who["login"]
    row.access = crypto.encrypt_for(str(reply["access_token"]), _context(user_id))
    row.refresh = crypto.encrypt_for(str(reply.get("refresh_token") or ""), _context(user_id))
    row.access_until = _moment(moment + access_for) if access_for > 0 else None
    row.until = _moment(until)
    row.created_at = _moment(begun)
    db.commit()


def status(db: Session, user_id: int) -> dict[str, Any]:
    """Whether this administrator is signed in, as whom, until when, and whether a code is waiting for him."""
    row = db.get(GithubLogin, user_id)
    if row is not None and _aware(row.until) <= _moment(now()):
        drop(db, user_id)
        row = None
    waiting = _waiting(db, user_id)
    if waiting is not None and now() >= waiting.expires_at:
        _pending.pop(user_id, None)
        waiting = None
    return {
        "signed_in": row is not None,
        "login": row.login if row else None,
        "github_id": row.github_id if row else None,
        "until": _iso(_aware(row.until)) if row else None,
        "pending": view_pending(waiting) if waiting else None,
    }


def drop(db: Session, user_id: int) -> None:
    """Sign out: the tokens are gone from here. (A token cannot be withdrawn at GitHub without a secret; it ends by itself.)"""
    row = db.get(GithubLogin, user_id)
    if row is not None:
        db.delete(row)
        db.commit()


def sign_out(db: Session, user_id: int) -> None:
    drop(db, user_id)
    _pending.pop(user_id, None)


@dataclass(frozen=True)
class Access:
    """The token to use now, and whose it is."""

    token: str
    github_id: str
    login: str


async def session(db: Session, user_id: int) -> Access:
    """The sign-in of an administrator, renewed when it is about to end. Raises ``github_login_needed`` when there is none (EC-2)."""
    row = db.get(GithubLogin, user_id)
    if row is None:
        raise login_needed("signed_out")
    if _aware(row.until) <= _moment(now()):
        drop(db, user_id)
        raise login_needed("expired")
    if row.access_until is None or _aware(row.access_until) - _moment(now()) > timedelta(seconds=RENEW_BEFORE):
        return _read(row, user_id)
    # A renewing token is used once: two requests at the same time must not both spend it.
    lock = _locks.setdefault(user_id, asyncio.Lock())
    async with lock:
        db.expire_all()
        row = db.get(GithubLogin, user_id)
        if row is None:
            raise login_needed("signed_out")
        if row.access_until is None or _aware(row.access_until) - _moment(now()) > timedelta(seconds=RENEW_BEFORE):
            return _read(row, user_id)
        return await _renew(db, row, user_id)


def _read(row: GithubLogin, user_id: int) -> Access:
    try:
        return Access(crypto.decrypt_for(row.access, _context(user_id)), row.github_id, row.login)
    except crypto.SecretUnreadable:
        raise login_needed("unreadable") from None


async def _renew(db: Session, row: GithubLogin, user_id: int) -> Access:
    try:
        refresh = crypto.decrypt_for(row.refresh, _context(user_id))
    except crypto.SecretUnreadable:
        drop(db, user_id)
        raise login_needed("unreadable") from None
    if not refresh:
        drop(db, user_id)
        raise login_needed("expired")
    reply = _json(
        await call(
            "POST",
            TOKEN_URL,
            data={"client_id": state.client_id(), "grant_type": "refresh_token", "refresh_token": refresh},
            form=True,
        )
    )
    if reply.get("error") or not reply.get("access_token"):
        # Withdrawn at GitHub, or too old: only a new sign-in helps (EC-2).
        logger.info("GitHub did not renew the sign-in of user %s (%s).", user_id, reply.get("error") or "no token")
        drop(db, user_id)
        raise login_needed("revoked")
    _save(db, user_id, reply, {"id": row.github_id, "login": row.login}, since=_aware(row.created_at))
    return _read(row, user_id)
