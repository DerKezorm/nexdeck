"""Two first calls at the same moment agree on one Web Push key pair.

⚠️ ``ensure_keys`` read, generated and wrote without holding anything. Two
browsers switching Web Push on at once both found no key, both made one, and
the second write replaced the first: the browser that had subscribed with the
first public key never got a message, or one of the calls ended in an error.
Still open in the check of 12.09.2026.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from app.migrations import migrate
from app.services.channels import webpush


def test_two_first_calls_at_once_agree_on_one_key_pair(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    migrate()
    real = webpush.ec.generate_private_key
    both_inside = threading.Barrier(2, timeout=1)

    def slow(curve: object) -> object:
        # Holds the first caller until the second has arrived as well, or a second has passed.
        try:
            both_inside.wait()
        except threading.BrokenBarrierError:
            pass
        return real(curve)

    monkeypatch.setattr(webpush.ec, "generate_private_key", slow)
    keys: list[str] = []
    failures: list[BaseException] = []

    def first_call() -> None:
        try:
            keys.append(webpush.public_key())
        except BaseException as failure:  # noqa: BLE001
            failures.append(failure)

    callers = [threading.Thread(target=first_call) for _ in range(2)]
    for caller in callers:
        caller.start()
    for caller in callers:
        caller.join(timeout=10)
    assert failures == []
    assert len(keys) == 2 and len(set(keys)) == 1, keys
