import pytest

from deployment_control import (
    ComposeOwnership,
    DeploymentControlError,
    verify_compose_ownership,
)


def inspection(files):
    return {
        "Config": {
            "Labels": {
                "com.docker.compose.project.working_dir": "/srv/nexdeck",
                "com.docker.compose.project.config_files": files,
            }
        }
    }


def expected(image_override=None, recovery_override=None):
    return ComposeOwnership(
        project_directory="/srv/nexdeck",
        compose_file="/srv/nexdeck/compose.yaml",
        image_override=image_override,
        recovery_override=recovery_override,
    )


def test_original_compose_ownership():
    verify_compose_ownership(
        inspection("/srv/nexdeck/compose.yaml"),
        expected(),
    )


def test_managed_image_override_ownership():
    override = "/srv/nexdeck/.nexdeck-updater/image.override.yaml"

    verify_compose_ownership(
        inspection(
            "/srv/nexdeck/compose.yaml," + override
        ),
        expected(image_override=override),
    )


def test_unexpected_override_rejected():
    with pytest.raises(DeploymentControlError):
        verify_compose_ownership(
            inspection(
                "/srv/nexdeck/compose.yaml,/tmp/unsafe.yaml"
            ),
            expected(),
        )


def test_missing_managed_override_rejected():
    override = "/srv/nexdeck/.nexdeck-updater/image.override.yaml"

    with pytest.raises(DeploymentControlError):
        verify_compose_ownership(
            inspection("/srv/nexdeck/compose.yaml"),
            expected(image_override=override),
        )
