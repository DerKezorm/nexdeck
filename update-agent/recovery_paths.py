"""Shared path validation for NexDeck recovery attachments."""

from __future__ import annotations


ALLOWED_ATTACHMENT_DIRECTORIES = frozenset({
    "avatars",
    "uploads",
    "brand",
})


def valid_attachment_path(value: object) -> bool:
    """Accept a single safe filename in an approved directory."""

    if not isinstance(value, str):
        return False

    if (
        not value
        or "\\" in value
        or ":" in value
        or "\x00" in value
    ):
        return False

    parts = value.split("/")

    if len(parts) != 2:
        return False

    directory, filename = parts

    if directory not in ALLOWED_ATTACHMENT_DIRECTORIES:
        return False

    if not filename or filename in {".", ".."}:
        return False

    if any(ord(character) < 32 for character in filename):
        return False

    return True
