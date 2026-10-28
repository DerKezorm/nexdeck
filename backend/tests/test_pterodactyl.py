"""Pterodactyl. NOT measured against a panel (it needs a database, Redis and a Wings node).
The answers follow Pterodactyl's documentation of the client API, with made-up names, so
these tests prove the reading, not the panel."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context, Unreachable, outbound_client

CONFIG = {"url": "https://panel.example.com", "api_key": "ptlc_example"}
API = "https://panel.example.com/api/client"


def server(identifier: str, name: str, **extra: Any) -> dict[str, Any]:
    return {"object": "server", "attributes": {"identifier": identifier, "name": name, "is_suspended": False,
                                                "limits": {"memory": 4096, "cpu": 0, "disk": 10240}, **extra}}


def stats(state: str, memory: int = 0, cpu: float = 0.0, uptime: int = 0) -> dict[str, Any]:
    return {"object": "stats", "attributes": {"current_state": state, "is_suspended": False, "resources": {
        "memory_bytes": memory, "cpu_absolute": cpu, "disk_bytes": 1, "network_rx_bytes": 1, "network_tx_bytes": 1, "uptime": uptime}}}


@pytest.fixture
def ctx() -> Context:
    return Context(outbound_client(guard=False), integration_id=1, widget_id=1, cache={})


def served() -> None:
    respx.get(API, params={"per_page": "100"}).mock(return_value=httpx.Response(200, json={
        "object": "list", "data": [server("a1b2c3d4", "Survival"), server("e5f6a7b8", "Modded"),
                                   server("03a4b5c6", "Old test", is_suspended=True)],
        "meta": {"pagination": {"total": 3, "count": 3, "per_page": 100, "current_page": 1, "total_pages": 1}}}))
    respx.get(f"{API}/servers/a1b2c3d4/resources").mock(return_value=httpx.Response(200, json=stats("running", 3 * 1024 ** 3, 41.6, 7_200_000)))
    respx.get(f"{API}/servers/e5f6a7b8/resources").mock(return_value=httpx.Response(200, json=stats("offline")))


@respx.mock
async def test_the_overview_counts_running_offline_and_suspended(ctx: Context) -> None:
    served()
    data = await get_adapter("pterodactyl").fetch("overview", CONFIG, {}, ctx)
    assert data.primary == {"label": "Running", "value": 1}
    assert data.secondary == [{"label": "Servers", "value": 3}, {"label": "Offline", "value": 1}, {"label": "Suspended", "value": 1}]
    assert data.status == "warn" and data.metrics == {"running": 1.0, "offline": 1.0}
    request = respx.calls[0].request
    assert request.headers["Authorization"] == "Bearer ptlc_example"
    assert request.headers["Accept"] == "Application/vnd.pterodactyl.v1+json"


@respx.mock
async def test_a_suspended_server_is_never_asked_for_resources(ctx: Context) -> None:
    served()
    await get_adapter("pterodactyl").fetch("servers", CONFIG, {}, ctx)
    assert not any("03a4b5c6" in str(call.request.url) and "resources" in str(call.request.url) for call in respx.calls)


@respx.mock
async def test_the_servers_card_gives_use_and_the_button_that_fits_the_state(ctx: Context) -> None:
    served()
    data = await get_adapter("pterodactyl").fetch("servers", CONFIG, {}, ctx)
    rows = {row["title"]: row for row in data.items}
    run = rows["Survival"]
    assert run["subtitle"] == "3.0 GB of 4.0 GB · CPU 42 % · up 2h"
    assert (run["status"], run["value"]) == ("ok", "Running")
    [stop] = run["actions"]
    assert (stop.id, stop.confirm, stop.danger, stop.params) == ("stop", True, True, {"id": "a1b2c3d4"})
    [start] = rows["Modded"]["actions"]
    assert (start.id, start.confirm, start.danger) == ("start", True, False)
    assert rows["Old test"]["actions"] == [] and rows["Old test"]["value"] == "Suspended"
    assert data.items[0]["title"] == "Old test"  # suspended is yellow, so it leads


@respx.mock
async def test_a_server_near_its_memory_limit_is_red(ctx: Context) -> None:
    served()
    respx.get(f"{API}/servers/a1b2c3d4/resources").mock(return_value=httpx.Response(200, json=stats("running", int(3.9 * 1024 ** 3), 90, 1000)))
    data = await get_adapter("pterodactyl").fetch("servers", CONFIG, {}, ctx)
    assert next(row for row in data.items if row["title"] == "Survival")["status"] == "bad"


@respx.mock
async def test_a_server_whose_resources_cannot_be_read_is_unknown_not_offline(ctx: Context) -> None:
    served()
    respx.get(f"{API}/servers/e5f6a7b8/resources").mock(return_value=httpx.Response(502, text="node down"))
    data = await get_adapter("pterodactyl").fetch("servers", CONFIG, {}, ctx)
    modded = next(row for row in data.items if row["title"] == "Modded")
    assert (modded["status"], modded["value"], modded["actions"]) == ("unknown", "Unknown", [])
    overview = await get_adapter("pterodactyl").fetch("overview", CONFIG, {}, ctx)
    assert {"label": "Offline", "value": 0} in overview.secondary


@respx.mock
async def test_start_and_stop_post_the_signal_and_nothing_else_is_accepted(ctx: Context) -> None:
    route = respx.post(f"{API}/servers/a1b2c3d4/power").mock(return_value=httpx.Response(204))
    assert await get_adapter("pterodactyl").action("servers", "stop", {"id": "a1b2c3d4"}, CONFIG, {}, ctx) == "The server is stopping."
    assert json.loads(route.calls.last.request.content) == {"signal": "stop"}
    await get_adapter("pterodactyl").action("servers", "start", {"id": "a1b2c3d4"}, CONFIG, {}, ctx)
    assert json.loads(route.calls.last.request.content) == {"signal": "start"}
    for refused in ("kill", "restart"):
        with pytest.raises(AdapterError) as failure:
            await get_adapter("pterodactyl").action("servers", refused, {"id": "a1b2c3d4"}, CONFIG, {}, ctx)
        assert failure.value.code == "no_such_action"
    with pytest.raises(AdapterError) as failure:
        await get_adapter("pterodactyl").action("servers", "stop", {"id": "../users"}, CONFIG, {}, ctx)
    assert failure.value.code == "bad_param"
    assert route.call_count == 2


@respx.mock
async def test_a_power_signal_the_panel_refuses_says_why(ctx: Context) -> None:
    respx.post(f"{API}/servers/a1b2c3d4/power").mock(return_value=httpx.Response(403, json={"errors": [{"code": "AccessDeniedHttpException"}]}))
    with pytest.raises(AdapterError) as failure:
        await get_adapter("pterodactyl").action("servers", "start", {"id": "a1b2c3d4"}, CONFIG, {}, ctx)
    assert failure.value.code == "not_allowed"


@respx.mock
async def test_the_connection_test_counts_the_servers(ctx: Context) -> None:
    served()
    respx.get(API, params={"per_page": "1"}).mock(return_value=httpx.Response(200, json={
        "data": [], "meta": {"pagination": {"total": 3}}}))
    assert await get_adapter("pterodactyl").test(CONFIG, ctx) == "Pterodactyl answers, 3 server(s)."


@respx.mock
async def test_a_wrong_key_is_an_authentication_failure(ctx: Context) -> None:
    respx.get(API).mock(return_value=httpx.Response(401, json={"errors": [{"code": "AuthenticationException"}]}))
    with pytest.raises(AuthFailed):
        await get_adapter("pterodactyl").fetch("overview", CONFIG, {}, ctx)


@respx.mock
async def test_a_page_instead_of_the_api_says_so(ctx: Context) -> None:
    route = respx.get(API).mock(return_value=httpx.Response(200, text="<html>panel</html>"))
    with pytest.raises(AdapterError) as failure:
        await get_adapter("pterodactyl").fetch("overview", CONFIG, {}, ctx)
    assert failure.value.code == "not_json"
    ctx.cache.clear()
    route.mock(return_value=httpx.Response(404, text="nope"))
    with pytest.raises(AdapterError) as failure:
        await get_adapter("pterodactyl").fetch("overview", CONFIG, {}, ctx)
    assert failure.value.code == "http_error" and "ptlc_" in (failure.value.hint or "")


@respx.mock
async def test_an_unreachable_panel_is_unreachable(ctx: Context) -> None:
    respx.get(API).mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(Unreachable):
        await get_adapter("pterodactyl").fetch("overview", CONFIG, {}, ctx)
