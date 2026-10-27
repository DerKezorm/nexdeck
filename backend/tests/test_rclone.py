"""rclone, against the answers of rclone v1.75.2 (rclone/rclone, ``rclone rcd``, 27.10.2026).

The stats, transfers, bandwidth limit and errors are the measured ones: a copy
of two files at 4 MiB/s, the same stats once it ended (the speed does not fall
to zero), a copy from a folder that is not there, a limit switched off. Paths,
remote names and the password are made up.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context, Unreachable, outbound_client

BASE = "http://rclone.example.com:5572"
CONFIG = {"url": BASE, "username": "admin", "password": "a-made-up-word"}
OPEN = {"url": BASE}
ADAPTER = get_adapter("rclone")


def fresh() -> Context:
    return Context(outbound_client(guard=False), integration_id=1, widget_id=1, cache={})


@pytest.fixture
def ctx() -> Context:
    return fresh()


MOVING = {
    "bytes": 16856768, "checks": 0, "deletedDirs": 0, "deletes": 0, "elapsedTime": 1.3, "errors": 0, "eta": 6, "fatalError": False, "listed": 2,
    "renames": 0, "retryError": False, "speed": 4205926.130982998, "totalBytes": 43000000, "totalChecks": 0, "totalTransfers": 2, "transferTime": 4.0,
    "transferring": [{"bytes": 13856768, "dstFs": "/data/dst", "eta": 7, "group": "job/4", "name": "photos/big.bin", "percentage": 34, "size": 40000000,
                      "speed": 3459489.3, "speedAvg": 3455988.5, "srcFs": "/data/src"}],
    "transfers": 1}
#: Once the copy was over: the speed is still the average, ``transferring`` is gone.
DONE = {**MOVING, "bytes": 43000000, "eta": 0, "transfers": 2, "elapsedTime": 12.0}
DONE.pop("transferring")
FAILED = {**DONE, "errors": 1, "lastError": "directory not found", "retryError": True}
RESET = {**DONE, "bytes": 0, "eta": None, "transfers": 0, "totalTransfers": 0, "totalBytes": 0, "speed": 0}
LIMIT = {"bytesPerSecond": 4194304, "bytesPerSecondRx": 4194304, "bytesPerSecondTx": 4194304, "rate": "4Mi"}
NO_LIMIT = {"bytesPerSecond": -1, "bytesPerSecondRx": -1, "bytesPerSecondTx": -1, "rate": "off"}
TRANSFERRED = {"transferred": [
    {"error": "", "name": "small.bin", "size": 3000000, "bytes": 3000000, "checked": False, "what": "transferring",
     "started_at": "2026-10-27T18:08:51.667Z", "completed_at": "2026-10-27T18:08:53.085Z", "group": "job/4", "srcFs": "/data/src", "dstFs": "/data/dst"},
    {"error": "", "name": "big.bin", "size": 40000000, "bytes": 40000000, "checked": False, "what": "transferring",
     "started_at": "2026-10-27T18:08:51.667Z", "completed_at": "2026-10-27T18:09:01.912Z", "group": "job/4", "srcFs": "/data/src", "dstFs": "/data/dst"},
    {"error": "failed to open source object: permission denied\nsecond line", "name": "locked/secret.doc", "size": 1048576, "bytes": 0, "checked": False,
     "what": "transferring", "started_at": "2026-10-27T18:08:50.0Z", "completed_at": "2026-10-27T18:08:50.5Z", "group": "job/4", "srcFs": "/data/src", "dstFs": "/data/dst"}]}


def rclone(answers: dict[str, object], seen: list[httpx.Request] | None = None, password: str = "a-made-up-word") -> None:
    """One address per method; a missing body is the error rclone gives, and a missing password is its 401."""
    def reply(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        if password and request.headers.get("authorization") is None:
            return httpx.Response(401, text="401 Unauthorized\n")
        if not request.content:
            return httpx.Response(400, json={"error": "failed to read input JSON: EOF", "input": {}, "path": request.url.path.strip("/"), "status": 400})
        answer = answers.get(request.url.path.strip("/"))
        if isinstance(answer, httpx.Response):
            return answer
        return httpx.Response(200, json=answer if answer is not None else {})
    respx.post(url__regex=rf"{BASE}/.*").mock(side_effect=reply)


@respx.mock
async def test_the_speed_card_shows_the_speed_while_a_file_moves_with_the_limit_as_the_full_dial(ctx: Context) -> None:
    rclone({"core/stats": MOVING, "core/bwlimit": LIMIT})
    data = await ADAPTER.fetch("speed", CONFIG, {}, ctx)
    assert data.primary == {"label": "Speed", "value": 4.0, "unit": "MB/s"}
    assert data.secondary == [{"label": "Transferred", "value": "16.1 MB of 41.0 MB"}, {"label": "Left", "value": "6s"}, {"label": "Files", "value": "1 of 2"}]
    assert (data.status, data.metrics) == ("ok", {"speed": 4.01})
    assert [action.id for action in data.actions] == ["reset"]
    dial = await ADAPTER.fetch("speed", CONFIG, {"view": "gauge"}, fresh())
    assert dial.meta["gauge"]["max"] == 4.0


@respx.mock
async def test_once_the_work_is_over_the_speed_is_zero_although_rclone_still_reports_the_average(ctx: Context) -> None:
    rclone({"core/stats": DONE, "core/bwlimit": NO_LIMIT})
    data = await ADAPTER.fetch("speed", CONFIG, {}, ctx)
    assert data.primary == {"label": "Idle", "value": 0.0, "unit": "MB/s"}
    assert data.metrics == {"speed": 0.0}
    assert not any(row["label"] == "Left" for row in data.secondary)


@respx.mock
async def test_an_error_turns_the_card_red_and_a_retry_alone_yellow(ctx: Context) -> None:
    rclone({"core/stats": FAILED, "core/bwlimit": NO_LIMIT})
    data = await ADAPTER.fetch("speed", CONFIG, {}, ctx)
    assert data.status == "bad" and {"label": "Errors", "value": 1} in data.secondary
    retrying = ADAPTER.speed_card({**DONE, "retryError": True}, NO_LIMIT, {})
    assert retrying.status == "warn"
    assert ADAPTER.speed_card({**DONE, "fatalError": True}, NO_LIMIT, {}).status == "bad"


@respx.mock
async def test_after_a_reset_there_is_nothing_to_reset_and_no_time_left(ctx: Context) -> None:
    rclone({"core/stats": RESET, "core/bwlimit": NO_LIMIT})
    data = await ADAPTER.fetch("speed", CONFIG, {}, ctx)
    assert data.actions == [] and data.secondary[0] == {"label": "Transferred", "value": "0 B"}


@respx.mock
async def test_the_transfer_list_has_the_moving_file_first_then_the_finished_ones_newest_first_and_failures_with_their_first_line(ctx: Context) -> None:
    rclone({"core/stats": MOVING, "core/transferred": TRANSFERRED})
    data = await ADAPTER.fetch("transfers", CONFIG, {}, ctx)
    assert [(item["title"], item["value"], item["status"]) for item in data.items] == [
        ("big.bin", "34%", "ok"), ("big.bin", "Done", "ok"), ("small.bin", "Done", "ok"), ("secret.doc", "Failed", "bad")]
    assert data.items[0]["progress"] == 34.0 and data.items[0]["subtitle"] == "38.1 MB · 3.3 MB/s · 7s left"
    assert data.items[3]["subtitle"] == "failed to open source object: permission denied"
    assert data.items[1]["subtitle"].startswith("38.1 MB · ")
    assert data.secondary == [{"label": "Moving", "value": 1}, {"label": "Errors", "value": 0}]


@respx.mock
async def test_the_last_error_and_the_limit_on_entries(ctx: Context) -> None:
    rclone({"core/stats": FAILED, "core/transferred": TRANSFERRED})
    data = await ADAPTER.fetch("transfers", CONFIG, {"limit": 2}, ctx)
    assert len(data.items) == 2 and data.status == "bad"
    assert {"label": "Last error", "value": "directory not found"} in data.secondary
    assert data.metrics == {"speed": 0.0, "errors": 1.0}


@respx.mock
async def test_an_idle_rclone_says_nothing_has_been_moved(ctx: Context) -> None:
    rclone({"core/stats": RESET, "core/transferred": {"transferred": []}})
    data = await ADAPTER.fetch("transfers", CONFIG, {}, ctx)
    assert (data.items, data.status, data.meta["empty"]) == ([], "ok", "Nothing has been moved.")


@respx.mock
async def test_the_overview_names_the_limit_the_remotes_and_the_version(ctx: Context) -> None:
    rclone({"core/bwlimit": LIMIT, "config/listremotes": {"remotes": ["offsite", "cloud-drive"]}, "core/version": {"version": "v1.75.2"}})
    data = await ADAPTER.fetch("overview", CONFIG, {}, ctx)
    assert data.primary == {"label": "Bandwidth limit", "value": "4.0 MB/s"}
    assert data.secondary == [{"label": "Remotes", "value": 2}, {"label": "Version", "value": "1.75.2"}]
    action = data.actions[0]
    assert (action.id, action.confirm, action.danger) == ("limit", False, False)
    assert [(one.value, one.label) for one in action.asks[0].options][:2] == [("off", "No limit"), ("1M", "1 MiB/s")]
    rclone({"core/bwlimit": NO_LIMIT, "config/listremotes": {"remotes": []}, "core/version": {"version": "v1.75.2"}})
    assert (await ADAPTER.fetch("overview", CONFIG, {}, fresh())).primary["value"] == "No limit"


@respx.mock
async def test_setting_the_limit_posts_the_rate_and_only_one_of_the_offered_ones(ctx: Context) -> None:
    seen: list[httpx.Request] = []
    rclone({"core/bwlimit": LIMIT, "core/stats-reset": {}}, seen)
    assert await ADAPTER.action("overview", "limit", {"rate": "5M"}, CONFIG, {}, ctx) == "The limit is 5M."
    assert json.loads(seen[-1].content) == {"rate": "5M"}
    assert await ADAPTER.action("overview", "limit", {"rate": "off"}, CONFIG, {}, ctx) == "The limit is off."
    for bad in ({}, {"rate": "abc"}, {"rate": "5M; rm"}):
        with pytest.raises(AdapterError) as failure:
            await ADAPTER.action("overview", "limit", bad, CONFIG, {}, ctx)
        assert failure.value.code == "bad_value"
    assert await ADAPTER.action("speed", "reset", {}, CONFIG, {}, ctx) == "The counters are reset."
    assert seen[-1].url.path == "/core/stats-reset"
    with pytest.raises(AdapterError) as failure:
        await ADAPTER.action("speed", "stop", {}, CONFIG, {}, ctx)
    assert failure.value.code == "no_such_action"


@respx.mock
async def test_every_call_has_a_body_because_rclone_answers_400_to_none(ctx: Context) -> None:
    seen: list[httpx.Request] = []
    rclone({"core/version": {"version": "v1.75.2"}}, seen)
    assert await ADAPTER.test(CONFIG, ctx) == "rclone 1.75.2 answers."
    assert await ADAPTER.running_version(CONFIG, fresh()) == "1.75.2"
    assert seen[-1].content == b"{}" and seen[-1].method == "POST"


@respx.mock
async def test_without_a_user_name_no_password_is_sent_and_a_refusal_says_what_is_missing(ctx: Context) -> None:
    seen: list[httpx.Request] = []
    rclone({"core/version": {"version": "v1.75.2"}}, seen, password="")
    await ADAPTER.test(OPEN, ctx)
    assert "authorization" not in seen[-1].headers
    rclone({"core/version": {"version": "v1.75.2"}})
    with pytest.raises(AuthFailed) as failure:
        await ADAPTER.test(OPEN, fresh())
    assert "wants a user name" in str(failure.value)
    respx.post(url__regex=rf"{BASE}/.*").mock(return_value=httpx.Response(401, text="401 Unauthorized\n"))
    with pytest.raises(AuthFailed) as failure:
        await ADAPTER.test(CONFIG, fresh())
    assert "rejected" in str(failure.value)


@respx.mock
async def test_a_failure_in_rclone_gives_its_message_and_something_else_at_the_address_is_not_rclone(ctx: Context) -> None:
    rclone({"core/bwlimit": httpx.Response(500, json={"error": "bad bwlimit: bad suffix 'c'", "input": {"rate": "abc"}, "path": "core/bwlimit", "status": 500})})
    with pytest.raises(AdapterError) as failure:
        await ADAPTER.fetch("overview", CONFIG, {}, ctx)
    assert failure.value.code == "rclone_error" and "bad suffix 'c'" in str(failure.value)
    # And the 400 of a call that was made wrongly says the same way what rclone said.
    rclone({"core/bwlimit": httpx.Response(400, json={"error": "failed to read input JSON: EOF", "input": {}, "path": "core/bwlimit", "status": 400})})
    with pytest.raises(AdapterError) as failure:
        await ADAPTER.fetch("overview", CONFIG, {}, fresh())
    assert failure.value.code == "rclone_error" and "failed to read input JSON" in str(failure.value)

    respx.post(url__regex=rf"{BASE}/.*").mock(return_value=httpx.Response(404, text="404 page not found"))
    with pytest.raises(AdapterError) as failure:
        await ADAPTER.test(CONFIG, fresh())
    assert failure.value.code == "not_rclone"
    respx.post(url__regex=rf"{BASE}/.*").mock(return_value=httpx.Response(200, json={"hello": "world"}))
    with pytest.raises(AdapterError) as failure:
        await ADAPTER.test(CONFIG, fresh())
    assert failure.value.code == "not_rclone"
    respx.post(url__regex=rf"{BASE}/.*").mock(return_value=httpx.Response(200, text="<html></html>"))
    with pytest.raises(AdapterError) as failure:
        await ADAPTER.test(CONFIG, fresh())
    assert failure.value.code == "not_json"


@respx.mock
async def test_an_unreachable_rclone(ctx: Context) -> None:
    respx.post(url__regex=rf"{BASE}/.*").mock(side_effect=httpx.ConnectError("connection refused"))
    with pytest.raises(Unreachable):
        await ADAPTER.fetch("speed", CONFIG, {}, ctx)


def test_the_demo_fills_every_card() -> None:
    for tick in range(0, 400, 20):
        assert ADAPTER.demo("speed", {}, tick).primary
        assert ADAPTER.demo("transfers", {}, tick).items
        assert ADAPTER.demo("overview", {}, tick).primary
