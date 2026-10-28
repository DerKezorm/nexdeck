"""The files an entry points at: its definition, its texts and its pictures, fetched through the server (KARTEN-14).

The browser never talks to GitHub: a picture comes from a route of this server, which keeps it for a while. A definition is
fetched only after the catalog said which checksum it has, and is used only when it has exactly that (EC-1).
"""

from __future__ import annotations

import hashlib
from collections import OrderedDict
from dataclasses import dataclass

from ..cards import schema
from . import catalog

#: What each kind of file may weigh.
MAX_DEFINITION = schema.MAX_DEFINITION * 4
MAX_TEXT = 256 * 1024
MAX_IMAGE = 3 * 1024 * 1024
#: How long a text and a picture are kept, in seconds; a definition is named by its checksum and never goes stale.
TEXT_FOR = 600
IMAGE_FOR = 3600
#: At most this many files and this many bytes are kept.
MAX_FILES = 400
MAX_BYTES = 96 * 1024 * 1024
PNG = b"\x89PNG\r\n\x1a\n"


@dataclass
class _Kept:
    at: float
    body: bytes
    #: ``None``: never goes stale.
    keep_for: float | None


_files: OrderedDict[tuple[str, str, str], _Kept] = OrderedDict()


def forget() -> None:
    _files.clear()


def _get(key: tuple[str, str, str]) -> bytes | None:
    kept = _files.get(key)
    if kept is None:
        return None
    if kept.keep_for is not None and catalog.now() - kept.at >= kept.keep_for:
        del _files[key]
        return None
    _files.move_to_end(key)
    return kept.body


def _put(key: tuple[str, str, str], body: bytes, keep_for: float | None) -> None:
    _files[key] = _Kept(catalog.now(), body, keep_for)
    _files.move_to_end(key)
    while len(_files) > MAX_FILES or sum(len(one.body) for one in _files.values()) > MAX_BYTES:
        _files.popitem(last=False)


async def definition(repo: str, entry: catalog.Entry) -> str:
    """The text of ``definition.yaml``, which has the checksum the catalog names, or ``CatalogError`` (EC-1)."""
    key = (repo, entry.files.definition, entry.sha256)
    body = _get(key)
    if body is None:
        body = await catalog.fetch(repo, entry.files.definition, MAX_DEFINITION)
        if hashlib.sha256(body).hexdigest() != entry.sha256:
            raise catalog.CatalogError(
                "checksum_mismatch",
                "The file does not match the checksum of the catalog, so it was not used. It may have been changed after it was listed.",
                409,
            )
        _put(key, body, None)
    try:
        return body.decode("utf-8")
    except UnicodeDecodeError:
        raise catalog.CatalogError("catalog_invalid", "The definition of this entry is not text.") from None


async def text(repo: str, path: str | None) -> str | None:
    """A text file of an entry (description, list of changes), or ``None`` when the entry has none."""
    if path is None:
        return None
    key = (repo, path, "text")
    body = _get(key)
    if body is None:
        body = await catalog.fetch(repo, path, MAX_TEXT)
        _put(key, body, TEXT_FOR)
    return body.decode("utf-8", errors="replace")


async def image(repo: str, path: str | None) -> bytes | None:
    """A picture of an entry, or ``None`` when it has none (or what came is not a PNG)."""
    if path is None:
        return None
    key = (repo, path, "image")
    body = _get(key)
    if body is None:
        body = await catalog.fetch(repo, path, MAX_IMAGE)
        if not body.startswith(PNG):
            return None
        _put(key, body, IMAGE_FOR)
    return body
