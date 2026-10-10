"""Whether people may sign in with a password (blueprint "Anmeldung mit OIDC und authentik", part 01).

The administrator can switch the password off once at least one provider is active; then only the providers let
people in. Administrators can always use their password: the way back if the provider fails. With no active provider
left the switch has no effect, so nobody is locked out by removing the last one.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import OidcProvider, Role, Setting, User

logger = logging.getLogger("nexdeck.auth")

SETTING_KEY = "sign_in"


def password_setting(db: Session) -> bool:
    """The switch as the administrator left it (on unless switched off)."""
    row = db.get(Setting, SETTING_KEY)
    return bool((row.value or {}).get("password_login", True)) if row is not None else True


def any_provider_active(db: Session) -> bool:
    return db.scalar(select(OidcProvider.id).where(OidcProvider.enabled.is_(True)).limit(1)) is not None


def password_login(db: Session) -> bool:
    """Whether the password form is offered to everybody: the switch, unless no provider is active."""
    return password_setting(db) or not any_provider_active(db)


def password_allowed(db: Session, user: User | None) -> bool:
    """Whether this account may sign in with its password now."""
    if password_login(db):
        return True
    return user is not None and user.role == Role.admin.value


class NoActiveProvider(Exception):
    """The password cannot be switched off while no provider would let anybody in."""


def set_password_login(db: Session, wanted: bool) -> bool:
    if not wanted and not any_provider_active(db):
        raise NoActiveProvider
    row = db.get(Setting, SETTING_KEY)
    value = dict(row.value or {}) if row is not None else {}
    value["password_login"] = bool(wanted)
    if row is None:
        db.add(Setting(key=SETTING_KEY, value=value))
    else:
        row.value = value
    logger.info("Sign-in with a password is now %s.", "on" if wanted else "off for everybody but administrators")
    return bool(wanted)
