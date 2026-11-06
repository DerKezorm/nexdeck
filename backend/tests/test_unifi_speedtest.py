"""The gateway's own speed tests, read back from the console (#64).

The answers below are shaped like the ones measured on 06.11.2026 against a
Dream Machine SE (Network 9) with two internet lines: the new list under
``/v2/api/site/<site>/speedtest`` and, for a controller without it, the old
report ``stat/report/archive.speedtest``.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AuthFailed, Context
from app.adapters.unifi import speedtest_card, speedtest_history

CONSOLE = "https://unifi.example.com"
KEY = {"url": CONSOLE, "api_key": "a-key", "site": "default", "unifi_os": True, "insecure": True}
ACCOUNT = {"url": CONSOLE, "username": "reader", "password": "a-long-enough-password", "site": "default", "unifi_os": True}
V2 = f"{CONSOLE}/proxy/network/v2/api/site/default/speedtest"
REPORT = f"{CONSOLE}/proxy/network/api/s/default/stat/report/archive.speedtest"

NOW = 1_793_990_000.0
DAY = 86_400


def _row(days_ago: float, down: float, up: float, ping: float, wan: str = "WAN", interface: str = "eth8") -> dict:
    return {"download_mbps": down, "upload_mbps": up, "latency_ms": ping, "time": int((NOW - days_ago * DAY) * 1000),
            "wan_networkgroup": wan, "interface_name": interface, "id": f"{wan}-{days_ago}"}


#: Out of order on purpose: nothing says the console sorts them.
LIST = {"data": [
    _row(9.0, 852, 10, 22),
    _row(40.0, 938, 73, 15),
    _row(8.99, 52, 30, 40, wan="WAN2", interface="eth6"),
    _row(2.0, 885, 20, 18),
]}


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


@pytest.fixture(autouse=True)
def frozen(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.adapters.unifi.time.time", lambda: NOW)


# ---------------------------------------------------------------------------
# The newest run
# ---------------------------------------------------------------------------


@respx.mock
async def test_the_card_shows_the_newest_run_with_upload_ping_and_its_age(ctx: Context) -> None:
    respx.get(V2).mock(return_value=httpx.Response(200, json=LIST))
    data = await get_adapter("unifi").fetch("speedtest", KEY, {}, ctx)
    assert data.status == "ok"
    assert data.primary == {"label": "Download", "metric": "download", "value": 885.0, "unit": "Mbps"}
    chips = {chip["label"]: chip["value"] for chip in data.secondary}
    assert chips["Upload"] == 20.0 and chips["Ping"] == 18
    assert chips["Tested"] == "2 d"
    assert chips["WAN"] == "WAN 1", "two lines and no choice made: the card says which line it was"
    assert data.metrics == {"download": 885.0, "upload": 20.0, "ping": 18.0}


@respx.mock
async def test_a_chosen_line_shows_only_its_own_runs(ctx: Context) -> None:
    respx.get(V2).mock(return_value=httpx.Response(200, json=LIST))
    data = await get_adapter("unifi").fetch("speedtest", KEY, {"wan": "WAN2"}, ctx)
    assert data.primary["value"] == 52.0
    assert "WAN" not in {chip["label"] for chip in data.secondary}, "the line was chosen, so the card need not name it"


@respx.mock
async def test_a_console_that_never_tested_says_so_instead_of_reading_zero(ctx: Context) -> None:
    respx.get(V2).mock(return_value=httpx.Response(200, json={"data": []}))
    data = await get_adapter("unifi").fetch("speedtest", KEY, {}, ctx)
    assert data.status == "unknown"
    assert data.primary["value"] is None
    assert data.metrics == {}


def test_a_run_that_measured_nothing_keeps_the_last_good_one_and_turns_yellow() -> None:
    from app.adapters.unifi import _speedtest

    runs = [run for row in (_row(3, 900, 40, 12), _row(1, 0, 0, 0)) if (run := _speedtest(row))]
    data = speedtest_card(runs, {}, now=NOW)
    assert data.status == "warn"
    assert data.primary["value"] == 900.0
    assert {"label": "Last test", "value": "Failed"} in data.secondary
    assert data.metrics["download"] == 900.0, "a failed run is not a reading of zero"


def test_only_failed_runs_give_no_number_at_all() -> None:
    from app.adapters.unifi import _speedtest

    data = speedtest_card([run for run in [_speedtest(_row(1, 0, 0, 0))] if run], {}, now=NOW)
    assert data.status == "warn"
    assert data.primary["value"] is None
    assert data.metrics == {}


# ---------------------------------------------------------------------------
# The history
# ---------------------------------------------------------------------------


@respx.mock
async def test_the_history_draws_each_line_apart_and_never_as_one(ctx: Context) -> None:
    """⚠️ 900 on fibre and 50 on LTE, drawn as one series, is a connection that collapses every time the backup is tested."""
    respx.get(V2).mock(return_value=httpx.Response(200, json=LIST))
    data = await get_adapter("unifi").fetch("speedtest_history", KEY, {"days": "30"}, ctx)
    lines = {line["key"]: line for line in data.meta["lines"]}
    assert set(lines) == {"download_wan", "upload_wan", "download_wan2", "upload_wan2"}
    assert [point[1] for point in lines["download_wan"]["points"]] == [852.0, 885.0], "oldest first, the 40-day run outside 30 days"
    assert [point[1] for point in lines["download_wan2"]["points"]] == [52.0]
    assert lines["download_wan2"]["label"] == "Download · WAN 2"
    assert data.secondary[1] == {"label": "Measurements", "value": 3}


@respx.mock
async def test_the_history_of_one_line_with_download_only(ctx: Context) -> None:
    respx.get(V2).mock(return_value=httpx.Response(200, json=LIST))
    data = await get_adapter("unifi").fetch("speedtest_history", KEY, {"days": "90", "wan": "WAN", "show": "download"}, ctx)
    assert [(line["key"], line["label"]) for line in data.meta["lines"]] == [("download", "Download")]
    assert [point[1] for point in data.meta["lines"][0]["points"]] == [938.0, 852.0, 885.0]


def test_a_failed_run_is_a_gap_on_the_line_not_a_fall_to_zero() -> None:
    from app.adapters.unifi import _speedtest

    runs = [run for row in (_row(3, 900, 40, 12), _row(2, 0, 0, 0), _row(1, 910, 41, 11)) if (run := _speedtest(row))]
    data = speedtest_history(runs, {"days": "7", "show": "download"}, now=NOW)
    assert [point[1] for point in data.meta["lines"][0]["points"]] == [900.0, None, 910.0]


def test_an_empty_period_says_so() -> None:
    data = speedtest_history([], {"days": "1"}, now=NOW)
    assert data.status == "unknown"
    assert data.meta["empty"] == "No measurement in this period"


# ---------------------------------------------------------------------------
# The ways in
# ---------------------------------------------------------------------------


@respx.mock
async def test_two_cards_on_one_console_ask_once(ctx: Context) -> None:
    route = respx.get(V2).mock(return_value=httpx.Response(200, json=LIST))
    unifi = get_adapter("unifi")
    await unifi.fetch("speedtest", KEY, {}, ctx)
    await unifi.fetch("speedtest_history", KEY, {}, ctx)
    assert route.call_count == 1
    assert route.calls[0].request.headers["X-API-KEY"] == "a-key"


@respx.mock
async def test_a_controller_without_the_new_list_is_asked_for_the_old_report(ctx: Context) -> None:
    respx.get(V2).mock(return_value=httpx.Response(404, text="<html>not found</html>"))
    report = respx.post(REPORT).mock(return_value=httpx.Response(200, json={"meta": {"rc": "ok"}, "data": [
        {"xput_download": 933.0, "xput_upload": 77.0, "latency": 14, "interface_name": "eth8", "time": int((NOW - DAY) * 1000), "o": "speedtest"},
    ]}))
    data = await get_adapter("unifi").fetch("speedtest", KEY, {}, ctx)
    assert data.primary["value"] == 933.0
    sent = json.loads(report.calls[0].request.content)
    assert set(sent["attrs"]) >= {"xput_download", "xput_upload", "latency", "time"}
    assert sent["end"] == int(NOW * 1000) and sent["end"] - sent["start"] == 90 * DAY * 1000


@respx.mock
async def test_a_local_account_signs_in_when_the_console_asks_for_it(ctx: Context) -> None:
    respx.get(V2).mock(side_effect=[httpx.Response(401), httpx.Response(200, json=LIST)])
    login = respx.post(f"{CONSOLE}/api/auth/login").mock(return_value=httpx.Response(200, json={}, headers={"x-csrf-token": "csrf-1"}))
    data = await get_adapter("unifi").fetch("speedtest", ACCOUNT, {}, ctx)
    assert login.call_count == 1
    assert data.primary["value"] == 885.0
    assert respx.calls[-1].request.headers["x-csrf-token"] == "csrf-1"


@respx.mock
async def test_a_rejected_key_is_said_as_such(ctx: Context) -> None:
    respx.get(V2).mock(return_value=httpx.Response(401))
    with pytest.raises(AuthFailed):
        await get_adapter("unifi").fetch("speedtest", KEY, {}, ctx)


def test_the_demo_draws_both_cards() -> None:
    unifi = get_adapter("unifi")
    latest = unifi.demo("speedtest", {}, tick=1)
    assert latest.status == "ok" and isinstance(latest.primary["value"], float)
    history = unifi.demo("speedtest_history", {"days": "7"}, tick=1)
    assert history.meta["lines"] and all(line["points"] for line in history.meta["lines"])
    assert [line["key"] for line in history.meta["lines"]] == ["download", "upload"], "the demo's history keeps to the main line"
