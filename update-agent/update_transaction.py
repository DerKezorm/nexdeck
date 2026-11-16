"""Restricted NexDeck update transaction planning.

Planning only. No Docker commands, backups, restores or updates
are executed by this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class UpdateStage(str, Enum):
    VALIDATE = "validate"
    BACKUP = "backup"
    VERIFY_BACKUP = "verify_backup"
    PULL_IMAGE = "pull_image"
    RECREATE = "recreate"
    HEALTH_CHECK = "health_check"
    COMPLETE = "complete"
    ROLLBACK = "rollback"


class UpdateTransactionError(ValueError):
    """An unsafe update transaction was requested."""


@dataclass(frozen=True)
class UpdatePlan:
    deployment_id: str
    stages: tuple[UpdateStage, ...]
    rollback_on_failure: bool


def build_update_plan(
    deployment_id: str,
    *,
    rollback_on_failure: bool = True,
) -> UpdatePlan:
    """Build a fixed-order update plan for an enrolled deployment."""

    if not isinstance(deployment_id, str):
        raise UpdateTransactionError(
            "Deployment identifier must be a string"
        )

    if (
        not deployment_id
        or len(deployment_id) > 128
        or not all(
            character.isascii()
            and (
                character.isalnum()
                or character in "-_"
            )
            for character in deployment_id
        )
    ):
        raise UpdateTransactionError(
            "Invalid deployment identifier"
        )

    if rollback_on_failure is not True:
        raise UpdateTransactionError(
            "Rollback protection is mandatory"
        )

    return UpdatePlan(
        deployment_id=deployment_id,
        stages=(
            UpdateStage.VALIDATE,
            UpdateStage.BACKUP,
            UpdateStage.VERIFY_BACKUP,
            UpdateStage.PULL_IMAGE,
            UpdateStage.RECREATE,
            UpdateStage.HEALTH_CHECK,
            UpdateStage.COMPLETE,
        ),
        rollback_on_failure=True,
    )
