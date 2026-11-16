"""Read-only recovery inventory for NexDeck deployments.

No Docker operations, file copies, restores or updates.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path


class RecoveryError(ValueError):
    """A recovery inventory cannot be safely constructed."""


@dataclass(frozen=True)
class FileRecord:
    path: str
    size: int
    sha256: str


def sha256_file(path: Path) -> str:
    """Hash a regular file without following its final symlink."""
    import os
    import stat

    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    fd = os.open(path, flags)

    try:
        before = os.fstat(fd)

        if not stat.S_ISREG(before.st_mode):
            raise RecoveryError(f"Not a regular file: {path}")

        digest = hashlib.sha256()

        with os.fdopen(os.dup(fd), "rb") as stream:
            for block in iter(
                lambda: stream.read(1024 * 1024),
                b"",
            ):
                digest.update(block)

        after = os.fstat(fd)

        if (
            before.st_dev != after.st_dev
            or before.st_ino != after.st_ino
            or before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
            or before.st_ctime_ns != after.st_ctime_ns
        ):
            raise RecoveryError(
                f"File changed during inventory: {path}"
            )

        return digest.hexdigest()
    finally:
        os.close(fd)


def inventory_directory(root: Path) -> list[FileRecord]:
    """Inventory regular files beneath a trusted directory.

    Symbolic links and special files are rejected.
    """

    if root.is_symlink() or not root.is_dir():
        raise RecoveryError("Recovery root must be a real directory")

    records = []

    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise RecoveryError(f"Symbolic link forbidden: {path}")

        if path.is_dir():
            continue

        if not path.is_file():
            raise RecoveryError(f"Special file forbidden: {path}")

        relative = path.relative_to(root).as_posix()

        records.append(
            FileRecord(
                path=relative,
                size=path.stat().st_size,
                sha256=sha256_file(path),
            )
        )

    return records
