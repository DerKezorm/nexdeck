"""NexDeck-specific published recovery verification tests."""

import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[1]),
)

from recovery_point import create_recovery_point
from recovery_verify import (
    RecoveryVerificationError,
    verify_nexdeck_recovery_package,
)


@pytest.fixture
def nexdeck_package(tmp_path):
    import sqlite3

    source = tmp_path / "source"
    recovery = tmp_path / "recovery"

    source.mkdir()
    recovery.mkdir()

    database = source / "nexdeck.db"

    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE example "
            "(id INTEGER PRIMARY KEY, value TEXT)"
        )
        connection.execute(
            "INSERT INTO example(value) VALUES ('original')"
        )

    profile = {
        "version": "test",
        "schema": 1,
        "created_at": "2026-11-12T13:00:00+00:00",
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
    key.write_text("disposable-test-secret")
    key.chmod(0o600)

    avatars = source / "avatars"
    avatars.mkdir()

    (avatars / "example.png").write_bytes(
        b"disposable-avatar"
    )

    return create_recovery_point(
        source,
        recovery,
        "nexdeck-verify-001",
    )


def rewrite_manifest(package):
    """Update manifest hashes to simulate consistent tampering."""

    manifest_path = package / "manifest.json"
    manifest = json.loads(manifest_path.read_text())

    records = []

    for file in sorted((package / "data").rglob("*")):
        if not file.is_file():
            continue

        records.append({
            "path": file.relative_to(
                package / "data"
            ).as_posix(),
            "size": file.stat().st_size,
            "sha256": hashlib.sha256(
                file.read_bytes()
            ).hexdigest(),
        })

    manifest["files"] = records
    manifest_path.write_text(json.dumps(manifest))


def test_accepts_complete_nexdeck_package(nexdeck_package):
    assert verify_nexdeck_recovery_package(nexdeck_package)


def test_rejects_missing_secret_key(nexdeck_package):
    (nexdeck_package / "data" / "secret.key").unlink()
    rewrite_manifest(nexdeck_package)

    with pytest.raises(RecoveryVerificationError):
        verify_nexdeck_recovery_package(nexdeck_package)


def test_rejects_corrupt_database_with_matching_hash(
    nexdeck_package,
):
    (nexdeck_package / "data" / "nexdeck.db").write_bytes(
        b"corrupted sqlite database"
    )
    rewrite_manifest(nexdeck_package)

    with pytest.raises(RecoveryVerificationError):
        verify_nexdeck_recovery_package(nexdeck_package)


def test_rejects_missing_profile(nexdeck_package):
    (
        nexdeck_package / "data" / "nexdeck-backup.json"
    ).unlink()
    rewrite_manifest(nexdeck_package)

    with pytest.raises(RecoveryVerificationError):
        verify_nexdeck_recovery_package(nexdeck_package)


def test_rejects_missing_declared_attachment(
    nexdeck_package,
):
    (
        nexdeck_package / "data" /
        "avatars" / "example.png"
    ).unlink()
    rewrite_manifest(nexdeck_package)

    with pytest.raises(RecoveryVerificationError):
        verify_nexdeck_recovery_package(nexdeck_package)


def test_rejects_insecure_secret_key_permissions(
    nexdeck_package,
):
    (
        nexdeck_package / "data" / "secret.key"
    ).chmod(0o644)

    with pytest.raises(RecoveryVerificationError):
        verify_nexdeck_recovery_package(nexdeck_package)


def test_rejects_colon_in_attachment_name(
    nexdeck_package,
):
    profile_path = (
        nexdeck_package / "data" / "nexdeck-backup.json"
    )

    profile = json.loads(profile_path.read_text())

    profile["contains"] = [
        "nexdeck.db",
        "avatars/example:alternate.png",
    ]

    profile_path.write_text(json.dumps(profile))

    original = (
        nexdeck_package / "data" /
        "avatars" / "example.png"
    )

    original.rename(
        nexdeck_package / "data" /
        "avatars" / "example:alternate.png"
    )

    rewrite_manifest(nexdeck_package)

    with pytest.raises(RecoveryVerificationError):
        verify_nexdeck_recovery_package(nexdeck_package)
