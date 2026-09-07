"""Reading an uploaded file without trusting how big it says it is.

⚠️ ``await file.read()`` with no argument loads the whole thing into memory,
and the size check that follows happens when the damage is done. The middleware
in ``main.py`` weighs ``Content-Length`` before anything is read, which covers
every ordinary client; this is the other half, for a body that arrives without
one. Chunked transfer encoding has no length to declare, and nothing stops a
client from using it.
"""

from __future__ import annotations

from fastapi import UploadFile, status

from .deps import error

#: Read this much at a time. Large enough that a 12 MB picture is a handful of
#: reads, small enough that a refused upload costs nothing worth counting.
CHUNK = 1024 * 1024


async def read_at_most(file: UploadFile, limit: int, what: str = "file") -> bytes:
    """The file's bytes, or a 413 as soon as the count passes ``limit``.

    The refusal comes at the first block over the line, not after the whole
    body has arrived, so what a client can spend is the limit plus one block.
    """
    chunks: list[bytes] = []
    seen = 0
    while True:
        piece = await file.read(CHUNK)
        if not piece:
            break
        seen += len(piece)
        if seen > limit:
            raise error(
                "too_large",
                f"The {what} is larger than {limit // (1024 * 1024)} MB.",
                status.HTTP_413_CONTENT_TOO_LARGE,
            )
        chunks.append(piece)
    return b"".join(chunks)
