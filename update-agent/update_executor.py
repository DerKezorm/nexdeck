"""Testable NexDeck update transaction executor.

Operations are injected by the caller. This module does not
access Docker, filesystems, networks or production services.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from update_transaction import UpdateStage, UpdatePlan


@dataclass(frozen=True)
class UpdateOperations:
    validate: Callable[[], None]
    backup: Callable[[], None]
    verify_backup: Callable[[], None]
    pull_image: Callable[[], None]
    recreate: Callable[[], None]
    health_check: Callable[[], None]
    rollback: Callable[[], None]


@dataclass(frozen=True)
class UpdateResult:
    success: bool
    completed: tuple[str, ...]
    failed_stage: str | None
    rollback_attempted: bool
    rollback_succeeded: bool


def execute_update(
    plan: UpdatePlan,
    operations: UpdateOperations,
) -> UpdateResult:
    """Execute a fixed plan with mandatory rollback on mutation failure."""

    expected = (
        UpdateStage.VALIDATE,
        UpdateStage.BACKUP,
        UpdateStage.VERIFY_BACKUP,
        UpdateStage.PULL_IMAGE,
        UpdateStage.RECREATE,
        UpdateStage.HEALTH_CHECK,
        UpdateStage.COMPLETE,
    )

    if plan.stages != expected or plan.rollback_on_failure is not True:
        raise ValueError("Unsafe update plan")

    actions = {
        UpdateStage.VALIDATE: operations.validate,
        UpdateStage.BACKUP: operations.backup,
        UpdateStage.VERIFY_BACKUP: operations.verify_backup,
        UpdateStage.PULL_IMAGE: operations.pull_image,
        UpdateStage.RECREATE: operations.recreate,
        UpdateStage.HEALTH_CHECK: operations.health_check,
    }

    completed = []
    mutation_started = False

    for stage in plan.stages:
        if stage == UpdateStage.COMPLETE:
            break

        # Treat recreation as potentially mutating even if it raises.
        if stage == UpdateStage.RECREATE:
            mutation_started = True

        try:
            actions[stage]()
            completed.append(stage.value)

        except Exception:
            if not mutation_started:
                return UpdateResult(
                    False,
                    tuple(completed),
                    stage.value,
                    False,
                    False,
                )

            try:
                operations.rollback()
            except Exception:
                return UpdateResult(
                    False,
                    tuple(completed),
                    stage.value,
                    True,
                    False,
                )

            return UpdateResult(
                False,
                tuple(completed),
                stage.value,
                True,
                True,
            )

    return UpdateResult(
        True,
        tuple(completed) + (UpdateStage.COMPLETE.value,),
        None,
        False,
        False,
    )
