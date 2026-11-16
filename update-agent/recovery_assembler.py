"""Offline NexDeck recovery-package assembly.

Not connected to Docker, running deployments or update execution.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import stat
import tempfile
from pathlib import Path
from recovery_paths import valid_attachment_path

from recovery_point import create_recovery_point
from secure_directory import open_directory_chain
from recovery_preflight import assess_recovery_material
from snapshot import SnapshotError, copy_regular_file


class RecoveryAssemblyError(SnapshotError):
    """Recovery material cannot be safely assembled."""


def assemble_recovery_package(
    data_directory: Path,
    backup_filename: str,
    recovery_root: Path,
    recovery_id: str,
    *,
    environment_key_configured: bool = False,
) -> Path:
    """Assemble an existing snapshot into a private recovery point."""

    data_directory = Path(data_directory)
    recovery_root = Path(recovery_root)

    assessment = assess_recovery_material(
        data_directory,
        backup_filename,
        environment_key_configured=environment_key_configured,
    )

    if not assessment.ready:
        raise RecoveryAssemblyError(
            f"Recovery preflight failed: {assessment.reason}"
        )

    backup = data_directory / "backups" / backup_filename
    profile_path = backup.with_suffix(".json")
    extras_root = backup.with_name(backup.stem + "-files")
    key_path = data_directory / "secret.key"

    try:
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise RecoveryAssemblyError("Invalid backup profile") from exc

    if (
        profile.get("kind") != "manual"
        or profile.get("note") != "Pre-update restore point"
    ):
        raise RecoveryAssemblyError("Not a pre-update manual backup")

    contains = profile["contains"]

    if (
        len(contains) != len(set(contains))
        or "secret.key" in contains
        or any(not isinstance(item, str) for item in contains)
    ):
        raise RecoveryAssemblyError("Invalid profile contents")

    expected_extras = set(contains) - {"nexdeck.db"}

    if not all(
        valid_attachment_path(entry)
        for entry in expected_extras
    ):
        raise RecoveryAssemblyError(
            "Invalid recovery attachment path"
        )

    # Reject undeclared attachments rather than silently creating
    # a recovery package that disagrees with its own profile.
    if extras_root.exists():
        if extras_root.is_symlink() or not extras_root.is_dir():
            raise RecoveryAssemblyError("Unsafe extras directory")

        actual_extras = set()

        for path in extras_root.rglob("*"):
            if path.is_symlink():
                raise RecoveryAssemblyError("Symlink in extras")

            if path.is_file():
                actual_extras.add(
                    path.relative_to(extras_root).as_posix()
                )
            elif not path.is_dir():
                raise RecoveryAssemblyError("Unsupported extras entry")

        if actual_extras != expected_extras:
            raise RecoveryAssemblyError(
                "Snapshot attachments disagree with profile"
            )

    elif expected_extras:
        raise RecoveryAssemblyError("Missing snapshot attachments")

    # Check the already-completed NexDeck snapshot.
    try:
        with sqlite3.connect(
            f"{backup.resolve().as_uri()}?mode=ro",
            uri=True,
        ) as connection:
            result = connection.execute(
                "PRAGMA integrity_check"
            ).fetchone()
            if result is None or result[0] != "ok":
                raise RecoveryAssemblyError(
                    "SQLite integrity check failed"
                )
    except sqlite3.Error as exc:
        raise RecoveryAssemblyError(
            "Cannot validate SQLite snapshot"
        ) from exc

    # The recovery root is separate from the application data.
    # The existing publisher independently rejects overlap.
    if not recovery_root.is_dir():
        raise RecoveryAssemblyError("Recovery root does not exist")

    with tempfile.TemporaryDirectory(
        prefix=".nexdeck-assembly-",
        dir=recovery_root.parent,
    ) as temporary:
        staging = Path(temporary)
        staging.chmod(0o700)

        def copy_one(source: Path, destination: Path) -> None:
            destination.parent.mkdir(
                parents=True,
                exist_ok=True,
                mode=0o700,
            )

            with open_directory_chain(
                source.parent.absolute()
            ) as source_fd:
                with open_directory_chain(
                    destination.parent.absolute()
                ) as destination_fd:
                    copy_regular_file(
                        source_fd,
                        source.name,
                        destination_fd,
                        destination.name,
                    )

        copy_one(backup, staging / "nexdeck.db")
        copy_one(profile_path, staging / "nexdeck-backup.json")
        copy_one(key_path, staging / "secret.key")

        for entry in sorted(expected_extras):
            copy_one(
                extras_root / entry,
                staging / entry,
            )

        # Validate the exact copies that will be published.
        staged_profile = staging / "nexdeck-backup.json"

        try:
            copied_profile = json.loads(
                staged_profile.read_text(encoding="utf-8")
            )
        except (OSError, UnicodeError, ValueError) as exc:
            raise RecoveryAssemblyError(
                "Copied backup profile is invalid"
            ) from exc

        if copied_profile != profile:
            raise RecoveryAssemblyError(
                "Backup profile changed during assembly"
            )

        staged_database = staging / "nexdeck.db"

        try:
            with sqlite3.connect(
                f"{staged_database.as_uri()}?mode=ro",
                uri=True,
            ) as connection:
                result = connection.execute(
                    "PRAGMA integrity_check"
                ).fetchone()

                if result is None or result[0] != "ok":
                    raise RecoveryAssemblyError(
                        "Copied SQLite database failed integrity check"
                    )
        except sqlite3.Error as exc:
            raise RecoveryAssemblyError(
                "Cannot validate copied SQLite database"
            ) from exc

        return create_recovery_point(
            staging,
            recovery_root,
            recovery_id,
        )
