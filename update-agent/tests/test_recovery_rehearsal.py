"""Tests for disposable NexDeck recovery rehearsals."""

import hashlib
import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[1]),
)

from recovery_point import create_recovery_point
from recovery_rehearsal import (
    RecoveryRehearsalError,
    rehearse_recovery,
)
from recovery_verify import RecoveryVerificationError


@pytest.fixture
def rehearsal_workspace(tmp_path):
    source = tmp_path / "source"
    recovery = tmp_path / "recovery"
    destination = tmp_path / "restored"

    source.mkdir()
    recovery.mkdir()

    with sqlite3.connect(source / "nexdeck.db") as connection:
        connection.execute(
            "CREATE TABLE example "
            "(id INTEGER PRIMARY KEY, value TEXT)"
        )
        connection.execute(
            "INSERT INTO example(value) VALUES ('recoverable')"
        )

    profile = {
        "version": "test",
        "schema": 1,
        "kind": "manual",
        "note": "Pre-update restore point",
        "contains": [
            "nexdeck.db",
            "avatars/example.png",
        ],
        "emptied": [],
    }

    (source / "nexdeck-backup.json").write_text(
        json.dumps(profile)
    )

    key = source / "secret.key"
    key.write_text("disposable-recovery-key")
    key.chmod(0o600)

    avatars = source / "avatars"
    avatars.mkdir()
    (avatars / "example.png").write_bytes(
        b"recoverable-avatar"
    )

    package = create_recovery_point(
        source,
        recovery,
        "rehearsal-test-001",
    )

    return source, package, destination


def test_rehearses_complete_recovery(rehearsal_workspace):
    source, package, destination = rehearsal_workspace

    result = rehearse_recovery(package, destination)

    assert result == destination
    assert destination.is_dir()

    with sqlite3.connect(
        destination / "nexdeck.db"
    ) as connection:
        value = connection.execute(
            "SELECT value FROM example"
        ).fetchone()[0]

    assert value == "recoverable"

    for name in (
        "nexdeck.db",
        "nexdeck-backup.json",
        "secret.key",
        "avatars/example.png",
    ):
        original = (source / name).read_bytes()
        restored = (destination / name).read_bytes()

        assert hashlib.sha256(original).digest() == (
            hashlib.sha256(restored).digest()
        )


def test_rejects_existing_destination(rehearsal_workspace):
    _, package, destination = rehearsal_workspace

    destination.mkdir()
    (destination / "keep.txt").write_text("preserve")

    with pytest.raises(RecoveryRehearsalError):
        rehearse_recovery(package, destination)

    assert (destination / "keep.txt").read_text() == "preserve"


def test_rejects_corrupt_package_before_copy(
    rehearsal_workspace,
):
    _, package, destination = rehearsal_workspace

    (package / "data" / "nexdeck.db").write_bytes(
        b"corrupt"
    )

    with pytest.raises(RecoveryVerificationError):
        rehearse_recovery(package, destination)

    assert not destination.exists()


def test_rejects_missing_encryption_key(
    rehearsal_workspace,
):
    _, package, destination = rehearsal_workspace

    (package / "data" / "secret.key").unlink()

    with pytest.raises(RecoveryVerificationError):
        rehearse_recovery(package, destination)

    assert not destination.exists()


def test_does_not_delete_replaced_destination(
    rehearsal_workspace,
    monkeypatch,
    tmp_path,
):
    import recovery_rehearsal

    _, package, destination = rehearsal_workspace

    def create_competing_destination_then_fail(
        source,
        staging,
    ):
        # Simulate another process creating the requested
        # destination while the rehearsal copies into staging.
        assert staging != destination

        destination.mkdir()
        (destination / "important.txt").write_text(
            "must not be deleted"
        )

        raise RuntimeError("simulated copy failure")

    monkeypatch.setattr(
        recovery_rehearsal,
        "copy_directory_tree",
        create_competing_destination_then_fail,
    )

    with pytest.raises(RuntimeError):
        rehearse_recovery(package, destination)

    assert (
        destination / "important.txt"
    ).read_text() == "must not be deleted"


