"""FortiGate (issue #41). The answers are shaped after Fortinet's administration
guide and the Linuxfabrik monitoring plugins, which read the same endpoints;
the names, addresses and numbers are made up."""

from __future__ import annotations

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context, outbound_client

CONFIG = {"url": "https://fortigate.example.com", "token": "fortios-example-token"}
BASE = "https://fortigate.example.com/api/v2/monitor"


def envelope(results, **extra) -> dict:
    return {"http_method": "GET", "results": results, "vdom": "root", "path": "system", "name": "x",
            "status": "success", "serial": "FGT60FTK00000001", "version": "v7.4.8", "build": 2795, **extra}


@pytest.fixture
def ctx() -> Context:
    return Context(outbound_client(guard=False), integration_id=1, widget_id=1, cache={})


@respx.mock
async def test_the_system_card_reads_cpu_memory_sessions_and_the_version(ctx: Context) -> None:
    route = respx.get(f"{BASE}/system/resource/usage").mock(return_value=httpx.Response(200, json=envelope({
        "cpu": [{"current": 12, "historical": {}}], "mem": [{"current": 57}], "session": [{"current": 3120}],
    })))
    data = await get_adapter("fortigate").fetch("system", CONFIG, {}, ctx)
    assert data.primary == {"label": "CPU", "value": 12, "unit": "%"}
    assert data.secondary == [
        {"label": "Memory", "value": 57, "unit": "%"},
        {"label": "Sessions", "value": 3120},
        {"label": "FortiOS", "value": "v7.4.8"},
    ]
    assert data.metrics == {"cpu": 12.0, "memory": 57.0, "sessions": 3120.0}
    assert data.status == "ok"
    request = route.calls.last.request
    # The token rides in the header, never in the address.
    assert request.headers["Authorization"] == "Bearer fortios-example-token"
    assert "access_token" not in str(request.url)
    assert "vdom" not in request.url.params


@respx.mock
async def test_the_vdom_goes_with_every_request(ctx: Context) -> None:
    route = respx.get(f"{BASE}/system/resource/usage").mock(return_value=httpx.Response(200, json=envelope({"cpu": [{"current": 97}], "mem": [{"current": 40}]})))
    data = await get_adapter("fortigate").fetch("system", {**CONFIG, "vdom": "branch"}, {}, ctx)
    assert route.calls.last.request.url.params["vdom"] == "branch"
    assert data.status == "bad", "97 % of the processor is past the alarm line"
    assert "sessions" not in data.metrics, "a reading that never came is not written down as zero"


@respx.mock
async def test_named_interfaces_turn_the_card_red_when_one_has_no_link(ctx: Context) -> None:
    respx.get(f"{BASE}/system/interface/select").mock(return_value=httpx.Response(200, json=envelope({
        "wan1": {"id": "wan1", "name": "wan1", "alias": "Fibre", "ip": "203.0.113.24", "mask": 29, "link": True, "speed": 1000,
                 "duplex": 1, "rx_bytes": 1024 ** 4, "tx_bytes": 2 * 1024 ** 3, "rx_errors": 0, "tx_errors": 0},
        "wan2": {"id": "wan2", "name": "wan2", "alias": "", "ip": "0.0.0.0", "mask": 0, "link": False, "speed": 0,
                 "duplex": 0, "rx_bytes": 0, "tx_bytes": 0, "rx_errors": 2, "tx_errors": 1},
        "internal1": {"id": "internal1", "name": "internal1", "link": False, "speed": 0},
    })))
    data = await get_adapter("fortigate").fetch("interfaces", CONFIG, {"names": "wan1, wan2, wan3"}, ctx)
    titles = [item["title"] for item in data.items]
    assert titles == ["wan1 (Fibre)", "wan2", "wan3"], "only the named ones, in the order named"
    wan1, wan2, wan3 = data.items
    assert wan1["subtitle"] == "203.0.113.24/29 · 1000 Mbit/s · ↓ 1.0 TB ↑ 2.0 GB" and wan1["status"] == "ok"
    assert (wan2["value"], wan2["status"]) == ("down", "bad")
    assert wan2["subtitle"] == "↓ 0 B ↑ 0 B · 3 errors"
    assert (wan3["subtitle"], wan3["status"]) == ("Not on this FortiGate", "bad")
    assert data.status == "bad" and data.metrics == {"interfaces_down": 2.0}
    assert data.secondary == [{"label": "Up", "value": 1}, {"label": "Down", "value": 2}]


@respx.mock
async def test_a_free_port_is_no_fault_when_nothing_was_named(ctx: Context) -> None:
    respx.get(f"{BASE}/system/interface/select").mock(return_value=httpx.Response(200, json=envelope({
        "wan1": {"name": "wan1", "link": True, "speed": 1000},
        "internal7": {"name": "internal7", "link": False},
    })))
    data = await get_adapter("fortigate").fetch("interfaces", CONFIG, {}, ctx)
    assert data.status == "ok"
    assert [item["status"] for item in data.items] == ["ok", "unknown"]


