"""Regression tests for private SQLite snapshot staging."""

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

from sqlite_private import snapshot_sqlite_private
from sqlite_snapshot import SQLiteSnapshotError


@pytest.fixture
def staging(tmp_path):
    directory = tmp_path / "staging"
    directory.mkdir(mode=0o700)
    return directory


@pytest.fixture
def wal_database(tmp_path):
    database = tmp_path / "source.db"
    connection = sqlite3.connect(database)

    assert connection.execute(
        "PRAGMA journal_mode=WAL"
    ).fetchone()[0] == "wal"

    connection.execute("PRAGMA wal_autocheckpoint=0")
    connection.execute(
        "CREATE TABLE records (value TEXT)"
    )
    connection.commit()
    connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    for number in range(100):
        connection.execute(
            "INSERT INTO records VALUES (?)",
            (f"Record {number}",),
        )

    connection.commit()

    try:
        yield database
    finally:
        connection.close()


def test_private_snapshot_preserves_wal(
    wal_database, staging
):
    destination = snapshot_sqlite_private(
        wal_database, staging
    )

    with sqlite3.connect(destination) as backup:
        assert backup.execute(
            "SELECT COUNT(*) FROM records"
        ).fetchone()[0] == 100

        assert backup.execute(
            "PRAGMA integrity_check"
        ).fetchone()[0] == "ok"


def test_private_snapshot_permissions(
    wal_database, staging
):
    destination = snapshot_sqlite_private(
        wal_database, staging
    )

    assert stat.S_IMODE(
        destination.parent.stat().st_mode
    ) == 0o700

    assert stat.S_IMODE(
        destination.stat().st_mode
    ) == 0o600


def test_invalid_database_cleans_staging(
    tmp_path, staging
):
    invalid = tmp_path / "invalid.db"
    invalid.write_bytes(b"Not a SQLite database")

    with pytest.raises(SQLiteSnapshotError):
        snapshot_sqlite_private(invalid, staging)

    assert not list(staging.iterdir())


def test_world_writable_staging_rejected(
    wal_database, tmp_path
):
    unsafe = tmp_path / "unsafe"
    unsafe.mkdir(mode=0o700)
    unsafe.chmod(0o777)

    with pytest.raises(SQLiteSnapshotError):
        snapshot_sqlite_private(wal_database, unsafe)

    assert not list(unsafe.iterdir())


def test_source_symlink_rejected(
    wal_database, staging, tmp_path
):
    linked = tmp_path / "linked.db"
    linked.symlink_to(wal_database)

    with pytest.raises(SQLiteSnapshotError):
        snapshot_sqlite_private(linked, staging)

    assert not list(staging.iterdir())
