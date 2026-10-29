"""Timed calendar entries carry their moment, so the card can put them on the viewer's own day (#56).

A show at seven in the evening in Chicago is past midnight in UTC. The card
used to list it under the next day, because the server sent only the day in
UTC. Now an entry with a time of day carries ``at``, the moment with its
offset, and the *arr are asked a day either side so nothing at the edge of
the window is lost.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import pytest
import respx

from app.adapters import get_adapter, ical
from app.adapters.base import Context
from app.adapters.ical import at_moment
from app.adapters.sportarr import SportarrAdapter

SONARR = {"url": "http://sonarr:8989", "api_key": "key"}
#: Seven in the evening in Chicago on 28 October 2026 (CDT, five hours behind UTC).
EVENING = "2026-10-29T00:00:00Z"


def episode(air: str, title: str = "Chicago Med") -> dict:
    return {"airDateUtc": air, "airDate": air[:10], "seasonNumber": 12, "episodeNumber": 4, "title": "Pilot", "hasFile": False, "series": {"title": title}}


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


def test_the_moment_keeps_its_offset_and_the_day_follows_the_clock_it_is_read_on() -> None:
    assert at_moment(EVENING, ZoneInfo("America/Chicago")) == {"date": "2026-10-28", "at": "2026-10-29T00:00:00+00:00"}
    assert at_moment(EVENING, ZoneInfo("Europe/Berlin")) == {"date": "2026-10-29", "at": "2026-10-29T00:00:00+00:00"}
    # Without an offset it is UTC, as the *arr write it; nothing readable is no moment.
    assert at_moment("2026-10-29T00:00:00", ZoneInfo("America/Chicago"))["date"] == "2026-10-28"
    assert at_moment("", None) is None and at_moment(None, None) is None and at_moment("soon", None) is None


def test_an_episode_carries_the_moment_it_airs() -> None:
    item = get_adapter("sonarr").calendar_item(episode(EVENING))
    assert item["at"] == "2026-10-29T00:00:00+00:00"
    assert item["subtitle"] == "S12E04 Pilot"
    # Only the day where the network is: a day, no moment.
    bare = get_adapter("sonarr").calendar_item({**episode(EVENING), "airDateUtc": None})
    assert bare["date"] == "2026-10-29" and "at" not in bare


@respx.mock
async def test_sonarr_is_asked_a_day_either_side_and_keeps_today_s_evening(ctx: Context, monkeypatch: pytest.MonkeyPatch) -> None:
    # Eight in the evening on the 28th on this server's clock: in UTC the 29th has begun.
    monkeypatch.setattr(ical, "_now", lambda: datetime(2026, 10, 28, 20, 0))
    route = respx.get("http://sonarr:8989/api/v3/calendar").mock(return_value=httpx.Response(200, json=[
        episode("2026-10-28T12:00:00Z", "Noon show"),
        episode(EVENING),
        episode("2026-10-26T12:00:00Z", "Days ago"),
    ]))
    data = await get_adapter("sonarr").fetch("calendar", SONARR, {"days": 7}, ctx)
    params = route.calls.last.request.url.params
    assert (params["start"], params["end"]) == ("2026-10-27", "2026-11-05")
    assert [item["title"] for item in data.items] == ["Noon show", "Chicago Med"]
    assert data.items[1]["at"] == "2026-10-29T00:00:00+00:00"


@respx.mock
async def test_an_appointment_in_a_zone_carries_its_moment_and_a_floating_one_does_not(ctx: Context, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ical, "_now", lambda: datetime(2026, 10, 27, 12, 0))
    ics = ("BEGIN:VCALENDAR\nBEGIN:VEVENT\nSUMMARY:Choir\nDTSTART;TZID=America/Chicago:20261028T190000\nDTEND;TZID=America/Chicago:20261028T200000\nEND:VEVENT\n"
           "BEGIN:VEVENT\nSUMMARY:Floating\nDTSTART:20261029T090000\nEND:VEVENT\nEND:VCALENDAR\n")
    respx.get("https://cal.example.com/family.ics").mock(return_value=httpx.Response(200, text=ics))
    data = await get_adapter("ical").fetch("events", {"url": "https://cal.example.com/family.ics"}, {"days": 14}, ctx)
    found = {item["title"]: item for item in data.items}
    assert found["Choir"]["at"] == "2026-10-28T19:00:00-05:00"
    assert "at" not in found["Floating"] and found["Floating"]["time"] == "09:00"


def test_a_sports_event_carries_its_start() -> None:
    data = SportarrAdapter._calendar([{"title": "Fight Night", "leagueName": "UFC", "eventDate": EVENING}])
    assert data.items[0]["at"] == "2026-10-29T00:00:00+00:00"
