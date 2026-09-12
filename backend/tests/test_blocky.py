"""Blocky, against the answers of a live Blocky 0.35.0 (11.09.2026)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, Context, Unreachable
from app.adapters.blocky import BlockyAdapter

FIXTURES = Path(__file__).parent / "fixtures"
BL = "http://blocky.example.com:4000"
CONFIG = {"url": BL}


def fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


STATS = fixture("blocky_stats.json")
ENABLED = fixture("blocky_status.json")
PAUSED = fixture("blocky_status_paused.json")


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


def test_the_blocking_card_shows_the_share_the_queries_and_a_pause_button() -> None:
    data = BlockyAdapter._blocking(ENABLED, STATS)
    # Six of eleven queries were blocked; filtered answers would not count.
    assert data.primary == {"label": "Blocked", "value": 54.5, "unit": "%"}
    assert data.secondary == [{"label": "Queries", "value": 11}, {"label": "Blocked", "value": 6}]
    assert [(action.id, action.label, action.params) for action in data.actions] == [("pause", "Pause 5 min", {})]
    assert data.meta["ring"] == [{"label": "Blocked", "value": 6.0}, {"label": "Allowed", "value": 5.0}]
    assert data.metrics == {"queries": 11.0, "blocked_percent": 54.5} and data.status == "ok"


def test_a_paused_blocky_says_when_blocking_comes_back() -> None:
    data = BlockyAdapter._blocking(PAUSED, STATS)
    assert data.status == "warn" and data.primary["label"] == "Blocking paused"
    assert data.secondary == [{"label": "Queries", "value": 11}, {"label": "Back on in", "value": "4m 59s"}]
    assert [action.id for action in data.actions] == ["enable"]
    forever = BlockyAdapter._blocking({"enabled": False, "disabledGroups": ["ads"]}, STATS)
    assert forever.secondary == [{"label": "Queries", "value": 11}]


def test_no_queries_is_no_share() -> None:
    quiet = {**STATS, "summary": {**STATS["summary"], "queries": 0, "blocked": 0}}
    data = BlockyAdapter._blocking(ENABLED, quiet)
    assert data.primary == {"label": "Blocked", "value": None, "unit": ""}
    assert data.metrics == {"queries": 0.0} and data.meta == {}


def test_the_domains_blocked_most_often() -> None:
    data = BlockyAdapter._top(STATS, {})
    assert [(row["title"], row["value"], row["status"]) for row in data.items] == [
        ("ads.example.com", 3, "bad"), ("a.doubleclick.example", 1, "bad"), ("social.example.org", 1, "bad"), ("tracker.example.net", 1, "bad")]
    assert data.secondary == [{"label": "Blocked", "value": 6}]
    assert [row["title"] for row in BlockyAdapter._top(STATS, {"limit": 2}).items] == ["ads.example.com", "a.doubleclick.example"]
    assert BlockyAdapter._top({"summary": {}, "topBlockedDomains": []}, {}).meta["empty"] == "Nothing was blocked in the last 24 hours."


@respx.mock
async def test_the_cards_read_statistics_and_status_without_credentials(ctx: Context) -> None:
    stats = respx.get(f"{BL}/api/stats").mock(return_value=httpx.Response(200, json=STATS))
    respx.get(f"{BL}/api/blocking/status").mock(return_value=httpx.Response(200, json=ENABLED))
    data = await get_adapter("blocky").fetch("blocking", CONFIG, {}, ctx)
    assert data.primary["value"] == 54.5
    # ⚠️ Measured: the API has no sign-in, so nothing is sent.
    assert "Authorization" not in stats.calls.last.request.headers
    top = await get_adapter("blocky").fetch("top", CONFIG, {"limit": 1}, ctx)
    assert [row["title"] for row in top.items] == ["ads.example.com"]


@respx.mock
async def test_pausing_and_enabling_check_the_status_afterwards(ctx: Context) -> None:
    """⚠️ Measured: both answer 200 with an empty body, so only the status says it happened."""
    disable = respx.get(f"{BL}/api/blocking/disable").mock(return_value=httpx.Response(200, text=""))
    status = respx.get(f"{BL}/api/blocking/status").mock(return_value=httpx.Response(200, json=PAUSED))
    assert await get_adapter("blocky").action("blocking", "pause", {}, CONFIG, {}, ctx) == "Blocking paused for five minutes."
    assert dict(disable.calls.last.request.url.params) == {"duration": "5m"} and status.called
    enable = respx.get(f"{BL}/api/blocking/enable").mock(return_value=httpx.Response(200, text=""))
    respx.get(f"{BL}/api/blocking/status").mock(return_value=httpx.Response(200, json=ENABLED))
    assert await get_adapter("blocky").action("blocking", "enable", {}, CONFIG, {}, ctx) == "Blocking enabled."
    assert enable.called


@respx.mock
async def test_the_refusals_of_pausing(ctx: Context) -> None:
    adapter = get_adapter("blocky")
    respx.get(f"{BL}/api/blocking/disable").mock(return_value=httpx.Response(400, text='time: invalid duration "soon"'))
    with pytest.raises(AdapterError) as bad:
        await adapter.action("blocking", "pause", {}, CONFIG, {}, ctx)
    assert bad.value.code == "action_failed" and "invalid duration" in bad.value.message
    respx.get(f"{BL}/api/blocking/disable").mock(return_value=httpx.Response(200, text=""))
    respx.get(f"{BL}/api/blocking/status").mock(return_value=httpx.Response(200, json=ENABLED))
    with pytest.raises(AdapterError) as unchanged:
        await adapter.action("blocking", "pause", {}, CONFIG, {}, ctx)
    assert (unchanged.value.code, unchanged.value.message) == ("action_failed", "Blocky answered, but blocking did not change.")
    with pytest.raises(AdapterError) as unknown:
        await adapter.action("blocking", "flush", {}, CONFIG, {}, ctx)
    assert unknown.value.code == "no_such_action"


@respx.mock
async def test_statistics_switched_off(ctx: Context) -> None:
    """Measured with statistics.enable: false."""
    respx.get(f"{BL}/api/stats").mock(return_value=httpx.Response(503, text="statistics are disabled\n"))
    with pytest.raises(AdapterError) as off:
        await get_adapter("blocky").fetch("blocking", CONFIG, {}, ctx)
    assert off.value.code == "no_statistics" and "statistics.enable" in off.value.hint


@respx.mock
async def test_an_address_that_is_not_blocky(ctx: Context) -> None:
    respx.get(f"{BL}/api/stats").mock(return_value=httpx.Response(200, json=STATS))
    respx.get(f"{BL}/api/blocking/status").mock(return_value=httpx.Response(200, json={"status": "ok"}))
    with pytest.raises(AdapterError) as wrong:
        await get_adapter("blocky").fetch("blocking", CONFIG, {}, ctx)
    assert wrong.value.code == "not_blocky"
    respx.get(f"{BL}/api/stats").mock(return_value=httpx.Response(200, text="<html></html>"))
    # A context of its own: the first fetch kept the statistics for ten seconds, as it should.
    fresh = Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})
    with pytest.raises(AdapterError) as page:
        await get_adapter("blocky").fetch("top", CONFIG, {}, fresh)
    assert page.value.code == "not_json"


@respx.mock
async def test_a_blocky_that_does_not_answer(ctx: Context) -> None:
    respx.get(f"{BL}/api/stats").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(Unreachable):
        await get_adapter("blocky").fetch("blocking", CONFIG, {}, ctx)


@respx.mock
async def test_the_connection_test(ctx: Context) -> None:
    respx.get(f"{BL}/api/blocking/status").mock(return_value=httpx.Response(200, json=ENABLED))
    respx.get(f"{BL}/api/stats").mock(return_value=httpx.Response(200, json=STATS))
    assert await get_adapter("blocky").test(CONFIG, ctx) == "Blocky answers; blocking is on, 11 queries in the last 24 hours."
