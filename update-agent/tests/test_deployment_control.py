"""Tests for restricted Docker deployment identity validation."""

import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[1]),
)

from deployment_control import (
    DeploymentControlError,
    DeploymentIdentity,
    build_inspect_command,
    verify_deployment_identity,
)


@pytest.fixture
def expected():
    return DeploymentIdentity(
        project_name="nexdeck-test",
        service_name="nexdeck",
        container_name="nexdeck-test",
        data_directory="/tmp/nexdeck-test-data",
    )


@pytest.fixture
def inspection():
    return {
        "Name": "/nexdeck-test",
        "Config": {
            "Labels": {
                "com.docker.compose.project": "nexdeck-test",
                "com.docker.compose.service": "nexdeck",
            }
        },
        "Mounts": [
            {
                "Type": "bind",
                "Source": "/tmp/nexdeck-test-data",
                "Destination": "/data",
            }
        ],
    }


def test_inspect_command_uses_argument_vector():
    result = build_inspect_command("nexdeck-test")

    assert result.command == (
        "docker",
        "container",
        "inspect",
        "--",
        "nexdeck-test",
    )


@pytest.mark.parametrize(
    "name",
    [
        "",
        "../nexdeck",
        "--privileged",
        "nexdeck;echo unsafe",
        "nexdeck && echo unsafe",
        "nexdeck\nother",
    ],
)
def test_unsafe_container_names_rejected(name):
    with pytest.raises(DeploymentControlError):
        build_inspect_command(name)


def test_matching_identity_accepted(inspection, expected):
    verify_deployment_identity(inspection, expected)


@pytest.mark.parametrize(
    "field,value",
    [
        ("Name", "/other"),
        ("Mounts", []),
        ("Mounts", None),
    ],
)
def test_invalid_identity_rejected(
    inspection, expected, field, value
):
    altered = copy.deepcopy(inspection)
    altered[field] = value

    with pytest.raises(DeploymentControlError):
        verify_deployment_identity(altered, expected)


def test_wrong_project_rejected(inspection, expected):
    inspection["Config"]["Labels"][
        "com.docker.compose.project"
    ] = "other"

    with pytest.raises(DeploymentControlError):
        verify_deployment_identity(inspection, expected)


def test_wrong_service_rejected(inspection, expected):
    inspection["Config"]["Labels"][
        "com.docker.compose.service"
    ] = "other"

    with pytest.raises(DeploymentControlError):
        verify_deployment_identity(inspection, expected)


def test_wrong_data_source_rejected(inspection, expected):
    inspection["Mounts"][0]["Source"] = "/tmp/other"

    with pytest.raises(DeploymentControlError):
        verify_deployment_identity(inspection, expected)


def test_duplicate_data_mount_rejected(inspection, expected):
    inspection["Mounts"].append(
        copy.deepcopy(inspection["Mounts"][0])
    )

    with pytest.raises(DeploymentControlError):
        verify_deployment_identity(inspection, expected)


def test_unlabelled_container_rejected(inspection, expected):
    inspection["Config"]["Labels"] = {}

    with pytest.raises(DeploymentControlError):
        verify_deployment_identity(inspection, expected)


def test_conflicting_data_mount_rejected(inspection, expected):
    inspection["Mounts"].append(
        {
            "Type": "bind",
            "Source": "/tmp/other-data",
            "Destination": "/data",
        }
    )

    with pytest.raises(DeploymentControlError):
        verify_deployment_identity(inspection, expected)


def test_non_bind_data_mount_rejected(inspection, expected):
    inspection["Mounts"][0]["Type"] = "volume"

    with pytest.raises(DeploymentControlError):
        verify_deployment_identity(inspection, expected)


def test_invalid_mount_entry_rejected(inspection, expected):
    inspection["Mounts"].append(None)

    with pytest.raises(DeploymentControlError):
        verify_deployment_identity(inspection, expected)


def test_capture_immutable_container_identity():
    from deployment_control import capture_container_identity

    inspection = {
        "Id": "a" * 64,
        "Image": "sha256:" + "b" * 64,
    }

    identity = capture_container_identity(inspection)

    assert identity.container_id == "a" * 64
    assert identity.image_id == "sha256:" + "b" * 64


