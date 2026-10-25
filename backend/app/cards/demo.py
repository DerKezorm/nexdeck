"""Example answers made from real ones: the shape stays, every text and number changes (KARTEN-9 AC-10).

A card from the shop or from a friend carries example answers, and answers copied from the author's own services say how
many films he has and what they are called. This makes them harmless the way the showcase mode of the board does
(``frontend/src/lib/showcase.ts``), but for data of any shape, where nothing says which text is a name:

- Kept: the keys, the structure, true and false, null, and anything that is a date or a time (a card reads those): a text
  in a date form, and a number in the range of epoch seconds or milliseconds under a key that names a time (``addedAt``).
- Cut: lists to a few entries and long texts to a few hundred characters, so the answers fit into a definition.
- Changed, the same way every time for the same value, so one title is one stand-in in all requests: a number to
  another of about the same size (a percentage stays a percentage), a text word for word to another word of the same
  kind (case and digits stay where they were), an address of a picture or a page to an address on example.com, a mail
  address to user-xxxxxx@example.com, an IP address to one from the ranges meant for documentation, a host name to
  host-xxxxx.example.

⚠️ This hides what a value says, it is no encryption: a short text or a small number can be guessed from its stand-in
by anybody who tries every one. The editor shows the result before it is taken over and lets the author change values.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from ..adapters.base import AdapterError
from .probe import clean

#: What the examples of all requests of one card may weigh together, in characters of JSON. A definition holds 60,000
#: with everything else in it.
MAX_CHARS = 20_000
#: The lists are cut to this many entries first, then to the next number until the examples fit.
ENTRIES = (10, 5, 3, 2, 1)
#: A text is cut to this many characters before it is made up.
TEXT_CHARS = 300
#: Anything deeper than this becomes null.
MAX_DEPTH = 30

_WORDS = (
    "harbour orbital nightshift glass mountain paper satellite tide signal copper field northbound static bloom kestrel "
    "saltwater hymn midnight ferry sky quiet lantern meadow ember cobalt willow garden river stone cedar maple falcon "
    "summit canyon prairie breeze timber velvet anchor beacon compass drift echo flint grove horizon island juniper "
    "lagoon marble nectar oasis pebble quartz ridge shadow thistle umber valley wander yarrow zephyr atlas bramble "
    "cinder dune"
).split()

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:[.,]\d+)?)?(?:Z|[+-]\d{2}(?::?\d{2})?)?)?$")
_TIME = re.compile(r"^\d{1,2}:\d{2}(?::\d{2}(?:\.\d+)?)?$")
_HTTP_DATE = re.compile(r"^(?:[A-Z][a-z]{2},\s)?\d{1,2}\s[A-Z][a-z]{2}\s\d{4}(?:\s\d{2}:\d{2}(?::\d{2})?(?:\s(?:GMT|UTC|[+-]\d{4}))?)?$")
_URL = re.compile(r"^https?://", re.I)
_MAIL = re.compile(r"^[\w.+-]+@[\w-]+(?:\.[\w-]+)+$")
_IPV4 = re.compile(r"^(?:\d{1,3}\.){3}\d{1,3}(?::\d{1,5})?$")
_IPV6 = re.compile(r"^[0-9a-f]{0,4}(?::[0-9a-f]{0,4}){2,7}$", re.I)
_MAC = re.compile(r"^(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}$", re.I)
_HOST = re.compile(r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]*[a-z0-9]$", re.I)
_FILE = re.compile(r"\.(?:jpe?g|png|gif|webp|svg|avif|bmp|pdf|mkv|mp4|avi|mov|zip|txt|json|ya?ml|log|iso|mp3|flac|m4a|m4b|epub|cbz|nfo|srt)$", re.I)
_PICTURE = re.compile(r"\.(?:jpe?g|png|gif|webp|svg|avif|bmp)$", re.I)
_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)

#: A number in this range of seconds, or of milliseconds, can be a moment in time (2000 to 2100).
_EPOCH = (946_684_800, 4_102_444_800)
#: The words of a key that say a number is a moment in time. ⚠️ The range alone is not enough: a file of 2 GB or a disk of
#: 3 TB, in bytes, lies in it as well, and those are what a card shows (found in the review of KARTEN-9, 25.10.2026).
_TIME_WORDS = frozenset(
    "at time date datetime timestamp stamp ts epoch added created updated modified expires expiry expire expired since until due when utc "
    "started finished seen scheduled aired airdate published released day ctime mtime atime login checked synced heartbeat".split()
)
_KEY_WORD = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])")


def _digest(kind: str, value: str) -> bytes:
    return hashlib.sha256(f"nexdeck-demo|{kind}|{value}".encode()).digest()


def _hex(kind: str, value: str, length: int) -> str:
    return _digest(kind, value).hex()[:length]


def _is_moment(text: str) -> bool:
    return bool(_DATE.match(text) or _TIME.match(text) or _HTTP_DATE.match(text))


def _digits(token: str, stream: bytes) -> str:
    """The same number of digits, every one of them another digit (and no leading zero where there was none)."""
    out = []
    for position, char in enumerate(token):
        new = (int(char) + 1 + stream[position % len(stream)] % 9) % 10
        if position == 0 and len(token) > 1 and new == 0:
            new = 1 if char != "1" else 2
        out.append(str(new))
    return "".join(out)


def _letters(token: str, stream: bytes) -> str:
    """A word of the list for a word, in the case the first had; another word than the first."""
    start = int.from_bytes(stream[:4], "big") % len(_WORDS)
    for step in range(len(_WORDS)):
        word = _WORDS[(start + step) % len(_WORDS)]
        if token.isupper() and len(token) > 1:
            word = word.upper()
        elif token[0].isupper():
            word = word.capitalize()
        if word != token:
            return word
    return token  # unreachable: the list has more than one word


def _mixed(token: str, stream: bytes) -> str:
    """Letters and digits together (``S01E02``, ``x264``): each character becomes another of its kind."""
    out = []
    for position, char in enumerate(token):
        step = 1 + stream[position % len(stream)] % 9
        if char.isdecimal():
            out.append(str((int(char) + step) % 10))
        elif char.isascii() and char.isalpha():
            base = ord("A") if char.isupper() else ord("a")
            out.append(chr(base + (ord(char) - base + step) % 26))
        else:
            out.append("x")
    return "".join(out)


def _word(match: re.Match[str]) -> str:
    token = match.group(0)
    stream = _digest("word", token.lower() if token.isalpha() else token)
    if token.isdecimal():
        return _digits(token, stream)
    if token.isalpha():
        return _letters(token, stream)
    return _mixed(token, stream)


def _text(text: str) -> str:
    """The words and numbers of a text made up one by one; spaces, punctuation and the order stay."""
    return _TOKEN.sub(_word, text)


def _address(text: str) -> str:
    """A page or a picture on some host, or a path on the service: an address on example.com."""
    path = re.split(r"[?#]", re.sub(r"^https?://[^/]*", "", text, flags=re.I), maxsplit=1)[0]
    extension = _PICTURE.search(path)
    return f"https://example.com/{_hex('url', text, 10)}{extension.group(0).lower() if extension else ''}"


def disguise_text(text: str) -> str:
    """One text of an answer, made up (or kept, when it is a moment in time or has no letter or digit in it)."""
    stripped = text.strip()
    if not any(char.isalnum() for char in stripped) or _is_moment(stripped):
        return text
    if _URL.match(stripped) or (stripped.startswith("/") and " " not in stripped):
        return _address(stripped)
    if _MAIL.match(stripped):
        return f"user-{_hex('mail', stripped.lower(), 6)}@example.com"
    if _MAC.match(stripped):
        stream = _digest("mac", stripped.lower())
        return f"02:00:00:00:{stream[0]:02x}:{stream[1]:02x}"
    if _IPV4.match(stripped):
        return f"192.0.2.{1 + _digest('ip', stripped)[0] % 254}"
    if _IPV6.match(stripped) and stripped.count(":") >= 2 and any(char in "0123456789abcdefABCDEF" for char in stripped):
        return f"2001:db8::{_digest('ip6', stripped.lower())[0]:x}"
    if _HOST.match(stripped) and not _FILE.search(stripped):
        return f"host-{_hex('host', stripped.lower(), 5)}.example"
    return _text(text)


def _is_epoch(number: float) -> bool:
    low, high = _EPOCH
    return low <= abs(number) <= high or low * 1000 <= abs(number) <= high * 1000


def names_a_time(key: str | None) -> bool:
    """Whether a key says its number is a moment in time: ``addedAt``, ``created_at``, ``timestamps``, ``date``."""
    if not key:
        return False
    return any(word.lower() in _TIME_WORDS or word.lower().removesuffix("s") in _TIME_WORDS for word in _KEY_WORD.findall(key))


def disguise_number(number: int | float, *, moment: bool = False) -> int | float:
    """A number of about the same size: never the same one, a part of a hundred stays within a hundred.

    ``moment`` says that the key names a time: a number in the range of epoch seconds or milliseconds then stays a date.
    """
    if isinstance(number, float) and (number != number or number in (float("inf"), float("-inf"))):
        return number
    if moment and _is_epoch(number):
        return number
    stream = _digest("number", repr(number))
    unit = int.from_bytes(stream[:4], "big") / 0xFFFFFFFF
    if isinstance(number, int):
        if abs(number) <= 3:
            return number + 1 + int(unit * 3)
        factor = 0.55 + 0.9 * unit
        if abs(number) <= 100 and abs(number * factor) > 100:
            factor = 0.55 + 0.4 * unit
        try:
            changed = round(number * factor)
        except OverflowError:
            return number // 2 + 1
        return changed if changed != number else number + 1
    decimals = min(6, len(repr(number).partition(".")[2])) if "e" not in repr(number) else 3
    factor = 0.55 + 0.9 * unit
    if abs(number) <= 100 and abs(number * factor) > 100:
        factor = 0.55 + 0.4 * unit
    changed = round(number * factor, decimals)
    return changed if changed != number else round(number + 10**-decimals, decimals)


def _cut(value: Any, entries: int, depth: int, cut: list[bool]) -> Any:
    if depth > MAX_DEPTH:
        cut[0] = True
        return None
    if isinstance(value, list):
        if len(value) > entries:
            cut[0] = True
        return [_cut(one, entries, depth + 1, cut) for one in value[:entries]]
    if isinstance(value, dict):
        return {clean(str(key)): _cut(one, entries, depth + 1, cut) for key, one in value.items()}
    if isinstance(value, str):
        if len(value) > TEXT_CHARS:
            cut[0] = True
        return clean(value[:TEXT_CHARS])
    return value


def _made_up(value: Any, key: str | None = None) -> Any:
    """``key`` is the name the value stands under (a list takes the name of its own key)."""
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int | float):
        return disguise_number(value, moment=names_a_time(key))
    if isinstance(value, str):
        # A made-up word can be longer than the one it stands for.
        return disguise_text(value)[:TEXT_CHARS]
    if isinstance(value, list):
        return [_made_up(one, key) for one in value]
    if isinstance(value, dict):
        return {name: _made_up(one, name) for name, one in value.items()}
    return value


def disguise(answers: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """The example answers for the real ones, and whether anything was cut to make them fit.

    Raises ``AdapterError`` with the code ``demo_too_large`` when even one entry of every list is more than a card keeps.
    """
    for entries in ENTRIES:
        cut = [False]
        made = {key: _made_up(_cut(one, entries, 0, cut)) for key, one in answers.items()}
        if len(json.dumps(made, ensure_ascii=False)) <= MAX_CHARS:
            return made, cut[0] or entries != ENTRIES[0]
    raise AdapterError(
        "The answers are too large to keep as examples, even with one entry of every list.",
        code="demo_too_large",
        hint="Ask for less with the path of the request, or write the examples by hand.",
    )
