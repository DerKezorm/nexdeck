"""AMP. NOT measured: AMP needs a licence and was not started. The answers follow the
CubeCoders API documentation and the shape their client libraries read, with made-up
names, so these tests prove the reading, not AMP."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.amp import instances_of
from app.adapters.base import AdapterError, AuthFailed, Context, Unreachable, outbound_client

CONFIG = {"url": "http://amp:8080", "username": "nexdeck", "password": "example-pass"}
API = "http://amp:8080/API"
LOGIN = {"success": True, "sessionID": "session-1", "permissions": [], "userInfo": {"Username": "nexdeck"}}
INSTANCES = [{"InstanceID": "manager", "FriendlyName": "Local", "AvailableInstances": [
    {"InstanceID": "i1", "InstanceName": "Survival01", "FriendlyName": "Survival", "Module": "Minecraft", "Running": True, "AppState": 20,
     "Metrics": {"Active Users": {"RawValue": 3, "MaxValue": 20}, "CPU Usage": {"RawValue": 41.6, "MaxValue": 100},
                 "Memory Usage": {"RawValue": 2048, "MaxValue": 4096}}},
    {"InstanceID": "i2", "InstanceName": "Valheim01", "FriendlyName": "Valheim", "Module": "Valheim", "Running": False, "AppState": 100, "Metrics": {}},
    {"InstanceID": "i3", "InstanceName": "Rust01", "FriendlyName": "Rust", "Module": "Rust", "Running": False, "AppState": 0, "Metrics": {}},
    {"InstanceID": "i4", "InstanceName": "Old01", "FriendlyName": "Old", "Module": "Terraria", "Suspended": True, "AppState": 0, "Metrics": {}},
]}]


@pytest.fixture
def ctx() -> Context:
    return Context(outbound_client(guard=False), integration_id=1, widget_id=1, cache={})


def served() -> respx.Route:
    login = respx.post(f"{API}/Core/Login").mock(return_value=httpx.Response(200, json=LOGIN))
    respx.post(f"{API}/ADSModule/GetInstances").mock(return_value=httpx.Response(200, json=INSTANCES))
    return login


def sent(route: respx.Route) -> dict[str, Any]:
    return json.loads(route.calls.last.request.content)


@respx.mock
async def test_the_overview_counts_running_stopped_failed_and_players(ctx: Context) -> None:
    served()
    data = await get_adapter("amp").fetch("overview", CONFIG, {}, ctx)
    assert data.primary == {"label": "Running", "value": 1}
    assert data.secondary == [{"label": "Instances", "value": 4}, {"label": "Stopped", "value": 1},
                              {"label": "Failed", "value": 1}, {"label": "Players", "value": 3}]
    assert data.status == "bad" and data.metrics == {"running": 1.0, "players": 3.0}


@respx.mock
async def test_the_session_travels_in_the_body_and_is_kept_between_calls(ctx: Context) -> None:
    login = served()
    await get_adapter("amp").fetch("overview", CONFIG, {}, ctx)
    await get_adapter("amp").fetch("instances", CONFIG, {}, ctx)
    assert login.call_count == 1
    assert sent(login) == {"username": "nexdeck", "password": "example-pass", "token": "", "rememberMe": False}
    assert json.loads(respx.calls.last.request.content)["SESSIONID"] == "session-1"


@respx.mock
async def test_the_instances_card_gives_players_and_use_and_the_button_that_fits_the_state(ctx: Context) -> None:
    served()
    data = await get_adapter("amp").fetch("instances", CONFIG, {}, ctx)
    rows = {row["title"]: row for row in data.items}
    survival = rows["Survival"]
    assert survival["subtitle"] == "Minecraft · 3 of 20 players · CPU 42 % · 2048 of 4096 MB"
    assert (survival["status"], survival["value"]) == ("ok", "Running")
    [stop] = survival["actions"]
    assert (stop.id, stop.confirm, stop.danger, stop.params) == ("stop", True, True, {"name": "Survival01"})
    [start] = rows["Rust"]["actions"]
    assert (start.id, start.confirm, start.danger, start.params) == ("start", True, False, {"name": "Rust01"})
    # A failed instance can be started again; a suspended one cannot be touched.
    assert [action.id for action in rows["Valheim"]["actions"]] == ["start"]
    assert (rows["Old"]["value"], rows["Old"]["actions"]) == ("Suspended", [])
    assert data.items[0]["title"] == "Valheim" and data.items[0]["status"] == "bad"


def test_a_plain_list_of_instances_is_read_as_well_as_one_grouped_by_manager() -> None:
    plain = [{"InstanceName": "A"}, {"InstanceID": "b"}, {"nothing": 1}, "text"]
    assert [one.get("InstanceName") or one.get("InstanceID") for one in instances_of(plain)] == ["A", "b"]
    assert len(instances_of(INSTANCES)) == 4 and instances_of({"unexpected": True}) == []


@respx.mock
async def test_start_and_stop_call_the_instance_manager_and_nothing_else_is_accepted(ctx: Context) -> None:
    served()
    start = respx.post(f"{API}/ADSModule/StartInstance").mock(return_value=httpx.Response(200, json={"Status": True, "Reason": "", "Result": None}))
    stop = respx.post(f"{API}/ADSModule/StopInstance").mock(return_value=httpx.Response(200, json={"Status": True}))
    assert await get_adapter("amp").action("instances", "start", {"name": "Rust01"}, CONFIG, {}, ctx) == "The instance is starting."
    assert sent(start)["InstanceName"] == "Rust01"
    assert await get_adapter("amp").action("instances", "stop", {"name": "Rust01"}, CONFIG, {}, ctx) == "The instance is stopping."
    assert stop.call_count == 1
    for refused in ("kill", "restart", "delete"):
        with pytest.raises(AdapterError) as failure:
            await get_adapter("amp").action("instances", refused, {"name": "Rust01"}, CONFIG, {}, ctx)
        assert failure.value.code == "no_such_action"
    with pytest.raises(AdapterError) as failure:
        await get_adapter("amp").action("instances", "stop", {"name": "../x"}, CONFIG, {}, ctx)
    assert failure.value.code == "bad_param"


@respx.mock
async def test_an_instance_that_amp_would_not_start_says_why(ctx: Context) -> None:
    served()
    respx.post(f"{API}/ADSModule/StartInstance").mock(return_value=httpx.Response(200, json={"Status": False, "Reason": "Instance is suspended"}))
    with pytest.raises(AdapterError) as failure:
        await get_adapter("amp").action("instances", "start", {"name": "Old01"}, CONFIG, {}, ctx)
    assert failure.value.code == "not_done" and "suspended" in str(failure.value)


@respx.mock
async def test_a_session_that_ran_out_is_replaced_once(ctx: Context) -> None:
    login = respx.post(f"{API}/Core/Login").mock(return_value=httpx.Response(200, json=LOGIN))
    respx.post(f"{API}/ADSModule/GetInstances").mock(side_effect=[
        httpx.Response(200, json={"Title": "Unauthorized Access", "Message": "API call requires authentication"}),
        httpx.Response(200, json=INSTANCES)])
    data = await get_adapter("amp").fetch("overview", CONFIG, {}, ctx)
    assert data.primary["value"] == 1 and login.call_count == 2


@respx.mock
async def test_a_wrong_password_is_an_authentication_failure(ctx: Context) -> None:
    respx.post(f"{API}/Core/Login").mock(return_value=httpx.Response(200, json={"success": False, "resultReason": "Invalid credentials"}))
    with pytest.raises(AuthFailed):
        await get_adapter("amp").fetch("overview", CONFIG, {}, ctx)


@respx.mock
async def test_the_connection_test_counts_the_instances(ctx: Context) -> None:
    served()
    assert await get_adapter("amp").test(CONFIG, ctx) == "AMP answers, 4 instance(s)."


@respx.mock
async def test_another_service_instead_of_amp_is_told_apart(ctx: Context) -> None:
    route = respx.post(f"{API}/Core/Login").mock(return_value=httpx.Response(200, text="<html></html>"))
    with pytest.raises(AdapterError) as failure:
        await get_adapter("amp").fetch("overview", CONFIG, {}, ctx)
    assert failure.value.code == "not_json"
    route.mock(return_value=httpx.Response(404, text="nope"))
    with pytest.raises(AdapterError) as failure:
        await get_adapter("amp").fetch("overview", CONFIG, {}, outbound())
    assert failure.value.code == "http_error"


def outbound() -> Context:
    return Context(outbound_client(guard=False), integration_id=2, widget_id=2, cache={})


@respx.mock
async def test_an_unreachable_server_is_unreachable(ctx: Context) -> None:
    respx.post(f"{API}/Core/Login").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(Unreachable):
        await get_adapter("amp").fetch("overview", CONFIG, {}, ctx)
