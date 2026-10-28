"""Example answers made from real ones: the shape stays, every text and number changes (KARTEN-9 AC-10).

A card from the shop or from a friend carries example answers, and answers copied from the author's own services say how
many films he has and what they are called. This makes them harmless the way the showcase mode of the board does
(``frontend/src/lib/showcase.ts``), but for data of any shape, where nothing says which text is a name:

- Kept: the keys (the paths of a card run through them), the structure, true and false, null, a time of day and a date in
  the form of a web server, and a number in the range of epoch seconds or milliseconds under a key that names a time
  (``addedAt``).
- Moved: a date or a time stamp in the form of ISO 8601 (``2026-10-01``, ``2026-10-01T12:30:00Z``) by a number of whole days
  between 30 and 400 (and some minutes), the same for all of the examples, so the form and the order of the moments stay
  and the day does not.
- Cut: lists to a few entries and long texts to a few hundred characters, so the answers fit into a definition.
- Changed, the same way every time for the same value, so one title is one stand-in in all requests: a number to
  another of about the same size (a percentage stays a percentage), a text word for word to another word of the same
  kind (case and digits stay where they were), an address of a picture or a page to an address on example.com, a mail
  address to user-xxxxxx@example.com, an IP address to one from the ranges meant for documentation, a host name to
  host-xxxxx.example. A key that is data itself is changed the way the same value would be (a hash, an IP address, a host
  name, a mail address, a UUID, a long number): answers keyed by torrent hashes or by host names would give those away
  otherwise. Two keys of one object never become one. A word made of letters and digits (a token such as ``ghp_AbCd…``)
  becomes an invented word, never its own characters moved on: nothing of three characters or more stays.

⚠️ This hides what a value says, it is no encryption: a short text or a small number can be guessed from its stand-in
by anybody who tries every one. The editor shows the result before it is taken over and lets the author change values.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
from datetime import datetime, timedelta
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
_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?:([T ])(\d{2}):(\d{2})(?::(\d{2})([.,]\d+)?)?(Z|[+-]\d{2}(?::?\d{2})?)?)?$")
_TIME = re.compile(r"^\d{1,2}:\d{2}(?::\d{2}(?:\.\d+)?)?$")
_HTTP_DATE = re.compile(r"^(?:[A-Z][a-z]{2},\s)?\d{1,2}\s[A-Z][a-z]{2}\s\d{4}(?:\s\d{2}:\d{2}(?::\d{2})?(?:\s(?:GMT|UTC|[+-]\d{4}))?)?$")
_URL = re.compile(r"^https?://", re.I)
_MAIL = re.compile(r"^[\w.+-]+@[\w-]+(?:\.[\w-]+)+$")
_IPV4 = re.compile(r"^(?:\d{1,3}\.){3}\d{1,3}(?::\d{1,5})?$")
_IPV6 = re.compile(r"^[0-9a-f]{0,4}(?::[0-9a-f]{0,4}){2,7}$", re.I)
_MAC = re.compile(r"^(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}$", re.I)
_HOST = re.compile(r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]*[a-z0-9]$", re.I)
_FILE = re.compile(r"\.(?:jpe?g|png|gif|webp|svg|avif|bmp|pdf|mkv|mp4|avi|mov|zip|txt|json|ya?ml|log|iso|mp3|flac|m4a|m4b|epub|cbz|nfo|srt|md|conf|cfg|ini|db|sql|tar|gz|7z|rar|html?|css|js|sh|py)$", re.I)
_PICTURE = re.compile(r"\.(?:jpe?g|png|gif|webp|svg|avif|bmp)$", re.I)
_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
#: A hash or any long run of hex digits, and a short one only with digits and letters in it (a short commit name).
_HEX = re.compile(r"^(?:[0-9a-f]{16,}|(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{7,15})$", re.I)
#: A key or token in base 64 or 62: long, with capitals, small letters and several digits, so that a field name is not taken for one.
_BASE64 = re.compile(r"^(?=.*[A-Z])(?=.*[a-z])(?=.*\d.*\d)[A-Za-z0-9+/_=-]{20,}$")
_NUMBER = re.compile(r"^\d{5,}$")

#: A number in this range of seconds, or of milliseconds, can be a moment in time (2000 to 2100).
_EPOCH = (946_684_800, 4_102_444_800)
#: The words of a key that say a number is a moment in time. ⚠️ The range alone is not enough: a file of 2 GB or a disk of
#: 3 TB, in bytes, lies in it as well, and those are what a card shows (found in the review of KARTEN-9, 25.10.2026).
_TIME_WORDS = frozenset(
    "at time date datetime timestamp stamp ts epoch added created updated modified expires expiry expire expired since until due when utc "
    "started finished seen scheduled aired airdate published released day ctime mtime atime login checked synced heartbeat".split()
)
_KEY_WORD = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])")


#: How far the moments of the examples move back, in whole days, and the minutes on top of that.
SHIFT_DAYS = (30, 400)
SHIFT_MINUTES = 59


def draw_shift() -> timedelta:
    """A time to move the moments of one set of examples back by: the same for all of them, different for each set."""
    days = SHIFT_DAYS[0] + secrets.randbelow(SHIFT_DAYS[1] - SHIFT_DAYS[0] + 1)
    return timedelta(days=days, minutes=secrets.randbelow(SHIFT_MINUTES + 1))


def shift_moment(text: str, shift: timedelta) -> str:
    """A date or a time stamp of ISO 8601 moved back by ``shift``, in the form it had; any other text as it is.

    A date without a time moves by the whole days only. The fraction of a second and the zone stay, so does the order of the moments.
    """
    stripped = text.strip()
    found = _ISO.match(stripped)
    if found is None:
        return text
    year, month, day, separator, hour, minute, second, fraction, zone = found.groups()
    try:
        moved = datetime(int(year), int(month), int(day), int(hour or 0), int(minute or 0), int(second or 0)) - (shift if separator else timedelta(days=shift.days))
    except (ValueError, OverflowError):
        return text
    out = f"{moved.year:04d}-{moved.month:02d}-{moved.day:02d}"
    if separator:
        out += f"{separator}{moved.hour:02d}:{moved.minute:02d}"
        if second is not None:
            out += f":{moved.second:02d}{fraction or ''}"
        out += zone or ""
    return text.replace(stripped, out)


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


#: How many stand-ins are tried before one is taken that shares a few characters with the original.
_TRIES = 400
#: Longer than this, a stand-in cannot be made to share no three characters with the original, and is not asked to.
_APART_UNTIL = 128
_ALNUM = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
_DOCUMENTATION = ("192.0.2", "198.51.100", "203.0.113")
#: The kinds whose stand-in shares no three characters with the original: these can be secrets.
_SECRETS = frozenset({"uuid", "hex", "base64"})


def _grams(text: str) -> set[str]:
    lower = text.lower()
    return {lower[at : at + 3] for at in range(len(lower) - 2)}


def _stream(kind: str, salt: str, length: int) -> bytes:
    out = b""
    for at in range(length // 32 + 1):
        out += _digest(kind, f"{salt}|{at}")
    return out[:length]


def _cased(word: str, like: str) -> str:
    if like.isupper() and len(like) > 1:
        return word.upper()
    if like[:1].isupper():
        return word.capitalize()
    return word


def _mixed(token: str, stream: bytes) -> str:
    """Letters and digits together (``S01E02``, ``x264``, a token): an invented word with a few digits.

    ⚠️ Not the characters of the token moved on (that left the shape and the case of a secret, and a guess among 9 steps
    for each place): nothing of three characters or more of the token stays in the stand-in (found in the review of
    KARTEN-9, 25.10.2026).
    """
    grams = _grams(token)
    digits = min(3, sum(char.isdecimal() for char in token))
    start = int.from_bytes(stream[:4], "big") % len(_WORDS)
    candidate = token
    for step in range(_TRIES):
        word = _cased(_WORDS[(start + step) % len(_WORDS)], token)
        candidate = word + "".join(str(stream[(4 + at + step) % len(stream)] % 10) for at in range(digits))
        if candidate != token and not _grams(candidate) & grams:
            return candidate
    return candidate


#: A token this long is hardly a word of a text but a name, a number or a key: nothing of three characters of it may stay.
_LONG = 8


def _word(token: str, nth: int = 0) -> str:
    """The stand-in for one word or number of a text; ``nth`` asks for another one than the first."""
    salt = token.lower() if token.isalpha() else token
    stream = _digest("word", salt if nth == 0 else f"{salt}|{nth}")
    if not (token.isdecimal() or token.isalpha()):
        return _mixed(token, stream)
    make = _digits if token.isdecimal() else _letters
    made = make(token, stream)
    if len(token) < _LONG:
        return made
    grams = _grams(token)
    for more in range(1, _TRIES):
        if not _grams(made) & grams:
            break
        made = make(token, _digest("word", f"{salt}|{nth}|{more}"))
    return made


def _text(text: str, nth: int = 0) -> str:
    """The words and numbers of a text made up one by one; spaces, punctuation and the order stay."""
    return _TOKEN.sub(lambda match: _word(match.group(0), nth), text)


_INNER_CAPITAL = re.compile(r"[a-z\d][A-Z]")


def _key_like(run: str) -> bool:
    """A run without a space that looks like a key: ``ghp_AbCd1234…``, ``sk_live_aBcD…``, ``AKIA…``, a word of 6 or more in it with letters and digits or capitals inside."""
    if len(run) < 10:
        return False
    return any(len(token) >= 6 and not token.isalpha() and not token.isdecimal() or _INNER_CAPITAL.search(token) for token in _TOKEN.findall(run))


def _address(text: str, salt: str) -> str:
    """A page or a picture on some host, or a path on the service: an address on example.com."""
    path = re.split(r"[?#]", re.sub(r"^https?://[^/]*", "", text, flags=re.I), maxsplit=1)[0]
    extension = _PICTURE.search(path)
    return f"https://example.com/{_hex('url', salt, 10)}{extension.group(0).lower() if extension else ''}"


def data_kind(text: str, *, paths: bool = False) -> str | None:
    """What a whole text is, when it is data: ``url``, ``mail``, ``mac``, ``ipv4``, ``ipv6``, ``host``, ``uuid``, ``hex`` or ``base64``.

    ``paths`` takes a text that starts with a slash and holds no space for an address on the service (a value does, a key does not).
    """
    if _URL.match(text) or (paths and text.startswith("/") and " " not in text):
        return "url"
    if _MAIL.match(text):
        return "mail"
    if _MAC.match(text):
        return "mac"
    if _IPV4.match(text):
        return "ipv4"
    if _IPV6.match(text) and text.count(":") >= 2 and any(char in "0123456789abcdefABCDEF" for char in text):
        return "ipv6"
    if _HOST.match(text) and not _FILE.search(text):
        return "host"
    if _UUID.match(text):
        return "uuid"
    if not _NUMBER.match(text) and _HEX.match(text):
        return "hex"
    if _BASE64.match(text):
        return "base64"
    return None


def _stand_in(kind: str, text: str, nth: int) -> str:
    """The ``nth`` stand-in for a text of a kind: the first is always the same one, the next ones are for when it is taken."""
    salt = text if nth == 0 else f"{text}\x00{nth}"
    if kind == "url":
        return _address(text, salt)
    if kind == "mail":
        return f"user-{_hex('mail', salt.lower(), 6)}@example.com"
    if kind == "mac":
        stream = _digest("mac", salt.lower())
        return f"02:00:00:00:{stream[0]:02x}:{stream[1]:02x}"
    if kind == "ipv4":
        # The three ranges meant for documentation hold 762 addresses; past those a host name stands in.
        if nth >= len(_DOCUMENTATION) * 254:
            return f"host-{_hex('host', salt, 5)}.example"
        return f"{_DOCUMENTATION[nth // 254]}.{1 + (_digest('ip', text)[0] + nth) % 254}"
    if kind == "ipv6":
        return f"2001:db8::{_digest('ip6', salt.lower())[0]:x}" if nth == 0 else f"2001:db8::{_digest('ip6', salt.lower())[:2].hex().lstrip('0') or '0'}"
    if kind == "host":
        return f"host-{_hex('host', salt.lower(), 5)}.example"
    if kind == "uuid":
        raw = _stream("uuid", salt.lower(), 16).hex()
        made = f"{raw[:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:32]}"
        return made.upper() if text.isupper() else made
    if kind == "hex":
        made = _stream("hex", salt.lower(), len(text) // 2 + 1).hex()[: len(text)]
        return made.upper() if text.isupper() else made
    if kind == "base64":
        return "".join(_ALNUM[byte % len(_ALNUM)] for byte in _stream("base64", salt, len(text)))
    return _digits(text, _stream("number", salt, len(text)))  # a long number


def _stand_for(kind: str, text: str, taken: set[str] | frozenset[str] = frozenset()) -> str:
    """The first stand-in that is no other one's, and for what can be a secret one that keeps nothing of the original."""
    grams = _grams(text) if kind in _SECRETS and len(text) <= _APART_UNTIL else set()
    for nth in range(_TRIES):
        made = _stand_in(kind, text, nth)
        if made != text and made not in taken and not _grams(made) & grams:
            return made
    made = _stand_in(kind, text, _TRIES)
    while made == text or made in taken:
        made += "x"
    return made


