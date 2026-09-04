"""A small path language for the JSON API widget.

``data.items[0].name`` walks objects and lists, ``results[*].title`` collects
a value from every element, and ``$`` or an empty path means the root.
Deliberately tiny: it covers what people paste from their services without
pulling in a JSONPath engine.
"""

from __future__ import annotations

import re
from typing import Any

_TOKEN = re.compile(r"([^.\[\]]+)|\[(\*|-?\d+)\]")


class PathError(ValueError):
    pass


def tokenize(path: str) -> list[str | int | None]:
    path = path.strip()
    if path in ("", "$"):
        return []
    if path.startswith("$."):
        path = path[2:]
    tokens: list[str | int | None] = []
    position = 0
    for match in _TOKEN.finditer(path):
        if match.start() != position and path[position:match.start()] not in (".", ""):
            raise PathError(f"Cannot read the path near {path[position:match.start()]!r}.")
        if match.group(1) is not None:
            tokens.append(match.group(1))
        elif match.group(2) == "*":
            tokens.append(None)
        else:
            tokens.append(int(match.group(2)))
        position = match.end()
    if position != len(path):
        raise PathError(f"Cannot read the path near {path[position:]!r}.")
    return tokens


def extract(data: Any, path: str) -> Any:
    tokens = tokenize(path)
    return _walk(data, tokens)


def _walk(node: Any, tokens: list[str | int | None]) -> Any:
    if not tokens:
        return node
    head, rest = tokens[0], tokens[1:]
    if head is None:
        if not isinstance(node, list):
            raise PathError("Expected a list where [*] is used.")
        return [_walk(item, rest) for item in node]
    if isinstance(head, int):
        if not isinstance(node, list):
            raise PathError(f"Expected a list before [{head}].")
        try:
            return _walk(node[head], rest)
        except IndexError as error:
            raise PathError(f"The list has no element {head}.") from error
    if isinstance(node, dict):
        if head not in node:
            raise PathError(f"There is no field named {head!r}.")
        return _walk(node[head], rest)
    if isinstance(node, list) and head.isdigit():
        return _walk(node, [int(head), *rest])
    raise PathError(f"Cannot look up {head!r} in a {type(node).__name__}.")


def as_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.strip().replace(",", ".")
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None
