"""Resolve the latest stable official NexDeck release."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from urllib.request import Request, urlopen


RELEASE_URL = (
    "https://api.github.com/repos/DerKezorm/nexdeck/releases/latest"
)

IMAGE_REPOSITORY = "ghcr.io/derkezorm/nexdeck"

VERSION_PATTERN = re.compile(
    r"v?([0-9]+)\.([0-9]+)\.([0-9]+)\Z"
)


class ReleaseResolutionError(RuntimeError):
    """Latest stable release could not be resolved safely."""


@dataclass(frozen=True)
class LatestRelease:
    version: str
    tag: str
    image_repository: str

    @property
    def image_reference(self) -> str:
        """Official version-specific image, never a moving latest tag."""
        return f"{self.image_repository}:{self.version}"


def parse_latest_release(payload: dict) -> LatestRelease:
    if not isinstance(payload, dict):
        raise ReleaseResolutionError("Invalid release response")

    if payload.get("draft") is not False:
        raise ReleaseResolutionError("Release is not published")

    if payload.get("prerelease") is not False:
        raise ReleaseResolutionError("Prerelease is not permitted")

    tag = payload.get("tag_name")

    if not isinstance(tag, str):
        raise ReleaseResolutionError("Missing release tag")

    match = VERSION_PATTERN.fullmatch(tag)

    if not match:
        raise ReleaseResolutionError("Invalid stable release tag")

    return LatestRelease(
        version=".".join(match.groups()),
        tag=tag,
        image_repository=IMAGE_REPOSITORY,
    )


def resolve_latest_release(timeout: int = 15) -> LatestRelease:
    request = Request(
        RELEASE_URL,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "NexDeck-Update-Agent",
        },
    )

    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
    except (OSError, ValueError) as exc:
        raise ReleaseResolutionError(
            "Unable to retrieve latest stable release"
        ) from exc

    return parse_latest_release(payload)
