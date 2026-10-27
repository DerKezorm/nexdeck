"""The calendar card as a week or a month grid: what the server hands out for it, and that the list is untouched."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
import respx

import app.adapters.ical as module
from app.adapters import get_adapter
from app.adapters.base import Context
from app.adapters.ical import GRID_AHEAD, GRID_BACK, GRID_LIMIT

ICS = """BEGIN:VCALENDAR
BEGIN:VEVENT
SUMMARY:Last month
DTSTART:20261003T090000
DTEND:20261003T100000
END:VEVENT
BEGIN:VEVENT
SUMMARY:Standup
DTSTART:20261027T081500
DTEND:20261027T083000
END:VEVENT
BEGIN:VEVENT
SUMMARY:Holiday
DTSTART;VALUE=DATE:20261029
END:VEVENT
BEGIN:VEVENT
SUMMARY:Next month
DTSTART:20261112T180000
DTEND:20261112T190000
END:VEVENT
BEGIN:VEVENT
SUMMARY:Far away
DTSTART:20270601T120000
DTEND:20270601T130000
END:VEVENT
END:VCALENDAR
"""
CONFIG = {"url": "https://cal.example.com/family.ics", "name": "Family"}


@pytest.fixture(autouse=True)
def clock(monkeypatch: pytest.MonkeyPatch) -> None:
    # Late in the day: the list would already have dropped the standup, the grid keeps it.
    monkeypatch.setattr(module, "_now", lambda: datetime(2026, 10, 27, 17, 0))


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


def titles(data: Any) -> list[str]:
    return [item["title"] for item in data.items]


@respx.mock
async def test_the_grid_reaches_back_and_ahead_and_keeps_what_is_over(ctx: Context) -> None:
    respx.get(CONFIG["url"]).mock(return_value=httpx.Response(200, text=ICS))
    adapter = get_adapter("ical")
    month = await adapter.fetch("events", CONFIG, {"view": "month", "days": 3, "limit": 1}, ctx)
    # "days" and "limit" are the list's: the grid ignores both, takes the past month and the next one, not a year away.
    assert titles(month) == ["Last month", "Standup", "Holiday", "Next month"]
    assert month.meta["view"] == "month"
    assert month.meta["range"] == {"from": "2026-08-26", "to": "2027-02-28"}
    assert (GRID_BACK, GRID_AHEAD) == (62, 124)
    week = await adapter.fetch("events", CONFIG, {"view": "week"}, ctx)
    assert titles(week) == titles(month) and week.meta["view"] == "week"


@respx.mock
async def test_the_list_is_what_it_was(ctx: Context) -> None:
    respx.get(CONFIG["url"]).mock(return_value=httpx.Response(200, text=ICS))
    adapter = get_adapter("ical")
    for options in ({"days": 20}, {"days": 20, "view": "list"}, {"days": 20, "view": "year"}):
        listed = await adapter.fetch("events", CONFIG, options, ctx)
        assert titles(listed) == ["Holiday", "Next month"], options
        assert listed.meta == {} and "slot" not in listed.items[0]


@respx.mock
async def test_a_grid_of_several_sources_gives_each_its_place_in_the_list(ctx: Context) -> None:
    respx.get(CONFIG["url"]).mock(return_value=httpx.Response(200, text=ICS))
    respx.get("http://radarr:7878/api/v3/calendar").mock(return_value=httpx.Response(200, json=[{"title": "Copper Sky", "digitalRelease": "2026-10-30T00:00:00Z", "hasFile": False}]))
    sources = {1: (get_adapter("ical"), CONFIG), 2: (get_adapter("radarr"), {"url": "http://radarr:7878", "api_key": "key"})}

    async def resolve(number: int) -> tuple[Any, dict[str, Any], Context]:
        adapter, config = sources[number]
        return adapter, config, ctx

    merged = Context(httpx.AsyncClient(), resolve_integration=resolve, cache={})
    calendar = get_adapter("calendar")
    grid = await calendar.fetch("upcoming", {}, {"sources": [2, 1], "view": "month"}, merged)
    by_title = {item["title"]: item for item in grid.items}
    assert by_title["Copper Sky"]["slot"] == 0 and by_title["Standup"]["slot"] == 1, "the order the card lists them in"
    assert by_title["Copper Sky"]["source"] == "Radarr" and by_title["Standup"]["source"] == "Family"
    asked = next(call.request.url for call in respx.calls if call.request.url.path.endswith("/calendar"))
    # The release calendar was asked for the past months too, not from today.
    assert asked.params["start"] < datetime.now(UTC).date().isoformat()
    listed = await calendar.fetch("upcoming", {}, {"sources": [2, 1], "days": 7}, merged)
    assert titles(listed) == ["Holiday", "Copper Sky"] and all("slot" not in item for item in listed.items)


def test_the_view_is_an_option_of_both_cards_and_hides_the_list_options_in_a_grid() -> None:
    for kind, widget in (("ical", "events"), ("calendar", "upcoming")):
        options = {field.name: field for field in next(w for w in get_adapter(kind).widgets if w.kind == widget).options}
        assert options["view"].default == "list" and [value for value, _label in options["view"].options] == ["list", "week", "month"]
        for name in ("days", "limit", "hide_past"):
            assert options[name].only_when == ("view", "list"), name


def test_the_demo_grid_has_busy_days_and_four_sources_and_the_list_demo_stays() -> None:
    demo = get_adapter("calendar").demo("upcoming", {"view": "month"}, 1)
    assert {item["slot"] for item in demo.items} == {0, 1, 2, 3}
    days: dict[str, int] = {}
    for item in demo.items:
        days[item["date"]] = days.get(item["date"], 0) + 1
    assert max(days.values()) >= 4, "a day that needs a +N"
    assert min(item["date"] for item in demo.items) < datetime.now(UTC).date().isoformat() < max(item["date"] for item in demo.items)
    assert len(demo.items) < GRID_LIMIT
    assert demo.meta["view"] == "month" and "range" in demo.meta
    own = get_adapter("ical").demo("events", {"view": "week"}, 1)
    assert {item["slot"] for item in own.items} == {0} and own.meta["view"] == "week"
    assert "view" not in get_adapter("calendar").demo("upcoming", {}, 1).meta
