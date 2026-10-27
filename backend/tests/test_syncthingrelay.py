"""Syncthing Relay, against the answer of a live strelaysrv 2.1.7 (27.10.2026), idle."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, Context, Unreachable
from app.adapters.syncthingrelay import SyncthingRelayAdapter

R = "http://relay.example.com:22070"
IDLE = json.loads((Path(__file__).parent / "fixtures" / "relay_status.json").read_text(encoding="utf-8"))
#: The same answer with a relay in use; the six rates are kbit/s over 10 s, 1, 5, 15, 30 and 60 minutes.
BUSY = {**IDLE, "numActiveSessions": 7, "numConnections": 16, "bytesProxied": 5_368_709_120, "uptimeSeconds": 90_000,
        "kbps10s1m5m15m30m60m": [4200, 2600, 900, 400, 300, 250], "options": {**IDLE["options"], "pools": ["https://relays.syncthing.net/endpoint"]}}


def fresh(number: int = 1) -> Context:
    return Context(httpx.AsyncClient(), integration_id=number, widget_id=1, cache={})


@respx.mock
async def test_an_idle_relay() -> None:
    respx.get(f"{R}/status").mock(return_value=httpx.Response(200, json=IDLE))
    data = await get_adapter("syncthingrelay").fetch("relay", {"url": R}, {}, fresh())
    assert data.primary == {"label": "Sessions", "value": 0, "unit": ""} and data.status == "ok"
    assert {row["label"]: row["value"] for row in data.secondary} == {
        "Connections": 0, "Throughput": "0 kbit/s", "Proxied": "0 B", "Uptime": "12s", "Pool": "None"}
    assert data.metrics == {"sessions": 0.0, "throughput": 0.0}


def test_a_relay_in_use_shows_the_minute_not_the_ten_seconds() -> None:
    data = SyncthingRelayAdapter._card(BUSY)
    rows = {row["label"]: row["value"] for row in data.secondary}
    assert data.primary["value"] == 7 and rows["Connections"] == 16 and rows["Throughput"] == "2.6 Mbit/s" and rows["Proxied"] == "5.0 GB"
    assert rows["Uptime"] == "25h" and "Pool" not in rows and data.metrics == {"sessions": 7.0, "throughput": 2600.0}
    assert SyncthingRelayAdapter._card({"numActiveSessions": 1, "kbps10s1m5m15m30m60m": [10, 120.4]}).secondary[1]["value"] == "120 kbit/s"
    assert "throughput" not in SyncthingRelayAdapter._card({"numActiveSessions": 1}).metrics


@respx.mock
async def test_the_connection_test_names_the_version() -> None:
    respx.get(f"{R}/status").mock(return_value=httpx.Response(200, json=IDLE))
    assert await get_adapter("syncthingrelay").test({"url": R}, fresh()) == "Syncthing Relay 2.1.7 answers."
    assert await get_adapter("syncthingrelay").running_version({"url": R}, fresh(2)) == "2.1.7"


@respx.mock
async def test_wrong_port_not_json_and_unreachable() -> None:
    adapter = get_adapter("syncthingrelay")
    respx.get(f"{R}/status").mock(return_value=httpx.Response(404, text="404 page not found"))
    with pytest.raises(AdapterError) as missing:
        await adapter.fetch("relay", {"url": R}, {}, fresh(1))
    assert missing.value.code == "http_error" and "22067" in missing.value.hint
    respx.get(f"{R}/status").mock(return_value=httpx.Response(200, json={"hello": "world"}))
    with pytest.raises(AdapterError) as other:
        await adapter.fetch("relay", {"url": R}, {}, fresh(2))
    assert other.value.code == "not_a_relay"
    respx.get(f"{R}/status").mock(return_value=httpx.Response(200, text="relay protocol"))
    with pytest.raises(AdapterError) as html:
        await adapter.fetch("relay", {"url": R}, {}, fresh(3))
    assert html.value.code == "not_json"
    respx.get(f"{R}/status").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(Unreachable):
        await adapter.fetch("relay", {"url": R}, {}, fresh(4))


def test_the_card_has_demo_data_that_moves() -> None:
    adapter = get_adapter("syncthingrelay")
    assert adapter.beta is True and not any(field.secret for field in adapter.fields)
    assert len({adapter.demo("relay", {}, tick).primary["value"] for tick in range(0, 300, 10)}) > 1
