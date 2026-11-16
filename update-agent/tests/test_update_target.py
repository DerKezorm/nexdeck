import pytest

from latest_release import parse_latest_release
from update_target import (
    UpdateTargetError,
    select_update_target,
)


@pytest.fixture
def release():
    return parse_latest_release({
        "tag_name": "v1.8.0",
        "draft": False,
        "prerelease": False,
    })


def test_production_uses_official_version(release):
    target = select_update_target(
        release,
        deployment_id="nexdeck-production",
    )

    assert target.version == "1.8.0"
    assert target.image_reference == (
        "ghcr.io/derkezorm/nexdeck:1.8.0"
    )


def test_isolated_test_uses_local_image(release):
    target = select_update_target(
        release,
        deployment_id="nexdeck-updater-realtest",
        test_mode=True,
    )

    assert target.image_reference == (
        "nexdeck-updater-realtest:1.8.0"
    )


def test_isolated_test_rejects_production_mode(release):
    with pytest.raises(UpdateTargetError):
        select_update_target(
            release,
            deployment_id="nexdeck-updater-realtest",
        )


def test_other_deployments_reject_test_mode(release):
    with pytest.raises(UpdateTargetError):
        select_update_target(
            release,
            deployment_id="nexdeck-production",
            test_mode=True,
        )
