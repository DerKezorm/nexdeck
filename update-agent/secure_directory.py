"""Descriptor-relative directory access without symlink traversal."""

from __future__ import annotations

import os
import stat
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from snapshot import SnapshotError


@contextmanager
def open_directory_chain(path: Path) -> Iterator[int]:
    """Open every directory component without following symlinks.

    Returns a descriptor for the final directory.
    All intermediate descriptors are closed automatically.
    """

    path = Path(path)

    if not path.is_absolute():
        raise SnapshotError(
            "Directory path must be absolute"
        )

    flags = (
        os.O_RDONLY
        | os.O_DIRECTORY
        | os.O_NOFOLLOW
        | os.O_CLOEXEC
    )

    descriptors = []

    try:
        current = os.open("/", flags)
        descriptors.append(current)

        for component in path.parts[1:]:
            if component in ("", ".", ".."):
                raise SnapshotError(
                    "Unsafe directory component"
                )

            next_fd = os.open(
                component,
                flags,
                dir_fd=current,
            )

            descriptors.append(next_fd)
            current = next_fd

            info = os.fstat(current)

            if not stat.S_ISDIR(info.st_mode):
                raise SnapshotError(
                    "Directory component is not a directory"
                )

        yield current

    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)
