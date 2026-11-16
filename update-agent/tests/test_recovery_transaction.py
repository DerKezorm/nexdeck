"""Offline tests for transactional recovery preparation."""

from unittest.mock import patch

import pytest

from recovery_transaction import (
    RecoveryTransactionError,
    prepare_recovery_transaction,
)


def make_fixture(tmp_path):
    package = tmp_path / "package"
    source = package / "data"
    (source / "uploads").mkdir(parents=True)

    (source / "nexdeck.db").write_bytes(b"backup-database")
    (source / "secret.key").write_bytes(b"backup-key")
    (source / "nexdeck-backup.json").write_text("{}")
    (source / "uploads" / "example.txt").write_text("backup-file")

    live = tmp_path / "live"
    live.mkdir()
    (live / "nexdeck.db").write_bytes(b"live-database")
    (live / "secret.key").write_bytes(b"live-key")

    transaction_root = tmp_path / "transactions"
    transaction_root.mkdir()

    return package, live, transaction_root


def test_preparation_preserves_live_data(tmp_path):
    package, live, root = make_fixture(tmp_path)

    with patch(
        "recovery_transaction.verify_nexdeck_recovery_package",
        return_value=True,
    ):
        prepared = prepare_recovery_transaction(
            package, live, root
        )

    staged = prepared.staging_directory

    assert (staged / "nexdeck.db").read_bytes() == b"backup-database"
    assert (staged / "secret.key").read_bytes() == b"backup-key"
    assert (
        staged / "uploads" / "example.txt"
    ).read_text() == "backup-file"

    assert (live / "nexdeck.db").read_bytes() == b"live-database"
    assert (live / "secret.key").read_bytes() == b"live-key"
    assert prepared.original_directory == live
    assert prepared.recovery_package == package


def test_preparation_rejects_overlapping_paths(tmp_path):
    package, live, root = make_fixture(tmp_path)

    with patch(
        "recovery_transaction.verify_nexdeck_recovery_package",
        return_value=True,
    ):
        with pytest.raises(
            RecoveryTransactionError,
            match="paths overlap",
        ):
            prepare_recovery_transaction(
                package,
                live,
                live,
            )


def test_preparation_rejects_invalid_package(tmp_path):
    package, live, root = make_fixture(tmp_path)

    with patch(
        "recovery_transaction.verify_nexdeck_recovery_package",
        return_value=False,
    ):
        with pytest.raises(
            RecoveryTransactionError,
            match="Recovery package verification failed",
        ):
            prepare_recovery_transaction(
                package,
                live,
                root,
            )


def test_replacement_tree_restores_data_and_preserves_original(tmp_path):
    """Build an exact recovery tree without modifying live data."""
    import sqlite3

    from recovery_transaction import build_replacement_directory

    package, live, root = make_fixture(tmp_path)

    # Replace the placeholder database with a genuine SQLite database.
    database = package / "data" / "nexdeck.db"
    database.unlink()

    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE recovery (value TEXT)")
        connection.execute(
            "INSERT INTO recovery VALUES ('before-update')"
        )

    (live / "nexdeck.db").write_bytes(b"changed-database")
    (live / "nexdeck.db-wal").write_bytes(b"old-wal")
    (live / "nexdeck.db-shm").write_bytes(b"old-shm")

    (live / "uploads").mkdir()
    (live / "uploads" / "new-file.txt").write_text(
        "created-after-backup"
    )

    (live / "logs").mkdir()
    (live / "logs" / "nexdeck.log").write_text("keep-log")

    (live / "backups").mkdir()
    (live / "backups" / "existing.db").write_bytes(
        b"keep-backup"
    )

    with patch(
        "recovery_transaction.verify_nexdeck_recovery_package",
        return_value=True,
    ):
        prepared = prepare_recovery_transaction(
            package, live, root
        )

    replacement = root / "replacement"

    result = build_replacement_directory(
        prepared,
        replacement,
    )

    assert result == replacement

    with sqlite3.connect(replacement / "nexdeck.db") as connection:
        value = connection.execute(
            "SELECT value FROM recovery"
        ).fetchone()

    assert value == ("before-update",)

    assert (
        replacement / "secret.key"
    ).read_bytes() == b"backup-key"

    assert (
        replacement / "uploads" / "example.txt"
    ).read_text() == "backup-file"

    assert not (
        replacement / "uploads" / "new-file.txt"
    ).exists()

    assert not (replacement / "nexdeck.db-wal").exists()
    assert not (replacement / "nexdeck.db-shm").exists()

    assert (
        replacement / "logs" / "nexdeck.log"
    ).read_text() == "keep-log"

    assert (
        replacement / "backups" / "existing.db"
    ).read_bytes() == b"keep-backup"

    # The original application data must remain unchanged.
    assert (live / "nexdeck.db").read_bytes() == b"changed-database"
    assert (live / "nexdeck.db-wal").read_bytes() == b"old-wal"

    assert (
        live / "uploads" / "new-file.txt"
    ).read_text() == "created-after-backup"


