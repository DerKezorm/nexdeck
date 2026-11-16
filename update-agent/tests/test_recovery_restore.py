"""Safety tests for NexDeck recovery restoration."""

from pathlib import Path
from unittest.mock import patch

import pytest

from recovery_restore import (
    RecoveryRestoreError,
    restore_application_data,
)


def make_fixture(tmp_path):
    package = tmp_path / "recovery"
    source = package / "data"
    source.mkdir(parents=True)

    (source / "nexdeck.db").write_bytes(b"snapshot-database")
    (source / "secret.key").write_bytes(b"snapshot-key")
    (source / "nexdeck-backup.json").write_text("{}")

    live = tmp_path / "live"
    live.mkdir()
    (live / "nexdeck.db").write_bytes(b"original-database")
    (live / "secret.key").write_bytes(b"original-key")

    return package, live


def test_restore_requires_stopped_application(tmp_path):
    package, live = make_fixture(tmp_path)

    with pytest.raises(
        RecoveryRestoreError,
        match="Application must be stopped",
    ):
        restore_application_data(package, live)

    assert (live / "nexdeck.db").read_bytes() == b"original-database"


def test_restore_rejects_symlinked_database(tmp_path):
    package, live = make_fixture(tmp_path)

    outside = tmp_path / "outside.db"
    outside.write_bytes(b"untouched")

    (live / "nexdeck.db").unlink()
    (live / "nexdeck.db").symlink_to(outside)

    with patch(
        "recovery_restore.verify_nexdeck_recovery_package",
        return_value=True,
    ):
        with pytest.raises(
            RecoveryRestoreError,
            match="Unsafe live application file",
        ):
            restore_application_data(
                package,
                live,
                application_stopped=True,
            )

    assert outside.read_bytes() == b"untouched"


def test_restore_rejects_symlinked_attachment_directory(tmp_path):
    package, live = make_fixture(tmp_path)

    outside = tmp_path / "outside"
    outside.mkdir()

    (live / "uploads").symlink_to(
        outside,
        target_is_directory=True,
    )

    with patch(
        "recovery_restore.verify_nexdeck_recovery_package",
        return_value=True,
    ):
        with pytest.raises(
            RecoveryRestoreError,
            match="Unsafe attachment directory",
        ):
            restore_application_data(
                package,
                live,
                application_stopped=True,
            )

    assert (live / "nexdeck.db").read_bytes() == b"original-database"


def test_restore_rejects_invalid_recovery_package(tmp_path):
    package, live = make_fixture(tmp_path)

    with patch(
        "recovery_restore.verify_nexdeck_recovery_package",
        return_value=False,
    ):
        with pytest.raises(
            RecoveryRestoreError,
            match="Recovery package verification failed",
        ):
            restore_application_data(
                package,
                live,
                application_stopped=True,
            )

    assert (live / "nexdeck.db").read_bytes() == b"original-database"


def test_restore_recovers_database_key_and_attachments(tmp_path):
    """Restore application files without disturbing unrelated data."""
    import sqlite3

    package = tmp_path / "recovery"
    source = package / "data"
    (source / "uploads").mkdir(parents=True)

    database = source / "nexdeck.db"

    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE recovery_test (value TEXT)"
        )
        connection.execute(
            "INSERT INTO recovery_test VALUES ('before-update')"
        )

    (source / "secret.key").write_bytes(b"original-secret-key")
    (source / "nexdeck-backup.json").write_text("{}")
    (source / "uploads" / "example.txt").write_text(
        "original-attachment"
    )

    live = tmp_path / "live"
    live.mkdir()

    with sqlite3.connect(live / "nexdeck.db") as connection:
        connection.execute(
            "CREATE TABLE recovery_test (value TEXT)"
        )
        connection.execute(
            "INSERT INTO recovery_test VALUES ('after-update')"
        )

    (live / "secret.key").write_bytes(b"changed-secret-key")

    (live / "uploads").mkdir()
    (live / "uploads" / "example.txt").write_text(
        "changed-attachment"
    )

    (live / "logs").mkdir()
    (live / "logs" / "nexdeck.log").write_text(
        "preserve-this-log"
    )

    (live / "backups").mkdir()
    (live / "backups" / "existing.db").write_bytes(
        b"preserve-this-backup"
    )

    with patch(
        "recovery_restore.verify_nexdeck_recovery_package",
        return_value=True,
    ):
        restore_application_data(
            package,
            live,
            application_stopped=True,
        )

    with sqlite3.connect(live / "nexdeck.db") as connection:
        result = connection.execute(
            "SELECT value FROM recovery_test"
        ).fetchone()

    assert result == ("before-update",)

    assert (live / "secret.key").read_bytes() == (
        b"original-secret-key"
    )

    assert (
        live / "uploads" / "example.txt"
    ).read_text() == "original-attachment"

    assert (
        live / "logs" / "nexdeck.log"
    ).read_text() == "preserve-this-log"

    assert (
        live / "backups" / "existing.db"
    ).read_bytes() == b"preserve-this-backup"
