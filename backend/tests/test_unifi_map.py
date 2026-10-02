"""The UniFi network map, shaped after a console of 24 devices measured on
01.10.2026 (Network 9): the device list carries no uplink, each device's
detail names its uplink as ``uplink.deviceId``, the gateway none, and
clients name their device as ``uplinkDeviceId``. Names here are made up."""

from __future__ import annotations

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, Context, outbound_client

CONFIG = {"url": "https://unifi.example.com", "api_key": "key", "site": "default"}
API = "https://unifi.example.com/proxy/network/integration/v1"
DEVICES = [
    {"id": "gw", "name": "Dream Machine", "model": "UDM-Pro", "features": ["switching"], "state": "ONLINE"},
    {"id": "core", "name": "Core", "model": "USW-24-PoE", "features": ["switching"], "state": "ONLINE"},
    {"id": "mesh1", "name": "Shed AP", "model": "U6-Mesh", "features": ["accessPoint"], "state": "ONLINE"},
    {"id": "mesh2", "name": "Garden AP", "model": "U6-Mesh", "features": ["accessPoint"], "state": "OFFLINE"},
]
UPLINK = {"gw": None, "core": {"deviceId": "gw"}, "mesh1": {"deviceId": "core"}, "mesh2": {"deviceId": "mesh1"}}


@pytest.fixture
def ctx() -> Context:
    return Context(outbound_client(guard=False), integration_id=1, widget_id=1, cache={})


def _console() -> None:
    respx.get(f"{API}/sites").mock(return_value=httpx.Response(200, json={"data": [{"id": "s1", "internalReference": "default", "name": "Default"}], "totalCount": 1}))
    respx.get(f"{API}/sites/s1/devices").mock(return_value=httpx.Response(200, json={"data": DEVICES, "totalCount": len(DEVICES)}))
    for device in DEVICES:
        respx.get(f"{API}/sites/s1/devices/{device['id']}").mock(return_value=httpx.Response(200, json={**device, "uplink": UPLINK[device["id"]]}))
    clients = [{"id": f"c{n}", "uplinkDeviceId": "mesh1" if n < 3 else "core"} for n in range(5)]
    respx.get(f"{API}/sites/s1/clients").mock(return_value=httpx.Response(200, json={"data": clients, "totalCount": len(clients)}))


@respx.mock
async def test_every_device_hangs_on_the_one_it_uplinks_to_however_deep(ctx: Context) -> None:
    _console()
    data = await get_adapter("unifi").fetch("map", CONFIG, {}, ctx)
    places = {place["id"]: place for place in data.meta["topology"]["places"]}
    assert places["gw"]["parent"] is None and places["gw"]["kind"] == "gateway"
    assert (places["core"]["parent"], places["mesh1"]["parent"], places["mesh2"]["parent"]) == ("gw", "core", "mesh1")
    assert places["mesh1"]["detail"] == "U6-Mesh · 3 clients" and places["core"]["detail"] == "USW-24-PoE · 2 clients"
    assert places["mesh2"]["status"] == "bad" and places["mesh2"]["detail"] == "offline"
    assert data.status == "warn" and data.primary["value"] == 3


@respx.mock
async def test_a_device_whose_uplink_is_not_on_the_list_stands_at_the_top(ctx: Context) -> None:
    UPLINK["mesh1"] = {"deviceId": "elsewhere"}
    try:
        _console()
        places = {p["id"]: p for p in (await get_adapter("unifi").fetch("map", CONFIG, {}, ctx)).meta["topology"]["places"]}
    finally:
        UPLINK["mesh1"] = {"deviceId": "core"}
    assert places["mesh1"]["parent"] is None


async def test_the_old_api_says_the_map_needs_a_key(ctx: Context) -> None:
    with pytest.raises(AdapterError) as refused:
        await get_adapter("unifi").fetch("map", {"url": "https://unifi.example.com", "username": "u", "password": "p"}, {}, ctx)
    assert refused.value.code == "needs_api_key"
