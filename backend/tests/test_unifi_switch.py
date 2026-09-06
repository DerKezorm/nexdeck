"""One UniFi switch, port by port, and the dropdown that picks it.

⚠️ What hangs on a port is not in here, and cannot be. The Integration API
tells a client which *device* it uplinks to and never which port, so this card
is about the ports themselves. Saying that out loud is the point: a card that
quietly answers a different question is worse than one that answers none.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, Context, shape_for_display

CONSOLE = "https://unifi.example.com"
KEY = {"url": CONSOLE, "api_key": "a-key", "site": "default", "unifi_os": True, "insecure": True}
ACCOUNT = {"url": CONSOLE, "username": "reader", "password": "a-long-enough-password", "site": "default", "unifi_os": True}

SITES = {"data": [{"id": "site-1", "internalReference": "default", "name": "Default"}], "totalCount": 1}
DEVICES = {"data": [
    {"id": "sw-1", "name": "Rack", "model": "USW-24-PoE", "features": ["switching"], "state": "ONLINE"},
    {"id": "sw-2", "name": "Attic", "model": "USW-Flex-Mini", "features": ["switching"], "state": "ONLINE"},
    {"id": "ap-1", "name": "Hallway", "model": "U7-Lite", "features": ["accessPoint"], "state": "ONLINE"},
], "totalCount": 3}
DETAIL = {
    "id": "sw-1", "name": "Rack", "model": "USW-24-PoE",
    # ⚠️ Deliberately out of order. A console is under no obligation to send
    # them sorted, and a fixture that is already in order proves nothing about
    # the sorting.
    "interfaces": {"ports": [
        {"idx": 3, "state": "DOWN", "connector": "RJ45", "maxSpeedMbps": 1000, "speedMbps": 0,
         "poe": {"enabled": False}},
        {"idx": 1, "state": "UP", "connector": "RJ45", "maxSpeedMbps": 1000, "speedMbps": 1000,
         "poe": {"standard": "802.3at", "enabled": True, "state": "UP"}},
        {"idx": 2, "state": "UP", "connector": "RJ45", "maxSpeedMbps": 1000, "speedMbps": 100,
         "poe": {"enabled": True, "state": "DOWN"}},
    ]},
}


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


def _console() -> None:
    base = f"{CONSOLE}/proxy/network/integration/v1"
    respx.get(f"{base}/sites").mock(return_value=httpx.Response(200, json=SITES))
    respx.get(f"{base}/sites/site-1/devices").mock(return_value=httpx.Response(200, json=DEVICES))
    respx.get(f"{base}/sites/site-1/devices/sw-1").mock(return_value=httpx.Response(200, json=DETAIL))


# ---------------------------------------------------------------------------
# The dropdown
# ---------------------------------------------------------------------------


@respx.mock
async def test_the_dropdown_offers_the_switches_and_nothing_else(ctx: Context) -> None:
    _console()
    offered = await get_adapter("unifi").choices("device", KEY, ctx)
    assert [value for value, _label in offered] == ["sw-2", "sw-1"], "by name, so the list reads like a list"
    assert offered[1] == ("sw-1", "Rack (USW-24-PoE)")


@respx.mock
async def test_the_dropdown_answers_nothing_for_a_field_it_does_not_know(ctx: Context) -> None:
    _console()
    assert await get_adapter("unifi").choices("colour", KEY, ctx) == []


async def test_the_dropdown_stays_empty_without_the_integration_api(ctx: Context) -> None:
    """⚠️ The old API knows a device by its MAC and the new one by an id. An
    id picked under one is meaningless under the other, so the list is not
    offered at all rather than offered and wrong."""
    assert await get_adapter("unifi").choices("device", ACCOUNT, ctx) == []


# ---------------------------------------------------------------------------
# The card
# ---------------------------------------------------------------------------


@respx.mock
async def test_a_card_without_a_switch_says_so_and_names_the_ones_there_are(ctx: Context) -> None:
    _console()
    with pytest.raises(AdapterError) as raised:
        await get_adapter("unifi").fetch("switch", KEY, {}, ctx)
    assert raised.value.code == "no_switch_picked"
    assert "Rack" in raised.value.hint and "Attic" in raised.value.hint


@respx.mock
async def test_a_switch_that_is_gone_is_not_silently_replaced(ctx: Context) -> None:
    """Somebody swapped the hardware; the card must not quietly show another."""
    _console()
    with pytest.raises(AdapterError) as raised:
        await get_adapter("unifi").fetch("switch", KEY, {"device": "sw-99"}, ctx)
    assert raised.value.code == "no_switch_picked"
    assert "any more" in raised.value.message


@respx.mock
async def test_every_port_becomes_a_row(ctx: Context) -> None:
    _console()
    data = await get_adapter("unifi").fetch("switch", KEY, {"device": "sw-1"}, ctx)
    assert [item["title"] for item in data.items] == ["Port 1", "Port 2", "Port 3"], "by number, whatever order they arrive in"
    assert [item["status"] for item in data.items] == ["ok", "ok", "unknown"]


@respx.mock
async def test_a_port_says_what_it_runs_at_and_what_it_could(ctx: Context) -> None:
    _console()
    data = await get_adapter("unifi").fetch("switch", KEY, {"device": "sw-1"}, ctx)
    assert data.items[0]["subtitle"].startswith("1 Gbit/s"), "at full speed, no comparison needed"
    assert data.items[1]["subtitle"].startswith("100 Mbit/s of 1 Gbit/s"), "below it, so say both"
    assert data.items[2]["subtitle"] == "not connected"


@respx.mock
async def test_a_port_says_whether_it_is_giving_power(ctx: Context) -> None:
    _console()
    data = await get_adapter("unifi").fetch("switch", KEY, {"device": "sw-1"}, ctx)
    assert "PoE 802.3at" in data.items[0]["subtitle"]
    assert "PoE ready" in data.items[1]["subtitle"], "able to, not doing it"
    assert "PoE" not in data.items[2]["subtitle"], "a port without it says nothing"


@respx.mock
async def test_the_card_names_the_switch_it_is_showing(ctx: Context) -> None:
    """⚠️ A console can hold a dozen. A card titled "Switch" showing five
    ports is a card nobody can place."""
    _console()
    data = await get_adapter("unifi").fetch("switch", KEY, {"device": "sw-1"}, ctx)
    assert data.secondary[0] == {"label": "Switch", "value": "Rack"}
    assert {chip["label"]: chip["value"] for chip in data.secondary}["Ports up"] == "2 / 3"


@respx.mock
async def test_empty_ports_can_be_left_out(ctx: Context) -> None:
    _console()
    data = await get_adapter("unifi").fetch("switch", KEY, {"device": "sw-1", "hide_empty": True}, ctx)
    assert [item["title"] for item in data.items] == ["Port 1", "Port 2"]


@respx.mock
async def test_speed_and_power_can_be_switched_off_like_any_other_part(ctx: Context) -> None:
    _console()
    adapter = get_adapter("unifi")
    options = {"device": "sw-1", "show_poe": False}
    data = shape_for_display(await adapter.fetch("switch", KEY, options, ctx), adapter, "switch", options)
    assert "PoE" not in data.items[0]["subtitle"]
    assert data.items[0]["subtitle"] == "1 Gbit/s"


async def test_the_card_says_it_needs_the_integration_api_rather_than_staying_empty(ctx: Context) -> None:
    with pytest.raises(AdapterError) as raised:
        await get_adapter("unifi").fetch("switch", ACCOUNT, {"device": "sw-1"}, ctx)
    assert raised.value.code == "needs_api_key"
