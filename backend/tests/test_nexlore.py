"""nexlore 0.4.0, measured on 02.10.2026 on nexlore's test stand with its made-up vault: the shapes are the
measured ones, names and counts made up."""

from __future__ import annotations

import json
from datetime import date, datetime

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters import nexlore as module
from app.adapters.base import AdapterError, AuthFailed, Context, outbound_client

CONFIG = {"url": "http://nexlore:8470", "api_key": "nxa_example"}
BASE = "http://nexlore:8470/api/v1"
TODAY = date(2026, 10, 2)
ME_WRITE = {"account": "alex", "display_name": "Alex", "level": "write", "spaces": None, "expires_at": None, "version": "0.4.0"}
ME_READ = {**ME_WRITE, "level": "read"}
DASHBOARD = {"spaces": 2, "notes": 120, "tasks_open": 14, "tasks_overdue": 2, "tasks_today": 3, "tasks_week": 5, "inbox": 4}
COUNTS = {"open": 14, "done": 5, "cancelled": 0, "overdue": 2, "today": 3, "week": 5, "later": 0, "none": 4}


def task(path: str, line: int, text: str, due: str) -> dict:
    return {"path": path, "title": path.rsplit("/", 1)[-1].removesuffix(".md"), "line": line,
            "raw": f"- [ ] {text} 📅 {due}", "text": text, "status": "open", "due": due, "scheduled": None,
            "completed": None, "priority": 0, "tags": [], "file_hash": "9f2c"}


@pytest.fixture
def ctx() -> Context:
    return Context(outbound_client(guard=False), integration_id=1, widget_id=1, cache={})


