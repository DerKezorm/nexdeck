"""Managed latest-stable NexDeck update transaction.

This module orchestrates the update but does not grant Docker access.
Operations are supplied by the caller for testing and enforcement.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class ManagedUpdateOperations:
    verify_deployment: Callable[[], None]
    resolve_target: Callable[[], object]
    prepare_image: Callable[[object], str]
    write_override: Callable[[str], None]
    recreate: Callable[[], None]
    verify_image: Callable[[str], None]
    wait_healthy: Callable[[], None]
    rollback: Callable[[], None]


def execute_managed_update(
    operations: ManagedUpdateOperations,
) -> str:
    """Execute an update with rollback after deployment mutation."""

    operations.verify_deployment()

    target = operations.resolve_target()
    image_id = operations.prepare_image(target)

    # Recheck deployment identity after potentially lengthy image pull.
    operations.verify_deployment()

    mutation_started = False

    try:
        mutation_started = True
        operations.write_override(image_id)
        operations.recreate()
        operations.verify_image(image_id)
        operations.wait_healthy()

        return image_id

    except Exception:
        if mutation_started:
            operations.rollback()
        raise
