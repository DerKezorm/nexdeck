"""Generate restricted, version-pinned NexDeck Compose overrides."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


_IMAGE = re.compile(
    r"(?:"
    r"(?:ghcr\.io/derkezorm/nexdeck|nexdeck-updater-realtest)"
    r"(?::[0-9]+\.[0-9]+\.[0-9]+|@sha256:[0-9a-f]{64})"
    r"|sha256:[0-9a-f]{64}"
    r")\Z"
)


class ImageOverrideError(ValueError):
    """Invalid managed NexDeck image override."""


@dataclass(frozen=True)
class ImageOverride:
    path: Path
    content: str


def build_image_override(
    project_directory: Path,
    image_reference: str,
) -> ImageOverride:
    """Build a minimal Compose override for an approved NexDeck image."""

    if not isinstance(project_directory, Path):
        raise ImageOverrideError("Invalid project directory")

    if not project_directory.is_absolute():
        raise ImageOverrideError("Project directory must be absolute")

    if ".." in project_directory.parts:
        raise ImageOverrideError("Parent traversal is forbidden")

    if (
        not isinstance(image_reference, str)
        or not _IMAGE.fullmatch(image_reference)
    ):
        raise ImageOverrideError("Unapproved NexDeck image reference")

    return ImageOverride(
        path=project_directory / ".nexdeck-updater" / "image.override.yaml",
        content=(
            "services:\n"
            "  nexdeck:\n"
            f"    image: {image_reference}\n"
            "    pull_policy: never\n"
        ),
    )