@pytest.fixture(autouse=True)
def on_the_measured_day(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(module, "_today", lambda: TODAY)


@respx.mock
async def test_the_overview_counts_and_offers_capture_only_to_a_write_token(ctx: Context) -> None:
    dashboard = respx.get(f"{BASE}/dashboard").mock(return_value=httpx.Response(200, json=DASHBOARD))
    respx.get(f"{BASE}/me").mock(return_value=httpx.Response(200, json=ME_WRITE))
    data = await get_adapter("nexlore").fetch("overview", CONFIG, {}, ctx)
    assert data.primary == {"label": "Open tasks", "value": 14}
    assert {row["label"]: row["value"] for row in data.secondary} == {"Today": 3, "Overdue": 2, "Inbox": 4, "Notes": 120}
    assert data.status == "warn" and [action.id for action in data.actions] == ["capture"]
    request = dashboard.calls.last.request
    assert request.url.params["today"] == "2026-10-02"
    assert request.headers["Authorization"] == "Bearer nxa_example" and "nxa_" not in str(request.url)
    assert "origin" not in request.headers

    respx.get(f"{BASE}/me").mock(return_value=httpx.Response(200, json=ME_READ))
    fresh = Context(outbound_client(guard=False), integration_id=1, widget_id=1, cache={})
    assert (await get_adapter("nexlore").fetch("overview", CONFIG, {}, fresh)).actions == []


@respx.mock
async def test_due_tasks_come_overdue_first_with_a_box_and_a_link(ctx: Context) -> None:
    def answer(request: httpx.Request) -> httpx.Response:
        when = request.url.params["when"]
        items = {"overdue": [task("Home/Certificates.md", 4, "Renew the certificate", "2026-09-30")],
                 "today": [task("Home/Projects/Garden shed.md", 9, "Order the timber", "2026-10-02")]}[when]
        return httpx.Response(200, json={"total": len(items), "counts": COUNTS, "items": items})

    respx.get(f"{BASE}/tasks").mock(side_effect=answer)
    respx.get(f"{BASE}/me").mock(return_value=httpx.Response(200, json=ME_WRITE))
    data = await get_adapter("nexlore").fetch("tasks", CONFIG, {"show": "due"}, ctx)
    late, now = data.items
    assert (late["title"], late["subtitle"], late["status"]) == ("Renew the certificate", "Certificates · 2026-09-30", "bad")
    assert now["status"] == "warn"
    assert now["url"] == "http://nexlore:8470/note/Home/Projects/Garden%20shed.md"
    assert late["actions"][0]["params"] == {"path": "Home/Certificates.md", "line": 4,
                                            "raw": "- [ ] Renew the certificate 📅 2026-09-30", "hash": "9f2c"}
    assert data.status == "bad"


@respx.mock
async def test_a_read_token_gets_no_boxes(ctx: Context) -> None:
    respx.get(f"{BASE}/tasks").mock(return_value=httpx.Response(200, json={
        "total": 1, "counts": COUNTS, "items": [task("Home/Plan.md", 3, "Water the beans", "2026-10-02")]}))
    respx.get(f"{BASE}/me").mock(return_value=httpx.Response(200, json=ME_READ))
    data = await get_adapter("nexlore").fetch("tasks", CONFIG, {"show": "open"}, ctx)
    assert [row.get("actions") for row in data.items] == [None]


@respx.mock
async def test_ticking_off_and_capturing_send_the_day_and_the_time(ctx: Context) -> None:
    done = respx.post(f"{BASE}/tasks/complete").mock(return_value=httpx.Response(200, json={
        "path": "Home/Plan.md", "line": 5, "raw": "- [x] Water the beans", "conflict": None, "added": None}))
    inbox = respx.post(f"{BASE}/inbox").mock(return_value=httpx.Response(200, json={"path": "Home/Inbox.md"}))
    adapter = get_adapter("nexlore")
    params = {"path": "Home/Plan.md", "line": 5, "raw": "- [ ] Water the beans", "hash": "9f2c"}
    assert await adapter.action("tasks", "complete", params, CONFIG, {}, ctx) == "Done."
    assert json.loads(done.calls.last.request.content) == {**params, "today": "2026-10-02"}
    assert await adapter.action("overview", "capture", {"text": "[ ] call the plumber"}, CONFIG, {}, ctx) == "In the inbox: Home/Inbox.md."
    body = json.loads(inbox.calls.last.request.content)
    assert body["text"] == "[ ] call the plumber" and datetime.fromisoformat(body["now"]).tzinfo is not None


@respx.mock
async def test_a_moved_task_and_a_read_token_are_said_plainly(ctx: Context) -> None:
    respx.post(f"{BASE}/tasks/complete").mock(return_value=httpx.Response(409, json={"detail": {"code": "task_changed", "message": "x"}}))
    with pytest.raises(AdapterError, match="no longer where it was"):
        await get_adapter("nexlore").action("tasks", "complete", {"path": "a.md", "line": 1, "raw": "- [ ] a", "hash": "h"}, CONFIG, {}, ctx)
    respx.post(f"{BASE}/inbox").mock(return_value=httpx.Response(403, json={"detail": {"code": "read_only_token", "message": "x"}}))
    with pytest.raises(AdapterError, match="may only read"):
        await get_adapter("nexlore").action("overview", "capture", {"text": "x"}, CONFIG, {}, ctx)


@respx.mock
async def test_switched_off_is_told_apart_from_a_wrong_token(ctx: Context) -> None:
    respx.get(f"{BASE}/dashboard").mock(return_value=httpx.Response(401, json={"detail": {"code": "api_off", "message": "x"}}))
    with pytest.raises(AdapterError) as off:
        await get_adapter("nexlore").fetch("overview", CONFIG, {}, ctx)
    assert not isinstance(off.value, AuthFailed) and "switched off" in str(off.value)
    fresh = Context(outbound_client(guard=False), integration_id=1, widget_id=1, cache={})
    respx.get(f"{BASE}/dashboard").mock(return_value=httpx.Response(401, json={"detail": {"code": "token_invalid", "message": "x"}}))
    with pytest.raises(AuthFailed):
        await get_adapter("nexlore").fetch("overview", CONFIG, {}, fresh)


@respx.mock
async def test_changed_last_links_each_note(ctx: Context) -> None:
    respx.get(f"{BASE}/recent").mock(return_value=httpx.Response(200, json=[
        {"path": "Home/Beans.md", "title": "Beans", "space": "Home", "modified": "2026-10-02T05:12:40Z"}]))
    data = await get_adapter("nexlore").fetch("recent", CONFIG, {"limit": 3}, ctx)
    assert [(row["title"], row["subtitle"], row["when"], row["url"]) for row in data.items] == [
        ("Beans", "Home", 1790917960.0, "http://nexlore:8470/note/Home/Beans.md")]


@respx.mock
async def test_the_connection_test_names_level_and_reach(ctx: Context) -> None:
    respx.get(f"{BASE}/me").mock(return_value=httpx.Response(200, json={**ME_READ, "spaces": ["Home"]}))
    assert await get_adapter("nexlore").test(CONFIG, ctx) == "nexlore 0.4.0 answers; the token of alex reads in 1 chosen space(s)."
