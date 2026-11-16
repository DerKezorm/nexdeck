"""Offline tests for secure recovery file creation."""

import os
import stat

import pytest

from recovery_files import (
    RecoveryFileError,
    write_recovery_override,
)


def test_creates_private_override(tmp_path):
    path = write_recovery_override(
        tmp_path,
        "services:\n  nexdeck:\n    image: test\n",
    )

    assert path.exists()
    assert path.read_text().startswith("services:")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700


def test_refuses_existing_override(tmp_path):
    write_recovery_override(tmp_path, "original")

    with pytest.raises(RecoveryFileError):
        write_recovery_override(tmp_path, "replacement")

    assert (
        tmp_path
        / ".nexdeck-recovery"
        / "rollback.override.yaml"
    ).read_text() == "original"


def test_refuses_symlinked_recovery_directory(tmp_path):
    target = tmp_path / "target"
    target.mkdir()

    link = tmp_path / ".nexdeck-recovery"
    link.symlink_to(target, target_is_directory=True)

    with pytest.raises(RecoveryFileError):
        write_recovery_override(tmp_path, "unsafe")

    assert list(target.iterdir()) == []


def test_refuses_world_readable_recovery_directory(tmp_path):
    directory = tmp_path / ".nexdeck-recovery"
    directory.mkdir(mode=0o700)
    os.chmod(directory, 0o755)

    with pytest.raises(RecoveryFileError):
        write_recovery_override(tmp_path, "unsafe")
