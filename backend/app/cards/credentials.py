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
_BAD_ENDINGS = ("cookie",)
#: Parts of a name that make it a credential wherever they stand in it: ``X-Api-Key``, ``refresh_token``, ``db_password``.
_BAD_PARTS = ("token", "password", "passwd", "secret", "apikey")

#: Shapes that are a credential wherever they stand.
_STRONG = (
    ("bearer", re.compile(r"\b(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE)),
    ("git_token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|glpat-[A-Za-z0-9_-]{16,})")),
    ("sk_key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}")),
    ("slack_token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("aws_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("google_key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]*")),
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("address_password", re.compile(r"://[^/\s:@]+:[^/\s@]+@")),
)  # fmt: skip
#: Shapes that only count in the structure of the card, where a service did not put them.
_STRUCTURE = (
    ("hex_key", re.compile(r"(?<![0-9A-Za-z])(?=[0-9a-fA-F]*\d)[0-9a-fA-F]{32,}(?![0-9A-Za-z])")),
    (
        "query_secret",
        re.compile(
            r"[?&;](?:[\w-]*(?:token|secret|passw(?:or)?d|pwd|api[_-]?key)[\w-]*|key|sid|sessionid|jwt|auth|authorization)=(?!\{)[^&\s]+",
            re.IGNORECASE,
        ),
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
    return name in _BAD_NAMES or name.endswith(_BAD_ENDINGS) or any(part in name for part in _BAD_PARTS)


def _word_like(part: str) -> bool:
    return 2 <= len(part) <= 15 and part.isalpha() and part.islower()


def _looks_like_a_key(text: str) -> bool:
    """A whole value of one run of key characters with letters and digits in it, which does not read as words.

    ⚠️ A slug (``my-long-card-name-for-the-queue-2``) and a path (``/api/v3/series/lookup/term/something/long``) are
    made of words between separators, a key is not: when most of the parts are lower-case words it is not a key.
    """
    if not (_RUN.fullmatch(text) and any(c.isdigit() for c in text) and any(c.isalpha() for c in text)):
        return False
    parts = [part for part in re.split(r"[-_/]", text) if part]
    return len(parts) < 3 or sum(_word_like(part) for part in parts) * 2 < len(parts)


def _value(text: str, *, structure: bool) -> str | None:
    for what, pattern in _STRONG:
        if pattern.search(text):
            return what
    if structure:
        for what, pattern in _STRUCTURE:
            if pattern.search(text):
                return what
        if _looks_like_a_key(text.strip()):
            return "long_key"
    return None


#: What each code stands for, in English (the interface has its own words for them).
PHRASES = {
    "bearer": "a bearer or basic authorization",
    "git_token": "a GitHub or GitLab token",
    "sk_key": "an API key of the sk- kind",
    "slack_token": "a Slack token",
    "aws_key": "an AWS access key",
    "google_key": "a Google API key",
    "jwt": "a JSON web token",
    "private_key": "a private key",
    "address_password": "a user name and password in an address",
    "hex_key": "a long hexadecimal key",
    "query_secret": "a key, token or password in the query of an address",
    "long_key": "a long key or token",
    "headers": "a field for headers",
    "field": "a field that holds a credential",
}


def find(data: Any, path: tuple[str | int, ...] = (), *, demo: bool = False) -> Iterator[Found]:
    """Everything in a parsed definition that is or asks for a secret."""
    if isinstance(data, dict):
        for key, child in data.items():
            here = (*path, key)
            inside_demo = demo or (not path and key == "demo")
            if isinstance(key, str) and not inside_demo and bad_name(key):
                yield Found(here, "card_secret_field", "headers" if _name(key) in ("headers", "header", "cookie", "cookies") else "field")
            yield from find(child, here, demo=inside_demo)
    elif isinstance(data, list):
        for index, child in enumerate(data):
            yield from find(child, (*path, index), demo=demo)
    elif isinstance(data, str):
        what = _value(data, structure=not demo)
        if what:
            yield Found(path, "card_secret_value", what)


#: Parts of a key in demo answers that say its value grants access (S3), upper or lower case, wherever they stand.
ACCESS_KEYS = (
    "apikey", "api_key", "token", "secret", "password", "passwd", "authorization", "cookie", "session", "private_key",
    "client_secret", "access_key",
)  # fmt: skip
#: What stands in demo answers where a credential was: the mark of a hidden value, dots, ``xxx…``, ``<…>``.
HIDDEN = "[hidden]"
_DOTS = re.compile(r"[.…•*]+")


def access_key(key: str) -> bool:
    lowered = key.lower()
    return any(part in lowered for part in ACCESS_KEYS)


def placeholder(text: str) -> bool:
    """A value that is obviously no credential but stands in for one."""
    text = text.strip()
    return (
        not text or text == HIDDEN or bool(_DOTS.fullmatch(text)) or text.lower().startswith("xxx")
        or (text.startswith("<") and text.endswith(">"))
    )


def demo_secrets(demo: Any, known: frozenset[str] | set[str] = frozenset()) -> list[tuple[str, str]]:
    """``(place, key)`` of every value in demo answers that is a credential, never the value itself (S3).

    ⚠️ A value under a key that sounds like access (:data:`ACCESS_KEYS`) that is not empty, null or a placeholder, and any
    value that is a credential of a connection of this installation (``known``), whatever its key. Demo answers are
    copied from a probe, and a service names its own key in some of them: shared, they would stand in a public issue.
    """
    found: list[tuple[str, str]] = []

    def walk(value: Any, place: str, key: str) -> None:
        if isinstance(value, dict):
            for name, child in value.items():
                walk(child, f"{place}.{name}", str(name))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, f"{place}[{index}]", key)
        elif value is None or isinstance(value, bool):
            return
        elif isinstance(value, str | int | float):
            text = str(value)
            if (access_key(key) and not placeholder(text)) or text.strip() in known:
                found.append((place, key))

    if isinstance(demo, dict):
        for name, answer in demo.items():
            walk(answer, f"demo.{name}", "")
    return found
