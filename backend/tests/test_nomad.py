"""Nomad, against the answers its HTTP API documents (issue #2).

⚠️ Recorded from the documented shapes, not from a live cluster: the adapter is
beta until somebody has run it against one. Each test therefore pins a shape
the documentation states outright, so the day a live cluster answers otherwise
the difference is visible here rather than on a board.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context

NOMAD = "http://nomad.example.com:4646"
CONFIG = {"url": NOMAD, "token": "made-up-token", "namespace": "default"}


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


def job(name: str, kind: str, status: str, groups: dict[str, dict[str, int]]) -> dict[str, Any]:
    """A job as ``GET /v1/jobs`` lists it: the counts live per task group."""
    return {
        "ID": name, "Name": name, "Type": kind, "Status": status, "Priority": 50, "ParentID": "",
        "JobSummary": {"JobID": name, "Namespace": "default", "Summary": {
            group: {"Queued": 0, "Complete": 0, "Failed": 0, "Running": 0, "Starting": 0, "Lost": 0, **counts}
            for group, counts in groups.items()
        }, "Children": {"Pending": 0, "Running": 0, "Dead": 0}},
    }


def node(identifier: str, name: str, status: str, *, cpu: int = 12000, memory: int = 16384, **rest: Any) -> dict[str, Any]:
    return {
        "ID": identifier, "Name": name, "Status": status, "Datacenter": "home", "NodePool": "default",
        "SchedulingEligibility": "eligible", "Drain": False, "Version": "1.9.3",
        "NodeResources": {"Cpu": {"CpuShares": cpu}, "Memory": {"MemoryMB": memory}},
        **rest,
    }


def allocation(node_id: str, tasks: dict[str, tuple[int, int]], *, state: str = "running") -> dict[str, Any]:
    return {
        "ID": f"alloc-{node_id}-{'-'.join(tasks)}", "JobID": "jellyfin", "NodeID": node_id, "NodeName": "n",
        "TaskGroup": "web", "ClientStatus": state, "DesiredStatus": "run",
        "AllocatedResources": {"Tasks": {
            name: {"Cpu": {"CpuShares": cpu}, "Memory": {"MemoryMB": memory}} for name, (cpu, memory) in tasks.items()
        }},
    }


JOBS = [
    job("jellyfin", "service", "running", {"web": {"Running": 1}}),
    job("paperless", "service", "running", {"web": {"Running": 1}, "worker": {"Running": 1, "Failed": 2}}),
    job("nightly-backup", "batch", "dead", {"restic": {"Complete": 1}}),
    job("traefik", "system", "running", {"proxy": {"Running": 3}}),
]
NODES = [
    node("a" * 36, "mac-mini", "ready", cpu=24000, memory=16384),
    node("b" * 36, "nuc", "down", cpu=12000, memory=32768),
]


def _jobs(answer: list[dict[str, Any]] | None = None) -> respx.Route:
    return respx.get(f"{NOMAD}/v1/jobs").mock(return_value=httpx.Response(200, json=JOBS if answer is None else answer))


def _nodes(answer: list[dict[str, Any]] | None = None) -> respx.Route:
    return respx.get(f"{NOMAD}/v1/nodes").mock(return_value=httpx.Response(200, json=NODES if answer is None else answer))


# -- what the cards read -------------------------------------------------------


@respx.mock
async def test_nomad_jobs_read_the_counts_from_the_task_groups(ctx: Context) -> None:
    """A job's state is not one field: ``Status`` says running while a task
    group of it has two failed allocations, and that job is the finding."""
    jobs = _jobs()
    data = await get_adapter("nomad").fetch("jobs", CONFIG, {"limit": 10}, ctx)
    assert [item["title"] for item in data.items] == ["paperless", "jellyfin", "nightly-backup", "traefik"], "trouble first, then by name"
    assert [item["status"] for item in data.items] == ["bad", "ok", "ok", "ok"]
    assert data.items[0]["subtitle"] == "service · 2 failed"
    assert data.items[1]["subtitle"] == "service · 1 running"
    assert data.items[2]["subtitle"] == "batch · finished", "a batch job that ran out of work is not a fault"
    assert data.status == "bad"
    assert data.metrics == {"running": 6.0, "failed": 2.0}
    assert jobs.calls.last.request.headers["X-Nomad-Token"] == "made-up-token"
    assert "namespace=default" in str(jobs.calls.last.request.url)


@respx.mock
async def test_nomad_a_stopped_service_job_is_not_green(ctx: Context) -> None:
    """``dead`` on a service job means somebody stopped it. A batch job of the
    same shape has simply finished, and one colour for both would be wrong for
    one of them."""
    _jobs([job("jellyfin", "service", "dead", {"web": {}})])
    data = await get_adapter("nomad").fetch("jobs", CONFIG, {}, ctx)
    assert data.items[0]["subtitle"] == "service · stopped"
    assert data.items[0]["status"] == "warn"
    assert data.status == "warn"


@respx.mock
async def test_nomad_hides_the_finished_jobs_on_request(ctx: Context) -> None:
    _jobs()
    data = await get_adapter("nomad").fetch("jobs", CONFIG, {"show_dead": False}, ctx)
    assert [item["title"] for item in data.items] == ["paperless", "jellyfin", "traefik"]


@respx.mock
async def test_nomad_offers_stop_and_scaling_where_they_mean_something(ctx: Context) -> None:
    """A system job runs one allocation per client and has no count to move; a
    job with two task groups has two counts, so the button asks which."""
    _jobs()
    data = await get_adapter("nomad").fetch("jobs", CONFIG, {}, ctx)
    offered = {item["title"]: {one["id"]: one for one in item["actions"]} for item in data.items}

    assert sorted(offered["jellyfin"]) == ["scale_down", "scale_up", "stop"]
    assert offered["jellyfin"]["scale_up"]["params"] == {"job": "jellyfin", "group": "web"}, "one group needs no question"
    assert offered["jellyfin"]["scale_up"]["asks"] == []

    assert offered["paperless"]["scale_up"]["params"] == {"job": "paperless"}
    assert [one["value"] for one in offered["paperless"]["scale_up"]["asks"][0]["options"]] == ["web", "worker"]

    assert sorted(offered["traefik"]) == ["stop"], "a system job has no count"
    assert offered["nightly-backup"] == {}, "a job that is already dead is not stopped again"


@respx.mock
async def test_nomad_nodes_add_up_what_is_allocated_per_task(ctx: Context) -> None:
    """⚠️ ``AllocatedResources.Tasks`` holds one entry per task, so a group of
    two sidecars occupies both of their reservations on that node."""
    nodes = _nodes()
    allocations = respx.get(f"{NOMAD}/v1/allocations").mock(return_value=httpx.Response(200, json=[
        allocation("a" * 36, {"web": (4000, 2048), "sidecar": (2000, 1024)}),
        allocation("a" * 36, {"worker": (6000, 4096)}),
        allocation("b" * 36, {"web": (1000, 512)}, state="complete"),
    ]))
    data = await get_adapter("nomad").fetch("nodes", CONFIG, {}, ctx)
    first = data.items[0]
    assert first["title"] == "mac-mini"
    assert first["cpu"] == 50.0, "12000 of 24000 MHz"
    assert first["memory"] == "7.0 GB"
    assert first["value"] == "50%"
    assert "2 allocations" in first["subtitle"]

    second = data.items[1]
    assert second["status"] == "bad", "a client that is down"
    assert second["value"] == "0%", "the finished allocation on it does not count"
    assert data.status == "bad"
    assert data.metrics["nodes_ready"] == 1.0
    assert "resources=true" in str(nodes.calls.last.request.url)
    assert "namespace=%2A" in str(allocations.calls.last.request.url), "allocations across every namespace"


@respx.mock
async def test_nomad_says_so_rather_than_understating_what_is_allocated(ctx: Context) -> None:
    """⚠️ A token that may read one namespace sees a fraction of what runs on a
    node. That fraction as the node's allocated share is a number that looks
    right and is wrong, so the rows show none at all and the card says why."""
    _nodes()
    respx.get(f"{NOMAD}/v1/allocations").mock(return_value=httpx.Response(403, text="Permission denied"))
    data = await get_adapter("nomad").fetch("nodes", CONFIG, {}, ctx)
    assert [item["value"] for item in data.items] == ["?", "?"]
    assert all("cpu" not in item for item in data.items)
    assert "cpu_percent" not in data.metrics, "nothing measured is not a zero in the history"
    assert [row for row in data.secondary if row["label"] == "Allocated"], "the reason is on the card"


@respx.mock
async def test_nomad_summary_counts_jobs_and_clients(ctx: Context) -> None:
    _jobs()
    _nodes()
    data = await get_adapter("nomad").fetch("summary", CONFIG, {}, ctx)
    assert data.primary == {"label": "Allocations running", "value": 6}
    assert [row["value"] for row in data.secondary] == [4, 2, "1 of 2"]
    assert data.status == "bad"
    assert data.metrics == {"running": 6.0, "failed": 2.0, "nodes_ready": 1.0}


@respx.mock
async def test_nomad_test_names_the_namespace_and_the_clients(ctx: Context) -> None:
    _jobs()
    _nodes()
    message = await get_adapter("nomad").test(CONFIG, ctx)
    assert message == "Nomad answers with 4 jobs in the namespace default and 1 of 2 clients ready."


# -- the buttons ---------------------------------------------------------------


@respx.mock
async def test_nomad_stops_a_job_with_delete(ctx: Context) -> None:
    """⚠️ The issue proposed ``POST /v1/job/:id`` with ``Stop=true``. Stopping
    is a DELETE, and a POST of that shape would have registered a job."""
    stop = respx.delete(f"{NOMAD}/v1/job/jellyfin").mock(return_value=httpx.Response(200, json={"EvalID": "e1", "Index": 45}))
    message = await get_adapter("nomad").action("jobs", "stop", {"job": "jellyfin"}, CONFIG, {}, ctx)
    assert message == "Job jellyfin stopped."
    assert stop.called
    assert "namespace=default" in str(stop.calls.last.request.url)


def _scale_status(desired: int, running: int) -> None:
    """``GET /v1/job/:id/scale``. ⚠️ Desired and Running are two numbers, and
    the group below is the case that tells them apart: one instance wanted,
    none of it running because the allocation died."""
    respx.get(f"{NOMAD}/v1/job/whisper/scale").mock(return_value=httpx.Response(200, json={
        "JobID": "whisper", "Namespace": "default", "JobStopped": False,
        "TaskGroups": {"gpu": {"Desired": desired, "Placed": running, "Running": running,
                               "Healthy": running, "Unhealthy": 0, "Events": None}},
    }))


@respx.mock
async def test_nomad_scales_from_the_count_the_cluster_wants(ctx: Context) -> None:
    """The count comes from ``/v1/job/:id/scale`` at the moment the button is
    pressed, and it is ``Desired``, not what happens to run: a group of one
    whose allocation has died runs none, and counting up from none would put
    it back where it already is. ⚠️ Nomad refuses a scale request that carries
    neither Message nor Error, so the body always has one."""
    _scale_status(desired=1, running=0)
    scale = respx.post(f"{NOMAD}/v1/job/whisper/scale").mock(return_value=httpx.Response(200, json={"EvalID": "e2", "Index": 46}))
    message = await get_adapter("nomad").action("jobs", "scale_up", {"job": "whisper", "group": "gpu"}, CONFIG, {}, ctx)
    assert message == "Task group gpu of whisper scaled from 1 to 2."
    sent = json.loads(scale.calls.last.request.content)
    assert sent["Count"] == 2
    assert sent["Target"] == {"Group": "gpu"}
    assert sent["Message"], "one of Message or Error has to be there"


@respx.mock
async def test_nomad_scales_down_to_zero_from_what_is_desired(ctx: Context) -> None:
    """The other side of the same number: down from one wanted is zero, and
    counting down from what runs would have asked for minus one."""
    _scale_status(desired=1, running=0)
    scale = respx.post(f"{NOMAD}/v1/job/whisper/scale").mock(return_value=httpx.Response(200, json={"Index": 47}))
    message = await get_adapter("nomad").action("jobs", "scale_down", {"job": "whisper", "group": "gpu"}, CONFIG, {}, ctx)
    assert message == "Task group gpu of whisper scaled from 1 to 0."
    assert json.loads(scale.calls.last.request.content)["Count"] == 0


@respx.mock
async def test_nomad_does_not_scale_below_zero(ctx: Context) -> None:
    """⚠️ Which is why the count is read rather than taken from the card: a
    group of one whose allocation has died shows 0 running, and counting down
    from what is running would ask Nomad for -1."""
    respx.get(f"{NOMAD}/v1/job/whisper/scale").mock(return_value=httpx.Response(200, json={
        "TaskGroups": {"gpu": {"Desired": 0, "Running": 0}},
    }))
    scale = respx.post(f"{NOMAD}/v1/job/whisper/scale").mock(return_value=httpx.Response(200, json={}))
    with pytest.raises(AdapterError) as refusal:
        await get_adapter("nomad").action("jobs", "scale_down", {"job": "whisper", "group": "gpu"}, CONFIG, {}, ctx)
    assert "already at zero" in refusal.value.message
    assert not scale.called


@respx.mock
async def test_nomad_refuses_a_group_the_job_does_not_have(ctx: Context) -> None:
    respx.get(f"{NOMAD}/v1/job/whisper/scale").mock(return_value=httpx.Response(200, json={
        "TaskGroups": {"gpu": {"Desired": 1}},
    }))
    scale = respx.post(f"{NOMAD}/v1/job/whisper/scale").mock(return_value=httpx.Response(200, json={}))
    with pytest.raises(AdapterError):
        await get_adapter("nomad").action("jobs", "scale_up", {"job": "whisper", "group": "web"}, CONFIG, {}, ctx)
    assert not scale.called


@respx.mock
async def test_nomad_passes_on_why_a_scale_was_refused(ctx: Context) -> None:
    """⚠️ Nomad answers 400 in plain text while a deployment of that job runs.
    "The service answered with an error" would send somebody looking at the
    address; the sentence Nomad sends says to wait."""
    respx.get(f"{NOMAD}/v1/job/whisper/scale").mock(return_value=httpx.Response(200, json={
        "TaskGroups": {"gpu": {"Desired": 1}},
    }))
    respx.post(f"{NOMAD}/v1/job/whisper/scale").mock(return_value=httpx.Response(
        400, text="Job scaling blocked due to active deployment"))
    with pytest.raises(AdapterError) as refusal:
        await get_adapter("nomad").action("jobs", "scale_up", {"job": "whisper", "group": "gpu"}, CONFIG, {}, ctx)
    assert "active deployment" in refusal.value.message


@respx.mock
async def test_nomad_refuses_a_job_name_that_is_not_one(ctx: Context) -> None:
    """A name on its way into an address is a single segment or nothing."""
    stop = respx.delete(url__startswith=f"{NOMAD}/v1/job").mock(return_value=httpx.Response(200, json={}))
    with pytest.raises(AdapterError):
        await get_adapter("nomad").action("jobs", "stop", {"job": "../nodes"}, CONFIG, {}, ctx)
    assert not stop.called


@respx.mock
async def test_nomad_names_a_refused_token(ctx: Context) -> None:
    """⚠️ Nomad's own words, in plain text: "ACL token not found" is a typo in
    the token, "Permission denied" a policy that is missing a rule. One of them
    is fixed in nexdeck and the other in Nomad."""
    respx.get(f"{NOMAD}/v1/jobs").mock(return_value=httpx.Response(403, text="ACL token not found"))
    with pytest.raises(AuthFailed) as refusal:
        await get_adapter("nomad").fetch("jobs", CONFIG, {}, ctx)
    assert "ACL token not found" in refusal.value.message


@respx.mock
async def test_nomad_sends_no_token_where_none_is_configured(ctx: Context) -> None:
    """A cluster without ACLs answers every read, and an empty header is not
    the same as no header."""
    jobs = _jobs()
    await get_adapter("nomad").fetch("jobs", {"url": NOMAD}, {}, ctx)
    assert "X-Nomad-Token" not in jobs.calls.last.request.headers
    assert "namespace=default" in str(jobs.calls.last.request.url), "the default namespace, not none"


@respx.mock
async def test_nomad_names_an_address_that_is_not_nomad(ctx: Context) -> None:
    respx.get(f"{NOMAD}/v1/jobs").mock(return_value=httpx.Response(200, json={"message": "hello"}))
    with pytest.raises(AdapterError) as failure:
        await get_adapter("nomad").fetch("jobs", CONFIG, {}, ctx)
    assert failure.value.code == "not_nomad"
