"""Schema creation and versioned migrations.

The first version creates every table from the models. Later versions append
a function to ``MIGRATIONS``; each runs once, in order, tracked in the
``schema_version`` table.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection, Engine

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


def _layout_version_column(connection: Connection) -> None:
    _add_column(connection, "pages", "layout_version", "INTEGER NOT NULL DEFAULT 0")


def _asset_digest_column(connection: Connection) -> None:
    _add_column(connection, "assets", "digest", "TEXT NOT NULL DEFAULT ''")
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_assets_digest ON assets (digest)"))


def _demo_checks_back_on(connection: Connection) -> None:
    """Switch on the checks of app tiles that no longer point at the demo's addresses.

    ⚠️ The demo board makes its app tiles with their checks switched off,
    because they point at example.com. Before 0.17 leaving the demo kept
    those tiles, the settings sheet sent the switched-off flag back on every
    save and showed it nowhere, so a demo tile edited into a real service
    stayed grey for good (issue #17). A tile still on example.com stays as
    it is; the demo may still be running.
    """
    connection.execute(text(
        "UPDATE health_checks SET enabled = 1 WHERE enabled = 0 AND target NOT LIKE '%.example.com%' "
        "AND widget_id IN (SELECT id FROM widgets WHERE kind = 'core.app' AND link NOT LIKE '%.example.com%')"
    ))


def _session_kind_columns(connection: Connection) -> None:
    _add_column(connection, "sessions", "kind", "VARCHAR(20) NOT NULL DEFAULT 'password'")
    _add_column(connection, "sessions", "address", "VARCHAR(64) NOT NULL DEFAULT ''")


def _muted_column(connection: Connection) -> None:
    _add_column(connection, "integrations", "muted", "BOOLEAN NOT NULL DEFAULT 0")


def _rest_column(connection: Connection) -> None:
    """Every display keeps showing its board until it is told to rest."""
    _add_column(connection, "kiosk_tokens", "rest_minutes", "INTEGER NOT NULL DEFAULT 0")


def _language_pair_column(connection: Connection) -> None:
    """Everybody keeps the two buttons they had: English and German."""
    _add_column(connection, "users", "language_pair", "VARCHAR(32) NOT NULL DEFAULT 'en,de'")


def _tilt_column(connection: Connection) -> None:
    """Everybody starts with the cards that tip towards the pointer; the profile switches it off."""
    _add_column(connection, "users", "tilt", "BOOLEAN NOT NULL DEFAULT 1")


def _check_since_column(connection: Connection) -> None:
    """A check from before knows nothing older than today: its long bars start here."""
    _add_column(connection, "health_checks", "created_at", "DATETIME")
    connection.execute(text("UPDATE health_checks SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL"))


def _provider_list_columns(connection: Connection) -> None:
    """The columns of the sign-in provider list, added beside the ones 0.36 reads.

    ⚠️ Added, not renamed, and every one with a default the database knows:
    an operator who goes back to 0.36 keeps a table 0.36 can read and write.
    ``created_at`` cannot get ``CURRENT_TIMESTAMP`` as a default in SQLite's
    ``ADD COLUMN``, so it is filled once here and by nexdeck on every insert.
    What only nexdeck can work out (the secret under its own context, the old
    callback, the order, the entry of the authentik button) is done at every
    start by ``services/oidc_store.sync_list``, because 0.36 may have changed
    rows in between.
    """
    _add_column(connection, "oidc_providers", "client_secret_enc", "TEXT NOT NULL DEFAULT ''")
    _add_column(connection, "oidc_providers", "managed", "VARCHAR(20) NOT NULL DEFAULT ''")
    _add_column(connection, "oidc_providers", "position", "INTEGER NOT NULL DEFAULT 0")
    _add_column(connection, "oidc_providers", "redirect_path", "VARCHAR(300) NOT NULL DEFAULT ''")
    _add_column(connection, "oidc_providers", "created_at", "DATETIME")
    _add_column(connection, "oidc_providers", "registered_redirect", "VARCHAR(500) NOT NULL DEFAULT ''")
    _add_column(connection, "oidc_links", "issuer", "VARCHAR(500) NOT NULL DEFAULT ''")
    _add_column(connection, "oidc_links", "created_at", "DATETIME")
    _add_column(connection, "oidc_links", "last_used_at", "DATETIME")
    connection.execute(text("UPDATE oidc_providers SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL"))
    connection.execute(text("UPDATE oidc_links SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL"))
    # One identity per provider and account. 0.36 replaced an account's link when it linked again, so a
    # duplicate cannot come from it; should one exist anyway, the newest stays.
    connection.execute(text(
        "DELETE FROM oidc_links WHERE id NOT IN (SELECT MAX(id) FROM oidc_links GROUP BY provider_id, user_id)"
    ))
    connection.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_oidc_links_provider_account ON oidc_links (provider_id, user_id)"
    ))


def _page_kind_columns(connection: Connection) -> None:
    _add_column(connection, "pages", "kind", "VARCHAR(16) NOT NULL DEFAULT 'cards'")
    _add_column(connection, "pages", "topology", "JSON NOT NULL DEFAULT '{}'")


def _home_page_column(connection: Connection) -> None:
    _add_column(connection, "pages", "home", "JSON NOT NULL DEFAULT '{}'")


def _page_side_column(connection: Connection) -> None:
    _add_column(connection, "pages", "side", "JSON NOT NULL DEFAULT '{}'")


def _token_scope_column(connection: Connection) -> None:
    """Every token that exists keeps the full rights it was made with; new ones start at reading."""
    _add_column(connection, "api_tokens", "scope", "VARCHAR(8) NOT NULL DEFAULT 'full'")


def _problems_cards_stay_as_they_were(connection: Connection) -> None:
    """The problems card becomes the attention card; the ones that exist keep their old answers.

    ⚠️ Same reason as ``_findings_stay_on_for_existing_widgets``: a default is
    retroactive. The new card looks at every board of the owner, counts the
    bell and opens the card a row is about. A problems card made before read
    only its own board and opened the service, and it goes on doing that
    until somebody changes it. New cards start with the new answers.
    """
    import json

    rows = connection.execute(text("SELECT id, options FROM widgets WHERE kind = 'core.problems'")).fetchall()
    for widget_id, raw in rows:
        try:
            options = json.loads(raw) if isinstance(raw, str) else (raw or {})
        except (TypeError, ValueError):
            options = {}
        if not isinstance(options, dict):
            options = {}
        for key, old in (("scope", "board"), ("bell", False), ("updates", False), ("opens", "service")):
            options.setdefault(key, old)
        connection.execute(
            text("UPDATE widgets SET options = :o WHERE id = :i"),
            {"o": json.dumps(options, ensure_ascii=False), "i": widget_id},
        )
    logger.info("%d problems card(s) keep looking at their own board only.", len(rows))


def _theme_schedule_columns(connection: Connection) -> None:
    """An account and a wall display can follow the clock; a display made before stays dark, as it always was."""
    for table in ("users", "kiosk_tokens"):
        _add_column(connection, table, "light_from", "VARCHAR(5) NOT NULL DEFAULT '07:00'")
        _add_column(connection, table, "dark_from", "VARCHAR(5) NOT NULL DEFAULT '20:00'")
    _add_column(connection, "kiosk_tokens", "theme", "VARCHAR(8) NOT NULL DEFAULT 'dark'")


def _card_editor_column(connection: Connection) -> None:
    _add_column(connection, "card_definitions", "updated_by", "INTEGER REFERENCES users(id) ON DELETE SET NULL")


def _own_integrations_table(connection: Connection) -> None:
    Base.metadata.tables["own_integrations"].create(connection, checkfirst=True)


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
    (11, "A page counts its saved layouts", _layout_version_column),
    (12, "An upload knows its own fingerprint", _asset_digest_column),
    (13, "A session says how it was opened, and from where", _session_kind_columns),
    (14, "App tiles that left the demo check their address again", _demo_checks_back_on),
    (15, "A connection can be muted", _muted_column),
    (16, "Each account chooses the two languages in its top bar", _language_pair_column),
    (17, "A wall display can rest on a large clock", _rest_column),
    (18, "A reachability check knows since when it measures", _check_since_column),
    (19, "Sign-in providers become a list", _provider_list_columns),
    (20, "Each account decides whether the cards tip towards the pointer", _tilt_column),
    (21, "A page can be a network plan", _page_kind_columns),
    (22, "A page can be a surface of Home Assistant controls", _home_page_column),
    (23, "A card page can have a side bar", _page_side_column),
    (24, "Problems cards that exist keep looking at their own board only", _problems_cards_stay_as_they_were),
    (25, "An API token can be one that only reads", _token_scope_column),
    (26, "Light and dark can follow the clock, for an account and for a wall display", _theme_schedule_columns),
    (27, "A custom card knows who saved it last", _card_editor_column),
    (28, "Own kinds of connection are kept in a table of their own", _own_integrations_table),
]


#: The migration that brings the sign-in providers to the list; a backup is written before it.
PROVIDER_LIST_VERSION = 19


def _backup_before_the_provider_list(engine: Engine) -> None:
    """A restore point before the sign-in providers change shape, when there are any.

    Written as a manual backup, so the automatic rotation never throws it away.
    """
    names = set(inspect(engine).get_table_names())
    if "schema_version" not in names or "oidc_providers" not in names:
        return
    with engine.connect() as connection:
        current = int(connection.execute(text("SELECT MAX(version) FROM schema_version")).scalar() or 0)
        rows = int(connection.execute(text("SELECT COUNT(*) FROM oidc_providers")).scalar() or 0)
    if current >= PROVIDER_LIST_VERSION or not rows:
        return
    from .services import backup

    backup.create(kind=backup.MANUAL, note="before sign-in providers")


def migrate() -> None:
    engine = get_engine()
    # Asked before ``create_all``, which would answer it the same for every database.
    fresh = not set(Base.metadata.tables) & set(inspect(engine).get_table_names())
    if not fresh:
        _backup_before_the_provider_list(engine)
    Base.metadata.create_all(engine)
    newest = max((number for number, _name, _step in MIGRATIONS), default=0)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)"))
        row = connection.execute(text("SELECT MAX(version) FROM schema_version")).scalar()
        current = int(row or 0)
        if current == 0:
            # ⚠️ A database with none of the tables was built a moment ago by
            # ``create_all``, already in its newest shape, and every step ran
            # over it anyway. Harmless while each step asks whether its column
            # is there; the first step that moves data would do to a new
            # installation what was meant for an old one. Tables without a
            # version are an installation from before the version table, and
            # for that one every step still applies.
            current = max(1, newest) if fresh else 1
            connection.execute(text("INSERT INTO schema_version (version) VALUES (:v)"), {"v": current})
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
