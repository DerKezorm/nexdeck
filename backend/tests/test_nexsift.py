"""nexsift 0.5.0, measured on 02.10.2026 against a fresh installation: the
shapes are the measured ones, the counts and names made up."""

from __future__ import annotations

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context, outbound_client

CONFIG = {"url": "http://nexsift:8490", "api_key": "nxs_example"}
BASE = "http://nexsift:8490/api/v1"
STATUS = {"version": "0.5.0", "unread": 7, "critical_open": 1, "warnings_unread": 2, "lines": 40,
          "messages_today": 23, "sources": 9, "targets_failing": 0, "last_message_at": "2026-10-02T06:10:00+00:00"}
THREADS = [
    {"id": 3, "title": "Backup failed", "source": "Duplicati", "priority": "crit", "state": "unread", "count": 2,
     "first_at": "2026-10-02T05:00:00", "last_at": "2026-10-02T06:00:00", "resolved": False},
    {"id": 2, "title": "Disk hot", "source": "Scrutiny", "priority": "crit", "state": "read", "count": 1,
     "first_at": "2026-10-01T05:00:00", "last_at": "2026-10-01T06:00:00", "resolved": True},
]


@pytest.fixture
def ctx() -> Context:
    return Context(outbound_client(guard=False), integration_id=1, widget_id=1, cache={})


@respx.mock
async def test_the_inbox_counts_and_turns_red_for_an_open_critical_line(ctx: Context) -> None:
    respx.get(f"{BASE}/status").mock(return_value=httpx.Response(200, json=STATUS))
    data = await get_adapter("nexsift").fetch("inbox", CONFIG, {}, ctx)
    assert data.primary == {"label": "Unread", "value": 7}
    assert {row["label"]: row["value"] for row in data.secondary} == {"Critical": 1, "Warnings": 2, "Today": 23, "Sources": 9}
    assert data.status == "bad"
    request = respx.calls.last.request
    assert request.headers["Authorization"] == "Bearer nxs_example" and "nxs_" not in str(request.url)


@respx.mock
async def test_lines_show_source_count_and_time_and_a_resolved_one_is_green(ctx: Context) -> None:
    route = respx.get(f"{BASE}/threads").mock(return_value=httpx.Response(200, json=THREADS))
    data = await get_adapter("nexsift").fetch("threads", CONFIG, {"view": "crit", "limit": 5}, ctx)
    first, second = data.items
    assert (first["title"], first["subtitle"], first["status"]) == ("Backup failed", "Duplicati · 2 messages", "bad")
    assert first["when"] == 1790920800.0  # 2026-10-02 06:00 UTC
    assert second["status"] == "ok"
    assert dict(route.calls.last.request.url.params) == {"view": "crit", "limit": "5"}


@respx.mock
async def test_switched_off_keys_are_told_apart_from_a_wrong_key(ctx: Context) -> None:
    respx.get(f"{BASE}/status").mock(return_value=httpx.Response(403, json={"detail": {"code": "api_keys_off", "message": "API keys are switched off in this installation."}}))
    with pytest.raises(AdapterError) as off:
        await get_adapter("nexsift").fetch("inbox", CONFIG, {}, ctx)
    assert not isinstance(off.value, AuthFailed) and "switched off" in str(off.value)
    ctx = Context(outbound_client(guard=False), integration_id=1, widget_id=1, cache={})
    respx.get(f"{BASE}/status").mock(return_value=httpx.Response(401, json={"detail": {"code": "api_key_invalid", "message": "This API key is not valid."}}))
    with pytest.raises(AuthFailed):
        await get_adapter("nexsift").fetch("inbox", CONFIG, {}, ctx)
