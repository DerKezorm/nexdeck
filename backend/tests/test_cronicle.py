"""Cronicle, against the answers of one server (bluet/cronicle-docker, 27.10.2026).

``fixtures/cronicle_answers.json`` holds the real shapes of ``get_schedule``,
``get_active_jobs``, ``get_history`` and ``get_master_state`` for four shell
events (one failing, one slow, one disabled) and the envelope Cronicle puts
round an error: HTTP 200 with a ``code`` that is a word. Scripts and the
host name are taken out; the key is made up.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context, Unreachable, outbound_client
from app.adapters.cronicle import when

BASE = "http://cronicle.example.com:3012"
CONFIG = {"url": BASE, "api_key": "made-up-key"}
ADAPTER = get_adapter("cronicle")
ANSWERS = json.loads((Path(__file__).parent / "fixtures" / "cronicle_answers.json").read_text(encoding="utf-8"))


@pytest.fixture
def ctx() -> Context:
    return Context(outbound_client(guard=False), integration_id=1, widget_id=1, cache={})


def fresh() -> Context:
    return Context(outbound_client(guard=False), integration_id=2, widget_id=2, cache={})


def cronicle() -> None:
    for name, key in (("get_schedule", "schedule"), ("get_active_jobs", "active"), ("get_history", "history"), ("get_master_state", "master")):
        respx.get(f"{BASE}/api/app/{name}").mock(return_value=httpx.Response(200, json=ANSWERS[key]))


def titles(data) -> list[str]:  # noqa: ANN001
    return [row["title"] for row in data.items]


@respx.mock
async def test_the_overview_counts_failing_events_running_jobs_and_the_days_figures(ctx: Context) -> None:
    cronicle()
    data = await ADAPTER.fetch("overview", CONFIG, {}, ctx)
    assert data.primary == {"label": "Failing", "value": 1}
    assert data.secondary == [{"label": "Events", "value": 4}, {"label": "Running", "value": 1}, {"label": "Completed today", "value": 4},
                              {"label": "Failed today", "value": 1}]
    assert data.status == "bad" and data.metrics == {"failing": 1.0, "running": 1.0} and data.link == BASE
    assert respx.calls[0].request.headers["x-api-key"] == "made-up-key", "the key travels in a header, not in the address"
    assert "api_key" not in str(respx.calls[0].request.url)


@respx.mock
async def test_the_events_card_puts_the_failing_first_and_says_how_each_is_timed(ctx: Context) -> None:
    cronicle()
    data = await ADAPTER.fetch("events", CONFIG, {}, ctx)
    assert titles(data) == ["Cleanup temp files", "Nightly backup", "Slow report", "Old sync"]
    cleanup, nightly, slow, old = data.items
    assert cleanup["status"] == "bad" and cleanup["subtitle"] == "Failed · Every hour · :00, :30"
    assert nightly["status"] == "ok" and nightly["subtitle"] == "Daily · 03:15"
    assert slow["subtitle"] == "Daily · 06:00"
    assert old["status"] == "unknown" and old["subtitle"] == "Disabled · On demand", "a disabled event is not a failure"
    assert cleanup["actions"] == [{"id": "run", "label": "Run now", "icon": "play", "confirm": True, "params": {"id": ANSWERS["schedule"]["rows"][0]["id"]}}]
    assert data.secondary == [{"label": "Failing", "value": 1}, {"label": "Events", "value": 4}] and data.metrics == {"failing": 1.0}
    only = await ADAPTER.fetch("events", CONFIG, {"only_failing": True}, fresh())
    assert titles(only) == ["Cleanup temp files"]


def test_an_event_that_never_ran_is_unknown_and_a_disabled_failure_does_not_count() -> None:
    events = [{"id": "a", "title": "New", "enabled": 1, "timing": {"minutes": [5]}}, {"id": "b", "title": "Off", "enabled": 0, "timing": {}}]
    data = ADAPTER.events_card(events, {"jobCodes": {"b": 1}}, {})
    assert [(row["title"], row["status"], row["subtitle"]) for row in data.items] == [
        ("New", "unknown", "Never run · Every hour · :05"), ("Off", "unknown", "Disabled · On demand")]
    assert data.status == "ok" and data.secondary[0] == {"label": "Failing", "value": 0}


def test_timing_is_said_in_parts() -> None:
    assert when({}) == when(False) == ["On demand"]
    assert when({"hours": [3], "minutes": [15]}) == ["Daily", "03:15"]
    assert when({"weekdays": [1, 3], "hours": [6], "minutes": [0]}) == ["Mon, Wed", "06:00"]
    assert when({"minutes": [0, 30]}) == ["Every hour", ":00, :30"]
    assert when({"hours": [1, 2], "minutes": [0, 30]}) == ["Daily", "01:00, 01:30, 02:00 +1"]
    assert when({"days": [1, 15], "months": [1, 7], "hours": [4], "minutes": [0]}) == ["day 1, 15", "Jan, Jul", "04:00"]
    assert when({"weekdays": [0], "minutes": [10]}) == ["Sun", "Every hour", ":10"]


@respx.mock
async def test_the_runs_card_shows_the_running_job_then_the_latest_with_the_reason(ctx: Context) -> None:
    cronicle()
    data = await ADAPTER.fetch("runs", CONFIG, {}, ctx)
    assert data.items[0]["title"] == "Slow report" and data.items[0]["status"] == "ok" and data.items[0]["subtitle"].startswith("Running · ")
    failed = [row for row in data.items if row["status"] == "bad"]
    assert len(failed) == 1 and failed[0]["title"] == "Cleanup temp files"
    assert failed[0]["subtitle"] == "Failed · Script exited with code: 1 · 0s" and failed[0]["value"]
    assert data.status == "warn" and data.secondary == [{"label": "Running", "value": 1}]
    assert len(data.items) == 5, "the running job and the four that finished"
    only = await ADAPTER.fetch("runs", CONFIG, {"only_failing": True}, fresh())
    assert titles(only) == ["Cleanup temp files"], "failures only: no running job, no success"


def test_a_job_that_reports_progress_draws_it() -> None:
    active = {"j": {"event_title": "Import", "time_start": 100.0, "now": 160.0, "progress": 0.25}}
    data = ADAPTER.runs_card(active, [], {})
    assert data.items[0]["progress"] == 25.0 and data.items[0]["subtitle"] == "Running · 1m"


@respx.mock
async def test_the_test_counts_the_events(ctx: Context) -> None:
    cronicle()
    assert await ADAPTER.test(CONFIG, ctx) == "Cronicle answers, 4 events scheduled."


@respx.mock
async def test_an_error_is_a_code_in_a_200_answer_and_each_kind_is_told_apart(ctx: Context) -> None:
    route = respx.get(f"{BASE}/api/app/get_schedule").mock(return_value=httpx.Response(200, json=ANSWERS["bad_key"]))
    with pytest.raises(AuthFailed) as wrong:
        await ADAPTER.test(CONFIG, ctx)
    assert "rejected the API key" in wrong.value.message and "Admin > API Keys" in wrong.value.hint
    route.mock(return_value=httpx.Response(200, json=ANSWERS["no_key"]))
    with pytest.raises(AuthFailed) as missing:
        await ADAPTER.test({"url": BASE}, ctx)
    assert "wants an API key" in missing.value.message
    route.mock(return_value=httpx.Response(200, json=ANSWERS["not_master"]))
    with pytest.raises(AdapterError) as starting:
        await ADAPTER.test(CONFIG, ctx)
    assert starting.value.code == "not_master" and not isinstance(starting.value, AuthFailed)
    route.mock(return_value=httpx.Response(200, json={"hello": "not cronicle"}))
    with pytest.raises(AdapterError) as elsewhere:
        await ADAPTER.test(CONFIG, ctx)
    assert elsewhere.value.code == "not_cronicle"


@respx.mock
async def test_an_unreachable_cronicle(ctx: Context) -> None:
    respx.get(f"{BASE}/api/app/get_schedule").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(Unreachable):
        await ADAPTER.fetch("events", CONFIG, {}, ctx)


@respx.mock
async def test_the_run_button_runs_one_event_and_says_when_it_is_gone(ctx: Context) -> None:
    route = respx.post(f"{BASE}/api/app/run_event").mock(return_value=httpx.Response(200, json=ANSWERS["run"]))
    assert await ADAPTER.action("events", "run", {"id": "emvrd675003"}, CONFIG, {}, ctx) == "The event is running."
    assert json.loads(route.calls.last.request.content) == {"id": "emvrd675003"}
    assert route.calls.last.request.headers["x-api-key"] == "made-up-key"
    route.mock(return_value=httpx.Response(200, json=ANSWERS["unknown_event"]))
    with pytest.raises(AdapterError) as gone:
        await ADAPTER.action("events", "run", {"id": "nope"}, CONFIG, {}, ctx)
    assert gone.value.code == "not_found"
    route.mock(return_value=httpx.Response(200, json=ANSWERS["already_running"]))
    with pytest.raises(AdapterError) as busy:
        await ADAPTER.action("events", "run", {"id": "emvrd675003"}, CONFIG, {}, ctx)
    assert busy.value.code == "already_running"
    route.mock(return_value=httpx.Response(200, json={"code": "user", "description": "User is not an administrator: undefined"}))
    with pytest.raises(AuthFailed) as refused:
        await ADAPTER.action("events", "run", {"id": "emvrd675003"}, CONFIG, {}, ctx)
    assert "Run Events" in refused.value.hint


@respx.mock
async def test_an_event_id_is_checked_before_anything_is_sent(ctx: Context) -> None:
    route = respx.post(f"{BASE}/api/app/run_event").mock(return_value=httpx.Response(200, json=ANSWERS["run"]))
    for bad in ("", "../x", "a b", "a" * 80, None):
        with pytest.raises(AdapterError) as refused:
            await ADAPTER.action("events", "run", {"id": bad}, CONFIG, {}, ctx)
        assert refused.value.code == "bad_param", bad
    assert route.call_count == 0
