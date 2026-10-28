"""Garage. The fixtures were recorded on 27.10.2026 from Garage 2.1.0 and from
Garage 1.3.1, one node each (``garage_v2_*`` and ``garage_v1_*``); the keys,
tokens and names are made up. The bucket "backups" has a quota of 5 GiB and
three objects of 3 MB, "media" one object of 3 MB and no quota."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context, Unreachable, outbound_client

FIXTURES = Path(__file__).parent / "fixtures"
CONFIG = {"url": "http://garage:3903", "token": "example-admin-token"}
BASE = "http://garage:3903"
UNKNOWN = {"code": "InvalidRequest", "message": "Bad request: Unknown API endpoint: GET /v2/x", "region": "garage"}


def recorded(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def ctx() -> Context:
    return Context(outbound_client(guard=False), integration_id=1, widget_id=1, cache={})


def garage_two() -> None:
    respx.get(f"{BASE}/v2/GetClusterHealth").mock(return_value=httpx.Response(200, json=recorded("garage_v2_health.json")))
    respx.get(f"{BASE}/v2/GetClusterStatus").mock(return_value=httpx.Response(200, json=recorded("garage_v2_status.json")))
    respx.get(f"{BASE}/v2/GetClusterLayout").mock(return_value=httpx.Response(200, json=recorded("garage_v2_layout.json")))
    respx.get(f"{BASE}/v2/ListBuckets").mock(return_value=httpx.Response(200, json=recorded("garage_v2_buckets.json")))
    for alias in ("backups", "media"):
        info = recorded(f"garage_v2_bucket_{alias}.json")
        respx.get(f"{BASE}/v2/GetBucketInfo", params={"id": info["id"]}).mock(return_value=httpx.Response(200, json=info))


def garage_one() -> None:
    """Garage 1 answers a /v2 path with 400 Unknown API endpoint, as recorded."""
    respx.get(url__regex=rf"{BASE}/v2/.*").mock(return_value=httpx.Response(400, json=UNKNOWN))
    respx.get(f"{BASE}/v1/health").mock(return_value=httpx.Response(200, json=recorded("garage_v1_health.json")))
    respx.get(f"{BASE}/v1/status").mock(return_value=httpx.Response(200, json=recorded("garage_v1_status.json")))
    respx.get(f"{BASE}/v1/layout").mock(return_value=httpx.Response(200, json=recorded("garage_v1_layout.json")))
    respx.get(f"{BASE}/v1/bucket", params={"list": ""}).mock(return_value=httpx.Response(200, json=recorded("garage_v1_buckets.json")))
    info = recorded("garage_v1_bucket_backups.json")
    respx.get(f"{BASE}/v1/bucket", params={"id": info["id"]}).mock(return_value=httpx.Response(200, json=info))


@respx.mock
async def test_the_cluster_card_of_garage_two_counts_the_storage_nodes_up(ctx: Context) -> None:
    garage_two()
    data = await get_adapter("garage").fetch("cluster", CONFIG, {}, ctx)
    assert data.status == "ok"
    assert data.primary == {"label": "Nodes up", "value": 1}
    assert data.secondary == [{"label": "Status", "value": "Healthy"}, {"label": "Storage nodes", "value": 1}]
    assert data.metrics == {"nodes_up": 1.0, "partitions_short": 0.0}
    assert respx.calls.last.request.headers["Authorization"] == "Bearer example-admin-token"


@respx.mock
async def test_garage_one_is_found_by_its_400_and_read_the_same_way(ctx: Context) -> None:
    garage_one()
    data = await get_adapter("garage").fetch("cluster", CONFIG, {}, ctx)
    # Garage 1 names the count storageNodesOk where Garage 2 says storageNodesUp.
    assert data.primary == {"label": "Nodes up", "value": 1}
    assert ctx.cache["garage.generation"] == "v1"


@respx.mock
async def test_a_degraded_cluster_is_yellow_and_names_the_partitions_short_of_copies(ctx: Context) -> None:
    garage_two()
    health = {**recorded("garage_v2_health.json"), "status": "degraded", "storageNodes": 3, "storageNodesUp": 2, "partitionsAllOk": 170}
    respx.get(f"{BASE}/v2/GetClusterHealth").mock(return_value=httpx.Response(200, json=health))
    data = await get_adapter("garage").fetch("cluster", CONFIG, {}, ctx)
    assert data.status == "warn"
    assert data.primary["value"] == 2
    assert {"label": "Partitions short of copies", "value": 86} in data.secondary
    assert data.metrics["partitions_short"] == 86.0


@respx.mock
async def test_an_unavailable_cluster_is_red(ctx: Context) -> None:
    garage_two()
    health = {**recorded("garage_v2_health.json"), "status": "unavailable", "storageNodesUp": 0}
    respx.get(f"{BASE}/v2/GetClusterHealth").mock(return_value=httpx.Response(200, json=health))
    data = await get_adapter("garage").fetch("cluster", CONFIG, {}, ctx)
    assert data.status == "bad"
    assert data.secondary[0] == {"label": "Status", "value": "Unavailable"}


@respx.mock
async def test_a_layout_change_that_waits_turns_a_healthy_cluster_yellow(ctx: Context) -> None:
    garage_two()
    layout = {**recorded("garage_v2_layout.json"), "stagedRoleChanges": [{"id": "ab12", "zone": "dc2", "capacity": 1, "tags": []}]}
    respx.get(f"{BASE}/v2/GetClusterLayout").mock(return_value=httpx.Response(200, json=layout))
    data = await get_adapter("garage").fetch("cluster", CONFIG, {}, ctx)
    assert data.status == "warn"
    assert {"label": "Layout changes waiting", "value": 1} in data.secondary


@respx.mock
async def test_the_nodes_card_gives_zone_capacity_and_free_space(ctx: Context) -> None:
    garage_two()
    data = await get_adapter("garage").fetch("nodes", CONFIG, {}, ctx)
    row = data.items[0]
    assert row["title"] == "6368dbdb357e"
    assert row["subtitle"] == "Zone dc1 · 10.0 GB · 177.4 GB free"
    assert (row["status"], row["value"]) == ("ok", "Up")
    assert data.secondary == [{"label": "Storage nodes", "value": 1}]


@respx.mock
async def test_a_node_that_is_down_comes_first_and_is_red(ctx: Context) -> None:
    status = recorded("garage_v2_status.json")
    second = {**status["nodes"][0], "id": "ff", "hostname": "garage-2", "isUp": False, "lastSeenSecsAgo": 900}
    status["nodes"].append(second)
    garage_two()
    respx.get(f"{BASE}/v2/GetClusterStatus").mock(return_value=httpx.Response(200, json=status))
    data = await get_adapter("garage").fetch("nodes", CONFIG, {}, ctx)
    assert [(row["title"], row["status"], row["value"]) for row in data.items] == [
        ("garage-2", "bad", "Down"), ("6368dbdb357e", "ok", "Up")]
    assert data.status == "bad"


@respx.mock
async def test_a_node_whose_data_disk_is_nearly_full_is_red_and_a_draining_one_yellow(ctx: Context) -> None:
    status = recorded("garage_v2_status.json")
    status["nodes"][0]["dataPartition"] = {"available": 20 * 1024 ** 3, "total": 1000 * 1024 ** 3}
    draining = {**status["nodes"][0], "id": "ee", "hostname": "garage-3", "draining": True,
                "dataPartition": {"available": 500 * 1024 ** 3, "total": 1000 * 1024 ** 3}}
    status["nodes"].append(draining)
    garage_two()
    respx.get(f"{BASE}/v2/GetClusterStatus").mock(return_value=httpx.Response(200, json=status))
    data = await get_adapter("garage").fetch("nodes", CONFIG, {}, ctx)
    assert [(row["status"], row["value"]) for row in data.items] == [("bad", "Up"), ("warn", "Draining")]


@respx.mock
async def test_the_buckets_card_reads_each_bucket_and_shows_the_quota_used(ctx: Context) -> None:
    garage_two()
    data = await get_adapter("garage").fetch("buckets", CONFIG, {}, ctx)
    rows = {row["title"]: row for row in data.items}
    assert rows["backups"]["subtitle"] == "8.6 MB of 5.0 GB" and rows["backups"]["value"] == 3
    assert rows["media"]["subtitle"] == "2.9 MB" and rows["media"]["value"] == 1
    assert data.secondary == [{"label": "Buckets", "value": 2}]
    assert data.status == "ok"


@respx.mock
async def test_a_bucket_near_its_quota_is_yellow_then_red(ctx: Context) -> None:
    garage_two()
    info = recorded("garage_v2_bucket_backups.json")
    info["quotas"] = {"maxSize": 10_000_000, "maxObjects": None}
    respx.get(f"{BASE}/v2/GetBucketInfo", params={"id": info["id"]}).mock(return_value=httpx.Response(200, json=info))
    data = await get_adapter("garage").fetch("buckets", CONFIG, {}, ctx)
    assert data.items[0]["title"] == "backups" and data.items[0]["status"] == "warn"
    info["quotas"] = {"maxSize": 9_000_001, "maxObjects": 3}
    ctx.cache.clear()
    garage_two()
    respx.get(f"{BASE}/v2/GetBucketInfo", params={"id": info["id"]}).mock(return_value=httpx.Response(200, json=info))
    data = await get_adapter("garage").fetch("buckets", CONFIG, {}, ctx)
    assert data.items[0]["status"] == "bad"


@respx.mock
async def test_the_storage_card_adds_the_buckets_and_names_the_fullest_disk(ctx: Context) -> None:
    garage_two()
    data = await get_adapter("garage").fetch("storage", CONFIG, {}, ctx)
    assert data.primary == {"label": "Stored", "value": "11.4 MB"}
    assert {"label": "Objects", "value": 4} in data.secondary
    assert {"label": "Fullest data disk", "value": 63.9, "unit": "%"} in data.secondary
    assert data.metrics == {"stored_bytes": 12_000_000.0, "objects": 4.0}


@respx.mock
async def test_garage_one_lists_its_buckets_through_the_older_calls(ctx: Context) -> None:
    garage_one()
    data = await get_adapter("garage").fetch("buckets", CONFIG, {}, ctx)
    assert [(row["title"], row["value"]) for row in data.items] == [("backups", 0)]


@respx.mock
async def test_after_an_update_from_garage_one_to_two_the_choice_is_made_again(ctx: Context) -> None:
    ctx.cache["garage.generation"] = "v1"
    respx.get(url__regex=rf"{BASE}/v1/.*").mock(return_value=httpx.Response(400, json={**UNKNOWN, "message": "Bad request: Unknown API endpoint: GET /v1/layout"}))
    garage_two()
    data = await get_adapter("garage").fetch("cluster", CONFIG, {}, ctx)
    assert data.primary["value"] == 1
    assert ctx.cache["garage.generation"] == "v2"


@respx.mock
async def test_the_connection_test_names_the_version_and_the_nodes(ctx: Context) -> None:
    garage_two()
    assert await get_adapter("garage").test(CONFIG, ctx) == "Garage v2.1.0 answers, 1 of 1 storage nodes up."
    assert await get_adapter("garage").running_version(CONFIG, ctx) == "2.1.0"


@respx.mock
async def test_a_wrong_token_is_an_authentication_failure(ctx: Context) -> None:
    respx.get(f"{BASE}/v2/GetClusterHealth").mock(return_value=httpx.Response(403, json={"code": "AccessDenied"}))
    with pytest.raises(AuthFailed):
        await get_adapter("garage").fetch("cluster", CONFIG, {}, ctx)


@respx.mock
async def test_the_s3_port_instead_of_the_admin_port_says_so(ctx: Context) -> None:
    respx.get(url__regex=rf"{BASE}/.*").mock(return_value=httpx.Response(400, text="<Error><Code>InvalidRequest</Code></Error>"))
    with pytest.raises(AdapterError) as failure:
        await get_adapter("garage").fetch("cluster", CONFIG, {}, ctx)
    assert failure.value.code == "http_error"


@respx.mock
async def test_neither_generation_known_is_said_so(ctx: Context) -> None:
    respx.get(url__regex=rf"{BASE}/.*").mock(return_value=httpx.Response(404, text="not found"))
    with pytest.raises(AdapterError) as failure:
        await get_adapter("garage").fetch("cluster", CONFIG, {}, ctx)
    assert failure.value.code == "no_admin_api"


@respx.mock
async def test_an_unreachable_garage_is_unreachable(ctx: Context) -> None:
    respx.get(f"{BASE}/v2/GetClusterHealth").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(Unreachable):
        await get_adapter("garage").fetch("cluster", CONFIG, {}, ctx)


@respx.mock
async def test_the_fullest_data_disk_colours_the_storage_card(ctx: Context) -> None:
    status = recorded("garage_v2_status.json")
    status["nodes"][0]["dataPartition"] = {"available": 10 * 1024 ** 3, "total": 1000 * 1024 ** 3}
    garage_two()
    respx.get(f"{BASE}/v2/GetClusterStatus").mock(return_value=httpx.Response(200, json=status))
    data = await get_adapter("garage").fetch("storage", CONFIG, {}, ctx)
    assert data.status == "bad"
    assert {"label": "Fullest data disk", "value": 99.0, "unit": "%"} in data.secondary


@respx.mock
async def test_a_quota_on_objects_alone_counts_as_well(ctx: Context) -> None:
    garage_two()
    info = recorded("garage_v2_bucket_backups.json")
    info["quotas"] = {"maxSize": None, "maxObjects": 3}
    respx.get(f"{BASE}/v2/GetBucketInfo", params={"id": info["id"]}).mock(return_value=httpx.Response(200, json=info))
    data = await get_adapter("garage").fetch("buckets", CONFIG, {}, ctx)
    assert (data.items[0]["title"], data.items[0]["status"]) == ("backups", "bad")


@respx.mock
async def test_the_admin_token_travels_with_every_call_including_the_bucket_ones(ctx: Context) -> None:
    garage_two()
    await get_adapter("garage").fetch("buckets", CONFIG, {}, ctx)
    sent = {call.request.headers.get("Authorization") for call in respx.calls}
    assert sent == {"Bearer example-admin-token"}
    assert len(respx.calls) == 4  # health, the list, two buckets


@respx.mock
async def test_a_bucket_id_that_climbs_out_of_the_path_is_refused(ctx: Context) -> None:
    garage_two()
    respx.get(f"{BASE}/v2/ListBuckets").mock(return_value=httpx.Response(200, json=[{"id": "../ClusterLayout", "globalAliases": ["x"]}]))
    with pytest.raises(AdapterError) as failure:
        await get_adapter("garage").fetch("buckets", CONFIG, {}, ctx)
    assert failure.value.code == "bad_param"
