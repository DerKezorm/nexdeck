"""What has to hold around a restore, and what runs by itself.

⚠️ Restoring is the one action in nexdeck that cannot be undone from inside
nexdeck, and until 07.09.2026 three things about it were not true:

* the safety copy of the current state was called the only way back and was
  skipped with a warning whenever it failed
* nothing stopped the collector, the reachability loop or another request from
  writing while the database file was being replaced under them
* the list of snapshots promised "newest first" and sorted by file name, where
  the kind and the version come before the timestamp

And the migrations had never once run against a database older than the build:
every test database is made by ``create_all``, which builds the finished schema
and leaves every migration with nothing to do.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db import get_engine
from app.services import backup

from .conftest import CSRF, setup_admin


def _an_archive(client: TestClient, password: str = "a-long-enough-password") -> bytes:
    made = client.post("/api/v1/backups", json={"note": "for the test"}, headers=CSRF)
    assert made.status_code in (200, 201), made.text
    name = made.json()["name"]
    packed = client.post(f"/api/v1/backups/{name}/archive", json={"password": password}, headers=CSRF)
    assert packed.status_code == 200, packed.text
    return packed.content


def test_a_restore_stops_when_the_safety_copy_fails(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """⚠️ The docstring of ``restore`` calls that copy the only way back if the
    archive turns out to be the broken one. It used to be skipped with a
    warning, which makes the promise true except when it matters.
    """
    setup_admin(client)
    archive = _an_archive(client)

    def no_room(*_args: object, **_kwargs: object) -> Path:
        raise OSError("No space left on device")

    monkeypatch.setattr(backup, "create", no_room)
    with pytest.raises(backup.BackupError) as refused:
        backup.restore(archive, "a-long-enough-password")
    assert refused.value.code == "no_safety_copy"

    # And a way through for the case the copy is what is broken.
    verdict = backup.restore(archive, "a-long-enough-password", without_safety_copy=True)
    assert verdict.restorable


def test_nothing_else_may_open_a_session_while_the_file_is_replaced() -> None:
    """The latch, on its own.

    Whether it is closed at the right moment is the restore's business; that it
    holds anybody back at all is this test's.
    """
    import threading

    from app.db import db_session, paused_for_swap

    got_in = threading.Event()

    def try_it() -> None:
        with db_session():
            got_in.set()

    with paused_for_swap():
        waiting = threading.Thread(target=try_it, daemon=True)
        waiting.start()
        assert not got_in.wait(timeout=1.5), "a session was opened while the database was being replaced"
    assert got_in.wait(timeout=10), "and it has to get in again once the swap is over"


def test_the_list_is_newest_first_whatever_the_names_say(client: TestClient) -> None:
    """⚠️ Sorting the file name backwards put "manual" above "automatic" and
    0.9.0 above 0.10.0, because both stand before the timestamp.
    """
    setup_admin(client)
    root = backup.folder()
    root.mkdir(parents=True, exist_ok=True)
    for number, name in enumerate(("nexdeck-manual-0.9.0-2020-01-01_000000.db",
                                   "nexdeck-automatic-0.10.0-2026-09-07_120000.db")):
        path = root / name
        path.write_bytes(b"SQLite format 3\x00" + b"\x00" * 100)
        # The second one is the newer file, whatever its name sorts like.
        import os

        os.utime(path, (time.time() + number, time.time() + number))

    names = [entry.name for entry in backup.listing()]
    assert names[0] == "nexdeck-automatic-0.10.0-2026-09-07_120000.db", names


def test_a_snapshot_is_written_by_itself_and_then_left_alone(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """⚠️ The sweeper for automatic snapshots existed and the writer did not."""
    setup_admin(client)
    monkeypatch.setenv("NEXDECK_BACKUP_EVERY_HOURS", "24")
    from app import config

    config.reset_settings_cache()

    first = backup.write_one_if_due()
    assert first is not None, "no snapshot was written at all"
    assert backup.write_one_if_due() is None, "a second one inside the interval"

    monkeypatch.setenv("NEXDECK_BACKUP_EVERY_HOURS", "0")
    config.reset_settings_cache()
    assert backup.write_one_if_due() is None, "zero hours means off"


def test_every_migration_runs_against_a_database_that_predates_it(data_dir: Path) -> None:
    """⚠️ The step nobody had ever taken.

    Every test database is built by ``create_all``, which lays down the
    finished schema, so each migration found its column already there and did
    nothing. Steps 3 to 7 had never been executed by anything. Here the tables
    are stripped back to what they looked like before, and then the real
    ``migrate()`` has to bring them up.
    """
    from app.migrations import MIGRATIONS, migrate

    migrate()
    engine = get_engine()

    #: Columns the later migrations add, taken back off so they have work to do.
    undone = {
        "users": ("avatar", "email", "totp_secret", "totp_confirmed", "totp_last_step"),
        "boards": ("in_menu",),
        "integrations": ("admin_only",),
        "api_tokens": ("expires_at", "revoked"),
        "oidc_providers": ("trusts_second_factor",),
    }
    removed = 0
    with engine.begin() as connection:
        for table, columns in undone.items():
            present = {row[1] for row in connection.execute(text(f"PRAGMA table_info({table})"))}
            for column in columns:
                if column in present:
                    connection.execute(text(f"ALTER TABLE {table} DROP COLUMN {column}"))
                    removed += 1
        connection.execute(text("DELETE FROM schema_version"))
        connection.execute(text("INSERT INTO schema_version (version) VALUES (1)"))
    assert removed >= 6, f"nothing was taken away, so this test proves nothing ({removed})"

    migrate()

    with engine.begin() as connection:
        for table, columns in undone.items():
            present = {row[1] for row in connection.execute(text(f"PRAGMA table_info({table})"))}
            missing = [column for column in columns if column not in present]
            assert missing == [], f"{table} came back without {missing}"
        version = connection.execute(text("SELECT MAX(version) FROM schema_version")).scalar()
    assert int(version or 0) == max(number for number, _n, _s in MIGRATIONS)


def test_reading_the_schema_of_an_archive_touches_no_disk(tmp_path: Path) -> None:
    """It used to write the whole foreign database into the system temp."""
    made = sqlite3.connect(":memory:")
    made.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
    made.execute("INSERT INTO schema_version VALUES (7)")
    made.commit()
    raw = made.serialize()
    made.close()

    before = set(tmp_path.iterdir())
    assert backup._schema_from_bytes(raw) == 7
    assert set(tmp_path.iterdir()) == before
