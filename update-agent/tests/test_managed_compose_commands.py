from pathlib import Path
from types import SimpleNamespace

import pytest

from deployment_control import (
    DeploymentControlError,
    build_compose_update_commands,
)


@pytest.fixture
def deployment():
    return SimpleNamespace(
        project_directory=Path("/srv/nexdeck"),
        compose_file=Path("/srv/nexdeck/compose.yaml"),
        project_name="nexdeck",
        service_name="nexdeck",
        container_name="nexdeck",
    )


def test_original_commands_unchanged(deployment):
    commands = build_compose_update_commands(deployment)

    assert commands.pull[-2:] == ("pull", "nexdeck")
    assert "--file" in commands.pull
    assert commands.pull.count("--file") == 1


def test_managed_override_added(deployment):
    override = (
        deployment.project_directory
        / ".nexdeck-updater"
        / "image.override.yaml"
    )

    commands = build_compose_update_commands(
        deployment,
        image_override=override,
    )

    assert commands.pull.count("--file") == 2
    assert str(override) in commands.pull
    assert str(override) in commands.recreate


def test_arbitrary_override_rejected(deployment):
    with pytest.raises(DeploymentControlError):
        build_compose_update_commands(
            deployment,
            image_override=Path("/tmp/unsafe.yaml"),
        )


def test_managed_image_and_recovery_override_order(deployment):
    image_override = (
        deployment.project_directory
        / ".nexdeck-updater"
        / "image.override.yaml"
    )
    recovery_override = (
        deployment.project_directory
        / ".nexdeck-recovery"
        / "rollback.override.yaml"
    )

    commands = build_compose_update_commands(
        deployment,
        image_override=image_override,
        recovery_override=recovery_override,
    )

    files = [
        commands.recreate[index + 1]
        for index, value in enumerate(commands.recreate[:-1])
        if value == "--file"
    ]

    assert files == [
        str(deployment.compose_file),
        str(image_override),
        str(recovery_override),
    ]


def test_arbitrary_recovery_override_rejected(deployment):
    with pytest.raises(DeploymentControlError):
        build_compose_update_commands(
            deployment,
            recovery_override=Path("/tmp/unsafe-recovery.yaml"),
        )
