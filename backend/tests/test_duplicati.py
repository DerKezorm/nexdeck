"""Duplicati, against the answers of a live Duplicati 2.4.0.0 (11.09.2026)."""

from __future__ import annotations

import time
from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context
from app.adapters.duplicati import _moment

DU = "http://duplicati.example.com"
CONFIG = {"url": DU, "password": "made-up-password"}

GOOD = {"Backup": {"ID": "1", "Name": "Settings to local folder", "Metadata": {
    "LastBackupDate": "20260911T090333Z", "BackupListCount": "1", "TargetSizeString": "27.43 KiB", "SourceFilesCount": "7",
    "LastBackupStarted": "20260911T090333Z", "LastBackupFinished": "20260911T090334Z", "LastBackupDuration": "00:00:00.3415812"}}, "Schedule": None}
#: Measured: a job that never got through has only the error.
NEVER_GOT_THROUGH = {"Backup": {"ID": "2", "Name": "Offsite that cannot connect", "Metadata": {
    "LastErrorDate": "20260911T090724Z", "LastErrorMessage": "The operation was canceled."}}, "Schedule": None}
#: ⚠️ Measured: failed at 09:14:06, ran fine at 09:14:45, and still carries the error.
RECOVERED = {"Backup": {"ID": "3", "Name": "Fails then recovers", "Metadata": {
    "LastErrorDate": "20260911T091406Z", "LastErrorMessage": "The folder /proc/cannot-write-here does not exist",
    "LastBackupDate": "20260911T091444Z", "LastBackupStarted": "20260911T091444Z", "LastBackupFinished": "20260911T091445Z"}},
    "Schedule": {"ID": 1, "Tags": ["ID=3"], "Time": "2026-09-12T02:00:00Z", "Repeat": "1D", "LastRun": "0001-01-01T00:00:00Z", "Rule": "", "AllowedDays": None}}
NEW = {"Backup": {"ID": "4", "Name": "Brand new", "Metadata": {}}, "Schedule": None}
ONLY_A_DATE = {"Backup": {"ID": "5", "Name": "Only a date", "Metadata": {"LastBackupDate": "20260911T080000Z"}}, "Schedule": None}
IDLE = {"ActiveTask": None, "ProgramState": "Running", "SchedulerQueueIds": [], "HasError": True, "SuggestedStatusIcon": "ReadyError"}


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


def _server(backups: list[dict[str, Any]], state: dict[str, Any] | None = None, token: str = "made-up-token") -> respx.Route:
    login = respx.post(f"{DU}/api/v1/auth/login").mock(side_effect=lambda request: httpx.Response(200, json={"AccessToken": token, "RefreshNonce": "made-up"})
                                                         if b"made-up-password" in request.content else httpx.Response(401, json={"Error": "Failed to log in", "Code": 401}))

    def guarded(payload: Any):
        def answer(request: httpx.Request) -> httpx.Response:
            if request.headers.get("Authorization") != f"Bearer {token}":
                return httpx.Response(401, text="")
            return httpx.Response(200, json=payload)
        return answer

    respx.get(f"{DU}/api/v1/backups").mock(side_effect=guarded(backups))
    respx.get(f"{DU}/api/v1/serverstate").mock(side_effect=guarded(state or IDLE))
    respx.get(f"{DU}/api/v1/systeminfo").mock(side_effect=guarded({"APIVersion": 1, "ServerVersion": "2.4.0.0", "ServerVersionType": "stable"}))
    return login


def test_compact_times_are_read() -> None:
    assert _moment("20260911T091445Z") - _moment("20260911T091406Z") == 39
    assert _moment(None) == 0 and _moment("2026-09-11T09:14:45Z") == 0


