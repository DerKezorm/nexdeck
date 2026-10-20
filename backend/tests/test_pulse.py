"""Pulse (issue #47). The answers are shaped after Pulse's own sources
(``internal/api/state_summary.go``, ``internal/unifiedresources/health.go``,
``internal/alerts/model.go``, v6.5.0, October 2026); the names and numbers
are made up."""

from __future__ import annotations

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context, outbound_client

CONFIG = {"url": "http://pulse:7655", "token": "pulse-example-token"}
BASE = "http://pulse:7655/api"
NOW = 1_792_490_400.0  # 2026-10-20 10:00 UTC

#: Pulse 6.0 to 6.4: the counts alone.
OLD_SUMMARY = {
    "activeAlerts": 1, "nodes": 2, "vms": 8, "containers": 12,
    "dockerHosts": [{"name": "Docker Host", "containers": 5, "uptimeSeconds": 86400, "cpuUsagePercent": 12.5}],
    "lastUpdate": "2026-10-20T09:59:58.123456789Z",
}
#: Pulse 6.5: the same, with the fleet's health.
SUMMARY = {
    **OLD_SUMMARY,
    "activeAlerts": 3,
    "verdicts": {"ok": 17, "attention": 2, "critical": 1, "stale": 1, "off": 2, "unknown": 0},
    "attention": [
        {"id": "storage:pve2:local-zfs", "name": "local-zfs", "type": "storage", "platformType": "proxmox",
         "verdict": "attention", "topReason": {"code": "warning_alert", "detail": "disk"}},
        {"id": "agent:pve3", "name": "pve3", "type": "agent", "platformType": "proxmox",
         "verdict": "critical", "topReason": {"code": "offline"}},
        {"id": "vm:pve1:104", "name": "backup-runner", "type": "vm", "verdict": "stale",
         "topReason": {"code": "telemetry_stale", "detail": "14m"}},
        {"id": "app-container:x", "name": "grafana", "type": "app-container", "verdict": "attention",
         "topReason": {"code": "something_new"}},
    ],
}


def alert(level: str, name: str, started: str, **more: object) -> dict:
    return {"id": f"{name}-{level}", "type": "cpu", "level": level, "resourceId": f"vm:{name}", "resourceName": name,
            "node": "pve1", "instance": "pve", "message": f"CPU usage at 95% on {name}", "value": 95, "threshold": 90,
            "startTime": started, "lastSeen": started, "acknowledged": False, **more}


@pytest.fixture
def ctx() -> Context:
    return Context(outbound_client(guard=False), integration_id=1, widget_id=1, cache={})


@respx.mock
async def test_the_overview_counts_and_turns_red_on_a_critical_resource(ctx: Context) -> None:
    route = respx.get(f"{BASE}/state/summary").mock(return_value=httpx.Response(200, json=SUMMARY))
    data = await get_adapter("pulse").fetch("overview", CONFIG, {}, ctx)
    assert data.status == "bad"
    assert data.primary == {"label": "Active alerts", "value": 3}
    assert data.secondary == [
        {"label": "Critical", "value": 1},
        {"label": "Needs attention", "value": 2},
        {"label": "Nodes", "value": 2},
        {"label": "VMs", "value": 8},
        {"label": "LXC containers", "value": 12},
        {"label": "Docker containers", "value": 5},
        {"label": "No fresh data", "value": 1},
    ]
    assert data.metrics == {"alerts": 3.0, "critical": 1.0, "attention": 2.0}
    assert data.link == "http://pulse:7655"
    sent = route.calls.last.request.headers
    assert sent["X-API-Token"] == "pulse-example-token"
    assert "Authorization" not in sent


@respx.mock
async def test_powered_off_machines_leave_the_overview_green(ctx: Context) -> None:
    calm = {**SUMMARY, "activeAlerts": 0, "verdicts": {"ok": 20, "attention": 0, "critical": 0, "stale": 0, "off": 5, "unknown": 0}}
    respx.get(f"{BASE}/state/summary").mock(return_value=httpx.Response(200, json=calm))
    data = await get_adapter("pulse").fetch("overview", CONFIG, {}, ctx)
    assert data.status == "ok"
    assert [row["label"] for row in data.secondary] == ["Nodes", "VMs", "LXC containers", "Docker containers"]


