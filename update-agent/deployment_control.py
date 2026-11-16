"""Restricted Docker deployment inspection primitives.

Command construction only. No Docker commands are executed here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


class DeploymentControlError(ValueError):
    """An unsafe or unsupported deployment operation was requested."""


_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")


@dataclass(frozen=True)
class DockerInspection:
    container_name: str
    command: tuple[str, ...]


def build_inspect_command(container_name: str) -> DockerInspection:
    """Construct an argument-vector Docker inspect command."""

    if not isinstance(container_name, str):
        raise DeploymentControlError(
            "Container name must be a string"
        )

    if not _IDENTIFIER.fullmatch(container_name):
        raise DeploymentControlError(
            "Invalid container name"
        )

    return DockerInspection(
        container_name=container_name,
        command=(
            "docker",
            "container",
            "inspect",
            "--",
            container_name,
        ),
    )


@dataclass(frozen=True)
class DeploymentIdentity:
    project_name: str
    service_name: str
    container_name: str
    data_directory: str


def verify_deployment_identity(
    inspection: dict,
    expected: DeploymentIdentity,
) -> None:
    """Verify inspected container identity against an enrolled deployment."""

    if not isinstance(inspection, dict):
        raise DeploymentControlError("Invalid Docker inspection")

    config = inspection.get("Config")
    if not isinstance(config, dict):
        raise DeploymentControlError("Missing container configuration")

    labels = config.get("Labels")
    if not isinstance(labels, dict):
        raise DeploymentControlError("Missing Compose labels")

    actual_name = inspection.get("Name")

    if actual_name != f"/{expected.container_name}":
        raise DeploymentControlError("Container name mismatch")

    required_labels = {
        "com.docker.compose.project": expected.project_name,
        "com.docker.compose.service": expected.service_name,
    }

    for key, value in required_labels.items():
        if labels.get(key) != value:
            raise DeploymentControlError(
                f"Compose identity mismatch: {key}"
            )

    mounts = inspection.get("Mounts")

    if not isinstance(mounts, list):
        raise DeploymentControlError("Missing container mounts")

    if not all(isinstance(mount, dict) for mount in mounts):
        raise DeploymentControlError(
            "Invalid container mount entry"
        )

    data_mounts = [
        mount
        for mount in mounts
        if mount.get("Destination") == "/data"
    ]

    if len(data_mounts) != 1:
        raise DeploymentControlError(
            "Expected exactly one persistent data mount"
        )

    data_mount = data_mounts[0]

    if (
        data_mount.get("Type") != "bind"
        or data_mount.get("Source") != expected.data_directory
    ):
        raise DeploymentControlError(
            "Persistent data mount mismatch"
        )


_CONTAINER_ID = re.compile(r"[0-9a-f]{64}\Z")


@dataclass(frozen=True)
class ContainerIdentity:
    container_id: str
    image_id: str


def capture_container_identity(
    inspection: dict,
) -> ContainerIdentity:
    """Capture immutable IDs from a Docker inspection result."""

    if not isinstance(inspection, dict):
        raise DeploymentControlError(
            "Invalid Docker inspection"
        )

    container_id = inspection.get("Id")
    image_id = inspection.get("Image")

    if (
        not isinstance(container_id, str)
        or not _CONTAINER_ID.fullmatch(container_id)
    ):
        raise DeploymentControlError(
            "Invalid Docker container ID"
        )

    if (
        not isinstance(image_id, str)
        or not image_id.startswith("sha256:")
        or not _CONTAINER_ID.fullmatch(image_id[7:])
    ):
        raise DeploymentControlError(
            "Invalid Docker image ID"
        )

    return ContainerIdentity(
        container_id=container_id,
        image_id=image_id,
    )


def verify_container_unchanged(
    inspection: dict,
    expected: ContainerIdentity,
) -> None:
    """Reject a replaced container or changed image identity."""

    actual = capture_container_identity(inspection)

    if actual != expected:
        raise DeploymentControlError(
            "Container or image identity changed"
        )


@dataclass(frozen=True)
class ComposeOwnership:
    project_directory: str
    compose_file: str
    recovery_override: str | None = None
    image_override: str | None = None


def verify_compose_ownership(
    inspection: dict,
    expected: ComposeOwnership,
) -> None:
    """Verify Compose configuration ownership against enrollment."""

    if not isinstance(inspection, dict):
        raise DeploymentControlError(
            "Invalid Docker inspection"
        )

    config = inspection.get("Config")

    if not isinstance(config, dict):
        raise DeploymentControlError(
            "Missing container configuration"
        )

    labels = config.get("Labels")

    if not isinstance(labels, dict):
        raise DeploymentControlError(
            "Missing Compose labels"
        )

    actual_directory = labels.get(
        "com.docker.compose.project.working_dir"
    )

    actual_files = labels.get(
        "com.docker.compose.project.config_files"
    )

    if (
        not isinstance(actual_directory, str)
        or actual_directory != expected.project_directory
    ):
        raise DeploymentControlError(
            "Compose working directory mismatch"
        )

    expected_files = expected.compose_file

    if expected.image_override is not None:
        expected_files += "," + expected.image_override

    if expected.recovery_override is not None:
        expected_files += "," + expected.recovery_override

    if (
        not isinstance(actual_files, str)
        or actual_files != expected_files
    ):
        raise DeploymentControlError(
            "Compose configuration file mismatch"
        )


def verify_enrolled_deployment(
    inspection: dict,
    deployment,
    expected_container: ContainerIdentity,
    recovery_override: str | None = None,
    image_override: str | None = None,
) -> None:
    """Require every deployment identity check to pass."""

    verify_deployment_identity(
        inspection,
        DeploymentIdentity(
            project_name=deployment.project_name,
            service_name=deployment.service_name,
            container_name=deployment.container_name,
            data_directory=str(deployment.data_directory),
        ),
    )

    verify_compose_ownership(
        inspection,
        ComposeOwnership(
            project_directory=str(deployment.project_directory),
            compose_file=str(deployment.compose_file),
            recovery_override=recovery_override,
            image_override=image_override,
        ),
    )

    verify_container_unchanged(
        inspection,
        expected_container,
    )



@dataclass(frozen=True)
class ComposeUpdateCommands:
    """Fixed commands for updating an enrolled Compose deployment."""

    pull: tuple[str, ...]
    recreate: tuple[str, ...]


def build_compose_update_commands(
    deployment,
    *,
    image_override: Path | None = None,
    recovery_override: Path | None = None,
) -> ComposeUpdateCommands:
    """Build restricted Compose commands without executing them.

    Deployment details must originate from a trusted manifest, never
    from an HTTP request.
    """

    if deployment.container_name in {
        "nexdeck-mfa-dev",
        "nexdeck-updater-isolated-fixture",
    }:
        raise DeploymentControlError(
            "Development and fixture deployments cannot be updated"
        )

    if deployment.service_name != "nexdeck":
        raise DeploymentControlError(
            "Only the NexDeck service can be updated"
        )

    base = (
        "docker",
        "compose",
        "--project-directory",
        str(deployment.project_directory),
        "--file",
        str(deployment.compose_file),
        "--project-name",
        deployment.project_name,
    )

    if image_override is not None:
        expected = (
            deployment.project_directory
            / ".nexdeck-updater"
            / "image.override.yaml"
        )

        if image_override != expected:
            raise DeploymentControlError(
                "Unapproved managed image override"
            )

        base += ("--file", str(image_override))

    if recovery_override is not None:
        expected_recovery = (
            deployment.project_directory
            / ".nexdeck-recovery"
            / "rollback.override.yaml"
        )

        if recovery_override != expected_recovery:
            raise DeploymentControlError(
                "Unapproved recovery override"
            )

        base += ("--file", str(recovery_override))

    return ComposeUpdateCommands(
        pull=base + ("pull", deployment.service_name),
        recreate=base + (
            "up",
            "--detach",
            "--no-deps",
            "--no-build",
            deployment.service_name,
        ),
    )
