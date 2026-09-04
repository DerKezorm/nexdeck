"""A brake on password guessing: per address, in memory."""

from __future__ import annotations

import time
from collections import defaultdict

from fastapi import HTTPException, status

WINDOW_SECONDS = 15 * 60
MAX_FAILURES = 10

_failures: dict[str, list[float]] = defaultdict(list)


def _prune(address: str, now: float) -> list[float]:
    recent = [t for t in _failures[address] if now - t < WINDOW_SECONDS]
    _failures[address] = recent
    return recent


def check(address: str) -> None:
    now = time.monotonic()
    if len(_prune(address, now)) >= MAX_FAILURES:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"code": "too_many_attempts", "message": "Too many failed sign-ins. Try again in a few minutes."},
        )


def failed(address: str) -> None:
    _failures[address].append(time.monotonic())


def succeeded(address: str) -> None:
    _failures.pop(address, None)


def reset() -> None:
    _failures.clear()
