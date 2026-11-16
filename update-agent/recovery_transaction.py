"""Prepare transactional NexDeck data restoration.

No Docker operations or live data mutation are performed here.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from recovery_verify import verify_nexdeck_recovery_package
from recovery_paths import valid_attachment_path


class RecoveryTransactionError(RuntimeError):
    """A recovery transaction cannot be prepared safely."""


@dataclass(frozen=True)
class PreparedRecovery:
    staging_directory: Path
    original_directory: Path
    recovery_package: Path


def prepare_recovery_transaction(
    package: Path,
    data_directory: Path,
    transaction_root: Path,
) -> PreparedRecovery:
    """Prepare verified recovery data without modifying live files."""

    package = Path(package)
    data_directory = Path(data_directory)
    transaction_root = Path(transaction_root)

    if not verify_nexdeck_recovery_package(package):
        raise RecoveryTransactionError(
            "Recovery package verification failed"
        )

    if not data_directory.is_dir() or data_directory.is_symlink():
        raise RecoveryTransactionError(
            "Unsafe application data directory"
        )

    if not transaction_root.is_dir() or transaction_root.is_symlink():
        raise RecoveryTransactionError(
            "Transaction storage is not configured"
        )

    source = package / "data"

    resolved = [
        source.resolve(),
        data_directory.resolve(),
        transaction_root.resolve(),
    ]

    for index, first in enumerate(resolved):
        for second in resolved[index + 1:]:
            if (
                first == second
                or first in second.parents
                or second in first.parents
            ):
                raise RecoveryTransactionError(
                    "Recovery transaction paths overlap"
                )

    staging = Path(
        tempfile.mkdtemp(
            prefix=".nexdeck-restore-",
            dir=transaction_root,
        )
    )
    staging.chmod(0o700)

    try:
        for name in ("nexdeck.db", "secret.key"):
            shutil.copy2(source / name, staging / name)

        (staging / "secret.key").chmod(0o600)

        for item in source.rglob("*"):
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
                raise RecoveryTransactionError(
                    f"Unexpected recovery file: {relative}"
                )

            destination = staging / relative
            destination.parent.mkdir(
                parents=True,
                exist_ok=True,
                mode=0o700,
            )
            shutil.copy2(item, destination)

        return PreparedRecovery(
            staging_directory=staging,
            original_directory=data_directory,
            recovery_package=package,
        )

    except Exception:
        shutil.rmtree(staging)
        raise


def build_replacement_directory(
    prepared: PreparedRecovery,
    destination: Path,
) -> Path:
    """Build a complete replacement tree without modifying live data.

    The caller must ensure the application is stopped and that no
    other process is writing to the original data directory.
    """
    import os
    import stat

    original = prepared.original_directory
    staging = prepared.staging_directory
    destination = Path(destination)

    if not original.is_dir() or original.is_symlink():
        raise RecoveryTransactionError(
            "Unsafe original data directory"
        )

    if not staging.is_dir() or staging.is_symlink():
        raise RecoveryTransactionError(
            "Unsafe staged recovery directory"
        )

    if destination.exists() or destination.is_symlink():
        raise RecoveryTransactionError(
            "Replacement destination already exists"
        )

    resolved = [
        original.resolve(),
        staging.resolve(),
        destination.resolve(),
    ]

    for index, first in enumerate(resolved):
        for second in resolved[index + 1:]:
            if (
                first == second
                or first in second.parents
                or second in first.parents
            ):
                raise RecoveryTransactionError(
                    "Replacement paths overlap"
                )

    for tree in (original, staging):
        for item in tree.rglob("*"):
            if item.is_symlink():
                raise RecoveryTransactionError(
                    "Symlink found in application data"
                )

            mode = item.stat().st_mode
            if not (
                stat.S_ISREG(mode)
                or stat.S_ISDIR(mode)
            ):
                raise RecoveryTransactionError(
                    "Unsupported application data entry"
                )

    # Preserve the original tree in a separate destination.
    shutil.copytree(
        original,
        destination,
        symlinks=False,
    )

    try:
        # Remove data that must exactly match the recovery point.
        for name in (
            "nexdeck.db",
            "nexdeck.db-wal",
            "nexdeck.db-shm",
            "secret.key",
        ):
            (destination / name).unlink(missing_ok=True)

        for name in ("avatars", "uploads", "brand"):
            target = destination / name

            if target.exists():
                shutil.rmtree(target)

        # Apply the recovered database and encryption key.
        for name in ("nexdeck.db", "secret.key"):
            shutil.copy2(
                staging / name,
                destination / name,
            )

        os.chmod(destination / "secret.key", 0o600)

        # Apply exactly the recovered attachments.
        for name in ("avatars", "uploads", "brand"):
            source = staging / name

            if source.is_dir():
                shutil.copytree(
                    source,
                    destination / name,
                )

        return destination

    except Exception:
        shutil.rmtree(destination)
        raise


def commit_recovery_transaction(
    prepared: PreparedRecovery,
    replacement: Path,
    retained_original: Path,
    *,
    application_stopped: bool = False,
) -> Path:
    """Switch to prepared recovery data, retaining the original tree.

    The application must be stopped, with no other writers.
    The caller must retain the original directory until recovery
    and application health have been verified.
    """
    import os

    if not application_stopped:
        raise RecoveryTransactionError(
            "Application must be stopped before recovery commit"
        )

    original = prepared.original_directory
    replacement = Path(replacement)
    retained_original = Path(retained_original)

    if not original.is_dir() or original.is_symlink():
        raise RecoveryTransactionError(
            "Unsafe original application directory"
        )

    if not replacement.is_dir() or replacement.is_symlink():
        raise RecoveryTransactionError(
            "Unsafe replacement directory"
        )

    if retained_original.exists() or retained_original.is_symlink():
        raise RecoveryTransactionError(
            "Retained original destination already exists"
        )

    paths = [
        original.resolve(),
        replacement.resolve(),
        retained_original.resolve(),
    ]

    for index, first in enumerate(paths):
        for second in paths[index + 1:]:
            if (
                first == second
                or first in second.parents
                or second in first.parents
            ):
                raise RecoveryTransactionError(
                    "Recovery commit paths overlap"
                )

    if not (
        original.parent.resolve()
        == replacement.parent.resolve()
        == retained_original.parent.resolve()
    ):
        raise RecoveryTransactionError(
            "Recovery commit requires sibling directories"
        )

    devices = {
        original.stat().st_dev,
        replacement.stat().st_dev,
        original.parent.stat().st_dev,
    }

    if len(devices) != 1:
        raise RecoveryTransactionError(
            "Recovery commit requires one filesystem"
        )

    os.rename(original, retained_original)

    try:
        os.rename(replacement, original)
    except Exception as exc:
        try:
            os.rename(retained_original, original)
        except Exception as restore_exc:
            raise RecoveryTransactionError(
                "Recovery commit failed and original directory "
                f"could not be restored: {restore_exc}"
            ) from exc

        raise RecoveryTransactionError(
            "Recovery commit failed; original directory restored"
        ) from exc

    return retained_original


def recover_interrupted_commit(
    original: Path,
    replacement: Path,
    retained_original: Path,
) -> str:
    """Recover a directory switch interrupted before completion.

    Must be invoked with the application stopped and no other writers.
    Never replaces an existing application data directory.
    """
    import os

    original = Path(original)
    replacement = Path(replacement)
    retained_original = Path(retained_original)

    if original.is_symlink() or retained_original.is_symlink():
        raise RecoveryTransactionError(
            "Unsafe recovery directory symlink"
        )

    if original.exists():
        if retained_original.exists():
            return "commit_present_original_retained"
        return "original_present"

    if not retained_original.is_dir():
        raise RecoveryTransactionError(
            "Application data missing and no retained original available"
        )

    if (
        original.parent.resolve()
        != retained_original.parent.resolve()
    ):
        raise RecoveryTransactionError(
            "Recovery directories must share a parent"
        )

    os.rename(retained_original, original)

    return "original_restored"
