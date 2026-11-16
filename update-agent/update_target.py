"""Select a safe NexDeck update target."""

from __future__ import annotations

from dataclasses import dataclass

from latest_release import LatestRelease


class UpdateTargetError(ValueError):
    """An update target is unsafe or unsupported."""


@dataclass(frozen=True)
class UpdateTarget:
    version: str
    image_reference: str


def select_update_target(
    release: LatestRelease,
    *,
    deployment_id: str,
    test_mode: bool = False,
) -> UpdateTarget:
    """Select the latest stable image for an enrolled deployment."""

    if test_mode:
        if deployment_id != "nexdeck-updater-realtest":
            raise UpdateTargetError(
                "Test mode is restricted to the isolated deployment"
            )

        return UpdateTarget(
            version=release.version,
            image_reference=(
                f"nexdeck-updater-realtest:{release.version}"
            ),
        )

    if deployment_id == "nexdeck-updater-realtest":
        raise UpdateTargetError(
            "The isolated deployment requires explicit test mode"
        )

    return UpdateTarget(
        version=release.version,
        image_reference=release.image_reference,
    )
