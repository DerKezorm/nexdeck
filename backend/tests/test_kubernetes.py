"""Kubernetes, against the answers of a live k3s v1.37.0 with metrics-server (26.09.2026)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context
from app.adapters.kubernetes import quantity

API = "https://kubernetes.example.com:6443"
CONFIG = {"url": API, "token": "a-service-account-token-for-the-cards"}
ADAPTER = get_adapter("kubernetes")


def listing(items: list[dict[str, Any]], kind: str) -> dict[str, Any]:
    return {"kind": kind, "apiVersion": "v1", "metadata": {"resourceVersion": "1234"}, "items": items}


def node(name: str, *, ready: bool = True, cordoned: bool = False, pressure: str = "", role: str = "control-plane") -> dict[str, Any]:
    conditions = [{"type": kind, "status": "True" if kind == pressure else "False"} for kind in ("MemoryPressure", "DiskPressure", "PIDPressure")]
    conditions.append({"type": "Ready", "status": "True" if ready else "False"})
    spec: dict[str, Any] = {"podCIDR": "10.42.0.0/24"}
    if cordoned:
        # ⚠️ Still Ready; only this changes.
        spec.update(unschedulable=True, taints=[{"key": "node.kubernetes.io/unschedulable", "effect": "NoSchedule"}])
    return {"metadata": {"name": name, "labels": {f"node-role.kubernetes.io/{role}": "true"} if role else {}}, "spec": spec,
            "status": {"conditions": conditions, "capacity": {"cpu": "4", "memory": "8138624Ki", "pods": "110"},
                       "allocatable": {"cpu": "4", "memory": "8138624Ki", "pods": "110"}, "nodeInfo": {"kubeletVersion": "v1.37.0+k3s1"}}}


def pod(name: str, namespace: str, phase: str, *containers: dict[str, Any]) -> dict[str, Any]:
    return {"metadata": {"name": name, "namespace": namespace, "ownerReferences": [{"kind": "ReplicaSet"}]},
            "status": {"phase": phase, "containerStatuses": list(containers)}}


def running(ready: bool = True, restarts: int = 0) -> dict[str, Any]:
    return {"name": "c", "ready": ready, "restartCount": restarts, "state": {"running": {"startedAt": "2026-09-26T21:20:00Z"}}}


def waiting(reason: str) -> dict[str, Any]:
    return {"name": "c", "ready": False, "restartCount": 0, "state": {"waiting": {"reason": reason, "message": "..."}}}


def terminated(reason: str, restarts: int) -> dict[str, Any]:
    return {"name": "c", "ready": False, "restartCount": restarts, "state": {"terminated": {"reason": reason, "exitCode": 1}}}


# As k3s answered with the invented workloads.
PODS = [
    pod("coredns-577d995dff-kbtnm", "kube-system", "Running", running()),
    pod("helm-install-gateway-api-crd-xc6ch", "kube-system", "Succeeded", terminated("Completed", 0)),
    pod("backup-once-bv4px", "shop", "Succeeded", terminated("Completed", 0)),
    pod("broken-d8777dbbc-j6gdv", "shop", "Pending", waiting("ImagePullBackOff")),
    # ⚠️ Crashing, and "Running" all the same.
    pod("crashy-775f9bd6b4-vdrq9", "shop", "Running", terminated("Error", 3)),
    pod("web-9bd756c7f-nj48v", "shop", "Running", running()),
    pod("web-9bd756c7f-qfsld", "shop", "Running", running(ready=False)),
]


def deployment(name: str, namespace: str, wanted: int, ready: int | None) -> dict[str, Any]:
    status: dict[str, Any] = {"observedGeneration": 1}
    # ⚠️ Scaled to zero: no replicas in the status at all.
    if wanted:
        status.update(replicas=wanted, updatedReplicas=wanted)
        if ready is not None:
            status.update(readyReplicas=ready, availableReplicas=ready)
    return {"metadata": {"name": name, "namespace": namespace}, "spec": {"replicas": wanted}, "status": status}


DEPLOYMENTS = [deployment("coredns", "kube-system", 1, 1), deployment("broken", "shop", 1, None), deployment("paused", "shop", 0, None),
               deployment("web", "shop", 2, 2)]
DAEMONSETS = [{"metadata": {"name": "svclb", "namespace": "kube-system"}, "status": {"desiredNumberScheduled": 3, "numberReady": 2}}]
NODE_METRICS = {"kind": "NodeMetricsList", "items": [{"metadata": {"name": "k3s-1"}, "usage": {"cpu": "61352018n", "memory": "664812Ki"}}]}
VERSION = {"major": "1", "minor": "37", "gitVersion": "v1.37.0+k3s1", "platform": "linux/amd64"}
FORBIDDEN = {"kind": "Status", "apiVersion": "v1", "status": "Failure", "reason": "Forbidden", "code": 403,
             "message": "nodes is forbidden: User \"system:serviceaccount:kube-system:nexdeck\" cannot list resource \"nodes\" in API group \"\" at the cluster scope"}


def cluster(*, nodes: list[dict[str, Any]] | None = None, metrics: httpx.Response | None = None) -> dict[str, respx.Route]:
    return {
        "version": respx.get(f"{API}/version").mock(return_value=httpx.Response(200, json=VERSION)),
        "nodes": respx.get(f"{API}/api/v1/nodes").mock(return_value=httpx.Response(200, json=listing(nodes or [node("k3s-1")], "NodeList"))),
        "pods": respx.get(f"{API}/api/v1/pods").mock(return_value=httpx.Response(200, json=listing(PODS, "PodList"))),
        "shop_pods": respx.get(f"{API}/api/v1/namespaces/shop/pods").mock(
            return_value=httpx.Response(200, json=listing([one for one in PODS if one["metadata"]["namespace"] == "shop"], "PodList"))),
        "deployments": respx.get(f"{API}/apis/apps/v1/deployments").mock(return_value=httpx.Response(200, json=listing(DEPLOYMENTS, "DeploymentList"))),
        "statefulsets": respx.get(f"{API}/apis/apps/v1/statefulsets").mock(return_value=httpx.Response(200, json=listing([], "StatefulSetList"))),
        "daemonsets": respx.get(f"{API}/apis/apps/v1/daemonsets").mock(return_value=httpx.Response(200, json=listing(DAEMONSETS, "DaemonSetList"))),
        "metrics": respx.get(f"{API}/apis/metrics.k8s.io/v1beta1/nodes").mock(return_value=metrics or httpx.Response(200, json=NODE_METRICS)),
    }


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


@pytest.mark.parametrize(("text", "number"), [("61352018n", 0.061352018), ("250m", 0.25), ("4", 4.0), ("664812Ki", 664812 * 1024.0),
                                              ("2Gi", 2 * 1024.0 ** 3), ("1000M", 1e9), ("", 0.0), ("12Zz", 0.0)])
def test_quantities_are_read_as_the_units_they_are(text: str, number: float) -> None:
    assert quantity(text) == pytest.approx(number)


@respx.mock
async def test_the_test_names_the_version_and_the_nodes(ctx: Context) -> None:
    routes = cluster()
    assert await ADAPTER.test(CONFIG, ctx) == "Kubernetes v1.37.0+k3s1 answers, with 1 node(s)."
    assert routes["nodes"].calls.last.request.headers["Authorization"] == f"Bearer {CONFIG['token']}"


@respx.mock
async def test_view_alone_does_not_reach_nodes_and_the_card_says_so(ctx: Context) -> None:
    respx.get(f"{API}/version").mock(return_value=httpx.Response(200, json=VERSION))
    respx.get(f"{API}/api/v1/nodes").mock(return_value=httpx.Response(403, json=FORBIDDEN))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.test(CONFIG, ctx)
    assert caught.value.code == "forbidden" and caught.value.message == "The token may not read nodes."
    assert "get and list on nodes" in caught.value.hint


@respx.mock
async def test_a_wrong_token(ctx: Context) -> None:
    respx.get(f"{API}/version").mock(return_value=httpx.Response(401, json={"kind": "Status", "message": "Unauthorized", "code": 401}))
    with pytest.raises(AuthFailed):
        await ADAPTER.test(CONFIG, ctx)


@respx.mock
async def test_pods_in_trouble_read_from_the_containers(ctx: Context) -> None:
    cluster()
    card = await ADAPTER.fetch("pods", CONFIG, {}, ctx)
    assert [(row["title"], row["subtitle"], row["status"]) for row in card.items] == [
        ("broken-d8777dbbc-j6gdv", "ImagePullBackOff · shop", "bad"),
        ("crashy-775f9bd6b4-vdrq9", "Crashing · shop · 3 restarts", "bad"),
        ("web-9bd756c7f-qfsld", "Not ready · shop", "warn"),
    ]
    assert card.metrics == {"pods_troubled": 3.0}


@respx.mock
async def test_every_pod_of_one_namespace(ctx: Context) -> None:
    routes = cluster()
    card = await ADAPTER.fetch("pods", CONFIG, {"namespace": "shop", "all_pods": True}, ctx)
    assert routes["shop_pods"].called and not routes["pods"].called
    # A finished job is fine, and the namespace is not repeated on every row.
    assert ("backup-once-bv4px", "Finished", "ok") in [(row["title"], row["subtitle"], row["status"]) for row in card.items]


@respx.mock
async def test_workloads_short_of_pods_first_and_zero_on_purpose(ctx: Context) -> None:
    cluster()
    card = await ADAPTER.fetch("workloads", CONFIG, {}, ctx)
    assert [(row["title"], row["subtitle"], row["value"], row["status"]) for row in card.items] == [
        ("broken", "Deployment · shop", "0 / 1", "bad"),
        ("svclb", "Daemon set · kube-system", "2 / 3", "bad"),
        ("paused", "Deployment · shop", "Scaled to zero", "unknown"),
        ("coredns", "Deployment · kube-system", "1 / 1", "ok"),
        ("web", "Deployment · shop", "2 / 2", "ok"),
    ]
    troubled = await ADAPTER.fetch("workloads", CONFIG, {"only_troubled": True}, ctx)
    assert [row["title"] for row in troubled.items] == ["broken", "svclb"]


@respx.mock
async def test_nodes_ready_cordoned_and_under_pressure(ctx: Context) -> None:
    cluster(nodes=[node("k3s-1"), node("k3s-2", cordoned=True, role=""), node("k3s-3", pressure="DiskPressure", role=""),
                   node("k3s-4", ready=False, role="")])
    card = await ADAPTER.fetch("nodes", CONFIG, {}, ctx)
    assert [(row["title"], row["subtitle"], row["status"]) for row in card.items] == [
        ("k3s-3", "DiskPressure · Worker", "bad"),
        ("k3s-4", "Not ready · Worker", "bad"),
        ("k3s-2", "Cordoned · Worker", "warn"),
        ("k3s-1", "Control plane · CPU 2 % · Memory 8 %", "ok"),
    ]


@respx.mock
async def test_the_cluster_card_adds_up(ctx: Context) -> None:
    cluster()
    card = await ADAPTER.fetch("cluster", CONFIG, {}, ctx)
    # Finished jobs are neither running nor in trouble.
    assert card.primary == {"label": "Pods running", "value": 2, "unit": "/ 5"}
    assert {row["part"]: row["value"] for row in card.secondary} == {
        "nodes": "1 / 1", "workloads": "2 / 4", "troubled": 3, "cpu": "2 %", "memory": "8 %", "version": "v1.37.0+k3s1"}
    assert card.status == "bad"
    assert card.metrics == {"pods_troubled": 3.0, "cpu_percent": 1.5, "memory_percent": 8.2}


@respx.mock
async def test_without_metrics_server_the_load_is_left_out_not_zero(ctx: Context) -> None:
    cluster(metrics=httpx.Response(503, text="service unavailable"))
    card = await ADAPTER.fetch("cluster", CONFIG, {}, ctx)
    assert {row["part"] for row in card.secondary} == {"nodes", "workloads", "troubled", "version"}
    assert card.metrics == {"pods_troubled": 3.0}, "no zero in the history for what nobody measured"
    nodes = await ADAPTER.fetch("nodes", CONFIG, {}, ctx)
    assert nodes.items[0]["subtitle"] == "Control plane"


@respx.mock
async def test_namespaces_to_choose_from(ctx: Context) -> None:
    respx.get(f"{API}/api/v1/namespaces").mock(return_value=httpx.Response(200, json=listing(
        [{"metadata": {"name": name}} for name in ("shop", "default", "kube-system")], "NamespaceList")))
    assert await ADAPTER.choices("namespace", CONFIG, ctx) == [("default", "default"), ("kube-system", "kube-system"), ("shop", "shop")]


@respx.mock
async def test_a_web_page_is_not_kubernetes(ctx: Context) -> None:
    respx.get(f"{API}/version").mock(return_value=httpx.Response(200, text="<html>dashboard</html>"))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.test(CONFIG, ctx)
    assert caught.value.code == "not_kubernetes"


@pytest.mark.parametrize("kind", [widget.kind for widget in ADAPTER.widgets])
def test_demo_has_every_card(kind: str) -> None:
    for tick in range(5):
        card = ADAPTER.demo(kind, {}, tick)
        assert card.items or card.primary
