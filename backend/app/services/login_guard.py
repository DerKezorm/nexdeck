"""A brake on password guessing, per address and per account, in memory.

⚠️ The address alone is not a brake. Behind a reverse proxy the client address
is whatever ``X-Forwarded-For`` says, and the container is started with
``--forwarded-allow-ips "*"`` so that a proxied deployment sees real
addresses at all. A guesser sends a different value with every attempt and
never meets the limit. So the account is counted too, and that one nobody can
spoof: guessing one account is capped however many addresses it comes from.

The second half is who may clear a bucket. Clearing the address on any
successful sign-in let a guesser with one account of their own reset the
counter every tenth attempt. A success now clears that account, and the
address bucket only ages out.
"""

from __future__ import annotations

import time

WINDOW_SECONDS = 15 * 60
#: From one address. Generous, because a household shares one.
MAX_PER_ADDRESS = 20
#: For one account, from anywhere. Tighter, because it cannot be spoofed.
MAX_PER_ACCOUNT = 10

_failures: dict[str, list[float]] = {}


class TooManyAttempts(Exception):
    """Raised instead of an HTTP error so the router decides how to answer."""


def _recent(key: str, now: float) -> list[float]:
    kept = [stamp for stamp in _failures.get(key, ()) if now - stamp < WINDOW_SECONDS]
    if kept:
        _failures[key] = kept
    else:
        # Do not leave a key behind for every address ever asked about.
        _failures.pop(key, None)
    return kept


def check(address: str, username: str = "") -> None:
    now = time.monotonic()
    if len(_recent(f"a:{address}", now)) >= MAX_PER_ADDRESS:
        raise TooManyAttempts
    if username and len(_recent(f"u:{username.lower()}", now)) >= MAX_PER_ACCOUNT:
        raise TooManyAttempts


def failed(address: str, username: str = "") -> None:
    now = time.monotonic()
    _failures.setdefault(f"a:{address}", []).append(now)
    if username:
        _failures.setdefault(f"u:{username.lower()}", []).append(now)


def succeeded(address: str, username: str = "") -> None:
    """Clear the account that just proved itself. The address ages out on its own."""
    if username:
        _failures.pop(f"u:{username.lower()}", None)


def reset() -> None:
    _failures.clear()
