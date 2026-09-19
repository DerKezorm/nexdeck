"""nexpulse, against the answers of nexpulse 0.1.0 and 0.1.1.

The fixtures follow the shape measured on 2026-09-19 with a key of each kind;
the numbers, the address and the result link in them are made up.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import WHOLE_CONNECTION, AdapterError, Context
from app.adapters.nexpulse import READ_ONLY, grade

FIXTURES = Path(__file__).parent / "fixtures"
# ⚠️ With a sub-path: nexpulse may live below one behind a proxy.
BASE = "https://pulse.example.com/nexpulse"
KEY = "npk_made-up-key"
CONFIG = {"url": BASE + "/", "api_key": KEY}


def fixture(name: str) -> Any:
    return json.loads((FIXTURES / f"nexpulse_{name}.json").read_text(encoding="utf-8"))


def results() -> list[dict[str, Any]]:
    return fixture("results")


def newest_ok() -> dict[str, Any]:
    return [one for one in results() if one["status"] == "ok"][-1]


def refused(status: int, code: str) -> httpx.Response:
    return httpx.Response(status, json={"detail": {"code": code, "message": "whatever nexpulse says"}})


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


def _rights(may_run: bool | None) -> respx.Route:
    """``/api/v1/me`` as nexpulse 0.1.1 answers it, or its 404 on 0.1.0 for ``None``."""
    if may_run is None:
        answer = httpx.Response(404, json={"detail": "Not Found"})
    else:
        answer = httpx.Response(200, json={"name": "board", "scope": "run" if may_run else "read",
                                           "can_run_tests": may_run, "version": "0.1.1"})
    return respx.get(f"{BASE}/api/v1/me").mock(return_value=answer)


def _no_post() -> respx.Route:
    """Every POST, so a test can say none went out."""
    return respx.post(f"{BASE}/api/v1/tests").mock(return_value=httpx.Response(202, json={"id": 99}))


def _status(running: bool = False, live: dict[str, Any] | None = None, latest: dict[str, Any] | None = None) -> respx.Route:
    body = {"version": "0.1.0", "running": running, "live": live, "latest": latest if latest is not None else newest_ok()}
    return respx.get(f"{BASE}/api/v1/status").mock(return_value=httpx.Response(200, json=body))


def _results(answer: list[dict[str, Any]] | None = None) -> respx.Route:
    return respx.get(f"{BASE}/api/v1/results").mock(
        return_value=httpx.Response(200, json=answer if answer is not None else results()))


# -- the key -----------------------------------------------------------------


@respx.mock
async def test_the_key_travels_as_a_bearer_header_and_nowhere_else(ctx: Context) -> None:
    status = _status()
    _rights(False)
    await get_adapter("nexpulse").test(CONFIG, ctx)
    request = status.calls.last.request
    assert request.headers["Authorization"] == f"Bearer {KEY}"
    assert KEY not in str(request.url), "never in the address, where proxies write it into their logs"
    assert str(request.url) == f"{BASE}/api/v1/status", "the sub-path stays, the trailing slash goes"


@respx.mock
async def test_nothing_is_posted_to_find_something_out(ctx: Context) -> None:
    """⚠️ nexpulse 0.1.0 started a real Cloudflare test for a body without a
    source. The rights come from ``/api/v1/me``; a POST goes out only when
    somebody presses the button."""
    _status()
    _results()
    respx.get(f"{BASE}/api/v1/latest").mock(return_value=httpx.Response(200, json=newest_ok()))
    respx.get(f"{BASE}/api/v1/stats").mock(return_value=httpx.Response(200, json=fixture("stats")))
    posted = _no_post()
    adapter = get_adapter("nexpulse")
    for may_run in (True, False, None):
        _rights(may_run)
        await adapter.test(CONFIG, ctx)
        for kind in ("latest", "history", "summary", "recent", "bufferbloat"):
            await adapter.fetch(kind, CONFIG, {}, ctx)
    assert posted.call_count == 0


@respx.mock
async def test_the_connection_test_says_what_a_reading_key_may_do(ctx: Context) -> None:
    _status()
    me = _rights(False)
    said = await get_adapter("nexpulse").test(CONFIG, ctx)
    assert "starting a test needs another key" in said
    assert me.calls.last.request.headers["Authorization"] == f"Bearer {KEY}"


@respx.mock
async def test_the_connection_test_says_what_a_starting_key_may_do(ctx: Context) -> None:
    _status()
    _rights(True)
    said = await get_adapter("nexpulse").test(CONFIG, ctx)
    assert "may read results and start tests" in said


@respx.mock
async def test_the_connection_test_asks_afresh_rather_than_from_memory(ctx: Context) -> None:
    _status()
    _rights(False)
    adapter = get_adapter("nexpulse")
    assert "needs another key" in await adapter.test(CONFIG, ctx)
    _rights(True)
    assert "start tests" in await adapter.test(CONFIG, ctx)


@respx.mock
async def test_nexpulse_0_1_0_is_asked_to_update_at_setup(ctx: Context) -> None:
    _status()
    _rights(None)
    said = await get_adapter("nexpulse").test(CONFIG, ctx)
    assert "cannot say what the key may do" in said and "0.1.1" in said


@respx.mock
async def test_an_unknown_key_says_where_to_make_a_new_one(ctx: Context) -> None:
    respx.get(f"{BASE}/api/v1/status").mock(return_value=refused(401, "invalid_api_key"))
    with pytest.raises(AdapterError) as caught:
        await get_adapter("nexpulse").test(CONFIG, ctx)
    assert caught.value.code == "nexpulse_key_invalid"
    assert "Settings → API keys" in str(caught.value)


@respx.mock
async def test_a_fault_in_front_of_nexpulse_is_not_taken_for_old_nexpulse(ctx: Context) -> None:
    """Only 404 means 0.1.0. A proxy's 502 is a fault, and calling it "rights
    unknown" would hide it behind a button that then fails."""
    _status()
    respx.get(f"{BASE}/api/v1/me").mock(return_value=httpx.Response(502, text="Bad gateway"))
    with pytest.raises(AdapterError, match="HTTP 502"):
        await get_adapter("nexpulse").test(CONFIG, ctx)


