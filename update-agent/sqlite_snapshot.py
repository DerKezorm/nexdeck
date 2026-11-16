"""SQLite online-backup primitive for NexDeck recovery snapshots.

Not connected to live deployments or update execution.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path


class SQLiteSnapshotError(ValueError):
    """A consistent SQLite snapshot could not be created."""


def snapshot_sqlite(
    source: Path,
    destination: Path,
) -> None:
    """Create and integrity-check a standalone SQLite backup."""

    source = Path(source)
    destination = Path(destination)

    if not source.is_file() or source.is_symlink():
        raise SQLiteSnapshotError(
            "Source must be a regular database file"
        )

    if destination.exists() or destination.is_symlink():
        raise SQLiteSnapshotError(
            "Destination already exists"
        )

    source_uri = source.resolve(strict=True).as_uri() + "?mode=ro"

    created = False
    completed = False

    try:
        # Reserve the destination exclusively before SQLite opens it.
        flags = (
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0)
        )

        fd = os.open(destination, flags, 0o600)
        created = True
        os.close(fd)

        with sqlite3.connect(
            source_uri,
            uri=True,
            timeout=5,
        ) as original:
            with sqlite3.connect(destination) as backup:
                original.backup(
                    backup,
                    pages=128,
                    sleep=0.05,
                )

                result = backup.execute(
                    "PRAGMA integrity_check"
                ).fetchone()

                if result is None or result[0] != "ok":
                    raise SQLiteSnapshotError(
                        "Snapshot failed SQLite integrity check"
                    )

        with destination.open("rb") as output:
            os.fsync(output.fileno())

        directory_fd = os.open(
            destination.parent,
            os.O_RDONLY | os.O_DIRECTORY,
        )

        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)

        completed = True

    except (sqlite3.Error, OSError) as exc:
        raise SQLiteSnapshotError(
            f"SQLite snapshot failed: {exc}"
        ) from exc

    finally:
        if created and not completed:
            try:
                destination.unlink(missing_ok=True)
            except OSError:
                pass
