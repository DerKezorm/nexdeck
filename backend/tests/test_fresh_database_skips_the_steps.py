"""A fresh database starts at the newest schema and runs none of the steps meant for old ones.

⚠️ ``create_all`` builds the finished schema, and then every migration ran over
it anyway. Harmless while every step asks whether its column is already there;
the first real data migration would do to a new installation what was meant
for an old one. Still open in the check of 12.09.2026.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app import migrations
from app.db import get_engine
from app.models import Base


def test_a_fresh_database_starts_at_the_newest_schema(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ran: list[int] = []
    monkeypatch.setattr(migrations, "MIGRATIONS", [
        (2, "a step", lambda connection: ran.append(2)),
        (3, "another step", lambda connection: ran.append(3)),
    ])
    migrations.migrate()
    assert ran == []
    assert migrations.schema_version() == 3


def test_a_database_from_before_the_version_table_still_gets_every_step(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The other side: tables there, no version yet. That is an old installation, not a new one."""
    Base.metadata.create_all(get_engine())
    ran: list[int] = []
    monkeypatch.setattr(migrations, "MIGRATIONS", [(2, "a step", lambda connection: ran.append(2))])
    migrations.migrate()
    assert ran == [2]
    assert migrations.schema_version() == 2
