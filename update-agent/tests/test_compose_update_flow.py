"""Offline tests for the managed Compose update sequence."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from compose_runner import ComposeRunner, UpdateError


OLD_IMAGE = "sha256:" + "b" * 64
NEW_IMAGE = "sha256:" + "c" * 64


def deployment(tmp_path):
    return SimpleNamespace(
        deployment_id="offline-test",
        project_directory=tmp_path,
        compose_file=tmp_path / "compose.yaml",
        project_name="nexdeck-offline-test",
        service_name="nexdeck",
        container_name="nexdeck-offline-test",
        data_directory=tmp_path / "data",
    )


def prepare_runner(tmp_path, *, health_fails=False):
    runner = ComposeRunner(deployment(tmp_path))
    events = []

    runner._inspect = lambda: {
        "Id": "a" * 64,
        "Image": OLD_IMAGE,
    }

    runner._prepare_recovery_checkpoint = lambda filename: (
        events.append(("recovery", filename))
    )

    runner._resolve_update_target = lambda: events.append(
        "resolve"
    ) or "target"

    runner._prepare_update_image = lambda target: (
        events.append("prepare") or NEW_IMAGE
    )

    runner._write_update_override = lambda image: (
        events.append(("override", image))
    )

    runner._recreate_with_managed_image = lambda: events.append(
        "recreate"
    )

    runner._verify_installed_image = lambda image: (
        events.append(("verify_image", image))
    )

    def health(**kwargs):
        events.append("health")
        assert kwargs["image_override"] == str(
            runner._managed_image_override()
        )
        if health_fails:
            raise UpdateError("Simulated unhealthy container")

    runner._wait_healthy = health

    runner._rollback = lambda image, **kwargs: events.append(
        ("rollback", image)
    )

    return runner, events


def test_successful_update_flow(tmp_path):
    runner, events = prepare_runner(tmp_path)

    assert runner.reserve()

    with patch(
        "compose_runner.verify_enrolled_deployment"
    ) as verify:
        runner.update(backup_filename="nexdeck-manual-test.db")

    assert verify.call_count == 2
    assert events == [
        ("recovery", "nexdeck-manual-test.db"),
        "resolve",
        "prepare",
        ("override", NEW_IMAGE),
        "recreate",
        ("verify_image", NEW_IMAGE),
        "health",
    ]
    assert runner.state.stage == "complete"
    assert runner.state.error is None
    assert not runner.lock.locked()


def test_failed_health_check_reports_failure(tmp_path):
    runner, events = prepare_runner(
        tmp_path,
        health_fails=True,
    )

    assert runner.reserve()

    with patch("compose_runner.verify_enrolled_deployment"):
        with pytest.raises(
            UpdateError,
            match="Simulated unhealthy container",
        ):
            runner.update(backup_filename="nexdeck-manual-test.db")

    assert events[-2:] == [
        "health",
        ("rollback", OLD_IMAGE),
    ]
    assert runner.state.stage == "rollback_complete"
    assert runner.state.error == "Simulated unhealthy container"
    assert not runner.lock.locked()


def test_missing_backup_blocks_update(tmp_path):
    runner, events = prepare_runner(tmp_path)

    assert runner.reserve()

    with patch("compose_runner.verify_enrolled_deployment"):
        with pytest.raises(
            UpdateError,
            match="A verified pre-update backup is required",
        ):
            runner.update()

    assert events == []
    assert runner.state.stage == "failed"
    assert not runner.lock.locked()


def test_failed_recovery_blocks_update(tmp_path):
    runner, events = prepare_runner(tmp_path)

    def failed_recovery(filename):
        events.append("recovery")
        raise UpdateError("Simulated recovery verification failure")

    runner._prepare_recovery_checkpoint = failed_recovery

    assert runner.reserve()

    with patch("compose_runner.verify_enrolled_deployment"):
        with pytest.raises(
            UpdateError,
            match="Simulated recovery verification failure",
        ):
            runner.update(
                backup_filename="nexdeck-manual-test.db"
            )

    assert events == ["recovery"]
    assert runner.state.stage == "failed"
    assert not runner.lock.locked()
