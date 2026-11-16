"""Restore NexDeck application data from a verified recovery package.

The caller must stop NexDeck before invoking this function.
This module does not control Docker or remove recovery packages.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import stat
from pathlib import Path

from recovery_verify import verify_nexdeck_recovery_package
from recovery_paths import valid_attachment_path
from snapshot import copy_directory_tree


class RecoveryRestoreError(RuntimeError):
    """Recovery data cannot be safely restored."""


def restore_application_data(
    package: Path,
    data_directory: Path,
    *,
    application_stopped: bool = False,
) -> None:
    """Restore a verified snapshot into an existing data directory."""

    if not application_stopped:
        raise RecoveryRestoreError(
            "Application must be stopped before restoration"
        )

    package = Path(package)
    data_directory = Path(data_directory)

    if not verify_nexdeck_recovery_package(package):
        raise RecoveryRestoreError(
            "Recovery package verification failed"
        )

    source = package / "data"

    if not data_directory.is_dir() or data_directory.is_symlink():
        raise RecoveryRestoreError("Unsafe application data directory")

    if (
        source.resolve() == data_directory.resolve()
        or source.resolve() in data_directory.resolve().parents
        or data_directory.resolve() in source.resolve().parents
    ):
        raise RecoveryRestoreError("Recovery paths overlap")

    database = source / "nexdeck.db"
    key = source / "secret.key"

    if not database.is_file() or not key.is_file():
        raise RecoveryRestoreError(
            "Recovery package lacks required application files"
        )

    # Validate every attachment before modifying live data.
    attachments = []

    for item in source.rglob("*"):
        if item.is_symlink():
            raise RecoveryRestoreError("Symlink in recovery package")

        if not item.is_file():
            continue

        relative = item.relative_to(source).as_posix()

        if relative in {
            "nexdeck.db",
            "secret.key",
            "nexdeck-backup.json",
        }:
            continue

        if not valid_attachment_path(relative):
            raise RecoveryRestoreError(
                f"Unexpected recovery file: {relative}"
            )

        attachments.append(relative)

    # Reject unsafe live paths before changing any application data.
    for name in ("nexdeck.db", "secret.key"):
        destination = data_directory / name

        if destination.is_symlink():
            raise RecoveryRestoreError(
                f"Unsafe live application file: {name}"
            )

        if destination.exists() and not destination.is_file():
            raise RecoveryRestoreError(
                f"Invalid live application file: {name}"
            )

    for directory in ("avatars", "uploads", "brand"):
        target = data_directory / directory

        if target.is_symlink():
            raise RecoveryRestoreError(
                f"Unsafe attachment directory: {directory}"
            )

        if target.exists() and not target.is_dir():
            raise RecoveryRestoreError(
                f"Invalid attachment directory: {directory}"
            )

        if target.is_dir():
            for item in target.rglob("*"):
                if item.is_symlink():
                    raise RecoveryRestoreError(
                        "Symlink in live attachment directory"
                    )

                if not item.is_file() and not item.is_dir():
                    raise RecoveryRestoreError(
                        "Unsupported live attachment entry"
                    )

    for relative in attachments:
        destination = data_directory / relative

        if destination.is_symlink():
            raise RecoveryRestoreError(
                f"Unsafe attachment destination: {relative}"
            )

        if destination.exists() and not destination.is_file():
            raise RecoveryRestoreError(
                f"Invalid attachment destination: {relative}"
            )

    # The database is replaced only after all preflight checks pass.
    # WAL/SHM files belong to the stopped application's previous state.
    for suffix in ("-wal", "-shm"):
        sidecar = data_directory / f"nexdeck.db{suffix}"
        if sidecar.exists():
            if sidecar.is_symlink() or not sidecar.is_file():
                raise RecoveryRestoreError(
                    f"Unsafe SQLite sidecar: {sidecar.name}"
                )

    # Reconcile only the approved attachment directories.
    # Logs, cache, backups and other application files are untouched.
    expected_attachments = set(attachments)

    for directory in ("avatars", "uploads", "brand"):
        target = data_directory / directory

        if not target.is_dir():
            continue

        for item in sorted(
            target.rglob("*"),
            key=lambda entry: len(entry.parts),
            reverse=True,
        ):
            if item.is_file():
                relative = item.relative_to(
                    data_directory
                ).as_posix()

                if relative not in expected_attachments:
                    item.unlink()

            elif item.is_dir():
                if not any(item.iterdir()):
                    item.rmdir()

    for relative in attachments:
        destination = data_directory / relative
        destination.parent.mkdir(
            parents=True,
            exist_ok=True,
            mode=0o700,
        )
        shutil.copy2(source / relative, destination)

    # Restore the database and key after attachment reconciliation.
    shutil.copy2(database, data_directory / "nexdeck.db")
    shutil.copy2(key, data_directory / "secret.key")
    os.chmod(data_directory / "secret.key", 0o600)

    for suffix in ("-wal", "-shm"):
        (data_directory / f"nexdeck.db{suffix}").unlink(
            missing_ok=True
        )

    # Verify the restored database.
    with sqlite3.connect(
        f"{(data_directory / 'nexdeck.db').as_uri()}?mode=ro",
        uri=True,
    ) as connection:
        result = connection.execute(
            "PRAGMA integrity_check"
        ).fetchone()

    if result is None or result[0] != "ok":
        raise RecoveryRestoreError(
            "Restored database failed integrity check"
        )
