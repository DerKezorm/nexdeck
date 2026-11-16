"""Strict Compose ownership validation during rollback."""

from dataclasses import replace

import pytest

from deployment_control import (
    ComposeOwnership,
    DeploymentControlError,
    verify_compose_ownership,
)


BASE = "/tmp/nexdeck-e2e"
COMPOSE = BASE + "/compose.yaml"
RECOVERY = BASE + "/.nexdeck-recovery/rollback.override.yaml"


def inspection(files):
    return {
        "Config": {
            "Labels": {
                "com.docker.compose.project.working_dir": BASE,
                "com.docker.compose.project.config_files": files,
            }
        }
    }


def test_normal_deployment_accepts_original_compose():
    expected = ComposeOwnership(BASE, COMPOSE)
    verify_compose_ownership(inspection(COMPOSE), expected)


def test_normal_deployment_rejects_recovery_override():
    expected = ComposeOwnership(BASE, COMPOSE)

    with pytest.raises(
        DeploymentControlError,
        match="configuration file mismatch",
    ):
        verify_compose_ownership(
            inspection(COMPOSE + "," + RECOVERY),
            expected,
        )


def test_rollback_accepts_exact_recovery_override():
    expected = ComposeOwnership(BASE, COMPOSE, RECOVERY)

    verify_compose_ownership(
        inspection(COMPOSE + "," + RECOVERY),
        expected,
    )


@pytest.mark.parametrize(
    "files",
    [
        COMPOSE + ",/tmp/unexpected.yaml",
        COMPOSE + "," + RECOVERY + ",/tmp/extra.yaml",
        RECOVERY + "," + COMPOSE,
        COMPOSE,
    ],
)
def test_rollback_rejects_unexpected_compose_files(files):
    expected = ComposeOwnership(BASE, COMPOSE, RECOVERY)

    with pytest.raises(
        DeploymentControlError,
        match="configuration file mismatch",
    ):
        verify_compose_ownership(
            inspection(files),
            expected,
        )


def test_rollback_rejects_wrong_working_directory():
    expected = ComposeOwnership(BASE, COMPOSE, RECOVERY)
    actual = inspection(COMPOSE + "," + RECOVERY)
    actual["Config"]["Labels"][
        "com.docker.compose.project.working_dir"
    ] = "/tmp/wrong"

    with pytest.raises(
        DeploymentControlError,
        match="working directory mismatch",
    ):
        verify_compose_ownership(actual, expected)
