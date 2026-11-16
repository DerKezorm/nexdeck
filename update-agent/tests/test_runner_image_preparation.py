import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from compose_runner import ComposeRunner, UpdateError
from update_target import UpdateTarget


IMAGE_ID = "sha256:" + "a" * 64


def runner_for(deployment_id):
    return ComposeRunner(SimpleNamespace(
        deployment_id=deployment_id,
        project_directory=Path("/tmp/nexdeck-image-test"),
    ))


def test_production_pulls_and_inspects_image():
    runner = runner_for("nexdeck-production")
    operations = []

    def fake_run(command, timeout):
        operations.append(command)
        if command[1:3] == ("image", "inspect"):
            return json.dumps([{"Id": IMAGE_ID}])
        return ""

    runner._run = fake_run

    result = runner._prepare_update_image(UpdateTarget(
        version="1.8.0",
        image_reference="ghcr.io/derkezorm/nexdeck:1.8.0",
    ))

    assert result == IMAGE_ID
    assert operations[0] == (
        "docker", "pull",
        "ghcr.io/derkezorm/nexdeck:1.8.0",
    )


def test_isolated_image_is_not_pulled():
    runner = runner_for("nexdeck-updater-realtest")
    operations = []

    def fake_run(command, timeout):
        operations.append(command)
        return json.dumps([{"Id": IMAGE_ID}])

    runner._run = fake_run

    result = runner._prepare_update_image(UpdateTarget(
        version="1.8.0",
        image_reference="nexdeck-updater-realtest:1.8.0",
    ))

    assert result == IMAGE_ID
    assert len(operations) == 1
    assert operations[0][:3] == (
        "docker", "image", "inspect",
    )


def test_invalid_image_identity_rejected():
    runner = runner_for("nexdeck-updater-realtest")
    runner._run = lambda command, timeout: json.dumps([
        {"Id": "not-a-digest"}
    ])

    with pytest.raises(UpdateError):
        runner._prepare_update_image(UpdateTarget(
            version="1.8.0",
            image_reference="nexdeck-updater-realtest:1.8.0",
        ))


def test_unapproved_image_rejected():
    runner = runner_for("nexdeck-production")
    runner._run = lambda command, timeout: pytest.fail(
        "Docker must not be called"
    )

    with pytest.raises(UpdateError):
        runner._prepare_update_image(UpdateTarget(
            version="1.8.0",
            image_reference="ubuntu:latest",
        ))
