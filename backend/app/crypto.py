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

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from .config import get_settings

PREFIX = "enc:"
_cached: MultiFernet | None = None


class SecretUnreadable(Exception):
    """The stored value was encrypted with a different key."""


#: How hard it is to try one guess at a hand-written secret key.
#:
#: ⚠️ The salt is fixed, and that is a deliberate half measure. A per
#: installation salt would need a second file next to ``secret.key``, and
#: losing it would make every stored secret unreadable, which is the failure
#: this whole module exists to avoid. What the fixed salt still buys is the
#: only thing that matters here: an operator who set ``NEXDECK_SECRET_KEY`` to
#: something short now costs an attacker with the database file 210000 rounds
#: per guess instead of one hash. The generated key is 288 bits of randomness
#: and was never at risk either way.
ROUNDS = 210_000
SALT = b"nexdeck-secrets-v2"


def _key_from(secret: bytes) -> bytes:
    derived = hashlib.pbkdf2_hmac("sha256", b"nexdeck-secrets:" + secret, SALT, ROUNDS)
    return base64.urlsafe_b64encode(derived)


def _legacy_key_from(secret: bytes) -> bytes:
    """One SHA-256, as it was until 07.09.2026.

    ⚠️ Still here on purpose, and only for reading. Everything encrypted before
    that day was written with it, and nexdeck 0.1.0 is out in the world. A
    change that silently makes every stored API key unreadable would be worse
    than the weakness it fixes. Values are rewritten with the new key whenever
    they are saved again.
    """
    return base64.urlsafe_b64encode(hashlib.sha256(b"nexdeck-secrets:" + secret).digest())


#: Derived keys by the secret they came from.
#:
#: ⚠️ Not the same thing as ``_cached``, which one call to ``forget_key``
#: empties. Stretching costs about 0.2 s, and the test suite drops the cached
#: key for every one of its several hundred cases; without this, the price of
#: doing the derivation properly would have been two minutes of every run, and
#: the next person would have lowered the rounds to get them back.
_derived: dict[bytes, MultiFernet] = {}


def _fernet() -> MultiFernet:
    global _cached
    if _cached is None:
        secret = get_settings().resolved_secret_key().encode("utf-8")
        made = _derived.get(secret)
        if made is None:
            # First key encrypts, every key decrypts.
            made = MultiFernet([Fernet(_key_from(secret)), Fernet(_legacy_key_from(secret))])
            if len(_derived) < 8:
                _derived[secret] = made
        _cached = made
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