def disguise_text(text: str, shift: timedelta | None = None) -> str:
    """One text of an answer, made up (or kept, when it is a time of day or has no letter or digit in it).

    A date or a time stamp of ISO 8601 moves back by ``shift``; without one it stays.
    """
    stripped = text.strip()
    if not any(char.isalnum() for char in stripped):
        return text
    if _is_moment(stripped):
        return shift_moment(text, shift) if shift is not None else text
    kind = data_kind(stripped, paths=True)
    if kind is not None:
        return _stand_for(kind, stripped)
    made = _text(text)
    # ⚠️ A key with a prefix and separators (ghp_…, sk_live_…) is one secret: the words of the prefix count as well, and the
    # other words of the text must not happen to carry a piece of it.
    secrets = [run for run in stripped.split() if _key_like(run)]
    if secrets and len(stripped) <= _APART_UNTIL:
        grams = set().union(*(_grams(run) for run in secrets))
        for nth in range(1, _TRIES):
            if not _grams(made) & grams:
                break
            made = _text(text, nth)
    return made


def disguise_key(name: str, taken: set[str] | frozenset[str]) -> str:
    """The name of a key: unchanged, unless it is data itself (a hash, an address, a host, a mail address, a UUID, a long number).

    ``taken`` are the names the object has or has got already; a stand-in is never one of them, so two keys never become one.
    """
    stripped = name.strip()
    kind = data_kind(stripped) or ("number" if _NUMBER.match(stripped) else None)
    return name if kind is None else _stand_for(kind, stripped, taken)


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


