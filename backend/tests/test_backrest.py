"""Backrest, against the answers of a live Backrest 1.14.1 (12.09.2026)."""

from __future__ import annotations

import base64
import json
from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.backrest import BackrestAdapter
from app.adapters.base import AdapterError, AuthFailed, Context, Unreachable

BR = "http://backrest.example.com:9898"
CONFIG = {"url": BR, "username": "admin", "password": "made-up-password"}
#: A little over two hours after the newest backup below.
NOW = 1789171550.0
REASON = "failed to backup: path /userdata/does-not-exist does not exist: stat /userdata/does-not-exist: no such file or directory"


def history(day: str, **counts: Any) -> list[dict[str, Any]]:
    return [{"timestampMs": day, **counts}]


#: The dashboard as Backrest answered it: numbers as strings, zeros left out, recent backups newest first.
DASHBOARD = {
    "planSummaries": [
        {"id": "documents", "backupsSuccessLast30days": "2", "bytesScannedLast30days": "6000028", "bytesAddedLast30days": "3001922",
         "bytesScannedAvg": "3000014", "bytesAddedAvg": "1500961",
         "recentBackups": {"flowId": ["4", "1"], "timestampMs": ["1789164247490", "1789164243828"], "durationMs": ["1392", "1411"],
                           "status": ["STATUS_SUCCESS", "STATUS_SUCCESS"], "bytesAdded": ["0", "3001922"]},
         "protectedBytes": "3000014",
         "historyLast30days": history("1789084800000", bytesAdded="3001922", bytesScanned="6000028",
                                      statusCounts=[{"count": "2", "status": "STATUS_SUCCESS"}])},
        {"id": "missing", "backupsFailed30days": "1",
         "recentBackups": {"flowId": ["2"], "timestampMs": ["1789164245930"], "durationMs": ["1000"], "status": ["STATUS_ERROR"], "bytesAdded": ["0"]},
         "historyLast30days": history("1789084800000", statusCounts=[{"count": "1", "status": "STATUS_ERROR"}])},
        {"id": "never", "recentBackups": {}, "historyLast30days": history("1789084800000")},
        # Newest first, as measured: a good backup after a failed one is a good plan.
        {"id": "recovered", "backupsFailed30days": "1", "backupsSuccessLast30days": "1",
         "recentBackups": {"flowId": ["7", "6"], "timestampMs": ["1789164100000", "1789160000000"], "durationMs": ["900", "800"],
                           "status": ["STATUS_SUCCESS", "STATUS_ERROR"], "bytesAdded": ["2048", "0"]},
         "protectedBytes": "1048576"},
    ],
    "configPath": "/config/config.json",
    "dataPath": "/data",
}


def operation(identifier: str, start: str, message: str) -> dict[str, Any]:
    return {"id": identifier, "modno": "8", "flowId": identifier, "repoId": "local", "repoGuid": "0" * 64, "planId": "missing",
            "instanceId": "example", "status": "STATUS_ERROR", "unixTimeStartMs": start, "unixTimeEndMs": str(int(start) + 687),
            "displayMessage": message, "logref": f"t-made-up-{identifier}", "operationBackup": {}}


#: Oldest first, as measured. The older failure is there so that the newest reason is the one shown.
OPERATIONS = {"operations": [operation("1", "1789160000000", "failed to backup: an older reason"), operation("2", "1789164245930", REASON)]}


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


@respx.mock
async def test_plans_failed_first_with_the_reason_from_their_operations(ctx: Context) -> None:
    dashboard = respx.post(f"{BR}/v1.Backrest/GetSummaryDashboard").mock(return_value=httpx.Response(200, json=DASHBOARD))
    asked = respx.post(f"{BR}/v1.Backrest/GetOperations").mock(return_value=httpx.Response(200, json=OPERATIONS))
    data = await get_adapter("backrest").fetch("plans", CONFIG, {"limit": 10}, ctx)
    assert dashboard.calls.last.request.headers["Authorization"] == "Basic " + base64.b64encode(b"admin:made-up-password").decode()
    # Only the failed plan is asked for its reason.
    assert asked.call_count == 1 and json.loads(asked.calls.last.request.content) == {"selector": {"planId": "missing"}, "lastN": 4}
    assert [(row["title"], row["subtitle"], row["status"]) for row in data.items] == [
        ("missing", f"Failed · {REASON}", "bad"), ("never", "Never run", "unknown"), ("documents", "2.9 MB", "ok"), ("recovered", "1.0 MB", "ok")]
    backup = data.items[0]["actions"][0]
    assert (backup.id, backup.params, backup.confirm) == ("backup", {"plan": "missing"}, True)
    assert data.secondary == [{"label": "Failed", "value": 1}] and data.status == "bad" and data.metrics == {"failed": 1.0}


def test_the_last_backup_of_every_plan_and_the_limit() -> None:
    data = BackrestAdapter._plans(DASHBOARD["planSummaries"], {"missing": REASON}, 10, now=NOW)
    assert [(row["title"], row.get("value")) for row in data.items] == [("missing", "2 h"), ("never", None), ("documents", "2 h"), ("recovered", "2 h")]
    assert [row["title"] for row in BackrestAdapter._plans(DASHBOARD["planSummaries"], {}, 2, now=NOW).items] == ["missing", "never"]
    assert BackrestAdapter._plans([{"id": "new", "recentBackups": {}}], {}, 10).status == "unknown"


