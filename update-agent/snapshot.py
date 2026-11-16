"""Secure file-copy primitives for NexDeck recovery snapshots.

Not yet connected to Docker, live application data or update execution.
"""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass


class SnapshotError(ValueError):
    """A snapshot operation could not be completed safely."""


@dataclass(frozen=True)
class CopiedFile:
    size: int
    sha256: str


def copy_regular_file(
    source_dir_fd: int,
    source_name: str,
    destination_dir_fd: int,
    destination_name: str,
) -> CopiedFile:
    """Copy one regular file without following filename symlinks."""

    for name in (source_name, destination_name):
        if (
            not name
            or name in (".", "..")
            or "/" in name
            or "\x00" in name
        ):
            raise SnapshotError("Unsafe filename")

    for directory_fd in (source_dir_fd, destination_dir_fd):
        directory_stat = os.fstat(directory_fd)
        if not stat.S_ISDIR(directory_stat.st_mode):
            raise SnapshotError(
                "Snapshot directory handle is not a directory"
            )

    source_fd = os.open(
        source_name,
        os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
        dir_fd=source_dir_fd,
    )

    try:
        before = os.fstat(source_fd)

        if not stat.S_ISREG(before.st_mode):
            raise SnapshotError("Source is not a regular file")

        destination_fd = os.open(
            destination_name,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | os.O_NOFOLLOW,
            0o600,
            dir_fd=destination_dir_fd,
        )

        try:
            digest = hashlib.sha256()
            total = 0

            while True:
                block = os.read(source_fd, 1024 * 1024)

                if not block:
                    break

                digest.update(block)
                total += len(block)

                view = memoryview(block)

                while view:
                    written = os.write(destination_fd, view)

                    if written <= 0:
                        raise SnapshotError("Incomplete file write")

                    view = view[written:]

            os.fsync(destination_fd)

            after = os.fstat(source_fd)

            if (
                before.st_dev != after.st_dev
                or before.st_ino != after.st_ino
                or before.st_size != after.st_size
                or before.st_mtime_ns != after.st_mtime_ns
                or before.st_ctime_ns != after.st_ctime_ns
                or total != before.st_size
            ):
                raise SnapshotError(
                    "Source changed during snapshot"
                )

            return CopiedFile(
                size=total,
                sha256=digest.hexdigest(),
            )

        except BaseException:
            try:
                os.unlink(
                    destination_name,
                    dir_fd=destination_dir_fd,
                )
            except OSError:
                pass
            raise
        finally:
            os.close(destination_fd)

    finally:
        os.close(source_fd)


@dataclass(frozen=True)
class SnapshotFile:
    path: str
    size: int
    sha256: str


def copy_directory_tree(
    source_root: Path,
    destination_root: Path,
) -> list[SnapshotFile]:
    """Copy a directory tree using descriptor-relative operations.

    Both roots must already exist. The destination must be empty.
    This function is intended for disposable, offline test data.
    """
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW

    source_fd = os.open(source_root, flags)
    try:
        destination_fd = os.open(destination_root, flags)
        try:
            if os.listdir(destination_fd):
                raise SnapshotError(
                    "Destination directory must be empty"
                )

            records: list[SnapshotFile] = []

            def walk(
                src_fd: int,
                dst_fd: int,
                prefix: str,
            ) -> None:
                for name in sorted(os.listdir(src_fd)):
                    if name in (".", ".."):
                        raise SnapshotError("Unsafe directory entry")

                    info = os.stat(
                        name,
                        dir_fd=src_fd,
                        follow_symlinks=False,
                    )

                    relative = (
                        f"{prefix}/{name}" if prefix else name
                    )

                    if stat.S_ISDIR(info.st_mode):
                        child_src = os.open(
                            name,
                            flags,
                            dir_fd=src_fd,
                        )
                        try:
                            os.mkdir(
                                name,
                                mode=0o700,
                                dir_fd=dst_fd,
                            )
                            child_dst = os.open(
                                name,
                                flags,
                                dir_fd=dst_fd,
                            )
                            try:
                                walk(
                                    child_src,
                                    child_dst,
                                    relative,
                                )
                                os.fsync(child_dst)
                            finally:
                                os.close(child_dst)
                        finally:
                            os.close(child_src)

                    elif stat.S_ISREG(info.st_mode):
                        copied = copy_regular_file(
                            src_fd,
                            name,
                            dst_fd,
                            name,
                        )
                        records.append(
                            SnapshotFile(
                                path=relative,
                                size=copied.size,
                                sha256=copied.sha256,
                            )
                        )

                    else:
                        raise SnapshotError(
                            f"Unsupported entry: {relative}"
                        )

            walk(source_fd, destination_fd, "")
            os.fsync(destination_fd)
            return sorted(records, key=lambda r: r.path)

        finally:
            os.close(destination_fd)
    finally:
        os.close(source_fd)