def _made_up(value: Any, key: str | None = None, shift: timedelta | None = None) -> Any:
    """``key`` is the name the value stands under (a list takes the name of its own key); ``shift`` moves the moments."""
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int | float):
        return disguise_number(value, moment=names_a_time(key))
    if isinstance(value, str):
        # A made-up word can be longer than the one it stands for.
        return disguise_text(value, shift)[:TEXT_CHARS]
    if isinstance(value, list):
        return [_made_up(one, key, shift) for one in value]
    if isinstance(value, dict):
        # ⚠️ A key that is data (a hash, a host name) is made up like a value; the other keys stay, since the paths of a card run through them.
        made: dict[str, Any] = {}
        taken = set(value)
        for name, one in value.items():
            new_name = disguise_key(name, taken)
            taken.add(new_name)
            made[new_name] = _made_up(one, name, shift)
        return made
    return value


def disguise(answers: dict[str, Any], shift: timedelta | None = None) -> tuple[dict[str, Any], bool]:
    """The example answers for the real ones, and whether anything was cut to make them fit.

    The moments in them move back by ``shift``, one time for all of them (drawn here when none is given).

    Raises ``AdapterError`` with the code ``demo_too_large`` when even one entry of every list is more than a card keeps.
    """
    shift = shift if shift is not None else draw_shift()
    for entries in ENTRIES:
        cut = [False]
        made = {key: _made_up(_cut(one, entries, 0, cut), None, shift) for key, one in answers.items()}
        if len(json.dumps(made, ensure_ascii=False)) <= MAX_CHARS:
            return made, cut[0] or entries != ENTRIES[0]
    raise AdapterError(
        "The answers are too large to keep as examples, even with one entry of every list.",
        code="demo_too_large",
        hint="Ask for less with the path of the request, or write the examples by hand.",
    )
