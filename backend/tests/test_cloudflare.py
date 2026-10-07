"""The Cloudflare cards against answers shaped after Cloudflare's API reference.

Nothing here was measured: there is no Cloudflare account to measure against.
The shapes follow the reference as of October 2026, including the change of
05.10.2026 that took the connections out of the tunnel list.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context

API = "https://api.cloudflare.com/client/v4"
# Built when the test runs, for the same reason: 32 hex characters read as a key.
ACCOUNT = "ab" * 16
# Built when the test runs: a token-shaped literal stops the scanners before a push.
TOKEN = "-".join(("made", "up", "for", "these", "tests"))
CONFIG = {"token": TOKEN, "account_id": ACCOUNT}
CF = get_adapter("cloudflare")


def _ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


def _at(**delta: float) -> str:
    return (datetime.now(UTC) + timedelta(**delta)).isoformat().replace("+00:00", "Z")


def _ok(result: Any) -> httpx.Response:
    return httpx.Response(200, json={"success": True, "errors": [], "messages": [], "result": result})


def _refused(status: int, code: int, message: str) -> httpx.Response:
    return httpx.Response(status, json={"success": False, "errors": [{"code": code, "message": message}], "messages": [], "result": None})


def _tunnels() -> list[dict[str, Any]]:
    """Made when a test runs: made on import, the ages were minutes off in a long run."""
    return [
        {"id": "t-home", "name": "home", "status": "healthy", "tun_type": "cfd_tunnel", "config_src": "cloudflare", "conns_active_at": _at(days=-6)},
        {"id": "t-test", "name": "test", "status": "inactive", "tun_type": "cfd_tunnel"},
        {"id": "t-office", "name": "office", "status": "down", "conns_active_at": _at(days=-2), "conns_inactive_at": _at(minutes=-15)},
        {"id": "t-lab", "name": "lab", "status": "degraded", "conns_active_at": _at(hours=-3)},
    ]


def _connections(*colos: str) -> httpx.Response:
    return _ok([{"id": "c1", "arch": "linux_amd64", "version": "2026.9.0", "run_at": _at(days=-6),
                 "conns": [{"client_id": "c1", "colo_name": colo, "opened_at": _at(days=-6), "origin_ip": "192.0.2.10"} for colo in colos]}])


@respx.mock
@pytest.mark.asyncio
async def test_the_tunnels_put_the_down_ones_first_and_count_the_connections_of_each() -> None:
    listed = respx.get(f"{API}/accounts/{ACCOUNT}/cfd_tunnel").mock(return_value=_ok(_tunnels()))
    respx.get(f"{API}/accounts/{ACCOUNT}/cfd_tunnel/t-home/connections").mock(return_value=_connections("fra06", "fra08", "fra06", "ams01"))
    lab = respx.get(f"{API}/accounts/{ACCOUNT}/cfd_tunnel/t-lab/connections").mock(return_value=_connections("dus01"))
    asked_of_down = respx.get(f"{API}/accounts/{ACCOUNT}/cfd_tunnel/t-office/connections").mock(return_value=_ok([]))
    data = await CF.fetch("tunnels", CONFIG, {}, _ctx())
    assert listed.calls.last.request.headers["Authorization"] == f"Bearer {TOKEN}"
    assert listed.calls.last.request.url.params["is_deleted"] == "false"
    assert [item["title"] for item in data.items] == ["office", "lab", "home", "test"]
    office, lab_row, home, test = data.items
    assert office == {"title": "office", "subtitle": "Down", "status": "bad", "value": "15 min"}
    assert lab_row["subtitle"] == "Degraded · 1 connection(s) · dus01" and lab_row["status"] == "warn"
    assert home["subtitle"] == "Healthy · 4 connection(s) · ams01, fra06, fra08" and home["value"] == "6 d"
    assert test == {"title": "test", "subtitle": "Never run", "status": "unknown", "value": ""}
    # A tunnel with no connections is not asked for them.
    assert not asked_of_down.called and lab.called
    assert data.status == "bad" and data.metrics == {"down": 1.0}
    assert data.secondary == [{"label": "Healthy", "value": 1}, {"label": "Down", "value": 1}]


@pytest.mark.asyncio
async def test_the_tunnels_need_the_account() -> None:
    with pytest.raises(AdapterError) as caught:
        await CF.fetch("tunnels", {"token": TOKEN}, {}, _ctx())
    assert caught.value.code == "missing_account"


@respx.mock
@pytest.mark.asyncio
async def test_a_token_without_the_tunnel_permission_names_the_one_it_lacks() -> None:
    respx.get(f"{API}/accounts/{ACCOUNT}/cfd_tunnel").mock(return_value=_refused(403, 10000, "Authentication error"))
    with pytest.raises(AdapterError) as caught:
        await CF.fetch("tunnels", CONFIG, {}, _ctx())
    assert caught.value.code == "missing_permission"
    assert "Cloudflare Tunnel > Read" in caught.value.hint


@respx.mock
@pytest.mark.asyncio
async def test_a_wrong_token_is_said_as_such() -> None:
    respx.get(f"{API}/zones").mock(return_value=_refused(401, 1000, "Invalid API Token"))
    with pytest.raises(AuthFailed):
        await CF.fetch("zones", CONFIG, {}, _ctx())


@respx.mock
@pytest.mark.asyncio
async def test_the_zones_put_the_ones_that_need_attention_first() -> None:
    respx.get(f"{API}/zones").mock(return_value=_ok([
        {"id": "z1", "name": "example.com", "status": "active", "paused": False, "type": "full", "activated_on": _at(days=-400)},
        {"id": "z2", "name": "example.net", "status": "active", "paused": True, "type": "full", "activated_on": _at(days=-90)},
        {"id": "z3", "name": "example.org", "status": "pending", "paused": False, "type": "full"},
        {"id": "z4", "name": "example.dev", "status": "active", "paused": False, "type": "partial", "activated_on": _at(days=-10)},
    ]))
    data = await CF.fetch("zones", CONFIG, {}, _ctx())
    assert [(item["title"], item["subtitle"], item["status"]) for item in data.items] == [
        ("example.net", "Paused", "warn"),
        ("example.org", "Waiting for the name servers", "warn"),
        ("example.com", "", "ok"),
        ("example.dev", "Partial setup", "ok"),
    ]
    assert data.status == "warn"
    assert data.secondary == [{"label": "Zones", "value": 4}, {"label": "Need attention", "value": 2}]


@respx.mock
@pytest.mark.asyncio
async def test_the_traffic_adds_up_the_cache_states_of_the_last_day() -> None:
    respx.get(f"{API}/zones").mock(return_value=_ok([{"id": "zone-1", "name": "example.com"}]))
    graphql = respx.post(f"{API}/graphql").mock(return_value=httpx.Response(200, json={"data": {"viewer": {"zones": [{"httpRequestsAdaptiveGroups": [
        {"count": 6000, "sum": {"edgeResponseBytes": 3_000_000_000, "visits": 900}, "dimensions": {"cacheStatus": "hit"}},
        {"count": 3000, "sum": {"edgeResponseBytes": 600_000_000, "visits": 700}, "dimensions": {"cacheStatus": "dynamic"}},
        {"count": 1000, "sum": {"edgeResponseBytes": 400_000_000, "visits": 400}, "dimensions": {"cacheStatus": "revalidated"}},
    ]}]}}, "errors": None}))
    data = await CF.fetch("traffic", CONFIG, {"zone": "Example.com"}, _ctx())
    sent = json.loads(graphql.calls.last.request.content)
    assert sent["variables"]["zone"] == "zone-1"
    since = datetime.fromisoformat(sent["variables"]["since"].replace("Z", "+00:00"))
    until = datetime.fromisoformat(sent["variables"]["until"].replace("Z", "+00:00"))
    assert until - since == timedelta(hours=24)
    assert data.primary == {"label": "Requests", "value": 10000, "metric": "requests"}
    assert data.secondary == [{"label": "Visits", "value": 2000}, {"label": "Data", "value": "3.7 GB"}, {"label": "Cached", "value": 70, "unit": "%"}]
    assert data.metrics == {"requests": 10000.0}


@respx.mock
@pytest.mark.asyncio
async def test_a_zone_the_token_does_not_see_is_named() -> None:
    respx.get(f"{API}/zones").mock(return_value=_ok([]))
    with pytest.raises(AdapterError) as caught:
        await CF.fetch("traffic", CONFIG, {"zone": "example.com"}, _ctx())
    assert caught.value.code == "unknown_zone"


@respx.mock
@pytest.mark.asyncio
async def test_graphql_faults_come_with_http_200_and_are_said() -> None:
    respx.get(f"{API}/zones").mock(return_value=_ok([{"id": "zone-1", "name": "example.com"}]))
    respx.post(f"{API}/graphql").mock(return_value=httpx.Response(200, json={"data": None, "errors": [
        {"message": "zones '[zone-1]' are not authorized", "path": ["viewer", "zones"]}]}))
    with pytest.raises(AdapterError) as caught:
        await CF.fetch("traffic", CONFIG, {"zone": "example.com"}, _ctx())
    assert caught.value.code == "missing_permission" and "Analytics" in caught.value.hint
    respx.post(f"{API}/graphql").mock(return_value=httpx.Response(200, json={"data": None, "errors": [{"message": "cannot request data older than 2678400s"}]}))
    with pytest.raises(AdapterError) as caught:
        await CF.fetch("traffic", CONFIG, {"zone": "example.com"}, _ctx())
    assert caught.value.code == "query_error" and "older than" in caught.value.message


@respx.mock
@pytest.mark.asyncio
async def test_the_rate_limit_is_said() -> None:
    respx.get(f"{API}/zones").mock(return_value=httpx.Response(429, json={"success": False, "errors": [{"code": 971, "message": "Please wait"}]}))
    with pytest.raises(AdapterError) as caught:
        await CF.fetch("zones", CONFIG, {}, _ctx())
    assert caught.value.code == "rate_limited"


@respx.mock
@pytest.mark.asyncio
async def test_the_connection_test_tries_the_account_when_the_token_is_not_a_users() -> None:
    respx.get(f"{API}/user/tokens/verify").mock(return_value=_refused(401, 1000, "Invalid API Token"))
    account = respx.get(f"{API}/accounts/{ACCOUNT}/tokens/verify").mock(return_value=_ok({"id": "x", "status": "active", "expires_on": "2027-01-01T00:00:00Z"}))
    assert await CF.test(CONFIG, _ctx()) == "Cloudflare accepts the token; it expires on 2027-01-01."
    assert account.called
    with pytest.raises(AuthFailed):
        await CF.test({"token": TOKEN}, _ctx())


@respx.mock
@pytest.mark.asyncio
async def test_a_disabled_token_is_refused_by_the_test() -> None:
    respx.get(f"{API}/user/tokens/verify").mock(return_value=_ok({"id": "x", "status": "disabled"}))
    with pytest.raises(AuthFailed) as caught:
        await CF.test(CONFIG, _ctx())
    assert "disabled" in caught.value.message


@respx.mock
@pytest.mark.asyncio
async def test_unreachable_is_said() -> None:
    respx.get(f"{API}/zones").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(AdapterError) as caught:
        await CF.fetch("zones", CONFIG, {}, _ctx())
    assert caught.value.code == "unreachable"
