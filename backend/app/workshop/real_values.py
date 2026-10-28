"""What the last probes of an administrator brought back, kept to warn when demo data look like the real thing (KARTEN-16 EC-4).

A card is shared with its demo data, and demo data are public. An author who took a probe over into them may have left
a name, an address or a title of his own in. So the texts of the last probes are remembered here, for this administrator
only, and compared with the demo data of a card when he is about to share it.

⚠️ Only texts, only in memory, only for a day, and never in an answer except the place and the text that matched: the
raw answer of a service goes to the administrator who asked and nowhere else (KARTEN-9 EC-4). A restart forgets them.
"""

from __future__ import annotations

import re
import time
from collections import deque
from typing import Any

from . import state

#: How many probes are remembered for one administrator, how long, and how many texts of each.
KEEP_PROBES = 5
KEEP_SECONDS = 24 * 3600
MAX_TEXTS = 3000
#: Shorter texts ("ok", "up", "1") are too common to say anything.
MIN_LENGTH = 4
MAX_DEPTH = 12
#: An address or a name found inside a text is kept apart from the whole texts by this sign in front of it.
ID = "\x00"
_OCTET = r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)"
_HEX = r"[0-9a-f]{1,4}"
#: What tells an administrator's own server from a demo: IPv4 and IPv6 addresses, e-mail addresses, host names (EC-4).
IPV4 = re.compile(rf"(?<![\w.]){_OCTET}(?:\.{_OCTET}){{3}}(?![\w-]|\.\w)")
IPV6 = re.compile(
    rf"(?<![\w:])(?:(?:{_HEX}:){{7}}{_HEX}|(?:{_HEX}:){{1,7}}:(?:{_HEX}(?::{_HEX}){{0,6}})?|::{_HEX}(?::{_HEX}){{0,6}})(?![\w:])",
    re.IGNORECASE,
)
EMAIL = re.compile(r"[\w.%+-]+@[a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,24}", re.IGNORECASE)
HOST = re.compile(r"(?<![\w@.-])(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}(?![\w@-])", re.IGNORECASE)

#: Per account number: who it was (``state.account_of``) and the probes of that account. A new account with the same number starts empty.
_kept: dict[int, tuple[str, deque[tuple[float, frozenset[str]]]]] = {}


def now() -> float:
    """The clock of this memory; a test sets it."""
    return time.time()


def identifiers(text: str) -> set[str]:
    """The addresses and names inside a text, in lower case."""
    return {found.group(0).lower() for pattern in (IPV4, IPV6, EMAIL, HOST) for found in pattern.finditer(text)}


def texts(value: Any, found: set[str] | None = None, depth: int = 0) -> set[str]:
    """Every text in an answer that is long enough to mean something."""
    found = set() if found is None else found
    if depth > MAX_DEPTH or len(found) >= MAX_TEXTS:
        return found
    if isinstance(value, str):
        text = value.strip()
        if len(text) >= MIN_LENGTH:
            found.update(ID + one for one in identifiers(text))
            if not text.replace(".", "").replace("-", "").isdigit():
                found.add(text)
    elif isinstance(value, dict):
        for child in value.values():
            texts(child, found, depth + 1)
    elif isinstance(value, list):
        for child in value:
            texts(child, found, depth + 1)
    return found


def remember(user: Any, answer: Any) -> None:
    """The texts of a probe, as the administrator (a ``User``) saw them."""
    who = state.account_of(user)
    held = _kept.get(user.id)
    if held is None or held[0] != who:
        held = _kept[user.id] = (who, deque(maxlen=KEEP_PROBES))
    held[1].append((now(), frozenset(texts(answer))))


def forget() -> None:
    _kept.clear()


def drop(user_id: int) -> None:
    """The account is gone (or no longer an administrator): so are its texts (EC-8)."""
    _kept.pop(user_id, None)


def _real(user: Any) -> frozenset[str]:
    held = _kept.get(user.id)
    kept = held[1] if held is not None and held[0] == state.account_of(user) else None
    if not kept:
        return frozenset()
    fresh = [one for when, one in kept if now() - when < KEEP_SECONDS]
    return frozenset().union(*fresh) if fresh else frozenset()


def places(user: Any, demo: Any) -> list[dict[str, str]]:
    """Where the demo data of a card hold a text one of the last probes returned: ``demo.<request>.<path>`` and the text."""
    real = _real(user)
    if not real or not isinstance(demo, dict):
        return []
    found: list[dict[str, str]] = []

    def walk(value: Any, path: str, depth: int) -> None:
        if depth > MAX_DEPTH or len(found) >= 30:
            return
        if isinstance(value, str):
            text = value.strip()
            if text in real:
                found.append({"path": path, "value": text[:80]})
            else:
                same = next((one for one in sorted(identifiers(text)) if ID + one in real), None)
                if same is not None:
                    found.append({"path": path, "value": same[:80]})
        elif isinstance(value, dict):
            for key, child in value.items():
                walk(child, f"{path}.{key}", depth + 1)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, f"{path}[{index}]", depth + 1)

    walk(demo, "demo", 0)
    return found
