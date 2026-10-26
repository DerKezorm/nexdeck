"""What nexdeck can ask of each kind of service, as its built-in cards do (JEDE-4, ``lesen aus dem Code``).

The list is **made from the code**, not typed: ``tools/card_reads.py`` fetches every built-in card of every kind once
against a stubbed service and writes down the GET requests that really leave. ``card_reads.json`` is its result, and
``tests/test_cards_card_reads.py`` makes it again and compares, so an adapter that asks something else turns the test red
until the file is made again.

The editor shows it in the step "Data" for the **kind**, with or without a connection and with or without a card of the
kind on any board. Nothing in it proves who asks: that is dropped when the list is made.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

TARGET = Path(__file__).with_name("card_reads.json")

#: Fields of a connection that name the account, whose value is a credential when it travels in an address.
ACCOUNT_FIELDS = ("username", "user", "login", "account", "email")


def what_proves_who_asks(adapter: Any, config: dict[str, Any]) -> tuple[frozenset[str], frozenset[str]]:
    """Names and values of the parameters this connection puts into an address to prove who asks.

    The names the kind lists or builds itself (``raw_params``: Navidrome's ``u``, ``t``, ``s``) and the values that are
    the user name or a secret of the connection, whatever the parameter is called.
    """
    try:
        built = dict(adapter.raw_params(config))
    except Exception:  # noqa: BLE001 - a kind that cannot build its parameters here still lists what it can
        built = {}
    secret_fields = adapter.secret_field_names()
    values = {str(value) for name, value in config.items() if isinstance(value, str) and len(value) >= 2
              and (name in secret_fields or name in ACCOUNT_FIELDS)}
    return frozenset({*adapter.raw_param_names, *built}), frozenset(values | {str(value) for value in built.values() if len(str(value)) >= 2})


@lru_cache(maxsize=1)
def _all() -> dict[str, list[dict[str, Any]]]:
    try:
        found = json.loads(TARGET.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return found if isinstance(found, dict) else {}


def reads_of(kind: str) -> list[dict[str, Any]]:
    """``[{"path": path under the address of the connection, "widgets": [kinds of the cards that ask it]}]`` of one kind.

    ``widgets`` is empty for a path from the documentation of the service that no card of nexdeck asks. Empty list for
    a kind with nothing known.
    """
    return [{"path": str(one["path"]), "widgets": list(one.get("widgets") or [])} for one in _all().get(kind, [])]


def kinds_with_reads() -> list[str]:
    return sorted(_all())
