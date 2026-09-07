"""Password hashing (bcrypt) and signed session tokens (JWT).

Sessions are HttpOnly cookies carrying a JWT. Every token records its issue
time in milliseconds next to the second-resolution ``iat`` so that a password
change can invalidate exactly the tokens issued before it, without either
rounding direction opening a hole.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt

from .config import get_settings

ALGORITHM = "HS256"
_BCRYPT_MAX_BYTES = 72
UNUSABLE_PASSWORD = "!no-password-set"


def _signing_key() -> bytes:
    secret = get_settings().resolved_secret_key().encode("utf-8")
    return hashlib.sha256(b"nexdeck-session:" + secret).digest()


def _password_bytes(password: str) -> bytes:
    return password.encode("utf-8")[:_BCRYPT_MAX_BYTES]


def hash_password(password: str) -> str:
    rounds = get_settings().bcrypt_rounds
    return bcrypt.hashpw(_password_bytes(password), bcrypt.gensalt(rounds)).decode("utf-8")


#: A real hash of a value nobody signs in with, so a sign-in for a name that
#: does not exist costs the same as one that does.
_DECOY = bcrypt.hashpw(b"nexdeck-decoy", bcrypt.gensalt(4)).decode("utf-8")


def prune_sessions(db) -> int:  # noqa: ANN001
    """Drop sessions nobody can use any more.

    ⚠️ The table only ever grew: a row per sign-in, and nothing removed one.
    Worse than the size was the list under "My sessions", which read the rows
    and so offered to sign out sessions that had run out months ago as though
    they were live.

    Gone: anything withdrawn, and anything not seen for longer than a session
    lasts. The cookie of such a row is refused by ``deps`` either way, so this
    removes nothing that still works.
    """
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import delete, or_

    from .config import get_settings
    from .models import Session

    stale = datetime.now(UTC) - timedelta(days=get_settings().session_days)
    done = db.execute(delete(Session).where(or_(Session.revoked.is_(True), Session.last_seen_at < stale)))
    return int(done.rowcount or 0)


def burn_a_password_check(password: str) -> bool:
    """Spend the time a real check would, and always say no.

    ⚠️ Cheap rounds on purpose: this only has to take a while, not protect
    anything, and making it as expensive as the real thing would hand anyone
    an amplifier for the cost of one request.
    """
    bcrypt.checkpw(_password_bytes(password), _DECOY.encode("utf-8"))
    return False


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(_password_bytes(password), password_hash.encode("utf-8"))
    except ValueError:
        return False


def has_usable_password(password_hash: str) -> bool:
    return password_hash != UNUSABLE_PASSWORD


def now_ms() -> int:
    return int(datetime.now(UTC).timestamp() * 1000)


def create_session_token(user_id: int, session_id: int) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "sid": session_id,
        "iat": int(now.timestamp()),
        "ms": int(now.timestamp() * 1000),
        "exp": int((now + timedelta(days=settings.session_days)).timestamp()),
    }
    return jwt.encode(payload, _signing_key(), algorithm=ALGORITHM)


@dataclass(frozen=True)
class SessionClaims:
    user_id: int
    session_id: int
    issued_ms: int


def read_session_token(token: str) -> SessionClaims | None:
    try:
        payload = jwt.decode(token, _signing_key(), algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None
    try:
        return SessionClaims(
            user_id=int(payload["sub"]),
            session_id=int(payload["sid"]),
            issued_ms=int(payload.get("ms", 0)),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _kiosk_key() -> bytes:
    secret = get_settings().resolved_secret_key().encode("utf-8")
    return hashlib.sha256(b"nexdeck-kiosk:" + secret).digest()


def create_kiosk_cookie(kiosk_id: int, expires: datetime | None) -> tuple[str, int]:
    """A signed stand-in for a kiosk token, and how long it is good for.

    ⚠️ The token itself used to be appended to every image, video and event
    address, because none of those can carry a header. Each of those lines
    lands in the reverse proxy log, and a display shows a few thousand a day.
    The display hands its token in once and gets this back.
    """
    now = datetime.now(UTC)
    ends = now + timedelta(days=1)
    if expires is not None and expires < ends:
        ends = expires
    payload = {"kid": int(kiosk_id), "iat": int(now.timestamp()), "exp": int(ends.timestamp())}
    return jwt.encode(payload, _kiosk_key(), algorithm=ALGORITHM), int((ends - now).total_seconds())


def read_kiosk_cookie(raw: str) -> int | None:
    """The kiosk token's number, or None if the cookie is not ours or is old."""
    try:
        payload = jwt.decode(raw, _kiosk_key(), algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None
    try:
        return int(payload["kid"])
    except (KeyError, TypeError, ValueError):
        return None


def _step_key() -> bytes:
    secret = get_settings().resolved_secret_key().encode("utf-8")
    return hashlib.sha256(b"nexdeck-second-step:" + secret).digest()


def create_step_token(user_id: int) -> str:
    """A ticket that says "the password was right", and nothing else.

    ⚠️ Not a session. It opens no board and reads no data; the only thing it
    can be exchanged for is a session, and only together with a code. Five
    minutes is long enough to find a phone and short enough that a ticket left
    on a shared machine is worth nothing.
    """
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "use": "second-step",
        "iat": int(now.timestamp()),
        "ms": int(now.timestamp() * 1000),
        "exp": int((now + timedelta(minutes=5)).timestamp()),
    }
    return jwt.encode(payload, _step_key(), algorithm=ALGORITHM)


def read_step_token(token: str) -> tuple[int, int] | None:
    """The account and when the ticket was issued, or None."""
    try:
        payload = jwt.decode(token, _step_key(), algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None
    if payload.get("use") != "second-step":
        return None
    try:
        return int(payload["sub"]), int(payload.get("ms", 0))
    except (KeyError, TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Opaque tokens: API tokens and kiosk tokens
# ---------------------------------------------------------------------------


def new_opaque_token(prefix: str) -> tuple[str, str, str]:
    """Return ``(token, token_hash, display_prefix)``.

    Only the hash is stored. The display prefix lets a user recognise a token
    in a list without the list ever showing the token itself.
    """
    raw = secrets.token_urlsafe(32)
    token = f"{prefix}_{raw}"
    return token, hash_token(token), token[: len(prefix) + 7]


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def tokens_match(token: str, token_hash: str) -> bool:
    return hmac.compare_digest(hash_token(token), token_hash)
