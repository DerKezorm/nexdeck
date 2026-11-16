"""Validation of explicitly registered NexDeck deployments.

This module performs no Docker operations and changes no files.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from manifest_security import (
    ManifestSecurityError,
    read_trusted_manifest,
)


_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")


class ManifestError(ValueError):
    """A deployment manifest is invalid or incomplete."""


@dataclass(frozen=True)
class Deployment:
    deployment_id: str
    compose_file: Path
    project_directory: Path
    project_name: str
    service_name: str
    container_name: str
    data_directory: Path


def load_manifest(path: Path) -> Deployment:
    """Read and validate a manifest (legacy, untrusted file access)."""

    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError, ValueError) as exc:
        raise ManifestError("Cannot read deployment manifest") from exc

    return parse_manifest_text(content)


def load_trusted_manifest(
    path: Path,
    expected_uid: int = 0,
) -> Deployment:
    """Securely read and validate an administrator-owned manifest."""

    try:
        content = read_trusted_manifest(
            path,
            expected_uid=expected_uid,
        )
    except ManifestSecurityError as exc:
        raise ManifestError(
            "Cannot securely read deployment manifest"
        ) from exc

    return parse_manifest_text(content)


def parse_manifest_text(content: str) -> Deployment:
    """Validate manifest content without accessing its source file."""

    try:
        document = json.loads(content)
    except (TypeError, ValueError) as exc:
        raise ManifestError("Cannot read deployment manifest") from exc

    if not isinstance(document, dict):
        raise ManifestError("Manifest must be a JSON object")

    required = (
        "deployment_id",
        "compose_file",
        "project_directory",
        "project_name",
        "service_name",
        "container_name",
        "data_directory",
    )

    for field in required:
        value = document.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ManifestError(f"Invalid or missing field: {field}")

    for field in ("deployment_id", "project_name", "service_name", "container_name"):
        value = document[field]
        if not _IDENTIFIER.fullmatch(value):
            raise ManifestError(f"Unsafe identifier: {field}")

    paths = {}

    for field in ("compose_file", "project_directory", "data_directory"):
        candidate = Path(document[field])

        if not candidate.is_absolute():
            raise ManifestError(f"Path must be absolute: {field}")

        if ".." in candidate.parts:
            raise ManifestError(f"Parent traversal is forbidden: {field}")

        if candidate != candidate.resolve(strict=False):
            raise ManifestError(f"Path is not canonical: {field}")

        current = Path(candidate.anchor)

        for component in candidate.parts[1:]:
            current = current / component

            if current.is_symlink():
                raise ManifestError(
                    f"Symbolic links are forbidden: {field}"
                )

        paths[field] = candidate

    return Deployment(
        deployment_id=document["deployment_id"],
        compose_file=paths["compose_file"],
        project_directory=paths["project_directory"],
        project_name=document["project_name"],
        service_name=document["service_name"],
        container_name=document["container_name"],
        data_directory=paths["data_directory"],
    )