def test_replaced_container_rejected():
    from deployment_control import (
        capture_container_identity,
        verify_container_unchanged,
    )

    original = {
        "Id": "a" * 64,
        "Image": "sha256:" + "b" * 64,
    }

    expected = capture_container_identity(original)

    replacement = {
        "Id": "c" * 64,
        "Image": "sha256:" + "b" * 64,
    }

    with pytest.raises(DeploymentControlError):
        verify_container_unchanged(replacement, expected)


def test_changed_image_rejected():
    from deployment_control import (
        capture_container_identity,
        verify_container_unchanged,
    )

    original = {
        "Id": "a" * 64,
        "Image": "sha256:" + "b" * 64,
    }

    expected = capture_container_identity(original)

    changed = {
        "Id": "a" * 64,
        "Image": "sha256:" + "c" * 64,
    }

    with pytest.raises(DeploymentControlError):
        verify_container_unchanged(changed, expected)


@pytest.mark.parametrize(
    "container_id,image_id",
    [
        ("short", "sha256:" + "b" * 64),
        ("g" * 64, "sha256:" + "b" * 64),
        ("a" * 64, "invalid"),
        ("a" * 64, "sha256:short"),
        (None, "sha256:" + "b" * 64),
    ],
)
def test_invalid_immutable_identity_rejected(
    container_id, image_id
):
    from deployment_control import capture_container_identity

    with pytest.raises(DeploymentControlError):
        capture_container_identity(
            {
                "Id": container_id,
                "Image": image_id,
            }
        )


def test_matching_compose_ownership_accepted():
    from deployment_control import (
        ComposeOwnership,
        verify_compose_ownership,
    )

    inspection = {
        "Config": {
            "Labels": {
                "com.docker.compose.project.working_dir":
                    "/opt/nexdeck",
                "com.docker.compose.project.config_files":
                    "/opt/nexdeck/docker-compose.yml",
            }
        }
    }

    expected = ComposeOwnership(
        project_directory="/opt/nexdeck",
        compose_file="/opt/nexdeck/docker-compose.yml",
    )

    verify_compose_ownership(inspection, expected)


@pytest.mark.parametrize(
    "working_dir,config_files",
    [
        ("/opt/other", "/opt/nexdeck/docker-compose.yml"),
        ("/opt/nexdeck", "/opt/other/compose.yml"),
        (None, "/opt/nexdeck/docker-compose.yml"),
        ("/opt/nexdeck", None),
        (
            "/opt/nexdeck",
            "/opt/nexdeck/docker-compose.yml,"
            "/opt/nexdeck/override.yml",
        ),
    ],
)
def test_invalid_compose_ownership_rejected(
    working_dir, config_files
):
    from deployment_control import (
        ComposeOwnership,
        verify_compose_ownership,
    )

    inspection = {
        "Config": {
            "Labels": {
                "com.docker.compose.project.working_dir":
                    working_dir,
                "com.docker.compose.project.config_files":
                    config_files,
            }
        }
    }

    expected = ComposeOwnership(
        project_directory="/opt/nexdeck",
        compose_file="/opt/nexdeck/docker-compose.yml",
    )

    with pytest.raises(DeploymentControlError):
        verify_compose_ownership(inspection, expected)


def test_unified_deployment_verification_accepted():
    from manifest import Deployment
    from deployment_control import (
        capture_container_identity,
        verify_enrolled_deployment,
    )

    deployment = Deployment(
        deployment_id="test-deployment",
        compose_file=Path("/opt/nexdeck/docker-compose.yml"),
        project_directory=Path("/opt/nexdeck"),
        project_name="nexdeck-test",
        service_name="nexdeck",
        container_name="nexdeck",
        data_directory=Path("/opt/nexdeck/data"),
    )

    inspection = {
        "Id": "a" * 64,
        "Image": "sha256:" + "b" * 64,
        "Name": "/nexdeck",
        "Config": {
            "Labels": {
                "com.docker.compose.project": "nexdeck-test",
                "com.docker.compose.service": "nexdeck",
                "com.docker.compose.project.working_dir":
                    "/opt/nexdeck",
                "com.docker.compose.project.config_files":
                    "/opt/nexdeck/docker-compose.yml",
            }
        },
        "Mounts": [
            {
                "Type": "bind",
                "Source": "/opt/nexdeck/data",
                "Destination": "/data",
            }
        ],
    }

    expected = capture_container_identity(inspection)

    verify_enrolled_deployment(
        inspection,
        deployment,
        expected,
    )