@respx.mock
async def test_a_failure_counts_only_while_it_is_newer_than_the_last_good_backup(ctx: Context) -> None:
    _server([GOOD, NEVER_GOT_THROUGH, RECOVERED, NEW])
    data = await get_adapter("duplicati").fetch("backups", CONFIG, {"limit": 10}, ctx)
    assert [(row["title"], row["status"], row["subtitle"]) for row in data.items] == [
        ("Offsite that cannot connect", "bad", "Failed · The operation was canceled."),
        ("Brand new", "unknown", "Never run"),
        ("Fails then recovers", "ok", ""),
        ("Settings to local folder", "ok", ""),
    ]
    assert data.items[0]["value"] == "" and data.items[2]["value"]
    # HasError is still on from the old failure; the cards go by the jobs.
    assert data.secondary == [{"label": "Failed", "value": 1}] and data.status == "bad"


@respx.mock
async def test_running_and_waiting_jobs(ctx: Context) -> None:
    # Measured while the FTP job hung: the running one is ActiveTask, the next one waits in the queue.
    _server([GOOD, NEVER_GOT_THROUGH], {"ActiveTask": {"Item1": 6, "Item2": "2"}, "SchedulerQueueIds": [{"Item1": 7, "Item2": "1"}]})
    data = await get_adapter("duplicati").fetch("backups", CONFIG, {"limit": 10}, ctx)
    assert {row["title"]: (row["status"], row["subtitle"]) for row in data.items} == {
        "Offsite that cannot connect": ("warn", "Running"), "Settings to local folder": ("unknown", "Waiting")}
    assert data.status == "ok"


@respx.mock
async def test_the_summary(ctx: Context) -> None:
    _server([GOOD, NEVER_GOT_THROUGH, RECOVERED, ONLY_A_DATE])
    data = await get_adapter("duplicati").fetch("summary", CONFIG, {}, ctx)
    # A job with a backup date but no finish time still ran.
    assert data.primary == {"label": "Jobs fine", "value": 3, "unit": "/ 4"}
    assert data.secondary[0] == {"label": "Failed", "value": 1} and data.secondary[1]["label"] == "Last backup"
    assert data.status == "bad" and data.metrics == {"failed": 1.0}


@respx.mock
async def test_one_sign_in_serves_several_refreshes(ctx: Context) -> None:
    login = _server([GOOD])
    for _ in range(3):
        await get_adapter("duplicati").fetch("summary", CONFIG, {}, ctx)
    assert login.call_count == 1


@respx.mock
async def test_an_expired_token_signs_in_again_once(ctx: Context) -> None:
    login = _server([GOOD])
    ctx.cache["duplicati_token"] = ("from-before-a-restart", time.monotonic() + 300)
    data = await get_adapter("duplicati").fetch("backups", CONFIG, {"limit": 10}, ctx)
    assert login.call_count == 1 and data.items[0]["title"] == "Settings to local folder"


@respx.mock
async def test_a_token_that_ran_out_is_not_used(ctx: Context) -> None:
    login = _server([GOOD])
    ctx.cache["duplicati_token"] = ("made-up-token", time.monotonic() - 1)
    await get_adapter("duplicati").fetch("summary", CONFIG, {}, ctx)
    assert login.call_count == 1


@respx.mock
async def test_wrong_password_and_something_else_at_the_address(ctx: Context) -> None:
    _server([GOOD])
    with pytest.raises(AuthFailed):
        await get_adapter("duplicati").test({"url": DU, "password": "wrong"}, ctx)
    respx.post(f"{DU}/api/v1/auth/login").mock(return_value=httpx.Response(200, text="<html>hello</html>"))
    with pytest.raises(AdapterError) as other:
        await get_adapter("duplicati").test(CONFIG, Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={}))
    assert other.value.code == "not_duplicati"


@respx.mock
async def test_the_connection_test(ctx: Context) -> None:
    login = _server([GOOD, RECOVERED])
    assert await get_adapter("duplicati").test(CONFIG, ctx) == "Duplicati 2.4.0.0 answers with 2 backup jobs."
    assert login.calls.last.request.read() == b'{"Password":"made-up-password"}'
