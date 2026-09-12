"""Zabbix, against the answers of a live Zabbix 7.4.14 (11.09.2026)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context, Unreachable
from app.adapters.zabbix import ZabbixAdapter

FIXTURES = Path(__file__).parent / "fixtures"
ZB = "http://zabbix.example.com:8080"
API = f"{ZB}/api_jsonrpc.php"
CONFIG = {"url": ZB, "token": "made-up-token"}
#: Ten minutes after the newest problem was raised.
NOW = 1789159586 + 600


def fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


PROBLEMS = fixture("zabbix_problems.json")["result"]
HOSTS = fixture("zabbix_event_hosts.json")["result"]


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


def _rows(data: Any) -> list[tuple[Any, ...]]:
    return [(row["title"], row["subtitle"], row["status"], row["value"], [(one.id, one.params) for one in row.get("actions", [])])
            for row in data.items]


def _server(answers: dict[str, Any]) -> respx.Route:
    """One address for every method, as JSON-RPC has it; each answer is a result or an error."""
    def reply(request: httpx.Request) -> httpx.Response:
        method = json.loads(request.content)["method"]
        answer = answers[method]
        body = answer if isinstance(answer, dict) and ("error" in answer or "result" in answer) else {"result": answer}
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, **body})

    return respx.post(API).mock(side_effect=reply)


def _calls(route: respx.Route, method: str) -> list[httpx.Request]:
    return [call.request for call in route.calls if json.loads(call.request.content)["method"] == method]


def test_problems_the_most_severe_first_with_hosts_and_a_button_on_the_unacknowledged() -> None:
    shown = ZabbixAdapter.ranked(PROBLEMS)
    data = ZabbixAdapter._list(PROBLEMS, shown, ZabbixAdapter.hosts_of(HOSTS), NOW)
    assert _rows(data) == [
        ("Test value is a disaster", "Disaster · app-server", "bad", "12 min", [("acknowledge", {"eventid": "8"})]),
        ("Test value is high", "High · app-server · Acknowledged", "bad", "12 min", []),
        ("Linux: Zabbix agent is not available (for 3m)", "Average · Zabbix server", "warn", "10 min", [("acknowledge", {"eventid": "26"})]),
        ("Test value is above one", "Warning · app-server · Acknowledged", "warn", "12 min", []),
    ]
    assert data.items[0]["actions"][0].confirm is True and data.meta["actions_visible"] is True
    assert data.secondary == [{"label": "Open problems", "value": 4}, {"label": "Unacknowledged", "value": 2}]
    assert data.metrics == {"problems": 4.0, "unacknowledged": 2.0} and data.status == "bad"


def test_the_overview_counts_high_or_worse_and_unacknowledged() -> None:
    data = ZabbixAdapter._summary(PROBLEMS)
    assert data.primary == {"label": "Open problems", "value": 4}
    assert data.secondary == [{"label": "High or worse", "value": 2}, {"label": "Unacknowledged", "value": 2}]
    assert data.metrics == {"problems": 4.0, "high_or_worse": 2.0} and data.status == "bad"
    average = [one for one in PROBLEMS if one["severity"] in ("2", "3")]
    assert ZabbixAdapter._summary(average).status == "warn"
    information = [{**PROBLEMS[0], "severity": "1"}]
    assert ZabbixAdapter._summary(information).status == "ok" and ZabbixAdapter._summary([]).status == "ok"
    assert ZabbixAdapter._list([], [], {}, NOW).meta["empty"] == "No problem is open."


@respx.mock
async def test_the_card_asks_like_the_problem_view_and_names_hosts_only_for_the_rows_it_shows(ctx: Context) -> None:
    route = _server({"problem.get": PROBLEMS, "event.get": HOSTS})
    data = await get_adapter("zabbix").fetch("problems", CONFIG, {"limit": 2}, ctx)
    problem_call = _calls(route, "problem.get")[0]
    assert problem_call.headers["Authorization"] == "Bearer made-up-token"
    params = json.loads(problem_call.content)["params"]
    # ⚠️ Measured: without suppressed=false the suppressed problems come too; eventid is the only sort field.
    assert (params["suppressed"], params["recent"], params["sortfield"]) == (False, False, ["eventid"])
    assert json.loads(_calls(route, "event.get")[0].content)["params"]["eventids"] == ["8", "7"]
    assert [row["title"] for row in data.items] == ["Test value is a disaster", "Test value is high"]
    assert data.items[0]["value"] != ""


@respx.mock
async def test_acknowledging_a_problem(ctx: Context) -> None:
    route = _server({"event.acknowledge": {"eventids": [8]}})
    assert await get_adapter("zabbix").action("problems", "acknowledge", {"eventid": "8"}, CONFIG, {}, ctx) == "Problem acknowledged."
    assert json.loads(route.calls.last.request.content)["params"] == {"eventids": ["8"], "action": 2}
    assert route.calls.last.request.headers["Authorization"] == "Bearer made-up-token"


@respx.mock
async def test_the_refusals_of_acknowledging(ctx: Context) -> None:
    adapter = get_adapter("zabbix")
    _server({"event.acknowledge": {"error": {"code": -32500, "message": "Application error.", "data": "No permissions to referred object or it does not exist!"}}})
    with pytest.raises(AdapterError) as gone:
        await adapter.action("problems", "acknowledge", {"eventid": "999999"}, CONFIG, {}, ctx)
    assert (gone.value.code, gone.value.message) == ("action_failed", "Zabbix has no such problem, or this token may not see it.")
    _server({"event.acknowledge": {"error": {"code": -32500, "message": "Application error.",
                                             "data": "Incorrect value for field \"action\": no permissions to acknowledge problems."}}})
    with pytest.raises(AdapterError) as not_allowed:
        await adapter.action("problems", "acknowledge", {"eventid": "8"}, CONFIG, {}, ctx)
    assert not_allowed.value.code == "action_failed" and "no permissions to acknowledge" in not_allowed.value.message
    _server({"event.acknowledge": {"eventids": []}})
    with pytest.raises(AdapterError) as silent:
        await adapter.action("problems", "acknowledge", {"eventid": "8"}, CONFIG, {}, ctx)
    assert silent.value.code == "action_failed"
    with pytest.raises(AdapterError) as bad:
        await adapter.action("problems", "acknowledge", {"eventid": "../1"}, CONFIG, {}, ctx)
    assert bad.value.code == "bad_param"
    with pytest.raises(AdapterError) as unknown:
        await adapter.action("problems", "close", {"eventid": "8"}, CONFIG, {}, ctx)
    assert unknown.value.code == "no_such_action"


@respx.mock
async def test_a_refused_token_comes_inside_a_200(ctx: Context) -> None:
    """⚠️ Measured: a missing and a made-up token both get HTTP 200 with this error."""
    _server({"problem.get": {"error": {"code": -32602, "message": "Invalid params.", "data": "Not authorized."}}})
    with pytest.raises(AuthFailed):
        await get_adapter("zabbix").fetch("summary", CONFIG, {}, ctx)


@respx.mock
async def test_an_address_that_is_not_zabbix(ctx: Context) -> None:
    respx.post(API).mock(return_value=httpx.Response(200, json={"status": "ok"}))
    with pytest.raises(AdapterError) as wrong:
        await get_adapter("zabbix").fetch("summary", CONFIG, {}, ctx)
    assert wrong.value.code == "not_zabbix"
    respx.post(API).mock(return_value=httpx.Response(200, text="<html>sign in</html>"))
    with pytest.raises(AdapterError) as page:
        await get_adapter("zabbix").fetch("summary", CONFIG, {}, ctx)
    assert page.value.code == "not_json"


@respx.mock
async def test_a_zabbix_that_does_not_answer(ctx: Context) -> None:
    respx.post(API).mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(Unreachable):
        await get_adapter("zabbix").fetch("problems", CONFIG, {}, ctx)


@respx.mock
async def test_the_connection_test_asks_the_version_without_the_token(ctx: Context) -> None:
    """⚠️ Measured: apiinfo.version refuses a request that carries the header."""
    route = _server({"apiinfo.version": "7.4.14", "problem.get": PROBLEMS})
    assert await get_adapter("zabbix").test(CONFIG, ctx) == "Zabbix 7.4.14 answers; 4 problems are open."
    assert "Authorization" not in _calls(route, "apiinfo.version")[0].headers
    assert _calls(route, "problem.get")[0].headers["Authorization"] == "Bearer made-up-token"
