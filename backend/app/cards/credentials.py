"""Finding keys, tokens and passwords in a card definition.

A card is shared (the shop, an issue, a backup of the board) and carries no
credentials: the connection holds them and the server adds them to every
request. So a definition that has a value shaped like a secret, or a field
for headers, is refused and says why (KARTEN-1 AC-7).

⚠️ Two strengths. The structure of a card (everything outside ``demo``) is
searched thoroughly, field names included. Demo answers are what a service
really sends, and a service sends hashes, identifiers and fields called
``token`` that mean nothing; there only values that are unmistakably a
credential count, such as ``ghp_...`` or ``Bearer ...``.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

#: Field names compared after removing - _ and spaces.
_BAD_NAMES = frozenset(
    {
        "headers", "header", "authorization", "auth", "cookie", "cookies", "credentials", "bearer",
        "token", "accesstoken", "apikey", "password", "passwd", "secret", "clientsecret", "privatekey",
    }
)  # fmt: skip
_BAD_ENDINGS = ("token", "password", "passwd", "secret", "apikey", "cookie")

#: Shapes that are a credential wherever they stand.
_STRONG = (
    ("a bearer or basic authorization", re.compile(r"\b(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE)),
    ("a GitHub or GitLab token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|glpat-[A-Za-z0-9_-]{16,})")),
    ("an API key of the sk- kind", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}")),
    ("a Slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("an AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("a Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("a JSON web token", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]*")),
    ("a private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("a user name and password in an address", re.compile(r"://[^/\s:@]+:[^/\s@]+@")),
)  # fmt: skip
#: Shapes that only count in the structure of the card, where a service did not put them.
_STRUCTURE = (
    ("a long hexadecimal key", re.compile(r"(?<![0-9A-Za-z])(?=[0-9a-fA-F]*\d)[0-9a-fA-F]{32,}(?![0-9A-Za-z])")),
    (
        "a key, token or password in the query of an address",
        re.compile(r"[?&;](?:api[_-]?key|apikey|access[_-]?token|token|password|passwd|secret|auth|authorization)=(?!\{)[^&\s]+", re.IGNORECASE),
    ),
)  # fmt: skip
_RUN = re.compile(r"[A-Za-z0-9+/_=-]{32,}")


@dataclass(frozen=True)
class Found:
    """Where it stands (``path`` as in ``requests[0].path``) and what it looks like."""

    path: tuple[str | int, ...]
    code: str
    what: str


def _name(key: str) -> str:
    return re.sub(r"[-_ ]", "", key.lower())


def bad_name(key: str) -> bool:
    name = _name(key)
    return name in _BAD_NAMES or name.endswith(_BAD_ENDINGS)


def _looks_like_a_key(text: str) -> bool:
    """A whole value of one run of key characters with letters and digits in it; a word or a path is not."""
    return bool(_RUN.fullmatch(text)) and any(c.isdigit() for c in text) and any(c.isalpha() for c in text)


def _value(text: str, *, structure: bool) -> str | None:
    for what, pattern in _STRONG:
        if pattern.search(text):
            return what
    if structure:
        for what, pattern in _STRUCTURE:
            if pattern.search(text):
                return what
        if _looks_like_a_key(text.strip()):
            return "a long key or token"
    return None


def find(data: Any, path: tuple[str | int, ...] = (), *, demo: bool = False) -> Iterator[Found]:
    """Everything in a parsed definition that is or asks for a secret."""
    if isinstance(data, dict):
        for key, child in data.items():
            here = (*path, key)
            inside_demo = demo or (not path and key == "demo")
            if isinstance(key, str) and not inside_demo and bad_name(key):
                what = "a field for headers" if _name(key) in ("headers", "header", "cookie", "cookies") else f"a field called {key}"
                yield Found(here, "card_secret_field", what)
            yield from find(child, here, demo=inside_demo)
    elif isinstance(data, list):
        for index, child in enumerate(data):
            yield from find(child, (*path, index), demo=demo)
    elif isinstance(data, str):
        what = _value(data, structure=not demo)
        if what:
            yield Found(path, "card_secret_value", what)
