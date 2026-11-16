"""Regression tests for offline recovery-point creation."""

import hashlib
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[1]),
)

import recovery_point
from snapshot import SnapshotError


@pytest.fixture
def workspace(tmp_path):
    source = tmp_path / "source"
    recovery = tmp_path / "recovery"

    source.mkdir()
    recovery.mkdir()

    (source / "boards").mkdir()
    (source / "boards" / "main.yaml").write_text(
        "title: Test Board\n"
    )
    (source / "secret.key").write_bytes(os.urandom(64))

    return source, recovery


def test_creates_verified_recovery_point(workspace):
    source, recovery = workspace

    result = recovery_point.create_recovery_point(
        source, recovery, "backup-001"
    )

    manifest = json.loads(
        (result / "manifest.json").read_text()
    )

    assert manifest["recovery_id"] == "backup-001"
    assert len(manifest["files"]) == 2

    for record in manifest["files"]:
        copied = (result / "data" / record["path"]).read_bytes()
        assert record["size"] == len(copied)
        assert record["sha256"] == hashlib.sha256(
            copied
        ).hexdigest()


def test_rejects_duplicate_recovery_id(workspace):
    source, recovery = workspace

    recovery_point.create_recovery_point(
        source, recovery, "backup-001"
    )

    with pytest.raises(SnapshotError):
        recovery_point.create_recovery_point(
            source, recovery, "backup-001"
        )


def test_rejects_overlapping_directories(workspace):
    source, recovery = workspace

    nested = source / "backups"
    nested.mkdir()

    with pytest.raises(SnapshotError, match="overlap"):
        recovery_point.create_recovery_point(
            source, nested, "backup-001"
        )

    with pytest.raises(SnapshotError, match="overlap"):
        recovery_point.create_recovery_point(
            source, source, "backup-001"
        )


def test_rejects_symlink_and_cleans_staging(workspace):
    source, recovery = workspace

    (source / "unsafe").symlink_to(
        source / "secret.key"
    )

    with pytest.raises((SnapshotError, OSError)):
        recovery_point.create_recovery_point(
            source, recovery, "backup-001"
        )

    assert not (recovery / "backup-001").exists()
    assert not list(recovery.glob(".nexdeck-staging-*"))


def test_reports_uncertain_durability(workspace):
    source, recovery = workspace

    original_fsync = os.fsync
    recovery_stat = recovery.stat()

    def fail_recovery_directory_sync(fd):
        info = os.fstat(fd)

        if (
            info.st_dev == recovery_stat.st_dev
            and info.st_ino == recovery_stat.st_ino
        ):
            raise OSError("Simulated fsync failure")

        return original_fsync(fd)

    with patch.object(
        recovery_point.os,
        "fsync",
        side_effect=fail_recovery_directory_sync,
    ):
        with pytest.raises(
            recovery_point.RecoveryDurabilityError
        ) as captured:
            recovery_point.create_recovery_point(
                source, recovery, "backup-001"
            )

    published = recovery / "backup-001"

    assert captured.value.recovery_path == published
    assert published.is_dir()
    assert (published / "manifest.json").is_file()
    assert not list(recovery.glob(".nexdeck-staging-*"))
