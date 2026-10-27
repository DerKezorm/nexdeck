"""Node-RED, against the answers of Node-RED 5.0.9 with and without adminAuth (27.10.2026)."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import CACHE_PREFIX, AdapterError, AuthFailed, Context, Unreachable

NR = "http://nodered.example.com:1880"
OPEN = {"url": NR}
CONFIG = {"url": NR, "username": "admin", "password": "nr-test-password"}
TOKEN = "nr-test-token"
ADAPTER = get_adapter("nodered")
FIXTURES = Path(__file__).parent / "fixtures"
CREDENTIALS = json.loads((FIXTURES / "nodered_auth_login.json").read_text(encoding="utf-8"))
GRANT = {"access_token": TOKEN, "expires_in": 604800, "token_type": "Bearer"}
BAD_GRANT = {"error": "invalid_grant", "error_description": "Invalid resource owner credentials"}
LOCKED = {"error": "server_error", "error_description": "Too many login attempts. Wait 10 minutes and try again"}


def recorded(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


def fresh() -> Context:
    return Context(httpx.AsyncClient(), cache={})


def serve(*, signed_in: bool = True, flows: Any = None, diagnostics: Any = None, state: Any = None) -> dict[str, list[Any]]:
    """A fake Node-RED with adminAuth (or without), writing down every sign-in and the token of every request."""
    seen: dict[str, list[Any]] = {"grants": [], "tokens": []}

    def token(request: httpx.Request) -> httpx.Response:
        seen["grants"].append(dict(httpx.QueryParams(request.content.decode())))
        return httpx.Response(200, json=GRANT)

    def reply(answer: Any, status: int = 200) -> Any:
        def inner(request: httpx.Request) -> httpx.Response:
            seen["tokens"].append(request.headers.get("Authorization", ""))
            return httpx.Response(status, json=answer)
        return inner

    respx.get(f"{NR}/auth/login").mock(return_value=httpx.Response(200, json=CREDENTIALS if signed_in else {}))
    respx.post(f"{NR}/auth/token").mock(side_effect=token)
    respx.get(f"{NR}/settings").mock(side_effect=reply(recorded("nodered_settings.json")))
    respx.get(f"{NR}/flows/state").mock(side_effect=reply(state or recorded("nodered_flows_state.json")))
    respx.get(f"{NR}/flows").mock(side_effect=reply(flows if flows is not None else recorded("nodered_flows.json")))
    respx.get(f"{NR}/diagnostics").mock(side_effect=reply(diagnostics or recorded("nodered_diagnostics.json")))
    return seen


@respx.mock
async def test_the_test_names_the_version_and_the_state(ctx: Context) -> None:
    serve()
    assert await ADAPTER.test(CONFIG, ctx) == "Node-RED 5.0.9 answers. Flows: running."
    serve(state={"state": "stop"})
    assert await ADAPTER.test(CONFIG, fresh()) == "Node-RED 5.0.9 answers. Flows: stopped."


@respx.mock
async def test_the_sign_in_is_a_form_with_the_editor_as_client_and_one_serves_every_card(ctx: Context) -> None:
    seen = serve()
    await ADAPTER.fetch("runtime", CONFIG, {}, ctx)
    await ADAPTER.fetch("flows", CONFIG, {}, ctx)
    await ADAPTER.fetch("injects", CONFIG, {}, ctx)
    assert seen["grants"] == [{"client_id": "node-red-admin", "grant_type": "password", "scope": "*",
                               "username": "admin", "password": "nr-test-password"}]
    assert set(seen["tokens"]) == {f"Bearer {TOKEN}"}


@respx.mock
async def test_without_adminauth_nothing_signs_in(ctx: Context) -> None:
    seen = serve(signed_in=False)
    card = await ADAPTER.fetch("runtime", OPEN, {}, ctx)
    assert card.status == "ok" and seen["grants"] == [] and set(seen["tokens"]) == {""}


@respx.mock
async def test_the_runtime_card(ctx: Context) -> None:
    serve()
    card = await ADAPTER.fetch("runtime", CONFIG, {}, ctx)
    assert card.status == "ok" and card.primary == {"label": "Flows", "value": "Running"}
    rows = {row["label"]: row["value"] for row in card.secondary}
    # Two tabs, one of them off; four nodes on the one that runs, the comment and the tab itself not counted.
    assert rows["Version"] == "5.0.9" and rows["Flows"] == 1 and rows["Nodes"] == 4 and rows["Memory"].endswith(" MB")
    assert card.metrics["nodes"] == 4.0 and 50 < card.metrics["memory_mb"] < 1000


@respx.mock
async def test_stopped_flows_are_yellow_and_a_node_that_is_off_is_not_counted(ctx: Context) -> None:
    flows = recorded("nodered_flows.json")
    flows.append({"id": "off1", "type": "function", "z": "tab1", "name": "off", "d": True, "func": "return msg;", "wires": [[]]})
    flows.append({"id": "cfg", "type": "mqtt-broker", "name": "config node has no tab"})
    flows.append({"id": "sub", "type": "function", "z": "a-subflow-definition"})
    # Notes, boxes round nodes and the joints of wires are not nodes that run.
    flows.extend({"id": f"x-{kind}", "type": kind, "z": "tab1"} for kind in ("comment", "group", "junction"))
    serve(flows=flows, state={"state": "stop"})
    card = await ADAPTER.fetch("runtime", CONFIG, {}, ctx)
    assert card.status == "warn" and card.primary["value"] == "Stopped"
    assert {row["label"]: row["value"] for row in card.secondary}["Nodes"] == 4


@respx.mock
async def test_diagnostics_that_are_switched_off_cost_the_memory_and_nothing_else(ctx: Context) -> None:
    serve()
    respx.get(f"{NR}/diagnostics").mock(return_value=httpx.Response(404, text="Not Found"))
    card = await ADAPTER.fetch("runtime", CONFIG, {}, ctx)
    assert [row["label"] for row in card.secondary] == ["Version", "Flows", "Nodes"] and card.metrics == {"nodes": 4.0}


@respx.mock
async def test_the_flows_card_lists_tabs_with_the_disabled_ones_last(ctx: Context) -> None:
    flows = recorded("nodered_flows.json")
    flows.sort(key=lambda node: node["id"] != "tab2")
    serve(flows=flows)
    card = await ADAPTER.fetch("flows", CONFIG, {}, ctx)
    assert [(row["title"], row["value"], row["subtitle"], row["status"]) for row in card.items] == [
        ("Heating", 4, "", "ok"), ("Old experiments", 1, "Disabled", "unknown")]
    assert card.secondary == [{"label": "Flows", "value": 2}]
    card = await ADAPTER.fetch("flows", CONFIG, {"limit": 1}, fresh())
    assert len(card.items) == 1


@respx.mock
async def test_inject_nodes_get_a_button_but_not_in_a_disabled_flow_and_not_a_debug_node(ctx: Context) -> None:
    serve()
    card = await ADAPTER.fetch("injects", CONFIG, {}, ctx)
    # ⚠️ The disabled tab's inject node is not deployed (404); the debug node would answer 200 and run.
    assert [(row["id"], row["title"], row["subtitle"]) for row in card.items] == [("inj1", "Boost heating", "Heating"), ("inj2", "x", "Heating")]
    action = card.items[0]["actions"][0]
    assert (action.id, action.confirm, action.danger, action.params) == ("run", True, False, {"node": "inj1"})
    assert card.secondary == [{"label": "Inject nodes", "value": 2}]


@respx.mock
async def test_an_inject_node_without_a_name_is_called_by_what_it_sends(ctx: Context) -> None:
    flows = recorded("nodered_flows.json")
    for node in flows:
        if node["id"] == "inj2":
            # What it sends is a time stamp, whatever the payload field still holds.
            node.update({"payloadType": "date", "payload": "x"})
        if node["id"] == "inj1":
            node["d"] = True
    serve(flows=flows)
    card = await ADAPTER.fetch("injects", CONFIG, {}, ctx)
    assert [(row["id"], row["title"]) for row in card.items] == [("inj2", "Inject")]
    serve(flows=[])
    card = await ADAPTER.fetch("injects", CONFIG, {}, fresh())
    assert card.items == [] and card.meta["empty"] == "No inject node in a flow that runs."


@respx.mock
async def test_the_button_posts_the_inject_and_forgets_what_it_knew(ctx: Context) -> None:
    serve()
    route = respx.post(f"{NR}/inject/inj1").mock(return_value=httpx.Response(200, text="OK"))
    await ADAPTER.fetch("injects", CONFIG, {}, ctx)
    assert [key for key in ctx.cache if key.startswith(CACHE_PREFIX)]
    assert await ADAPTER.action("injects", "run", {"node": "inj1"}, CONFIG, {}, ctx) == "Triggered."
    assert route.calls[0].request.headers["Authorization"] == f"Bearer {TOKEN}"
    assert not [key for key in ctx.cache if key.startswith(CACHE_PREFIX)]
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.action("injects", "stop_everything", {"node": "inj1"}, CONFIG, {}, ctx)
    assert caught.value.code == "no_such_action"
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.action("injects", "run", {"node": "../flows"}, CONFIG, {}, ctx)
    assert caught.value.code == "bad_param"
    respx.post(f"{NR}/inject/gone").mock(return_value=httpx.Response(404, text="Not Found"))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.action("injects", "run", {"node": "gone"}, CONFIG, {}, ctx)
    assert caught.value.code == "no_node"


@respx.mock
async def test_a_user_who_may_only_read_gets_the_cards_and_is_told_why_the_button_fails() -> None:
    # ⚠️ The scope * is refused to such a user with the words of a wrong password; read is let through.
    grants: list[str] = []

    def token(request: httpx.Request) -> httpx.Response:
        scope = dict(httpx.QueryParams(request.content.decode()))["scope"]
        grants.append(scope)
        return httpx.Response(200, json=GRANT) if scope == "read" else httpx.Response(403, json=BAD_GRANT)

    serve()
    respx.post(f"{NR}/auth/token").mock(side_effect=token)
    respx.post(f"{NR}/inject/inj1").mock(return_value=httpx.Response(401, text="Unauthorized"))
    context = fresh()
    assert (await ADAPTER.fetch("runtime", CONFIG, {}, context)).status == "ok"
    assert grants == ["*", "read"]
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.action("injects", "run", {"node": "inj1"}, CONFIG, {}, context)
    assert caught.value.code == "read_only" and not isinstance(caught.value, AuthFailed)


@respx.mock
async def test_a_wrong_password_costs_two_attempts_and_is_not_tried_again(ctx: Context) -> None:
    # ⚠️ 403 for a wrong password; five of them lock the address out, so the refusal is remembered.
    serve()
    grant = respx.post(f"{NR}/auth/token").mock(return_value=httpx.Response(403, json=BAD_GRANT))
    with pytest.raises(AuthFailed) as caught:
        await ADAPTER.fetch("runtime", CONFIG, {}, ctx)
    assert caught.value.message == "Node-RED turned the user or the password down."
    with pytest.raises(AuthFailed):
        await ADAPTER.fetch("flows", CONFIG, {}, ctx)
    assert grant.call_count == 2
    ctx.cache["nodered_refused"] = (time.monotonic() - 1, "old")
    respx.post(f"{NR}/auth/token").mock(return_value=httpx.Response(200, json=GRANT))
    assert (await ADAPTER.fetch("runtime", CONFIG, {}, ctx)).status == "ok"


@respx.mock
async def test_the_lockout_is_said_in_its_own_words_and_remembered(ctx: Context) -> None:
    serve()
    grant = respx.post(f"{NR}/auth/token").mock(return_value=httpx.Response(500, json=LOCKED))
    with pytest.raises(AuthFailed) as caught:
        await ADAPTER.fetch("runtime", CONFIG, {}, ctx)
    assert "locked this address out" in caught.value.message and "ten minutes" in caught.value.hint
    with pytest.raises(AuthFailed):
        await ADAPTER.fetch("runtime", CONFIG, {}, ctx)
    assert grant.call_count == 1


@respx.mock
async def test_a_token_that_runs_out_or_is_turned_down_is_replaced_once(ctx: Context) -> None:
    seen = serve()
    await ADAPTER.fetch("flows", CONFIG, {}, ctx)
    ctx.cache["nodered_token"] = (time.monotonic() - 1, TOKEN)
    ctx.forget_answers()
    await ADAPTER.fetch("flows", CONFIG, {}, ctx)
    assert len(seen["grants"]) == 2
    # Node-RED restarted and forgot its sessions: 401 once, then fine.
    answers = iter([httpx.Response(401, text="Unauthorized"), httpx.Response(200, json=recorded("nodered_flows.json"))])
    respx.get(f"{NR}/flows").mock(side_effect=lambda request: next(answers))
    ctx.forget_answers()
    assert (await ADAPTER.fetch("flows", CONFIG, {}, ctx)).items
    assert len(seen["grants"]) == 3
    respx.get(f"{NR}/flows").mock(return_value=httpx.Response(401, text="Unauthorized"))
    ctx.forget_answers()
    with pytest.raises(AuthFailed):
        await ADAPTER.fetch("flows", CONFIG, {}, ctx)
    assert len(seen["grants"]) == 4


@respx.mock
async def test_without_a_user_it_asks_for_one(ctx: Context) -> None:
    serve()
    with pytest.raises(AuthFailed) as caught:
        await ADAPTER.fetch("runtime", OPEN, {}, ctx)
    assert caught.value.message == "Node-RED asks for a sign-in."


@respx.mock
async def test_an_outside_sign_in_is_said_not_attempted(ctx: Context) -> None:
    respx.get(f"{NR}/auth/login").mock(return_value=httpx.Response(200, json={"type": "strategy", "prompts": [{"type": "button", "label": "GitHub"}]}))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.fetch("runtime", CONFIG, {}, ctx)
    assert caught.value.code == "unsupported_login"


@respx.mock
async def test_unreachable_and_not_node_red(ctx: Context) -> None:
    respx.get(f"{NR}/auth/login").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(Unreachable):
        await ADAPTER.test(CONFIG, ctx)
    respx.get(f"{NR}/auth/login").mock(return_value=httpx.Response(200, text="<html>a router</html>"))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.test(CONFIG, fresh())
    assert caught.value.code == "not_nodered"
    serve()
    respx.get(f"{NR}/settings").mock(return_value=httpx.Response(200, json={"hello": "world"}))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.test(CONFIG, fresh())
    assert caught.value.code == "not_nodered"
    respx.get(f"{NR}/flows").mock(return_value=httpx.Response(200, json={"flows": []}))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.fetch("flows", CONFIG, {}, fresh())
    assert caught.value.code == "not_nodered"
    respx.get(f"{NR}/flows").mock(return_value=httpx.Response(200, text="<html></html>"))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.fetch("flows", CONFIG, {}, fresh())
    assert caught.value.code == "not_nodered"
    respx.get(f"{NR}/flows").mock(return_value=httpx.Response(500, text="boom"))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.fetch("flows", CONFIG, {}, fresh())
    assert caught.value.code == "http_error"
    respx.post(f"{NR}/auth/token").mock(return_value=httpx.Response(502, text="bad gateway"))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.fetch("runtime", CONFIG, {}, fresh())
    assert caught.value.code == "http_error"


@respx.mock
async def test_ignoring_tls_errors_goes_through_the_relaxed_client(ctx: Context, monkeypatch: pytest.MonkeyPatch) -> None:
    used: list[int] = []
    relaxed = httpx.AsyncClient()
    monkeypatch.setattr("app.adapters.base._relaxed_client", lambda: (used.append(1), relaxed)[1])
    serve()
    await ADAPTER.fetch("flows", {**CONFIG, "insecure": True}, {}, ctx)
    assert used
    used.clear()
    await ADAPTER.fetch("flows", CONFIG, {}, fresh())
    assert not used


@pytest.mark.parametrize("kind", [widget.kind for widget in ADAPTER.widgets])
def test_demo_has_every_card(kind: str) -> None:
    for tick in (0, 5, 50, 110):
        card = ADAPTER.demo(kind, {}, tick)
        assert card.primary or card.items
        assert card.secondary
