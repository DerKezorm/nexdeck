"""Kubernetes: nodes, workloads and the pods that need a look, read-only through the cluster's own API.

Measured on 26.09.2026 against k3s v1.37.0 with metrics-server, one node,
and invented workloads: a deployment of two that ran, one whose image does
not exist, one that crashes three seconds after starting, one scaled to
nothing, and a job that finished. Read through a service account token.

⚠️ The built-in ClusterRole ``view`` does not reach nodes: ``/api/v1/nodes``
answered 403 "nodes is forbidden" for a token bound to it, while pods,
deployments and the node metrics came through. The cards need ``view`` plus
``get`` and ``list`` on nodes, and the connection sheet says so.

⚠️ A pod whose container keeps crashing is still ``phase: Running``. Only
the container's state says so: ``terminated`` with reason ``Error`` and a
growing ``restartCount``, or ``waiting`` with ``CrashLoopBackOff``. A missing
image is ``Pending`` with ``waiting`` ``ImagePullBackOff``. The card reads
the containers, not the phase.

⚠️ A pod that has ``Succeeded`` is a finished job, not a broken pod; a
deployment scaled to zero has no ``replicas`` at all in its status and is
not unhealthy either.

⚠️ A cordoned node stays ``Ready``; ``spec.unschedulable`` and a taint
``node.kubernetes.io/unschedulable`` are what change.

⚠️ Quantities come as Kubernetes writes them: CPU as ``61352018n``, ``250m``
or ``4``, memory as ``664812Ki``, ``2Gi`` or ``1000M``, binary and decimal
suffixes side by side. Without metrics-server there are no usage figures,
and the cards leave them out rather than showing zero.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

from . import demo as fake
from .base import (
    Adapter,
    AdapterError,
    AuthFailed,
    Context,
    Field,
    WidgetData,
    WidgetType,
    base_url,
    part_on,
)

ROLE_HINT = "Bind the token to the ClusterRole view, and to a ClusterRole with get and list on nodes."
ORDER = {"bad": 0, "warn": 1, "unknown": 2, "ok": 3}
QUANTITY = re.compile(r"^([0-9.]+)([a-zA-Z]*)$")
SUFFIX = {"n": 1e-9, "u": 1e-6, "m": 1e-3, "": 1.0, "k": 1e3, "M": 1e6, "G": 1e9, "T": 1e12, "P": 1e15,
          "Ki": 1024.0, "Mi": 1024.0 ** 2, "Gi": 1024.0 ** 3, "Ti": 1024.0 ** 4, "Pi": 1024.0 ** 5}
#: Container reasons that mean the pod will not come up by itself.
BROKEN = {"CrashLoopBackOff", "ImagePullBackOff", "ErrImagePull", "CreateContainerConfigError", "CreateContainerError",
          "InvalidImageName", "RunContainerError", "OOMKilled", "Error"}
NAMESPACE = Field("namespace", "Namespace", type="choices", help="Empty for every namespace.")


def quantity(text: Any) -> float:
    """A Kubernetes quantity as a plain number: cores for CPU, bytes for memory."""
    found = QUANTITY.match(str(text or "").strip())
    if not found or found.group(2) not in SUFFIX:
        return 0.0
    return float(found.group(1)) * SUFFIX[found.group(2)]


def _name(item: dict[str, Any]) -> str:
    return str((item.get("metadata") or {}).get("name") or "?")


def _namespace(item: dict[str, Any]) -> str:
    return str((item.get("metadata") or {}).get("namespace") or "")


def _pod_state(pod: dict[str, Any]) -> tuple[str, str, int]:
    """How a pod is, as a colour and a few words, and its restarts. Read from the containers."""
    status = pod.get("status") or {}
    phase = str(status.get("phase") or "")
    containers = [one for one in [*(status.get("initContainerStatuses") or []), *(status.get("containerStatuses") or [])] if isinstance(one, dict)]
    restarts = sum(int(one.get("restartCount") or 0) for one in containers)
    if phase == "Succeeded":
        return "ok", "Finished", restarts
    if phase == "Failed":
        return "bad", str(status.get("reason") or "Failed"), restarts
    for container in containers:
        state = container.get("state") or {}
        waiting = state.get("waiting") or {}
        terminated = state.get("terminated") or {}
        reason = str(waiting.get("reason") or "")
        if reason in BROKEN:
            return "bad", reason, restarts
        # ⚠️ Crashed and about to be started again: still "Running" for the pod.
        if terminated and terminated.get("reason") != "Completed" and container.get("restartCount"):
            return "bad", "Crashing", restarts
    if phase == "Pending":
        return "warn", "Pending", restarts
    if phase == "Running":
        if all(one.get("ready") for one in status.get("containerStatuses") or []):
            return "ok", "Running", restarts
        return "warn", "Not ready", restarts
    return "unknown", phase or "Unknown", restarts


def _ready_node(node: dict[str, Any]) -> bool:
    return any(one.get("type") == "Ready" and one.get("status") == "True" for one in (node.get("status") or {}).get("conditions") or [])


class KubernetesAdapter(Adapter):
    kind = "kubernetes"
    label = "Kubernetes"
    category = "hosts"
    description = "A Kubernetes cluster read-only: its nodes with their load, the workloads and whether they are ready, and the pods that need a look."
    icon = "kubernetes"
    beta = False
    docs_url = "https://kubernetes.io/docs/reference/access-authn-authz/rbac/"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="https://kubernetes.example.com:6443"),
        Field("token", "Token", type="password", secret=True, required=True,
              help="A service account token. Bind it to the ClusterRole view and to a ClusterRole with get and list on nodes; "
                   "view alone does not reach nodes. Nothing here writes."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False, help="A cluster signs with a certificate authority of its own."),
    )
    widgets = (
        WidgetType(kind="cluster", label="Cluster",
                   description="Pods running, with nodes ready, workloads ready, the pods in trouble and the load across the nodes.",
                   renderer="value", default_size=(3, 2), refresh_seconds=60, metrics=("pods_troubled", "cpu_percent", "memory_percent"),
                   parts=(("nodes", "Nodes"), ("workloads", "Workloads"), ("troubled", "Pods in trouble"), ("cpu", "Processor"),
                          ("memory", "Memory"), ("version", "Version"))),
        WidgetType(kind="nodes", label="Nodes",
                   description="Every node with whether it is ready, cordoned or under pressure, and its processor and memory.",
                   renderer="list", default_size=(3, 3), refresh_seconds=60),
        WidgetType(kind="workloads", label="Workloads",
                   description="Deployments, stateful sets and daemon sets with how many of their pods are ready, those short of it first.",
                   renderer="list", default_size=(3, 3), refresh_seconds=60,
                   options=(NAMESPACE, Field("only_troubled", "Only those short of pods", type="bool", default=False))),
        WidgetType(kind="pods", label="Pods in trouble",
                   description="Pods that crash, cannot pull their image, wait or are not ready, with their restarts.",
                   renderer="list", default_size=(3, 3), refresh_seconds=30, metrics=("pods_troubled",),
                   options=(NAMESPACE, Field("all_pods", "Show every pod", type="bool", default=False))),
    )

    # -- talking to the cluster ----------------------------------------------

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, *, params: dict[str, Any] | None = None,
                   optional: bool = False, cache: float = 10) -> Any:
        response = await ctx.request("GET", f"{base_url(config)}{path}", params=params,
                                     headers={"Authorization": f"Bearer {str(config.get('token') or '').strip()}"},
                                     verify=not config.get("insecure"), timeout=20.0, cache_seconds=cache, auth_errors=False)
        try:
            answer: Any = response.json()
        except ValueError:
            answer = None
        if response.status_code == 401:
            raise AuthFailed("The cluster rejected the token.")
        if optional and response.status_code in (404, 503):
            # metrics-server missing or not answering: no usage, no failure.
            return None
        if response.status_code == 403:
            said = str((answer or {}).get("message") or "") if isinstance(answer, dict) else ""
            what = said.split(" is forbidden", 1)[0] if " is forbidden" in said else "this"
            raise AdapterError(f"The token may not read {what}.", code="forbidden", hint=ROLE_HINT)
        if response.status_code >= 400:
            said = str((answer or {}).get("message") or "") if isinstance(answer, dict) else ""
            raise AdapterError(f"The cluster refused: {said}" if said else f"The cluster answered with HTTP {response.status_code}.", code="http_error")
        if not isinstance(answer, dict):
            raise AdapterError("This address answers with something other than a Kubernetes API.", code="not_kubernetes",
                               hint="Enter the address of the API server, port 6443 by default.")
        return answer

    async def _items(self, config: dict[str, Any], ctx: Context, path: str, namespace: str = "") -> list[dict[str, Any]]:
        if namespace:
            # /api/v1/pods -> /api/v1/namespaces/<ns>/pods, and the same for apps/v1.
            head, _, kind = path.rpartition("/")
            path = f"{head}/namespaces/{namespace}/{kind}"
        answer = await self._get(config, ctx, path)
        return [one for one in answer.get("items") or [] if isinstance(one, dict)]

    async def _node_usage(self, config: dict[str, Any], ctx: Context) -> dict[str, dict[str, float]]:
        answer = await self._get(config, ctx, "/apis/metrics.k8s.io/v1beta1/nodes", optional=True)
        usage: dict[str, dict[str, float]] = {}
        for one in (answer or {}).get("items") or []:
            if isinstance(one, dict):
                usage[_name(one)] = {"cpu": quantity((one.get("usage") or {}).get("cpu")), "memory": quantity((one.get("usage") or {}).get("memory"))}
        return usage

    # -- the hooks -----------------------------------------------------------

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        version = await self._get(config, ctx, "/version", cache=0)
        if not version.get("gitVersion"):
            raise AdapterError("This address answers, but not the way a Kubernetes API does.", code="not_kubernetes")
        nodes = await self._items(config, ctx, "/api/v1/nodes")
        return f"Kubernetes {version['gitVersion']} answers, with {len(nodes)} node(s)."

    async def choices(self, field: str, config: dict[str, Any], ctx: Context) -> list[tuple[str, str]]:
        if field != "namespace":
            return await super().choices(field, config, ctx)
        return sorted((_name(one), _name(one)) for one in await self._items(config, ctx, "/api/v1/namespaces"))

    def demo_choices(self, field: str) -> list[tuple[str, str]]:
        return [(one, one) for one in ("default", "home", "kube-system", "media")] if field == "namespace" else []

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        namespace = str(options.get("namespace") or "").strip()
        if widget_kind == "pods":
            pods = await self._items(config, ctx, "/api/v1/pods", namespace)
            return self._pod_rows(pods, all_pods=options.get("all_pods") is True, several=not namespace)
        if widget_kind == "workloads":
            found = await asyncio.gather(*(self._items(config, ctx, f"/apis/apps/v1/{kind}", namespace)
                                           for kind in ("deployments", "statefulsets", "daemonsets")))
            return self._workload_rows(*found, only_troubled=options.get("only_troubled") is True, several=not namespace)
        nodes, usage = await asyncio.gather(self._items(config, ctx, "/api/v1/nodes"), self._node_usage(config, ctx))
        if widget_kind == "nodes":
            return self._node_rows(nodes, usage)
        pods, deployments, statefulsets, daemonsets = await asyncio.gather(
            self._items(config, ctx, "/api/v1/pods"), self._items(config, ctx, "/apis/apps/v1/deployments"),
            self._items(config, ctx, "/apis/apps/v1/statefulsets"), self._items(config, ctx, "/apis/apps/v1/daemonsets"))
        version = await self._get(config, ctx, "/version", cache=3600) if part_on(options, "version") else {}
        return self._cluster(nodes, usage, pods, self._workload_rows(deployments, statefulsets, daemonsets), str(version.get("gitVersion") or ""))

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def _load(nodes: list[dict[str, Any]], usage: dict[str, dict[str, float]]) -> tuple[float | None, float | None]:
        """Share of the allocatable processor and memory in use, over the nodes metrics-server knows."""
        cpu_used = cpu_total = memory_used = memory_total = 0.0
        for node in nodes:
            used = usage.get(_name(node))
            if not used:
                continue
            allocatable = (node.get("status") or {}).get("allocatable") or {}
            cpu_used += used["cpu"]
            cpu_total += quantity(allocatable.get("cpu"))
            memory_used += used["memory"]
            memory_total += quantity(allocatable.get("memory"))
        return (100 * cpu_used / cpu_total if cpu_total else None, 100 * memory_used / memory_total if memory_total else None)

    @classmethod
    def _node_rows(cls, nodes: list[dict[str, Any]], usage: dict[str, dict[str, float]]) -> WidgetData:
        rows = []
        for node in nodes:
            labels = (node.get("metadata") or {}).get("labels") or {}
            roles = [key.split("/", 1)[1] for key in labels if key.startswith("node-role.kubernetes.io/") and "/" in key]
            parts = [" · ".join(sorted(roles)).replace("control-plane", "Control plane") or "Worker"]
            conditions = (node.get("status") or {}).get("conditions") or []
            pressure = [one.get("type") for one in conditions if one.get("type", "").endswith("Pressure") and one.get("status") == "True"]
            ready = _ready_node(node)
            cordoned = bool((node.get("spec") or {}).get("unschedulable"))
            if not ready:
                status = "bad"
                parts.insert(0, "Not ready")
            elif pressure:
                status = "bad"
                parts.insert(0, " · ".join(str(one) for one in pressure))
            elif cordoned:
                status = "warn"
                parts.insert(0, "Cordoned")
            else:
                status = "ok"
            cpu, memory = cls._load([node], usage)
            if cpu is not None:
                parts.append(f"CPU {cpu:.0f} %")
            if memory is not None:
                parts.append(f"Memory {memory:.0f} %")
            rows.append({"title": _name(node), "subtitle": " · ".join(parts),
                         "value": str(((node.get("status") or {}).get("nodeInfo") or {}).get("kubeletVersion") or ""), "status": status})
        rows.sort(key=lambda row: (ORDER.get(row["status"], 9), row["title"]))
        return WidgetData(
            status="bad" if any(row["status"] == "bad" for row in rows) else "warn" if any(row["status"] == "warn" for row in rows)
            else "ok" if rows else "unknown",
            items=rows, meta={"empty": "The cluster lists no node."})

    @staticmethod
    def _workload_rows(deployments: list[dict[str, Any]], statefulsets: list[dict[str, Any]], daemonsets: list[dict[str, Any]],
                       *, only_troubled: bool = False, several: bool = True) -> WidgetData:
        rows = []
        for kind, items in (("Deployment", deployments), ("Stateful set", statefulsets), ("Daemon set", daemonsets)):
            for item in items:
                status = item.get("status") or {}
                if kind == "Daemon set":
                    wanted, ready = int(status.get("desiredNumberScheduled") or 0), int(status.get("numberReady") or 0)
                else:
                    wanted, ready = int((item.get("spec") or {}).get("replicas", 1) or 0), int(status.get("readyReplicas") or 0)
                parts = [kind]
                if several:
                    parts.append(_namespace(item))
                if wanted == 0:
                    # ⚠️ Scaled to nothing on purpose; its status has no replicas at all.
                    colour, value = "unknown", "Scaled to zero"
                else:
                    colour, value = ("ok" if ready >= wanted else "bad"), f"{ready} / {wanted}"
                if only_troubled and colour != "bad":
                    continue
                rows.append({"title": _name(item), "subtitle": " · ".join(part for part in parts if part), "value": value, "status": colour})
        rows.sort(key=lambda row: (ORDER.get(row["status"], 9), row["title"]))
        return WidgetData(
            status="bad" if any(row["status"] == "bad" for row in rows) else "ok" if rows else "unknown",
            items=rows, meta={"empty": "Every workload has its pods." if only_troubled else "No workloads."})

    @staticmethod
    def _pod_rows(pods: list[dict[str, Any]], *, all_pods: bool = False, several: bool = True) -> WidgetData:
        rows = []
        troubled = 0
        for pod in pods:
            colour, word, restarts = _pod_state(pod)
            troubled += colour in ("bad", "warn")
            if not all_pods and colour not in ("bad", "warn"):
                continue
            parts = [word]
            if several:
                parts.append(_namespace(pod))
            if restarts:
                parts.append("1 restart" if restarts == 1 else f"{restarts} restarts")
            rows.append({"title": _name(pod), "subtitle": " · ".join(part for part in parts if part), "status": colour})
        rows.sort(key=lambda row: (ORDER.get(row["status"], 9), row["title"]))
        return WidgetData(
            status="bad" if any(row["status"] == "bad" for row in rows) else "warn" if troubled else "ok",
            items=rows, meta={"empty": "No pod needs a look." if not all_pods else "No pods."},
            metrics={"pods_troubled": float(troubled)})

    @classmethod
    def _cluster(cls, nodes: list[dict[str, Any]], usage: dict[str, dict[str, float]], pods: list[dict[str, Any]],
                 workloads: WidgetData, version: str) -> WidgetData:
        states = [_pod_state(pod) for pod in pods]
        live = [state for state in states if state[1] != "Finished"]
        running = sum(1 for state in live if state[0] == "ok")
        troubled = sum(1 for state in live if state[0] in ("bad", "warn"))
        counted = [row for row in workloads.items if row["status"] != "unknown"]
        cpu, memory = cls._load(nodes, usage)
        ready_nodes = sum(1 for node in nodes if _ready_node(node))
        secondary = [
            {"label": "Nodes", "value": f"{ready_nodes} / {len(nodes)}", "part": "nodes"},
            {"label": "Workloads", "value": f"{sum(1 for row in counted if row['status'] == 'ok')} / {len(counted)}", "part": "workloads"},
            {"label": "Pods in trouble", "value": troubled, "part": "troubled"},
        ]
        # ⚠️ Without metrics-server: left out, not zero.
        if cpu is not None:
            secondary.append({"label": "Processor", "value": f"{cpu:.0f} %", "part": "cpu"})
        if memory is not None:
            secondary.append({"label": "Memory", "value": f"{memory:.0f} %", "part": "memory"})
        if version:
            secondary.append({"label": "Version", "value": version, "part": "version"})
        bad = ready_nodes < len(nodes) or any(state[0] == "bad" for state in live) or workloads.status == "bad"
        return WidgetData(
            status="bad" if bad else "warn" if troubled else "ok" if nodes else "unknown",
            primary={"label": "Pods running", "value": running, "unit": f"/ {len(live)}"},
            secondary=secondary,
            # No zero in the history for a figure nobody measured.
            metrics={"pods_troubled": float(troubled),
                     **({"cpu_percent": round(cpu, 1)} if cpu is not None else {}),
                     **({"memory_percent": round(memory, 1)} if memory is not None else {})},
        )

    # -- demo ----------------------------------------------------------------

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        crashing = fake.flicker("kubernetes-crash", tick, 0.3)

        def pod(name: str, namespace: str, state: str = "running", restarts: int = 0, phase: str = "Running") -> dict[str, Any]:
            container: dict[str, Any] = {"ready": state == "running", "restartCount": restarts,
                                         "state": {"running": {}} if state == "running" else {"waiting": {"reason": state}}}
            return {"metadata": {"name": name, "namespace": namespace}, "status": {"phase": phase, "containerStatuses": [container]}}

        def node(name: str, role: str, cordoned: bool = False) -> dict[str, Any]:
            return {"metadata": {"name": name, "labels": {f"node-role.kubernetes.io/{role}": "true"} if role else {}},
                    "spec": {"unschedulable": cordoned}, "status": {"conditions": [{"type": "Ready", "status": "True"}],
                                                                    "allocatable": {"cpu": "4", "memory": "16Gi"}, "nodeInfo": {"kubeletVersion": "v1.37.0+k3s1"}}}

        nodes = [node("k3s-1", "control-plane"), node("k3s-2", ""), node("k3s-3", "", cordoned=tick % 5 == 4)]
        usage = {"k3s-1": {"cpu": 1.1 + tick % 3 * 0.2, "memory": 7.2e9}, "k3s-2": {"cpu": 0.6, "memory": 5.1e9}, "k3s-3": {"cpu": 0.3, "memory": 2.4e9}}
        pods = [pod("immich-server-7d9f", "media"), pod("jellyfin-0", "media"), pod("home-assistant-0", "home"),
                pod("paperless-5c8b", "home", "CrashLoopBackOff" if crashing else "running", restarts=6 if crashing else 1),
                pod("coredns-577d", "kube-system"), pod("backup-2026-09-26", "home", "Completed", phase="Succeeded"),
                pod("nextcloud-cron-29c1", "home", "ContainerCreating", phase="Pending")]

        def deployment(name: str, namespace: str, wanted: int, ready: int) -> dict[str, Any]:
            return {"metadata": {"name": name, "namespace": namespace}, "spec": {"replicas": wanted}, "status": {"readyReplicas": ready}}

        deployments = [deployment("immich-server", "media", 1, 1), deployment("paperless", "home", 1, 0 if crashing else 1),
                       deployment("coredns", "kube-system", 1, 1), deployment("staging-site", "default", 0, 0)]
        statefulsets = [deployment("jellyfin", "media", 1, 1), deployment("home-assistant", "home", 1, 1)]
        if widget_kind == "nodes":
            return self._node_rows(nodes, usage)
        if widget_kind == "pods":
            return self._pod_rows(pods, all_pods=options.get("all_pods") is True)
        if widget_kind == "workloads":
            return self._workload_rows(deployments, statefulsets, [], only_troubled=options.get("only_troubled") is True)
        return self._cluster(nodes, usage, pods, self._workload_rows(deployments, statefulsets, []), "v1.37.0+k3s1")


ADAPTER = KubernetesAdapter()
