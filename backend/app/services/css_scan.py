"""What a style sheet would fetch, read the way a browser reads it.

The look's own style sheet was checked with patterns on its text, and a
browser does not read text, it reads tokens. ``\\75 rl(https://…)`` is
``url(`` once the escape is decoded, and ``image-set("https://…")`` fetches
without the word url anywhere; both went past the patterns. So the sheet is
tokenised with tinycss2, which decodes escapes as the CSS syntax spec says,
and every token that would fetch is looked at: an address, a function that
takes one, an @import. Only a data: address fetches nothing and passes.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator

import tinycss2
from tinycss2 import ast

#: Functions that fetch the address they are given: ``url`` and ``src`` take one, the image functions a list.
FETCHING = frozenset({"url", "src", "image", "image-set", "-webkit-image-set", "cross-fade", "-webkit-cross-fade"})
#: Functions that hand a function above them a value from elsewhere. Inside one that fetches, that value is an
#: address nobody can read here: ``--x: "https://…"`` and ``src(var(--x))`` fetch it.
INDIRECT = frozenset({"var", "env", "attr"})


def _local(address: str) -> bool:
    return address.strip().lower().startswith("data:")


def _walk(nodes: Iterable[ast.Node] | None) -> Iterator[ast.Node]:
    for node in nodes or ():
        yield node
        for inner in (getattr(node, "prelude", None), getattr(node, "content", None), getattr(node, "arguments", None)):
            if isinstance(inner, list):
                yield from _walk(inner)


def _fetching(function: ast.FunctionBlock) -> str | None:
    """Every string anywhere inside is an address to it, also one an ``if()`` picks; each must be data:."""
    name = function.lower_name
    for node in _walk(function.arguments):
        if isinstance(node, ast.FunctionBlock) and node.lower_name in INDIRECT:
            return f"{name}() may only hold a data: address written out, not {node.lower_name}()."
        if isinstance(node, ast.StringToken) and not _local(node.value):
            return f"{name}() fetches from somewhere else; only data: is allowed here."
    return None


def what_fetches(css: str) -> str | None:
    """Why the sheet would fetch something, or None when it fetches nothing."""
    for node in _walk(tinycss2.parse_stylesheet(css, skip_comments=True, skip_whitespace=True)):
        if isinstance(node, ast.AtRule) and node.lower_at_keyword == "import":
            return "@import fetches a file from somewhere else; put the style sheet in here instead."
        if isinstance(node, ast.URLToken) and not _local(node.value):
            return "url() fetches from somewhere else; only data: is allowed here."
        if isinstance(node, ast.ParseError) and node.kind == "bad-url":
            # A browser drops an address it cannot read; refused all the same, so nothing rests on that.
            return "url() holds an address a browser cannot read."
        if isinstance(node, ast.FunctionBlock) and node.lower_name in FETCHING and (why := _fetching(node)):
            return why
    return None
