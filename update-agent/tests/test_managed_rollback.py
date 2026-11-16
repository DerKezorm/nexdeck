from pathlib import Path
from types import SimpleNamespace

import pytest

from rollback_control import build_rollback_plan
from deployment_control import DeploymentControlError


@pytest.fixture
def deployment():
    return SimpleNamespace(
        project_directory=Path("/srv/nexdeck"),
        compose_file=Path("/srv/nexdeck/compose.yaml"),
        project_name="nexdeck",
        service_name="nexdeck",
        container_name="nexdeck",
    )


def test_rollback_without_managed_override(deployment):
    recovery = (
        deployment.project_directory
        / ".nexdeck-recovery"
        / "rollback.override.yaml"
    )

    plan = build_rollback_plan(
        deployment,
        "sha256:" + "a" * 64,
        recovery,
    )

    assert plan.command.count("--file") == 2
    assert "--force-recreate" in plan.command
    assert "image: sha256:" in plan.override_content


def test_rollback_with_managed_override(deployment):
    image = (
        deployment.project_directory
        / ".nexdeck-updater"
        / "image.override.yaml"
    )

    recovery = (
        deployment.project_directory
        / ".nexdeck-recovery"
        / "rollback.override.yaml"
    )

    plan = build_rollback_plan(
        deployment,
        "sha256:" + "b" * 64,
        recovery,
        image_override=image,
    )

    files = [
        plan.command[index + 1]
        for index, value in enumerate(plan.command[:-1])
        if value == "--file"
    ]

    assert files == [
        str(deployment.compose_file),
        str(image),
        str(recovery),
    ]

    assert plan.command[-5:] == (
        "up",
        "--detach",
        "--no-deps",
        "--force-recreate",
        "--no-build",
    ) or (
        plan.command[-6:] == (
            "up",
            "--detach",
            "--no-deps",
            "--force-recreate",
            "--no-build",
            "nexdeck",
        )
    )


def test_unapproved_recovery_path_rejected(deployment):
    with pytest.raises(DeploymentControlError):
        build_rollback_plan(
            deployment,
            "sha256:" + "c" * 64,
            Path("/tmp/unapproved.yaml"),
        )