# -- latest result -------------------------------------------------------------


@respx.mock
async def test_the_latest_result_with_a_key_that_may_only_read_has_no_button(ctx: Context) -> None:
    _status()
    _results([newest_ok()])
    _rights(False)
    card = await get_adapter("nexpulse").fetch("latest", CONFIG, {}, ctx)
    assert card.status == "ok"
    assert card.primary == {"label": "Download", "value": 912.4, "unit": "Mbps"}
    assert [chip["label"] for chip in card.secondary] == ["Upload", "Ping", "Jitter", "Tested"]
    assert card.actions == []


@respx.mock
async def test_the_latest_result_offers_the_button_to_a_key_that_may_start_tests(ctx: Context) -> None:
    _status()
    _results([newest_ok()])
    probe = _rights(True)
    adapter = get_adapter("nexpulse")
    card = await adapter.fetch("latest", CONFIG, {}, ctx)
    assert [action.id for action in card.actions] == ["run"]
    await adapter.fetch("latest", CONFIG, {}, ctx)
    assert probe.call_count == 1, "the rights are remembered for a while, not asked on every refresh"


@respx.mock
async def test_on_nexpulse_0_1_0_the_button_is_shown_and_a_refusal_says_why(ctx: Context) -> None:
    """Rights unknown: the button stays, and a key that may only read hears
    nexpulse's 403 as a sentence when it is pressed."""
    _status()
    _results([newest_ok()])
    _rights(None)
    adapter = get_adapter("nexpulse")
    card = await adapter.fetch("latest", CONFIG, {}, ctx)
    assert [action.id for action in card.actions] == ["run"]
    respx.post(f"{BASE}/api/v1/tests").mock(return_value=refused(403, "key_read_only"))
    with pytest.raises(AdapterError) as caught:
        await adapter.action("latest", "run", {}, CONFIG, {}, ctx)
    assert str(caught.value) == READ_ONLY


@respx.mock
async def test_a_swapped_key_does_not_inherit_the_rights_of_the_one_before(ctx: Context) -> None:
    _status()
    _results([newest_ok()])
    _rights(True)
    adapter = get_adapter("nexpulse")
    assert (await adapter.fetch("latest", CONFIG, {}, ctx)).actions
    _rights(False)
    card = await adapter.fetch("latest", {**CONFIG, "api_key": "npk_another"}, {}, ctx)
    assert card.actions == []


@respx.mock
async def test_a_running_test_shows_its_speed_and_hides_the_button(ctx: Context) -> None:
    live = {"running": True, "source": "cloudflare", "phase": "download", "current_mbps": 211.4}
    _status(running=True, live=live)
    _results([newest_ok()])
    probe = _rights(True)
    card = await get_adapter("nexpulse").fetch("latest", CONFIG, {}, ctx)
    assert card.secondary[0] == {"label": "Test running", "value": 211.0, "unit": "Mbps"}
    assert card.actions == [] and probe.call_count == 0


