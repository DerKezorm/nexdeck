"""Restricted Docker Compose rollback command construction.

This module does not execute Docker commands or modify deployments.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from deployment_control import build_compose_update_commands


_IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}\Z")


class RollbackError(ValueError):
    """A rollback request is invalid or unsafe."""


@dataclass(frozen=True)
class RollbackPlan:
    previous_image: str
    override_content: str
    command: tuple[str, ...]


def build_rollback_plan(
    deployment,
    previous_image: str,
    override_file: Path,
    *,
    image_override: Path | None = None,
) -> RollbackPlan:
    """Build a rollback plan for an explicitly enrolled deployment."""

    if (
        not isinstance(previous_image, str)
        or not _IMAGE_ID.fullmatch(previous_image)
    ):
        raise RollbackError("Invalid previous image identity")

    if not isinstance(override_file, Path):
        raise RollbackError("Invalid rollback override path")

    if not override_file.is_absolute():
        raise RollbackError("Rollback override path must be absolute")

    if ".." in override_file.parts:
        raise RollbackError("Rollback override path contains traversal")

    # Reuse deployment restrictions and approved override paths.
    commands = build_compose_update_commands(
        deployment,
        image_override=image_override,
        recovery_override=override_file,
    )

    # Recovery must take precedence over the managed image.
    command = commands.recreate[:-2] + (
        "--force-recreate",
    ) + commands.recreate[-2:]

    override_content = (
        "services:\n"
        f"  {deployment.service_name}:\n"
        f"    image: {previous_image}\n"
        "    pull_policy: never\n"
    )

    return RollbackPlan(
        previous_image=previous_image,
        override_content=override_content,
        command=command,
    )
