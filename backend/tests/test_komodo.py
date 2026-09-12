"""Komodo, against the answers of a live Komodo 2.3.3 (11.09.2026)."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters import komodo as module
from app.adapters.base import AdapterError, AuthFailed, Context, Unreachable

KM = "http://komodo.example.com:9120"
CONFIG = {"url": KM, "api_key": "K_madeupkey", "api_secret": "S_madeupsecret"}
SERVER = "0000000000000000000000a1"
WEB = "0000000000000000000000b1"
BROKEN = "0000000000000000000000b2"


def stack(identifier: str, name: str, state: str, status: str | None, services: list[tuple[str, str]]) -> dict[str, Any]:
    """The list entry as Komodo 2.3.3 answered it."""
    return {"id": identifier, "type": "Stack", "name": name, "template": False, "tags": [], "info": {
        "swarm_id": "", "swarm_name": "", "server_id": SERVER, "server_name": "Local", "files_on_host": False, "file_contents": True,
        "linked_repo": "", "linked_repo_name": "", "git_provider": "github.com", "repo": "", "branch": "main",
        "repo_link": "https://github.com//tree/main", "state": state, "status": status,
        "services": [{"service": service, "image": image, "latest_image": None, "update_available": False} for service, image in services],
        "auto_update_all_services": False, "project_missing": False, "missing_files": [], "deployed_hash": None, "latest_hash": None}}


#: Named so that the alphabet would put the healthy one first.
STACKS = [
    stack(WEB, "app", "running", "running(2)", [("sidecar", "nginx:1.26.0-alpine"), ("web", "nginx:1.26.0-alpine")]),
    stack(BROKEN, "broken", "down", None, [("app", "example/does-not-exist:0.0.1")]),
]
DEPLOYMENTS = [
    {"id": "0000000000000000000000c1", "type": "Deployment", "name": "api", "template": False, "tags": [], "info": {
        "state": "running", "status": "Up 9 seconds", "custom_name": "api", "image": "nginx:1.26.0-alpine", "update_available": False,
        "swarm_id": "", "swarm_name": "", "server_id": SERVER, "server_name": "Local", "build_id": None}},
    {"id": "0000000000000000000000c2", "type": "Deployment", "name": "job", "template": False, "tags": [], "info": {
        "state": "exited", "status": "Exited (0) 2 minutes ago", "custom_name": "job", "image": "example/job:1.0", "update_available": False,
        "swarm_id": "", "swarm_name": "", "server_id": SERVER, "server_name": "Local", "build_id": None}},
]
IN_PROGRESS = {"_id": {"$oid": "0000000000000000000000d1"}, "operation": "RestartStack", "start_ts": 1789162432023, "success": True,
               "operator": "0000000000000000000000e1", "target": {"type": "Stack", "id": WEB}, "logs": [], "end_ts": None, "status": "InProgress"}
REFUSED_LOG = {"stage": "Task Error", "success": False, "stdout": "", "command": "", "start_ts": 1789162432073, "end_ts": 1789162432074,
               "stderr": '<span style="color: var(--mantine-color-red-6)">ERROR</span>: User does not have required permissions on this Stack. Must have at least Execute permissions'}


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(module, "POLL_SECONDS", 0)


@respx.mock
async def test_stacks_troubled_first_with_a_restart_where_there_are_containers(ctx: Context) -> None:
    route = respx.post(f"{KM}/read/ListStacks").mock(return_value=httpx.Response(200, json=STACKS))
    data = await get_adapter("komodo").fetch("stacks", CONFIG, {"limit": 10}, ctx)
    request = route.calls.last.request
    assert (request.headers["X-Api-Key"], request.headers["X-Api-Secret"]) == ("K_madeupkey", "S_madeupsecret")
    # ⚠️ limit 0 is every entry; without it Komodo stops at its page size.
    assert json.loads(request.content) == {"limit": 0}
    assert [(row["title"], row["subtitle"], row["status"]) for row in data.items] == [("broken", "Down · Local", "bad"), ("app", "Running · Local", "ok")]
    restart = data.items[1]["actions"][0]
    assert (restart.id, restart.params, restart.confirm) == ("restart", {"stack": WEB}, True)
    assert "actions" not in data.items[0]
    assert data.status == "bad" and data.metrics == {"stacks_down": 1.0}
    assert [row["title"] for row in module.KomodoAdapter._stacks(STACKS, 1).items] == ["broken"]


@respx.mock
async def test_deployments_with_state_image_and_server(ctx: Context) -> None:
    respx.post(f"{KM}/read/ListDeployments").mock(return_value=httpx.Response(200, json=DEPLOYMENTS))
    data = await get_adapter("komodo").fetch("deployments", CONFIG, {"limit": 10}, ctx)
    assert [(row["title"], row["subtitle"], row["status"]) for row in data.items] == [
        ("job", "Exited · example/job:1.0 · Local", "bad"), ("api", "Running · nginx:1.26.0-alpine · Local", "ok")]
    assert data.status == "bad"


@respx.mock
async def test_the_summary(ctx: Context) -> None:
    respx.post(f"{KM}/read/GetStacksSummary").mock(return_value=httpx.Response(200, json={"total": 2, "running": 1, "stopped": 0, "down": 1, "unhealthy": 0, "unknown": 0}))
    respx.post(f"{KM}/read/GetDeploymentsSummary").mock(return_value=httpx.Response(200, json={"total": 1, "running": 1, "stopped": 0, "not_deployed": 0, "unhealthy": 0, "unknown": 0}))
    respx.post(f"{KM}/read/GetServersSummary").mock(return_value=httpx.Response(200, json={"total": 1, "healthy": 1, "warning": 0, "unhealthy": 0, "disabled": 0}))
    data = await get_adapter("komodo").fetch("summary", CONFIG, {}, ctx)
    assert data.primary == {"label": "Stacks running", "value": 1, "unit": "/ 2"}
    assert data.secondary == [{"label": "Deployments", "value": "1 / 1"}, {"label": "Servers", "value": "1 / 1"}]
    assert data.status == "bad" and data.metrics == {"stacks_running": 1.0, "stacks_down": 1.0}


def test_a_server_that_does_not_answer_turns_the_summary_red() -> None:
    calm = {"total": 1, "running": 1, "stopped": 0, "down": 0, "unhealthy": 0, "unknown": 0}
    data = module.KomodoAdapter._summary(calm, {"total": 0, "running": 0, "unhealthy": 0}, {"total": 1, "healthy": 0, "warning": 0, "unhealthy": 1, "disabled": 0})
    assert data.status == "bad" and data.secondary[1] == {"label": "Servers", "value": "0 / 1"}
    assert module.KomodoAdapter._summary(calm, {"total": 0}, {"total": 1, "healthy": 1, "unhealthy": 0}).status == "ok"


def test_a_server_without_its_periphery_leaves_every_state_unknown() -> None:
    """⚠️ Measured: with periphery stopped, stacks and deployments read unknown, not down, and that is not a calm card."""
    gone = [stack(WEB, "app", "unknown", None, []), stack(BROKEN, "broken", "unknown", None, [])]
    data = module.KomodoAdapter._stacks(gone, 10)
    assert data.status == "unknown" and [row["subtitle"] for row in data.items] == ["Unknown · Local", "Unknown · Local"]
    assert all("actions" not in row for row in data.items)
    lost = module.KomodoAdapter._deployments([{**DEPLOYMENTS[0], "info": {**DEPLOYMENTS[0]["info"], "state": "unknown"}}], 10)
    assert lost.status == "unknown" and lost.items[0]["subtitle"] == "Unknown · nginx:1.26.0-alpine · Local"


def test_a_key_that_may_see_nothing_says_so() -> None:
    """⚠️ Measured: a user without permissions gets empty lists and summaries of 0, not a refusal."""
    zero = {"total": 0, "running": 0, "stopped": 0, "down": 0, "unhealthy": 0, "unknown": 0}
    data = module.KomodoAdapter._summary(zero, zero, {"total": 0, "healthy": 0, "warning": 0, "unhealthy": 0, "disabled": 0})
    assert data.status == "unknown" and "Read on stacks" in data.meta["empty"]
    empty = module.KomodoAdapter._stacks([], 10)
    assert empty.status == "unknown" and empty.meta["empty"] == "No stacks, or none this API key may see."


@respx.mock
async def test_a_rejected_key(ctx: Context) -> None:
    respx.post(f"{KM}/read/ListStacks").mock(return_value=httpx.Response(401, json={"error": "Invalid user credentials | You have 4 attempts remaining", "trace": []}))
    with pytest.raises(AuthFailed):
        await get_adapter("komodo").fetch("stacks", CONFIG, {}, ctx)


@respx.mock
async def test_too_many_failed_attempts_lock_the_address(ctx: Context) -> None:
    """⚠️ Measured: after five wrong pairs, the right key from the same address got 429 as well."""
    respx.post(f"{KM}/read/GetStacksSummary").mock(return_value=httpx.Response(429, json={"error": "Too many attempts | Try again in 15s", "trace": []}))
    with pytest.raises(AdapterError) as locked:
        await get_adapter("komodo").fetch("summary", CONFIG, {}, ctx)
    assert locked.value.code == "rate_limited" and "15 seconds" in locked.value.hint


@respx.mock
async def test_an_unreachable_komodo(ctx: Context) -> None:
    respx.post(f"{KM}/read/ListDeployments").mock(side_effect=httpx.ConnectError("connection refused"))
    with pytest.raises(Unreachable):
        await get_adapter("komodo").fetch("deployments", CONFIG, {}, ctx)


@respx.mock
async def test_a_restart_follows_the_update_until_it_is_complete(ctx: Context) -> None:
    execute = respx.post(f"{KM}/execute/RestartStack").mock(return_value=httpx.Response(200, json=IN_PROGRESS))
    done = {**IN_PROGRESS, "status": "Complete", "end_ts": 1789162434000, "logs": [
        {"stage": "Compose Command", "success": True, "stdout": "", "stderr": " Container app-web-1 Restarting \n Container app-web-1 Started \n"}]}
    follow = respx.post(f"{KM}/read/GetUpdate").mock(side_effect=[httpx.Response(200, json=IN_PROGRESS), httpx.Response(200, json=done)])
    assert await get_adapter("komodo").action("stacks", "restart", {"stack": WEB}, CONFIG, {}, ctx) == "Komodo has restarted the stack."
    assert json.loads(execute.calls.last.request.content) == {"stack": WEB}
    assert follow.call_count == 2 and json.loads(follow.calls.last.request.content) == {"id": "0000000000000000000000d1"}


@respx.mock
async def test_a_restart_without_execute_permission_is_refused_in_the_update(ctx: Context) -> None:
    """⚠️ Measured: 200 and success true at first, success false once the Update is complete."""
    respx.post(f"{KM}/execute/RestartStack").mock(return_value=httpx.Response(200, json=IN_PROGRESS))
    respx.post(f"{KM}/read/GetUpdate").mock(return_value=httpx.Response(200, json={
        **IN_PROGRESS, "status": "Complete", "success": False, "logs": [REFUSED_LOG]}))
    with pytest.raises(AdapterError) as refused:
        await get_adapter("komodo").action("stacks", "restart", {"stack": BROKEN}, CONFIG, {}, ctx)
    assert refused.value.code == "action_failed"
    assert refused.value.message == ("Komodo could not restart the stack: User does not have required permissions on this Stack. "
                                     "Must have at least Execute permissions")


@respx.mock
async def test_a_restart_of_a_stack_komodo_does_not_know(ctx: Context) -> None:
    respx.post(f"{KM}/execute/RestartStack").mock(return_value=httpx.Response(500, json={"error": "Did not find any Stack matching gone", "trace": []}))
    with pytest.raises(AdapterError) as missing:
        await get_adapter("komodo").action("stacks", "restart", {"stack": "gone"}, CONFIG, {}, ctx)
    assert "Did not find any Stack matching gone" in missing.value.message
    with pytest.raises(AdapterError) as blank:
        await get_adapter("komodo").action("stacks", "restart", {"stack": ""}, CONFIG, {}, ctx)
    assert blank.value.code == "bad_param"
    with pytest.raises(AdapterError) as unknown:
        await get_adapter("komodo").action("stacks", "destroy", {"stack": WEB}, CONFIG, {}, ctx)
    assert unknown.value.code == "no_such_action"


@respx.mock
async def test_the_connection_test(ctx: Context) -> None:
    respx.post(f"{KM}/read/GetVersion").mock(return_value=httpx.Response(200, json={"version": "2.3.3"}))
    respx.post(f"{KM}/read/ListStacks").mock(return_value=httpx.Response(200, json=STACKS))
    assert await get_adapter("komodo").test(CONFIG, ctx) == "Komodo 2.3.3 answers; this key sees 2 stacks."
