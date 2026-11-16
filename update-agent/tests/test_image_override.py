from pathlib import Path

import pytest

from image_override import (
    ImageOverrideError,
    build_image_override,
)


def test_official_versioned_image():
    result = build_image_override(
        Path("/srv/nexdeck"),
        "ghcr.io/derkezorm/nexdeck:1.8.0",
    )

    assert result.path == Path(
        "/srv/nexdeck/.nexdeck-updater/image.override.yaml"
    )
    assert "image: ghcr.io/derkezorm/nexdeck:1.8.0" in result.content
    assert "pull_policy: never" in result.content


def test_immutable_digest():
    digest = "a" * 64

    result = build_image_override(
        Path("/srv/nexdeck"),
        f"ghcr.io/derkezorm/nexdeck@sha256:{digest}",
    )

    assert f"@sha256:{digest}" in result.content


def test_isolated_test_image():
    result = build_image_override(
        Path("/srv/nexdeck-test"),
        "nexdeck-updater-realtest:1.8.0",
    )

    assert "nexdeck-updater-realtest:1.8.0" in result.content


@pytest.mark.parametrize("image", [
    "ubuntu:latest",
    "ghcr.io/derkezorm/nexdeck:latest",
    "ghcr.io/derkezorm/nexdeck:v1.8.0",
    "ghcr.io/derkezorm/nexdeck:1.8.0\nprivileged: true",
    "nexdeck-updater-realtest:feature-auto-refresh",
])
def test_unapproved_images_rejected(image):
    with pytest.raises(ImageOverrideError):
        build_image_override(Path("/srv/nexdeck"), image)


def test_relative_directory_rejected():
    with pytest.raises(ImageOverrideError):
        build_image_override(
            Path("nexdeck"),
            "ghcr.io/derkezorm/nexdeck:1.8.0",
        )


def test_immutable_docker_image_id():
    image_id = "sha256:" + "a" * 64

    result = build_image_override(
        Path("/srv/nexdeck"),
        image_id,
    )

    assert f"image: {image_id}" in result.content
    assert "pull_policy: never" in result.content


@pytest.mark.parametrize("image_id", [
    "sha256:",
    "sha256:" + "a" * 63,
    "sha256:" + "a" * 65,
    "sha256:" + "g" * 64,
    "sha256:" + "A" * 64,
    "sha256:" + "a" * 64 + "\\nprivileged: true",
])
def test_invalid_docker_image_ids_rejected(image_id):
    with pytest.raises(ImageOverrideError):
        build_image_override(
            Path("/srv/nexdeck"),
            image_id,
        )
