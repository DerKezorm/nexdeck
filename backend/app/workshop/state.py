"""What an administrator decided about the shop, and the key the operator set for a private catalog.

Kept as one row of the settings table. The shop is off until an administrator turns it on: nothing in this package asks
GitHub while ``enabled`` is false (KARTEN-14 AC-2).

⚠️ The key (``NEXDECK_WORKSHOP_TOKEN``) is read from the environment when it is needed and kept nowhere else: not in the
database, not in a reply, not in a log line. Only whether it is set is ever told.
"""

from __future__ import annotations

import os
import re
from typing import Any

from sqlalchemy.orm import Session

from ..models import Setting

KEY = "workshop"
DEFAULT_REPO = "DerKezorm/nexdeck-workshop"
REPO = re.compile(r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$")
TOKEN_VARIABLE = "NEXDECK_WORKSHOP_TOKEN"


def token() -> str:
    """The key for the private test repository, or an empty text."""
    return os.environ.get(TOKEN_VARIABLE, "").strip()


def _read(db: Session) -> dict[str, Any]:
    row = db.get(Setting, KEY)
    return dict(row.value) if row is not None else {}


def _write(db: Session, value: dict[str, Any]) -> None:
    db.merge(Setting(key=KEY, value=value))


def enabled(db: Session) -> bool:
    return bool(_read(db).get("enabled", False))


def repo(db: Session) -> str:
    found = str(_read(db).get("repo") or "")
    return found if REPO.match(found) else DEFAULT_REPO


def configure(db: Session, *, enabled: bool | None = None, repo: str | None = None) -> None:
    value = _read(db)
    if enabled is not None:
        value["enabled"] = enabled
    if repo is not None:
        value["repo"] = repo
    _write(db, value)


def risk_acknowledged(db: Session, user_id: int) -> bool:
    return user_id in _read(db).get("risk", [])


def acknowledge_risk(db: Session, user_id: int) -> None:
    value = _read(db)
    if user_id not in value.get("risk", []):
        value["risk"] = [*value.get("risk", []), user_id]
        _write(db, value)


def told(db: Session) -> list[str]:
    """The recalls the administrators were told about already (``<ref>@<when it was removed>``)."""
    return [str(one) for one in _read(db).get("told", [])]


def mark_told(db: Session, keys: list[str]) -> None:
    value = _read(db)
    value["told"] = sorted({*value.get("told", []), *keys})
    _write(db, value)