@pytest.mark.parametrize(
    "change",
    [
        "project",
        "service",
        "compose_file",
        "working_dir",
        "data_mount",
        "container_id",
        "image_id",
    ],
)
def test_unified_deployment_verification_rejects_mismatch(change):
    from manifest import Deployment
    from deployment_control import (
        capture_container_identity,
        verify_enrolled_deployment,
    )

    deployment = Deployment(
        deployment_id="test-deployment",
        compose_file=Path("/opt/nexdeck/docker-compose.yml"),
        project_directory=Path("/opt/nexdeck"),
        project_name="nexdeck-test",
        service_name="nexdeck",
        container_name="nexdeck",
        data_directory=Path("/opt/nexdeck/data"),
    )

    inspection = {
        "Id": "a" * 64,
        "Image": "sha256:" + "b" * 64,
        "Name": "/nexdeck",
        "Config": {
            "Labels": {
                "com.docker.compose.project": "nexdeck-test",
                "com.docker.compose.service": "nexdeck",
                "com.docker.compose.project.working_dir":
                    "/opt/nexdeck",
                "com.docker.compose.project.config_files":
                    "/opt/nexdeck/docker-compose.yml",
            }
        },
        "Mounts": [
            {
                "Type": "bind",
                "Source": "/opt/nexdeck/data",
                "Destination": "/data",
            }
        ],
    }

    expected = capture_container_identity(inspection)

    labels = inspection["Config"]["Labels"]

    if change == "project":
        labels["com.docker.compose.project"] = "other"
    elif change == "service":
        labels["com.docker.compose.service"] = "other"
    elif change == "compose_file":
        labels["com.docker.compose.project.config_files"] = (
            "/opt/other/compose.yml"
        )
    elif change == "working_dir":
        labels["com.docker.compose.project.working_dir"] = (
            "/opt/other"
        )
    elif change == "data_mount":
        inspection["Mounts"][0]["Source"] = "/opt/other/data"
    elif change == "container_id":
        inspection["Id"] = "c" * 64
    elif change == "image_id":
        inspection["Image"] = "sha256:" + "c" * 64

    with pytest.raises(DeploymentControlError):
        verify_enrolled_deployment(
            inspection,
            deployment,
            expected,
        )


def test_unified_verification_accepts_distinct_container_name():
    from manifest import Deployment
    from deployment_control import (
        capture_container_identity,
        verify_enrolled_deployment,
    )

    deployment = Deployment(
        deployment_id="production",
        compose_file=Path("/opt/nexdeck/docker-compose.yml"),
        project_directory=Path("/opt/nexdeck"),
        project_name="nexdeck",
        service_name="nexdeck",
        container_name="nexdeck-production",
        data_directory=Path("/opt/nexdeck/data"),
    )

    inspection = {
        "Id": "a" * 64,
        "Image": "sha256:" + "b" * 64,
        "Name": "/nexdeck-production",
        "Config": {
            "Labels": {
                "com.docker.compose.project": "nexdeck",
                "com.docker.compose.service": "nexdeck",
                "com.docker.compose.project.working_dir":
                    "/opt/nexdeck",
                "com.docker.compose.project.config_files":
                    "/opt/nexdeck/docker-compose.yml",
            }
        },
        "Mounts": [
            {
                "Type": "bind",
                "Source": "/opt/nexdeck/data",
                "Destination": "/data",
            }
        ],
    }

    expected = capture_container_identity(inspection)

    verify_enrolled_deployment(
        inspection,
        deployment,
        expected,
    )

    inspection["Name"] = "/nexdeck"

    with pytest.raises(DeploymentControlError):
        verify_enrolled_deployment(
            inspection,
            deployment,
            expected,
        )
