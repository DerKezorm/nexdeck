"""Calagopus. The answers have the form of a fresh all-in-one panel 1.2.7 (measured on 31.10.2026), with made-up names."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context, Unreachable, outbound_client

CONFIG = {"url": "https://panel.example.com", "api_key": "made-up-key"}
API = "https://panel.example.com/api/client"
SERVERS = f"{API}/servers"
NODE_A = "11111111-1111-4111-8111-111111111111"
NODE_B = "22222222-2222-4222-8222-222222222222"
SURVIVAL = "aaaaaaaa-0000-4000-8000-000000000001"
MODDED = "aaaaaaaa-0000-4000-8000-000000000002"
OLD = "aaaaaaaa-0000-4000-8000-000000000003"
NEW = "aaaaaaaa-0000-4000-8000-000000000004"


def server(uuid: str, name: str, node: str = NODE_A, **extra: Any) -> dict[str, Any]:
    return {"uuid": uuid, "uuid_short": uuid[:8], "name": name, "node_uuid": node, "status": None, "is_suspended": False,
            "is_transferring": False, "limits": {"memory": 4096, "cpu": 0, "swap": 0, "disk": 10240}, **extra}


def usage(state: str, memory: int = 0, cpu: float = 0.0, uptime: int = 0) -> dict[str, Any]:
    return {"state": state, "memory_bytes": memory, "memory_limit_bytes": 4700 * 1024 ** 2, "disk_bytes": 1, "cpu_absolute": cpu,
            "cpu_limit_absolute": 0.0, "uptime": uptime, "network": {"rx_bytes": 1, "rx_packets": 1, "tx_bytes": 1, "tx_packets": 1}}


def page(*servers: dict[str, Any], total: int | None = None) -> dict[str, Any]:
    return {"servers": {"total": len(servers) if total is None else total, "per_page": 100, "page": 1, "data": list(servers)}}


@pytest.fixture
def ctx() -> Context:
    return Context(outbound_client(guard=False), integration_id=1, widget_id=1, cache={})


def served() -> None:
    respx.get(SERVERS).mock(return_value=httpx.Response(200, json=page(
        server(SURVIVAL, "Survival"), server(MODDED, "Modded", NODE_B), server(OLD, "Old test", NODE_B, is_suspended=True))))
    respx.get(f"{SERVERS}/nodes/{NODE_A}/resources").mock(return_value=httpx.Response(200, json={
        "resources": {SURVIVAL: usage("running", 3 * 1024 ** 3, 41.6, 7_200_000)}}))
    respx.get(f"{SERVERS}/nodes/{NODE_B}/resources").mock(return_value=httpx.Response(200, json={
        "resources": {MODDED: usage("offline"), OLD: usage("offline")}}))


@respx.mock
async def test_the_overview_counts_running_offline_and_suspended(ctx: Context) -> None:
    served()
    data = await get_adapter("calagopus").fetch("overview", CONFIG, {}, ctx)
    assert data.primary == {"label": "Running", "value": 1}
    assert data.secondary == [{"label": "Servers", "value": 3}, {"label": "Offline", "value": 1}, {"label": "Suspended", "value": 1}]
    assert data.status == "warn" and data.metrics == {"running": 1.0, "offline": 1.0}
    request = respx.calls[0].request
    assert request.headers["Authorization"] == "Bearer made-up-key" and request.headers["Accept"] == "application/json"
    assert request.url.params["page"] == "1" and request.url.params["per_page"] == "100" and request.url.params["other"] == "false"


@respx.mock
async def test_each_node_is_asked_once_and_no_server_is_asked_alone(ctx: Context) -> None:
    served()
    respx.get(SERVERS).mock(return_value=httpx.Response(200, json=page(
        server(SURVIVAL, "Survival"), server(MODDED, "Modded"), server(NEW, "Fresh"))))
    await get_adapter("calagopus").fetch("servers", CONFIG, {}, ctx)
    asked = [call.request.url.path for call in respx.calls]
    assert asked == ["/api/client/servers", f"/api/client/servers/nodes/{NODE_A}/resources"]


@respx.mock
async def test_a_node_with_only_suspended_servers_is_not_asked(ctx: Context) -> None:
    respx.get(SERVERS).mock(return_value=httpx.Response(200, json=page(server(OLD, "Old test", NODE_B, is_suspended=True))))
    data = await get_adapter("calagopus").fetch("servers", CONFIG, {}, ctx)
    assert len(respx.calls) == 1 and data.items[0]["value"] == "Suspended"


@respx.mock
async def test_the_servers_card_gives_use_and_the_button_that_fits_the_state(ctx: Context) -> None:
    served()
    data = await get_adapter("calagopus").fetch("servers", CONFIG, {}, ctx)
    rows = {row["title"]: row for row in data.items}
    run = rows["Survival"]
    assert run["subtitle"] == "3.0 GB of 4.0 GB · CPU 42 % · up 2h"
    assert (run["status"], run["value"]) == ("ok", "Running")
    [stop] = run["actions"]
    assert (stop.id, stop.confirm, stop.danger, stop.params) == ("stop", True, True, {"id": SURVIVAL})
    [start] = rows["Modded"]["actions"]
    assert (start.id, start.confirm, start.danger, start.params) == ("start", True, False, {"id": MODDED})
    assert (rows["Modded"]["status"], rows["Modded"]["value"]) == ("bad", "Offline")  # issue #59: it was green
    assert data.items[-1]["title"] == "Modded"
    assert rows["Old test"]["actions"] == [] and rows["Old test"]["value"] == "Suspended"


@respx.mock
@pytest.mark.parametrize("trouble", [{"status": "installing"}, {"status": "install_failed"}, {"status": "restoring_backup"}, {"is_transferring": True}])
async def test_a_server_the_panel_refuses_every_signal_has_no_button_and_does_not_count_as_offline(ctx: Context, trouble: dict[str, Any]) -> None:
    respx.get(SERVERS).mock(return_value=httpx.Response(200, json=page(server(NEW, "Fresh", **trouble))))
    respx.get(f"{SERVERS}/nodes/{NODE_A}/resources").mock(return_value=httpx.Response(200, json={"resources": {NEW: usage("offline")}}))
    adapter = get_adapter("calagopus")
    [row] = (await adapter.fetch("servers", CONFIG, {}, ctx)).items
    assert (row["status"], row["value"], row["actions"]) == ("unknown", "Unknown", [])
    assert {"label": "Offline", "value": 0} in (await adapter.fetch("overview", CONFIG, {}, ctx)).secondary


@respx.mock
async def test_a_node_that_cannot_be_read_leaves_its_servers_unknown_and_the_others_alone(ctx: Context) -> None:
    served()
    respx.get(f"{SERVERS}/nodes/{NODE_B}/resources").mock(return_value=httpx.Response(502, text="wings is down"))
    adapter = get_adapter("calagopus")
    rows = {row["title"]: row for row in (await adapter.fetch("servers", CONFIG, {}, ctx)).items}
    assert (rows["Modded"]["status"], rows["Modded"]["value"], rows["Modded"]["actions"]) == ("unknown", "Unknown", [])
    assert rows["Survival"]["value"] == "Running"
    assert {"label": "Offline", "value": 0} in (await adapter.fetch("overview", CONFIG, {}, ctx)).secondary


@respx.mock
async def test_a_server_missing_from_the_answer_of_its_node_is_unknown(ctx: Context) -> None:
    served()
    respx.get(f"{SERVERS}/nodes/{NODE_B}/resources").mock(return_value=httpx.Response(200, json={"resources": {}}))
    rows = {row["title"]: row for row in (await get_adapter("calagopus").fetch("servers", CONFIG, {}, ctx)).items}
    assert rows["Modded"]["value"] == "Unknown"


@respx.mock
async def test_a_node_id_that_would_leave_its_place_in_the_address_is_refused(ctx: Context) -> None:
    respx.get(SERVERS).mock(return_value=httpx.Response(200, json=page(server(SURVIVAL, "Survival", "../../account"))))
    with pytest.raises(AdapterError) as failure:
        await get_adapter("calagopus").fetch("overview", CONFIG, {}, ctx)
    assert failure.value.code == "bad_param"
    assert len(respx.calls) == 1


@respx.mock
async def test_start_and_stop_post_the_action_and_nothing_else_is_accepted(ctx: Context) -> None:
    route = respx.post(f"{SERVERS}/{SURVIVAL}/power").mock(return_value=httpx.Response(200, json={}))
    adapter = get_adapter("calagopus")
    assert await adapter.action("servers", "stop", {"id": SURVIVAL}, CONFIG, {}, ctx) == "The server is stopping."
    assert json.loads(route.calls.last.request.content) == {"action": "stop"}
    await adapter.action("servers", "start", {"id": SURVIVAL}, CONFIG, {}, ctx)
    assert json.loads(route.calls.last.request.content) == {"action": "start"}
    for refused in ("kill", "restart"):
        with pytest.raises(AdapterError) as failure:
            await adapter.action("servers", refused, {"id": SURVIVAL}, CONFIG, {}, ctx)
        assert failure.value.code == "no_such_action" and "Calagopus" in str(failure.value)
    with pytest.raises(AdapterError) as failure:
        await adapter.action("servers", "stop", {"id": "../users"}, CONFIG, {}, ctx)
    assert failure.value.code == "bad_param"
    assert route.call_count == 2


@respx.mock
async def test_a_key_without_control_is_told_what_it_lacks(ctx: Context) -> None:
    respx.post(f"{SERVERS}/{SURVIVAL}/power").mock(return_value=httpx.Response(403, json={"errors": ["you do not have permission to perform this action"]}))
    with pytest.raises(AdapterError) as failure:
        await get_adapter("calagopus").action("servers", "start", {"id": SURVIVAL}, CONFIG, {}, ctx)
    assert failure.value.code == "not_allowed" and "control.start" in (failure.value.hint or "")


@respx.mock
async def test_a_signal_while_the_server_is_busy_says_so(ctx: Context) -> None:
    respx.post(f"{SERVERS}/{SURVIVAL}/power").mock(return_value=httpx.Response(409, json={"errors": ["server is currently installing"]}))
    with pytest.raises(AdapterError) as failure:
        await get_adapter("calagopus").action("servers", "start", {"id": SURVIVAL}, CONFIG, {}, ctx)
    assert failure.value.code == "server_busy"


@respx.mock
async def test_the_connection_test_counts_the_servers_with_one_small_page(ctx: Context) -> None:
    route = respx.get(SERVERS).mock(return_value=httpx.Response(200, json=page(server(SURVIVAL, "Survival"), total=3)))
    assert await get_adapter("calagopus").test(CONFIG, ctx) == "Calagopus answers, 3 server(s)."
    assert route.calls.last.request.url.params["per_page"] == "1"


@respx.mock
async def test_a_wrong_key_is_an_authentication_failure(ctx: Context) -> None:
    respx.get(SERVERS).mock(return_value=httpx.Response(401, json={"errors": ["invalid authorization token"]}))
    with pytest.raises(AuthFailed):
        await get_adapter("calagopus").fetch("overview", CONFIG, {}, ctx)


@respx.mock
async def test_a_page_instead_of_the_api_says_so(ctx: Context) -> None:
    route = respx.get(SERVERS).mock(return_value=httpx.Response(200, text="<html>panel</html>"))
    with pytest.raises(AdapterError) as failure:
        await get_adapter("calagopus").fetch("overview", CONFIG, {}, ctx)
    assert failure.value.code == "not_json"
    ctx.cache.clear()
    route.mock(return_value=httpx.Response(404, text="nope"))
    with pytest.raises(AdapterError) as failure:
        await get_adapter("calagopus").fetch("overview", CONFIG, {}, ctx)
    assert failure.value.code == "http_error" and "API Keys" in (failure.value.hint or "")


@respx.mock
async def test_an_unreachable_panel_is_unreachable(ctx: Context) -> None:
    respx.get(SERVERS).mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(Unreachable):
        await get_adapter("calagopus").fetch("overview", CONFIG, {}, ctx)


def test_the_demo_shows_the_same_cards_as_pterodactyl() -> None:
    adapter = get_adapter("calagopus")
    assert [widget.kind for widget in adapter.widgets] == ["overview", "servers"]
    assert adapter.beta is False, "measured against a panel, unlike Pterodactyl"
    assert adapter.demo("servers", {}, 0).items and adapter.demo("overview", {}, 0).primary["label"] == "Running"
