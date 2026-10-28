"""KARTEN-15 EC-2: a card remembers the text it was installed with; the step that adds the column leaves old rows alone (migration 30)."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import text

from app import migrations
from app.db import get_engine
from app.models import Base


def test_karten15_migration_30_adds_the_columns_to_an_older_database(data_dir: Path) -> None:
    engine = get_engine()
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE card_definitions DROP COLUMN shop_hash"))
        for column in ("shop_ref", "shop_version", "shop_hash"):
            connection.execute(text(f"ALTER TABLE own_integrations DROP COLUMN {column}"))
        connection.execute(text("CREATE TABLE schema_version (version INTEGER NOT NULL)"))
        connection.execute(text("INSERT INTO schema_version (version) VALUES (29)"))
        connection.execute(
            text("INSERT INTO card_definitions (slug, kind, yaml_source, definition, origin, shop_ref, shop_version, users_may_place, created_at, updated_at) "
                 "VALUES ('old', 'card', 'x', '{}', 'local', '', '', 0, '2026-10-01 00:00:00', '2026-10-01 00:00:00')")
        )
    migrations.migrate()
    assert migrations.schema_version() == migrations.MIGRATIONS[-1][0]
    with engine.connect() as connection:
        columns = {row[1] for row in connection.execute(text("PRAGMA table_info(card_definitions)"))}
        pieces = {row[1] for row in connection.execute(text("PRAGMA table_info(own_integrations)"))}
        kept = connection.execute(text("SELECT slug, shop_hash FROM card_definitions")).all()
    assert "shop_hash" in columns
    assert {"shop_ref", "shop_version", "shop_hash"} <= pieces
    assert [tuple(row) for row in kept] == [("old", "")]
    # Run again: nothing changes its mind.
    migrations.migrate()
    assert migrations.schema_version() == migrations.MIGRATIONS[-1][0]
