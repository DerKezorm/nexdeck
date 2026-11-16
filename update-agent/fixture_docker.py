"""Restricted Docker adapter for the disposable updater fixture.

Command construction only. No Docker operations are executed.
Not intended for production deployments.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class FixtureDockerError(ValueError):
    """Unsafe fixture update operation."""


@dataclass(frozen=True)
class FixtureDeployment:
    compose_file: Path
    project_name: str
    service_name: str
    container_name: str
    data_directory: Path


@dataclass(frozen=True)
class FixtureCommand:
    argv: tuple[str, ...]
    environment: tuple[tuple[str, str], ...]


EXPECTED_PROJECT = "nexdeck-updater-isolated-test"
EXPECTED_SERVICE = "updater-fixture"
EXPECTED_CONTAINER = "nexdeck-updater-isolated-fixture"

APPROVED_VERSIONS = frozenset({"v1", "v2"})


def validate_fixture(deployment: FixtureDeployment) -> None:
    """Reject any deployment other than the exact disposable fixture."""

    expected_root = (
        Path(__file__).resolve().parent / "integration-test"
    )

    if deployment.project_name != EXPECTED_PROJECT:
        raise FixtureDockerError("Unexpected Compose project")

    if deployment.service_name != EXPECTED_SERVICE:
        raise FixtureDockerError("Unexpected Compose service")

    if deployment.container_name != EXPECTED_CONTAINER:
        raise FixtureDockerError("Unexpected container")

    if deployment.compose_file.resolve() != (
        expected_root / "compose.yaml"
    ).resolve():
        raise FixtureDockerError("Unexpected Compose file")

    if deployment.data_directory.resolve() != (
        expected_root / "test-data"
    ).resolve():
        raise FixtureDockerError("Unexpected data directory")


def build_fixture_update_command(
    deployment: FixtureDeployment,
    version: str,
) -> FixtureCommand:
    """Construct an approved fixture recreation command."""

    validate_fixture(deployment)

    if version not in APPROVED_VERSIONS:
        raise FixtureDockerError("Unapproved fixture version")

    return FixtureCommand(
        argv=(
            "docker",
            "compose",
            "--project-name",
            EXPECTED_PROJECT,
            "--file",
            str(deployment.compose_file),
            "up",
            "--detach",
            "--no-build",
            "--no-deps",
            "--force-recreate",
            EXPECTED_SERVICE,
        ),
        environment=(
            ("FIXTURE_IMAGE_TAG", version),
            ("FIXTURE_VERSION", version),
        ),
    )
