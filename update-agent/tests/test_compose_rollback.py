"""Offline tests for managed Compose rollback."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from compose_runner import ComposeRunner, UpdateError


OLD_IMAGE = "sha256:" + "b" * 64
NEW_IMAGE = "sha256:" + "c" * 64


def deployment():
    root = Path("/tmp/nexdeck-rollback-offline")
    return SimpleNamespace(
        deployment_id="rollback-offline",
        project_directory=root,
        compose_file=root / "compose.yaml",
        project_name="nexdeck-rollback-offline",
        service_name="nexdeck",
        container_name="nexdeck-rollback-offline",
        data_directory=root / "data",
    )


def inspection():
    return {
        "Id": "a" * 64,
        "Image": OLD_IMAGE,
    }


@pytest.mark.parametrize(
    "rollback_fails, expected_stage",
    [
        (False, "rollback_complete"),
        (True, "rollback_failed"),
    ],
)
def test_failed_health_triggers_rollback(
    rollback_fails,
    expected_stage,
):
    runner = ComposeRunner(deployment())
    events = []

    runner._inspect = inspection
    runner._prepare_recovery_checkpoint = lambda filename: None
    runner._resolve_update_target = lambda: "target"
    runner._prepare_update_image = lambda target: NEW_IMAGE
    runner._write_update_override = lambda image: None
    runner._recreate_with_managed_image = lambda: None
    runner._verify_installed_image = lambda image: None

    def failed_health(**kwargs):
        events.append("health")
        raise UpdateError("Simulated update health failure")

    runner._wait_healthy = failed_health

    def fake_rollback(previous_image, *, recovery_package=None):
        events.append("rollback")
        assert previous_image == OLD_IMAGE
        if rollback_fails:
            raise UpdateError("Simulated rollback failure")

    runner._rollback = fake_rollback

    assert runner.reserve()

    with patch("compose_runner.verify_enrolled_deployment"):
        with pytest.raises(UpdateError):
            runner.update(backup_filename="nexdeck-manual-test.db")

    assert events == ["health", "rollback"]
    assert runner.state.stage == expected_stage
    assert not runner.lock.locked()


def test_failure_before_mutation_does_not_rollback():
    runner = ComposeRunner(deployment())
    events = []

    runner._inspect = inspection
    runner._prepare_recovery_checkpoint = lambda filename: None
    runner._resolve_update_target = lambda: "target"

    def failed_prepare(target):
        raise UpdateError("Simulated image preparation failure")

    runner._prepare_update_image = failed_prepare
    runner._rollback = lambda image: events.append("rollback")

    assert runner.reserve()

    with patch("compose_runner.verify_enrolled_deployment"):
        with pytest.raises(
            UpdateError,
            match="Simulated image preparation failure",
        ):
            runner.update(backup_filename="nexdeck-manual-test.db")

    assert "rollback" not in events
    assert runner.state.stage == "failed"
    assert not runner.lock.locked()


def test_retained_rollback_blocks_new_updates(tmp_path):
    deployment_config = deployment()
    deployment_config.project_directory = tmp_path

    recovery_dir = tmp_path / ".nexdeck-recovery"
    recovery_dir.mkdir()

    override = recovery_dir / "rollback.override.yaml"
    override.write_text(
        "services:\n"
        "  nexdeck:\n"
        "    image: sha256:" + "b" * 64 + "\n"
    )

    runner = ComposeRunner(deployment_config)

    assert runner.reserve() is False
    assert runner.state.stage == "recovery_required"
    assert "reconcile" in runner.state.error
    assert not runner.lock.locked()

    # A new runner simulates an agent restart.
    restarted_runner = ComposeRunner(deployment_config)

    assert restarted_runner.reserve() is False
    assert restarted_runner.state.stage == "recovery_required"


def test_can_update_reflects_recovery_state(tmp_path):
    config = deployment()
    config.project_directory = tmp_path

    runner = ComposeRunner(config)

    assert runner.can_update() is True

    assert runner.reserve() is True
    assert runner.can_update() is False
    runner.lock.release()

    recovery_dir = tmp_path / ".nexdeck-recovery"
    recovery_dir.mkdir()

    override = recovery_dir / "rollback.override.yaml"
    override.write_text("services:\n  nexdeck:\n    image: test\n")

    assert runner.can_update() is False

    restarted = ComposeRunner(config)
    assert restarted.can_update() is False
