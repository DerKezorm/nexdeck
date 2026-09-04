"""Encryption of secrets stored in the database (API keys, passwords, tokens).

The Fernet key is derived from the installation secret with a purpose prefix,
so it can never coincide with the session signing key in ``security.py``.
The derived key is cached per process; a key file swapped on disk therefore
takes effect after a restart, which is the safer of the two behaviours: a
swapped key makes every stored secret unreadable, and the operator should see
that all at once, not one request at a time.
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from .config import get_settings

PREFIX = "enc:"
_cached: Fernet | None = None


class SecretUnreadable(Exception):
    """The stored value was encrypted with a different key."""


def _fernet() -> Fernet:
    global _cached
    if _cached is None:
        secret = get_settings().resolved_secret_key().encode("utf-8")
        digest = hashlib.sha256(b"nexdeck-secrets:" + secret).digest()
        _cached = Fernet(base64.urlsafe_b64encode(digest))
    return _cached


def forget_key() -> None:
    global _cached
    _cached = None


def encrypt(value: str) -> str:
    if value.startswith(PREFIX):
        return value
    return PREFIX + _fernet().encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt(value: str) -> str:
    """Decrypt a stored value; plain values are passed through unchanged."""
    if not value.startswith(PREFIX):
        return value
    try:
        return _fernet().decrypt(value[len(PREFIX) :].encode("utf-8")).decode("utf-8")
    except InvalidToken as error:
        raise SecretUnreadable(
            "A stored secret cannot be decrypted. The NEXDECK_SECRET_KEY or the "
            "data/secret.key file no longer matches the database."
        ) from error


def is_encrypted(value: str) -> bool:
    return value.startswith(PREFIX)
