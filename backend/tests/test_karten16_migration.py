"""KARTEN-16 AC-4, EC-8: the table of GitHub sign-ins is made by migration 31 and goes with the account."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import text

from app import migrations
from app.db import get_engine
from app.models import Base

NEWEST = max(number for number, _name, _step in migrations.MIGRATIONS)


def test_karten16_migration_31_adds_the_table_to_an_older_database(data_dir: Path) -> None:
    engine = get_engine()
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE github_logins"))
        connection.execute(text("CREATE TABLE schema_version (version INTEGER NOT NULL)"))
        connection.execute(text("INSERT INTO schema_version (version) VALUES (30)"))
    migrations.migrate()
    assert migrations.schema_version() == NEWEST
    with engine.connect() as connection:
        columns = {row[1] for row in connection.execute(text("PRAGMA table_info(github_logins)"))}
        links = [(row[2], row[6]) for row in connection.execute(text("PRAGMA foreign_key_list(github_logins)"))]
    assert {"user_id", "github_id", "login", "access", "refresh", "access_until", "until", "created_at"} <= columns
    assert ("users", "CASCADE") in links, "the sign-in goes with the account"
    migrations.migrate()
    assert migrations.schema_version() == NEWEST
