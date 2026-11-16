"""Restricted production Compose updater.

This module performs Docker operations only when explicitly invoked
by the authenticated host agent.
"""

from __future__ import annotations

import json
import os
import re
import time
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path

from latest_release import resolve_latest_release
from update_target import select_update_target
from image_override import build_image_override
from managed_override import write_managed_override

from deployment_control import (
    build_compose_update_commands,
    build_inspect_command,
    capture_container_identity,
    verify_enrolled_deployment,
)


class UpdateError(RuntimeError):
    """An enrolled deployment could not be updated safely."""


@dataclass
class UpdateState:
    stage: str = "idle"
    error: str | None = None


class ComposeRunner:
    def __init__(self, deployment):
        self.deployment = deployment
        self.state = UpdateState()
        self.lock = threading.Lock()

    def _resolve_update_target(self):
        """Select the latest stable image for this deployment."""
        release = resolve_latest_release()

        return select_update_target(
            release,
            deployment_id=self.deployment.deployment_id,
            test_mode=(
                self.deployment.deployment_id
                == "nexdeck-updater-realtest"
            ),
        )

    def _prepare_update_image(self, target) -> str:
        """Prepare an approved image and return its immutable local ID."""
        reference = target.image_reference

        if self.deployment.deployment_id == "nexdeck-updater-realtest":
            if not re.fullmatch(
                r"nexdeck-updater-realtest:[0-9]+\.[0-9]+\.[0-9]+",
                reference,
            ):
                raise UpdateError("Unapproved isolated test image")
        else:
            if not re.fullmatch(
                r"ghcr\.io/derkezorm/nexdeck:[0-9]+\.[0-9]+\.[0-9]+",
                reference,
            ):
                raise UpdateError("Unapproved official image")

            self._run(
                ("docker", "pull", reference),
                timeout=900,
            )

        raw = self._run(
            ("docker", "image", "inspect", reference),
            timeout=30,
        )

        try:
            entries = json.loads(raw)
            image_id = entries[0]["Id"]

            if (
                len(entries) != 1
                or not isinstance(image_id, str)
                or not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id)
            ):
                raise ValueError("Invalid image identity")

            return image_id

        except (ValueError, TypeError, KeyError, IndexError) as exc:
            raise UpdateError(
                "Cannot verify selected update image"
            ) from exc

    def _write_update_override(self, image_id: str) -> Path:
        """Persist an approved immutable image override."""
        override = build_image_override(
            self.deployment.project_directory,
            image_id,
        )

        expected = self._managed_image_override()

        if override.path != expected:
            raise UpdateError("Managed override path mismatch")

        return write_managed_override(override)

    def _recreate_with_managed_image(self) -> None:
        """Recreate only the enrolled NexDeck service."""
        commands = build_compose_update_commands(
            self.deployment,
            image_override=self._managed_image_override(),
        )

        self._run(commands.recreate, timeout=300)

    def _verify_installed_image(self, image_id: str) -> None:
        """Verify the replacement uses the selected image."""
        inspection = self._inspect()

        if inspection.get("Image") != image_id:
            raise UpdateError(
                "Installed container image does not match target"
            )

        verify_enrolled_deployment(
            inspection,
            self.deployment,
            capture_container_identity(inspection),
            image_override=str(self._managed_image_override()),
        )

    def _managed_image_override(self) -> Path:
        """Return the fixed managed image override location."""
        return (
            self.deployment.project_directory
            / ".nexdeck-updater"
            / "image.override.yaml"
        )

    def _run(self, argv: tuple[str, ...], timeout: int) -> str:
        try:
            result = subprocess.run(
                argv,
                cwd=self.deployment.project_directory,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=True,
            )
            return result.stdout
        except (subprocess.SubprocessError, OSError) as exc:
            raise UpdateError(
                f"Command failed: {argv[0]} {argv[1]}"
            ) from exc

    def _inspect(self) -> dict:
        command = build_inspect_command(
            self.deployment.container_name
        )
        raw = self._run(command.command, timeout=30)
        try:
            entries = json.loads(raw)
            if not isinstance(entries, list) or len(entries) != 1:
                raise ValueError("Unexpected Docker inspection")
            return entries[0]
        except (ValueError, TypeError) as exc:
            raise UpdateError("Invalid Docker inspection") from exc

    def _wait_healthy(
        self,
        timeout: int = 180,
        recovery_override: str | None = None,
        image_override: str | None = None,
    ) -> dict:
        """Wait for the enrolled replacement container to become healthy."""

        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            inspection = self._inspect()

            verify_enrolled_deployment(
                inspection,
                self.deployment,
                capture_container_identity(inspection),
                recovery_override=recovery_override,
                image_override=image_override,
            )

            state = inspection.get("State", {})

            if not isinstance(state, dict):
                raise UpdateError("Invalid container state")

            if state.get("Running") is not True:
                raise UpdateError("Updated container is not running")

            health = state.get("Health", {})

            if not isinstance(health, dict):
                raise UpdateError("Updated container has no health status")

            status = health.get("Status")

            if status == "healthy":
                return inspection

            if status == "unhealthy":
                raise UpdateError("Updated container is unhealthy")

            time.sleep(3)

        raise UpdateError("Updated container did not become healthy")

    def verify_backup(self, filename: str) -> None:
        """Validate a fresh NexDeck SQLite restore point."""

        import sqlite3
        import stat

        if (
            not isinstance(filename, str)
            or not filename.startswith("nexdeck-manual-")
            or not filename.endswith(".db")
            or Path(filename).name != filename
            or filename in {".", ".."}
        ):
            raise UpdateError("Invalid backup filename")

        backup_directory = self.deployment.data_directory / "backups"
        backup_path = backup_directory / filename

        try:
            info = backup_path.lstat()
        except OSError as exc:
            raise UpdateError("Pre-update backup does not exist") from exc

        if not stat.S_ISREG(info.st_mode):
            raise UpdateError("Pre-update backup is not a regular file")

        age = time.time() - info.st_mtime

        if age < -60 or age > 600:
            raise UpdateError("Pre-update backup is not recent")

        if info.st_size < 4096:
            raise UpdateError("Pre-update backup is unexpectedly small")

        try:
            connection = sqlite3.connect(
                f"file:{backup_path}?mode=ro",
                uri=True,
                timeout=5,
            )
            try:
                result = connection.execute(
                    "PRAGMA integrity_check"
                ).fetchone()
            finally:
                connection.close()
        except sqlite3.Error as exc:
            raise UpdateError("Cannot verify SQLite backup") from exc

        if result is None or result[0] != "ok":
            raise UpdateError("SQLite backup integrity check failed")

        # The backup service writes a JSON profile alongside each snapshot.
        import json

        profile_path = backup_path.with_suffix(".json")

        try:
            profile_info = profile_path.lstat()
        except OSError as exc:
            raise UpdateError("Backup profile does not exist") from exc

        if not stat.S_ISREG(profile_info.st_mode):
            raise UpdateError("Backup profile is not a regular file")

        if profile_info.st_size < 10 or profile_info.st_size > 65536:
            raise UpdateError("Invalid backup profile size")

        try:
            profile = json.loads(
                profile_path.read_text(encoding="utf-8")
            )
        except (OSError, UnicodeError, ValueError) as exc:
            raise UpdateError("Cannot read backup profile") from exc

        if not isinstance(profile, dict):
            raise UpdateError("Invalid backup profile")

        if profile.get("kind") != "manual":
            raise UpdateError("Backup is not a manual restore point")

        if not isinstance(profile.get("version"), str):
            raise UpdateError("Backup version is missing")

        if (
            not isinstance(profile.get("schema"), int)
            or isinstance(profile.get("schema"), bool)
            or profile["schema"] < 0
        ):
            raise UpdateError("Invalid backup schema")

        contains = profile.get("contains")

        if not isinstance(contains, list) or "nexdeck.db" not in contains:
            raise UpdateError("Backup does not identify NexDeck database")

        if profile.get("note") != "Pre-update restore point":
            raise UpdateError("Backup is not a pre-update restore point")


    def _rollback(
        self,
        previous_image: str,
        *,
        recovery_package: Path | None = None,
    ) -> None:
        """Restore the enrolled deployment's image and application data."""
        from rollback_control import build_rollback_plan
        from recovery_files import write_recovery_override
        from recovery_transaction import (
            prepare_recovery_transaction,
            build_replacement_directory,
            commit_recovery_transaction,
        )

        if recovery_package is None:
            raise UpdateError(
                "Rollback requires a verified application recovery package"
            )

        project = self.deployment.project_directory
        data_directory = self.deployment.data_directory

        transaction_root = project / ".nexdeck-updater" / "transactions"

        if (
            not transaction_root.is_dir()
            or transaction_root.is_symlink()
        ):
            raise UpdateError(
                "Secure recovery transaction storage is not configured"
            )

        from recovery_transaction import recover_interrupted_commit

        replacement = data_directory.parent / (
            data_directory.name + ".nexdeck-restore-new"
        )
        retained = data_directory.parent / (
            data_directory.name + ".nexdeck-before-restore"
        )

        # Never continue a new rollback over unresolved recovery data.
        if retained.exists() or retained.is_symlink():
            raise UpdateError(
                "Previous recovery data is retained. "
                "Manual recovery review required before another update."
            )

        if replacement.exists() or replacement.is_symlink():
            raise UpdateError(
                "Previous recovery replacement exists. "
                "Manual recovery review required."
            )

        if not data_directory.is_dir() or data_directory.is_symlink():
            raise UpdateError(
                "Enrolled application data directory is missing or unsafe"
            )

        prepared = prepare_recovery_transaction(
            recovery_package,
            data_directory,
            transaction_root,
        )

        replacement = data_directory.parent / (
            data_directory.name + ".nexdeck-restore-new"
        )

        retained = data_directory.parent / (
            data_directory.name + ".nexdeck-before-restore"
        )

        override = (
            project
            / ".nexdeck-recovery"
            / "rollback.override.yaml"
        )

        image_override = self._managed_image_override()

        plan = build_rollback_plan(
            self.deployment,
            previous_image,
            override,
            image_override=(
                image_override
                if image_override.is_file()
                else None
            ),
        )

        created_override = write_recovery_override(
            project,
            plan.override_content,
        )

        if created_override != override:
            raise UpdateError(
                "Recovery override path mismatch"
            )

        # Stop only the container enrolled for this deployment.
        self._run(
            ["docker", "stop", self.deployment.container_name],
            timeout=120,
        )

        # Copy application data only after its writers have stopped.
        build_replacement_directory(prepared, replacement)

        commit_recovery_transaction(
            prepared,
            replacement,
            retained,
            application_stopped=True,
        )

        self._run(plan.command, timeout=300)

        inspection = self._wait_healthy(
            recovery_override=str(override),
            image_override=(
                str(image_override)
                if image_override.is_file()
                else None
            ),
        )

        if inspection is None:
            inspection = self._inspect()

        if inspection["Image"] != previous_image:
            raise UpdateError(
                "Rollback image mismatch: restored container "
                "does not use the previous image"
            )

    def recovery_required(self) -> bool:
        """Whether a retained rollback prevents further updates."""
        override = (
            self.deployment.project_directory
            / ".nexdeck-recovery"
            / "rollback.override.yaml"
        )
        return override.exists() or override.is_symlink()

    def can_update(self) -> bool:
        """Whether the runner may accept another update."""
        return (
            not self.lock.locked()
            and not self.recovery_required()
            and self.state.stage not in (
                "recovery_required",
                "rollback_complete",
                "rollback_failed",
            )
        )

    def reserve(self) -> bool:
        """Reserve an update only when recovery is not required."""
        if not self.lock.acquire(blocking=False):
            return False

        try:
            if self.recovery_required():
                self.state = UpdateState(
                    stage="recovery_required",
                    error=(
                        "A retained rollback override exists. "
                        "Review and reconcile the deployment before updating."
                    ),
                )
                self.lock.release()
                return False

            self.state = UpdateState(stage="queued")
            return True

        except BaseException:
            self.lock.release()
            raise


    def _prepare_recovery_checkpoint(
        self,
        backup_filename: str,
        *,
        environment_key_configured: bool = False,
    ) -> Path:
        """Assemble and verify a complete pre-update recovery package."""

        from datetime import datetime, timezone
        from uuid import uuid4

        from recovery_assembler import assemble_recovery_package
        from recovery_verify import verify_nexdeck_recovery_package

        self.verify_backup(backup_filename)

        recovery_root = (
            self.deployment.project_directory
            / ".nexdeck-updater"
            / "recovery"
        )

        # Recovery storage must already have been securely provisioned.
        # Never silently create a potentially unprotected directory.
        if not recovery_root.is_dir() or recovery_root.is_symlink():
            raise UpdateError(
                "Secure recovery storage is not configured"
            )

        recovery_id = (
            "pre-update-"
            + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            + "-"
            + uuid4().hex[:12]
        )

        package = assemble_recovery_package(
            self.deployment.data_directory,
            backup_filename,
            recovery_root,
            recovery_id,
            environment_key_configured=environment_key_configured,
        )

        if verify_nexdeck_recovery_package(package) is not True:
            raise UpdateError("Recovery package verification failed")

        return package

    def update(self, backup_filename: str | None = None) -> None:
        """Run a reserved update with its verified backup reference."""
        if not self.lock.locked() or self.state.stage != "queued":
            raise UpdateError("Update was not reserved")

        mutation_started = False
        previous_image = None
        recovery_package = None

        try:
            self.state = UpdateState(stage="validating")

            inspection = self._inspect()
            identity = capture_container_identity(inspection)
            previous_image = identity.image_id

            verify_enrolled_deployment(
                inspection,
                self.deployment,
                identity,
            )

            self.state.stage = "preparing_recovery"
            if not backup_filename:
                raise UpdateError(
                    "A verified pre-update backup is required"
                )

            recovery_package = self._prepare_recovery_checkpoint(
                backup_filename
            )

            self.state.stage = "resolving_release"
            target = self._resolve_update_target()

            self.state.stage = "preparing_image"
            image_id = self._prepare_update_image(target)

            # Refuse mutation if the enrolled container changed
            # while the update image was being prepared.
            self.state.stage = "verifying"
            verify_enrolled_deployment(
                self._inspect(),
                self.deployment,
                identity,
            )

            self.state.stage = "writing_override"
            mutation_started = True
            self._write_update_override(image_id)

            self.state.stage = "recreating"
            self._recreate_with_managed_image()

            self.state.stage = "verifying_image"
            self._verify_installed_image(image_id)

            self.state.stage = "checking_health"
            self._wait_healthy(
                image_override=str(self._managed_image_override()),
            )

            self.state.stage = "complete"

        except Exception as exc:
            self.state.error = str(exc)

            if mutation_started and previous_image is not None:
                self.state.stage = "rolling_back"

                try:
                    self._rollback(
                        previous_image,
                        recovery_package=recovery_package,
                    )
                except Exception as rollback_exc:
                    self.state.stage = "rollback_failed"
                    self.state.error = (
                        f"Update failed: {exc}; "
                        f"rollback failed: {rollback_exc}"
                    )
                else:
                    self.state.stage = "rollback_complete"
            else:
                self.state.stage = "failed"

            raise

        finally:
            self.lock.release()
