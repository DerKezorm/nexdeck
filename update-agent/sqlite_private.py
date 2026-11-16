"""Private-staging SQLite snapshot prototype.

For offline recovery testing only.
Not connected to live deployments or update execution.
"""

from __future__ import annotations

import os
import sqlite3
import stat
import tempfile
from pathlib import Path

from sqlite_snapshot import SQLiteSnapshotError


def snapshot_sqlite_private(
    source: Path,
    staging_root: Path,
) -> Path:
    """Create a verified SQLite backup in a private staging directory."""

    source = Path(source)
    staging_root = Path(staging_root)

    if not source.is_file() or source.is_symlink():
        raise SQLiteSnapshotError(
            "Source must be a regular SQLite database"
        )

    if not staging_root.is_dir() or staging_root.is_symlink():
        raise SQLiteSnapshotError(
            "Staging root must be a real directory"
        )

    root_info = staging_root.stat()

    if root_info.st_uid != os.geteuid():
        raise SQLiteSnapshotError(
            "Staging root must be owned by the current user"
        )

    if stat.S_IMODE(root_info.st_mode) & 0o022:
        raise SQLiteSnapshotError(
            "Staging root must not be group/world writable"
        )

    private = Path(
        tempfile.mkdtemp(
            prefix=".nexdeck-sqlite-",
            dir=staging_root,
        )
    )

    destination = private / "nexdeck.db"

    try:
        source_uri = (
            source.resolve(strict=True).as_uri()
            + "?mode=ro"
        )

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
                        "SQLite integrity verification failed"
                    )

        os.chmod(destination, 0o600)

        with destination.open("rb") as stream:
            os.fsync(stream.fileno())

        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW

        private_fd = os.open(private, flags)

        try:
            os.fsync(private_fd)
        finally:
            os.close(private_fd)

        root_fd = os.open(staging_root, flags)

        try:
            os.fsync(root_fd)
        finally:
            os.close(root_fd)

        return destination

    except BaseException as exc:
        # A failed private snapshot must never be returned as valid.
        import shutil
        shutil.rmtree(private, ignore_errors=True)

        if isinstance(exc, SQLiteSnapshotError):
            raise

        if isinstance(exc, (sqlite3.Error, OSError)):
            raise SQLiteSnapshotError(
                f"Private SQLite snapshot failed: {exc}"
            ) from exc

        raise
