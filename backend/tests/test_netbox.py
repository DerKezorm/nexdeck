"""NetBox, against the answers of a live NetBox 4.7.0 (11.09.2026)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AuthFailed, Context
from app.adapters.netbox import usable

NB = "http://netbox.example.com"
CONFIG = {"url": NB, "token": "nbt_madeupkey.made-up-secret"}


def device(identifier: int, name: str, status: str, label: str) -> dict[str, Any]:
    return {"id": identifier, "url": f"{NB}/api/dcim/devices/{identifier}/", "display_url": f"{NB}/dcim/devices/{identifier}/", "display": name, "name": name,
            "device_type": {"id": 1, "model": "Box 1"}, "role": {"id": 1, "name": "Server", "slug": "server"},
            "site": {"id": 1, "name": "Home", "slug": "home"}, "status": {"value": status, "label": label}, "primary_ip": None}


def prefix(identifier: int, cidr: str, status: str, label: str) -> dict[str, Any]:
    return {"id": identifier, "display_url": f"{NB}/ipam/prefixes/{identifier}/", "prefix": cidr, "status": {"value": status, "label": label},
            "vrf": None, "children": 0, "_depth": 0, "mark_utilized": False, "is_pool": False, "family": {"value": 4, "label": "IPv4"}}


#: Measured with status__n=active: sorted by name, as NetBox answered.
NOT_ACTIVE = [device(5, "broken-ups", "failed", "Failed"), device(4, "new-switch", "planned", "Planned"), device(3, "old-pi", "offline", "Offline")]


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


def test_how_many_addresses_a_prefix_hands_out() -> None:
    assert usable("192.0.2.0/24") == 254 and usable("192.0.2.0/30") == 2
    assert usable("192.0.2.0/31") == 2 and usable("192.0.2.1/32") == 1
    assert usable("2001:db8::/120") == 256 and usable("2001:db8::/64") is None and usable("not a prefix") is None


@respx.mock
async def test_devices_that_are_not_active_the_worst_first(ctx: Context) -> None:
    route = respx.get(f"{NB}/api/dcim/devices/").mock(return_value=httpx.Response(200, json={"count": 3, "next": None, "results": NOT_ACTIVE}))
    data = await get_adapter("netbox").fetch("devices", {**CONFIG, "token": f"  {CONFIG['token']} "}, {"limit": 10}, ctx)
    request = route.calls.last.request
    # ⚠️ Measured: a v2 token only works whole, with Bearer; pasted spaces must not break it.
    assert request.headers["Authorization"] == "Bearer nbt_madeupkey.made-up-secret"
    assert dict(request.url.params) == {"limit": "200", "status__n": "active"}
    assert [(row["title"], row["subtitle"], row["status"]) for row in data.items] == [
        ("broken-ups", "Failed · Home · Server", "bad"), ("old-pi", "Offline · Home · Server", "warn"), ("new-switch", "Planned · Home · Server", "unknown")]
    assert data.items[0]["url"] == f"{NB}/dcim/devices/5/"
    assert data.secondary == [{"label": "Not active", "value": 3}] and data.status == "bad"


@respx.mock
async def test_all_devices_when_asked(ctx: Context) -> None:
    everything = [device(1, "nas", "active", "Active"), *NOT_ACTIVE, device(2, "router", "active", "Active")]
    route = respx.get(f"{NB}/api/dcim/devices/").mock(return_value=httpx.Response(200, json={"count": 5, "results": everything}))
    data = await get_adapter("netbox").fetch("devices", CONFIG, {"all": True, "limit": 10}, ctx)
    assert "status__n" not in route.calls.last.request.url.params
    assert [row["title"] for row in data.items] == ["broken-ups", "old-pi", "new-switch", "nas", "router"]
    assert data.secondary == [{"label": "Devices", "value": 5}]


@respx.mock
async def test_prefixes_with_the_addresses_counted_inside(ctx: Context) -> None:
    respx.get(f"{NB}/api/ipam/prefixes/").mock(return_value=httpx.Response(200, json={"count": 3, "results": [
        prefix(1, "192.0.2.0/24", "active", "Active"), prefix(2, "198.51.100.0/24", "reserved", "Reserved"), prefix(3, "203.0.113.0/30", "active", "Active")]}))
    counts = {"192.0.2.0/24": 3, "198.51.100.0/24": 0, "203.0.113.0/30": 2}
    addresses = respx.get(f"{NB}/api/ipam/ip-addresses/").mock(side_effect=lambda request: httpx.Response(
        200, json={"count": counts[request.url.params["parent"]], "results": []}))
    data = await get_adapter("netbox").fetch("prefixes", CONFIG, {"limit": 8}, ctx)
    assert addresses.call_count == 3
    assert [(row["title"], row["subtitle"], row["value"], row["progress"], row["status"]) for row in data.items] == [
        ("192.0.2.0/24", "Active", "1%", 1.0, "ok"), ("198.51.100.0/24", "Reserved", "0%", 0.0, "ok"), ("203.0.113.0/30", "Active", "100%", 100.0, "bad")]
    assert data.secondary == [{"label": "Prefixes", "value": 3}]


@respx.mock
async def test_the_summary_counts_without_paging(ctx: Context) -> None:
    def counted(request: httpx.Request) -> httpx.Response:
        assert request.url.params["limit"] == "1"
        path = request.url.path
        number = {"/api/dcim/sites/": 2, "/api/ipam/ip-addresses/": 3}.get(path, 3 if "status__n" in request.url.params else 5)
        return httpx.Response(200, json={"count": number, "next": None, "results": []})
    for path in ("/api/dcim/devices/", "/api/dcim/sites/", "/api/ipam/ip-addresses/"):
        respx.get(f"{NB}{path}").mock(side_effect=counted)
    data = await get_adapter("netbox").fetch("summary", CONFIG, {}, ctx)
    assert data.primary == {"label": "Devices", "value": 5}
    assert data.secondary == [{"label": "Not active", "value": 3}, {"label": "Sites", "value": 2}, {"label": "IP addresses", "value": 3}]


@respx.mock
async def test_a_refused_token(ctx: Context) -> None:
    respx.get(f"{NB}/api/status/").mock(return_value=httpx.Response(403, json={"detail": "Invalid v1 token"}))
    with pytest.raises(AuthFailed, match="nbt_"):
        await get_adapter("netbox").test(CONFIG, ctx)


@respx.mock
async def test_the_connection_test(ctx: Context) -> None:
    respx.get(f"{NB}/api/status/").mock(return_value=httpx.Response(200, json={"django-version": "6.1", "netbox-version": "4.7.0", "plugins": {}}))
    respx.get(f"{NB}/api/dcim/devices/").mock(return_value=httpx.Response(200, json={"count": 5, "results": []}))
    assert await get_adapter("netbox").test(CONFIG, ctx) == "NetBox 4.7.0 answers with 5 devices."
