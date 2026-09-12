"""Where browsers reach this installation, read in one place.

⚠️ The address can be set in the interface or in ``NEXDECK_PUBLIC_URL``, and
five places used to read it three different ways. Web Push and the rescue
link looked at the environment only, so an installation that set its address
in the interface signed its push messages as ``mailto:admin@localhost`` and
printed a rescue link to localhost. A guard test keeps every other module
from reading either source itself.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import db_session
from ..models import Setting


def public_url(db: Session | None = None) -> str:
    """The setting, else the environment variable, without a slash at the end; ``""`` when neither is set."""
    if db is None:
        with db_session() as own:
            return public_url(own)
    row = db.get(Setting, "general")
    stored = str((row.value or {}).get("public_url") or "") if row is not None else ""
    return (stored or get_settings().public_url).strip().rstrip("/")
