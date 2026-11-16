"""Integrated ComposeRunner recovery rollback tests."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from compose_runner import ComposeRunner


def test_rollback_restores_data_before_recreating_container(tmp_path):
    events = []

    project = tmp_path / "project"
    project.mkdir()

    data = tmp_path / "data"
    data.mkdir()

    transaction_root = project / ".nexdeck-updater" / "transactions"
    transaction_root.mkdir(parents=True)

    deployment = SimpleNamespace(
        project_directory=project,
        data_directory=data,
        container_name="enrolled-nexdeck-container",
    )

    runner = ComposeRunner(deployment)

    runner._managed_image_override = (
        lambda: project / "image.override.yaml"
    )

    runner._run = lambda command, timeout: events.append(
        ("run", command)
    )

    runner._wait_healthy = lambda **kwargs: {
        "Image": "sha256:previous"
    }

    prepared = SimpleNamespace(
        original_directory=data,
    )

    plan = SimpleNamespace(
        override_content="services: {}",
        command=["docker", "compose", "up", "-d", "nexdeck"],
    )

    override = (
        project / ".nexdeck-recovery" / "rollback.override.yaml"
    )

    def prepare(*args):
        events.append("prepare")
        return prepared

    def build(*args):
        events.append("build")

    def commit(*args, **kwargs):
        events.append("commit")

    with (
        patch(
            "recovery_transaction.prepare_recovery_transaction",
            side_effect=prepare,
        ),
        patch(
            "recovery_transaction.build_replacement_directory",
            side_effect=build,
        ),
        patch(
            "recovery_transaction.commit_recovery_transaction",
            side_effect=commit,
        ),
        patch(
            "rollback_control.build_rollback_plan",
            return_value=plan,
        ),
        patch(
            "recovery_files.write_recovery_override",
            return_value=override,
        ),
    ):
        runner._rollback(
            "sha256:previous",
            recovery_package=tmp_path / "checkpoint",
        )

    assert events == [
        "prepare",
        ("run", ["docker", "stop", "enrolled-nexdeck-container"]),
        "build",
        "commit",
        ("run", plan.command),
    ]
