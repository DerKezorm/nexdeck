"""Regression tests for SQLite recovery snapshots."""

import os
import sqlite3
import stat
import sys
from pathlib import Path

import pytest

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[1]),
)

from sqlite_snapshot import SQLiteSnapshotError, snapshot_sqlite


@pytest.fixture
def wal_database(tmp_path):
    database = tmp_path / "nexdeck.db"
    connection = sqlite3.connect(database)

    assert connection.execute(
        "PRAGMA journal_mode=WAL"
    ).fetchone()[0] == "wal"

    connection.execute("PRAGMA wal_autocheckpoint=0")

    connection.execute(
        "CREATE TABLE records "
        "(id INTEGER PRIMARY KEY, value TEXT)"
    )
    connection.commit()

    connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    for number in range(100):
        connection.execute(
            "INSERT INTO records(value) VALUES (?)",
            (f"Record {number}",),
        )

    connection.commit()

    try:
        yield database
    finally:
        connection.close()


def test_snapshot_preserves_committed_wal_records(
    wal_database, tmp_path
):
    destination = tmp_path / "snapshot.db"

    snapshot_sqlite(wal_database, destination)

    with sqlite3.connect(destination) as backup:
        assert backup.execute(
            "SELECT COUNT(*) FROM records"
        ).fetchone()[0] == 100

        assert backup.execute(
            "PRAGMA integrity_check"
        ).fetchone()[0] == "ok"

    permissions = stat.S_IMODE(destination.stat().st_mode)

    assert permissions & 0o077 == 0


def test_existing_destination_is_not_overwritten(
    wal_database, tmp_path
):
    destination = tmp_path / "existing.db"
    destination.write_bytes(b"preserve this content")

    with pytest.raises(SQLiteSnapshotError):
        snapshot_sqlite(wal_database, destination)

    assert destination.read_bytes() == b"preserve this content"


def test_invalid_database_removes_incomplete_snapshot(tmp_path):
    source = tmp_path / "invalid.db"
    destination = tmp_path / "snapshot.db"

    source.write_bytes(b"Not a SQLite database")

    with pytest.raises(SQLiteSnapshotError):
        snapshot_sqlite(source, destination)

    assert not destination.exists()


def test_missing_source_is_rejected(tmp_path):
    source = tmp_path / "missing.db"
    destination = tmp_path / "snapshot.db"

    with pytest.raises(SQLiteSnapshotError):
        snapshot_sqlite(source, destination)

    assert not destination.exists()


def test_source_symlink_is_rejected(
    wal_database, tmp_path
):
    source_link = tmp_path / "linked.db"
    destination = tmp_path / "snapshot.db"

    source_link.symlink_to(wal_database)

    with pytest.raises(SQLiteSnapshotError):
        snapshot_sqlite(source_link, destination)

    assert not destination.exists()
