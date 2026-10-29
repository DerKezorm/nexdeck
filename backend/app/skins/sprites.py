"""Sprites drawn as pictures the browser needs nothing else for.

A sprite is rows of characters; it becomes an SVG of one ``<rect>`` per run
of the same colour in a row, with crisp edges, as a ``data:`` address. SVG
rather than a PNG made in the browser: the same sprite gives the same bytes
on the server, in a test and in every browser, and nothing has to be drawn
before the page is.
"""

from __future__ import annotations

from urllib.parse import quote

from .schema import Sprite

#: Status symbols must differ in shape, not only in colour: at least this share of their pixels.
LEAST_DIFFERENCE = 0.15


def svg(sprite: Sprite) -> str:
    width, height = len(sprite.rows[0]), len(sprite.rows)
    rects = []
    for y, row in enumerate(sprite.rows):
        x = 0
        while x < width:
            char = row[x]
            run = 1
            while x + run < width and row[x + run] == char:
                run += 1
            if char != ".":
                fill = "#000" if sprite.tint else sprite.palette[char]
                rects.append(f'<rect x="{x}" y="{y}" width="{run}" height="1" fill="{fill}"/>')
            x += run
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
        f'shape-rendering="crispEdges">{"".join(rects)}</svg>'
    )


def address(sprite: Sprite) -> str:
    return "data:image/svg+xml," + quote(svg(sprite), safe="=:/, ")


def shape(sprite: Sprite) -> set[tuple[int, int]]:
    return {(x, y) for y, row in enumerate(sprite.rows) for x, char in enumerate(row) if char != "."}


def too_alike(first: Sprite, second: Sprite) -> bool:
    """Whether two symbols could only be told apart by their colours."""
    one, other = shape(first), shape(second)
    union = one | other
    if not union:
        return True
    return len(one ^ other) / len(union) < LEAST_DIFFERENCE
