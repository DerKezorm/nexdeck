"""Tautulli's plays per day: one square a day, the series added up."""

from __future__ import annotations

from app.adapters import get_adapter
from app.adapters.tautulli import heat_of


def test_the_series_of_a_day_add_up_to_one_square() -> None:
    graph = {"categories": ["2026-09-29", "2026-09-30", "2026-10-01"],
             "series": [{"name": "TV", "data": [2, 0, 5]}, {"name": "Movies", "data": [1, 0, 0]}, {"name": "Music", "data": [0, 0, 3]}]}
    card = heat_of(graph, hours=False)
    assert card.meta["heatmap"]["days"] == [["2026-09-29", 3], ["2026-09-30", 0], ["2026-10-01", 8]]
    assert card.primary == {"label": "Plays", "value": 11}
    assert card.secondary == [{"label": "Busiest day", "value": "2026-10-01"}]


def test_time_watched_is_shown_in_hours() -> None:
    card = heat_of({"categories": ["2026-10-01"], "series": [{"name": "TV", "data": [5400]}]}, hours=True)
    assert card.meta["heatmap"] == {"days": [["2026-10-01", 1.5]], "unit": "h"}
    assert card.primary["label"] == "Hours watched"


def test_an_answer_without_a_graph_is_an_empty_card_not_a_crash() -> None:
    card = heat_of(None, hours=False)
    assert card.meta["heatmap"]["days"] == [] and card.secondary == []
    ragged = heat_of({"categories": ["2026-10-01", "2026-10-02"], "series": [{"name": "TV", "data": [1, None, 7]}]}, hours=False)
    assert ragged.meta["heatmap"]["days"] == [["2026-10-01", 1], ["2026-10-02", 0]]


def test_the_demo_covers_the_chosen_span() -> None:
    assert len(get_adapter("tautulli").demo("days", {"days": "35"}, 0).meta["heatmap"]["days"]) == 35


def test_who_is_watching_travels_apart_from_the_line() -> None:
    rows = get_adapter("tautulli").demo("activity", {}, 120).items
    assert rows and all(row["user"] and row["subtitle"].startswith(row["user"]) for row in rows)
