"""wg-easy, against the answers of a live wg-easy 15.4.0 (11.09.2026)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context
from app.adapters.wgeasy import WgEasyAdapter

WE = "http://wg-easy.example.com"
CONFIG = {"url": WE, "username": "admin", "password": "made-up-password"}
NOW = datetime.fromisoformat("2026-09-11T13:14:12+00:00").timestamp()


def client(identifier: int, name: str, address: str, *, enabled: bool = True, handshake: str | None = None,
           rx: int | None = 0, tx: int | None = 0, expires: str | None = None) -> dict[str, Any]:
    return {"id": identifier, "userId": 1, "interfaceId": "wg0", "name": name, "ipv4Address": address, "ipv6Address": "fdcc::2",
            "publicKey": "made-up", "expiresAt": expires, "enabled": enabled, "createdAt": "2026-09-11T13:07:02.000Z",
            "latestHandshakeAt": handshake, "endpoint": "192.0.2.50:39996" if handshake else None, "transferRx": rx, "transferTx": tx}


#: As measured: a real client connected, one never did, one disabled with null transfer.
CLIENTS = [
    client(2, "laptop", "10.8.0.3"),
    client(3, "old-tablet", "10.8.0.4", enabled=False, rx=None, tx=None),
    client(1, "phone", "10.8.0.2", handshake="2026-09-11T13:13:59.000Z", rx=2416, tx=1264),
]


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


def test_connected_first_then_never_then_disabled() -> None:
    data = WgEasyAdapter._list(WgEasyAdapter._rows(CLIENTS, NOW), {"limit": 10})
    assert [(row["title"], row["subtitle"], row["status"], row["value"]) for row in data.items] == [
        ("phone", "Connected · 10.8.0.2", "ok", "3.6 KB"),
        ("laptop", "Never connected · 10.8.0.3", "unknown", ""),
        ("old-tablet", "Disabled · 10.8.0.4", "unknown", ""),
    ]
    assert data.secondary == [{"label": "Connected", "value": 1}]


def test_an_old_handshake_is_last_seen_and_an_expired_client_says_so() -> None:
    quiet = client(4, "car", "10.8.0.5", handshake="2026-09-11T13:04:12.000Z", rx=10, tx=10)
    gone = client(5, "guest", "10.8.0.6", handshake="2026-09-11T13:14:00.000Z", expires="2026-09-01T00:00:00.000Z")
    rows = WgEasyAdapter._rows([quiet, gone], NOW)
    assert [(one["row"]["subtitle"], one["row"]["value"]) for one in rows] == [("Last seen · 10.8.0.5", "10 min"), ("Expired · 10.8.0.6", "")]
    # Three minutes is still connected, a second more is not.
    edge = client(6, "edge", "10.8.0.7", handshake="2026-09-11T13:11:12.000Z")
    assert WgEasyAdapter._rows([edge], NOW)[0]["row"]["subtitle"].startswith("Connected")
    assert WgEasyAdapter._rows([edge], NOW + 1)[0]["row"]["subtitle"].startswith("Last seen")


def test_the_summary() -> None:
    data = WgEasyAdapter._summary(WgEasyAdapter._rows(CLIENTS, NOW))
    assert data.primary == {"label": "Connected", "value": 1, "unit": "/ 2"}
    assert data.secondary == [{"label": "Traffic", "value": "3.6 KB"}, {"label": "Disabled", "value": 1}]


@respx.mock
async def test_basic_authentication_on_the_client_list(ctx: Context) -> None:
    route = respx.get(f"{WE}/api/client").mock(return_value=httpx.Response(200, json=CLIENTS))
    data = await get_adapter("wgeasy").fetch("summary", CONFIG, {}, ctx)
    assert route.calls.last.request.headers["Authorization"].startswith("Basic ")
    assert data.primary["unit"] == "/ 2"


@respx.mock
async def test_a_wrong_password_and_a_wg_easy_14(ctx: Context) -> None:
    respx.get(f"{WE}/api/client").mock(return_value=httpx.Response(401, json={"statusCode": 401, "message": "Session failed"}))
    with pytest.raises(AuthFailed):
        await get_adapter("wgeasy").fetch("clients", CONFIG, {}, ctx)
    respx.get(f"{WE}/api/client").mock(return_value=httpx.Response(404, json={"statusCode": 404, "message": "Page not found: /api/client"}))
    with pytest.raises(AdapterError) as old:
        await get_adapter("wgeasy").fetch("clients", CONFIG, {}, Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={}))
    assert "15" in old.value.hint


@respx.mock
async def test_the_connection_test(ctx: Context) -> None:
    respx.get(f"{WE}/api/client").mock(return_value=httpx.Response(200, json=CLIENTS))
    respx.get(f"{WE}/api/information").mock(return_value=httpx.Response(200, json={"currentRelease": "v15.4.0", "updateAvailable": False, "insecure": True}))
    assert await get_adapter("wgeasy").test(CONFIG, ctx) == "wg-easy 15.4.0 answers with 3 clients."