@respx.mock
async def test_a_pulse_that_watches_only_docker_shows_no_row_of_zeros(ctx: Context) -> None:
    # As a fresh Pulse 6.5.0 with one Docker agent answered on 20.10.2026: 67 containers, 19 of them stopped.
    docker_only = {
        "activeAlerts": 19, "nodes": 0, "vms": 0, "containers": 0,
        "dockerHosts": [{"name": "docker-host", "containers": 67, "uptimeSeconds": 232696, "cpuUsagePercent": 19.5}],
        "lastUpdate": "2026-10-20T05:35:57.086781497Z",
        "verdicts": {"ok": 508, "attention": 0, "critical": 0, "stale": 0, "off": 19, "unknown": 0}, "attention": [],
    }
    respx.get(f"{BASE}/state/summary").mock(return_value=httpx.Response(200, json=docker_only))
    pulse = get_adapter("pulse")
    data = await pulse.fetch("overview", CONFIG, {}, ctx)
    assert data.secondary == [{"label": "Docker containers", "value": 67}]
    # Stopped containers raise warnings in Pulse but are "off", not a problem of their own.
    assert data.status == "warn"
    assert await pulse.test(CONFIG, ctx) == "Pulse answers and watches 527 resources."
    empty = {**docker_only, "dockerHosts": [], "activeAlerts": 0}
    assert pulse.overview_card(empty).secondary == [{"label": "Nodes", "value": 0}]


@respx.mock
async def test_an_older_pulse_shows_the_counts_and_the_attention_card_says_why_it_is_empty(ctx: Context) -> None:
    respx.get(f"{BASE}/state/summary").mock(return_value=httpx.Response(200, json=OLD_SUMMARY))
    pulse = get_adapter("pulse")
    overview = await pulse.fetch("overview", CONFIG, {}, ctx)
    assert overview.status == "warn"
    assert overview.metrics == {"alerts": 1.0}
    assert [row["label"] for row in overview.secondary] == ["Nodes", "VMs", "LXC containers", "Docker containers"]
    assert await pulse.test(CONFIG, ctx) == "Pulse answers."
    attention = await pulse.fetch("attention", CONFIG, {}, ctx)
    assert attention.items == []
    assert attention.status == "unknown"
    assert attention.meta["empty"] == "This card needs Pulse 6.5 or newer."


@respx.mock
async def test_the_attention_card_puts_the_worst_first_and_names_the_reason(ctx: Context) -> None:
    respx.get(f"{BASE}/state/summary").mock(return_value=httpx.Response(200, json=SUMMARY))
    data = await get_adapter("pulse").fetch("attention", CONFIG, {"limit": 3}, ctx)
    assert data.status == "bad"
    assert data.items == [
        {"title": "pve3", "subtitle": "Server · Offline", "value": "Critical", "status": "bad"},
        {"title": "local-zfs", "subtitle": "Storage · Warning · disk", "value": "Needs attention", "status": "warn"},
        {"title": "grafana", "subtitle": "Container · Something new", "value": "Needs attention", "status": "warn"},
    ]
    assert data.secondary == [{"label": "OK", "value": 17}, {"label": "Off", "value": 2}]


@respx.mock
async def test_resources_without_fresh_data_leave_the_card_grey_not_green(ctx: Context) -> None:
    unclear = {**SUMMARY, "attention": [row for row in SUMMARY["attention"] if row["verdict"] == "stale"]}
    respx.get(f"{BASE}/state/summary").mock(return_value=httpx.Response(200, json=unclear))
    data = await get_adapter("pulse").fetch("attention", CONFIG, {}, ctx)
    assert data.status == "unknown"
    assert data.items == [{"title": "backup-runner", "subtitle": "VM · No fresh data · 14m", "value": "Stale", "status": "unknown"}]


@respx.mock
async def test_nothing_to_look_at_is_green_and_says_so(ctx: Context) -> None:
    calm = {**SUMMARY, "attention": []}
    respx.get(f"{BASE}/state/summary").mock(return_value=httpx.Response(200, json=calm))
    data = await get_adapter("pulse").fetch("attention", CONFIG, {}, ctx)
    assert data.status == "ok"
    assert data.meta["empty"] == "Nothing needs a look."


