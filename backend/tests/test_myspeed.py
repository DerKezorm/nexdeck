"""MySpeed, against the answers of a live MySpeed 1.0.9 (27.10.2026)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context, Unreachable
from app.adapters.myspeed import MyspeedAdapter

FIXTURES = Path(__file__).parent / "fixtures"
MS = "http://myspeed.example.com:5216"
CONFIG = {"url": MS, "password": "made-up-password"}


def fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


TESTS = fixture("myspeed_speedtests.json")
STATISTICS = fixture("myspeed_statistics.json")
SETTINGS = fixture("myspeed_config.json")
VERSION = fixture("myspeed_version.json")
IDLE = {"paused": False, "running": False}
#: Half an hour after the newest test of the fixture.
NOW = datetime(2026, 10, 27, 18, 49, 53, 541000, UTC).timestamp()


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


def fresh(number: int) -> Context:
    return Context(httpx.AsyncClient(), integration_id=number, widget_id=1, cache={})


def test_the_latest_card_takes_the_newest_test_that_worked() -> None:
    data = MyspeedAdapter._latest(TESTS, IDLE, {"download": 100.0, "upload": 1.0, "ping": 100.0}, now=NOW)
    assert data.primary == {"label": "Download", "metric": "download", "value": 566.5, "unit": "Mbps"}
    assert data.secondary[:3] == [{"label": "Upload", "metric": "upload", "value": 4.7, "unit": "Mbps"}, {"label": "Ping", "value": 39, "unit": "ms"},
                                  {"label": "Tested", "value": "30 min"}]
    assert data.status == "ok" and data.metrics == {"download": 566.46, "upload": 4.66, "ping": 39.0}
    run = data.actions[0]
    assert (run.id, run.label, run.confirm) == ("run", "Run test now", True)


def test_a_speed_below_what_myspeed_expects_is_yellow() -> None:
    """The expected values are MySpeed's own (``/api/config``): 100 down, 50 up, 25 ms ping. The fixture's upload of 4.66 misses them."""
    data = MyspeedAdapter._latest(TESTS, IDLE, {"download": 100.0, "upload": 50.0, "ping": 25.0}, now=NOW)
    assert data.status == "warn" and data.meta["below_expected"] == ["upload", "ping"]
    assert MyspeedAdapter._latest(TESTS, IDLE, {}, now=NOW).status == "ok", "without expected values nothing is missed"


def test_a_failed_test_is_a_word_and_never_minus_one() -> None:
    """⚠️ Measured: a failed test is a row with -1 in ping, download and upload and an ``error``."""
    failed_on_top = [{**TESTS[2], "id": 4, "created": "2026-10-27T19:00:00.000Z"}, *TESTS]
    data = MyspeedAdapter._latest(failed_on_top, IDLE, {}, now=NOW)
    assert data.primary["value"] == 566.5 and data.status == "warn"
    assert {"label": "Last test", "value": "Failed"} in data.secondary
    only_failed = MyspeedAdapter._latest([TESTS[2]], IDLE, {}, now=NOW)
    assert only_failed.status == "warn" and only_failed.primary["value"] is None and "Failed · Validation error" in only_failed.secondary[0]["value"]
    assert only_failed.metrics == {}
    nothing = MyspeedAdapter._latest([], IDLE, {})
    assert nothing.status == "unknown" and nothing.secondary[0]["value"] == "No test yet"


def test_the_button_is_not_offered_while_a_test_runs_or_the_tests_are_paused() -> None:
    running = MyspeedAdapter._latest(TESTS, {"paused": False, "running": True}, {}, now=NOW)
    assert running.actions == [] and {"label": "State", "value": "Test running"} in running.secondary
    paused = MyspeedAdapter._latest(TESTS, {"paused": True, "running": False}, {}, now=NOW)
    assert paused.actions == [] and {"label": "State", "value": "Paused"} in paused.secondary


def test_the_averages_of_a_period() -> None:
    data = MyspeedAdapter._statistics(STATISTICS, 1)
    rows = {row["label"]: row for row in data.secondary}
    assert (rows["Average download"]["value"], rows["Average upload"]["value"], rows["Average ping"]["value"]) == (430.5, 9.8, 34)
    assert (rows["Lowest download"]["value"], rows["Highest download"]["value"]) == (294.5, 566.5)
    # Three tests, one of them failed: two worked.
    assert rows["Tests"]["value"] == 2 and rows["Failed"]["value"] == 1 and data.status == "ok"
    empty = MyspeedAdapter._statistics({"tests": {"total": 0, "failed": 0}, "ping": {"min": None, "max": None, "avg": None},
                                        "download": {"min": None, "max": None, "avg": None}, "upload": {"min": None, "max": None, "avg": None}}, 7)
    assert empty.status == "unknown" and {row["label"]: row["value"] for row in empty.secondary}["Average download"] is None
    mostly_failed = MyspeedAdapter._statistics({**STATISTICS, "tests": {"total": 4, "failed": 3}}, 1)
    assert mostly_failed.status == "warn"


def test_the_history_draws_failed_tests_as_gaps_oldest_first() -> None:
    data = MyspeedAdapter._history(TESTS, {}, 7)
    lines = {line["key"]: line["points"] for line in data.meta["lines"]}
    assert [value for _at, value in lines["download"]] == [None, 294.47, 566.46]
    assert [value for _at, value in lines["upload"]] == [None, 14.86, 4.66]
    assert lines["download"][0][0] < lines["download"][1][0] < lines["download"][2][0]
    assert data.primary["value"] == 566.5 and data.secondary == [{"label": "Tests", "value": 3}]
    only = MyspeedAdapter._history(TESTS, {"show": "upload"}, 7)
    assert [line["key"] for line in only.meta["lines"]] == ["upload"] and only.primary["label"] == "Upload"
    assert MyspeedAdapter._history([], {}, 7).status == "unknown"


@respx.mock
async def test_the_cards_read_with_the_password_in_its_header(ctx: Context) -> None:
    tests = respx.get(f"{MS}/api/speedtests").mock(return_value=httpx.Response(200, json=TESTS))
    respx.get(f"{MS}/api/speedtests/status").mock(return_value=httpx.Response(200, json=IDLE))
    respx.get(f"{MS}/api/config").mock(return_value=httpx.Response(200, json=SETTINGS))
    stats = respx.get(f"{MS}/api/speedtests/statistics").mock(return_value=httpx.Response(200, json=STATISTICS))
    adapter = get_adapter("myspeed")
    latest = await adapter.fetch("latest", CONFIG, {}, ctx)
    assert tests.calls.last.request.headers["password"] == "made-up-password" and "authorization" not in tests.calls.last.request.headers
    assert tests.calls.last.request.url.params["limit"] == "10"
    # The expected values came from MySpeed's own settings (50 up, 25 ms): 4.66 and 39 miss them.
    assert latest.status == "warn" and latest.meta["below_expected"] == ["upload", "ping"]
    await adapter.fetch("statistics", CONFIG, {"days": "30"}, ctx)
    assert stats.calls.last.request.url.params["days"] == "30"
    await adapter.fetch("history", CONFIG, {"days": "7"}, ctx)
    assert tests.calls.last.request.url.params["hours"] == "168"


@respx.mock
async def test_without_a_password_no_header_is_sent(ctx: Context) -> None:
    status = respx.get(f"{MS}/api/speedtests/status").mock(return_value=httpx.Response(200, json=IDLE))
    respx.get(f"{MS}/api/info/version").mock(return_value=httpx.Response(200, json=VERSION))
    assert await get_adapter("myspeed").test({"url": MS}, ctx) == "MySpeed 1.0.9 answers."
    assert "password" not in status.calls.last.request.headers


@respx.mock
async def test_the_connection_test_names_the_version_even_when_it_cannot_be_read(ctx: Context) -> None:
    """⚠️ Measured: with the level Read, ``/api/info/version`` wants the password and the rest does not."""
    respx.get(f"{MS}/api/speedtests/status").mock(return_value=httpx.Response(200, json={"paused": True, "running": False}))
    respx.get(f"{MS}/api/info/version").mock(return_value=httpx.Response(401, json={"message": "Please provide the correct password in the header"}))
    assert await get_adapter("myspeed").test({"url": MS}, ctx) == "MySpeed answers, its tests are paused."


@respx.mock
async def test_a_missing_or_wrong_password(ctx: Context) -> None:
    respx.get(f"{MS}/api/speedtests").mock(return_value=httpx.Response(401, json={"message": "Please provide the correct password in the header"}))
    with pytest.raises(AuthFailed) as wrong:
        await get_adapter("myspeed").fetch("history", CONFIG, {}, ctx)
    assert "rejected the password" in str(wrong.value)
    with pytest.raises(AuthFailed) as none:
        await get_adapter("myspeed").fetch("history", {"url": MS}, {}, fresh(2))
    assert "asks for its password" in str(none.value)


@respx.mock
async def test_unreachable_and_not_myspeed(ctx: Context) -> None:
    respx.get(f"{MS}/api/speedtests/status").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(Unreachable):
        await get_adapter("myspeed").test(CONFIG, ctx)
    respx.get(f"{MS}/api/speedtests/status").mock(return_value=httpx.Response(200, json={"hello": "world"}))
    with pytest.raises(AdapterError) as other:
        await get_adapter("myspeed").test(CONFIG, fresh(2))
    assert other.value.code == "not_myspeed"
    respx.get(f"{MS}/api/speedtests/status").mock(return_value=httpx.Response(200, text="<html></html>"))
    with pytest.raises(AdapterError) as html:
        await get_adapter("myspeed").test(CONFIG, fresh(3))
    assert html.value.code == "not_json"


@respx.mock
async def test_running_a_test(ctx: Context) -> None:
    route = respx.post(f"{MS}/api/speedtests/run").mock(return_value=httpx.Response(200, json={"message": "Speedtest successfully created"}))
    adapter = get_adapter("myspeed")
    assert await adapter.action("latest", "run", {}, CONFIG, {}, ctx) == "MySpeed has started a test."
    assert route.calls.last.request.headers["password"] == "made-up-password"
    # ⚠️ Measured: a fresh MySpeed has no provider and says so with 410.
    route.mock(return_value=httpx.Response(410, json={"message": "No provider selected"}))
    with pytest.raises(AdapterError) as none:
        await adapter.action("latest", "run", {}, CONFIG, {}, ctx)
    assert none.value.code == "action_failed" and none.value.message == "MySpeed could not run a test: No provider selected"
    route.mock(return_value=httpx.Response(401, json={"message": "Please provide the correct password in the header"}))
    with pytest.raises(AuthFailed):
        await adapter.action("latest", "run", {}, CONFIG, {}, ctx)
    with pytest.raises(AdapterError) as other:
        await adapter.action("latest", "delete", {}, CONFIG, {}, ctx)
    assert other.value.code == "no_such_action"


def test_the_password_is_a_secret_and_the_cards_have_demo_data_that_moves() -> None:
    adapter = get_adapter("myspeed")
    assert {field.name for field in adapter.fields if field.secret} == {"password"} and adapter.beta is True
    for widget in adapter.widgets:
        options = {field.name: field.default for field in widget.options}
        assert adapter.demo(widget.kind, options, 0).error is None, widget.kind
    assert len({adapter.demo("latest", {}, tick).primary["value"] for tick in range(0, 300, 10)}) > 1
    history = adapter.demo("history", {"days": "7"}, 0)
    assert any(value is None for line in history.meta["lines"] for _at, value in line["points"]), "the demo has a failed test, to show the gap"
