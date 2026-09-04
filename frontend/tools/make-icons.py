"""Render the app icon as PNG in the sizes the web manifest needs.

Pure Python, no Pillow: the mark is three rounded cards and a dot, drawn with
signed-distance functions and written as an RGBA PNG.

    python tools/make-icons.py
"""

from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
PUBLIC = HERE.parent / "public"


def rounded_rect(px: float, py: float, x: float, y: float, w: float, h: float, r: float) -> float:
    """Signed distance to a rounded rectangle (negative inside)."""
    cx, cy = x + w / 2, y + h / 2
    qx, qy = abs(px - cx) - (w / 2 - r), abs(py - cy) - (h / 2 - r)
    outside = math.hypot(max(qx, 0), max(qy, 0))
    inside = min(max(qx, qy), 0)
    return outside + inside - r


def coverage(distance: float, scale: float) -> float:
    """Anti-aliasing: full inside, soft edge of about one pixel."""
    return max(0.0, min(1.0, 0.5 - distance * scale))


def lerp(a: tuple[float, ...], b: tuple[float, ...], t: float) -> tuple[float, ...]:
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(len(a)))


def blend(dest: list[float], colour: tuple[float, float, float], alpha: float) -> None:
    if alpha <= 0:
        return
    dest[0] = dest[0] * (1 - alpha) + colour[0] * alpha
    dest[1] = dest[1] * (1 - alpha) + colour[1] * alpha
    dest[2] = dest[2] * (1 - alpha) + colour[2] * alpha
    dest[3] = dest[3] * (1 - alpha) + 255 * alpha


def render(size: int, maskable: bool = False) -> bytes:
    scale = size / 32.0
    rows = []
    for j in range(size):
        row = bytearray()
        for i in range(size):
            px, py = (i + 0.5) / scale, (j + 0.5) / scale
            pixel = [0.0, 0.0, 0.0, 0.0]
            # Tile.
            tile = rounded_rect(px, py, 1.5, 1.5, 29, 29, 8.5) if not maskable else rounded_rect(px, py, -4, -4, 40, 40, 0)
            blend(pixel, (15, 20, 32), coverage(tile, scale))
            # Back and middle cards.
            blend(pixel, (34, 211, 238), coverage(rounded_rect(px, py, 11, 7.5, 14, 9, 2.2), scale) * 0.22)
            t = (px - 8.5) / 14
            blend(pixel, lerp((34, 211, 238), (14, 116, 144), max(0, min(1, t))), coverage(rounded_rect(px, py, 8.5, 11, 14, 9, 2.2), scale) * 0.55)
            # Front card with gradient.
            t = max(0.0, min(1.0, ((px - 6) + (py - 14.5)) / 23))
            colour = lerp((165, 243, 252), (34, 211, 238), min(1, t / 0.55)) if t < 0.55 else lerp((34, 211, 238), (8, 145, 178), (t - 0.55) / 0.45)
            blend(pixel, colour, coverage(rounded_rect(px, py, 6, 14.5, 14, 9, 2.2), scale))
            # Value line on the front card: a polyline as thick segments.
            line = ((8.5, 21.2), (10.9, 18.9), (12.9, 20.3), (15.2, 17.2), (17.5, 18.8))
            best = 99.0
            for (ax, ay), (bx, by) in zip(line, line[1:]):
                dx, dy = bx - ax, by - ay
                u = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
                best = min(best, math.hypot(px - (ax + u * dx), py - (ay + u * dy)))
            blend(pixel, (6, 42, 51), coverage(best - 0.65, scale))
            # Live dot and halo.
            dot = math.hypot(px - 24.6, py - 8.2)
            blend(pixel, (34, 211, 238), coverage(abs(dot - 4.4) - 0.5, scale) * 0.35)
            blend(pixel, (34, 211, 238), coverage(dot - 2.4, scale))
            row += bytes(int(round(c)) for c in pixel)
        rows.append(bytes([0]) + bytes(row))
    raw = b"".join(rows)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


if __name__ == "__main__":
    PUBLIC.mkdir(exist_ok=True)
    (PUBLIC / "icon-192.png").write_bytes(render(192))
    (PUBLIC / "icon-512.png").write_bytes(render(512))
    (PUBLIC / "apple-touch-icon.png").write_bytes(render(180))
    (PUBLIC / "icon-maskable-512.png").write_bytes(render(512, maskable=True))
    print("icons written to", PUBLIC)
