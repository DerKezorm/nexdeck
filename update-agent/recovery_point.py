"""Offline recovery-point creation for disposable test data.

Not connected to live NexDeck, Docker or update execution.
"""

from __future__ import annotations

import ctypes
import errno
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path

from snapshot import SnapshotError, copy_directory_tree


class RecoveryDurabilityError(SnapshotError):
    """A recovery point was published but durability is unconfirmed."""

    def __init__(self, recovery_path: Path):
        self.recovery_path = recovery_path
        super().__init__(
            "Recovery point published but durability unconfirmed: "
            f"{recovery_path}"
        )


def publish_exclusively(
    staging: Path,
    final: Path,
) -> None:
    """Publish without replacing an existing filesystem entry."""

    libc = ctypes.CDLL(None, use_errno=True)

    renameat2 = getattr(libc, "renameat2", None)

    if renameat2 is None:
        raise SnapshotError(
            "Exclusive publication is unsupported"
        )

    renameat2.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    renameat2.restype = ctypes.c_int

    result = renameat2(
        -100,
        os.fsencode(staging),
        -100,
        os.fsencode(final),
        1,
    )

    if result != 0:
        error = ctypes.get_errno()

        if error == errno.EEXIST:
            raise SnapshotError(
                "Recovery point already exists"
            )

        raise OSError(
            error,
            os.strerror(error),
        )


def create_recovery_point(
    source: Path,
    recovery_root: Path,
    recovery_id: str,
) -> Path:
    """Copy, verify and publish an offline recovery point."""

    if (
        not recovery_id
        or not all(
            c.isascii() and (c.isalnum() or c in "-_")
            for c in recovery_id
        )
    ):
        raise SnapshotError("Invalid recovery identifier")

    if not recovery_root.is_dir():
        raise SnapshotError("Recovery root does not exist")

    source_resolved = source.resolve(strict=True)
    recovery_resolved = recovery_root.resolve(strict=True)

    if not source_resolved.is_dir():
        raise SnapshotError("Source must be a directory")

    if (
        source_resolved == recovery_resolved
        or source_resolved in recovery_resolved.parents
        or recovery_resolved in source_resolved.parents
    ):
        raise SnapshotError(
            "Source and recovery directories must not overlap"
        )

    final = recovery_root / recovery_id

    if final.exists() or final.is_symlink():
        raise SnapshotError("Recovery point already exists")

    staging = Path(
        tempfile.mkdtemp(
            prefix=".nexdeck-staging-",
            dir=recovery_root,
        )
    )

    try:
        data = staging / "data"
        data.mkdir(mode=0o700)

        records = copy_directory_tree(source, data)

        def directory_names(root: Path) -> list[str]:
            names = []

            for entry in root.rglob("*"):
                if entry.is_symlink():
                    raise SnapshotError(
                        "Symbolic link found during verification"
                    )
                if entry.is_dir():
                    names.append(
                        entry.relative_to(root).as_posix()
                    )

            return sorted(names)

        source_directories = directory_names(source)
        copied_directories = directory_names(data)

        if source_directories != copied_directories:
            raise SnapshotError(
                "Directory structure changed during snapshot"
            )

        for record in records:
            path = data / record.path

            digest = hashlib.sha256()
            size = 0

            with path.open("rb") as stream:
                for block in iter(
                    lambda: stream.read(1024 * 1024),
                    b"",
                ):
                    digest.update(block)
                    size += len(block)

            if (
                digest.hexdigest() != record.sha256
                or size != record.size
            ):
                raise SnapshotError(
                    f"Verification failed: {record.path}"
                )

        manifest = {
            "format_version": 1,
            "recovery_id": recovery_id,
            "directories": copied_directories,
            "files": [
                {
                    "path": record.path,
                    "size": record.size,
                    "sha256": record.sha256,
                }
                for record in records
            ],
        }

        manifest_path = staging / "manifest.json"

        manifest_fd = os.open(
            manifest_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
        )

        with os.fdopen(manifest_fd, "w", encoding="utf-8") as stream:
            json.dump(manifest, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())

        directory_flags = (
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        )

        staging_fd = os.open(staging, directory_flags)

        try:
            os.fsync(staging_fd)
        finally:
            os.close(staging_fd)

        recovery_fd = os.open(
            recovery_root,
            directory_flags,
        )

        try:
            publish_exclusively(staging, final)

            try:
                os.fsync(recovery_fd)
            except OSError as exc:
                raise RecoveryDurabilityError(final) from exc
        finally:
            os.close(recovery_fd)

        return final

    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
