from pathlib import Path

import pytest

from image_override import build_image_override
from managed_override import (
    ManagedOverrideError,
    write_managed_override,
)


def test_writes_override(tmp_path):
    override = build_image_override(
        tmp_path,
        "ghcr.io/derkezorm/nexdeck:1.8.0",
    )

    result = write_managed_override(override)

    assert result.exists()
    assert result.read_text() == override.content
    assert result.stat().st_mode & 0o777 == 0o600


def test_replaces_existing_override(tmp_path):
    first = build_image_override(
        tmp_path,
        "ghcr.io/derkezorm/nexdeck:1.7.0",
    )
    second = build_image_override(
        tmp_path,
        "ghcr.io/derkezorm/nexdeck:1.8.0",
    )

    write_managed_override(first)
    write_managed_override(second)

    assert second.path.read_text() == second.content


def test_rejects_symlink_override(tmp_path):
    override = build_image_override(
        tmp_path,
        "ghcr.io/derkezorm/nexdeck:1.8.0",
    )

    override.path.parent.mkdir()
    target = tmp_path / "target.yaml"
    target.write_text("protected")
    override.path.symlink_to(target)

    with pytest.raises(ManagedOverrideError):
        write_managed_override(override)

    assert target.read_text() == "protected"


def test_rejects_symlink_directory(tmp_path):
    override = build_image_override(
        tmp_path,
        "ghcr.io/derkezorm/nexdeck:1.8.0",
    )

    other = tmp_path / "other"
    other.mkdir()
    override.path.parent.symlink_to(other, target_is_directory=True)

    with pytest.raises(ManagedOverrideError):
        write_managed_override(override)
