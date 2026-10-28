"""ProxMenux Monitor. NOT measured: the Monitor runs on a Proxmox host that was not at
hand. The answers follow the project's README for ``/api/system`` and its source
for ``/api/health/status`` and ``/api/health/active-errors``; names are made up,
so these tests prove the reading, not the Monitor."""

from __future__ import annotations

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context, Unreachable, outbound_client

CONFIG = {"url": "http://pve:8008", "token": "example-token"}
API = "http://pve:8008/api"
STATUS = {"status": "WARNING", "summary": "Findings need a look", "critical_count": 0, "warning_count": 2, "ok_count": 6,
          "timestamp": "2026-10-27T12:00:00"}
ERRORS = {"errors": [
    {"error_key": "disk_sdb", "category": "disks", "severity": "WARNING", "reason": "Disk /dev/sdb: reallocated sectors rising",
     "first_seen": "2026-10-20T08:00:00", "last_seen": "2026-10-27T11:00:00", "occurrence_count": 12},
    {"error_key": "svc_cluster", "category": "pve_services", "severity": "CRITICAL", "reason": "Service pve-cluster is not running",
     "first_seen": "2026-10-27T10:00:00", "last_seen": "2026-10-27T16:30:00Z", "occurrence_count": 1},
]}
SYSTEM = {"hostname": "pve", "cpu_usage": 15.2, "memory_usage": 45.8, "temperature": 42.5, "uptime": 345600,
          "kernel": "6.2.16-3-pve", "pve_version": "8.0.3"}


@pytest.fixture
def ctx() -> Context:
    return Context(outbound_client(guard=False), integration_id=1, widget_id=1, cache={})


@respx.mock
async def test_the_health_card_gives_the_verdict_and_the_counts(ctx: Context) -> None:
    route = respx.get(f"{API}/health/status").mock(return_value=httpx.Response(200, json=STATUS))
    data = await get_adapter("proxmenux").fetch("health", CONFIG, {}, ctx)
    assert data.status == "warn" and data.primary == {"label": "Host", "value": "Warning"}
    assert data.secondary == [{"label": "Critical", "value": 0}, {"label": "Warnings", "value": 2}, {"label": "Fine", "value": 6}]
    assert data.metrics == {"critical": 0.0, "warnings": 2.0}
    assert route.calls.last.request.headers["Authorization"] == "Bearer example-token"


@respx.mock
async def test_critical_is_red_and_ok_is_green(ctx: Context) -> None:
    route = respx.get(f"{API}/health/status").mock(return_value=httpx.Response(200, json={**STATUS, "status": "CRITICAL", "critical_count": 1}))
    assert (await get_adapter("proxmenux").fetch("health", CONFIG, {}, ctx)).status == "bad"
    ctx.cache.clear()
    route.mock(return_value=httpx.Response(200, json={**STATUS, "status": "OK", "warning_count": 0}))
    data = await get_adapter("proxmenux").fetch("health", CONFIG, {}, ctx)
    assert (data.status, data.primary["value"]) == ("ok", "Healthy")


@respx.mock
async def test_the_findings_card_puts_critical_first_with_the_reason(ctx: Context) -> None:
    respx.get(f"{API}/health/active-errors").mock(return_value=httpx.Response(200, json=ERRORS))
    data = get_adapter("proxmenux")._findings(ERRORS["errors"], {}, now=1793124600.0)
    first, second = data.items
    assert (first["title"], first["status"], first["value"]) == ("Service pve-cluster is not running", "bad", "Critical")
    assert first["subtitle"] == "Pve services · seen 1 h ago"
    # A time without a zone is not turned into an age.
    assert second["subtitle"] == "Disks · 12 times" and second["status"] == "warn"
    assert data.status == "bad" and data.secondary == [{"label": "Open findings", "value": 2}]
    live = await get_adapter("proxmenux").fetch("findings", CONFIG, {"limit": 1}, ctx)
    assert len(live.items) == 1 and live.items[0]["status"] == "bad"


