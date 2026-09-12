"""Netdata, against the answers of a live Netdata 2.11.0 (11.09.2026): a parent with one child streaming to it."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context, Unreachable
from app.adapters.netdata import NetdataAdapter

FIXTURES = Path(__file__).parent / "fixtures"
ND = "http://netdata.example.com:19999"
CONFIG = {"url": ND}
#: Five minutes after the child's alerts were raised, six after the parent's.
NOW = 1789158503 + 300


def fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


def test_raised_alerts_critical_first_and_newest_first_on_every_node() -> None:
    data = NetdataAdapter._alerts(fixture("netdata_alerts.json"), {}, NOW)
    assert [(row["title"], row["subtitle"], row["status"], row["value"]) for row in data.items] == [
        ("nexdeck_test_cpu", "Critical · child · 4 %", "bad", "5 min"),
        ("nexdeck_test_cpu", "Critical · parent · 4 %", "bad", "6 min"),
        ("nexdeck_test_load", "Warning · child · 0.28 load", "warn", "5 min"),
        ("nexdeck_test_load", "Warning · parent · 0.28 load", "warn", "6 min"),
    ]
    assert data.status == "bad"
    assert data.secondary == [{"label": "Critical", "value": 2}, {"label": "Warning", "value": 2}]
    assert data.metrics == {"critical": 2.0, "warning": 2.0}
    assert len(NetdataAdapter._alerts(fixture("netdata_alerts.json"), {"limit": 1}, NOW).items) == 1


def test_nothing_raised_is_an_empty_list_and_calm() -> None:
    """Measured: nothing raised is ``"alert_instances": []``."""
    answer = {**fixture("netdata_alerts.json"), "alert_instances": []}
    data = NetdataAdapter._alerts(answer, {}, NOW)
    assert (data.status, data.items, data.metrics) == ("ok", [], {"critical": 0.0, "warning": 0.0})
    only_warnings = {**answer, "alert_instances": fixture("netdata_alerts.json")["alert_instances"][1:2]}
    assert NetdataAdapter._alerts(only_warnings, {}, NOW).status == "warn"


@respx.mock
async def test_the_alerts_card_asks_for_raised_alerts_of_every_node(ctx: Context) -> None:
    route = respx.get(f"{ND}/api/v3/alerts").mock(return_value=httpx.Response(200, json=fixture("netdata_alerts.json")))
    data = await get_adapter("netdata").fetch("alerts", CONFIG, {"limit": 3}, ctx)
    assert dict(route.calls.last.request.url.params) == {"status": "raised", "options": "instances,values"}
    assert [row["subtitle"].split(" · ")[0] for row in data.items] == ["Critical", "Critical", "Warning"]


@respx.mock
async def test_load_per_node_with_its_state_and_worst_alert(ctx: Context) -> None:
    respx.get(f"{ND}/api/v3/nodes").mock(return_value=httpx.Response(200, json=fixture("netdata_nodes.json")))
    load = respx.get(f"{ND}/api/v3/data").mock(return_value=httpx.Response(200, json=fixture("netdata_load.json")))
    data = await get_adapter("netdata").fetch("nodes", CONFIG, {}, ctx)
    params = load.calls.last.request.url.params
    assert (params["scope_contexts"], params["dimensions"], params["group_by"], params["format"]) == ("system.load", "load1", "node", "json2")
    assert [(row["title"], row["subtitle"], row["status"], row["value"]) for row in data.items] == [
        ("parent", "Online · Critical", "bad", "0.23"),
        ("child", "Online · Critical", "bad", "0.22"),
    ]
    assert data.secondary == [{"label": "Nodes online", "value": "2/2"}]


@respx.mock
async def test_a_child_that_stopped_streaming_is_stale_first_and_has_no_load(ctx: Context) -> None:
    """⚠️ Measured: its health turns "disabled" and its alerts leave the list, while the data query still has a value."""
    respx.get(f"{ND}/api/v3/nodes").mock(return_value=httpx.Response(200, json=fixture("netdata_nodes_stale.json")))
    respx.get(f"{ND}/api/v3/data").mock(return_value=httpx.Response(200, json=fixture("netdata_load.json")))
    data = await get_adapter("netdata").fetch("nodes", CONFIG, {}, ctx)
    assert [(row["title"], row["subtitle"], row["status"], row["value"]) for row in data.items] == [
        ("child", "Stale", "bad", ""),
        ("parent", "Online · Critical", "bad", "0.23"),
    ]
    assert data.secondary == [{"label": "Nodes online", "value": "1/2"}]
    summary = await get_adapter("netdata").fetch("summary", CONFIG, {}, ctx)
    assert summary.primary == {"label": "Raised alerts", "value": 2}
    assert summary.secondary == [{"label": "Critical", "value": 1}, {"label": "Nodes online", "value": "1/2"}]
    assert summary.status == "bad"


def test_a_load_above_the_core_count_warns() -> None:
    calm = {"status": "online", "alerts": {"critical": 0, "warning": 0}}
    nodes = [{"mg": "a", "nm": "calm", "state": "reachable", "hw": {"cpus": "4"}, "health": calm},
             {"mg": "b", "nm": "busy", "state": "reachable", "hw": {"cpus": "4"}, "health": calm}]
    data = NetdataAdapter._node_list(nodes, {"a": 1.25, "b": 5.5}, {})
    assert [(row["title"], row["subtitle"], row["status"], row["value"]) for row in data.items] == [
        ("busy", "Online", "warn", "5.50"), ("calm", "Online", "ok", "1.25")]
    assert data.status == "warn"
    assert NetdataAdapter.loads_of({}) == {} and NetdataAdapter.loads_of(fixture("netdata_load.json")) == {
        "00000000-0000-4000-8000-00000000000a": 0.235, "00000000-0000-4000-8000-00000000000b": 0.2155254}


def test_the_overview_counts_the_alerts_of_the_nodes_that_report() -> None:
    nodes = fixture("netdata_nodes.json")["nodes"]
    data = NetdataAdapter._summary(nodes)
    assert data.primary == {"label": "Raised alerts", "value": 4}
    assert data.secondary == [{"label": "Critical", "value": 2}, {"label": "Nodes online", "value": "2/2"}]
    assert data.metrics == {"critical": 2.0, "warning": 2.0} and data.status == "bad"
    warnings_only = [{**node, "health": {"status": "online", "alerts": {"critical": 0, "warning": 1}}} for node in nodes]
    assert NetdataAdapter._summary(warnings_only).status == "warn"


@respx.mock
async def test_a_refusal_is_an_auth_failure(ctx: Context) -> None:
    """Measured on the one address that wanted a sign-in: 451, not 401."""
    respx.get(f"{ND}/api/v3/nodes").mock(return_value=httpx.Response(451, text="You need to be authorized to access this resource"))
    with pytest.raises(AuthFailed):
        await get_adapter("netdata").fetch("summary", CONFIG, {}, ctx)


@respx.mock
async def test_an_agent_that_does_not_answer(ctx: Context) -> None:
    respx.get(f"{ND}/api/v3/nodes").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(Unreachable):
        await get_adapter("netdata").fetch("nodes", CONFIG, {}, ctx)


@respx.mock
async def test_an_address_that_is_not_netdata(ctx: Context) -> None:
    respx.get(f"{ND}/api/v3/alerts").mock(return_value=httpx.Response(200, json={"status": "ok"}))
    with pytest.raises(AdapterError) as wrong:
        await get_adapter("netdata").fetch("alerts", CONFIG, {}, ctx)
    assert wrong.value.code == "not_netdata"


@respx.mock
async def test_the_connection_test(ctx: Context) -> None:
    respx.get(f"{ND}/api/v3/nodes").mock(return_value=httpx.Response(200, json=fixture("netdata_nodes.json")))
    assert await get_adapter("netdata").test(CONFIG, ctx) == "Netdata v2.11.0 answers with 2 nodes."
