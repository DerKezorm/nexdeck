"""Safely persist an agent-managed NexDeck image override."""

from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path

from image_override import ImageOverride


class ManagedOverrideError(RuntimeError):
    """Managed override cannot be written safely."""


def write_managed_override(override: ImageOverride) -> Path:
    path = override.path
    directory = path.parent

    if not path.is_absolute():
        raise ManagedOverrideError("Override path must be absolute")

    if directory.is_symlink():
        raise ManagedOverrideError("Override directory is a symlink")

    if directory.exists():
        if not directory.is_dir():
            raise ManagedOverrideError("Invalid override directory")
    else:
        directory.mkdir(mode=0o700)

    if path.is_symlink():
        raise ManagedOverrideError("Override path is a symlink")

    if path.exists():
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode):
            raise ManagedOverrideError("Override is not a regular file")
        if info.st_nlink != 1:
            raise ManagedOverrideError("Override has multiple hard links")

    temporary = None

    try:
        fd, name = tempfile.mkstemp(
            prefix=".image-",
            suffix=".tmp",
            dir=directory,
        )
        temporary = Path(name)

        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(override.content)
            stream.flush()
            os.fsync(stream.fileno())

        os.chmod(temporary, 0o600)
        os.replace(temporary, path)

        directory_fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)

        return path

    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
