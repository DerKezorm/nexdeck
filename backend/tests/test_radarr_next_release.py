"""Radarr's upcoming card shows the next release of a movie, named by its kind.

⚠️ Issue #8: Radarr lists a movie in its calendar when any of its three dates
falls in the window. The card always took the digital release when there was
one, so Toy Story 5 read "18 August, digital release" on 18 September, listed
because its physical release was four days away.

Dates are counted from today rather than written down: a fixed date turns
from future to past on its own and the test with it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.adapters import get_adapter


def _day(offset: int) -> str:
    return f"{(datetime.now(UTC).date() + timedelta(days=offset)).isoformat()}T00:00:00Z"


def test_the_next_date_wins_over_a_past_digital_release() -> None:
    item = get_adapter("radarr").calendar_item({
        "title": "Toy Story 5", "hasFile": False,
        "inCinemas": _day(-93), "digitalRelease": _day(-31), "physicalRelease": _day(4),
    })
    assert item is not None
    assert (item["date"], item["subtitle"]) == (_day(4)[:10], "Physical release")


def test_of_two_dates_ahead_the_nearer_one_is_shown() -> None:
    item = get_adapter("radarr").calendar_item({
        "title": "Copper Sky", "inCinemas": _day(2), "digitalRelease": _day(40),
    })
    assert item is not None
    assert (item["date"], item["subtitle"]) == (_day(2)[:10], "In cinemas")


def test_a_release_today_is_still_upcoming() -> None:
    item = get_adapter("radarr").calendar_item({
        "title": "Nightshift", "digitalRelease": _day(0), "physicalRelease": _day(30),
    })
    assert item is not None
    assert (item["date"], item["subtitle"]) == (_day(0)[:10], "Digital release")


def test_only_past_dates_show_the_latest() -> None:
    item = get_adapter("radarr").calendar_item({
        "title": "Orbital", "inCinemas": _day(-60), "physicalRelease": _day(-2),
    })
    assert item is not None
    assert (item["date"], item["subtitle"]) == (_day(-2)[:10], "Physical release")


def test_no_date_no_row() -> None:
    assert get_adapter("radarr").calendar_item({"title": "Paper Towns of Mars"}) is None
