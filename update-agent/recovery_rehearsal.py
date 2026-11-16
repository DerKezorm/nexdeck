"""Offline NexDeck recovery rehearsal using disposable destinations.

Never operates on a running deployment or invokes Docker.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import sqlite3
import shutil
from pathlib import Path

from recovery import inventory_directory
from recovery_point import publish_exclusively
from recovery_verify import verify_nexdeck_recovery_package
from snapshot import SnapshotError, copy_directory_tree


class RecoveryRehearsalError(SnapshotError):
    """A disposable recovery rehearsal failed."""


def rehearse_recovery(
    package: Path,
    destination: Path,
) -> Path:
    """Copy a verified recovery package into a new destination.

    The destination must not already exist.
    This function does not start NexDeck or run migrations.
    """

    package = Path(package)
    destination = Path(destination)

    # Reject existing destinations rather than overwriting data.
    if destination.exists() or destination.is_symlink():
        raise RecoveryRehearsalError(
            "Recovery rehearsal destination already exists"
        )

    # Verify before creating any destination material.
    # Capture manifest bytes and bind them to verification.
    # Reject a manifest replaced during the verification window.
    manifest_path = package / "manifest.json"
    manifest_bytes = manifest_path.read_bytes()
    manifest_digest = hashlib.sha256(
        manifest_bytes
    ).digest()

    if not verify_nexdeck_recovery_package(package):
        raise RecoveryRehearsalError(
            "Recovery package verification failed"
        )

    if hashlib.sha256(
        manifest_path.read_bytes()
    ).digest() != manifest_digest:
        raise RecoveryRehearsalError(
            "Recovery manifest changed during verification"
        )

    manifest = json.loads(manifest_bytes)

    expected_files = {
        record["path"]: (
            record["size"],
            record["sha256"],
        )
        for record in manifest["files"]
    }

    expected_directories = set(
        manifest["directories"]
    )

    source = package / "data"

    # Prevent copying into the package or its own hierarchy.
    source_resolved = source.resolve(strict=True)
    destination_resolved = destination.resolve(strict=False)

    if (
        destination_resolved == source_resolved
        or source_resolved in destination_resolved.parents
        or destination_resolved in source_resolved.parents
    ):
        raise RecoveryRehearsalError(
            "Recovery source and destination overlap"
        )

    # Build privately, then publish without replacing anything.
    # Never delete the requested destination on failure.
    with tempfile.TemporaryDirectory(
        prefix=".nexdeck-rehearsal-",
        dir=destination.parent,
    ) as temporary:
        staging = Path(temporary) / "data"
        staging.mkdir(mode=0o700)

        copy_directory_tree(source, staging)

        restored_records = inventory_directory(staging)

        restored = {
            record.path: (record.size, record.sha256)
            for record in restored_records
        }

        if restored != expected_files:
            raise RecoveryRehearsalError(
                "Restored files differ from verified manifest"
            )

        restored_directories = {
            path.relative_to(staging).as_posix()
            for path in staging.rglob("*")
            if path.is_dir()
        }

        if restored_directories != expected_directories:
            raise RecoveryRehearsalError(
                "Restored directories differ from verified manifest"
            )

        database = staging / "nexdeck.db"

        with sqlite3.connect(
            f"{database.as_uri()}?mode=ro",
            uri=True,
        ) as connection:
            result = connection.execute(
                "PRAGMA integrity_check"
            ).fetchone()

            if result is None or result[0] != "ok":
                raise RecoveryRehearsalError(
                    "Restored SQLite database failed integrity check"
                )

        key = staging / "secret.key"

        if key.stat().st_mode & 0o077:
            raise RecoveryRehearsalError(
                "Restored encryption key has insecure permissions"
            )

        # Recheck the complete staged inventory immediately before
        # exclusive publication. A changed file must never be
        # accepted as a valid recovery rehearsal.
        final_records = inventory_directory(staging)

        final_files = {
            record.path: (record.size, record.sha256)
            for record in final_records
        }

        if final_files != expected_files:
            raise RecoveryRehearsalError(
                "Staging changed before publication"
            )

        # Linux RENAME_NOREPLACE: never overwrite an existing
        # destination, including one created concurrently.
        publish_exclusively(staging, destination)

        # Publication moves staging to destination. Verify the
        # actual published files before accepting the rehearsal.
        try:
            published_records = inventory_directory(destination)

            published_files = {
                record.path: (record.size, record.sha256)
                for record in published_records
            }

            published_directories = {
                item.relative_to(destination).as_posix()
                for item in destination.rglob("*")
                if item.is_dir()
            }

            if (
                published_files != expected_files
                or published_directories != expected_directories
            ):
                raise RecoveryRehearsalError(
                    "Published recovery differs from verified manifest"
                )

        except Exception:
            # The exclusive publication succeeded, so this is
            # our newly created disposable rehearsal directory.
            shutil.rmtree(destination)
            raise

    return destination
