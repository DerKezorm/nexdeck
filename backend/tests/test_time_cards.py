"""The countdown and the timer: cards that count in the browser, from options checked here."""

from __future__ import annotations

from app.adapters import get_adapter
from app.adapters.core import countdown_meta, timer_meta


def test_the_countdown_passes_on_what_it_counts_to() -> None:
    meta = countdown_meta({"event": " Holiday ", "date": "2026-11-06", "time": "18:30", "yearly": True, "show": "all", "after": "here"})
    assert meta == {"event": "Holiday", "date": "2026-11-06", "time": "18:30", "yearly": True, "show": "all", "after": "here"}


def test_a_date_that_is_none_comes_out_empty_and_the_card_asks_for_one() -> None:
    for written in ("2026-02-30", "6.11.2026", "tomorrow", ""):
        assert countdown_meta({"date": written})["date"] == "", written


def test_a_time_that_is_none_counts_to_the_start_of_the_day() -> None:
    for written in ("24:00", "7:5", "18.30", "noon"):
        assert countdown_meta({"date": "2026-11-06", "time": written})["time"] == "", written
    assert countdown_meta({"date": "2026-11-06", "time": "07:05"})["time"] == "07:05"


def test_the_countdown_keeps_its_choices_to_the_ones_it_has() -> None:
    meta = countdown_meta({"date": "2026-11-06", "show": "weeks", "after": "forever"})
    assert (meta["show"], meta["after"]) == ("auto", "since")


def test_the_timer_reads_its_quick_picks() -> None:
    meta = timer_meta({"minutes": 12, "presets": "3, 5,10 ; 0.5, 5, soon, 0, 2000", "end": "flash"})
    # A pick that is no number, too short, too long or twice is left out.
    assert meta == {"minutes": 12, "presets": [3, 5, 10, 0.5], "end": "flash"}


def test_the_timer_shows_at_most_eight_picks_and_starts_at_ten_without_a_start() -> None:
    meta = timer_meta({"presets": " ".join(str(n) for n in range(1, 13)), "minutes": "", "end": "loud"})
    assert meta["presets"] == [1, 2, 3, 4, 5, 6, 7, 8]
    assert meta["minutes"] == 10
    assert meta["end"] == "sound"


def test_a_timer_runs_for_a_day_at_most() -> None:
    assert timer_meta({"minutes": 1441})["minutes"] == 10
    assert timer_meta({"minutes": 1440})["minutes"] == 1440


def test_both_cards_draw_from_the_board_without_asking_the_server_again() -> None:
    core = get_adapter("core")
    assert core.widget("countdown").client_only and core.widget("timer").client_only
    assert core.demo("countdown", {"date": "2026-12-24"}, 0).meta["date"] == "2026-12-24"
    assert core.demo("timer", {}, 0).meta["presets"] == []
