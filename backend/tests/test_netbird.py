"""NetBird, against the answers its management API gives.

The peer below is the example of NetBird's OpenAPI description, trimmed to the
fields that matter and given a second and a third peer. The 401 answers were
recorded from a live netbird-server 0.79.0 on 24.09.2026.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context

URL = "https://netbird.example.com"
CONFIG = {"url": URL, "token": "nbp_example"}


def _seen(hours: float) -> str:
    return (datetime.now(UTC) - timedelta(hours=hours)).isoformat().replace("+00:00", "Z")


def _peers() -> list[dict]:
    return [
        {
            "id": "chacbco6lnnbn6cg5s90", "name": "stage-host-1", "created_at": "2023-05-05T09:00:35.477782Z",
            "ip": "10.64.0.1", "connection_ip": "35.64.0.1", "connected": True, "last_seen": _seen(0),
            "os": "Darwin 13.2.1", "version": "0.14.0", "groups": [{"id": "g1", "name": "devs", "peers_count": 2}],
            "ssh_enabled": True, "hostname": "stage-host-1", "dns_label": "stage-host-1.netbird.cloud",
            "login_expiration_enabled": False, "login_expired": False, "approval_required": False,
            "accessible_peers_count": 5,
        },
        {"id": "p2", "name": "backup-box", "ip": "10.64.0.7", "connected": False, "last_seen": _seen(5), "os": "Linux 6.12", "login_expired": False},
        {"id": "p3", "name": "old-laptop", "ip": "10.64.0.9", "connected": False, "last_seen": _seen(400), "os": "Windows 11", "login_expired": True},
    ]


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


@respx.mock
async def test_peers_are_read_with_the_token_header(ctx: Context) -> None:
    route = respx.get(f"{URL}/api/peers").mock(return_value=httpx.Response(200, json=_peers()))
    data = await get_adapter("netbird").fetch("peers", CONFIG, {}, ctx)
    assert route.calls.last.request.headers["Authorization"] == "Token nbp_example"
    # The expired login first, then who is connected, then who is away.
    assert [(item["title"], item["value"], item["status"]) for item in data.items] == [
        ("old-laptop", "Login expired", "warn"),
        ("stage-host-1", "now", "ok"),
        ("backup-box", "5 h", "unknown"),
    ]
    assert data.items[1]["subtitle"] == "10.64.0.1 · Darwin 13.2.1"
    assert data.metrics == {"peers": 3.0, "connected": 1.0}


@respx.mock
async def test_only_away_leaves_the_connected_out(ctx: Context) -> None:
    respx.get(f"{URL}/api/peers").mock(return_value=httpx.Response(200, json=_peers()))
    data = await get_adapter("netbird").fetch("peers", CONFIG, {"only_offline": True}, ctx)
    assert [item["title"] for item in data.items] == ["old-laptop", "backup-box"]


@respx.mock
async def test_status_counts_and_warns_about_an_expired_login(ctx: Context) -> None:
    respx.get(f"{URL}/api/peers").mock(return_value=httpx.Response(200, json=_peers()))
    data = await get_adapter("netbird").fetch("status", CONFIG, {}, ctx)
    assert data.status == "warn"
    assert data.primary == {"label": "Peers", "value": 3}
    assert data.secondary == [
        {"label": "Connected", "value": 1},
        {"label": "Away", "value": 2},
        {"label": "Login expired", "value": 1},
    ]


@respx.mock
async def test_the_cloud_is_the_address_when_none_is_given(ctx: Context) -> None:
    route = respx.get("https://api.netbird.io/api/peers").mock(return_value=httpx.Response(200, json=[]))
    message = await get_adapter("netbird").test({"url": "", "token": "nbp_example"}, ctx)
    assert route.called
    assert message == "NetBird answers with 0 peers, 0 connected."


@respx.mock
async def test_a_wrong_token_is_said_as_such(ctx: Context) -> None:
    respx.get(f"{URL}/api/peers").mock(return_value=httpx.Response(401, json={"message": "token invalid", "code": 401}))
    with pytest.raises(AuthFailed):
        await get_adapter("netbird").test(CONFIG, ctx)


@respx.mock
async def test_a_page_instead_of_the_api_is_not_taken_for_peers(ctx: Context) -> None:
    """The dashboard answers every address with its own page; pointed at the
    wrong path, that is HTML, not an empty network."""
    respx.get(f"{URL}/api/peers").mock(return_value=httpx.Response(200, text="<!doctype html><html></html>"))
    with pytest.raises(AdapterError) as failure:
        await get_adapter("netbird").fetch("peers", CONFIG, {}, ctx)
    assert failure.value.code == "not_json"


def test_the_demo_draws_both_cards() -> None:
    netbird = get_adapter("netbird")
    assert netbird.demo("status", {}, 0).primary == {"label": "Peers", "value": 5}
    assert any(item["value"] == "Login expired" for item in netbird.demo("peers", {}, 0).items)
