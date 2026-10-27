"""Wazuh, against answers written after the documentation of the server API (27.10.2026). Never measured against a Wazuh."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context, Unreachable
from app.adapters.wazuh import WazuhAdapter

W = "https://wazuh.example.com:55000"
CONFIG = {"url": W, "username": "nexdeck", "password": "made-up-password", "insecure": True}
SUMMARY = {"data": {"connection": {"active": 9, "disconnected": 2, "never_connected": 1, "pending": 0, "total": 12},
                    "configuration": {"synced": 9, "not_synced": 3, "total": 12}}, "error": 0}
NOW = datetime(2026, 9, 12, 13, 25, 50, tzinfo=UTC).timestamp()
LISTED = {"data": {"affected_items": [
    {"id": "003", "name": "laptop", "ip": "192.0.2.31", "status": "never_connected", "os": {"name": "Ubuntu"}},
    {"id": "002", "name": "web-01", "ip": "192.0.2.10", "status": "disconnected", "os": {"name": "Debian GNU/Linux"}, "lastKeepAlive": "2026-09-12T10:25:50Z"},
    {"id": "004", "name": "db-01", "ip": "any", "status": "disconnected", "lastKeepAlive": "2026-09-12T12:25:50Z"}],
    "total_affected_items": 3, "total_failed_items": 0, "failed_items": []}, "message": "All selected agents information was returned", "error": 0}
DAEMONS = {"wazuh-agentlessd": "stopped", "wazuh-analysisd": "running", "wazuh-apid": "running", "wazuh-db": "running", "wazuh-execd": "running",
           "wazuh-integratord": "stopped", "wazuh-modulesd": "running", "wazuh-remoted": "running"}


def fresh(number: int = 1) -> Context:
    return Context(httpx.AsyncClient(), integration_id=number, widget_id=1, cache={})


def signed_in() -> respx.Route:
    return respx.post(f"{W}/security/user/authenticate").mock(return_value=httpx.Response(200, text="eyJhbGciOiJFUzUxMiJ9.made-up.token"))


def test_agents_card_counts_and_goes_red_for_a_disconnected_one() -> None:
    data = WazuhAdapter._agents(SUMMARY["data"]["connection"])
    assert data.primary == {"label": "Agents active", "value": 9, "unit": "/ 12"} and data.status == "bad"
    assert data.secondary == [{"label": "Disconnected", "value": 2}, {"label": "Never connected", "value": 1}]
    assert data.metrics == {"inactive": 3.0}
    assert data.meta["ring"][0] == {"label": "Active", "value": 9.0}
    # Never connected or pending is yellow: nobody lost contact, an agent was never finished.
    assert WazuhAdapter._agents({"active": 3, "disconnected": 0, "never_connected": 1, "pending": 0, "total": 4}).status == "warn"
    assert WazuhAdapter._agents({"active": 3, "disconnected": 0, "never_connected": 0, "pending": 0, "total": 3}).status == "ok"
    assert WazuhAdapter._agents({}).status == "unknown"


def test_the_silent_agents_disconnected_first_with_when_they_last_reported() -> None:
    now = NOW
    data = WazuhAdapter._silent(LISTED["data"]["affected_items"], SUMMARY["data"]["connection"], 10, now=now)
    assert [(row["title"], row["status"]) for row in data.items] == [("db-01", "bad"), ("web-01", "bad"), ("laptop", "warn")]
    assert data.items[1]["subtitle"] == "Disconnected · 192.0.2.10 · Debian GNU/Linux" and data.items[1]["value"] == "3 h" and data.items[0]["value"] == "1 h"
    assert data.items[2]["value"] == "" and data.secondary == [{"label": "Not reporting", "value": 3}] and data.status == "bad"
    assert len(WazuhAdapter._silent(LISTED["data"]["affected_items"], {}, 1).items) == 1
    assert WazuhAdapter._silent([], {}, 5).status == "ok"


def test_the_manager_is_red_for_a_failed_daemon_and_calm_about_the_ones_switched_off() -> None:
    fine = WazuhAdapter._manager(DAEMONS)
    assert fine.status == "ok" and fine.primary == {"label": "Daemons running", "value": 6, "unit": "/ 8"} and fine.metrics == {"down": 0.0}
    failed = WazuhAdapter._manager({**DAEMONS, "wazuh-analysisd": "failed"})
    assert failed.status == "bad" and failed.meta["status_reason"] == "Not running: analysisd" and failed.metrics == {"down": 1.0}
    stopped = WazuhAdapter._manager({**DAEMONS, "wazuh-remoted": "stopped"})
    assert stopped.status == "warn" and stopped.meta["status_reason"] == "Not running: remoted"
    assert WazuhAdapter._manager({}).status == "unknown"


@respx.mock
async def test_it_signs_in_once_and_sends_the_token_as_a_bearer() -> None:
    sign = signed_in()
    summary = respx.get(f"{W}/agents/summary/status").mock(return_value=httpx.Response(200, json=SUMMARY))
    respx.get(f"{W}/agents").mock(return_value=httpx.Response(200, json=LISTED))
    adapter, context = get_adapter("wazuh"), fresh()
    await adapter.fetch("agents", CONFIG, {}, context)
    await adapter.fetch("silent", CONFIG, {"limit": 2}, context)
    assert sign.call_count == 1 and sign.calls.last.request.url.params["raw"] == "true"
    assert sign.calls.last.request.headers["Authorization"].startswith("Basic ")
    assert summary.calls.last.request.headers["Authorization"] == "Bearer eyJhbGciOiJFUzUxMiJ9.made-up.token"
    listing = respx.calls.last.request
    assert listing.url.params["status"] == "disconnected,never_connected,pending" and listing.url.params["limit"] == "100"


@respx.mock
async def test_an_expired_token_signs_in_again_once() -> None:
    sign = signed_in()
    respx.get(f"{W}/manager/status").mock(side_effect=[httpx.Response(401, json={"title": "Unauthorized", "detail": "Invalid token"}),
                                                       httpx.Response(200, json={"data": {"affected_items": [DAEMONS]}})])
    data = await get_adapter("wazuh").fetch("manager", CONFIG, {}, fresh())
    assert data.status == "ok" and sign.call_count == 2
    respx.get(f"{W}/manager/status").mock(return_value=httpx.Response(401, json={"title": "Unauthorized", "detail": "Invalid token"}))
    with pytest.raises(AuthFailed):
        await get_adapter("wazuh").fetch("manager", CONFIG, {}, fresh(2))


@respx.mock
async def test_the_connection_test_names_the_api_version_and_the_agents() -> None:
    signed_in()
    respx.get(f"{W}/").mock(return_value=httpx.Response(200, json={"data": {"title": "Wazuh API REST", "api_version": "v4.9.2", "hostname": "manager"}, "error": 0}))
    respx.get(f"{W}/agents/summary/status").mock(return_value=httpx.Response(200, json=SUMMARY))
    assert await get_adapter("wazuh").test(CONFIG, fresh()) == "Wazuh 4.9.2 answers, 12 agents."


@respx.mock
async def test_wrong_credentials_wrong_address_and_unreachable() -> None:
    adapter = get_adapter("wazuh")
    respx.post(f"{W}/security/user/authenticate").mock(return_value=httpx.Response(401, json={"title": "Unauthorized", "detail": "Invalid credentials"}))
    with pytest.raises(AuthFailed) as wrong:
        await adapter.fetch("agents", CONFIG, {}, fresh(1))
    assert "user name or the password" in str(wrong.value)
    respx.post(f"{W}/security/user/authenticate").mock(return_value=httpx.Response(404, text="<html>dashboard</html>"))
    with pytest.raises(AdapterError) as dashboard:
        await adapter.fetch("agents", CONFIG, {}, fresh(2))
    assert dashboard.value.code == "http_error" and "55000" in dashboard.value.hint
    signed_in()
    respx.get(f"{W}/agents/summary/status").mock(return_value=httpx.Response(200, text="<html></html>"))
    with pytest.raises(AdapterError) as html:
        await adapter.fetch("agents", CONFIG, {}, fresh(3))
    assert html.value.code == "not_json"
    respx.post(f"{W}/security/user/authenticate").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(Unreachable):
        await adapter.fetch("agents", CONFIG, {}, fresh(4))


def test_the_password_is_a_secret_and_the_cards_have_demo_data_that_moves() -> None:
    adapter = get_adapter("wazuh")
    assert {field.name for field in adapter.fields if field.secret} == {"password"} and adapter.beta is True
    for widget in adapter.widgets:
        assert adapter.demo(widget.kind, {}, 0).error is None, widget.kind
    assert {adapter.demo("agents", {}, tick).status for tick in range(0, 900, 15)} >= {"warn", "bad"}
