"""Read-only assessment of NexDeck recovery material.

No Docker operations, secret disclosure or filesystem mutations.
"""

from __future__ import annotations

import json
import stat
from dataclasses import dataclass
from pathlib import Path
from recovery_paths import valid_attachment_path


@dataclass(frozen=True)
class RecoveryAssessment:
    ready: bool
    reason: str
    key_source: str
    files_checked: int


def assess_recovery_material(
    data_directory: Path,
    backup_filename: str,
    *,
    environment_key_configured: bool = False,
) -> RecoveryAssessment:
    """Check whether snapshot recovery material is available.

    This is a presence assessment, not a complete recovery guarantee.
    """

    if (
        not isinstance(backup_filename, str)
        or not backup_filename.startswith("nexdeck-manual-")
        or not backup_filename.endswith(".db")
        or Path(backup_filename).name != backup_filename
    ):
        return RecoveryAssessment(False, "invalid_filename", "unknown", 0)

    backup = data_directory / "backups" / backup_filename
    profile_path = backup.with_suffix(".json")

    if not backup.is_file() or backup.is_symlink():
        return RecoveryAssessment(False, "missing_database", "unknown", 0)

    if not profile_path.is_file() or profile_path.is_symlink():
        return RecoveryAssessment(False, "missing_profile", "unknown", 0)

    try:
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return RecoveryAssessment(False, "invalid_profile", "unknown", 0)

    if not isinstance(profile, dict):
        return RecoveryAssessment(False, "invalid_profile", "unknown", 0)

    contains = profile.get("contains")

    if not isinstance(contains, list) or "nexdeck.db" not in contains:
        return RecoveryAssessment(False, "invalid_profile", "unknown", 0)

    extras_root = backup.with_name(backup.stem + "-files")
    checked = 0

    for entry in contains:
        if entry == "nexdeck.db":
            continue

        if not isinstance(entry, str):
            return RecoveryAssessment(False, "invalid_profile", "unknown", checked)

        if not valid_attachment_path(entry):
            return RecoveryAssessment(
                False, "invalid_extra_path", "unknown", checked
            )

        parts = entry.split("/")

        candidate = extras_root / entry

        # Reject symlinks in the snapshot directory hierarchy.
        # lstat(candidate) alone checks only the final component.
        for directory in (
            data_directory,
            data_directory / "backups",
            extras_root,
            extras_root / parts[0],
        ):
            try:
                directory_info = directory.lstat()
            except OSError:
                return RecoveryAssessment(
                    False, "missing_extra_directory", "unknown", checked
                )

            if not stat.S_ISDIR(directory_info.st_mode):
                return RecoveryAssessment(
                    False, "unsafe_extra_directory", "unknown", checked
                )

        try:
            info = candidate.lstat()
        except OSError:
            return RecoveryAssessment(False, "missing_extra", "unknown", checked)

        if not stat.S_ISREG(info.st_mode):
            return RecoveryAssessment(False, "unsafe_extra", "unknown", checked)

        checked += 1

    if environment_key_configured:
        return RecoveryAssessment(
            False, "external_key_requires_recovery_plan", "environment", checked
        )

    key_file = data_directory / "secret.key"

    try:
        info = key_file.lstat()
    except OSError:
        return RecoveryAssessment(False, "missing_key", "file", checked)

    if not stat.S_ISREG(info.st_mode) or info.st_size == 0:
        return RecoveryAssessment(False, "invalid_key", "file", checked)

    if info.st_mode & 0o077:
        return RecoveryAssessment(False, "insecure_key_permissions", "file", checked)

    return RecoveryAssessment(True, "material_present", "file", checked)
