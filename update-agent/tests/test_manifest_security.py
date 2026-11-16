"""Tests for deployment enrollment file security."""

import os
from pathlib import Path

import pytest

from manifest_security import (
    ManifestSecurityError,
    inspect_manifest_file,
)


def test_secure_manifest_accepted(tmp_path):
    path = tmp_path / "deployment.json"
    path.write_text("{}", encoding="utf-8")
    path.chmod(0o600)

    details = inspect_manifest_file(
        path,
        expected_uid=os.getuid(),
    )

    assert details.st_uid == os.getuid()


def test_incorrect_owner_rejected(tmp_path):
    path = tmp_path / "deployment.json"
    path.write_text("{}", encoding="utf-8")
    path.chmod(0o600)

    with pytest.raises(ManifestSecurityError):
        inspect_manifest_file(
            path,
            expected_uid=-1,
        )


@pytest.mark.parametrize(
    "permissions",
    [
        0o666,
        0o644 | 0o020,
        0o606,
        0o777,
    ],
)
def test_writable_manifest_rejected(tmp_path, permissions):
    path = tmp_path / "deployment.json"
    path.write_text("{}", encoding="utf-8")
    path.chmod(permissions)

    with pytest.raises(ManifestSecurityError):
        inspect_manifest_file(
            path,
            expected_uid=os.getuid(),
        )


def test_symlink_manifest_rejected(tmp_path):
    actual = tmp_path / "actual.json"
    actual.write_text("{}", encoding="utf-8")
    actual.chmod(0o600)

    link = tmp_path / "deployment.json"
    link.symlink_to(actual)

    with pytest.raises(ManifestSecurityError):
        inspect_manifest_file(
            link,
            expected_uid=os.getuid(),
        )


def test_directory_manifest_rejected(tmp_path):
    path = tmp_path / "deployment.json"
    path.mkdir()

    with pytest.raises(ManifestSecurityError):
        inspect_manifest_file(
            path,
            expected_uid=os.getuid(),
        )


def test_hardlinked_manifest_rejected(tmp_path):
    path = tmp_path / "deployment.json"
    path.write_text("{}", encoding="utf-8")
    path.chmod(0o600)

    second = tmp_path / "second.json"
    os.link(path, second)

    with pytest.raises(ManifestSecurityError):
        inspect_manifest_file(
            path,
            expected_uid=os.getuid(),
        )


def test_relative_manifest_path_rejected():
    with pytest.raises(ManifestSecurityError):
        inspect_manifest_file(
            Path("deployment.json"),
            expected_uid=os.getuid(),
        )


def test_parent_traversal_rejected(tmp_path):
    path = tmp_path / "subdir" / ".." / "deployment.json"

    with pytest.raises(ManifestSecurityError):
        inspect_manifest_file(
            path,
            expected_uid=os.getuid(),
        )


def test_missing_manifest_rejected(tmp_path):
    with pytest.raises(ManifestSecurityError):
        inspect_manifest_file(
            tmp_path / "missing.json",
            expected_uid=os.getuid(),
        )