def test_the_summary() -> None:
    data = BackrestAdapter._summary(DASHBOARD["planSummaries"], now=NOW)
    assert data.primary == {"label": "Plans fine", "value": 2, "unit": "/ 4"}
    assert data.secondary == [{"label": "Failed", "value": 1}, {"label": "Last backup", "value": "2 h"}]
    assert data.status == "bad" and data.metrics == {"failed": 1.0}


@respx.mock
async def test_a_backrest_without_plans(ctx: Context) -> None:
    """⚠️ Measured: before the first plan the dashboard carries its paths and nothing else."""
    respx.post(f"{BR}/v1.Backrest/GetSummaryDashboard").mock(return_value=httpx.Response(200, json={"configPath": "/config/config.json", "dataPath": "/data"}))
    data = await get_adapter("backrest").fetch("plans", CONFIG, {}, ctx)
    assert data.items == [] and data.status == "unknown" and data.meta["empty"] == "No backup plans yet."
    summary = await get_adapter("backrest").fetch("summary", CONFIG, {}, ctx)
    assert summary.status == "unknown" and summary.primary == {"label": "Plans fine", "value": 0, "unit": "/ 0"}


@respx.mock
async def test_without_a_user_no_credentials_are_sent(ctx: Context) -> None:
    route = respx.post(f"{BR}/v1.Backrest/GetSummaryDashboard").mock(return_value=httpx.Response(200, json=DASHBOARD))
    assert await get_adapter("backrest").test({"url": BR}, ctx) == "Backrest answers with 4 backup plans."
    assert "Authorization" not in route.calls.last.request.headers


@respx.mock
async def test_a_rejected_password(ctx: Context) -> None:
    """⚠️ Measured: a wrong password gets the same words as no header at all."""
    respx.post(f"{BR}/v1.Backrest/GetSummaryDashboard").mock(return_value=httpx.Response(
        401, text="Unauthorized (No Authorization Header)\n", headers={"content-type": "text/plain; charset=utf-8"}))
    with pytest.raises(AuthFailed):
        await get_adapter("backrest").fetch("summary", CONFIG, {}, ctx)


@respx.mock
async def test_an_unreachable_backrest(ctx: Context) -> None:
    respx.post(f"{BR}/v1.Backrest/GetSummaryDashboard").mock(side_effect=httpx.ConnectError("connection refused"))
    with pytest.raises(Unreachable):
        await get_adapter("backrest").fetch("plans", CONFIG, {}, ctx)


@respx.mock
async def test_backing_up(ctx: Context) -> None:
    route = respx.post(f"{BR}/v1.Backrest/Backup").mock(return_value=httpx.Response(200, json={}))
    assert await get_adapter("backrest").action("plans", "backup", {"plan": "documents"}, CONFIG, {}, ctx) == "Backrest has finished the backup."
    assert json.loads(route.calls.last.request.content) == {"value": "documents"}
    route.mock(return_value=httpx.Response(500, json={"code": "unknown", "message": REASON}))
    with pytest.raises(AdapterError) as failed:
        await get_adapter("backrest").action("plans", "backup", {"plan": "missing"}, CONFIG, {}, ctx)
    assert failed.value.code == "action_failed" and failed.value.message == f"Backrest could not back up: {REASON}"
    route.mock(return_value=httpx.Response(404, json={"code": "not_found", "message": 'get plan "gone": plan not found'}))
    with pytest.raises(AdapterError) as gone:
        await get_adapter("backrest").action("plans", "backup", {"plan": "gone"}, CONFIG, {}, ctx)
    assert "plan not found" in gone.value.message
    route.mock(return_value=httpx.Response(401, text="Unauthorized (No Authorization Header)\n"))
    with pytest.raises(AuthFailed):
        await get_adapter("backrest").action("plans", "backup", {"plan": "documents"}, CONFIG, {}, ctx)


@respx.mock
async def test_a_backup_that_takes_longer_goes_on_without_the_card(ctx: Context) -> None:
    """⚠️ Measured: a request the client stopped waiting for still ran to a good snapshot."""
    respx.post(f"{BR}/v1.Backrest/Backup").mock(side_effect=httpx.ReadTimeout("still backing up"))
    assert await get_adapter("backrest").action("plans", "backup", {"plan": "documents"}, CONFIG, {}, ctx) == \
        "Backrest is backing up; it goes on in the background."


async def test_only_an_offered_backup_is_started(ctx: Context) -> None:
    with pytest.raises(AdapterError) as blank:
        await get_adapter("backrest").action("plans", "backup", {"plan": ""}, CONFIG, {}, ctx)
    assert blank.value.code == "bad_param"
    with pytest.raises(AdapterError) as unknown:
        await get_adapter("backrest").action("plans", "forget", {"plan": "documents"}, CONFIG, {}, ctx)
    assert unknown.value.code == "no_such_action"
