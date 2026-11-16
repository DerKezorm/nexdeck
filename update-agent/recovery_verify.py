"""Read-only verification of published NexDeck recovery packages.

Offline only. No Docker, restore or update operations.
"""

from __future__ import annotations

import json
import re
import stat
from pathlib import Path
from recovery_paths import valid_attachment_path

from recovery import inventory_directory, sha256_file


class RecoveryVerificationError(ValueError):
    """A published recovery package failed verification."""


def verify_recovery_package(package: Path) -> bool:
    """Verify manifest, file inventory and recorded hashes."""

    package = Path(package)

    if package.is_symlink() or not package.is_dir():
        raise RecoveryVerificationError(
            "Recovery package is not a real directory"
        )

    manifest_path = package / "manifest.json"
    data = package / "data"

    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise RecoveryVerificationError(
            "Missing or unsafe recovery manifest"
        )

    if data.is_symlink() or not data.is_dir():
        raise RecoveryVerificationError(
            "Missing or unsafe recovery data directory"
        )

    try:
        manifest = json.loads(
            manifest_path.read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, ValueError) as exc:
        raise RecoveryVerificationError(
            "Invalid recovery manifest"
        ) from exc

    if not isinstance(manifest, dict):
        raise RecoveryVerificationError(
            "Recovery manifest must be an object"
        )

    if manifest.get("format_version") != 1:
        raise RecoveryVerificationError(
            "Unsupported recovery manifest version"
        )

    recovery_id = manifest.get("recovery_id")

    if (
        not isinstance(recovery_id, str)
        or not re.fullmatch(r"[A-Za-z0-9_-]+", recovery_id)
        or recovery_id != package.name
    ):
        raise RecoveryVerificationError(
            "Recovery identifier mismatch"
        )

    entries = manifest.get("files")
    directories = manifest.get("directories")

    if not isinstance(entries, list):
        raise RecoveryVerificationError(
            "Invalid manifest file list"
        )

    if not isinstance(directories, list):
        raise RecoveryVerificationError(
            "Invalid manifest directory list"
        )

    # Reject duplicate, malformed or unsafe directory declarations.
    if (
        not all(isinstance(x, str) for x in directories)
        or len(directories) != len(set(directories))
    ):
        raise RecoveryVerificationError(
            "Invalid or duplicate manifest directories"
        )

    for directory in directories:
        if (
            not directory
            or directory.startswith("/")
            or "\\" in directory
            or any(
                part in ("", ".", "..")
                for part in directory.split("/")
            )
        ):
            raise RecoveryVerificationError(
                "Unsafe manifest directory"
            )

    expected = {}

    for entry in entries:
        if not isinstance(entry, dict):
            raise RecoveryVerificationError(
                "Invalid manifest file entry"
            )

        name = entry.get("path")
        size = entry.get("size")
        digest = entry.get("sha256")

        if (
            not isinstance(name, str)
            or not name
            or name.startswith("/")
            or "\\" in name
            or any(
                part in ("", ".", "..")
                for part in name.split("/")
            )
            or type(size) is not int
            or size < 0
            or not isinstance(digest, str)
            or not re.fullmatch(
                r"[0-9a-f]{64}", digest
            )
        ):
            raise RecoveryVerificationError(
                "Unsafe or invalid manifest entry"
            )

        if name in expected:
            raise RecoveryVerificationError(
                "Duplicate manifest file"
            )

        expected[name] = (size, digest)

    actual = {}

    try:
        records = inventory_directory(data)
    except (OSError, ValueError) as exc:
        raise RecoveryVerificationError(
            "Unsafe recovery data inventory"
        ) from exc

    for record in records:
        actual[record.path] = (
            record.size,
            record.sha256,
        )

    if actual != expected:
        raise RecoveryVerificationError(
            "Recovery files differ from manifest"
        )

    actual_directories = []

    for path in data.rglob("*"):
        if path.is_symlink():
            raise RecoveryVerificationError(
                "Symbolic link in recovery package"
            )

        if path.is_dir():
            actual_directories.append(
                path.relative_to(data).as_posix()
            )

    if sorted(actual_directories) != sorted(directories):
        raise RecoveryVerificationError(
            "Recovery directories differ from manifest"
        )

    package_entries = {
        item.name for item in package.iterdir()
    }

    if package_entries != {"manifest.json", "data"}:
        raise RecoveryVerificationError(
            "Unexpected recovery package entries"
        )

    return True


def verify_nexdeck_recovery_package(package: Path) -> bool:
    """Verify a published package contains usable NexDeck material.

    This is offline structural and integrity verification only.
    It does not perform a restore or prove encryption-key correctness.
    """

    import sqlite3

    verify_recovery_package(package)

    data = Path(package) / "data"

    required = {
        "nexdeck.db",
        "nexdeck-backup.json",
        "secret.key",
    }

    records = inventory_directory(data)
    actual = {record.path for record in records}

    if not required.issubset(actual):
        raise RecoveryVerificationError(
            "Required NexDeck recovery files are missing"
        )

    key = data / "secret.key"

    if key.is_symlink():
        raise RecoveryVerificationError(
            "Recovery encryption key is a symbolic link"
        )

    key_info = key.stat()

    if (
        not stat.S_ISREG(key_info.st_mode)
        or key_info.st_size == 0
        or key_info.st_mode & 0o077
    ):
        raise RecoveryVerificationError(
            "Recovery encryption key is missing or insecure"
        )

    profile_path = data / "nexdeck-backup.json"

    try:
        profile = json.loads(
            profile_path.read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, ValueError) as exc:
        raise RecoveryVerificationError(
            "Invalid NexDeck backup profile"
        ) from exc

    if not isinstance(profile, dict):
        raise RecoveryVerificationError(
            "NexDeck backup profile must be an object"
        )

    if (
        profile.get("kind") != "manual"
        or profile.get("note") != "Pre-update restore point"
        or not isinstance(profile.get("version"), str)
        or not profile["version"]
        or type(profile.get("schema")) is not int
        or profile["schema"] < 0
    ):
        raise RecoveryVerificationError(
            "Invalid pre-update backup metadata"
        )

    contains = profile.get("contains")

    if (
        not isinstance(contains, list)
        or not all(isinstance(x, str) for x in contains)
        or len(contains) != len(set(contains))
        or "nexdeck.db" not in contains
        or "secret.key" in contains
    ):
        raise RecoveryVerificationError(
            "Invalid backup contents declaration"
        )

    declared_extras = set(contains) - {"nexdeck.db"}

    if not all(
        valid_attachment_path(entry)
        for entry in declared_extras
    ):
        raise RecoveryVerificationError(
            "Unsafe backup attachment path"
        )

    actual_extras = actual - required

    if actual_extras != declared_extras:
        raise RecoveryVerificationError(
            "Backup attachments differ from profile"
        )

    database = data / "nexdeck.db"

    try:
        with sqlite3.connect(
            f"{database.resolve().as_uri()}?mode=ro",
            uri=True,
        ) as connection:
            result = connection.execute(
                "PRAGMA integrity_check"
            ).fetchone()

            if result is None or result[0] != "ok":
                raise RecoveryVerificationError(
                    "Recovery SQLite database failed integrity check"
                )
    except sqlite3.Error as exc:
        raise RecoveryVerificationError(
            "Cannot validate recovery SQLite database"
        ) from exc

    return True