@respx.mock
async def test_no_findings_is_green(ctx: Context) -> None:
    respx.get(f"{API}/health/active-errors").mock(return_value=httpx.Response(200, json={"errors": []}))
    data = await get_adapter("proxmenux").fetch("findings", CONFIG, {}, ctx)
    assert data.status == "ok" and data.items == []


@respx.mock
async def test_the_host_card_gives_processor_memory_temperature_and_uptime(ctx: Context) -> None:
    respx.get(f"{API}/system").mock(return_value=httpx.Response(200, json=SYSTEM))
    data = await get_adapter("proxmenux").fetch("host", CONFIG, {}, ctx)
    assert data.primary == {"label": "CPU", "value": 15.2, "unit": "%"}
    assert data.secondary == [
        {"label": "Memory", "value": 45.8, "unit": "%"}, {"label": "Temperature", "value": 42.5, "unit": "°C"},
        {"label": "Uptime", "value": "4d"}, {"label": "Proxmox VE", "value": "8.0.3"}]
    assert data.metrics == {"cpu": 15.2, "memory": 45.8, "temperature": 42.5}
    assert data.status == "ok"


@respx.mock
async def test_a_host_without_a_temperature_sensor_records_none_instead_of_zero(ctx: Context) -> None:
    respx.get(f"{API}/system").mock(return_value=httpx.Response(200, json={**SYSTEM, "temperature": 0, "cpu_usage": 97.0}))
    data = await get_adapter("proxmenux").fetch("host", CONFIG, {}, ctx)
    assert "temperature" not in data.metrics and "Temperature" not in [row["label"] for row in data.secondary]
    assert data.status == "bad"


@respx.mock
async def test_without_a_token_no_header_is_sent_and_a_refusal_asks_for_one(ctx: Context) -> None:
    route = respx.get(f"{API}/health/status").mock(return_value=httpx.Response(401, json={"error": "Authentication required"}))
    with pytest.raises(AuthFailed) as failure:
        await get_adapter("proxmenux").fetch("health", {"url": "http://pve:8008"}, {}, ctx)
    assert "wants a token" in str(failure.value)
    assert "Authorization" not in route.calls.last.request.headers


@respx.mock
async def test_a_refused_token_is_an_authentication_failure(ctx: Context) -> None:
    respx.get(f"{API}/health/status").mock(return_value=httpx.Response(401, json={"error": "Invalid token"}))
    with pytest.raises(AuthFailed) as failure:
        await get_adapter("proxmenux").fetch("health", CONFIG, {}, ctx)
    assert "refused the token" in str(failure.value)


@respx.mock
async def test_the_connection_test_names_the_host_and_the_verdict(ctx: Context) -> None:
    respx.get(f"{API}/system-info").mock(return_value=httpx.Response(200, json={"hostname": "pve", "uptime": 5, "health": {"status": "warning"}}))
    respx.get(f"{API}/health/status").mock(return_value=httpx.Response(200, json=STATUS))
    assert await get_adapter("proxmenux").test(CONFIG, ctx) == "ProxMenux Monitor answers, host pve, warning."


@respx.mock
async def test_another_service_on_the_port_is_told_apart(ctx: Context) -> None:
    route = respx.get(f"{API}/health/status").mock(return_value=httpx.Response(200, text="<html></html>"))
    with pytest.raises(AdapterError) as failure:
        await get_adapter("proxmenux").fetch("health", CONFIG, {}, ctx)
    assert failure.value.code == "not_json"
    ctx.cache.clear()
    route.mock(return_value=httpx.Response(500, text="oops"))
    with pytest.raises(AdapterError) as failure:
        await get_adapter("proxmenux").fetch("health", CONFIG, {}, ctx)
    assert failure.value.code == "http_error"


@respx.mock
async def test_an_unreachable_monitor_is_unreachable(ctx: Context) -> None:
    respx.get(f"{API}/health/status").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(Unreachable):
        await get_adapter("proxmenux").fetch("health", CONFIG, {}, ctx)
