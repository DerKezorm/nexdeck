"""A brake on password guessing, per address and per account, in memory.

⚠️ The address alone is not a brake. Behind a reverse proxy the client address
is whatever ``X-Forwarded-For`` says: the app reads the forwarding headers
from anybody (``RecordPeer`` in ``services/home_network.py``, which replaced
uvicorn's ``--forwarded-allow-ips "*"``) so that a proxied deployment sees
real addresses at all. A guesser sends a different value with every attempt and
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


#: What an account's attempts are counted for: the password, the second step, a reset mail.
#:
#: ⚠️ Each one its own bucket, and the kind stands in front of the name. The
#: second step used to count under the name "2fa:<name>" in the password's
#: bucket, so a sign-in as "2fa:admin", from anywhere and without an account,
#: filled the administrator's second step until a right code was refused.
KINDS = ("u", "2fa", "forgot")


def _account(kind: str, username: str) -> str:
    if kind not in KINDS:
        raise ValueError(f"no such attempt kind: {kind!r}")
    return f"{kind}:{username.lower()}"


def check(address: str, username: str = "", per_account: int = MAX_PER_ACCOUNT, *, kind: str = "u") -> None:
    now = time.monotonic()
    if len(_recent(f"a:{address}", now)) >= MAX_PER_ADDRESS:
        raise TooManyAttempts
    if username and len(_recent(_account(kind, username), now)) >= per_account:
        raise TooManyAttempts


def failed(address: str, username: str = "", *, kind: str = "u") -> None:
    now = time.monotonic()
    _failures.setdefault(f"a:{address}", []).append(now)
    if username:
        _failures.setdefault(_account(kind, username), []).append(now)
    _sweep(now)


#: Above this many buckets, every stale one is thrown out at once.
#:
#: ⚠️ ``_recent`` drops a bucket that has aged out, but only when that exact
#: key is looked at again. A guesser sends a different address and a different
#: name every time and never asks about any of them twice, so every attempt
#: left two buckets behind for good. The list grew with the attempts, and it is
#: reachable without an account.
SWEEP_ABOVE = 5000


def _sweep(now: float) -> None:
    if len(_failures) <= SWEEP_ABOVE:
        return
    for key, stamps in list(_failures.items()):
        if not any(now - stamp < WINDOW_SECONDS for stamp in stamps):
            _failures.pop(key, None)


def succeeded(address: str, username: str = "", *, kind: str = "u") -> None:
    """Clear the account that just proved itself. The address ages out on its own."""
    if username:
        _failures.pop(_account(kind, username), None)


def reset() -> None:
    _failures.clear()
