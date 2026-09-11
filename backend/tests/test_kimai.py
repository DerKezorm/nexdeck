"""Kimai, against the answers of a live Kimai 2.66.0 (11.09.2026)."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context
from app.adapters.kimai import KimaiAdapter, week_start

KM = "http://kimai.example.com"
CONFIG = {"url": KM, "token": "made-up-token"}
NOW = datetime(2026, 9, 11, 11, 20, tzinfo=UTC)
PROJECT = {"id": 1, "name": "Website", "customer": {"id": 1, "name": "Example Customer", "currency": "EUR", "timezone": "Europe/Berlin"}, "visible": True}
ACTIVITY = {"id": 1, "name": "Development", "project": None, "visible": True}


def entry(identifier: int, begin: str, end: str | None, duration: int, description: str) -> dict[str, Any]:
    return {"tags": [], "id": identifier, "begin": begin, "end": end, "duration": duration, "break": 0, "user": {"id": 1, "username": "admin", "timezone": "UTC"},
            "activity": ACTIVITY, "project": PROJECT, "description": description, "rate": 0.0, "internalRate": 0.0, "exported": False, "billable": True}


#: Newest first, as asked for. A running entry has no end and a duration of 0.
ENTRIES = [
    entry(7, "2026-09-11T11:07:11+0000", None, 0, "Second timer"),
    entry(6, "2026-09-11T10:47:00+0000", "2026-09-11T11:07:00+0000", 1200, "Review the pull request"),
    entry(2, "2026-09-11T08:00:00+0000", "2026-09-11T10:15:00+0000", 8100, "Fix the login"),
    entry(1, "2026-09-07T09:00:00+0000", "2026-09-07T11:30:00+0000", 9000, "Planning"),
]
ME = {"apiToken": False, "locale": "en", "timezone": "UTC", "language": "en", "id": 1, "username": "admin", "enabled": True, "roles": ["ROLE_SUPER_ADMIN"],
      "preferences": [{"name": "work_contract_type", "value": "none"}, {"name": "first_weekday", "value": "monday"}]}


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


def test_the_week_begins_where_the_user_says() -> None:
    friday = date(2026, 9, 11)
    assert week_start(friday, "monday") == date(2026, 9, 7)
    assert week_start(friday, "sunday") == date(2026, 9, 6)
    assert week_start(date(2026, 9, 6), "sunday") == date(2026, 9, 6) and week_start(date(2026, 9, 7), "monday") == date(2026, 9, 7)


def test_the_running_timer_first_with_its_time_so_far() -> None:
    data = KimaiAdapter()._entries(ENTRIES, NOW, {"limit": 8})
    assert [(row["title"], row["subtitle"], row["status"], row["value"]) for row in data.items] == [
        ("Second timer", "Running · Website · Example Customer", "warn", "12m 49s"),
        ("Review the pull request", "Website · Example Customer", "ok", "20m"),
        ("Fix the login", "Website · Example Customer", "ok", "2h 15m"),
        ("Planning", "Website · Example Customer", "ok", "2h 30m"),
    ]
    stop = data.items[0]["actions"][0]
    assert (stop.id, stop.params, stop.confirm) == ("stop", {"id": "7"}, True) and "actions" not in data.items[1]
    assert data.secondary == [{"label": "This week", "value": "5h 17m"}] and data.meta["actions_visible"] is True


def test_the_summary_counts_today_in_the_users_zone() -> None:
    data = KimaiAdapter()._summary(ENTRIES, NOW, ZoneInfo("UTC"))
    assert data.primary == {"label": "This week", "value": 5.3, "unit": "h"}
    assert data.secondary == [{"label": "Today", "value": "2h 47m"}, {"label": "Running", "value": 1}]
    # At 01:00 on Saturday in Tokyo, Friday's entries were yesterday, and one begun at 00:30 there is today although UTC still says Friday.
    after_midnight = entry(9, "2026-09-11T15:30:00+0000", "2026-09-11T15:50:00+0000", 1200, "Late call")
    tokyo = KimaiAdapter()._summary([after_midnight, *ENTRIES[1:]], datetime(2026, 9, 11, 16, 0, tzinfo=UTC), ZoneInfo("Asia/Tokyo"))
    assert tokyo.secondary == [{"label": "Today", "value": "20m"}]


def test_a_timer_begun_in_the_future_has_run_for_nothing() -> None:
    ahead = entry(8, "2026-09-11T12:26:37+0000", None, 0, "Clock of another zone")
    assert KimaiAdapter()._entries([ahead], NOW, {}).items[0]["value"] == "0s"


@respx.mock
async def test_the_filter_is_a_local_time_in_the_users_zone(ctx: Context) -> None:
    respx.get(f"{KM}/api/users/me").mock(return_value=httpx.Response(200, json={**ME, "timezone": "Europe/Berlin"}))
    route = respx.get(f"{KM}/api/timesheets").mock(return_value=httpx.Response(200, headers={"x-total-count": "4"}, json=ENTRIES))
    data = await get_adapter("kimai").fetch("summary", CONFIG, {}, ctx)
    params = route.calls.last.request.url.params
    assert route.calls.last.request.headers["Authorization"] == "Bearer made-up-token"
    # ⚠️ Measured: a begin with an offset gets 400.
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T00:00:00", params["begin"]) and params["full"] == "true"
    assert data.primary["label"] == "This week"


@respx.mock
async def test_stopping_a_timer(ctx: Context) -> None:
    stop = respx.patch(f"{KM}/api/timesheets/7/stop").mock(return_value=httpx.Response(200, json={**ENTRIES[0], "end": "2026-09-11T11:13:00+0000", "duration": 360}))
    assert await get_adapter("kimai").action("entries", "stop", {"id": "7"}, CONFIG, {}, ctx) == "Timer stopped."
    assert stop.calls.last.request.headers["Authorization"] == "Bearer made-up-token"
    respx.patch(f"{KM}/api/timesheets/99999/stop").mock(return_value=httpx.Response(404, json={"code": 404, "message": "Not found"}))
    with pytest.raises(AdapterError) as gone:
        await get_adapter("kimai").action("entries", "stop", {"id": "99999"}, CONFIG, {}, ctx)
    assert gone.value.code == "action_failed"
    respx.patch(f"{KM}/api/timesheets/8/stop").mock(return_value=httpx.Response(403, json={"code": 403, "message": "Forbidden"}))
    with pytest.raises(AuthFailed):
        await get_adapter("kimai").action("entries", "stop", {"id": "8"}, CONFIG, {}, ctx)
    with pytest.raises(AdapterError) as unknown:
        await get_adapter("kimai").action("entries", "restart", {"id": "7"}, CONFIG, {}, ctx)
    assert unknown.value.code == "no_such_action"


@respx.mock
async def test_a_missing_and_a_wrong_token(ctx: Context) -> None:
    respx.get(f"{KM}/api/users/me").mock(return_value=httpx.Response(401, text=""))
    with pytest.raises(AuthFailed):
        await get_adapter("kimai").fetch("entries", CONFIG, {}, ctx)


@respx.mock
async def test_the_connection_test(ctx: Context) -> None:
    respx.get(f"{KM}/api/version").mock(return_value=httpx.Response(200, json={"version": "2.66.0", "versionId": 26600, "copyright": "Kimai 2.66.0 by Kevin Papst."}))
    respx.get(f"{KM}/api/users/me").mock(return_value=httpx.Response(200, json=ME))
    assert await get_adapter("kimai").test(CONFIG, ctx) == "Kimai 2.66.0 answers for admin."
