"""Sportarr, against the answers of a live Sportarr 4.1.7.1117 (11.09.2026)."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context
from app.adapters.sportarr import SportarrAdapter

SP = "http://sportarr.example.com:1867"
CONFIG = {"url": SP, "api_key": "made-up-key"}
NOW = datetime(2026, 9, 11, 21, 13, tzinfo=UTC)


def event(number: int, title: str, league: str, start: str, has_file: bool = False, broadcast: str = "") -> dict[str, Any]:
    """An event as ``/api/calendar`` and ``/api/wanted/missing`` hand it out, with made-up titles and places."""
    return {"id": number, "externalId": f"ev-{number:07d}", "title": title, "sport": "Combat" if league == "UFC" else "Motorsport",
            "leagueId": 1 if league == "UFC" else 2, "leagueName": league, "leagueLogoUrl": "https://images.example.com/league.png",
            "homeTeamId": None, "homeTeamName": None, "awayTeamId": None, "awayTeamName": None, "season": "2026", "seasonNumber": 2026,
            "episodeNumber": number, "round": str(number), "eventDate": start, "broadcastDate": broadcast or f"{start[:10]}T00:00:00Z", "broadcastTimezone": None,
            "venue": "Example Arena", "location": "US", "broadcast": None, "monitored": True, "manuallyMonitored": False, "monitoredParts": None,
            "hasFile": has_file, "filePath": None, "fileSize": None, "quality": None, "qualityProfileId": 1,
            "thumbUrl": "https://images.example.com/event.jpg", "added": "2026-09-11T21:13:01.6401639Z", "lastUpdate": "2026-09-11T21:13:01.6401639Z",
            "homeScore": None, "awayScore": None, "status": "scheduled", "partStatuses": None, "dvrInfo": None, "files": [], "images": []}


#: The next seven days, ordered by start as Sportarr sends them. The broadcast dates are the measured ones: midnight, sometimes the day before.
CALENDAR = [event(41, "Fight Night 288 Example vs Sample", "UFC", "2026-09-12T18:00:00Z", broadcast="2026-09-12T00:00:00Z"),
            event(42, "Contender Series Week 6", "UFC", "2026-09-16T00:00:00Z", broadcast="2026-09-15T00:00:00Z")]
#: The latest first; 40 in all, and /api/stats said wanted 56 because it counts the coming ones too.
MISSING = {"events": [event(40, "Contender Series Week 5", "UFC", "2026-09-09T00:00:00Z", broadcast="2026-09-08T00:00:00Z"),
                      event(39, "Fight Night 287 Model vs Pattern", "UFC", "2026-09-05T16:00:00Z", broadcast="2026-09-05T00:00:00Z"),
                      event(38, "Contender Series Week 4", "UFC", "2026-09-01T23:00:00Z", broadcast="2026-09-01T00:00:00Z")],
           "page": 1, "pageSize": 3, "totalRecords": 40}
STATS = {"wanted": 56, "queued": 0, "leagues": 2, "events": 735, "monitored": 56, "downloaded": 0, "files": 0}
STATUS = {"appName": "Sportarr", "version": "4.1.7.1117", "buildTime": "2026-09-11 21:05:38", "isDebug": False, "isProduction": True, "isDocker": True,
          "runtimeVersion": "8.0.31", "databaseType": "SQLite", "authentication": "apikey", "branch": "main", "urlBase": "", "timeZone": "Etc/UTC"}
REFUSED = {"error": "Unauthorized", "message": "API key required"}


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


def test_upcoming_events_by_day() -> None:
    finished = event(7, "Grand Prix of Example", "Formula 1", "2026-09-13T13:00:00Z", has_file=True)
    data = SportarrAdapter._calendar([*CALENDAR, finished, {"title": "No start", "eventDate": None}])
    assert [(row["date"], row["title"], row["subtitle"], row["status"]) for row in data.items] == [
        ("2026-09-12", "Fight Night 288 Example vs Sample", "UFC", "unknown"),
        ("2026-09-16", "Contender Series Week 6", "UFC", "unknown"),
        ("2026-09-13", "Grand Prix of Example", "Formula 1", "ok"),
    ]
    assert data.secondary == [{"label": "Next days", "value": 3}] and data.metrics == {"upcoming": 3.0}


@respx.mock
async def test_the_calendar_asks_from_now_for_the_days_ahead(ctx: Context) -> None:
    route = respx.get(f"{SP}/api/calendar").mock(return_value=httpx.Response(200, json=CALENDAR))
    data = await get_adapter("sportarr").fetch("upcoming", CONFIG, {"days": 3}, ctx)
    request = route.calls.last.request
    assert request.headers["X-Api-Key"] == "made-up-key"
    start, end = request.url.params["start"], request.url.params["end"]
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:00Z", start)
    span = datetime.strptime(end, "%Y-%m-%dT%H:%M:%SZ") - datetime.strptime(start, "%Y-%m-%dT%H:%M:%SZ")
    assert span.days == 3 and len(data.items) == 2


def test_missing_events_the_latest_first_with_their_age() -> None:
    data = SportarrAdapter._missing_list(MISSING, NOW)
    assert [(row["title"], row["subtitle"], row["status"], row["value"]) for row in data.items] == [
        ("Contender Series Week 5", "UFC", "warn", "2 d"),
        ("Fight Night 287 Model vs Pattern", "UFC", "warn", "6 d"),
        ("Contender Series Week 4", "UFC", "warn", "9 d"),
    ]
    # The number of all missing events, not of the rows on this page.
    assert data.secondary == [{"label": "Missing", "value": 40}] and data.metrics == {"missing": 40.0}


@respx.mock
async def test_the_missing_card_asks_for_one_page(ctx: Context) -> None:
    """⚠️ Measured: without page and pageSize the list answers 400."""
    route = respx.get(f"{SP}/api/wanted/missing").mock(return_value=httpx.Response(200, json=MISSING))
    data = await get_adapter("sportarr").fetch("missing", CONFIG, {"limit": 3}, ctx)
    assert dict(route.calls.last.request.url.params) == {"page": "1", "pageSize": "3"}
    assert len(data.items) == 3


@respx.mock
async def test_the_summary_counts_what_has_taken_place_not_what_stats_calls_wanted(ctx: Context) -> None:
    respx.get(f"{SP}/api/wanted/missing").mock(return_value=httpx.Response(200, json={**MISSING, "events": MISSING["events"][:1], "pageSize": 1}))
    respx.get(f"{SP}/api/calendar").mock(return_value=httpx.Response(200, json=CALENDAR))
    respx.get(f"{SP}/api/stats").mock(return_value=httpx.Response(200, json=STATS))
    data = await get_adapter("sportarr").fetch("summary", CONFIG, {}, ctx)
    assert data.primary == {"label": "Missing", "value": 40}
    assert data.secondary == [{"label": "Upcoming", "value": 2}, {"label": "Leagues", "value": 2}]
    assert data.metrics == {"missing": 40.0, "upcoming": 2.0}


@respx.mock
async def test_a_made_up_key(ctx: Context) -> None:
    respx.get(f"{SP}/api/wanted/missing").mock(return_value=httpx.Response(401, json=REFUSED))
    with pytest.raises(AuthFailed):
        await get_adapter("sportarr").fetch("missing", CONFIG, {}, ctx)


@respx.mock
async def test_an_unreachable_server(ctx: Context) -> None:
    respx.get(f"{SP}/api/calendar").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(AdapterError) as failure:
        await get_adapter("sportarr").fetch("upcoming", CONFIG, {}, ctx)
    assert failure.value.code == "unreachable"


@respx.mock
async def test_another_service_on_the_address(ctx: Context) -> None:
    adapter = get_adapter("sportarr")
    respx.get(f"{SP}/api/system/status").mock(return_value=httpx.Response(200, json={**STATUS, "appName": "Sonarr"}))
    with pytest.raises(AdapterError) as other:
        await adapter.test(CONFIG, ctx)
    assert other.value.code == "not_sportarr"
    respx.get(f"{SP}/api/calendar").mock(return_value=httpx.Response(200, json={"records": []}))
    with pytest.raises(AdapterError) as shape:
        await adapter.fetch("upcoming", CONFIG, {}, ctx)
    assert shape.value.code == "not_sportarr"


@respx.mock
async def test_the_connection_test(ctx: Context) -> None:
    respx.get(f"{SP}/api/system/status").mock(return_value=httpx.Response(200, json=STATUS))
    respx.get(f"{SP}/api/stats").mock(return_value=httpx.Response(200, json=STATS))
    assert await get_adapter("sportarr").test(CONFIG, ctx) == "Sportarr 4.1.7.1117 answers with 2 leagues."
