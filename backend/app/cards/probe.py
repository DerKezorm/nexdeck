"""The answer of a service as a tree an editor can show, with the path of every node (KARTEN-9 AC-3, EC-1).

The tree is cut, never the answer: at most ``MAX_NODES`` nodes, ``ARRAY_SHOWN`` entries of a list (every entry of a list
has the same fields, so the first few show them all) and ``OBJECT_SHOWN`` fields of an object. What is left out is
counted in ``more``. Texts are clipped to ``TEXT_SHOWN`` characters. The tree is built level by level, so a long list
near the top cannot use up the nodes the fields beneath its neighbours need.

⚠️ The path of a node is JMESPath from the root and is what the editor writes into the definition. A name that is not a
plain identifier goes in double quotes the way JMESPath reads them (a JSON string), so a field called ``a b``, ``1x`` or
``x.y`` finds exactly its own value. The root itself is ``@``.
"""

from __future__ import annotations

import json
import re
from collections import deque
from typing import Any

#: The most nodes in one tree (KARTEN-9 EC-1).
MAX_NODES = 500
#: The entries of a list that are shown; the rest is ``more``.
ARRAY_SHOWN = 10
#: The fields of an object that are shown; the rest is ``more``.
OBJECT_SHOWN = 200
#: The longest text of a value, in characters.
TEXT_SHOWN = 200

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _field(parent: str, key: str) -> str:
    name = key if _IDENTIFIER.match(key) else json.dumps(key, ensure_ascii=False)
    return name if parent == "@" else f"{parent}.{name}"


def _entry(parent: str, index: int) -> str:
    return f"{'' if parent == '@' else parent}[{index}]"


def _type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int | float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    return "object"


def _node(key: str | int | None, path: str, value: Any) -> dict[str, Any]:
    kind = _type(value)
    node: dict[str, Any] = {"key": key, "path": path, "type": kind}
    if kind in ("object", "array"):
        return node
    if isinstance(value, str) and len(value) > TEXT_SHOWN:
        node["value"] = value[:TEXT_SHOWN]
        node["truncated"] = True
    elif kind != "null":
        node["value"] = value
    return node


def build(answer: Any) -> dict[str, Any]:
    """``{tree, nodes, cut}`` for an answer: ``cut`` says that something was left out."""
    root = _node(None, "@", answer)
    count = 1
    cut = False
    queue: deque[tuple[dict[str, Any], Any]] = deque([(root, answer)])
    while queue:
        node, value = queue.popleft()
        if isinstance(value, list):
            wanted = list(enumerate(value[:ARRAY_SHOWN]))
            total = len(value)
        elif isinstance(value, dict):
            wanted = list(value.items())[:OBJECT_SHOWN]
            total = len(value)
        else:
            continue
        room = max(0, MAX_NODES - count)
        shown = wanted[:room]
        children = []
        for key, child in shown:
            path = _entry(node["path"], key) if isinstance(value, list) else _field(node["path"], str(key))
            made = _node(key, path, child)
            children.append(made)
            queue.append((made, child))
        count += len(children)
        if children:
            node["children"] = children
        if total > len(children):
            node["more"] = total - len(children)
            cut = True
    return {"tree": root, "nodes": count, "cut": cut}
