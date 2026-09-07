"""One container, one guest: the card for a single one.

⚠️ Five services answer this card, and they answer it differently. Docker and
Portainer know the network counters; DSM does not; the VM manager does not
even give a CPU load. The point of the shared shape is that a row nobody
measured is *absent*, never a zero: a zero on a card whose whole job is to say
how one thing is doing reads as "measured, and fine", which is the worst thing
it could say.

The other half is what happens when the thing is gone. A container keeps its
name and gets a new id every time it is rebuilt, so these cards hold on to the
name; a name that is no longer there has to say so rather than draw an empty
card.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, Context

ENGINE = "http://docker.example.com:2375"
NAS = "https://nas.example.com:5001"
PVE = "https://pve.example.com:8006"


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})

RUNNING = {
    "Id": "abc123def456", "Names": ["/jellyfin"], "State": "running",
    "Status": "Up 3 days", "Image": "jellyfin/jellyfin:latest",
}
STOPPED = {"Id": "dead00beef11", "Names": ["/backup"], "State": "exited", "Status": "Exited (0) 5 months ago", "Image": "restic/restic"}
STATS = {
    "cpu_stats": {"cpu_usage": {"total_usage": 2_000_000}, "system_cpu_usage": 20_000_000, "online_cpus": 4},
    "precpu_stats": {"cpu_usage": {"total_usage": 1_000_000}, "system_cpu_usage": 10_000_000},
    "memory_stats": {"usage": 500_000_000, "limit": 2_000_000_000, "stats": {"inactive_file": 100_000_000}},
    "networks": {"eth0": {"rx_bytes": 2_100_000_000, "tx_bytes": 400_000_000}},
    "blkio_stats": {"io_service_bytes_recursive": [{"op": "Read", "value": 320_000_000}, {"op": "Write", "value": 1_800_000_000}]},
    "pids_stats": {"current": 31},
}
DOCKER = {"host": ENGINE, "insecure": False}


def _labels(data) -> list[str]:
    return [str(row.get("label")) for row in data.secondary]


def _value(data, label: str):
    return next((row.get("value") for row in data.secondary if row.get("label") == label), None)


@respx.mock
async def test_docker_gives_everything_it_has(ctx: Context) -> None:
    respx.get(f"{ENGINE}/containers/json").mock(return_value=httpx.Response(200, json=[RUNNING, STOPPED]))
    respx.get(f"{ENGINE}/containers/{RUNNING['Id']}/stats").mock(return_value=httpx.Response(200, json=STATS))

    data = await get_adapter("docker").fetch("container", DOCKER, {"which": "jellyfin"}, ctx)

    assert data.status == "ok"
    assert data.primary["label"] == "CPU" and data.primary["value"] == 40.0
    # The four the container cards used to throw away.
    assert "Network in" in _labels(data) and "Network out" in _labels(data)
    assert "Disk read" in _labels(data) and "Disk written" in _labels(data)
    assert _value(data, "Processes") == 31
    assert _value(data, "Image") == "jellyfin/jellyfin:latest"
    assert _value(data, "State") == "running"
    # Memory without the cache: 500 MB reported, 100 MB of it cache.
    # human_bytes counts in binary units: 400 MB of bytes is 381.5 MiB.
    assert _value(data, "Memory") == "381.5 MB"
    assert _value(data, "Memory used") == 20.0


@respx.mock
async def test_a_stopped_container_says_so_and_offers_to_start(ctx: Context) -> None:
    """⚠️ No numbers at all here, and none invented. A stopped container uses
    no CPU, but "0%" and "nothing to measure" are different statements, and
    only one of them is true."""
    respx.get(f"{ENGINE}/containers/json").mock(return_value=httpx.Response(200, json=[RUNNING, STOPPED]))

    data = await get_adapter("docker").fetch("container", DOCKER, {"which": "backup"}, ctx)

    assert data.status == "bad"
    assert data.primary["value"] is None
    # Every measured row is gone, not zeroed. Memory is the one that matters:
    # "0 B" on a stopped container reads as a container using no memory, which
    # is true and useless, rather than as one that is not running.
    for gone in ("Memory", "Memory used", "Network in", "Disk read", "Processes"):
        assert gone not in _labels(data), gone
    assert _value(data, "State") == "exited"
    assert [action.id for action in data.actions] == ["start"]


@respx.mock
async def test_a_container_that_is_gone_says_which_one(ctx: Context) -> None:
    respx.get(f"{ENGINE}/containers/json").mock(return_value=httpx.Response(200, json=[RUNNING]))
    with pytest.raises(AdapterError) as gone:
        await get_adapter("docker").fetch("container", DOCKER, {"which": "paperless"}, ctx)
    assert "paperless" in str(gone.value)


@respx.mock
async def test_a_card_nobody_has_pointed_anywhere_says_that(ctx: Context) -> None:
    respx.get(f"{ENGINE}/containers/json").mock(return_value=httpx.Response(200, json=[RUNNING]))
    with pytest.raises(AdapterError) as empty:
        await get_adapter("docker").fetch("container", DOCKER, {}, ctx)
    assert empty.value.code == "nothing_picked"


@respx.mock
async def test_the_stats_call_failing_is_not_the_card_failing(ctx: Context) -> None:
    """The engine answers the list and refuses the stats. The card still knows
    the state, the image and how long it has been up."""
    respx.get(f"{ENGINE}/containers/json").mock(return_value=httpx.Response(200, json=[RUNNING]))
    respx.get(f"{ENGINE}/containers/{RUNNING['Id']}/stats").mock(return_value=httpx.Response(500, json={"message": "no"}))

    data = await get_adapter("docker").fetch("container", DOCKER, {"which": "jellyfin"}, ctx)
    assert data.primary["value"] is None
    assert _value(data, "State") == "running"
    assert _value(data, "Image") == "jellyfin/jellyfin:latest"


@respx.mock
async def test_the_list_of_containers_comes_from_the_engine(ctx: Context) -> None:
    respx.get(f"{ENGINE}/containers/json").mock(return_value=httpx.Response(200, json=[RUNNING, STOPPED]))
    offered = await get_adapter("docker").choices("which", DOCKER, ctx)
    assert offered == [("backup", "backup"), ("jellyfin", "jellyfin")]
    # No other field is answered by mistake.
    assert await get_adapter("docker").choices("history", DOCKER, ctx) == []


@respx.mock
async def test_a_history_nobody_wants_is_not_recorded(ctx: Context) -> None:
    """The switch is not decoration: a card per container on a busy host is a
    lot of rows in the history table for numbers nobody looks back at."""
    respx.get(f"{ENGINE}/containers/json").mock(return_value=httpx.Response(200, json=[RUNNING]))
    respx.get(f"{ENGINE}/containers/{RUNNING['Id']}/stats").mock(return_value=httpx.Response(200, json=STATS))

    kept = await get_adapter("docker").fetch("container", DOCKER, {"which": "jellyfin", "history": True}, ctx)
    dropped = await get_adapter("docker").fetch("container", DOCKER, {"which": "jellyfin", "history": False}, ctx)
    assert set(kept.metrics) == {"cpu", "memory"}
    assert dropped.metrics == {}


# ---------------------------------------------------------------------------
# What each service can and cannot answer
# ---------------------------------------------------------------------------


def _dsm(answers: dict) -> None:
    respx.post(f"{NAS}/webapi/auth.cgi").mock(return_value=httpx.Response(200, json={"success": True, "data": {"sid": "sid-1"}}))

    def route(request: httpx.Request) -> httpx.Response:
        found = answers.get((request.url.params.get("api"), request.url.params.get("method")))
        if found is None:
            return httpx.Response(200, json={"success": False, "error": {"code": 101}})
        return httpx.Response(200, json={"success": True, "data": found})

    respx.get(f"{NAS}/webapi/entry.cgi").mock(side_effect=route)


SYNO_CONFIG = {"url": NAS, "username": "nexdeck", "password": "a-password", "insecure": True}


@respx.mock
async def test_dsm_answers_what_it_has_and_leaves_out_what_it_does_not(ctx: Context) -> None:
    """⚠️ The whole reason for the shared shape. DSM reports no network
    counters and no block IO for a container. Those rows are missing, not
    zero."""
    _dsm({
        ("SYNO.Docker.Container", "list"): {"containers": [
            {"id": "c1", "name": "nexview", "status": "running", "up_status": "Up 3 days", "image": "ghcr.io/x:1"},
        ]},
        ("SYNO.Docker.Container.Resource", "get"): {"resources": [
            {"name": "nexview", "cpu": 1.2, "memory": 412_000_000, "memoryPercent": 20.6},
        ]},
    })
    data = await get_adapter("synology").fetch("container", SYNO_CONFIG, {"which": "nexview"}, ctx)

    assert data.primary["value"] == 1.2
    assert _value(data, "Memory used") == 20.6
    assert "Network in" not in _labels(data)
    assert "Disk read" not in _labels(data)
    assert "Processes" not in _labels(data)


@respx.mock
async def test_a_virtual_machine_has_no_cpu_and_does_not_pretend_to(ctx: Context) -> None:
    _dsm({
        ("SYNO.Virtualization.Guest", "list"): {"guests": [
            {"guest_id": "g1", "name": "homeassistant", "status": "running", "vram_size": 4096, "vcpu_num": 2, "host_name": "nas"},
        ]},
        ("SYNO.Virtualization.Guest", "get"): {"ram_used": 2048},
    })
    data = await get_adapter("synology").fetch("vm", SYNO_CONFIG, {"which": "homeassistant"}, ctx)

    assert data.primary["value"] is None, "the VM manager reports no load, so the card must not show one"
    assert _value(data, "Processors") == 2
    assert _value(data, "Memory") == "2.0 MB"


@respx.mock
async def test_proxmox_pays_for_nothing_extra(ctx: Context) -> None:
    """One call, the one the guest list already makes: the cluster resources
    carry CPU, memory, disk and both network counters for every guest."""
    respx.get(f"{PVE}/api2/json/nodes").mock(return_value=httpx.Response(200, json={"data": []}))
    asked = respx.get(f"{PVE}/api2/json/cluster/resources").mock(return_value=httpx.Response(200, json={"data": [
        {"vmid": 101, "name": "docker", "node": "pve", "status": "running", "cpu": 0.12,
         "mem": 2_000_000_000, "maxmem": 8_000_000_000, "disk": 18_000_000_000, "maxdisk": 32_000_000_000,
         "netin": 2_100_000_000, "netout": 400_000_000, "uptime": 260_000},
    ]}))
    config = {"url": PVE, "token_id": "root@pam!nexdeck", "token_secret": "s", "insecure": True}

    data = await get_adapter("proxmox").fetch("guest", config, {"which": "docker"}, ctx)

    # One request over the wire. A second call would be served from the
    # response cache anyway, so this says "no other endpoint was needed",
    # which is the claim the card makes.
    assert asked.call_count == 1
    assert data.primary["value"] == 12.0
    assert _value(data, "Storage") == 56.2
    assert _value(data, "Node") == "pve"
