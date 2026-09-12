"""Watchtower, against the answers of a live Watchtower 1.22.1 (nickfedor/watchtower, 11.09.2026)."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context, Unreachable
from app.adapters.watchtower import WatchtowerAdapter

WT = "http://watchtower.example.com:8080"
CONFIG = {"url": WT, "token": "made-up-token"}
#: The answer after a run that recreated one of three containers.
STATUS = {"api_version": "v1", "summary": {"failed": 0, "restarted": 0, "scanned": 3, "skipped": 0, "updated": 1},
          "timestamp": "2026-09-11T21:01:20Z"}
NOW = datetime(2026, 9, 11, 21, 13, 20, tzinfo=UTC).timestamp()


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


def test_the_last_run_with_what_it_updated_and_when() -> None:
    data = WatchtowerAdapter._summary(STATUS, now=NOW)
    assert data.primary == {"label": "Updated", "value": 1, "unit": "/ 3"}
    assert data.secondary == [{"label": "Failed", "value": 0}, {"label": "Last run", "value": "12 min"}]
    assert data.status == "ok" and data.metrics == {"updated": 1.0, "failed": 0.0}
    run = data.actions[0]
    assert (run.id, run.confirm) == ("run", True)


def test_a_failed_update_turns_the_card_red() -> None:
    failed = {**STATUS, "summary": {**STATUS["summary"], "failed": 2, "updated": 0}}
    data = WatchtowerAdapter._summary(failed, now=NOW)
    assert data.status == "bad" and data.secondary[0] == {"label": "Failed", "value": 2}
    assert data.metrics == {"updated": 0.0, "failed": 2.0}


@respx.mock
async def test_before_the_first_run_there_is_no_status(ctx: Context) -> None:
    """⚠️ Measured: 204 without a body until the first run, and again after every restart."""
    route = respx.get(f"{WT}/v1/status").mock(return_value=httpx.Response(204))
    data = await get_adapter("watchtower").fetch("summary", CONFIG, {}, ctx)
    assert route.calls.last.request.headers["Authorization"] == "Bearer made-up-token"
    assert data.status == "unknown" and data.primary == {"label": "Updated", "value": None}
    assert data.meta["empty"] == "No run since Watchtower started." and [action.id for action in data.actions] == ["run"]


@respx.mock
async def test_the_card_reads_the_status(ctx: Context) -> None:
    respx.get(f"{WT}/v1/status").mock(return_value=httpx.Response(200, json=STATUS))
    data = await get_adapter("watchtower").fetch("summary", CONFIG, {}, ctx)
    assert data.primary == {"label": "Updated", "value": 1, "unit": "/ 3"} and data.secondary[0] == {"label": "Failed", "value": 0}


@respx.mock
async def test_a_rejected_token(ctx: Context) -> None:
    respx.get(f"{WT}/v1/status").mock(return_value=httpx.Response(401, text="missing or invalid API Key"))
    with pytest.raises(AuthFailed):
        await get_adapter("watchtower").fetch("summary", CONFIG, {}, ctx)


@respx.mock
async def test_a_status_endpoint_that_is_switched_off(ctx: Context) -> None:
    """⚠️ Measured: with only update in WATCHTOWER_HTTP_API_ENDPOINTS, /v1/status is 404."""
    respx.get(f"{WT}/v1/status").mock(return_value=httpx.Response(404, text="Not Found"))
    with pytest.raises(AdapterError) as off:
        await get_adapter("watchtower").fetch("summary", CONFIG, {}, ctx)
    assert off.value.code == "endpoint_off" and "metrics" in off.value.hint


@respx.mock
async def test_an_answer_that_is_not_watchtower(ctx: Context) -> None:
    respx.get(f"{WT}/v1/status").mock(return_value=httpx.Response(200, json={"status": "ok"}))
    with pytest.raises(AdapterError) as other:
        await get_adapter("watchtower").fetch("summary", CONFIG, {}, ctx)
    assert other.value.code == "not_watchtower"


@respx.mock
async def test_an_unreachable_watchtower(ctx: Context) -> None:
    respx.get(f"{WT}/v1/status").mock(side_effect=httpx.ConnectError("connection refused"))
    with pytest.raises(Unreachable):
        await get_adapter("watchtower").fetch("summary", CONFIG, {}, ctx)


@respx.mock
async def test_starting_a_run(ctx: Context) -> None:
    run = respx.post(f"{WT}/v1/update", params={"async": "true"}).mock(
        return_value=httpx.Response(202, text="Accepted", headers={"content-type": "text/plain; charset=utf-8"}))
    assert await get_adapter("watchtower").action("summary", "run", {}, CONFIG, {}, ctx) == "Watchtower has started an update run."
    assert run.calls.last.request.headers["Authorization"] == "Bearer made-up-token"
    # ⚠️ Measured: a second run while one is going.
    run.mock(return_value=httpx.Response(429, headers={"Retry-After": "30"},
                                         json={"api_version": "v1", "error": "another update is already running", "timestamp": "2026-09-11T21:01:23Z"}))
    with pytest.raises(AdapterError) as busy:
        await get_adapter("watchtower").action("summary", "run", {}, CONFIG, {}, ctx)
    assert busy.value.code == "action_failed" and "30 seconds" in busy.value.hint
    run.mock(return_value=httpx.Response(404, text="Not Found"))
    with pytest.raises(AdapterError) as off:
        await get_adapter("watchtower").action("summary", "run", {}, CONFIG, {}, ctx)
    assert off.value.code == "endpoint_off" and "update" in off.value.hint
    run.mock(return_value=httpx.Response(401, text="missing or invalid API Key"))
    with pytest.raises(AuthFailed):
        await get_adapter("watchtower").action("summary", "run", {}, CONFIG, {}, ctx)
    with pytest.raises(AdapterError) as unknown:
        await get_adapter("watchtower").action("summary", "restart", {}, CONFIG, {}, ctx)
    assert unknown.value.code == "no_such_action"


@respx.mock
async def test_the_connection_test(ctx: Context) -> None:
    route = respx.get(f"{WT}/v1/status").mock(return_value=httpx.Response(200, json=STATUS))
    assert await get_adapter("watchtower").test(CONFIG, ctx) == "Watchtower answers. Its last run updated 1 of 3 containers."
    route.mock(return_value=httpx.Response(204))
    assert await get_adapter("watchtower").test(CONFIG, ctx) == "Watchtower answers. It has not run since it started."
