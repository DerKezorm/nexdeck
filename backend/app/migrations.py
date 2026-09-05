"""Schema creation and versioned migrations.

The first version creates every table from the models. Later versions append
a function to ``MIGRATIONS``; each runs once, in order, tracked in the
``schema_version`` table.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from sqlalchemy import text
from sqlalchemy.engine import Connection

from .db import get_engine
from .models import Base

logger = logging.getLogger("nexdeck.migrations")

def _nexview_logo(connection: Connection) -> None:
    """Nexview widgets created before the logo shipped carry the placeholder symbol."""
    connection.execute(
        text("UPDATE widgets SET icon = 'nexview' WHERE kind LIKE 'nexview.%' AND icon = 'lucide:clapperboard'")
    )


MIGRATIONS: list[tuple[int, str, Callable[[Connection], None]]] = [
    # (version, description, function). Version 1 is create_all.
    (2, "Nexview widgets get the bundled Nexview logo", _nexview_logo),
]


def migrate() -> None:
    engine = get_engine()
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)"))
        row = connection.execute(text("SELECT MAX(version) FROM schema_version")).scalar()
        current = int(row or 0)
        if current == 0:
            connection.execute(text("INSERT INTO schema_version (version) VALUES (1)"))
            current = 1
        for version, description, function in MIGRATIONS:
            if version <= current:
                continue
            logger.info("Applying migration %d: %s", version, description)
            function(connection)
            connection.execute(text("INSERT INTO schema_version (version) VALUES (:v)"), {"v": version})
            current = version


def schema_version() -> int:
    with get_engine().connect() as connection:
        return int(connection.execute(text("SELECT MAX(version) FROM schema_version")).scalar() or 0)
