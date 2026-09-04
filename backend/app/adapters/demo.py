"""Deterministic fake data for demo mode.

Every adapter's ``demo()`` builds on these helpers so that values move
believably from tick to tick and look the same on every installation: a
screenshot taken here matches what someone else sees at the same tick.
"""

from __future__ import annotations

import hashlib
import math
import random


def _seed(*parts: object) -> int:
    digest = hashlib.sha1("|".join(str(p) for p in parts).encode()).digest()
    return int.from_bytes(digest[:8], "big")


def walk(name: str, tick: int, low: float, high: float, *, period: float = 90.0, noise: float = 0.08) -> float:
    """A smooth value between ``low`` and ``high`` that drifts with ``tick``."""
    seed = _seed(name)
    phase = (seed % 1000) / 1000 * math.tau
    speed = 0.6 + (seed % 7) / 10
    base = (math.sin(tick / period * speed + phase) + 1) / 2
    wobble = (math.sin(tick / 7 + phase * 3) + 1) / 2
    rng = random.Random(_seed(name, tick))
    jitter = (rng.random() - 0.5) * noise
    value = low + (high - low) * min(1.0, max(0.0, base * 0.8 + wobble * 0.2 + jitter))
    return round(value, 1)


def pick(name: str, tick: int, choices: list[str], *, every: int = 40) -> str:
    """Pick a stable choice that changes every ``every`` ticks."""
    return choices[(_seed(name) + tick // every) % len(choices)]


def counter(name: str, tick: int, start: int, per_tick: float) -> int:
    return int(start + tick * per_tick + (_seed(name) % 50))


def flicker(name: str, tick: int, chance: float = 0.05) -> bool:
    """True occasionally: a container restarting, a check failing."""
    rng = random.Random(_seed(name, tick // 15))
    return rng.random() < chance
