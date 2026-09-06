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


def _add_column(connection: Connection, table: str, column: str, definition: str) -> None:
    """``create_all`` builds missing tables, never missing columns."""
    columns = {row[1] for row in connection.execute(text(f"PRAGMA table_info({table})"))}
    if column not in columns:
        connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {definition}"))


def _avatar_column(connection: Connection) -> None:
    _add_column(connection, "users", "avatar", "VARCHAR(120) NOT NULL DEFAULT ''")


def _email_column(connection: Connection) -> None:
    _add_column(connection, "users", "email", "VARCHAR(200) NOT NULL DEFAULT ''")


def _menu_and_lock_columns(connection: Connection) -> None:
    _add_column(connection, "boards", "in_menu", "BOOLEAN NOT NULL DEFAULT 1")
    _add_column(connection, "integrations", "admin_only", "BOOLEAN NOT NULL DEFAULT 0")


def _token_expiry_columns(connection: Connection) -> None:
    for table in ("api_tokens", "kiosk_tokens"):
        _add_column(connection, table, "expires_at", "DATETIME")
        _add_column(connection, table, "revoked", "BOOLEAN NOT NULL DEFAULT 0")
        _add_column(connection, table, "revoked_at", "DATETIME")


def _second_factor_columns(connection: Connection) -> None:
    _add_column(connection, "users", "totp_secret", "TEXT NOT NULL DEFAULT ''")
    _add_column(connection, "users", "totp_confirmed", "BOOLEAN NOT NULL DEFAULT 0")
    _add_column(connection, "users", "totp_last_step", "INTEGER NOT NULL DEFAULT 0")


MIGRATIONS: list[tuple[int, str, Callable[[Connection], None]]] = [
    # (version, description, function). Version 1 is create_all.
    (2, "Nexview widgets get the bundled Nexview logo", _nexview_logo),
    (3, "Users can have a profile picture", _avatar_column),
    (4, "Users can have an e-mail address", _email_column),
    (5, "Boards can stay out of the menu, connections can be locked", _menu_and_lock_columns),
    (6, "API and kiosk tokens can expire and be withdrawn", _token_expiry_columns),
    (7, "Accounts can carry a second factor", _second_factor_columns),
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
