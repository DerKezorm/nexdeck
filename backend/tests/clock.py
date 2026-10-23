"""A fixed hour of the day for tests that speak of "today" in the demo house.

⚠️ The demo house keeps Berlin time, and its day begins at midnight there. In
the first hour after it nothing has been measured yet today, so a test asking
what the coffee machine used today, or how cold the living room got, found
nothing. Red on 24.10.2026 at 00:05, in the tag run of a release, green in the
afternoon before.
"""

from __future__ import annotations

import datetime as real
import types

import pytest


def hold_clock_at(monkeypatch: pytest.MonkeyPatch, module: object, hour_utc: int, minute: int = 0) -> None:
    """``module.dt.datetime.now`` answers today at this hour, everything else in ``dt`` stays."""

    class Held(real.datetime):
        @classmethod
        def now(cls, tz: real.tzinfo | None = None) -> real.datetime:  # type: ignore[override]
            moment = real.datetime.now(real.UTC).replace(hour=hour_utc, minute=minute, second=0, microsecond=0)
            return moment.astimezone(tz) if tz is not None else moment.replace(tzinfo=None)

    shim = types.SimpleNamespace(**{name: getattr(real, name) for name in dir(real) if not name.startswith("__")})
    shim.datetime = Held
    monkeypatch.setattr(module, "dt", shim)


@pytest.fixture
def midday(monkeypatch: pytest.MonkeyPatch) -> None:
    """Noon in Berlin, summer or winter: well inside the demo house's day."""
    from app.services import hass_registry, hass_stats

    # Both clocks: the statistics decide when today began, the demo house's history what it measured since.
    for module in (hass_stats, hass_registry):
        hold_clock_at(monkeypatch, module, 10)