@respx.mock
async def test_a_failed_newest_test_is_said_and_not_hidden_behind_the_old_numbers(ctx: Context) -> None:
    """⚠️ ``latest`` is the newest *successful* result. The failed one after it is
    only in the list, and without it the card would call a broken line fine."""
    _status()
    _results([results()[-1]])
    _rights(False)
    card = await get_adapter("nexpulse").fetch("latest", CONFIG, {}, ctx)
    assert card.status == "warn"
    assert card.meta["notice"] == "The newest test failed. The numbers are from the test before it."
    assert card.primary["value"] == 912.4


@respx.mock
async def test_below_the_plan_turns_the_latest_result_yellow(ctx: Context) -> None:
    below = {**newest_ok(), "below_plan": True}
    _status(latest=below)
    _results([below])
    _rights(False)
    card = await get_adapter("nexpulse").fetch("latest", CONFIG, {}, ctx)
    assert card.status == "warn" and card.meta["status_reason"] == "Below the plan set in nexpulse"


@respx.mock
async def test_a_card_narrowed_to_one_source_asks_for_that_source(ctx: Context) -> None:
    _status()
    latest = respx.get(f"{BASE}/api/v1/latest").mock(
        # What FastAPI sends for a result that is not there: the word null.
        return_value=httpx.Response(200, content=b"null", headers={"content-type": "application/json"}))
    listed = _results([])
    _rights(False)
    card = await get_adapter("nexpulse").fetch("latest", CONFIG, {"source": "ookla"}, ctx)
    assert latest.calls.last.request.url.params["source"] == "ookla"
    assert listed.calls.last.request.url.params["source"] == "ookla"
    assert card.status == "unknown" and card.meta["empty"] == "No measurement yet"


# -- the button ----------------------------------------------------------------


@respx.mock
async def test_the_button_tests_with_the_card_source_or_cloudflare(ctx: Context) -> None:
    started = respx.post(f"{BASE}/api/v1/tests").mock(return_value=httpx.Response(202, json={"id": 45}))
    adapter = get_adapter("nexpulse")
    said = await adapter.action("latest", "run", {}, CONFIG, {}, ctx)
    assert json.loads(started.calls.last.request.content) == {"source": "cloudflare"}
    assert "Cloudflare" in said
    await adapter.action("latest", "run", {}, CONFIG, {"source": "librespeed"}, ctx)
    assert json.loads(started.calls.last.request.content) == {"source": "librespeed"}


@pytest.mark.parametrize(("status", "code", "ours"), [
    (403, "key_read_only", "nexpulse_read_only"),
    (409, "busy", "nexpulse_busy"),
    (409, "source_disabled", "nexpulse_source_off"),
])
@respx.mock
async def test_the_button_says_why_nexpulse_refused(ctx: Context, status: int, code: str, ours: str) -> None:
    respx.post(f"{BASE}/api/v1/tests").mock(return_value=refused(status, code))
    with pytest.raises(AdapterError) as caught:
        await get_adapter("nexpulse").action("latest", "run", {}, CONFIG, {}, ctx)
    assert caught.value.code == ours
    if code == "key_read_only":
        assert str(caught.value) == READ_ONLY


def test_a_button_card_may_start_a_test_and_nothing_else() -> None:
    adapter = get_adapter("nexpulse")
    assert [(one.widget_kind, one.id) for one in adapter.deeds] == [("latest", "run")]


async def test_the_button_settings_say_there_is_nothing_to_pick(ctx: Context) -> None:
    """Rather than the yellow "this connection offers nothing", which reads like a fault."""
    assert await get_adapter("nexpulse").choices("target", CONFIG, ctx) == [("", WHOLE_CONNECTION)]


# -- history -------------------------------------------------------------------


@respx.mock
async def test_the_history_draws_a_failed_test_as_a_gap(ctx: Context) -> None:
    listed = _results()
    card = await get_adapter("nexpulse").fetch("history", CONFIG, {"period": "24h"}, ctx)
    assert "from" in listed.calls.last.request.url.params
    download = next(line for line in card.meta["lines"] if line["key"] == "download")
    assert [value for _at, value in download["points"]] == [912.4, 402.7, 912.4, None]
    assert card.primary["value"] == 912.4, "the newest good test, not the failed one"
    assert {"label": "Tests", "value": 4} in card.secondary