def test_commit_switches_directories_and_retains_original(tmp_path):
    from recovery_transaction import (
        PreparedRecovery,
        commit_recovery_transaction,
    )

    original = tmp_path / "data"
    replacement = tmp_path / "replacement"
    retained = tmp_path / "data-before-restore"

    original.mkdir()
    replacement.mkdir()

    (original / "state.txt").write_text("original")
    (replacement / "state.txt").write_text("restored")

    prepared = PreparedRecovery(
        staging_directory=tmp_path / "staging",
        original_directory=original,
        recovery_package=tmp_path / "package",
    )

    result = commit_recovery_transaction(
        prepared,
        replacement,
        retained,
        application_stopped=True,
    )

    assert result == retained
    assert (original / "state.txt").read_text() == "restored"
    assert (retained / "state.txt").read_text() == "original"
    assert not replacement.exists()


def test_commit_refuses_running_application(tmp_path):
    from recovery_transaction import (
        PreparedRecovery,
        RecoveryTransactionError,
        commit_recovery_transaction,
    )

    original = tmp_path / "data"
    replacement = tmp_path / "replacement"
    retained = tmp_path / "data-before-restore"

    original.mkdir()
    replacement.mkdir()

    prepared = PreparedRecovery(
        staging_directory=tmp_path / "staging",
        original_directory=original,
        recovery_package=tmp_path / "package",
    )

    with pytest.raises(
        RecoveryTransactionError,
        match="Application must be stopped",
    ):
        commit_recovery_transaction(
            prepared,
            replacement,
            retained,
        )

    assert original.is_dir()
    assert replacement.is_dir()
    assert not retained.exists()


def test_commit_restores_original_when_second_rename_fails(tmp_path):
    import os

    from recovery_transaction import (
        PreparedRecovery,
        RecoveryTransactionError,
        commit_recovery_transaction,
    )

    original = tmp_path / "data"
    replacement = tmp_path / "replacement"
    retained = tmp_path / "data-before-restore"

    original.mkdir()
    replacement.mkdir()

    (original / "state.txt").write_text("original")
    (replacement / "state.txt").write_text("restored")

    prepared = PreparedRecovery(
        staging_directory=tmp_path / "staging",
        original_directory=original,
        recovery_package=tmp_path / "package",
    )

    real_rename = os.rename
    calls = []

    def simulated_rename(source, destination):
        calls.append((source, destination))

        if len(calls) == 2:
            raise OSError("Simulated filesystem failure")

        return real_rename(source, destination)

    with patch(
        "recovery_transaction.os.rename",
        side_effect=simulated_rename,
    ):
        with pytest.raises(
            RecoveryTransactionError,
            match="original directory restored",
        ):
            commit_recovery_transaction(
                prepared,
                replacement,
                retained,
                application_stopped=True,
            )

    assert (original / "state.txt").read_text() == "original"
    assert (replacement / "state.txt").read_text() == "restored"
    assert not retained.exists()
    assert len(calls) == 3


def test_interrupted_commit_restores_original_directory(tmp_path):
    from recovery_transaction import recover_interrupted_commit

    original = tmp_path / "data"
    replacement = tmp_path / "replacement"
    retained = tmp_path / "data-before-restore"

    replacement.mkdir()
    retained.mkdir()

    (retained / "state.txt").write_text("original-data")
    (replacement / "state.txt").write_text("restored-data")

    result = recover_interrupted_commit(
        original,
        replacement,
        retained,
    )

    assert result == "original_restored"
    assert (original / "state.txt").read_text() == "original-data"
    assert (replacement / "state.txt").read_text() == "restored-data"
    assert not retained.exists()


def test_interrupted_commit_never_overwrites_existing_data(tmp_path):
    from recovery_transaction import recover_interrupted_commit

    original = tmp_path / "data"
    replacement = tmp_path / "replacement"
    retained = tmp_path / "data-before-restore"

    original.mkdir()
    replacement.mkdir()
    retained.mkdir()

    (original / "state.txt").write_text("current-data")
    (retained / "state.txt").write_text("previous-data")

    result = recover_interrupted_commit(
        original,
        replacement,
        retained,
    )

    assert result == "commit_present_original_retained"
    assert (original / "state.txt").read_text() == "current-data"
    assert (retained / "state.txt").read_text() == "previous-data"
