"""The answer of a service as a tree an editor can show, with the path of every node (KARTEN-9 AC-3, EC-1).

The tree is cut, never the answer: at most ``MAX_NODES`` nodes, ``ARRAY_SHOWN`` entries of a list (every entry of a list
has the same fields, so the first few show them all) and ``OBJECT_SHOWN`` fields of an object. What is left out is
counted in ``more``. Texts are clipped to ``TEXT_SHOWN`` characters. The tree is built level by level, so a long list
near the top cannot use up the nodes the fields beneath its neighbours need.

⚠️ Three more limits keep a hostile or odd answer from becoming a failure or a flood: nothing deeper than ``MAX_DEPTH``
levels is opened (the answer cannot be written out as JSON far below that), a name is clipped like a text, and a node
whose path has grown past ``MAX_PATH`` characters is not opened (every node carries the whole path of its way). Text
that cannot be written as UTF-8, a lone surrogate half that JSON allows, carries a replacement mark instead.

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
#: The longest text of a value or a name, in characters.
TEXT_SHOWN = 200
#: Levels below the root that are opened; deeper is counted in ``more``.
MAX_DEPTH = 30
#: A node whose path is longer than this has no children shown.
MAX_PATH = 1000

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def clean(text: str) -> str:
    """The text with what UTF-8 cannot hold (a lone surrogate half) replaced by a mark."""
    return text.encode("utf-8", "replace").decode("utf-8")


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
    if isinstance(value, str):
        node["value"] = clean(value[:TEXT_SHOWN])
        if len(value) > TEXT_SHOWN:
            node["truncated"] = True
    elif kind != "null":
        node["value"] = value
    return node


def build(answer: Any) -> dict[str, Any]:
    """``{tree, nodes, cut}`` for an answer: ``cut`` says that something was left out."""
    root = _node(None, "@", answer)
    count = 1
    cut = False
    queue: deque[tuple[dict[str, Any], Any, int]] = deque([(root, answer, 0)])
    while queue:
        node, value, depth = queue.popleft()
        if isinstance(value, list):
            wanted = list(enumerate(value[:ARRAY_SHOWN]))
            total = len(value)
        elif isinstance(value, dict):
            wanted = list(value.items())[:OBJECT_SHOWN]
            total = len(value)
        else:
            continue
        room = max(0, MAX_NODES - count) if depth < MAX_DEPTH and len(node["path"]) <= MAX_PATH else 0
        shown = wanted[:room]
        children = []
        for key, child in shown:
            if isinstance(value, list):
                path, name = _entry(node["path"], key), key
            else:
                name = clean(str(key))[:TEXT_SHOWN]
                path = _field(node["path"], name)
            made = _node(name, path, child)
            children.append(made)
            queue.append((made, child, depth + 1))
        count += len(children)
        if children:
            node["children"] = children
        if total > len(children):
            node["more"] = total - len(children)
            cut = True
    return {"tree": root, "nodes": count, "cut": cut}
