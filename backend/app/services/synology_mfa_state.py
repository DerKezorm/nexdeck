"""Concurrency-safe Synology MFA state updates.

The revision is stored inside Integration.config so existing installations
do not need a database migration. SQLite performs the conditional update
atomically, preventing stale MFA enrolment responses from restoring a
credential after an administrator has un-enrolled it.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import update
from sqlalchemy.orm import Session

from ..models import Integration

REVISION_KEY = "_synology_mfa_revision"


def revision(config: dict[str, Any] | None) -> int:
    """Read the internal revision, including configurations predating MFA."""
    value = (config or {}).get(REVISION_KEY, 0)
    return value if type(value) is int and value >= 0 else 0


def advance(config: dict[str, Any] | None) -> dict[str, Any]:
    """Return a new configuration with its MFA revision advanced."""
    updated = dict(config or {})
    updated[REVISION_KEY] = revision(updated) + 1
    return updated


def replace_if_unchanged(
    db: Session,
    integration_id: int,
    expected: dict[str, Any],
    replacement: dict[str, Any],
) -> bool:
    """Atomically replace the configuration only if it is still unchanged.

    Compare the complete original JSON value, not just the revision, so a
    concurrent URL, username, password or other configuration edit also
    invalidates the pending MFA operation.
    """
    result = db.execute(
        update(Integration)
        .where(
            Integration.id == integration_id,
            Integration.kind == "synology",
            Integration.demo.is_(False),
            Integration.config == expected,
        )
        .values(config=replacement)
        .execution_options(synchronize_session=False)
    )
    return result.rowcount == 1
