"""Vikunja, against the answers of a live Vikunja 2.6.0 (11.09.2026)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context
from app.adapters.vikunja import VikunjaAdapter

VK = "http://vikunja.example.com"
CONFIG = {"url": VK, "token": "tk_made-up", "timezone": "Europe/Berlin"}
NOW = datetime(2026, 9, 11, 11, 0, tzinfo=UTC)


def task(identifier: int, title: str, due: str, project: int = 2, priority: int = 0, done: bool = False) -> dict[str, Any]:
    return {"id": identifier, "title": title, "description": "", "done": done, "done_at": "0001-01-01T00:00:00Z", "due_date": due, "reminders": None,
            "project_id": project, "repeat_after": 0, "repeat_mode": 0, "priority": priority, "start_date": "0001-01-01T00:00:00Z",
            "end_date": "0001-01-01T00:00:00Z", "assignees": None, "labels": None, "percent_done": 0, "identifier": f"#{identifier}",
            "index": identifier, "is_favorite": False, "created": "2026-09-11T11:00:13Z", "updated": "2026-09-11T11:00:13Z", "bucket_id": 0}


TASKS = [
    task(1, "Renew the certificate", "2026-09-10T09:00:06Z", priority=4),
    task(2, "Swap the backup disk", "2026-09-11T14:00:06Z"),
    task(6, "Late tonight in UTC", "2026-09-11T22:30:00Z"),
    task(3, "Pay the electricity bill", "2026-09-14T11:00:06Z", project=3, priority=3),
    task(4, "Buy light bulbs", "0001-01-01T00:00:00Z", project=3),
]
PROJECTS = [{"id": 1, "title": "Inbox"}, {"id": 2, "title": "Homelab"}, {"id": 3, "title": "Household"}, {"id": -2, "title": "My Open Tasks"}]


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


def test_today_depends_on_the_time_zone() -> None:
    """Measured: the task due at 22:30 UTC was today in UTC and tomorrow in Europe/Berlin."""
    names = {2: "Homelab", 3: "Household"}
    in_utc = VikunjaAdapter._due(TASKS, names, NOW, ZoneInfo("UTC"), VK, {"limit": 10})
    in_berlin = VikunjaAdapter._due(TASKS, names, NOW, ZoneInfo("Europe/Berlin"), VK, {"limit": 10})
    assert [(row["title"], row["subtitle"], row["value"]) for row in in_utc.items][1:3] == [
        ("Swap the backup disk", "Today · Homelab", "14:00"), ("Late tonight in UTC", "Today · Homelab", "22:30")]
    assert [(row["title"], row["subtitle"], row["value"]) for row in in_berlin.items] == [
        ("Renew the certificate", "Overdue · Urgent · Homelab", "1 d"),
        ("Swap the backup disk", "Today · Homelab", "16:00"),
        ("Late tonight in UTC", "Tomorrow · Homelab", "00:30"),
        ("Pay the electricity bill", "2026-09-14 · High · Household", ""),
    ]
    assert [row["status"] for row in in_berlin.items] == ["bad", "warn", "ok", "ok"]
    # "0001-01-01T00:00:00Z" is no date at all.
    assert "Buy light bulbs" not in [row["title"] for row in in_berlin.items]
    assert in_berlin.items[0]["url"] == f"{VK}/tasks/1" and in_berlin.secondary == [{"label": "Overdue", "value": 1}] and in_berlin.status == "bad"


@respx.mock
async def test_the_due_list_asks_tasks_not_tasks_all(ctx: Context) -> None:
    tasks = respx.get(f"{VK}/api/v1/tasks").mock(return_value=httpx.Response(200, json=TASKS[:3]))
    respx.get(f"{VK}/api/v1/projects").mock(return_value=httpx.Response(200, json=PROJECTS))
    gone = respx.get(f"{VK}/api/v1/tasks/all").mock(return_value=httpx.Response(401, json={"code": 11, "message": "missing, malformed, expired or otherwise invalid token provided"}))
    data = await get_adapter("vikunja").fetch("due", CONFIG, {"days": 2, "limit": 10}, ctx)
    assert not gone.called and tasks.calls.last.request.headers["Authorization"] == "Bearer tk_made-up"
    assert dict(tasks.calls.last.request.url.params) == {"filter": "done = false && due_date < now/d+3d", "filter_timezone": "Europe/Berlin",
                                                         "sort_by": "due_date", "order_by": "asc", "per_page": "50"}
    assert data.items[0]["subtitle"].endswith("Homelab")


@respx.mock
async def test_the_summary_counts_from_the_page_header(ctx: Context) -> None:
    counts = {"done = false && due_date < now": "1", "done = false && due_date >= now && due_date < now/d+1d": "1", "done = false": "5"}
    route = respx.get(f"{VK}/api/v1/tasks").mock(side_effect=lambda request: httpx.Response(
        200, headers={"x-pagination-result-count": "1", "x-pagination-total-pages": counts[request.url.params["filter"]]}, json=TASKS[:1]))
    data = await get_adapter("vikunja").fetch("summary", CONFIG, {}, ctx)
    assert route.call_count == 3 and all(call.request.url.params["per_page"] == "1" for call in route.calls)
    assert data.primary == {"label": "Overdue", "value": 1}
    assert data.secondary == [{"label": "Due today", "value": 1}, {"label": "Open", "value": 5}] and data.status == "bad"


@respx.mock
async def test_nothing_matching_counts_zero(ctx: Context) -> None:
    respx.get(f"{VK}/api/v1/tasks").mock(return_value=httpx.Response(200, headers={"x-pagination-result-count": "0", "x-pagination-total-pages": "0"}, json=[]))
    data = await get_adapter("vikunja").fetch("summary", CONFIG, {}, ctx)
    assert data.primary == {"label": "Overdue", "value": 0} and data.status == "ok"


@respx.mock
async def test_a_rejected_token_and_a_zone_that_does_not_exist(ctx: Context) -> None:
    respx.get(f"{VK}/api/v1/tasks").mock(return_value=httpx.Response(401, json={"code": 11, "message": "missing, malformed, expired or otherwise invalid token provided"}))
    with pytest.raises(AuthFailed):
        await get_adapter("vikunja").fetch("summary", CONFIG, {}, ctx)
    with pytest.raises(AdapterError) as zone:
        await get_adapter("vikunja").fetch("due", {**CONFIG, "timezone": "Middle/Earth"}, {}, ctx)
    assert zone.value.code == "bad_timezone"


@respx.mock
async def test_the_connection_test(ctx: Context) -> None:
    respx.get(f"{VK}/api/v1/info").mock(return_value=httpx.Response(200, json={"version": "v2.6.0", "frontend_url": f"{VK}/", "max_items_per_page": 50}))
    respx.get(f"{VK}/api/v1/tasks").mock(return_value=httpx.Response(200, headers={"x-pagination-total-pages": "5"}, json=TASKS[:1]))
    assert await get_adapter("vikunja").test(CONFIG, ctx) == "Vikunja 2.6.0 answers with 5 open tasks."
