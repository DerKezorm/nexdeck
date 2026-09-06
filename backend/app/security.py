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
