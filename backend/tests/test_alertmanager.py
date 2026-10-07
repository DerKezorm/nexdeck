"""The Alertmanager cards against the answers of its API v2.

The answers are shaped after Alertmanager 0.34.1, measured on 07.10.2026 with
invented alerts and silences: a critical alert, a warning it inhibits on the
same instance, a warning of its own, an alert without a severity, and an
info alert under a silence; a silence in force, one still to come and one
expired. Every moment is counted from the moment the test runs.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context

URL = "http://alertmanager.example.com:9093"
API = f"{URL}/api/v2"
CONFIG = {"url": URL}
AM = get_adapter("alertmanager")


def _ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


def _at(**delta: float) -> str:
    return (datetime.now(UTC) + timedelta(**delta)).isoformat().replace("+00:00", "Z")


def _alert(name: str, severity: str | None, instance: str, *, silenced: list[str] | None = None, inhibited: list[str] | None = None,
           started: float = -2, **notes: str) -> dict[str, Any]:
    labels = {"alertname": name, "instance": instance, **({"severity": severity} if severity else {})}
    quiet = bool(silenced or inhibited)
    return {
        "annotations": notes, "endsAt": _at(days=3), "fingerprint": name.lower(), "receivers": [{"name": "nowhere"}],
        "startsAt": _at(hours=started), "updatedAt": _at(),
        "status": {"inhibitedBy": inhibited or [], "mutedBy": [], "silencedBy": silenced or [], "state": "suppressed" if quiet else "active"},
        "labels": labels,
    }


def _alerts() -> list[dict[str, Any]]:
    return [
        _alert("BackupLate", "info", "backup.example.com", silenced=["s-active"], description="Last backup 30 hours ago"),
        _alert("DiskFilling", "warning", "node1.example.com:9100", inhibited=["hostdown"], summary="Disk 85 percent full"),
        {**_alert("HostDown", "critical", "node1.example.com:9100", started=-8, summary="node1 is down"),
         "generatorURL": "http://prometheus.example.com/graph?g0.expr=up"},
        _alert("DiskFilling", "warning", "node2.example.com:9100", started=-3, summary="Disk 91 percent full"),
        _alert("CertExpiring", None, "web.example.com", started=-5),
    ]


def _silence(silence_id: str, state: str, starts: dict[str, float], ends: dict[str, float], comment: str, *matchers: dict[str, Any]) -> dict[str, Any]:
    return {"id": silence_id, "status": {"state": state}, "updatedAt": _at(), "comment": comment, "createdBy": "operator",
            "startsAt": _at(**starts), "endsAt": _at(**ends), "matchers": list(matchers)}


def _silences() -> list[dict[str, Any]]:
    return [
        _silence("s-expired", "expired", {"hours": -3}, {"hours": -2}, "Renewed", {"name": "alertname", "value": "CertExpiring", "isRegex": False, "isEqual": True}),
        _silence("s-pending", "pending", {"days": 1}, {"days": 2}, "Planned reboot", {"name": "instance", "value": "node[0-9]+.*", "isRegex": True, "isEqual": True}),
        _silence("s-active", "active", {"minutes": -5}, {"hours": 5}, "Backup host in maintenance",
                 {"name": "alertname", "value": "BackupLate", "isRegex": False, "isEqual": True},
                 {"name": "job", "value": "test", "isRegex": False, "isEqual": False}),
    ]


@respx.mock
@pytest.mark.asyncio
async def test_the_firing_alerts_put_the_critical_first_and_leave_the_quiet_ones_out() -> None:
    respx.get(f"{API}/alerts").mock(return_value=httpx.Response(200, json=_alerts()))
    data = await AM.fetch("alerts", CONFIG, {}, _ctx())
    assert data.status == "bad"
    assert [item["title"] for item in data.items] == ["HostDown", "DiskFilling", "CertExpiring"]
    first = data.items[0]
    assert first["status"] == "bad" and first["value"] == "8 h"
    assert first["subtitle"] == "critical · node1.example.com:9100 · node1 is down"
    assert first["url"] == "http://prometheus.example.com/graph?g0.expr=up"
    # An alert without a severity is shown, uncoloured.
    assert data.items[2]["status"] == "unknown"
    assert data.secondary == [{"label": "Firing", "value": 3}, {"label": "Critical", "value": 1}, {"label": "Silenced", "value": 2}]
    assert data.metrics == {"firing": 3.0, "critical": 1.0}


@respx.mock
@pytest.mark.asyncio
async def test_silenced_and_inhibited_alerts_come_after_the_firing_ones_and_say_why() -> None:
    respx.get(f"{API}/alerts").mock(return_value=httpx.Response(200, json=_alerts()))
    data = await AM.fetch("alerts", CONFIG, {"suppressed": True}, _ctx())
    assert [item["title"] for item in data.items] == ["HostDown", "DiskFilling", "CertExpiring", "DiskFilling", "BackupLate"]
    assert data.items[3]["subtitle"].startswith("Inhibited · warning")
    assert data.items[4]["subtitle"].startswith("Silenced · info")
    assert {data.items[3]["status"], data.items[4]["status"]} == {"unknown"}


@respx.mock
@pytest.mark.asyncio
async def test_the_matchers_go_to_alertmanager_one_filter_each() -> None:
    route = respx.get(f"{API}/alerts").mock(return_value=httpx.Response(200, json=_alerts()[3:4]))
    data = await AM.fetch("alerts", CONFIG, {"filter": 'severity="warning"\n\n  instance=~"node2.*"  '}, _ctx())
    assert route.calls.last.request.url.params.get_list("filter") == ['severity="warning"', 'instance=~"node2.*"']
    assert data.status == "warn"


@respx.mock
@pytest.mark.asyncio
async def test_matchers_alertmanager_does_not_take_are_said_as_such() -> None:
    respx.get(f"{API}/alerts").mock(return_value=httpx.Response(400, json={"code": 400, "message": "bad matcher format"}))
    with pytest.raises(AdapterError) as caught:
        await AM.fetch("alerts", CONFIG, {"filter": "severity=="}, _ctx())
    assert caught.value.code == "bad_filter"


@respx.mock
@pytest.mark.asyncio
async def test_the_summary_counts_what_fires_and_what_is_kept_quiet() -> None:
    respx.get(f"{API}/alerts").mock(return_value=httpx.Response(200, json=_alerts()))
    respx.get(f"{API}/silences").mock(return_value=httpx.Response(200, json=_silences()))
    data = await AM.fetch("summary", CONFIG, {}, _ctx())
    assert data.status == "bad"
    assert data.primary == {"label": "Firing", "value": 3}
    assert {row["label"]: row["value"] for row in data.secondary} == {"Critical": 1, "Warning": 1, "Silenced": 1, "Inhibited": 1, "Silences": 1}


@respx.mock
@pytest.mark.asyncio
async def test_nothing_firing_is_green() -> None:
    respx.get(f"{API}/alerts").mock(return_value=httpx.Response(200, json=_alerts()[:1]))
    respx.get(f"{API}/silences").mock(return_value=httpx.Response(200, json=[]))
    assert (await AM.fetch("summary", CONFIG, {}, _ctx())).status == "ok"
    alerts = await AM.fetch("alerts", CONFIG, {}, _ctx())
    assert alerts.status == "ok" and alerts.items == [] and alerts.meta["empty"] == "No alert is firing."


@respx.mock
@pytest.mark.asyncio
async def test_the_silences_leave_the_expired_out_and_say_when_each_ends_or_starts() -> None:
    respx.get(f"{API}/silences").mock(return_value=httpx.Response(200, json=_silences()))
    respx.get(f"{API}/alerts").mock(return_value=httpx.Response(200, json=_alerts()))
    data = await AM.fetch("silences", CONFIG, {}, _ctx())
    assert [item["title"] for item in data.items] == ['alertname="BackupLate", job!="test"', 'instance=~"node[0-9]+.*"']
    active, pending = data.items
    assert active["subtitle"] == "1 alert(s) · Backup host in maintenance · operator"
    assert active["value"] == "in 5 h" and active["status"] == "ok"
    assert pending["subtitle"] == "Pending · Planned reboot · operator"
    assert pending["value"] == "in 24 h" and pending["status"] == "unknown"
    assert data.secondary == [{"label": "Silences", "value": 1}, {"label": "Pending", "value": 1}]


@respx.mock
@pytest.mark.asyncio
async def test_a_proxy_gets_its_credentials_and_its_refusal_is_said_as_the_proxys() -> None:
    route = respx.get(f"{API}/alerts").mock(return_value=httpx.Response(401))
    token = "-".join(("made", "up", "for", "this", "test"))
    with pytest.raises(AuthFailed) as caught:
        await AM.fetch("alerts", {**CONFIG, "token": token}, {}, _ctx())
    assert route.calls.last.request.headers["Authorization"] == f"Bearer {token}"
    assert "proxy" in caught.value.hint


@respx.mock
@pytest.mark.asyncio
async def test_basic_authentication_is_sent_when_a_user_is_set() -> None:
    route = respx.get(f"{API}/alerts").mock(return_value=httpx.Response(200, json=[]))
    await AM.fetch("alerts", {**CONFIG, "username": "viewer", "password": "secret"}, {}, _ctx())
    assert route.calls.last.request.headers["Authorization"].startswith("Basic ")


@respx.mock
@pytest.mark.asyncio
async def test_an_address_without_the_api_says_so() -> None:
    respx.get(f"{API}/alerts").mock(return_value=httpx.Response(404, text="404 page not found"))
    with pytest.raises(AdapterError) as caught:
        await AM.fetch("alerts", CONFIG, {}, _ctx())
    assert caught.value.code == "not_alertmanager"
    respx.get(f"{API}/alerts").mock(return_value=httpx.Response(200, json={"status": "success"}))
    with pytest.raises(AdapterError) as caught:
        await AM.fetch("alerts", CONFIG, {}, _ctx())
    assert caught.value.code == "not_alertmanager"


@respx.mock
@pytest.mark.asyncio
async def test_unreachable_is_said() -> None:
    respx.get(f"{API}/alerts").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(AdapterError) as caught:
        await AM.fetch("alerts", CONFIG, {}, _ctx())
    assert caught.value.code == "unreachable"


@respx.mock
@pytest.mark.asyncio
async def test_the_connection_test_names_the_version_and_the_firing_alerts() -> None:
    respx.get(f"{API}/status").mock(return_value=httpx.Response(200, json={
        "cluster": {"name": "a", "peers": [{"address": "192.0.2.1:9094", "name": "a"}], "status": "ready"},
        "uptime": _at(minutes=-5), "versionInfo": {"version": "0.34.1"}}))
    respx.get(f"{API}/alerts").mock(return_value=httpx.Response(200, json=_alerts()))
    assert await AM.test(CONFIG, _ctx()) == "Alertmanager 0.34.1 answers: 3 alerts firing."
