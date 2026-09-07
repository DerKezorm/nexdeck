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


def _findings_stay_on_for_existing_widgets(connection: Connection) -> None:
    """Keep every card that exists showing its reason and its warning colour.

    ⚠️ "Show findings" becomes something you switch on, not something you
    switch off. A default is retroactive: cards carry no value of their own,
    they inherit it, so flipping it would make every card on every board fall
    silent at once. This writes the old answer down once, for the cards that
    were made under it. New cards start quiet.
    """
    import json

    rows = connection.execute(text("SELECT id, options FROM widgets")).fetchall()
    changed = 0
    for widget_id, raw in rows:
        try:
            options = json.loads(raw) if isinstance(raw, str) else (raw or {})
        except (TypeError, ValueError):
            options = {}
        if not isinstance(options, dict) or "show_findings" in options:
            continue
        options["show_findings"] = True
        connection.execute(
            text("UPDATE widgets SET options = :o WHERE id = :i"),
            {"o": json.dumps(options, ensure_ascii=False), "i": widget_id},
        )
        changed += 1
    logger.info("Findings stay switched on for %d existing widget(s).", changed)


def _provider_second_factor_column(connection: Connection) -> None:
    """Existing providers do not check a factor until somebody says they do."""
    _add_column(connection, "oidc_providers", "trusts_second_factor", "BOOLEAN NOT NULL DEFAULT 0")


def _unique_email_index(connection: Connection) -> None:
    """Make the database keep the promise the code already relies on.

    ⚠️ Two places assume an address belongs to one account: the profile route
    refuses a second one, and the password reset looks an account up by it. The
    check in the route is a read followed by a write, so two requests can both
    pass it, and then a reset link is ambiguous.

    Empty is not an address and stays free, so the index skips those. And an
    installation that already has a duplicate must not fail to start over this:
    it gets the plain index, a line in the log, and the operator can sort the
    two accounts out.
    """
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_users_email ON users (email)"))
    duplicates = connection.execute(text(
        "SELECT lower(email) FROM users WHERE email <> '' GROUP BY lower(email) HAVING COUNT(*) > 1"
    )).scalars().all()
    if duplicates:
        logger.error(
            "%d e-mail address(es) belong to more than one account, so they cannot be made unique. "
            "Change one of each pair in the user settings.", len(duplicates),
        )
        return
    connection.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_users_email ON users (lower(email)) WHERE email <> ''"
    ))


MIGRATIONS: list[tuple[int, str, Callable[[Connection], None]]] = [
    # (version, description, function). Version 1 is create_all.
    (2, "Nexview widgets get the bundled Nexview logo", _nexview_logo),
    (3, "Users can have a profile picture", _avatar_column),
    (4, "Users can have an e-mail address", _email_column),
    (5, "Boards can stay out of the menu, connections can be locked", _menu_and_lock_columns),
    (6, "API and kiosk tokens can expire and be withdrawn", _token_expiry_columns),
    (7, "Accounts can carry a second factor", _second_factor_columns),
    (8, "Findings stay on for the cards that already exist", _findings_stay_on_for_existing_widgets),
    (9, "An identity provider can say it checks a second factor itself", _provider_second_factor_column),
    (10, "An e-mail address belongs to one account", _unique_email_index),
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
        newest = max((number for number, _name, _step in MIGRATIONS), default=0)
        if current > newest:
            # ⚠️ Said out loud, because nothing else will say it. There is no
            # migration that runs backwards, so a database written by a newer
            # nexdeck keeps columns and tables this build does not know, and
            # the symptoms turn up later as odd errors nobody connects to a
            # downgrade. Refusing to start would be worse: the operator would
            # have no way in to fix it.
            logger.error(
                "This database was written by a newer nexdeck (schema %d, this build knows %d). "
                "Downgrading is not supported; expect trouble until you go back to the newer version.",
                current, newest,
            )
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
