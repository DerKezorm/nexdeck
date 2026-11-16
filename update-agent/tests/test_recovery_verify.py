"""Published recovery-package verification tests."""

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
    verify_recovery_package,
)


@pytest.fixture
def published_package(tmp_path):
    source = tmp_path / "source"
    recovery = tmp_path / "recovery"

    source.mkdir()
    recovery.mkdir()

    (source / "example.txt").write_text(
        "original recovery content"
    )

    return create_recovery_point(
        source,
        recovery,
        "verify-test-001",
    )


def test_accepts_valid_package(published_package):
    assert verify_recovery_package(
        published_package
    ) is True


def test_rejects_modified_file(published_package):
    (
        published_package / "data" / "example.txt"
    ).write_text("tampered")

    with pytest.raises(RecoveryVerificationError):
        verify_recovery_package(published_package)


def test_rejects_extra_file(published_package):
    (
        published_package / "data" / "unexpected.txt"
    ).write_text("unexpected")

    with pytest.raises(RecoveryVerificationError):
        verify_recovery_package(published_package)


def test_rejects_duplicate_manifest_entry(published_package):
    path = published_package / "manifest.json"
    manifest = json.loads(path.read_text())

    manifest["files"].append(
        dict(manifest["files"][0])
    )

    path.write_text(json.dumps(manifest))

    with pytest.raises(RecoveryVerificationError):
        verify_recovery_package(published_package)


def test_rejects_manifest_path_traversal(published_package):
    path = published_package / "manifest.json"
    manifest = json.loads(path.read_text())

    manifest["files"][0]["path"] = "../outside"

    path.write_text(json.dumps(manifest))

    with pytest.raises(RecoveryVerificationError):
        verify_recovery_package(published_package)


def test_rejects_symlinked_file(published_package):
    file = published_package / "data" / "example.txt"
    file.unlink()
    file.symlink_to(
        published_package / "manifest.json"
    )

    with pytest.raises(RecoveryVerificationError):
        verify_recovery_package(published_package)


def test_rejects_duplicate_manifest_directory(
    published_package,
):
    path = published_package / "manifest.json"
    manifest = json.loads(path.read_text())

    # Add a directory to the fixture, then duplicate its
    # manifest declaration.
    directory = published_package / "data" / "attachments"
    directory.mkdir()

    manifest["directories"] = [
        "attachments",
        "attachments",
    ]

    path.write_text(json.dumps(manifest))

    with pytest.raises(RecoveryVerificationError):
        verify_recovery_package(published_package)


def test_rejects_unexpected_empty_directory(
    published_package,
):
    directory = published_package / "data" / "unexpected"
    directory.mkdir()

    with pytest.raises(RecoveryVerificationError):
        verify_recovery_package(published_package)
