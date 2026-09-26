"""Arcane, against the answers of a live Arcane 2.14.0 (26.09.2026), manager plus one agent."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context, WidgetData

AR = "http://arcane.example.com:3552"
API = f"{AR}/api"
CONFIG = {"url": AR, "api_key": "arc_madeupkey"}
LOCAL = "0"
REMOTE = "27af15bf-0000-4000-8000-000000000001"
SITE = "c1" * 32
WHO = "c2" * 32
SICK = "c3" * 32
OLD = "c4" * 32
CHECKED = "2026-09-26T09:34:12.089592795Z"

ENVIRONMENTS = [
    {"id": LOCAL, "name": "Local Docker", "apiUrl": "http://arcane.example.com:3552", "status": "online", "enabled": True, "isEdge": False,
     "lastSeen": "2026-09-26T09:18:00.015473453Z"},
    {"id": REMOTE, "name": "remote-box", "apiUrl": "http://agent.example.com:3553", "status": "online", "enabled": True, "isEdge": False,
     "lastSeen": "2026-09-26T09:18:00.017613304Z"},
]


def envelope(data: Any, **extra: Any) -> dict[str, Any]:
    """Arcane wraps every answer but one, ``/app-version``."""
    return {"$schema": f"{AR}/api/schemas/Example.json", "success": True, "data": data, **extra}


def page(data: list[dict[str, Any]]) -> dict[str, Any]:
    return envelope(data, pagination={"totalPages": 1, "totalItems": len(data), "currentPage": 1, "itemsPerPage": len(data), "grandTotalItems": len(data)})


def update_info(has_update: bool, error: str = "") -> dict[str, Any]:
    return {"checkTime": CHECKED, "updateType": "digest", "currentVersion": "1.27-alpine", "latestVersion": "",
            "currentDigest": "sha256:" + "1" * 64, "latestDigest": "sha256:" + ("2" if has_update else "1") * 64, "error": error,
            "authMethod": "anonymous", "authRegistry": "docker.io", "responseTimeMs": 1204, "hasUpdate": has_update, "usedCredential": False}


def container(identifier: str, name: str, image: str, state: str, status: str, info: dict[str, Any] | None) -> dict[str, Any]:
    """The list entry as Arcane 2.14.0 answered it, without labels, ports, mounts and network settings."""
    entry = {"id": identifier, "names": [name], "image": image, "imageId": "sha256:" + "3" * 64, "command": "/whoami", "created": 1790414531,
             "state": state, "status": status, "updateStrategy": "digest", "redeployDisabled": False, "autoUpdateEnabled": True, "hidden": False}
    if info is not None:
        entry["updateInfo"] = info
    return entry


LOCAL_CONTAINERS = [
    # ⚠️ Failing its healthcheck and still "running".
    container(SICK, "sick-sick-1", "traefik/whoami:v1.10", "running", "Up About a minute (unhealthy)", update_info(False)),
    container(SITE, "web-site-1", "nginx:1.27-alpine", "running", "Up 8 seconds", update_info(True)),
    container(WHO, "web-who-1", "traefik/whoami:v1.10", "running", "Up About a minute", update_info(False)),
]
REMOTE_CONTAINERS = [
    container(OLD, "media-who-1", "traefik/whoami:v1.10", "exited", "Exited (2) 1 second ago", None),
]


def project(identifier: str, name: str, status: str, running: int, services: int, has_update: bool) -> dict[str, Any]:
    return {"tags": [], "updateInfo": {"status": "has_update" if has_update else "up_to_date", "hasUpdate": has_update, "imageCount": services,
                                       "checkedImageCount": services, "imagesWithUpdates": int(has_update), "imagesNotPulled": 0, "errorCount": 0},
            "status": status, "dirName": name, "name": name, "relativePath": name, "id": identifier, "path": f"/app/data/projects/{name}",
            "updatedAt": "2026-09-26T09:22:48Z", "createdAt": "2026-09-26T09:21:49Z", "runningCount": running, "serviceCount": services,
            "isDiscovered": False, "isArchived": False, "hasBuildDirective": False, "redeployDisabled": False}


WEB = "a25d022a-0000-4000-8000-000000000002"
BROKEN = "abd2213c-0000-4000-8000-000000000003"
MEDIA = "5497f4d1-0000-4000-8000-000000000004"
LOCAL_PROJECTS = [
    project(WEB, "web", "running", 2, 2, True),
    project(BROKEN, "broken", "stopped", 0, 1, False),
]
REMOTE_PROJECTS = [project(MEDIA, "media", "partially running", 1, 2, False)]

PROXY_FAILED = {"success": False, "data": {"error": 'Proxy request failed: Get "http://agent.example.com:3553/api/environments/0/containers/counts": '
                                                    "dial tcp: lookup agent on 127.0.0.11:53: server misbehaving"}}


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


def environments() -> respx.Route:
    return respx.get(f"{API}/environments").mock(return_value=httpx.Response(200, json=page(ENVIRONMENTS)))


def lists(what: str, local: list[dict[str, Any]], remote: list[dict[str, Any]] | None) -> tuple[respx.Route, respx.Route]:
    first = respx.get(f"{API}/environments/{LOCAL}/{what}").mock(return_value=httpx.Response(200, json=page(local)))
    second = respx.get(f"{API}/environments/{REMOTE}/{what}").mock(
        return_value=httpx.Response(200, json=page(remote)) if remote is not None else httpx.Response(502, json=PROXY_FAILED))
    return first, second


def rows(data: WidgetData) -> list[tuple[str, str, str, list[str]]]:
    return [(row["title"], row["subtitle"], row["status"], [action.id for action in row.get("actions", [])]) for row in data.items]


@respx.mock
async def test_the_test_names_the_version_and_the_environments_the_key_sees(ctx: Context) -> None:
    route = environments()
    respx.get(f"{API}/app-version").mock(return_value=httpx.Response(200, json={"currentVersion": "v2.14.0", "displayVersion": "v2.14.0"}))
    # ⚠️ Typed with the prefix, the prefix is not doubled.
    assert await get_adapter("arcane").test({**CONFIG, "url": f"{AR}/api/"}, ctx) == "Arcane v2.14.0 answers; this key sees 2 environment(s)."
    request = route.calls.last.request
    assert request.headers["X-API-Key"] == "arc_madeupkey"
    # ⚠️ Twenty per page otherwise.
    assert request.url.params["limit"] == "-1"


@respx.mock
async def test_a_wrong_key_is_a_refusal_and_a_web_page_is_not_arcane(ctx: Context) -> None:
    route = respx.get(f"{API}/environments").mock(return_value=httpx.Response(
        401, json={"title": "Unauthorized", "status": 401, "detail": "Unauthorized: invalid API key"}))
    with pytest.raises(AuthFailed, match="rejected the API key"):
        await get_adapter("arcane").fetch("environments", CONFIG, {}, ctx)
    route.mock(return_value=httpx.Response(200, text="<!doctype html><html></html>"))
    with pytest.raises(AdapterError) as caught:
        await get_adapter("arcane").fetch("environments", CONFIG, {}, Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={}))
    assert caught.value.code == "not_arcane"


@respx.mock
async def test_a_missing_permission_is_named(ctx: Context) -> None:
    environments()
    respx.get(f"{API}/environments/{LOCAL}/projects").mock(return_value=httpx.Response(
        403, json={"title": "Forbidden", "status": 403, "detail": "permission denied: projects:list"}))
    respx.get(f"{API}/environments/{REMOTE}/projects").mock(return_value=httpx.Response(
        403, json={"title": "Forbidden", "status": 403, "detail": "permission denied: projects:list"}))
    with pytest.raises(AdapterError, match="lacks the permission projects:list") as caught:
        await get_adapter("arcane").fetch("projects", CONFIG, {}, ctx)
    assert caught.value.code == "forbidden" and "Settings > API keys" in caught.value.hint


@respx.mock
async def test_containers_troubled_first_with_health_from_the_status_text(ctx: Context) -> None:
    environments()
    local, _remote = lists("containers", LOCAL_CONTAINERS, REMOTE_CONTAINERS)
    data = await get_adapter("arcane").fetch("containers", CONFIG, {}, ctx)
    assert local.calls.last.request.url.params["limit"] == "-1"
    assert rows(data) == [
        ("media-who-1", "Exited · traefik/whoami:v1.10 · remote-box", "bad", ["start"]),
        ("sick-sick-1", "Running · Unhealthy · traefik/whoami:v1.10 · Local Docker", "bad", ["stop", "restart"]),
        ("web-site-1", "Running · nginx:1.27-alpine · Local Docker", "ok", ["stop", "restart"]),
        ("web-who-1", "Running · traefik/whoami:v1.10 · Local Docker", "ok", ["stop", "restart"]),
    ]
    assert data.items[0]["actions"][0].params == {"environment": REMOTE, "id": OLD}
    assert data.status == "bad" and data.metrics == {"containers_running": 3.0}
    hidden = await get_adapter("arcane").fetch("containers", CONFIG, {"show_stopped": False}, ctx)
    assert "media-who-1" not in [row["title"] for row in hidden.items]


@respx.mock
async def test_one_environment_is_picked_and_its_name_left_out(ctx: Context) -> None:
    environments()
    local, remote = lists("containers", LOCAL_CONTAINERS, REMOTE_CONTAINERS)
    data = await get_adapter("arcane").fetch("containers", CONFIG, {"environment": REMOTE}, ctx)
    assert rows(data) == [("media-who-1", "Exited · traefik/whoami:v1.10", "bad", ["start"])]
    assert not local.called and remote.called
    with pytest.raises(AdapterError) as caught:
        await get_adapter("arcane").fetch("containers", CONFIG, {"environment": "gone"}, ctx)
    assert caught.value.code == "no_environment"
    assert await get_adapter("arcane").choices("environment", CONFIG, ctx) == [(LOCAL, "Local Docker"), (REMOTE, "remote-box")]


@respx.mock
async def test_an_environment_that_does_not_answer_leaves_the_others_standing(ctx: Context) -> None:
    environments()
    lists("containers", LOCAL_CONTAINERS, None)
    data = await get_adapter("arcane").fetch("containers", CONFIG, {}, ctx)
    assert [row["title"] for row in data.items] == ["sick-sick-1", "web-site-1", "web-who-1"]
    assert data.meta["notice"] == "Some environments did not answer; their rows are missing."
    with pytest.raises(AdapterError) as caught:
        await get_adapter("arcane").fetch("containers", CONFIG, {"environment": REMOTE}, ctx)
    assert caught.value.code == "environment_unreachable"


@respx.mock
async def test_environments_believe_the_answer_not_the_flag(ctx: Context) -> None:
    switched_off = {**ENVIRONMENTS[0], "id": "e3", "name": "old-box", "enabled": False}
    locked = {**ENVIRONMENTS[0], "id": "e4", "name": "locked"}
    respx.get(f"{API}/environments").mock(return_value=httpx.Response(200, json=page([*ENVIRONMENTS, switched_off, locked])))
    respx.get(f"{API}/environments/{LOCAL}/containers/counts").mock(return_value=httpx.Response(
        200, json=envelope({"runningContainers": 3, "stoppedContainers": 1, "totalContainers": 4})))
    # ⚠️ Still "online" in the list, two minutes after its agent stopped.
    respx.get(f"{API}/environments/{REMOTE}/containers/counts").mock(return_value=httpx.Response(502, json=PROXY_FAILED))
    respx.get(f"{API}/environments/e4/containers/counts").mock(return_value=httpx.Response(
        403, json={"success": False, "data": {"error": "You don't have permission to perform this action on this environment"}}))
    data = await get_adapter("arcane").fetch("environments", CONFIG, {}, ctx)
    assert [(row["title"], row["subtitle"], row["status"], row.get("value")) for row in data.items] == [
        ("remote-box", "Not reachable", "bad", None),
        ("locked", "No access", "unknown", None),
        ("old-box", "Switched off", "unknown", None),
        ("Local Docker", "Online", "ok", "3 / 4"),
    ]
    assert data.status == "bad" and data.metrics == {"environments_offline": 1.0}


@respx.mock
async def test_projects_offer_what_their_state_allows(ctx: Context) -> None:
    environments()
    lists("projects", LOCAL_PROJECTS, REMOTE_PROJECTS)
    data = await get_adapter("arcane").fetch("projects", CONFIG, {}, ctx)
    assert rows(data) == [
        ("media", "Partially running · 1/2 · remote-box", "warn", ["up", "down", "redeploy"]),
        ("broken", "Stopped · 0/1 · Local Docker", "unknown", ["up"]),
        ("web", "Running · 2/2 · Local Docker · Update available", "ok", ["down", "redeploy", "update_project"]),
    ]
    assert data.items[2]["actions"][2].params == {"environment": LOCAL, "project": WEB}
    assert data.status == "warn"


@respx.mock
async def test_updates_list_the_containers_arcane_found_newer_images_for(ctx: Context) -> None:
    environments()
    lists("containers", LOCAL_CONTAINERS, REMOTE_CONTAINERS)
    data = await get_adapter("arcane").fetch("updates", CONFIG, {}, ctx)
    assert rows(data) == [("web-site-1", "nginx:1.27-alpine · Local Docker", "warn", ["update"])]
    assert data.items[0]["actions"][0].params == {"environment": LOCAL, "id": SITE}
    assert data.metrics == {"updates_waiting": 1.0} and data.meta["notice"] == ""


@respx.mock
async def test_updates_tell_never_checked_from_nothing_waiting(ctx: Context) -> None:
    environments()
    local, _remote = lists("containers", [container(WHO, "web-who-1", "traefik/whoami:v1.10", "running", "Up", None)], [])
    data = await get_adapter("arcane").fetch("updates", CONFIG, {}, ctx)
    assert (data.status, data.meta["empty"]) == ("unknown", "Arcane has not checked these images for updates yet.")
    local.mock(return_value=httpx.Response(200, json=page([
        container(WHO, "web-who-1", "traefik/whoami:v1.10", "running", "Up", update_info(False, "registry timeout"))])))
    data = await get_adapter("arcane").fetch("updates", CONFIG, {}, Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={}))
    assert (data.status, data.meta["empty"], data.meta["notice"]) == ("ok", "Everything is up to date.", "Arcane could not check some images.")


@respx.mock
async def test_the_overview_adds_up_every_environment(ctx: Context) -> None:
    environments()
    lists("containers", LOCAL_CONTAINERS, REMOTE_CONTAINERS)
    respx.get(f"{API}/environments/{LOCAL}/projects/counts").mock(return_value=httpx.Response(
        200, json=envelope({"runningProjects": 2, "stoppedProjects": 1, "totalProjects": 3, "archivedProjects": 0})))
    respx.get(f"{API}/environments/{REMOTE}/projects/counts").mock(return_value=httpx.Response(
        200, json=envelope({"runningProjects": 0, "stoppedProjects": 1, "totalProjects": 1, "archivedProjects": 0})))
    for env in (LOCAL, REMOTE):
        respx.get(f"{API}/environments/{env}/images/counts").mock(return_value=httpx.Response(
            200, json=envelope({"imagesInuse": 2, "imagesUnused": 0, "totalImages": 2, "totalImageSize": 53783845})))
        respx.get(f"{API}/environments/{env}/volumes/counts").mock(return_value=httpx.Response(200, json=envelope({"inuse": 0, "unused": 1, "total": 1})))
        respx.get(f"{API}/environments/{env}/networks/counts").mock(return_value=httpx.Response(200, json=envelope({"inuse": 2, "unused": 0, "total": 5})))
    # ⚠️ Never asked: it counted an old image nothing used as an update waiting.
    summary = respx.get(f"{API}/environments/{LOCAL}/image-updates/summary")
    data = await get_adapter("arcane").fetch("summary", CONFIG, {}, ctx)
    assert data.primary == {"label": "Containers running", "value": 3, "unit": "/ 4"}
    assert [(row["label"], row["value"]) for row in data.secondary] == [
        ("Unhealthy", 1), ("Projects", "2 / 4"), ("Environments", "2 / 2"), ("Image updates", 1), ("Images", 4), ("Volumes", 2), ("Networks", 10)]
    assert data.status == "bad"
    assert data.metrics == {"containers_running": 3.0, "containers_unhealthy": 1.0, "updates_waiting": 1.0}
    assert not summary.called


@respx.mock
async def test_the_overview_does_not_ask_for_counts_it_does_not_show(ctx: Context) -> None:
    environments()
    lists("containers", LOCAL_CONTAINERS, REMOTE_CONTAINERS)
    for env in (LOCAL, REMOTE):
        respx.get(f"{API}/environments/{env}/projects/counts").mock(return_value=httpx.Response(
            200, json=envelope({"runningProjects": 1, "stoppedProjects": 0, "totalProjects": 1, "archivedProjects": 0})))
    # ⚠️ A key without images:list still fills the card once the count is ticked off.
    images = respx.get(f"{API}/environments/{LOCAL}/images/counts").mock(return_value=httpx.Response(
        403, json={"title": "Forbidden", "status": 403, "detail": "permission denied: images:list"}))
    off = {"show_images": False, "show_volumes": False, "show_networks": False}
    data = await get_adapter("arcane").fetch("summary", CONFIG, off, ctx)
    assert [row["label"] for row in data.secondary] == ["Unhealthy", "Projects", "Environments", "Image updates"]
    assert not images.called


@respx.mock
async def test_container_buttons_reach_their_environment_and_forget_the_old_answer(ctx: Context) -> None:
    route = respx.post(f"{API}/environments/{REMOTE}/containers/{OLD}/start").mock(return_value=httpx.Response(
        200, json=envelope({"message": "Container started successfully", "activityId": "0000"})))
    ctx.cache["resp:stale"] = (float("inf"), None)
    message = await get_adapter("arcane").action("containers", "start", {"environment": REMOTE, "id": OLD}, CONFIG, {}, ctx)
    assert message == "Arcane has started the container."
    assert route.called and route.calls.last.request.headers["X-API-Key"] == "arc_madeupkey"
    assert "resp:stale" not in ctx.cache
    with pytest.raises(AdapterError):
        await get_adapter("arcane").action("containers", "start", {"environment": REMOTE, "id": "../volumes/prune"}, CONFIG, {}, ctx)
    with pytest.raises(AdapterError) as caught:
        await get_adapter("arcane").action("containers", "remove", {"environment": REMOTE, "project": WEB}, CONFIG, {}, ctx)
    assert caught.value.code == "no_such_action"


@respx.mock
async def test_an_update_reports_what_arcane_did_not_what_it_says(ctx: Context) -> None:
    def result(status: str, error: str = "") -> httpx.Response:
        item = {"resourceId": SITE, "resourceName": "web-site-1", "resourceType": "container", "status": status,
                "updateAvailable": status == "updated", "updateApplied": status == "updated", **({"error": error} if error else {})}
        # ⚠️ success is true in every one of them.
        return httpx.Response(200, json=envelope({"success": True, "checked": 1, "updated": int(status == "updated"), "restarted": 0,
                                                   "skipped": int(status == "skipped"), "failed": int(status == "failed"), "items": [item]}))

    route = respx.post(f"{API}/environments/{LOCAL}/containers/{SITE}/update")
    params = {"environment": LOCAL, "id": SITE}
    route.mock(return_value=result("updated"))
    assert await get_adapter("arcane").action("updates", "update", params, CONFIG, {}, ctx) == \
        "Arcane has pulled the new image and recreated the container."
    route.mock(return_value=result("skipped", "image digest unchanged after pull"))
    assert await get_adapter("arcane").action("updates", "update", params, CONFIG, {}, ctx) == "Arcane found nothing newer to update to."
    route.mock(return_value=result("failed", "pull access denied"))
    with pytest.raises(AdapterError, match="could not update the container: pull access denied"):
        await get_adapter("arcane").action("updates", "update", params, CONFIG, {}, ctx)


@respx.mock
async def test_a_failed_start_is_found_inside_the_stream(ctx: Context) -> None:
    lines = [{"type": "activity", "activityId": "0000"},
             {"error": "failed to prepare project images for deploy: failed to pull image registry.example.invalid/nope:1"}]
    respx.post(f"{API}/environments/{LOCAL}/projects/{BROKEN}/up").mock(return_value=httpx.Response(
        200, text="\n".join(json.dumps(line) for line in lines) + "\n", headers={"content-type": "application/x-json-stream"}))
    with pytest.raises(AdapterError, match="could not start the project: failed to prepare project images") as caught:
        await get_adapter("arcane").action("projects", "up", {"environment": LOCAL, "project": BROKEN}, CONFIG, {}, ctx)
    assert caught.value.code == "action_failed"
    good = [{"type": "activity", "activityId": "0000"}, {"log": " Container web-site-1 Healthy "}, {"done": True}]
    respx.post(f"{API}/environments/{LOCAL}/projects/{WEB}/redeploy").mock(return_value=httpx.Response(
        200, text="\n".join(json.dumps(line) for line in good) + "\n", headers={"content-type": "application/x-json-stream"}))
    assert await get_adapter("arcane").action("projects", "redeploy", {"environment": LOCAL, "project": WEB}, CONFIG, {}, ctx) == \
        "Arcane has redeployed the project."


@respx.mock
async def test_stopping_and_updating_a_project(ctx: Context) -> None:
    down = respx.post(f"{API}/environments/{REMOTE}/projects/{MEDIA}/down").mock(return_value=httpx.Response(
        200, json=envelope({"message": "Project brought down successfully", "activityId": "0000"})))
    assert await get_adapter("arcane").action("projects", "down", {"environment": REMOTE, "project": MEDIA}, CONFIG, {}, ctx) == \
        "Arcane has stopped the project."
    assert down.called
    update = respx.post(f"{API}/environments/{LOCAL}/projects/{WEB}/update-services").mock(return_value=httpx.Response(
        200, json=envelope({"message": "Project services updated successfully", "activityId": "0000"})))
    assert await get_adapter("arcane").action("projects", "update_project", {"environment": LOCAL, "project": WEB}, CONFIG, {}, ctx) == \
        "Arcane has pulled the new images and recreated the project."
    # An empty body is every service.
    assert json.loads(update.calls.last.request.content) == {}
    update.mock(return_value=httpx.Response(400, json={"title": "Bad Request", "status": 400, "detail": "Failed to update project: pull access denied"}))
    with pytest.raises(AdapterError, match="Arcane refused: Failed to update project: pull access denied"):
        await get_adapter("arcane").action("projects", "update_project", {"environment": LOCAL, "project": WEB}, CONFIG, {}, ctx)


@pytest.mark.parametrize("kind", ["summary", "environments", "projects", "containers", "updates"])
def test_demo_has_every_card(kind: str) -> None:
    data = get_adapter("arcane").demo(kind, {}, 3)
    assert data.primary or data.items
