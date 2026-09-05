"""Network and access: tunnels, resolvers, the router and the sign-in server.

Each parser against a recorded answer. Two shapes bite here and nowhere else:
RouterOS answers with the strings "true" and "false", and Gluetun renamed its
status address in 3.35 while the old one kept answering.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


def _ago(**delta: float) -> str:
    return (datetime.now(UTC) - timedelta(**delta)).isoformat().replace("+00:00", "Z")


# -- tailscale -----------------------------------------------------------------


@respx.mock
async def test_tailscale_reads_reachability_out_of_the_last_seen_stamp(ctx: Context) -> None:
    """The API has no online flag; a device counts as away once its stamp is
    older than five minutes."""
    config = {"api_key": "tskey", "tailnet": "-"}
    respx.get("https://api.tailscale.com/api/v2/tailnet/-/devices").mock(return_value=httpx.Response(200, json={"devices": [
        {"name": "nas.tail1234.ts.net", "os": "linux", "addresses": ["100.64.0.3"], "lastSeen": _ago(seconds=20)},
        {"name": "tablet.tail1234.ts.net", "os": "android", "addresses": ["100.64.0.11"], "lastSeen": _ago(hours=6), "updateAvailable": True},
    ]}))
    data = await get_adapter("tailscale").fetch("status", config, {}, ctx)
    assert data.primary == {"label": "Devices", "value": 2}
    assert {entry["label"]: entry["value"] for entry in data.secondary} == {"Reachable": 1, "Away": 1, "Updates": 1}
    assert data.status == "warn"
    assert respx.calls.last.request.headers["Authorization"] == "Bearer tskey"


@respx.mock
async def test_tailscale_shortens_the_name_and_sorts_the_away_ones_last(ctx: Context) -> None:
    config = {"api_key": "tskey"}
    respx.get("https://api.tailscale.com/api/v2/tailnet/-/devices").mock(return_value=httpx.Response(200, json={"devices": [
        {"name": "tablet.tail1234.ts.net", "os": "android", "addresses": ["100.64.0.11"], "lastSeen": _ago(hours=6)},
        {"name": "nas.tail1234.ts.net", "os": "linux", "addresses": ["100.64.0.3"], "lastSeen": _ago(seconds=20)},
    ]}))
    data = await get_adapter("tailscale").fetch("devices", config, {}, ctx)
    assert [item["title"] for item in data.items] == ["nas", "tablet"]
    assert data.items[0]["value"] == "now" and data.items[1]["value"] == "6 h"
    assert data.items[0]["subtitle"] == "linux · 100.64.0.3"


@respx.mock
async def test_tailscale_can_show_only_the_away_ones(ctx: Context) -> None:
    config = {"api_key": "tskey"}
    respx.get("https://api.tailscale.com/api/v2/tailnet/-/devices").mock(return_value=httpx.Response(200, json={"devices": [
        {"name": "nas.tail1234.ts.net", "lastSeen": _ago(seconds=20)},
        {"name": "tablet.tail1234.ts.net", "lastSeen": _ago(days=3)},
    ]}))
    data = await get_adapter("tailscale").fetch("devices", config, {"only_offline": True}, ctx)
    assert [item["title"] for item in data.items] == ["tablet"]
    assert data.items[0]["value"] == "3 d"
    # The counts stay whole even when the list is filtered.
    assert {entry["label"]: entry["value"] for entry in data.secondary} == {"Reachable": 1, "Devices": 2}


# -- headscale -----------------------------------------------------------------


@respx.mock
async def test_headscale_names_the_owner_of_every_node(ctx: Context) -> None:
    config = {"url": "http://headscale:8080", "api_key": "key"}
    respx.get("http://headscale:8080/api/v1/node").mock(return_value=httpx.Response(200, json={"nodes": [
        {"givenName": "laptop", "user": {"name": "sam"}, "ipAddresses": ["100.64.0.9"], "online": False, "lastSeen": _ago(hours=4)},
        {"givenName": "nas", "user": {"name": "alex"}, "ipAddresses": ["100.64.0.3"], "online": True},
    ]}))
    data = await get_adapter("headscale").fetch("nodes", config, {}, ctx)
    assert [item["title"] for item in data.items] == ["nas", "laptop"]
    assert data.items[0]["subtitle"] == "alex · 100.64.0.3"
    assert data.items[1]["value"] == "4 h"
    assert respx.calls.last.request.headers["Authorization"] == "Bearer key"


@respx.mock
async def test_headscale_counts_the_users_beside_the_nodes(ctx: Context) -> None:
    config = {"url": "http://headscale:8080", "api_key": "key"}
    respx.get("http://headscale:8080/api/v1/node").mock(return_value=httpx.Response(200, json={"nodes": [
        {"givenName": "nas", "online": True}, {"givenName": "laptop", "online": False},
    ]}))
    respx.get("http://headscale:8080/api/v1/user").mock(return_value=httpx.Response(200, json={"users": [{"name": "alex"}, {"name": "sam"}]}))
    data = await get_adapter("headscale").fetch("status", config, {}, ctx)
    assert data.primary == {"label": "Nodes", "value": 2}
    assert {entry["label"]: entry["value"] for entry in data.secondary} == {"Online": 1, "Away": 1, "Users": 2}


# -- gluetun -------------------------------------------------------------------


@respx.mock
async def test_gluetun_falls_back_to_the_address_of_the_older_control_server(ctx: Context) -> None:
    """3.35 renamed /v1/openvpn/status to /v1/vpn/status. Older containers
    answer 404 on the new one, and the card must not read that as down."""
    config = {"url": "http://gluetun:8000"}
    respx.get("http://gluetun:8000/v1/vpn/status").mock(return_value=httpx.Response(404, json={}))
    respx.get("http://gluetun:8000/v1/openvpn/status").mock(return_value=httpx.Response(200, json={"status": "running"}))
    respx.get("http://gluetun:8000/v1/publicip/ip").mock(return_value=httpx.Response(200, json={
        "public_ip": "198.51.100.42", "country": "Netherlands", "city": "Amsterdam", "region": "North Holland",
    }))
    respx.get("http://gluetun:8000/v1/portforwarded").mock(return_value=httpx.Response(200, json={"port": 51820}))
    data = await get_adapter("gluetun").fetch("vpn", config, {}, ctx)
    assert data.status == "ok"
    assert data.primary == {"label": "Country", "value": "Netherlands"}
    assert {entry["label"]: entry["value"] for entry in data.secondary}["Forwarded port"] == 51820
    assert data.metrics == {"up": 1.0}


@respx.mock
async def test_gluetun_without_port_forwarding_is_not_a_fault(ctx: Context) -> None:
    config = {"url": "http://gluetun:8000"}
    respx.get("http://gluetun:8000/v1/vpn/status").mock(return_value=httpx.Response(200, json={"status": "stopped"}))
    respx.get("http://gluetun:8000/v1/publicip/ip").mock(return_value=httpx.Response(200, json={"public_ip": "198.51.100.42"}))
    respx.get("http://gluetun:8000/v1/portforwarded").mock(return_value=httpx.Response(404, json={}))
    data = await get_adapter("gluetun").fetch("vpn", config, {}, ctx)
    assert {entry["label"]: entry["value"] for entry in data.secondary}["Forwarded port"] == "none"
    # The stopped tunnel is the fault, not the missing port.
    assert data.status == "bad" and data.meta["status_reason"]


@respx.mock
async def test_gluetun_lets_a_rejected_key_through_instead_of_calling_it_down(ctx: Context) -> None:
    config = {"url": "http://gluetun:8000", "api_key": "wrong"}
    respx.get("http://gluetun:8000/v1/vpn/status").mock(return_value=httpx.Response(401, json={}))
    with pytest.raises(AuthFailed):
        await get_adapter("gluetun").fetch("vpn", config, {}, ctx)


# -- technitium ----------------------------------------------------------------


@respx.mock
async def test_technitium_unwraps_the_envelope_and_works_out_the_share(ctx: Context) -> None:
    config = {"url": "http://technitium:5380", "token": "tok"}
    respx.get("http://technitium:5380/api/dashboard/stats/get").mock(return_value=httpx.Response(200, json={
        "status": "ok",
        "response": {"stats": {"totalQueries": 40000, "totalBlocked": 6000, "totalClients": 26}},
    }))
    data = await get_adapter("technitium").fetch("summary", config, {}, ctx)
    assert data.primary == {"label": "Blocked", "value": 15.0, "unit": "%"}
    assert {entry["label"]: entry["value"] for entry in data.secondary} == {"Queries": 40000, "Blocked": 6000, "Clients": 26}
    assert dict(respx.calls.last.request.url.params)["token"] == "tok"


@respx.mock
async def test_technitium_says_which_domains_it_blocked_most(ctx: Context) -> None:
    config = {"url": "http://technitium:5380", "token": "tok"}
    respx.get("http://technitium:5380/api/dashboard/stats/getTop").mock(return_value=httpx.Response(200, json={
        "status": "ok",
        "response": {"topBlockedDomains": [{"name": "ads.example.net", "hits": 812}, {"name": "trk.example.org", "hits": 431}]},
    }))
    data = await get_adapter("technitium").fetch("top", config, {"limit": 5}, ctx)
    assert [(item["title"], item["value"]) for item in data.items] == [("ads.example.net", 812), ("trk.example.org", 431)]
    assert dict(respx.calls.last.request.url.params)["statsType"] == "TopBlockedDomains"


@respx.mock
async def test_technitium_says_so_when_the_token_expired(ctx: Context) -> None:
    """It answers 200 with an error in the envelope, so the HTTP code says
    nothing."""
    config = {"url": "http://technitium:5380", "token": "old"}
    respx.get("http://technitium:5380/api/dashboard/stats/get").mock(return_value=httpx.Response(200, json={"status": "invalid-token"}))
    with pytest.raises(AuthFailed):
        await get_adapter("technitium").fetch("summary", config, {}, ctx)


@respx.mock
async def test_technitium_passes_on_what_it_says_went_wrong(ctx: Context) -> None:
    config = {"url": "http://technitium:5380", "token": "tok"}
    respx.get("http://technitium:5380/api/dashboard/stats/get").mock(return_value=httpx.Response(200, json={
        "status": "error", "errorMessage": "Invalid type: LastYear",
    }))
    with pytest.raises(AdapterError, match="Invalid type"):
        await get_adapter("technitium").fetch("summary", config, {}, ctx)


# -- nextdns -------------------------------------------------------------------


@respx.mock
async def test_nextdns_adds_the_rows_of_the_status_analytics_up(ctx: Context) -> None:
    """The answer is one row per status, not a total; the share has to be
    worked out from them."""
    config = {"api_key": "key", "profile": "abc123"}
    respx.get("https://api.nextdns.io/profiles/abc123/analytics/status").mock(return_value=httpx.Response(200, json={"data": [
        {"status": "default", "queries": 9000}, {"status": "blocked", "queries": 1500}, {"status": "allowed", "queries": 500},
    ]}))
    data = await get_adapter("nextdns").fetch("summary", config, {}, ctx)
    assert data.primary == {"label": "Blocked", "value": 13.6, "unit": "%"}
    assert {entry["label"]: entry["value"] for entry in data.secondary} == {"Queries": 11000, "Blocked": 1500, "Allowed": 500}
    assert respx.calls.last.request.headers["X-Api-Key"] == "key"
    assert dict(respx.calls.last.request.url.params)["from"] == "-24h"


@respx.mock
async def test_nextdns_asks_only_for_the_blocked_domains(ctx: Context) -> None:
    config = {"api_key": "key", "profile": "abc123"}
    respx.get("https://api.nextdns.io/profiles/abc123/analytics/domains").mock(return_value=httpx.Response(200, json={"data": [
        {"domain": "ads.example.net", "queries": 320},
    ]}))
    data = await get_adapter("nextdns").fetch("top", config, {"window": "-7d", "limit": 3}, ctx)
    assert [(item["title"], item["value"]) for item in data.items] == [("ads.example.net", 320)]
    params = dict(respx.calls.last.request.url.params)
    assert params["status"] == "blocked" and params["from"] == "-7d"


# -- mikrotik ------------------------------------------------------------------


@respx.mock
async def test_mikrotik_reads_the_string_booleans_of_routeros(ctx: Context) -> None:
    """RouterOS answers with "true" and "false" as text. Taken as Python
    truth, every disabled port would count as running."""
    config = {"url": "https://router.example.com", "username": "read", "password": "pw"}
    respx.get("https://router.example.com/rest/interface").mock(return_value=httpx.Response(200, json=[
        {"name": "ether1", "type": "ether", "running": "true", "disabled": "false", "rx-byte": "840000000000", "tx-byte": "210000000000"},
        {"name": "ether5", "type": "ether", "running": "false", "disabled": "true", "rx-byte": "0", "tx-byte": "0"},
        {"name": "ether2", "type": "ether", "running": "false", "disabled": "false", "rx-byte": "10", "tx-byte": "20"},
    ]))
    data = await get_adapter("mikrotik").fetch("interfaces", config, {}, ctx)
    states = {item["title"]: item["status"] for item in data.items}
    assert states == {"ether1": "ok", "ether5": "unknown", "ether2": "bad"}
    # A switched-off port is not a fault; a port that should run and does not, is.
    assert {entry["label"]: entry["value"] for entry in data.secondary}["Down"] == 1
    assert data.status == "bad"
    assert data.items[0]["title"] == "ether2"


@respx.mock
async def test_mikrotik_turns_free_memory_into_used_memory(ctx: Context) -> None:
    config = {"url": "https://router.example.com", "username": "read", "password": "pw"}
    respx.get("https://router.example.com/rest/system/resource").mock(return_value=httpx.Response(200, json={
        "cpu-load": "7", "free-memory": "192000000", "total-memory": "256000000", "uptime": "6w2d4h", "version": "7.16.2",
    }))
    data = await get_adapter("mikrotik").fetch("system", config, {}, ctx)
    assert data.primary == {"label": "CPU", "value": 7.0, "unit": "%"}
    values = {entry["label"]: entry["value"] for entry in data.secondary}
    assert values["Memory"] == "25.0 %" and values["Uptime"] == "6w2d4h"
    assert respx.calls.last.request.headers["Authorization"].startswith("Basic ")


# -- authentik -----------------------------------------------------------------


@respx.mock
async def test_authentik_counts_only_the_failures_of_the_last_day(ctx: Context) -> None:
    """The event API has no window; it hands out pages. Counting the whole
    page would report last month's attempts as today's."""
    config = {"url": "https://auth.example.com", "token": "tok"}
    respx.get("https://auth.example.com/api/v3/events/events/").mock(side_effect=lambda request: httpx.Response(200, json={"results": [
        {"created": _ago(hours=2), "context": {"username": "kim"}, "client_ip": "203.0.113.24"},
        {"created": _ago(days=9), "context": {"username": "kim"}, "client_ip": "203.0.113.24"},
    ]}))
    respx.get("https://auth.example.com/api/v3/core/users/").mock(return_value=httpx.Response(200, json={"pagination": {"count": 14}}))
    respx.get("https://auth.example.com/api/v3/admin/version/").mock(return_value=httpx.Response(200, json={"version_current": "2026.6.2", "outdated": False}))
    data = await get_adapter("authentik").fetch("status", config, {}, ctx)
    assert data.primary == {"label": "Sign-ins", "value": 1}
    values = {entry["label"]: entry["value"] for entry in data.secondary}
    assert values["Failed"] == 1 and values["Users"] == 14 and values["Version"] == "2026.6.2"
    assert data.status == "warn"


@respx.mock
async def test_authentik_marks_a_version_that_is_behind(ctx: Context) -> None:
    config = {"url": "https://auth.example.com", "token": "tok"}
    respx.get("https://auth.example.com/api/v3/events/events/").mock(return_value=httpx.Response(200, json={"results": []}))
    respx.get("https://auth.example.com/api/v3/core/users/").mock(return_value=httpx.Response(200, json={"pagination": {"count": 3}}))
    respx.get("https://auth.example.com/api/v3/admin/version/").mock(return_value=httpx.Response(200, json={"version_current": "2026.2.1", "outdated": True}))
    data = await get_adapter("authentik").fetch("status", config, {}, ctx)
    assert {entry["label"]: entry["value"] for entry in data.secondary}["Version"] == "2026.2.1 !"
    assert data.status == "warn"


@respx.mock
async def test_authentik_lists_who_did_not_get_in(ctx: Context) -> None:
    config = {"url": "https://auth.example.com", "token": "tok"}
    respx.get("https://auth.example.com/api/v3/events/events/").mock(return_value=httpx.Response(200, json={"results": [
        {"created": _ago(minutes=30), "user": {"username": "sam"}, "client_ip": "198.51.100.9"},
    ]}))
    data = await get_adapter("authentik").fetch("failed", config, {"limit": 5}, ctx)
    assert data.items[0]["title"] == "sam"
    assert "198.51.100.9" in data.items[0]["subtitle"]
    assert data.status == "warn"
    assert dict(respx.calls.last.request.url.params)["action"] == "login_failed"


# -- every one of them ---------------------------------------------------------


@pytest.mark.parametrize("kind", ["tailscale", "headscale", "gluetun", "technitium", "nextdns", "mikrotik", "authentik"])
def test_every_network_adapter_has_demo_data_for_every_widget(kind: str) -> None:
    adapter = get_adapter(kind)
    assert adapter.widgets, kind
    for widget in adapter.widgets:
        options = {field.name: field.default for field in widget.options}
        for tick in (0, 7, 41):
            data = adapter.demo(widget.kind, options, tick)
            filled = data.items or data.primary or data.secondary
            assert filled, f"{kind}/{widget.kind} at tick {tick} is empty"