async def test_the_alerts_put_critical_first_and_an_acknowledged_one_does_not_colour_the_card() -> None:
    alerts = [
        alert("warning", "jellyfin", "2026-10-20T08:30:00Z"),
        alert("critical", "pve3", "2026-10-20T09:56:00.5+00:00", acknowledged=True, ackUser="admin"),
        alert("warning", "nas", "2026-10-20T09:00:00Z", nodeDisplayName="Main node"),
        alert("warning", "grafana", "2026-10-20T09:00:00Z", node="201eb85cdf74", metadata={"hostName": "docker-host", "hostHostname": "201eb85cdf74"}),
    ]
    pulse = get_adapter("pulse")
    data = pulse.alerts_card(alerts, {}, now=NOW)
    assert [item["title"] for item in data.items] == ["pve3", "jellyfin", "nas", "grafana"]
    assert data.items[0] == {"title": "pve3", "subtitle": "CPU usage at 95% on pve3 · pve1 · Acknowledged", "value": "3 min", "status": "bad"}
    assert data.items[1]["value"] == "1 h"
    assert data.items[2]["subtitle"] == "CPU usage at 95% on nas · Main node"
    assert data.items[3]["subtitle"] == "CPU usage at 95% on grafana · docker-host"
    assert data.status == "warn"
    assert data.metrics == {"critical": 1.0, "warning": 3.0}
    hidden = pulse.alerts_card(alerts, {"acknowledged": False}, now=NOW)
    assert [item["title"] for item in hidden.items] == ["jellyfin", "nas", "grafana"]
    assert hidden.metrics == {"critical": 0.0, "warning": 3.0}


async def test_an_open_critical_alert_turns_the_card_red_and_an_unset_start_shows_no_age() -> None:
    data = get_adapter("pulse").alerts_card([alert("critical", "pve3", "0001-01-01T00:00:00Z")], {}, now=NOW)
    assert data.status == "bad"
    assert data.items[0]["value"] == ""


@respx.mock
async def test_the_alerts_card_reads_the_active_alerts(ctx: Context) -> None:
    respx.get(f"{BASE}/alerts/active").mock(return_value=httpx.Response(200, json=[]))
    data = await get_adapter("pulse").fetch("alerts", CONFIG, {}, ctx)
    assert data.status == "ok"
    assert data.items == []
    assert data.meta["empty"] == "No alert is raised."


@respx.mock
async def test_the_test_counts_what_pulse_watches(ctx: Context) -> None:
    respx.get(f"{BASE}/state/summary").mock(return_value=httpx.Response(200, json=SUMMARY))
    assert await get_adapter("pulse").test(CONFIG, ctx) == "Pulse answers and watches 23 resources."


@respx.mock
async def test_a_wrong_token_and_a_missing_scope_say_different_things(ctx: Context) -> None:
    pulse = get_adapter("pulse")
    respx.get(f"{BASE}/state/summary").mock(return_value=httpx.Response(401, json={"error": "unauthorized"}))
    with pytest.raises(AuthFailed):
        await pulse.test(CONFIG, ctx)
    respx.get(f"{BASE}/state/summary").mock(return_value=httpx.Response(403, json={"error": "missing_scope"}))
    with pytest.raises(AdapterError) as failure:
        await pulse.test(CONFIG, ctx)
    assert failure.value.code == "missing_scope"
    assert "monitoring:read" in (failure.value.hint or "")


@respx.mock
async def test_something_else_at_the_address_is_not_taken_for_pulse(ctx: Context) -> None:
    pulse = get_adapter("pulse")
    respx.get(f"{BASE}/state/summary").mock(return_value=httpx.Response(404, text="not found"))
    with pytest.raises(AdapterError) as failure:
        await pulse.test(CONFIG, ctx)
    assert failure.value.code == "not_pulse"
    respx.get(f"{BASE}/state/summary").mock(return_value=httpx.Response(200, json={"status": "ok"}))
    with pytest.raises(AdapterError) as failure:
        await pulse.test(CONFIG, ctx)
    assert failure.value.code == "not_pulse"


def test_the_demo_fills_every_card() -> None:
    pulse = get_adapter("pulse")
    for tick in range(4):
        assert pulse.demo("overview", {}, tick).primary
        assert pulse.demo("attention", {}, tick).items
        assert pulse.demo("alerts", {}, tick).items
