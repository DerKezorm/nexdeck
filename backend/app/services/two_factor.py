"""The second factor: a time code, and a way back in when the phone is gone.

⚠️ **Offered, not forced.** nexmail makes this compulsory, and rightly so: a
mail client is the place every "forgot my password" ends up. A dashboard is
not, and a wall display has nobody to type a code. So each person turns it on
for themselves, and an administrator who wants it for everybody says so once
in the settings.

⚠️ **The QR code is drawn here, in this process.** A secret handed to a
foreign QR service to be drawn is not a secret any more.

⚠️ **Kiosk links and API tokens are untouched.** They have no sign-in to put a
second step in front of, and pretending otherwise would only mean a wall
display that stops working with no way to fix it.
"""

from __future__ import annotations

import hashlib
import io
import logging
import secrets
import time

import pyotp
import segno
from sqlalchemy.orm import Session as DbSessionType

from ..crypto import decrypt, encrypt
from ..models import RecoveryCode, Setting, User, utcnow

logger = logging.getLogger("nexdeck.two_factor")

STEP_SECONDS = 30
#: One step either side, so a phone whose clock drifts a little still works.
TOLERANCE = 1
CODE_COUNT = 10
SETTING_KEY = "security"


# ---------------------------------------------------------------------------
# The secret
# ---------------------------------------------------------------------------


def new_secret() -> str:
    return pyotp.random_base32()


def store_secret(user: User, secret: str) -> None:
    """Keep the secret, and leave it unconfirmed until a code proves it works."""
    user.totp_secret = encrypt(secret)
    user.totp_confirmed = False
    user.totp_last_step = 0


def read_secret(user: User) -> str:
    return decrypt(user.totp_secret) if user.totp_secret else ""


def enabled(user: User) -> bool:
    return bool(user.totp_confirmed and user.totp_secret)


def otpauth_url(user: User, secret: str, issuer: str = "nexdeck") -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=user.username, issuer_name=issuer)


def qr_svg(url: str) -> str:
    """The QR code as an SVG string, ready to drop into the page.

    ``BytesIO`` and not ``StringIO``: segno writes bytes even for SVG, and a
    text buffer fails with "string argument expected, got 'bytes'".

    ``xmldecl=False``: this goes inside an HTML page, where an XML declaration
    has no business.
    """
    buffer = io.BytesIO()
    segno.make(url, error="m").save(buffer, kind="svg", scale=5, border=2, dark="#0d1219", xmldecl=False)
    return buffer.getvalue().decode("utf-8")


def check_code(db: DbSessionType, user: User, code: str) -> bool:
    """Check a time code and, if it is good, use it up.

    ⚠️ A code that was accepted is never accepted again. The last good step is
    remembered and nothing at or below it is taken. Without that, a code
    somebody read over a shoulder is good for another half minute, which is
    longer than anybody needs to type it in somewhere else.
    """
    secret = read_secret(user)
    code = (code or "").strip().replace(" ", "")
    if not secret or not code.isdigit():
        return False
    totp = pyotp.TOTP(secret, interval=STEP_SECONDS)
    current = int(time.time()) // STEP_SECONDS
    for offset in range(-TOLERANCE, TOLERANCE + 1):
        step = current + offset
        if step <= user.totp_last_step:
            continue
        if secrets.compare_digest(totp.at(step * STEP_SECONDS), code):
            user.totp_last_step = step
            db.commit()
            return True
    return False


# ---------------------------------------------------------------------------
# Recovery codes
# ---------------------------------------------------------------------------


def _hash(code: str) -> str:
    return hashlib.sha256(code.replace("-", "").replace(" ", "").upper().encode("ascii")).hexdigest()


def _one_code() -> str:
    """Ten characters that cannot be confused, in two groups.

    No 0/O and no 1/I/L: these get copied off paper, usually by somebody who
    is already having a bad day.
    """
    alphabet = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
    raw = "".join(secrets.choice(alphabet) for _ in range(10))
    return f"{raw[:5]}-{raw[5:]}"


def new_codes(db: DbSessionType, user: User) -> list[str]:
    """Fresh codes, old ones thrown away. Returned in the clear exactly once."""
    for old in list(user.recovery_codes):
        db.delete(old)
    plain = [_one_code() for _ in range(CODE_COUNT)]
    for code in plain:
        db.add(RecoveryCode(user_id=user.id, code_hash=_hash(code)))
    db.commit()
    logger.info("New recovery codes were made for %s.", user.username)
    return plain


def use_code(db: DbSessionType, user: User, given: str) -> bool:
    """Check a recovery code and use it up.

    ⚠️ Used means used, and the row stays. Deleting it would be tidier and
    would throw away the answer to "how many do I have left".
    """
    wanted = _hash(given)
    for row in user.recovery_codes:
        if row.used_at is None and secrets.compare_digest(row.code_hash, wanted):
            row.used_at = utcnow()
            db.commit()
            logger.info("A recovery code of %s was used.", user.username)
            return True
    return False


def codes_left(user: User) -> int:
    return sum(1 for code in user.recovery_codes if code.used_at is None)


def turn_off(db: DbSessionType, user: User) -> None:
    """Take the second factor away: secret, codes and the step counter.

    ⚠️ Not just the flag. Left behind, the old QR code would still work after
    somebody switched it back on, along with every photograph anybody took of
    it, and a recovery code off a year-old scrap of paper would count again.

    ⚠️ The step counter has to go too. Otherwise the freshly set up factor
    refuses every code whose step is below the remembered one, which for the
    first half minute is all of them. That looks exactly like a broken QR code.
    """
    user.totp_secret = ""
    user.totp_confirmed = False
    user.totp_last_step = 0
    for code in list(user.recovery_codes):
        db.delete(code)
    db.commit()
    logger.info("The second factor of %s was switched off.", user.username)


# ---------------------------------------------------------------------------
# What the installation demands
# ---------------------------------------------------------------------------


def required(db: DbSessionType) -> bool:
    """Does the operator want a second factor from everybody?"""
    row = db.get(Setting, SETTING_KEY)
    return bool((row.value or {}).get("require_two_factor")) if row else False


def set_required(db: DbSessionType, wanted: bool) -> bool:
    row = db.get(Setting, SETTING_KEY)
    value = dict(row.value or {}) if row else {}
    value["require_two_factor"] = bool(wanted)
    if row is None:
        db.add(Setting(key=SETTING_KEY, value=value))
    else:
        row.value = value
    db.commit()
    logger.info("A second factor is now %s for everybody.", "required" if wanted else "optional")
    return bool(wanted)


def must_set_up(db: DbSessionType, user: User) -> bool:
    """Is this person being kept at the door until they set one up?"""
    return required(db) and not enabled(user)
