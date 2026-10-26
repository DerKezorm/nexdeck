"""What the built-in cards of a connection read, kept in memory so the editor can offer it as a start.

Someone who runs a service and already has its built-in card on the board often wants a card of their own next to it.
The paths the built-in card asks are the best answer to "where is the data": they are known to work with this very
service. Every GET a built-in card makes through a connection is noted here, per connection, and nothing else:

- only GET, and only from a built-in card (a custom card's own requests, the Test button and the probe are not noted);
- the path under the address of the connection, **without** what proves who asks (``apikey``, ``token`` and the like);
- the card's number, so the name it has on the board *now* is looked up when it is asked for, and a card taken off the
  board takes its paths with it;
- at most :data:`MOST` paths per connection, the newest kept; a path that comes again with other values (a salt, a
  timestamp) renews its entry instead of taking a new place.

⚠️ Memory only, gone with the process, never written to the database, the journal or the log. A path that has a secret
of the connection in it (a key in the middle of the address) is dropped when it is read out, not shown with a hole.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl, quote, urlsplit

#: Paths kept per connection.
MOST = 20
#: Longest path kept; a path beyond it is a body smuggled into an address, not a place to read.
LONGEST = 400


@dataclass
class Seen:
    origin: str
    path: str
    widget_id: int
    at: float


@dataclass
class _Held:
    """What is kept of one request: the path, and the parameters apart, so that what proves who asks can go when it is read out."""

    origin: str
    path: str
    pairs: list[tuple[str, str]]
    widget_id: int
    at: float


#: Per connection, keyed by the path **without** its values: a path whose parameters change from call to call (a salt, a
#: timestamp, a page) is one entry that is renewed, not a new one each time that pushes the other cards out of the twenty.
_seen: dict[int, OrderedDict[tuple[str, tuple[str, ...], int], _Held]] = {}


def _credential(name: str) -> bool:
    from ..adapters.rawread import CREDENTIAL_PARAM

    return bool(CREDENTIAL_PARAM.search(name))


def _query(pairs: list[tuple[str, str]]) -> str:
    return "&".join(f"{quote(name, safe='')}={quote(value, safe='')}" for name, value in pairs)


def note(integration_id: int | None, widget_id: int | None, method: str, url: str, params: dict[str, Any] | None) -> None:
    """One request of a built-in card, as it is about to leave. Never raises: a note must not fail a card."""
    if integration_id is None or widget_id is None or method.upper() != "GET":
        return
    try:
        parts = urlsplit(url)
        pairs = [(name, value) for name, value in parse_qsl(parts.query, keep_blank_values=True) if not _credential(name)]
        pairs += [(str(name), str(value)) for name, value in (params or {}).items() if not _credential(str(name))]
        path = parts.path + ("?" + _query(pairs) if pairs else "")
        if not parts.scheme or not parts.netloc or len(path) > LONGEST:
            return
        held = _seen.setdefault(integration_id, OrderedDict())
        key = (parts.path, tuple(sorted(name for name, _ in pairs)), widget_id)
        held.pop(key, None)
        held[key] = _Held(f"{parts.scheme}://{parts.netloc}".lower(), parts.path, pairs, widget_id, time.time())
        while len(held) > MOST:
            held.popitem(last=False)
    except Exception:  # noqa: BLE001, S110 - see the docstring
        return


def forget(integration_id: int) -> None:
    _seen.pop(integration_id, None)


def read(
    integration_id: int,
    base: str,
    secrets: list[str],
    *,
    names: frozenset[str] = frozenset(),
    values: frozenset[str] = frozenset(),
) -> list[Seen]:
    """The notes of one connection, newest first, as paths under ``base`` and without any that carry a secret.

    ``names`` and ``values`` are what the connection itself puts into an address to prove who asks (Navidrome sends
    ``u``, ``t`` and ``s``: the user name, a token made from the password, and the salt of it): a parameter with such a
    name, or whose value is a credential of the connection, does not leave this function. Two notes that are the same
    path after that are one.
    """
    base_parts = urlsplit(base)
    origin = f"{base_parts.scheme}://{base_parts.netloc}".lower()
    prefix = base_parts.path.rstrip("/")
    lowered = {name.lower() for name in names}
    out: list[Seen] = []
    taken: set[tuple[str, int]] = set()
    for one in reversed(list(_seen.get(integration_id, {}).values())):
        if one.origin != origin or not one.path.startswith(prefix):
            continue
        rest = one.path[len(prefix):]
        if not rest.startswith("/") or any(secret and secret in rest for secret in secrets):
            continue
        pairs = [(name, value) for name, value in one.pairs if name.lower() not in lowered and value not in values]
        shown = rest + ("?" + _query(pairs) if pairs else "")
        if any(secret and secret in shown for secret in secrets) or (shown, one.widget_id) in taken:
            continue
        taken.add((shown, one.widget_id))
        out.append(Seen(one.origin, shown, one.widget_id, one.at))
    return out


def clear() -> None:
    """For tests."""
    _seen.clear()
