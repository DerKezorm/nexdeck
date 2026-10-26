"""What the built-in cards of a connection read, kept in memory so the editor can offer it as a start.

Someone who runs a service and already has its built-in card on the board often wants a card of their own next to it.
The paths the built-in card asks are the best answer to "where is the data": they are known to work with this very
service. Every GET a built-in card makes through a connection is noted here, per connection, and nothing else:

- only GET, and only from a built-in card (a custom card's own requests, the Test button and the probe are not noted);
- the path under the address of the connection, **without** what proves who asks (``apikey``, ``token`` and the like);
- the card's number, so the name it has on the board *now* is looked up when it is asked for, and a card taken off the
  board takes its paths with it;
- at most :data:`MOST` paths per connection, the newest kept.

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


_seen: dict[int, OrderedDict[tuple[str, int], Seen]] = {}


def _credential(name: str) -> bool:
    from ..adapters.rawread import CREDENTIAL_PARAM

    return bool(CREDENTIAL_PARAM.search(name))


def note(integration_id: int | None, widget_id: int | None, method: str, url: str, params: dict[str, Any] | None) -> None:
    """One request of a built-in card, as it is about to leave. Never raises: a note must not fail a card."""
    if integration_id is None or widget_id is None or method.upper() != "GET":
        return
    try:
        parts = urlsplit(url)
        pairs = [(name, value) for name, value in parse_qsl(parts.query, keep_blank_values=True) if not _credential(name)]
        pairs += [(str(name), str(value)) for name, value in (params or {}).items() if not _credential(str(name))]
        query = "&".join(f"{quote(name, safe='')}={quote(value, safe='')}" for name, value in pairs)
        path = parts.path + (f"?{query}" if query else "")
        if not parts.scheme or not parts.netloc or len(path) > LONGEST:
            return
        held = _seen.setdefault(integration_id, OrderedDict())
        key = (path, widget_id)
        held.pop(key, None)
        held[key] = Seen(f"{parts.scheme}://{parts.netloc}".lower(), path, widget_id, time.time())
        while len(held) > MOST:
            held.popitem(last=False)
    except Exception:  # noqa: BLE001, S110 - see the docstring
        return


def forget(integration_id: int) -> None:
    _seen.pop(integration_id, None)


def read(integration_id: int, base: str, secrets: list[str]) -> list[Seen]:
    """The notes of one connection, newest first, as paths under ``base`` and without any that carry a secret."""
    base_parts = urlsplit(base)
    origin = f"{base_parts.scheme}://{base_parts.netloc}".lower()
    prefix = base_parts.path.rstrip("/")
    out: list[Seen] = []
    for one in reversed(list(_seen.get(integration_id, {}).values())):
        if one.origin != origin or not one.path.startswith(prefix):
            continue
        rest = one.path[len(prefix):]
        if not rest.startswith("/") or any(secret and secret in rest for secret in secrets):
            continue
        out.append(Seen(one.origin, rest, one.widget_id, one.at))
    return out


def clear() -> None:
    """For tests."""
    _seen.clear()
