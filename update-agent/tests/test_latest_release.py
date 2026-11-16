import pytest

from latest_release import (
    ReleaseResolutionError,
    parse_latest_release,
)


def test_valid_stable_release():
    release = parse_latest_release({
        "tag_name": "v1.8.0",
        "draft": False,
        "prerelease": False,
    })

    assert release.version == "1.8.0"
    assert release.tag == "v1.8.0"
    assert release.image_repository == "ghcr.io/derkezorm/nexdeck"


@pytest.mark.parametrize("payload", [
    {"tag_name": "v1.8.0", "draft": True, "prerelease": False},
    {"tag_name": "v1.8.0", "draft": False, "prerelease": True},
    {"tag_name": "v1.8.0-rc1", "draft": False, "prerelease": False},
    {"tag_name": "latest", "draft": False, "prerelease": False},
    {"tag_name": "", "draft": False, "prerelease": False},
    {"draft": False, "prerelease": False},
])
def test_invalid_release_rejected(payload):
    with pytest.raises(ReleaseResolutionError):
        parse_latest_release(payload)


def test_release_uses_version_specific_image():
    release = parse_latest_release({
        "tag_name": "v1.8.0",
        "draft": False,
        "prerelease": False,
    })

    assert release.image_reference == (
        "ghcr.io/derkezorm/nexdeck:1.8.0"
    )
