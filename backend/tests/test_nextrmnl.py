"""The nextrmnl cards against nextrmnl's /api/v1 answers."""

from __future__ import annotations

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, Context

URL = "https://ssh.example.com"
CONFIG = {"url": URL, "api_key": "nxt_test-key-for-the-cards"}


def _ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


@respx.mock
async def test_the_status_card_counts_and_carries_the_key_in_the_header() -> None:
    route = respx.get(f"{URL}/api/v1/status").mock(return_value=httpx.Response(200, json={
        "version": "0.3.0", "update_available": True, "latest_version": "0.3.1",
        "sessions_running": 2, "connections": 14, "sessions_today": 9, "failed_today": 1}))
    card = await get_adapter("nextrmnl").fetch("status", CONFIG, {}, _ctx())
    assert route.calls.last.request.headers["Authorization"] == "Bearer nxt_test-key-for-the-cards"
    assert "nxt_" not in str(route.calls.last.request.url), "the key stays out of the address"
    assert card.primary == {"label": "Live sessions", "value": 2} and card.status == "warn"
    assert {chip["label"]: chip["value"] for chip in card.secondary} == {"Today": 9, "Failed today": 1, "Connections": 14, "New version": "0.3.1"}
    assert card.metrics == {"sessions_running": 2.0}


@respx.mock
async def test_live_sessions_and_a_connecting_one() -> None:
    respx.get(f"{URL}/api/v1/sessions").mock(return_value=httpx.Response(200, json=[
        {"account": "admin", "name": "nas", "target": "root@192.0.2.10:22", "started_at": "2026-09-26T08:00:00+00:00", "state": "open"},
        {"account": "alex", "name": "pve", "target": "root@192.0.2.20:22", "started_at": "2026-09-26T09:00:00+00:00", "state": "connecting"},
    ]))
    card = await get_adapter("nextrmnl").fetch("sessions", CONFIG, {}, _ctx())
    assert [(row["title"], row["subtitle"], row["status"]) for row in card.items] == [
        ("nas", "admin · root@192.0.2.10:22", "ok"), ("pve", "alex · root@192.0.2.20:22", "unknown")]
    assert card.primary["value"] == 2


@respx.mock
async def test_a_changed_host_key_makes_the_history_red() -> None:
    route = respx.get(f"{URL}/api/v1/history").mock(return_value=httpx.Response(200, json=[
        {"account": "admin", "name": "router", "target": "admin@192.0.2.1:22", "started_at": "2026-09-26T08:00:00+00:00",
         "end": "hostkey", "detail": "The host key changed."},
        {"account": "alex", "name": "nas", "target": "root@192.0.2.10:22", "started_at": "2026-09-26T07:00:00+00:00", "end": "normal", "detail": ""},
        {"account": "alex", "name": "backup", "target": "backup@198.51.100.7:22", "started_at": "2026-09-26T06:00:00+00:00",
         "end": "failed", "detail": "Authentication failed."},
    ]))
    card = await get_adapter("nextrmnl").fetch("history", CONFIG, {"limit": 3}, _ctx())
    assert route.calls.last.request.url.params["limit"] == "3"
    assert [(row["title"], row["status"]) for row in card.items] == [("router", "bad"), ("nas", "ok"), ("backup", "bad")]
    assert card.items[0]["subtitle"] == "Host key changed · admin · The host key changed."
    assert card.items[1]["subtitle"] == "alex", "a normal end needs no word"
    assert card.status == "bad" and card.meta["status_reason"]
    calm = respx.get(f"{URL}/api/v1/history").mock(return_value=httpx.Response(200, json=[
        {"account": "alex", "name": "backup", "started_at": "2026-09-26T06:00:00+00:00", "end": "failed", "detail": "x"}]))
    assert calm is not None
    assert (await get_adapter("nextrmnl").fetch("history", CONFIG, {"limit": 1}, _ctx())).status == "ok", "a failed login is no alarm"


@respx.mock
async def test_connections_and_only_what_does_not_answer() -> None:
    respx.get(f"{URL}/api/v1/connections").mock(return_value=httpx.Response(200, json=[
        {"name": "nas", "group": "Home", "target": "192.0.2.10:22", "reach": "up", "latency_ms": 3},
        {"name": "backup", "group": "Offsite", "target": "198.51.100.7:22", "reach": "down", "latency_ms": None},
        {"name": "jump", "group": "", "target": "192.0.2.30:22", "reach": "unknown", "latency_ms": None},
    ]))
    adapter = get_adapter("nextrmnl")
    card = await adapter.fetch("connections", CONFIG, {}, _ctx())
    assert [(row["title"], row["status"], row["value"]) for row in card.items] == [
        ("nas", "ok", "3 ms"), ("backup", "bad", ""), ("jump", "unknown", "")]
    assert card.status == "bad" and card.primary == {"label": "Down", "value": 1}
    down = await adapter.fetch("connections", CONFIG, {"only_down": True}, _ctx())
    assert [row["title"] for row in down.items] == ["backup"]


@pytest.mark.parametrize(("status", "code", "ours"), [
    (403, "api_keys_off", "nextrmnl_keys_off"),
    (401, "api_key_invalid", "nextrmnl_key_invalid"),
    (401, "api_key_missing", "nextrmnl_key_missing"),
    (403, "something_else", "nextrmnl_refused"),
])
@respx.mock
async def test_each_refusal_says_what_to_do(status: int, code: str, ours: str) -> None:
    respx.get(f"{URL}/api/v1/status").mock(return_value=httpx.Response(status, json={"detail": {"code": code, "message": "x"}}))
    with pytest.raises(AdapterError) as refused:
        await get_adapter("nextrmnl").fetch("status", CONFIG, {}, _ctx())
    assert refused.value.code == ours


@respx.mock
async def test_an_old_nextrmnl_and_the_connection_test() -> None:
    adapter = get_adapter("nextrmnl")
    respx.get(f"{URL}/api/v1/status").mock(return_value=httpx.Response(404, json={"detail": "Not Found"}))
    with pytest.raises(AdapterError) as old:
        await adapter.test(CONFIG, _ctx())
    assert old.value.code == "nextrmnl_too_old"
    respx.get(f"{URL}/api/v1/status").mock(return_value=httpx.Response(200, json={"version": "0.3.0", "sessions_running": 1}))
    assert await adapter.test(CONFIG, _ctx()) == "nextrmnl 0.3.0 answers; 1 live sessions."


def test_every_demo_draws() -> None:
    adapter = get_adapter("nextrmnl")
    for kind in ("status", "sessions", "history", "connections"):
        card = adapter.demo(kind, {}, 0)
        assert card.items or card.primary, kind
    assert adapter.demo("history", {}, 0).status == "bad"
