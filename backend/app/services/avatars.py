"""Profile pictures: check the bytes, store the file, hand it back.

Kept apart from the general uploads on purpose. An avatar belongs to one
account, it replaces the one before it, and it goes when the account goes;
listing it among the board backgrounds would only be in the way.

The file name is random, so a new picture is a new address: no browser keeps
showing the old one, and nobody can guess who has which file.
"""

from __future__ import annotations

import secrets
from pathlib import Path

from ..config import get_settings

#: Two megabytes. A picture shown at 32 pixels needs nothing near that.
MAX_BYTES = 2 * 1024 * 1024

#: First bytes to extension and content type. The name a browser sends is not
#: evidence, the bytes are. SVG is missing on purpose: it can carry script.
SIGNATURES: tuple[tuple[bytes, str, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "png", "image/png"),
    (b"\xff\xd8\xff", "jpg", "image/jpeg"),
    (b"GIF87a", "gif", "image/gif"),
    (b"GIF89a", "gif", "image/gif"),
)


class AvatarError(Exception):
    """Something about the picture is wrong; the router turns it into an answer."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def directory() -> Path:
    path = get_settings().data_dir / "avatars"
    path.mkdir(parents=True, exist_ok=True)
    return path


def detect(data: bytes) -> tuple[str, str]:
    """Extension and content type from the first bytes."""
    for magic, suffix, content_type in SIGNATURES:
        if data.startswith(magic):
            return suffix, content_type
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp", "image/webp"
    raise AvatarError("bad_type", "Only PNG, JPEG, GIF and WebP pictures are accepted.")


def save(data: bytes, previous: str = "") -> str:
    """Store the picture and return its file name. The old one is removed."""
    if not data:
        raise AvatarError("empty", "The file is empty.")
    if len(data) > MAX_BYTES:
        raise AvatarError("too_large", "The picture is larger than 2 MB.")
    suffix, _ = detect(data)
    name = f"{secrets.token_hex(16)}.{suffix}"
    (directory() / name).write_bytes(data)
    remove(previous)
    return name


def remove(name: str) -> None:
    """Delete a stored picture. Without this, replacing one leaves it behind."""
    if not name:
        return
    path = directory() / Path(name).name  # cut any path parts off the name
    path.unlink(missing_ok=True)


def read(name: str) -> tuple[bytes, str]:
    """Load a stored picture. The name comes from the database and is still
    reduced to its last part, against tricks like ``../``."""
    path = directory() / Path(name).name
    if not path.is_file():
        raise AvatarError("not_found", "There is no such picture.")
    data = path.read_bytes()
    _, content_type = detect(data)
    return data, content_type


def url_for(name: str) -> str | None:
    """The address the app puts into an image tag, or None without a picture."""
    return f"/api/v1/avatars/{name}" if name else None