def test_competing_destination_at_publication_is_preserved(
    rehearsal_workspace,
    monkeypatch,
):
    import recovery_rehearsal

    _, package, destination = rehearsal_workspace

    original_publish = recovery_rehearsal.publish_exclusively

    def competing_publish(staging, final):
        assert final == destination
        assert staging.is_dir()

        # Another process creates the destination immediately
        # before our exclusive publication attempt.
        final.mkdir()
        (final / "important.txt").write_text(
            "competing process data"
        )

        return original_publish(staging, final)

    monkeypatch.setattr(
        recovery_rehearsal,
        "publish_exclusively",
        competing_publish,
    )

    with pytest.raises(Exception):
        rehearse_recovery(package, destination)

    assert (
        destination / "important.txt"
    ).read_text() == "competing process data"

    assert not list(
        destination.parent.glob(".nexdeck-rehearsal-*")
    )


def test_rejects_source_changed_after_verification(
    rehearsal_workspace,
    monkeypatch,
):
    import recovery_rehearsal

    _, package, destination = rehearsal_workspace

    original_copy = recovery_rehearsal.copy_directory_tree

    def modify_source_then_copy(source, target):
        # Package verification has already completed.
        # Simulate an attachment changing before copying.
        attachment = source / "avatars" / "example.png"

        attachment.write_bytes(
            b"modified-after-verification"
        )

        return original_copy(source, target)

    monkeypatch.setattr(
        recovery_rehearsal,
        "copy_directory_tree",
        modify_source_then_copy,
    )

    with pytest.raises(Exception):
        rehearse_recovery(package, destination)

    assert not destination.exists()


def test_rejects_manifest_replaced_after_verification(
    rehearsal_workspace,
    monkeypatch,
):
    import recovery_rehearsal

    _, package, destination = rehearsal_workspace

    original_verify = (
        recovery_rehearsal.verify_nexdeck_recovery_package
    )

    def verify_then_replace_manifest(path):
        result = original_verify(path)

        manifest_path = path / "manifest.json"

        manifest = json.loads(
            manifest_path.read_text(encoding="utf-8")
        )

        # Change a manifest hash after the original verifier
        # has accepted the package.
        for record in manifest["files"]:
            if record["path"] == "avatars/example.png":
                record["sha256"] = "0" * 64
                break

        manifest_path.write_text(
            json.dumps(manifest),
            encoding="utf-8",
        )

        return result

    monkeypatch.setattr(
        recovery_rehearsal,
        "verify_nexdeck_recovery_package",
        verify_then_replace_manifest,
    )

    with pytest.raises(Exception):
        rehearse_recovery(package, destination)

    assert not destination.exists()


def test_rejects_coordinated_replacement_after_verification(
    rehearsal_workspace,
    monkeypatch,
):
    import hashlib
    import json
    import recovery_rehearsal

    _, package, destination = rehearsal_workspace

    original_verify = (
        recovery_rehearsal.verify_nexdeck_recovery_package
    )

    def verify_then_replace(path):
        result = original_verify(path)

        attachment = (
            path / "data" / "avatars" / "example.png"
        )

        replacement = b"unauthorised-replacement"
        attachment.write_bytes(replacement)

        manifest_path = path / "manifest.json"

        manifest = json.loads(
            manifest_path.read_text(encoding="utf-8")
        )

        updated = False

        for record in manifest["files"]:
            if record["path"] == "avatars/example.png":
                record["size"] = len(replacement)
                record["sha256"] = hashlib.sha256(
                    replacement
                ).hexdigest()
                updated = True
                break

        assert updated

        manifest_path.write_text(
            json.dumps(manifest),
            encoding="utf-8",
        )

        return result

    monkeypatch.setattr(
        recovery_rehearsal,
        "verify_nexdeck_recovery_package",
        verify_then_replace,
    )

    with pytest.raises(Exception):
        rehearse_recovery(package, destination)

    assert not destination.exists()


def test_rejects_staging_modified_before_publication(
    rehearsal_workspace,
    monkeypatch,
):
    import recovery_rehearsal

    _, package, destination = rehearsal_workspace

    original_publish = (
        recovery_rehearsal.publish_exclusively
    )

    def corrupt_staging_then_publish(staging, final):
        assert final == destination

        attachment = (
            staging / "avatars" / "example.png"
        )

        attachment.write_bytes(
            b"modified-after-final-verification"
        )

        return original_publish(staging, final)

    monkeypatch.setattr(
        recovery_rehearsal,
        "publish_exclusively",
        corrupt_staging_then_publish,
    )

    with pytest.raises(Exception):
        rehearse_recovery(package, destination)

    assert not destination.exists()
