"""Dockhand, against the answers of a live Dockhand 1.0.49 (26.09.2026): one engine over TCP, one behind a Hawser agent."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context, WidgetData

DH = "http://dockhand.example.com:3000"
API = f"{DH}/api"
TOKEN = "dh_test-token-for-the-cards"
CONFIG = {"url": DH, "api_token": TOKEN}
DOCKHAND = get_adapter("dockhand")


def environment(identifier: int, name: str, connection: str) -> dict[str, Any]:
    """The list entry as Dockhand 1.0.49 answered it, without the TLS and Hawser fields."""
    return {"id": identifier, "name": name, "host": "10.0.0.10", "port": 2375, "protocol": "http", "icon": "globe", "labels": [],
            "connectionType": connection, "socketPath": "/var/run/docker.sock", "hasTlsKey": False, "hasHawserToken": connection != "direct",
            "publicIp": None, "updateCheckEnabled": False, "updateCheckAutoUpdate": False, "imagePruneEnabled": False, "timezone": "UTC"}


# ⚠️ Dockhand sorts by nothing the cards want: edge-box came before Main.
ENVIRONMENTS = [environment(2, "edge-box", "hawser-standard"), environment(1, "Main", "direct")]


def stat(identifier: int, name: str, *, online: bool = True, total: int, running: int, unhealthy: int = 0, pending: int = 0,
         stacks: tuple[int, int, int] = (0, 0, 0), images: int = 0, volumes: int = 0, networks: int = 0,
         cpu: float = 0.0, memory: float = 0.0) -> dict[str, Any]:
    return {"id": identifier, "name": name, "host": "10.0.0.10", "port": 2375, "icon": "globe", "online": online,
            "connectionType": "direct", "updateCheckEnabled": False, "labels": [],
            "containers": {"total": total, "running": running, "stopped": total - running, "paused": 0, "restarting": 0,
                           "unhealthy": unhealthy, "pendingUpdates": pending},
            "images": {"total": images, "totalSize": 311086108}, "volumes": {"total": volumes, "totalSize": 0}, "networks": {"total": networks},
            "stacks": {"total": sum(stacks), "running": stacks[0], "partial": stacks[1], "stopped": stacks[2]},
            "metrics": {"cpuPercent": cpu, "memoryPercent": memory, "memoryUsed": 19222528, "memoryTotal": 8333950976},
            "events": {"total": 1, "today": 1}, "topContainers": []}


STATS = [
    stat(2, "edge-box", total=2, running=2, stacks=(1, 0, 0), images=2, volumes=1, networks=4, memory=0.1959545004167781),
    stat(1, "Main", total=6, running=4, unhealthy=1, pending=1, stacks=(1, 1, 0), images=3, volumes=1, networks=5,
         cpu=0.0258955223880597, memory=0.23065324064608464),
]


def container(name: str, image: str, state: str, status: str, health: str | None = None, system: str | None = None) -> dict[str, Any]:
    entry = {"id": name.encode().hex().ljust(64, "0")[:64], "name": name, "image": image, "imageId": "sha256:" + "3" * 64,
             "state": state, "status": status, "created": 1790452880, "ports": [], "networks": {}, "restartCount": 0, "mounts": [],
             "labels": {}, "command": "/docker-entrypoint.sh", "systemContainer": system}
    if health:
        entry["health"] = health
    return entry


MAIN_CONTAINERS = [
    container("shop-web-1", "nginx:alpine", "running", "Up 48 seconds"),
    container("shop-cache-1", "redis:7.2", "running", "Up 48 seconds"),
    container("oneshot", "alpine:3.20", "exited", "Exited (0) 57 seconds ago"),
    # ⚠️ Failing its healthcheck and still "running".
    container("sick", "nginx:alpine", "running", "Up 57 seconds (unhealthy)", health="unhealthy"),
]
EDGE_CONTAINERS = [
    container("hawser", "ghcr.io/finsys/hawser:latest", "running", "Up 18 seconds (healthy)", health="healthy", system="hawser"),
    container("edge-proxy-1", "traefik:v3.5", "running", "Up 41 seconds"),
]


def stack(name: str, status: str, states: list[str], updates: bool = False) -> dict[str, Any]:
    return {"name": name, "containers": [f"{name}-{index}" for index in range(len(states))],
            "containerDetails": [{"id": f"{name}-{index}", "name": f"{name}-{index}", "service": f"s{index}", "state": state, "image": "nginx:alpine",
                                  "updateAvailable": updates and index == 0, "newerVersion": None} for index, state in enumerate(states)],
            "updatesAvailable": updates, "updateCount": int(updates), "newerVersionCount": 0, "status": status}


UNAUTHORIZED = {"error": "Unauthorized", "message": "Authentication required"}


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


def environments(answer: list[dict[str, Any]] | None = None) -> respx.Route:
    return respx.get(f"{API}/environments").mock(return_value=httpx.Response(200, json=ENVIRONMENTS if answer is None else answer))


def stats(answer: Any = None, **params: str) -> respx.Route:
    route = respx.get(f"{API}/dashboard/stats", params=params) if params else respx.get(f"{API}/dashboard/stats")
    return route.mock(return_value=httpx.Response(200, json=STATS if answer is None else answer))


def per_environment(path: str, main: Any, edge: Any) -> tuple[respx.Route, respx.Route]:
    first = respx.get(f"{API}{path}", params={"env": "1"}).mock(
        return_value=main if isinstance(main, httpx.Response) else httpx.Response(200, json=main))
    second = respx.get(f"{API}{path}", params={"env": "2"}).mock(
        return_value=edge if isinstance(edge, httpx.Response) else httpx.Response(200, json=edge))
    return first, second


def rows(data: WidgetData) -> list[tuple[str, str, str]]:
    return [(row["title"], row["subtitle"], row["status"]) for row in data.items]


@respx.mock
async def test_the_test_counts_the_environments_and_sends_the_token(ctx: Context) -> None:
    route = environments()
    # ⚠️ Typed with the prefix, the prefix is not doubled.
    assert await DOCKHAND.test({**CONFIG, "url": f"{DH}/api/"}, ctx) == "Dockhand answers and manages 2 environment(s)."
    assert route.calls.last.request.headers["Authorization"] == f"Bearer {TOKEN}"


@respx.mock
async def test_without_a_token_no_header_goes_out(ctx: Context) -> None:
    # Sign-in switched off in Dockhand: everything is open.
    route = environments()
    await DOCKHAND.test({"url": DH, "api_token": "  "}, ctx)
    assert "Authorization" not in route.calls.last.request.headers


@respx.mock
async def test_a_refusal_says_whether_a_token_is_missing_or_wrong(ctx: Context) -> None:
    respx.get(f"{API}/environments").mock(return_value=httpx.Response(401, json=UNAUTHORIZED))
    with pytest.raises(AuthFailed, match="asks for sign-in"):
        await DOCKHAND.test({"url": DH}, ctx)
    with pytest.raises(AuthFailed, match="rejected the API token"):
        await DOCKHAND.test(CONFIG, ctx)


@respx.mock
async def test_the_lock_after_wrong_tokens_is_named(ctx: Context) -> None:
    respx.get(f"{API}/environments").mock(return_value=httpx.Response(429, json={"error": "Too many failed authentication attempts"}))
    with pytest.raises(AdapterError) as caught:
        await DOCKHAND.test(CONFIG, ctx)
    assert caught.value.code == "locked"
    assert "five minutes" in caught.value.hint


@respx.mock
async def test_a_web_page_is_not_dockhand(ctx: Context) -> None:
    respx.get(f"{API}/environments").mock(return_value=httpx.Response(200, text="<!doctype html><title>Dockhand</title>"))
    with pytest.raises(AdapterError) as caught:
        await DOCKHAND.test(CONFIG, ctx)
    assert caught.value.code == "not_dockhand"


@respx.mock
async def test_the_overview_adds_up_every_environment_from_one_request(ctx: Context) -> None:
    route = stats()
    card = await DOCKHAND.fetch("summary", CONFIG, {}, ctx)
    assert route.call_count == 1 and "env" not in route.calls.last.request.url.params
    assert card.primary == {"label": "Containers running", "value": 6, "unit": "/ 8"}
    assert {row["part"]: row["value"] for row in card.secondary} == {
        "unhealthy": 1, "stacks": "2 / 3", "environments": "2 / 2", "updates": 1, "images": 5, "volumes": 2, "networks": 9}
    assert card.status == "bad", "an unhealthy container"
    assert card.metrics == {"containers_running": 6.0, "containers_unhealthy": 1.0, "updates_waiting": 1.0}


@respx.mock
async def test_the_overview_of_one_environment_asks_for_that_one(ctx: Context) -> None:
    route = stats(STATS[0], env="2")
    card = await DOCKHAND.fetch("summary", CONFIG, {"environment": "2"}, ctx)
    assert route.called
    assert card.primary["value"] == 2 and card.status == "ok"


@respx.mock
async def test_environments_with_their_containers_and_load(ctx: Context) -> None:
    stats()
    card = await DOCKHAND.fetch("environments", CONFIG, {}, ctx)
    assert [(row["title"], row["subtitle"], row["value"], row["status"]) for row in card.items] == [
        ("Main", "Online · CPU 0.0 % · Memory 0.2 % · 1 unhealthy", "4 / 6", "warn"),
        ("edge-box", "Online · CPU 0.0 % · Memory 0.2 %", "2 / 2", "ok"),
    ]
    plain = await DOCKHAND.fetch("environments", CONFIG, {"show_usage": False}, ctx)
    assert plain.items[1]["subtitle"] == "Online"


@respx.mock
async def test_containers_troubled_first_and_the_environment_named(ctx: Context) -> None:
    stats()
    per_environment("/containers", MAIN_CONTAINERS, EDGE_CONTAINERS)
    card = await DOCKHAND.fetch("containers", CONFIG, {}, ctx)
    assert rows(card) == [
        ("oneshot", "Exited · alpine:3.20 · Main", "bad"),
        ("sick", "Running · Unhealthy · nginx:alpine · Main", "bad"),
        ("edge-proxy-1", "Running · traefik:v3.5 · edge-box", "ok"),
        ("hawser", "Running · ghcr.io/finsys/hawser:latest · edge-box", "ok"),
        ("shop-cache-1", "Running · redis:7.2 · Main", "ok"),
        ("shop-web-1", "Running · nginx:alpine · Main", "ok"),
    ]
    assert card.status == "bad"
    assert card.metrics == {"containers_running": 5.0}
    running = await DOCKHAND.fetch("containers", CONFIG, {"show_stopped": False}, ctx)
    assert "oneshot" not in [row["title"] for row in running.items]
    assert running.metrics == {"containers_running": 5.0}, "hidden, still counted"


@respx.mock
async def test_one_environment_is_picked_and_its_name_left_out(ctx: Context) -> None:
    # ⚠️ One environment comes back as the object, not a list of one.
    stats(STATS[0], env="2")
    main, edge = per_environment("/containers", MAIN_CONTAINERS, EDGE_CONTAINERS)
    card = await DOCKHAND.fetch("containers", CONFIG, {"environment": "2"}, ctx)
    assert not main.called and edge.called
    assert [row["subtitle"] for row in card.items] == ["Running · traefik:v3.5", "Running · ghcr.io/finsys/hawser:latest"]


@respx.mock
async def test_an_environment_that_is_gone_from_dockhand_is_said(ctx: Context) -> None:
    respx.get(f"{API}/dashboard/stats", params={"env": "9"}).mock(return_value=httpx.Response(404, json={"error": "Environment not found"}))
    with pytest.raises(AdapterError) as caught:
        await DOCKHAND.fetch("containers", CONFIG, {"environment": "9"}, ctx)
    assert caught.value.code == "no_environment"


DOWN = dict(stat(2, "edge-box", online=False, total=0, running=0), error="DockerConnectionError: Connection error", metrics=None)


@respx.mock
async def test_an_environment_dockhand_cannot_reach_is_left_out_not_drawn_empty(ctx: Context) -> None:
    # ⚠️ Its lists answer 200 and nothing, like an empty engine.
    stats([DOWN, STATS[1]])
    main, edge = per_environment("/containers", MAIN_CONTAINERS, [])
    card = await DOCKHAND.fetch("containers", CONFIG, {}, ctx)
    assert main.called and not edge.called
    assert card.meta["notice"] == "Some environments did not answer; their rows are missing."
    assert card.items[0]["subtitle"].endswith("· Main"), "the environment still named: more than one is covered"


@respx.mock
async def test_a_picked_environment_that_cannot_be_reached_says_so(ctx: Context) -> None:
    stats(DOWN, env="2")
    _main, edge = per_environment("/stacks", [], [])
    with pytest.raises(AdapterError) as caught:
        await DOCKHAND.fetch("stacks", CONFIG, {"environment": "2"}, ctx)
    assert caught.value.code == "environment_unreachable" and not edge.called


@respx.mock
async def test_offline_environments_on_the_cards_that_read_the_stats(ctx: Context) -> None:
    stats([DOWN, STATS[1]])
    places = await DOCKHAND.fetch("environments", CONFIG, {}, ctx)
    assert [(row["title"], row["subtitle"], row["status"]) for row in places.items][0] == ("edge-box", "Not reachable", "bad")
    assert places.status == "bad" and places.metrics == {"environments_offline": 1.0}
    overview = await DOCKHAND.fetch("summary", CONFIG, {}, ctx)
    assert {row["part"]: row["value"] for row in overview.secondary}["environments"] == "1 / 2"
    assert overview.status == "bad"


@respx.mock
async def test_stacks_with_their_state_and_how_many_run(ctx: Context) -> None:
    stats()
    per_environment("/stacks", [stack("shop", "running", ["running", "running"], updates=True),
                                stack("notes", "partial", ["running", "exited"])],
                    [stack("edge", "running", ["running"])])
    card = await DOCKHAND.fetch("stacks", CONFIG, {}, ctx)
    assert rows(card) == [
        ("notes", "Partially running · 1/2 · Main", "warn"),
        ("edge", "Running · 1/1 · edge-box", "ok"),
        ("shop", "Running · 2/2 · Main · Update available", "ok"),
    ]
    assert card.status == "warn"


@respx.mock
async def test_updates_list_what_dockhand_recorded(ctx: Context) -> None:
    stats()
    per_environment("/containers/pending-updates",
                    {"environmentId": 1, "pendingUpdates": [{"containerId": "6cc9" * 16, "containerName": "shop-cache-1", "currentImage": "redis:7.2",
                                                             "checkedAt": "2026-09-26T20:02:06.151Z", "hasImageUpdate": True, "newerVersion": None}]},
                    {"environmentId": 2, "pendingUpdates": []})
    card = await DOCKHAND.fetch("updates", CONFIG, {}, ctx)
    assert rows(card) == [("shop-cache-1", "redis:7.2 · Main", "warn")]
    assert card.metrics == {"updates_waiting": 1.0}


@respx.mock
async def test_no_update_is_not_up_to_date_while_nobody_checks(ctx: Context) -> None:
    # ⚠️ The scheduled check is off by default: an empty list proves nothing.
    route = stats()
    per_environment("/containers/pending-updates", {"environmentId": 1, "pendingUpdates": []}, {"environmentId": 2, "pendingUpdates": []})
    card = await DOCKHAND.fetch("updates", CONFIG, {}, ctx)
    assert card.items == [] and card.status == "unknown"
    assert card.meta["empty"].startswith("No update recorded.")
    route.mock(return_value=httpx.Response(200, json=[STATS[0], {**STATS[1], "updateCheckEnabled": True}]))
    checked = await DOCKHAND.fetch("updates", CONFIG, {}, Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={}))
    assert checked.status == "ok" and checked.meta["empty"] == "Everything is up to date, as Dockhand last checked."


@pytest.mark.parametrize("kind", [widget.kind for widget in DOCKHAND.widgets])
def test_demo_has_every_card(kind: str) -> None:
    for tick in range(4):
        card = DOCKHAND.demo(kind, {}, tick)
        assert card.items or card.primary
