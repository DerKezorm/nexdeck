"""OpenWrt, against the answers of a live OpenWrt 25.12.5 with LuCI (26.09.2026); refusals seen alike on 24.10.8."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context

ROUTER = "http://router.example.com"
UBUS = f"{ROUTER}/ubus"
CONFIG = {"url": ROUTER, "username": "nexdeck", "password": "a-password-for-the-cards"}
ADAPTER = get_adapter("openwrt")
SESSION = "session-of-the-test-router"
DENIED = {"jsonrpc": "2.0", "id": 1, "error": {"code": -32002, "message": "Access denied"}}

BOARD = {"kernel": "6.12.107", "hostname": "router", "system": "ARMv8 Processor rev 4", "model": "GL.iNet GL-MT6000",
         "board_name": "glinet,gl-mt6000", "release": {"distribution": "OpenWrt", "version": "25.12.5", "revision": "r33051-f5dae5ece4",
                                                      "target": "mediatek/filogic", "description": "OpenWrt 25.12.5 r33051-f5dae5ece4"}}
INFO = {"localtime": 1790457737, "uptime": 911845, "load": [10816, 10528, 9376],
        "memory": {"total": 8333950976, "free": 210493440, "shared": 455204864, "buffered": 75194368, "available": 3059007488, "cached": 3025797120},
        "root": {"total": 257815288, "free": 188275576, "used": 69539712, "avail": 177748844}, "swap": {"total": 0, "free": 0}}
INTERFACES = {"interface": [
    {"interface": "iot", "up": False, "pending": False, "available": False, "autostart": False, "proto": "static", "device": "eth7", "data": {}},
    {"interface": "lan", "up": True, "pending": False, "available": True, "autostart": True, "proto": "static", "device": "eth0", "l3_device": "eth0",
     "uptime": 33, "ipv4-address": [{"address": "192.168.1.1", "mask": 24}], "route": []},
    {"interface": "loopback", "up": True, "autostart": True, "proto": "static", "device": "lo", "l3_device": "lo", "uptime": 33,
     "ipv4-address": [{"address": "127.0.0.1", "mask": 8}]},
    {"interface": "wan", "up": False, "pending": False, "available": False, "autostart": True, "proto": "dhcp", "device": "eth9",
     "errors": [{"subsystem": "interface", "code": "NO_DEVICE"}]},
]}
DEVICES = {"lo": {"up": True, "stats": {"rx_bytes": 0, "tx_bytes": 0}},
           "eth0": {"up": True, "stats": {"rx_bytes": 12616, "tx_bytes": 29821, "rx_packets": 131, "tx_packets": 108}}}
LEASES = {"dhcp_leases": [
    {"expires": 3350, "hostname": "office-printer", "macaddr": "02:00:5E:10:00:01", "ipaddr": "192.168.1.101"},
    {"expires": 39750, "macaddr": "02:00:5E:10:00:02", "ipaddr": "192.168.1.102"},
    # ⚠️ Ran out: 0. Handed out for good: false.
    {"expires": 0, "hostname": "tv-livingroom", "macaddr": "02:00:5E:10:00:03", "ipaddr": "192.168.1.103"},
    {"expires": False, "hostname": "nas", "macaddr": "02:00:5E:10:00:04", "ipaddr": "192.168.1.10"},
], "dhcp6_leases": []}

ANSWERS: dict[tuple[str, str], Any] = {("system", "board"): BOARD, ("system", "info"): INFO, ("network.interface", "dump"): INTERFACES,
                                        ("luci-rpc", "getNetworkDevices"): DEVICES, ("luci-rpc", "getDHCPLeases"): LEASES}


def router(*, password: str = CONFIG["password"], denied: frozenset[tuple[str, str]] = frozenset()) -> list[list[Any]]:
    """A fake uhttpd: logs in, answers the calls it knows, writes down what it was sent."""
    calls: list[list[Any]] = []

    def answer(request: httpx.Request) -> httpx.Response:
        params = json.loads(request.content)["params"]
        calls.append(params)
        session, target, method, arguments = params
        if (target, method) == ("session", "login"):
            ok = arguments == {"username": CONFIG["username"], "password": password}
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": [0, {"ubus_rpc_session": SESSION, "timeout": 300}] if ok else [6]})
        if session != SESSION or (target, method) in denied:
            return httpx.Response(200, json=DENIED)
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": [0, ANSWERS[(target, method)]]})

    respx.post(UBUS).mock(side_effect=answer)
    return calls


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


@respx.mock
async def test_the_test_names_firmware_and_model(ctx: Context) -> None:
    calls = router()
    assert await ADAPTER.test(CONFIG, ctx) == "OpenWrt 25.12.5 r33051-f5dae5ece4 answers on GL.iNet GL-MT6000."
    assert calls[0][:3] == ["0" * 32, "session", "login"]
    assert calls[1][0] == SESSION


@respx.mock
async def test_a_wrong_password_is_a_six_at_the_door(ctx: Context) -> None:
    router(password="something else")
    with pytest.raises(AuthFailed, match="rejected the user or the password"):
        await ADAPTER.test(CONFIG, ctx)


@respx.mock
async def test_a_stale_session_signs_in_again_and_a_missing_right_is_named(ctx: Context) -> None:
    calls = router()
    ctx.cache["openwrt_session"] = (("http://router.example.com", "nexdeck", CONFIG["password"]), "f" * 32)
    card = await ADAPTER.fetch("leases", CONFIG, {}, ctx)
    assert len(card.items) == 4
    assert [call[1:3] for call in calls] == [["luci-rpc", "getDHCPLeases"], ["session", "login"], ["luci-rpc", "getDHCPLeases"]]
    respx.reset()
    router(denied=frozenset({("system", "board")}))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.test(CONFIG, Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={}))
    assert caught.value.code == "forbidden" and caught.value.message == "The user may not call system board."
    assert "luci-mod-status-index" in caught.value.hint


@respx.mock
async def test_the_router_card_reads_load_and_memory_right(ctx: Context) -> None:
    router()
    card = await ADAPTER.fetch("system", CONFIG, {}, ctx)
    # ⚠️ Available memory, not free: 63 %, not 97 %.
    assert card.primary == {"label": "Memory used", "value": 63, "unit": "%"}
    assert {row["part"]: row["value"] for row in card.secondary} == {
        "load": "0.17 / 0.16 / 0.14", "uptime": "10d 13h", "firmware": "25.12.5", "storage": "27 %"}
    assert card.status == "ok"
    assert card.metrics == {"memory_percent": 63.0, "load": 10816 / 65536}


@respx.mock
async def test_the_router_card_asks_for_the_board_only_for_the_firmware(ctx: Context) -> None:
    calls = router()
    await ADAPTER.fetch("system", CONFIG, {"show_firmware": False}, ctx)
    assert ["system", "board"] not in [call[1:3] for call in calls]


@respx.mock
async def test_interfaces_down_first_loopback_left_out(ctx: Context) -> None:
    router()
    card = await ADAPTER.fetch("interfaces", CONFIG, {}, ctx)
    assert [(row["title"], row["subtitle"], row["value"], row["status"]) for row in card.items] == [
        ("wan", "DHCP client · No device", "Down", "bad"),
        ("iot", "Static address", "Switched off", "unknown"),
        ("lan", "Static address · 192.168.1.1/24 · up 33s · ↓ 12.3 KB ↑ 29.1 KB", "Up", "ok"),
    ]
    assert card.status == "bad"


@respx.mock
async def test_interfaces_without_traffic_do_not_ask_for_the_devices(ctx: Context) -> None:
    calls = router()
    card = await ADAPTER.fetch("interfaces", CONFIG, {"show_traffic": False, "show_uptime": False}, ctx)
    assert ["luci-rpc", "getNetworkDevices"] not in [call[1:3] for call in calls]
    assert card.items[2]["subtitle"] == "Static address · 192.168.1.1/24"


@respx.mock
async def test_leases_with_their_time_left(ctx: Context) -> None:
    router()
    card = await ADAPTER.fetch("leases", CONFIG, {}, ctx)
    assert [(row["title"], row["subtitle"], row["value"], row["status"]) for row in card.items] == [
        ("192.168.1.102", "02:00:5E:10:00:02", "11h 2m", "ok"),
        ("nas", "192.168.1.10 · 02:00:5E:10:00:04", "no end", "ok"),
        ("office-printer", "192.168.1.101 · 02:00:5E:10:00:01", "55m 50s", "ok"),
        ("tv-livingroom", "192.168.1.103 · 02:00:5E:10:00:03", "expired", "unknown"),
    ]
    assert card.metrics == {"leases": 4.0}


@respx.mock
async def test_without_ubus_the_router_says_what_to_install(ctx: Context) -> None:
    respx.post(UBUS).mock(return_value=httpx.Response(404, text="Not Found"))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.test(CONFIG, ctx)
    assert caught.value.code == "no_ubus" and "uhttpd-mod-ubus" in caught.value.hint


@pytest.mark.parametrize("kind", [widget.kind for widget in ADAPTER.widgets])
def test_demo_has_every_card(kind: str) -> None:
    for tick in range(4):
        card = ADAPTER.demo(kind, {}, tick)
        assert card.items or card.primary
