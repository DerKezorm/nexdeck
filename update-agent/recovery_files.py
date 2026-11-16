"""Secure creation of retained Docker Compose recovery overrides."""

from __future__ import annotations

import os
import stat
from pathlib import Path


class RecoveryFileError(RuntimeError):
    """Recovery evidence cannot be created safely."""


def write_recovery_override(
    project_directory: Path,
    content: str,
) -> Path:
    """Create a private, exclusive recovery override."""

    project_directory = Path(project_directory)

    if not project_directory.is_absolute():
        raise RecoveryFileError("Project directory must be absolute")

    recovery_dir = project_directory / ".nexdeck-recovery"

    try:
        recovery_dir.mkdir(mode=0o700, exist_ok=True)

        directory_stat = recovery_dir.lstat()

        if not stat.S_ISDIR(directory_stat.st_mode):
            raise RecoveryFileError(
                "Recovery path is not a real directory"
            )

        if directory_stat.st_mode & 0o077:
            raise RecoveryFileError(
                "Recovery directory permissions are too broad"
            )

        override = recovery_dir / "rollback.override.yaml"

        flags = (
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
        )

        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW

        fd = os.open(override, flags, 0o600)

        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)

        return override

    except RecoveryFileError:
        raise
    except OSError as exc:
        raise RecoveryFileError(
            f"Cannot safely create recovery override: {exc}"
        ) from exc
