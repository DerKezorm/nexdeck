"""A way back in for somebody who forgot their password.

⚠️ **The same answer either way.** Whether the name exists, whether the account
carries an address, whether the mail went out: the reply is identical. Anything
else turns this form into a list of who has an account here, which is exactly
what somebody probing a self-hosted box wants first.

⚠️ **Only with a mail server.** Without one there is nowhere to send the link,
so the link is not offered at all rather than offered and quietly useless.

⚠️ **Only the hash is stored.** A reset link out of a database dump would be a
way into every account at once.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSessionType

from ..models import PasswordReset, Session, User, utcnow
from ..security import hash_token, new_opaque_token, now_ms
from . import mail as mail_service

logger = logging.getLogger("nexdeck.password_reset")

#: Long enough to walk to another room, short enough that a link left in an
#: inbox is not a spare key.
VALID_MINUTES = 30
#: How many unused links one account may have at once. Somebody pressing the
#: button ten times must not leave ten open doors.
MAX_OPEN = 3

SUBJECT = "Set a new nexdeck password"
BODY = """Somebody asked to set a new password for the nexdeck account "{username}".

Open this link within {minutes} minutes:

{link}

Using it signs out every browser and ends every API token of the account.

If this was not you, nothing has happened and you can ignore this message.
"""


def available(db: DbSessionType) -> bool:
    """Can a link be sent at all?

    Two conditions, not one. A mail server to send through, and an address
    this installation answers on: a mail whose link reads ``/reset/nr_...``
    with no host in front of it is a mail nobody can use.
    """
    return mail_service.configured(db) and bool(_public_url(db))


def _public_url(db: DbSessionType) -> str:
    """Where browsers reach this installation.

    ⚠️ The setting **or** the environment variable, the way the rest of the
    app reads it. This looked only at the setting, so an installation
    configured through ``NEXDECK_PUBLIC_URL`` in its compose file, which is
    the ordinary case in Docker, sent out a link with no host in it.
    """
    from ..config import get_settings
    from ..models import Setting

    row = db.get(Setting, "general")
    stored = str((row.value or {}).get("public_url") or "") if row else ""
    return (stored or get_settings().public_url).rstrip("/")


def request(db: DbSessionType, username_or_email: str) -> None:
    """Send a link, if there is somebody and somewhere to send it to.

    Returns nothing on purpose: the caller must not be able to tell the cases
    apart, and a return value is the easiest way to leak one by accident.
    """
    wanted = (username_or_email or "").strip()
    if not wanted or not available(db):
        return
    user = db.scalar(
        select(User).where(
            (func.lower(User.username) == wanted.lower()) | (func.lower(User.email) == wanted.lower())
        )
    )
    if user is None or user.disabled or not user.email:
        # Written down, because an administrator reading the log should be able
        # to see that somebody asked and why nothing went out.
        logger.info("A password reset was asked for %r; nothing was sent.", wanted[:40])
        return

    base = _public_url(db)
    if not base:
        # ⚠️ Refused rather than sent half. A link without a host is a line
        # of text nobody can click, and the person who asked would wait for a
        # mail that already arrived and was useless.
        logger.warning(
            "A password reset for %s was not sent: this installation has no public URL. "
            "Set NEXDECK_PUBLIC_URL, or the address under System, Address.",
            user.username,
        )
        return

    open_now = list(db.scalars(
        select(PasswordReset).where(
            PasswordReset.user_id == user.id,
            PasswordReset.used_at.is_(None),
            PasswordReset.expires_at > utcnow(),
        )
    ))
    if len(open_now) >= MAX_OPEN:
        logger.info("A password reset for %s was not sent: too many are open already.", user.username)
        return

    token, token_hash, _prefix = new_opaque_token("nr")
    db.add(PasswordReset(
        user_id=user.id, token_hash=token_hash,
        expires_at=utcnow() + timedelta(minutes=VALID_MINUTES),
    ))
    db.commit()

    link = f"{base}/reset/{token}"
    try:
        mail_service.send(
            mail_service.stored(db), user.email, SUBJECT,
            BODY.format(username=user.username, minutes=VALID_MINUTES, link=link),
        )
    except mail_service.MailError as failure:
        logger.warning("The password reset for %s could not be sent: %s", user.username, failure.message)
        return
    logger.info("A password reset link was sent to the address of %s.", user.username)


def holder(db: DbSessionType, token: str) -> User | None:
    """Whose link this is, if it is still good for anything."""
    if not token.startswith("nr_"):
        return None
    row = db.scalar(select(PasswordReset).where(PasswordReset.token_hash == hash_token(token)))
    if row is None or row.used_at is not None or row.expires_at <= utcnow():
        return None
    user = db.get(User, row.user_id)
    return None if user is None or user.disabled else user


def redeem(db: DbSessionType, token: str, new_password: str) -> bool:
    """Set the password and burn everything the old one opened.

    ⚠️ Every session and every API token of the account ends here. Somebody
    resetting a password is usually doing it because they think the old one
    got out; leaving the intruder's session running would defeat the point.
    """
    row = db.scalar(select(PasswordReset).where(PasswordReset.token_hash == hash_token(token))) if token.startswith("nr_") else None
    if row is None or row.used_at is not None or row.expires_at <= utcnow():
        return False
    user = db.get(User, row.user_id)
    if user is None or user.disabled:
        return False

    from ..security import hash_password

    user.password_hash = hash_password(new_password)
    user.password_changed_ms = now_ms()
    # Every open link of this account is spent now, this one included: one
    # reset, one door. Setting ``row`` separately first would be a line that
    # does nothing, because this loop reaches it too.
    for open_link in db.scalars(select(PasswordReset).where(PasswordReset.user_id == user.id, PasswordReset.used_at.is_(None))):
        open_link.used_at = utcnow()
    for session in db.scalars(select(Session).where(Session.user_id == user.id, Session.revoked.is_(False))):
        session.revoked = True
    db.commit()
    logger.info("%s set a new password through a reset link; every session and token of the account ended.", user.username)
    return True


def prune(db: DbSessionType) -> int:
    """Throw away links nobody can use any more."""
    rows = list(db.scalars(select(PasswordReset).where(PasswordReset.expires_at <= utcnow() - timedelta(days=1))))
    for row in rows:
        db.delete(row)
    if rows:
        db.commit()
    return len(rows)