@respx.mock
async def test_ipsec_tunnels_count_their_selectors(ctx: Context) -> None:
    respx.get(f"{BASE}/vpn/ipsec").mock(return_value=httpx.Response(200, json=envelope([
        {"name": "to-branch", "rgwy": "198.51.100.40", "type": "automatic", "incoming_bytes": 1024 ** 3, "outgoing_bytes": 512 * 1024 ** 2,
         "proxyid": [{"p2name": "to-branch", "status": "up"}]},
        {"name": "to-datacentre", "rgwy": "203.0.113.90", "type": "automatic", "incoming_bytes": 0, "outgoing_bytes": 0,
         "proxyid": [{"p2name": "lan", "status": "up"}, {"p2name": "dmz", "status": "down"}]},
        {"name": "to-old-site", "rgwy": "192.0.2.10", "type": "automatic", "proxyid": [{"p2name": "to-old-site", "status": "down"}]},
        {"name": "dialup-template", "type": "dialup", "proxyid": []},
    ])))
    data = await get_adapter("fortigate").fetch("ipsec", CONFIG, {}, ctx)
    assert [(item["title"], item["value"], item["status"]) for item in data.items] == [
        ("to-old-site", "down", "bad"),
        ("to-datacentre", "1 of 2 up", "warn"),
        ("to-branch", "up", "ok"),
    ]
    assert data.items[2]["subtitle"] == "198.51.100.40 · ↓ 1.0 GB ↑ 512.0 MB"
    assert data.status == "bad" and data.metrics == {"tunnels_down": 1.0}
    assert data.secondary == [{"label": "Up", "value": 1}, {"label": "Down", "value": 1}]


@respx.mock
async def test_the_cluster_names_the_primary_and_the_sync(ctx: Context) -> None:
    respx.get(f"{BASE}/system/ha-peer").mock(return_value=httpx.Response(200, json=envelope([
        {"serial_no": "FGT60FTK00000002", "hostname": "fw-office-b", "priority": 100, "primary": False},
        {"serial_no": "FGT60FTK00000001", "hostname": "fw-office-a", "priority": 200, "primary": True},
    ])))
    checksums = respx.get(f"{BASE}/system/ha-checksums").mock(return_value=httpx.Response(200, json=envelope([
        {"serial_no": "FGT60FTK00000001", "checksum": {"global": "a", "root": "b", "all": "c1"}},
        {"serial_no": "FGT60FTK00000002", "checksum": {"global": "a", "root": "b", "all": "c1"}},
    ])))
    data = await get_adapter("fortigate").fetch("ha", CONFIG, {}, ctx)
    assert [(item["title"], item["value"]) for item in data.items] == [("fw-office-a", "Primary"), ("fw-office-b", "Secondary")]
    assert data.items[0]["subtitle"] == "FGT60FTK00000001 · priority 200"
    assert data.secondary == [{"label": "Members", "value": 2}, {"label": "Configuration", "value": "in sync"}]
    assert data.status == "ok"
    checksums.mock(return_value=httpx.Response(200, json=envelope([
        {"serial_no": "FGT60FTK00000001", "checksum": {"all": "c1"}},
        {"serial_no": "FGT60FTK00000002", "checksum": {"all": "c2"}},
    ])))
    ctx.cache.clear()
    drifted = await get_adapter("fortigate").fetch("ha", CONFIG, {}, ctx)
    assert drifted.secondary[-1] == {"label": "Configuration", "value": "out of sync"} and drifted.status == "warn"


@respx.mock
async def test_a_fortigate_on_its_own_is_not_a_cluster(ctx: Context) -> None:
    respx.get(f"{BASE}/system/ha-peer").mock(return_value=httpx.Response(424, json={"status": "error", "http_status": 424}))
    data = await get_adapter("fortigate").fetch("ha", CONFIG, {}, ctx)
    assert data.items == [] and data.meta == {"empty": "This FortiGate is not in a cluster."}


@respx.mock
async def test_a_refused_token_is_an_authentication_failure_even_for_the_cluster(ctx: Context) -> None:
    respx.get(f"{BASE}/system/ha-peer").mock(return_value=httpx.Response(401))
    with pytest.raises(AuthFailed):
        await get_adapter("fortigate").fetch("ha", CONFIG, {}, ctx)


@respx.mock
async def test_an_error_inside_the_envelope_is_not_taken_for_data(ctx: Context) -> None:
    respx.get(f"{BASE}/vpn/ipsec").mock(return_value=httpx.Response(200, json={"status": "error", "results": []}))
    with pytest.raises(AdapterError) as failure:
        await get_adapter("fortigate").fetch("ipsec", CONFIG, {}, ctx)
    assert failure.value.code == "fortios_error"


@respx.mock
async def test_the_connection_test_names_model_and_version(ctx: Context) -> None:
    respx.get(f"{BASE}/system/status").mock(return_value=httpx.Response(200, json=envelope({"model_name": "FortiGate", "model_number": "60F", "model": "FGT60F", "hostname": "fw-office-a"})))
    assert await get_adapter("fortigate").test(CONFIG, ctx) == "FGT60F answers, FortiOS v7.4.8."
