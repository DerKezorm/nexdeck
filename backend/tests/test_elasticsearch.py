"""Elasticsearch and OpenSearch, against the answers of a live Elasticsearch 9.5.3 and OpenSearch 3.8.0 (26.09.2026)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context

ES = "https://search.example.com:9200"
KEY = "dGVzdC1rZXktZm9yLXRoZS1jYXJkcw=="
CONFIG = {"url": ES, "api_key": KEY}
USER = {"url": ES, "username": "nexdeck", "password": "a-password-for-the-cards"}
ADAPTER = get_adapter("elasticsearch")

ROOT_ES = {"name": "es-1", "cluster_name": "docker-cluster", "cluster_uuid": "xDMFiEqEQTiBJDCI7zjwfw",
           "version": {"number": "9.5.3", "build_flavor": "default", "build_type": "docker", "lucene_version": "10.5.1"},
           "tagline": "You Know, for Search"}
ROOT_OS = {"name": "os-1", "cluster_name": "docker-cluster", "cluster_uuid": "Ir2_NdBZRQmDQDnAz0nHSw",
           "version": {"distribution": "opensearch", "number": "3.8.0", "build_type": "tar", "lucene_version": "10.5.0"},
           "tagline": "The OpenSearch Project: https://opensearch.org/"}


def health(status: str, *, nodes: int = 1, unassigned: int = 0, unassigned_primary: int | None = 0, active: float = 100.0) -> dict[str, Any]:
    answer = {"cluster_name": "docker-cluster", "status": status, "timed_out": False, "number_of_nodes": nodes, "number_of_data_nodes": nodes,
              "active_primary_shards": 7, "active_shards": 7, "relocating_shards": 0, "initializing_shards": 0, "unassigned_shards": unassigned,
              "delayed_unassigned_shards": 0, "number_of_pending_tasks": 0, "number_of_in_flight_fetch": 0,
              "task_max_waiting_in_queue_millis": 0, "active_shards_percent_as_number": active}
    # ⚠️ OpenSearch has no count of unassigned primaries.
    if unassigned_primary is not None:
        answer["unassigned_primary_shards"] = unassigned_primary
    return answer


RED = health("red", unassigned=2, unassigned_primary=1, active=77.77777777777779)
STATS = {"status": "red", "indices": {"count": 6, "docs": {"count": 62, "deleted": 0}, "store": {"size_in_bytes": 114913}},
         "nodes": {"count": {"total": 1}, "versions": ["9.5.3"]}}


def index(name: str, health_: str, docs: str | None, size: str | None, status: str = "open") -> dict[str, Any]:
    return {"health": health_, "status": status, "index": name, "docs.count": docs, "store.size": size, "pri": "1", "rep": "0"}


# As Elasticsearch 9.5.3 answered, strings and nulls included.
INDICES = [
    index("shop-orders", "yellow", "5", "4278"),
    index("logs-web", "green", "20", "12698"),
    # ⚠️ Closed, and called green.
    index("archive-2025", "green", None, None, status="close"),
    index("broken-index", "red", None, None),
]
HIDDEN = [index(".ds-ilm-history-7-2026.09.26-000001", "green", "3", "20753")]


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


@respx.mock
async def test_the_test_names_the_product_and_sends_the_key(ctx: Context) -> None:
    root = respx.get(f"{ES}/").mock(return_value=httpx.Response(200, json=ROOT_ES))
    respx.get(f"{ES}/_cluster/health").mock(return_value=httpx.Response(200, json=RED))
    # Pasted with the word in front, as the documentation writes it.
    said = await ADAPTER.test({**CONFIG, "api_key": f"ApiKey {KEY}"}, ctx)
    assert said == "Elasticsearch 9.5.3 answers; cluster docker-cluster is red, with 1 node(s)."
    assert root.calls.last.request.headers["Authorization"] == f"ApiKey {KEY}"


@respx.mock
async def test_opensearch_is_named_and_signed_in_with_a_user(ctx: Context) -> None:
    root = respx.get(f"{ES}/").mock(return_value=httpx.Response(200, json=ROOT_OS))
    respx.get(f"{ES}/_cluster/health").mock(return_value=httpx.Response(200, json=health("yellow", unassigned_primary=None)))
    assert (await ADAPTER.test(USER, ctx)).startswith("OpenSearch 3.8.0 answers")
    assert root.calls.last.request.headers["Authorization"].startswith("Basic ")


@respx.mock
async def test_refusals_say_what_is_wrong(ctx: Context) -> None:
    route = respx.get(f"{ES}/")
    # ⚠️ OpenSearch answers a wrong password in plain text.
    route.mock(return_value=httpx.Response(401, text="Unauthorized"))
    with pytest.raises(AuthFailed, match="user or the password"):
        await ADAPTER.test(USER, ctx)
    with pytest.raises(AuthFailed, match="rejected the API key"):
        await ADAPTER.test(CONFIG, ctx)
    with pytest.raises(AuthFailed, match="asks for sign-in"):
        await ADAPTER.test({"url": ES}, ctx)


@respx.mock
@pytest.mark.parametrize("reason", [
    "action [cluster:monitor/main] is unauthorized for API key id [XC5536ABKXJ65ixRojXT] of user [elastic], "
    "this action is granted by the cluster privileges [monitor,manage,all]",
    "no permissions for [cluster:monitor/main] and User [name=nobody, backend_roles=[], requestedTenant=null]",
])
async def test_a_missing_privilege_is_named_in_both_dialects(ctx: Context, reason: str) -> None:
    respx.get(f"{ES}/").mock(return_value=httpx.Response(403, json={"error": {"type": "security_exception", "reason": reason}, "status": 403}))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.test(CONFIG, ctx)
    assert caught.value.code == "forbidden"
    assert caught.value.message == "The cluster refuses the right cluster:monitor/main."
    assert "monitor" in caught.value.hint


async def test_a_key_and_a_user_at_once_is_refused_before_asking(ctx: Context) -> None:
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.fetch("cluster", {**CONFIG, "username": "elastic"}, {}, ctx)
    assert caught.value.code == "two_ways_in"


@respx.mock
async def test_the_cluster_card_counts_and_colours(ctx: Context) -> None:
    respx.get(f"{ES}/_cluster/health").mock(return_value=httpx.Response(200, json=RED))
    respx.get(f"{ES}/_cluster/stats").mock(return_value=httpx.Response(200, json=STATS))
    card = await ADAPTER.fetch("cluster", CONFIG, {}, ctx)
    assert card.status == "bad" and card.primary == {"label": "Cluster health", "value": "Red"}
    assert {row["part"]: row["value"] for row in card.secondary} == {
        "nodes": 1, "indices": 6, "documents": "62", "size": "112.2 KB", "unassigned": 2, "active": "78 %"}
    assert card.metrics == {"unassigned_shards": 2.0, "documents": 62.0}


@respx.mock
async def test_yellow_on_a_single_node_is_calm_and_says_why(ctx: Context) -> None:
    respx.get(f"{ES}/_cluster/health").mock(return_value=httpx.Response(200, json=health("yellow", unassigned=1)))
    respx.get(f"{ES}/_cluster/stats").mock(return_value=httpx.Response(200, json=STATS))
    card = await ADAPTER.fetch("cluster", CONFIG, {}, ctx)
    assert card.status == "ok" and card.primary["value"] == "Yellow"
    assert card.meta["status_reason"] == "Replicas have nowhere to go on a single node."
    respx.get(f"{ES}/_cluster/health").mock(return_value=httpx.Response(200, json=health("yellow", nodes=3, unassigned=1)))
    three = await ADAPTER.fetch("cluster", CONFIG, {}, Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={}))
    assert three.status == "warn", "on three nodes a replica has somewhere to go"


@respx.mock
async def test_the_cluster_card_leaves_the_stats_alone_when_it_shows_none_of_them(ctx: Context) -> None:
    respx.get(f"{ES}/_cluster/health").mock(return_value=httpx.Response(200, json=RED))
    stats = respx.get(f"{ES}/_cluster/stats").mock(return_value=httpx.Response(200, json=STATS))
    await ADAPTER.fetch("cluster", CONFIG, {"show_indices": False, "show_documents": False, "show_size": False}, ctx)
    assert not stats.called


@respx.mock
async def test_indices_troubled_first_then_largest_closed_last(ctx: Context) -> None:
    respx.get(f"{ES}/_cluster/health").mock(return_value=httpx.Response(200, json=RED))
    route = respx.get(f"{ES}/_cat/indices").mock(return_value=httpx.Response(200, json=INDICES))
    card = await ADAPTER.fetch("indices", CONFIG, {}, ctx)
    assert [(row["title"], row["subtitle"], row.get("value"), row["status"]) for row in card.items] == [
        ("broken-index", "Red, a primary shard has no home", "", "bad"),
        ("logs-web", "20 documents", "12.4 KB", "ok"),
        # ⚠️ One node: its replica can never be placed.
        ("shop-orders", "No room for a replica · 5 documents", "4.2 KB", "ok"),
        ("archive-2025", "Closed", None, "unknown"),
    ]
    assert card.status == "bad"
    assert "expand_wildcards" not in route.calls.last.request.url.params


@respx.mock
async def test_system_indices_only_when_asked(ctx: Context) -> None:
    respx.get(f"{ES}/_cluster/health").mock(return_value=httpx.Response(200, json=health("green", nodes=3)))
    route = respx.get(f"{ES}/_cat/indices").mock(return_value=httpx.Response(200, json=[*INDICES[:2], *HIDDEN]))
    plain = await ADAPTER.fetch("indices", CONFIG, {}, ctx)
    assert ".ds-ilm-history-7-2026.09.26-000001" not in [row["title"] for row in plain.items]
    everything = await ADAPTER.fetch("indices", CONFIG, {"show_system": True}, Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={}))
    assert ".ds-ilm-history-7-2026.09.26-000001" in [row["title"] for row in everything.items]
    # ⚠️ Elasticsearch hides them otherwise.
    assert route.calls.last.request.url.params["expand_wildcards"] == "all"
    # On three nodes a yellow index is yellow.
    assert plain.items[0] == {"title": "shop-orders", "subtitle": "Yellow · 5 documents", "value": "4.2 KB", "status": "warn"}


@respx.mock
async def test_the_limit_cuts_the_list(ctx: Context) -> None:
    respx.get(f"{ES}/_cluster/health").mock(return_value=httpx.Response(200, json=RED))
    respx.get(f"{ES}/_cat/indices").mock(return_value=httpx.Response(200, json=INDICES))
    card = await ADAPTER.fetch("indices", CONFIG, {"limit": 2}, ctx)
    assert [row["title"] for row in card.items] == ["broken-index", "logs-web"]


@respx.mock
async def test_nodes_with_disk_heap_and_processor(ctx: Context) -> None:
    respx.get(f"{ES}/_cat/nodes").mock(return_value=httpx.Response(200, json=[
        {"name": "es-1", "node.role": "cdfhilmrstw", "master": "*", "heap.percent": "29", "cpu": "6", "load_1m": "0.34",
         "disk.used_percent": "29.59", "version": "9.5.3"},
        {"name": "es-2", "node.role": "dimr", "master": "-", "heap.percent": "40", "cpu": "3", "load_1m": "0.1",
         "disk.used_percent": "91.2", "version": "9.5.3"},
    ]))
    card = await ADAPTER.fetch("nodes", CONFIG, {}, ctx)
    assert [(row["title"], row["subtitle"], row["value"], row["status"]) for row in card.items] == [
        ("es-2", "Disk 91 % · Heap 40 % · CPU 3 %", "9.5.3", "bad"),
        ("es-1", "Leads the cluster · Disk 30 % · Heap 29 % · CPU 6 %", "9.5.3", "ok"),
    ]
    assert card.status == "bad"
    quiet = await ADAPTER.fetch("nodes", CONFIG, {"show_heap": False, "show_cpu": False}, ctx)
    assert quiet.items[1]["subtitle"] == "Leads the cluster · Disk 30 %"


@respx.mock
async def test_a_web_page_is_not_a_cluster(ctx: Context) -> None:
    respx.get(f"{ES}/").mock(return_value=httpx.Response(200, text="<!doctype html><title>Kibana</title>"))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.test(CONFIG, ctx)
    assert caught.value.code == "not_elasticsearch"


@pytest.mark.parametrize("kind", [widget.kind for widget in ADAPTER.widgets])
def test_demo_has_every_card(kind: str) -> None:
    for tick in range(4):
        card = ADAPTER.demo(kind, {}, tick)
        assert card.items or card.primary