@respx.mock
async def test_the_history_of_the_ping_shows_idle_and_under_load(ctx: Context) -> None:
    _results()
    card = await get_adapter("nexpulse").fetch("history", CONFIG, {"show": "latency"}, ctx)
    assert [line["key"] for line in card.meta["lines"]] == ["ping", "loaded"]
    assert card.meta["unit"] == "ms"
    loaded = card.meta["lines"][1]["points"]
    assert loaded[0][1] == 38.6, "the worse of the two directions"


@respx.mock
async def test_an_empty_period_says_so(ctx: Context) -> None:
    _results([])
    card = await get_adapter("nexpulse").fetch("history", CONFIG, {}, ctx)
    assert card.status == "unknown" and card.meta["empty"] == "No measurement in this period"


# -- summary -------------------------------------------------------------------


@respx.mock
async def test_the_summary_takes_the_figure_that_was_picked(ctx: Context) -> None:
    asked = respx.get(f"{BASE}/api/v1/stats").mock(return_value=httpx.Response(200, json=fixture("stats")))
    card = await get_adapter("nexpulse").fetch("summary", CONFIG, {"period": "30d", "figure": "median"}, ctx)
    assert asked.calls.last.request.url.params["range"] == "30d"
    assert card.primary == {"label": "Download", "value": 905.2, "unit": "Mbps"}
    assert {"label": "Failed", "value": 2} in card.secondary and {"label": "Below plan", "value": 1} in card.secondary
    assert card.status == "warn", "2 of 20 failed is a tenth"
    assert "2 of 20 tests failed" in card.meta["status_reason"]


@respx.mock
async def test_a_quiet_period_shows_no_chips_at_zero(ctx: Context) -> None:
    quiet = {**fixture("stats"), "failed": 0, "below_plan": 0}
    respx.get(f"{BASE}/api/v1/stats").mock(return_value=httpx.Response(200, json=quiet))
    card = await get_adapter("nexpulse").fetch("summary", CONFIG, {}, ctx)
    assert [chip["label"] for chip in card.secondary] == ["Upload", "Ping", "Tests"]
    assert card.status == "ok"


# -- recent tests --------------------------------------------------------------


@respx.mock
async def test_recent_tests_read_newest_first_with_their_colours(ctx: Context) -> None:
    listed = _results()
    card = await get_adapter("nexpulse").fetch("recent", CONFIG, {"limit": 3}, ctx)
    assert listed.calls.last.request.url.params["limit"] == "3"
    rows = card.items
    assert [row["id"] for row in rows] == ["44", "43", "42", "41"][: len(rows)]
    assert rows[0]["title"] == "Failed" and rows[0]["status"] == "bad" and rows[0]["subtitle"].endswith("timeout")
    assert rows[1]["url"].startswith("https://www.speedtest.net/"), "Ookla's own page for its result"
    assert rows[2]["status"] == "warn" and rows[2]["subtitle"].endswith("Below plan")
    assert rows[2]["title"] == "403 / 32 Mbps"


# -- latency under load --------------------------------------------------------


@pytest.mark.parametrize(("idle", "busy", "mark"), [
    (10, 14.9, "A+"), (10, 15, "A"), (10, 39.9, "A"), (10, 40, "B"), (10, 69.9, "B"), (10, 70, "C"),
    (10, 209.9, "C"), (10, 210, "D"), (10, 409.9, "D"), (10, 410, "F"),
])
def test_the_grade_follows_the_waveform_steps(idle: float, busy: float, mark: str) -> None:
    graded = grade({"ping_ms": idle, "loaded_down_ms": busy, "loaded_up_ms": None})
    assert graded is not None and graded[0] == mark


def test_no_ping_under_load_is_no_grade_rather_than_the_best_one() -> None:
    assert grade({"ping_ms": 10, "loaded_down_ms": None, "loaded_up_ms": None}) is None


@respx.mock
async def test_the_latency_card_grades_the_newest_result(ctx: Context) -> None:
    respx.get(f"{BASE}/api/v1/latest").mock(return_value=httpx.Response(200, json=newest_ok()))
    card = await get_adapter("nexpulse").fetch("bufferbloat", CONFIG, {}, ctx)
    assert card.primary == {"label": "Grade", "value": "A"}
    assert card.metrics == {"growth": 26.8}, "38.6 under load less 11.8 idle"


# -- demo ----------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["latest", "history", "summary", "recent", "bufferbloat"])
def test_every_card_has_a_demo(kind: str) -> None:
    card = get_adapter("nexpulse").demo(kind, {}, 42)
    assert card.status in ("ok", "warn", "bad")
    assert card.primary or card.items
