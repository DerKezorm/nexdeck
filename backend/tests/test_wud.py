"""What's Up Docker, against the answers of a live WUD 9.0.0 (11.09.2026)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context, Unreachable
from app.adapters.wud import WudAdapter

WUD = "http://wud.example.com:3000"
CONFIG = {"url": WUD, "token": "wud_madeuptoken"}
TARGET = "7a1d" * 16
HELD = "3be0" * 16
BUILD = "c41f" * 16
LOCAL = "9e27" * 16


def container(identifier: str, name: str, image: str, tag: str, *, update: bool = False,
              kind: dict[str, Any] | None = None, error: str | None = None, trigger_include: str | None = None) -> dict[str, Any]:
    """The shape WUD 9.0.0 answered with, trimmed of the compose labels."""
    one: dict[str, Any] = {
        "id": identifier, "name": name, "displayName": name, "displayIcon": "mdi:docker", "status": "running",
        "watcher": "local", "stack": "example", "includeTags": None, "excludeTags": None, "transformTags": None,
        "linkTemplate": None, "link": None, "triggerInclude": trigger_include, "triggerExclude": None,
        "labels": {"wud.watch": "true"},
        "image": {"id": "sha256:" + "5" * 64, "registry": {"name": "hub.public", "url": "https://registry-1.docker.io/v2"},
                  "name": image, "tag": {"value": tag, "semver": True},
                  "digest": {"watch": False, "value": None, "repo": "sha256:" + "5" * 64},
                  "architecture": "amd64", "os": "linux", "variant": None, "created": "2024-05-03T19:49:21.000Z"},
        "result": {"tag": tag, "digest": None, "created": None, "link": None},
        "updateAvailable": update,
        "updateKind": kind or {"kind": "unknown", "localValue": None, "remoteValue": None, "semverDiff": None},
    }
    if error:
        one["error"] = {"message": error}
    return one


CONTAINERS = [
    container(HELD, "held", "library/nginx", "1.25-alpine"),
    container(LOCAL, "internal", "example/local-only", "1.0", error="Request failed with status code 401"),
    container(BUILD, "proxy", "library/nginx", "mainline-alpine", update=True,
              kind={"kind": "digest", "localValue": "sha256:" + "1" * 64, "remoteValue": "sha256:" + "2" * 64, "semverDiff": None}),
    container(TARGET, "web", "library/nginx", "1.25-alpine", update=True, trigger_include="docker.test",
              kind={"kind": "tag", "localValue": "1.25-alpine", "remoteValue": "1.31-alpine", "semverDiff": "minor"}),
]
DOCKER_TRIGGER = {"id": "docker.test", "type": "docker", "name": "test", "configuration": {
    "prune": False, "includebydefault": False, "auto": False, "dryrun": False, "autoremovetimeout": 10000,
    "multinetworkfallback": True, "threshold": "all", "mode": "simple", "once": True}}
NTFY_TRIGGER = {"id": "ntfy.phone", "type": "ntfy", "name": "phone", "configuration": {"threshold": "all", "mode": "simple"}}


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


@respx.mock
async def test_updates_with_a_button_only_where_a_docker_trigger_is(ctx: Context) -> None:
    listing = respx.get(f"{WUD}/api/containers").mock(return_value=httpx.Response(200, json=CONTAINERS))
    respx.get(f"{WUD}/api/containers/{TARGET}/triggers").mock(return_value=httpx.Response(200, json=[DOCKER_TRIGGER]))
    # A notification trigger updates nothing, so that row gets no button.
    respx.get(f"{WUD}/api/containers/{BUILD}/triggers").mock(return_value=httpx.Response(200, json=[NTFY_TRIGGER]))
    data = await get_adapter("wud").fetch("updates", CONFIG, {"limit": 10}, ctx)
    assert listing.calls.last.request.headers["Authorization"] == "Bearer wud_madeuptoken"
    assert [(row["title"], row["subtitle"], row["status"], row.get("value")) for row in data.items] == [
        ("web", "Minor · nginx", "ok", "1.25-alpine → 1.31-alpine"),
        ("proxy", "New build · nginx", "ok", None),
        ("internal", "Not checked · Request failed with status code 401", "unknown", None),
    ]
    update = data.items[0]["actions"][0]
    assert (update.id, update.params, update.confirm) == ("update", {"id": TARGET, "type": "docker", "name": "test"}, True)
    assert "actions" not in data.items[1] and "actions" not in data.items[2]
    assert data.secondary == [{"label": "Not checked", "value": 1}]
    assert data.status == "warn" and data.metrics == {"updates": 2.0}


def test_a_major_step_comes_first_and_warns() -> None:
    major = container("0dbb" * 16, "db", "library/postgres", "16-alpine", update=True,
                      kind={"kind": "tag", "localValue": "16-alpine", "remoteValue": "17-alpine", "semverDiff": "major"})
    data = WudAdapter._updates([*CONTAINERS, major], {}, 2)
    assert [(row["title"], row["subtitle"], row["status"]) for row in data.items] == [("db", "Major · postgres", "warn"), ("web", "Minor · nginx", "ok")]
    calm = WudAdapter._updates([CONTAINERS[0]], {}, 10)
    assert calm.status == "ok" and calm.items == [] and calm.secondary == []


@respx.mock
async def test_the_summary_counts_updates_and_what_could_not_be_checked(ctx: Context) -> None:
    respx.get(f"{WUD}/api/containers").mock(return_value=httpx.Response(200, json=CONTAINERS))
    data = await get_adapter("wud").fetch("summary", CONFIG, {}, ctx)
    assert data.primary == {"label": "Updates", "value": 2, "unit": "/ 4"}
    assert data.secondary == [{"label": "Not checked", "value": 1}]
    assert data.meta["ring"] == [{"label": "Up to date", "value": 1.0}, {"label": "Updates", "value": 2.0}, {"label": "Not checked", "value": 1.0}]
    assert [action.id for action in data.actions] == ["check"] and data.status == "warn"


def test_the_token_is_the_only_credential() -> None:
    """⚠️ Measured: basic authentication leaves a session cookie behind, and with it
    no header, a made-up token and a wrong password all got in."""
    assert [field.name for field in WudAdapter.fields] == ["url", "token", "insecure"]
    token = next(field for field in WudAdapter.fields if field.name == "token")
    assert token.secret and token.required
    nothing = WudAdapter._summary([])
    assert nothing.status == "unknown" and nothing.primary == {"label": "Updates", "value": 0, "unit": "/ 0"}


@respx.mock
async def test_a_rejected_token(ctx: Context) -> None:
    """⚠️ Measured: no header, a made-up token and a wrong password all get 401."""
    route = respx.get(f"{WUD}/api/containers").mock(return_value=httpx.Response(
        401, text="Unauthorized", headers={"www-authenticate": 'Bearer realm="Users", error="invalid_token"'}))
    with pytest.raises(AuthFailed):
        await get_adapter("wud").fetch("updates", CONFIG, {}, ctx)
    route.mock(return_value=httpx.Response(403, json={"error": "Forbidden: API token missing read scope"}))
    # A fresh context: the one above still remembers the 401 for a few seconds.
    with pytest.raises(AuthFailed) as scope:
        await get_adapter("wud").fetch("summary", CONFIG, {}, Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={}))
    assert "read scope" in scope.value.message


@respx.mock
async def test_an_unreachable_wud(ctx: Context) -> None:
    respx.get(f"{WUD}/api/containers").mock(side_effect=httpx.ConnectError("connection refused"))
    with pytest.raises(Unreachable):
        await get_adapter("wud").fetch("summary", CONFIG, {}, ctx)


@respx.mock
async def test_updating_runs_the_docker_trigger(ctx: Context) -> None:
    run = respx.post(f"{WUD}/api/containers/{TARGET}/triggers/docker/test").mock(return_value=httpx.Response(200, json={}))
    params = {"id": TARGET, "type": "docker", "name": "test"}
    assert await get_adapter("wud").action("updates", "update", params, CONFIG, {}, ctx) == "WUD has updated the container."
    assert run.calls.last.request.headers["Authorization"] == "Bearer wud_madeuptoken"
    # ⚠️ Measured: the recreated container has a new id, and the old one gets 404.
    respx.post(f"{WUD}/api/containers/{HELD}/triggers/docker/test").mock(
        return_value=httpx.Response(404, json={"error": "Not found", "message": "Container not found"}))
    with pytest.raises(AdapterError) as gone:
        await get_adapter("wud").action("updates", "update", {**params, "id": HELD}, CONFIG, {}, ctx)
    assert gone.value.code == "action_failed" and gone.value.message == "WUD no longer knows this container." and "new id" in gone.value.hint
    respx.post(f"{WUD}/api/containers/{BUILD}/triggers/docker/test").mock(return_value=httpx.Response(500, json={
        "error": "Trigger execution failed",
        "message": "Error when running trigger (type=docker, name=test) (Cannot read properties of undefined (reading 'indexOf'))"}))
    with pytest.raises(AdapterError) as crashed:
        await get_adapter("wud").action("updates", "update", {**params, "id": BUILD}, CONFIG, {}, ctx)
    assert crashed.value.code == "action_failed" and "Cannot read properties" in crashed.value.message
    respx.post(f"{WUD}/api/containers/{LOCAL}/triggers/docker/test").mock(
        return_value=httpx.Response(403, json={"error": "Forbidden: API token missing write scope"}))
    with pytest.raises(AuthFailed):
        await get_adapter("wud").action("updates", "update", {**params, "id": LOCAL}, CONFIG, {}, ctx)


async def test_an_update_only_goes_to_a_trigger_that_updates(ctx: Context) -> None:
    with pytest.raises(AdapterError) as notify:
        await get_adapter("wud").action("updates", "update", {"id": TARGET, "type": "ntfy", "name": "phone"}, CONFIG, {}, ctx)
    assert notify.value.code == "bad_param"
    with pytest.raises(AdapterError) as walked:
        await get_adapter("wud").action("updates", "update", {"id": "../watch", "type": "docker", "name": "test"}, CONFIG, {}, ctx)
    assert walked.value.code == "bad_param"
    with pytest.raises(AdapterError) as unknown:
        await get_adapter("wud").action("updates", "restart", {"id": TARGET}, CONFIG, {}, ctx)
    assert unknown.value.code == "no_such_action"


@respx.mock
async def test_check_now(ctx: Context) -> None:
    watch = respx.post(f"{WUD}/api/containers/watch").mock(return_value=httpx.Response(200, json=CONTAINERS))
    assert await get_adapter("wud").action("summary", "check", {}, CONFIG, {}, ctx) == "WUD has checked every watched container again."
    assert watch.call_count == 1
    watch.mock(return_value=httpx.Response(403, json={"error": "Forbidden: API token missing write scope"}))
    with pytest.raises(AuthFailed) as refused:
        await get_adapter("wud").action("summary", "check", {}, CONFIG, {}, ctx)
    assert "write scope" in refused.value.message


@respx.mock
async def test_the_connection_test(ctx: Context) -> None:
    respx.get(f"{WUD}/api/app").mock(return_value=httpx.Response(200, json={"name": "wud", "version": "9.0.0"}))
    respx.get(f"{WUD}/api/containers").mock(return_value=httpx.Response(200, json=CONTAINERS))
    assert await get_adapter("wud").test(CONFIG, ctx) == "What's Up Docker 9.0.0 answers with 4 watched containers."
