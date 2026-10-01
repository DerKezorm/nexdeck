"""Tracearr 2.5.1, measured on 01.10.2026 without a media server behind it:
the counts are the measured answers, the violation follows Tracearr's own
OpenAPI description, since none can arise without streams."""

from __future__ import annotations

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AuthFailed, Context, outbound_client

CONFIG = {"url": "http://tracearr:3000", "api_key": "trr_pub_key"}
BASE = "http://tracearr:3000/api/v1/public"
STATS = {"activeStreams": 2, "totalUsers": 9, "totalSessions": 120, "recentViolations": 1, "timestamp": "2026-10-01T21:49:42.024Z"}
TODAY = {"activeStreams": 2, "todayPlays": 14, "todaySessions": 15, "watchTimeHours": 6.54, "alertsLast24h": 1, "activeUsersToday": 4}
VIOLATIONS = {"data": [
    {"id": "v1", "severity": "high", "acknowledged": False, "data": {}, "createdAt": "2026-10-01T19:12:00Z", "rule": {"id": "r1", "name": "Too many streams at once", "type": None}, "user": {"id": "u1", "username": "family"}},
    {"id": "v2", "severity": "low", "acknowledged": True, "data": {}, "createdAt": "2026-10-01T08:40:00Z", "rule": {"id": "r2", "name": "New device", "type": None}, "user": {"id": "u2", "username": "kim"}},
], "meta": {"total": 1, "page": 1, "pageSize": 25}}


@pytest.fixture
def ctx() -> Context:
    return Context(outbound_client(guard=False), integration_id=1, widget_id=1, cache={})


@respx.mock
async def test_the_overview_counts_streams_today_and_alerts(ctx: Context) -> None:
    respx.get(f"{BASE}/stats").mock(return_value=httpx.Response(200, json=STATS))
    respx.get(f"{BASE}/stats/today").mock(return_value=httpx.Response(200, json=TODAY))
    data = await get_adapter("tracearr").fetch("overview", CONFIG, {}, ctx)
    assert data.primary == {"label": "Streams", "value": 2}
    assert {row["label"]: row["value"] for row in data.secondary} == {"Plays today": 14, "Hours today": 6.5, "Alerts": 1, "Users": 9}
    assert data.status == "warn" and data.metrics == {"streams": 2.0}
    assert respx.calls.last.request.headers["Authorization"] == "Bearer trr_pub_key"


@respx.mock
async def test_violations_show_the_rule_and_who_and_leave_out_what_was_looked_at(ctx: Context) -> None:
    route = respx.get(f"{BASE}/violations").mock(return_value=httpx.Response(200, json=VIOLATIONS))
    data = await get_adapter("tracearr").fetch("violations", CONFIG, {"limit": 5}, ctx)
    assert [(row["title"], row["user"], row["status"]) for row in data.items] == [("Too many streams at once", "family", "bad")]
    assert data.status == "bad"
    assert route.calls.last.request.url.params["acknowledged"] == "false"


@respx.mock
async def test_nothing_flagged_is_a_quiet_card(ctx: Context) -> None:
    respx.get(f"{BASE}/violations").mock(return_value=httpx.Response(200, json={"data": [], "meta": {"total": 0, "page": 1, "pageSize": 25}}))
    data = await get_adapter("tracearr").fetch("violations", CONFIG, {}, ctx)
    assert data.items == [] and data.status == "ok"


@respx.mock
async def test_a_wrong_key_is_refused(ctx: Context) -> None:
    respx.get(f"{BASE}/stats").mock(return_value=httpx.Response(401, json={"statusCode": 401, "error": "UnauthorizedError", "message": "Invalid API key"}))
    with pytest.raises(AuthFailed):
        await get_adapter("tracearr").fetch("overview", CONFIG, {}, ctx)


@respx.mock
async def test_the_connection_test_names_the_version_and_the_servers(ctx: Context) -> None:
    respx.get(f"{BASE}/health").mock(return_value=httpx.Response(200, json={"status": "ok", "version": "v2.5.1", "servers": [{"id": "s", "name": "Plex", "type": "plex", "online": True}]}))
    assert await get_adapter("tracearr").test(CONFIG, ctx) == "Tracearr v2.5.1 answers and watches 1 media server(s)."
