"""Nomad: the jobs a cluster runs, the nodes under them, and a hand on the count.

Asked for in issue #2 by somebody running three nodes at home. Nomad is the
lighter answer to Kubernetes, and it is the one homelab orchestrator whose
workloads nexdeck could not see at all: the Docker card looks at one engine,
and a Nomad cluster hands its containers to whichever client has room.

⚠️ Written against Nomad's HTTP API documentation, not against a live cluster,
so the adapter stays ``beta`` until somebody has confirmed it against one. The
author of the issue offered a three-node cluster for exactly that.

What the documentation pins down, and what the issue got slightly wrong:

⚠️ Stopping a job is ``DELETE /v1/job/:id``, not a POST with ``Stop=true``.

⚠️ Scaling is ``POST /v1/job/:id/scale`` with ``Target.Group`` and ``Count``,
and **one of ``Message`` or ``Error`` has to be in the body** or the request is
refused. It answers 400 while a deployment of that job is running, which is
its own sentence on the card rather than "the service answered with an error".

⚠️ A node's live CPU and memory load is not in the server API. ``/v1/nodes``
knows a node's capacity, its status and whether it is draining; the real load
sits behind each client's own address (``/v1/client/stats``), one request per
node. The nodes card therefore shows what is **allocated** on a node, summed
from the allocations, and the rows say so. Allocated is not used: a job that
asks for 2000 MHz and idles fills the bar all the same.

⚠️ Everything is per namespace, and a token sees the namespaces it is allowed
to. The allocations behind the nodes card are asked for across all namespaces;
where the token may not have them, the rows show no allocated share at all
rather than the share of the one namespace this card carries, which would be a
number that looks right and is a third of the truth.

⚠️ Scaling is offered for service jobs. A system job runs one allocation per
client and has no count to move, and a batch job's count is the size of the
batch. The count itself is read at the moment the button is pressed, from
``/v1/job/:id/scale``, because the job list only carries how many allocations
are running, and running is not desired: a group of one whose allocation has
died reads as 0 running, and "scale down" from there would ask for -1.

⚠️ "Failed" comes from the allocations that exist now, not from the job
summary. The summary's Failed and Lost are a tally that never goes down: the
reporter's OpenBao read Failed 3 beside Running 1 while ``/v1/job/openbao/
allocations?all=true`` held one allocation, running, and the three failed
ones were gone altogether. Measured on his cluster, issue #2, 18.09.2026.
Counted as trouble is an allocation that failed or was lost, that Nomad still
wants running, and that nothing has replaced.
"""

from __future__ import annotations

from typing import Any

from . import demo as fake
from .base import (
    Action,
    Adapter,
    AdapterError,
    Ask,
    AuthFailed,
    Choice,
    Context,
    Field,
    WidgetData,
    WidgetType,
    base_url,
    human_bytes,
    measured,
    path_segment,
    percent,
    percent_text,
)

#: Which of a node's own words mean what, on the card.
NODE_STATUS = {"ready": "ok", "initializing": "warn", "down": "bad", "disconnected": "bad"}
#: The counts a job summary keeps per task group.
SUMMARY_KEYS = ("Running", "Starting", "Queued", "Complete", "Failed", "Lost")


def _namespace(config: dict[str, Any]) -> str:
    return str(config.get("namespace") or "").strip() or "default"


def _counts(job: dict[str, Any]) -> dict[str, int]:
    """One job's allocations by state, summed over its task groups."""
    groups = ((job.get("JobSummary") or {}).get("Summary") or {})
    totals = dict.fromkeys(SUMMARY_KEYS, 0)
    for group in groups.values():
        if isinstance(group, dict):
            for key in SUMMARY_KEYS:
                totals[key] += int(group.get(key) or 0)
    return totals


def _failures(allocations: list[dict[str, Any]]) -> dict[str, int]:
    """Per job, the allocations that failed or were lost and still stand."""
    found: dict[str, int] = {}
    for allocation in allocations:
        if not isinstance(allocation, dict):
            continue
        if str(allocation.get("ClientStatus") or "") not in ("failed", "lost"):
            continue
        # Replaced by a reschedule, or no longer wanted: history, not trouble.
        if allocation.get("NextAllocation") or str(allocation.get("DesiredStatus") or "run") != "run":
            continue
        key = str(allocation.get("JobID") or "")
        found[key] = found.get(key, 0) + 1
    return found


def _group_names(job: dict[str, Any]) -> list[str]:
    """The task groups of a job, from the summary the list already carries."""
    groups = ((job.get("JobSummary") or {}).get("Summary") or {})
    return sorted(name for name, entry in groups.items() if isinstance(entry, dict))


def _allocated(allocation: dict[str, Any]) -> tuple[float, float]:
    """What one allocation asked for: CPU in MHz, memory in MB.

    ⚠️ Per task, not per allocation. ``AllocatedResources.Tasks`` holds one
    entry for each task of the group, and a group of three sidecars that each
    ask for 500 MHz occupies 1500 of the node.
    """
    resources = (allocation.get("AllocatedResources") or {}).get("Tasks") or {}
    cpu = 0.0
    memory = 0.0
    for task in resources.values():
        if not isinstance(task, dict):
            continue
        cpu += float((task.get("Cpu") or {}).get("CpuShares") or 0)
        memory += float((task.get("Memory") or {}).get("MemoryMB") or 0)
    return cpu, memory


class NomadAdapter(Adapter):
    kind = "nomad"
    label = "Nomad"
    category = "hosts"
    description = "The jobs of a Nomad cluster, the nodes under them, and buttons to stop or scale a job."
    icon = "nomad"
    docs_url = "https://developer.hashicorp.com/nomad/api-docs"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://nomad:4646",
              help="The address of a Nomad server, port 4646 by default."),
        Field("token", "ACL token", type="password", secret=True,
              help="Sent as X-Nomad-Token. Leave it empty on a cluster without ACLs. Reading needs node:read and namespace:read-job; the buttons need namespace:scale-job for scaling and namespace:submit-job for stopping."),
        Field("namespace", "Namespace", default="default",
              help="* for every namespace the token may see."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(
            kind="jobs",
            label="Jobs",
            description="Every job with its state and how many allocations run, the troubled ones first, with buttons to stop or scale it.",
            renderer="list",
            default_size=(3, 3),
            refresh_seconds=30,
            metrics=("running", "failed"),
            options=(
                Field("limit", "Entries", type="number", default=10),
                Field("show_dead", "Show stopped and finished jobs", type="bool", default=True),
            ),
        ),
        WidgetType(
            kind="nodes",
            label="Nodes",
            description="The clients of the cluster with their state and how much of them is allocated.",
            renderer="list",
            default_size=(3, 3),
            refresh_seconds=60,
            metrics=("nodes_ready", "cpu_percent"),
            options=(Field("limit", "Entries", type="number", default=10),),
        ),
        WidgetType(
            kind="summary",
            label="Cluster",
            description="How many jobs run, how many are in trouble, and how many clients are ready.",
            renderer="value",
            default_size=(2, 2),
            min_size=(1, 1),
            refresh_seconds=60,
            metrics=("running", "failed", "nodes_ready"),
        ),
    )

    # -- talking to Nomad ----------------------------------------------------

    def _headers(self, config: dict[str, Any]) -> dict[str, str] | None:
        token = str(config.get("token") or "").strip()
        return {"X-Nomad-Token": token} if token else None

    @staticmethod
    def _said(response: Any) -> str:
        """Nomad's own words about a refusal.

        ⚠️ Plain text, not JSON: a wrong token reads "ACL token not found", a
        token without the right rule "Permission denied". Those two sentences
        are the difference between a typo and a missing policy, and neither
        survives being replaced by "the service answered with an error".
        """
        return " ".join(str(getattr(response, "text", "") or "").split())[:200]

    async def _request(self, method: str, path: str, config: dict[str, Any], ctx: Context, *,
                       params: dict[str, Any] | None = None, json_body: Any = None, cache: float = 0) -> Any:
        query = {"namespace": _namespace(config)}
        query.update(params or {})
        response = await ctx.request(
            method,
            f"{base_url(config)}/v1{path}",
            headers=self._headers(config),
            params=query,
            json_body=json_body,
            verify=not config.get("insecure"),
            cache_seconds=cache if method.upper() == "GET" else 0,
            auth_errors=False,
        )
        if response.status_code in (401, 403):
            said = self._said(response)
            raise AuthFailed(f"Nomad turned the token down: {said}" if said else "Nomad turned the token down.")
        if response.status_code == 404:
            raise AdapterError("Nomad does not know this job or address any more.", code="not_found",
                               hint="Check the URL; it is the address of a Nomad server, without /v1.")
        if response.status_code >= 400:
            said = self._said(response)
            raise AdapterError(f"Nomad refused: {said}" if said else f"Nomad answered with HTTP {response.status_code}.",
                               code="http_error")
        return response

    async def _json(self, path: str, config: dict[str, Any], ctx: Context, *,
                    params: dict[str, Any] | None = None, cache: float = 15) -> Any:
        response = await self._request("GET", path, config, ctx, params=params, cache=cache)
        try:
            return response.json()
        except ValueError as error:
            raise AdapterError("Nomad did not answer with data.", code="not_json",
                               hint="The URL probably points at something else than a Nomad server.") from error

    async def _jobs(self, config: dict[str, Any], ctx: Context) -> list[dict[str, Any]]:
        answer = await self._json("/jobs", config, ctx, params={"meta": "false"})
        if not isinstance(answer, list):
            raise AdapterError("This address answers, but not the way Nomad does.", code="not_nomad")
        return [job for job in answer if isinstance(job, dict)]

    async def _nodes(self, config: dict[str, Any], ctx: Context) -> list[dict[str, Any]]:
        # ⚠️ Namespaces do not apply to nodes, and Nomad ignores the parameter
        # here; it goes along because one place assembles every request.
        answer = await self._json("/nodes", config, ctx, params={"resources": "true"}, cache=30)
        if not isinstance(answer, list):
            raise AdapterError("This address answers, but not the way Nomad does.", code="not_nomad")
        return [node for node in answer if isinstance(node, dict)]

    async def _allocations(self, config: dict[str, Any], ctx: Context) -> list[dict[str, Any]] | None:
        """Every running allocation with what it asked for, or nothing at all.

        Nothing means the token may not read across namespaces. The nodes card
        then shows no allocated share, which is the honest answer: the share of
        one namespace on a node is not the node's share.
        """
        try:
            answer = await self._json(
                "/allocations", config, ctx,
                params={"namespace": "*", "resources": "true", "task_states": "false"}, cache=30,
            )
        except AuthFailed:
            return None
        if not isinstance(answer, list):
            return None
        return [one for one in answer if isinstance(one, dict) and one.get("ClientStatus") == "running"]

    async def _failed(self, config: dict[str, Any], ctx: Context) -> dict[str, int]:
        answer = await self._json("/allocations", config, ctx, params={"task_states": "false"}, cache=15)
        return _failures(answer if isinstance(answer, list) else [])

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        jobs = await self._jobs(config, ctx)
        nodes = await self._nodes(config, ctx)
        ready = sum(1 for node in nodes if node.get("Status") == "ready")
        return f"Nomad answers with {len(jobs)} jobs in the namespace {_namespace(config)} and {ready} of {len(nodes)} clients ready."

    # -- the cards -----------------------------------------------------------

    def _job_item(self, job: dict[str, Any], failed: int) -> dict[str, Any]:
        totals = _counts(job)
        identifier = str(job.get("ID") or job.get("Name") or "")
        kind = str(job.get("Type") or "service")
        state = str(job.get("Status") or "")
        waiting = totals["Queued"] + totals["Starting"]
        if failed:
            status = "bad"
            word = f"{failed} failed"
        elif state == "dead":
            # A dead job was stopped by hand or, for a batch, has run out of
            # work. The first is worth a colour, the second is the normal end.
            status = "ok" if kind == "batch" else "warn"
            word = "finished" if kind == "batch" else "stopped"
        elif waiting:
            status = "warn"
            word = f"{waiting} waiting"
        elif totals["Running"]:
            status = "ok"
            word = f"{totals['Running']} running"
        else:
            status = "warn"
            word = state or "nothing running"
        return {
            "id": identifier,
            "title": str(job.get("Name") or identifier),
            "subtitle": f"{kind} · {word}",
            "status": status,
            "value": str(totals["Running"]),
            # ⚠️ Its own field, not a word in the subtitle. The switch that
            # hides stopped jobs reads this, and reading it off the sentence
            # would break the day the sentence is worded differently.
            "state": state,
            "actions": self._actions_for(job),
        }

    def _actions_for(self, job: dict[str, Any]) -> list[dict[str, Any]]:
        identifier = str(job.get("ID") or job.get("Name") or "")
        if not identifier:
            return []
        params = {"job": identifier}
        actions = []
        if str(job.get("Status") or "") != "dead":
            actions.append(Action(id="stop", label="Stop", icon="square", confirm=True, danger=True,
                                  params=dict(params)).model_dump())
        if str(job.get("Type") or "service") == "service":
            groups = _group_names(job)
            for action_id, label, icon in (("scale_up", "Scale up", "plus"), ("scale_down", "Scale down", "minus")):
                action = Action(id=action_id, label=label, icon=icon, confirm=True, params=dict(params))
                if len(groups) == 1:
                    action.params["group"] = groups[0]
                elif len(groups) > 1:
                    # ⚠️ A pick list rather than a guess. Every group of a job
                    # has a count of its own, and scaling "the job" would move
                    # whichever one happened to be first.
                    action.asks = [Ask(name="group", label="Task group", kind="choice",
                                       options=[Choice(value=name, label=name) for name in groups])]
                else:
                    continue
                actions.append(action.model_dump())
        return actions

    def _jobs_card(self, jobs: list[dict[str, Any]], failures: dict[str, int], options: dict[str, Any]) -> WidgetData:
        items = [self._job_item(job, failures.get(str(job.get("ID") or ""), 0)) for job in jobs]
        if not options.get("show_dead", True):
            items = [item for item in items if item["state"] != "dead"]
        order = {"bad": 0, "warn": 1, "unknown": 2, "ok": 3}
        items.sort(key=lambda item: (order.get(item["status"], 4), item["title"]))
        limit = max(1, int(options.get("limit") or 10))
        running = sum(_counts(job)["Running"] for job in jobs)
        failed = sum(failures.get(str(job.get("ID") or ""), 0) for job in jobs)
        return WidgetData(
            status="bad" if failed else ("warn" if any(item["status"] == "warn" for item in items) else "ok"),
            items=items[:limit],
            secondary=[
                {"label": "Jobs", "value": len(items)},
                {"label": "Allocations running", "value": running},
            ],
            metrics=measured({"running": float(running), "failed": float(failed)}),
        )

    def _nodes_card(self, nodes: list[dict[str, Any]], allocations: list[dict[str, Any]] | None,
                    options: dict[str, Any]) -> WidgetData:
        per_node: dict[str, tuple[float, float, int]] = {}
        if allocations is not None:
            for allocation in allocations:
                key = str(allocation.get("NodeID") or "")
                cpu, memory = _allocated(allocation)
                before = per_node.get(key, (0.0, 0.0, 0))
                per_node[key] = (before[0] + cpu, before[1] + memory, before[2] + 1)
        items = []
        cluster_cpu = 0.0
        cluster_capacity = 0.0
        ready = 0
        for node in sorted(nodes, key=lambda node: str(node.get("Name") or "")):
            state = str(node.get("Status") or "")
            status = NODE_STATUS.get(state, "unknown")
            words = [str(node.get("Datacenter") or ""), state or "?"]
            if node.get("Drain"):
                status = "warn" if status == "ok" else status
                words.append("draining")
            elif str(node.get("SchedulingEligibility") or "eligible") != "eligible":
                status = "warn" if status == "ok" else status
                words.append("ineligible")
            if state == "ready":
                ready += 1
            resources = node.get("NodeResources") or {}
            capacity = float((resources.get("Cpu") or {}).get("CpuShares") or 0)
            memory_total = float((resources.get("Memory") or {}).get("MemoryMB") or 0) * 1024 * 1024
            # ⚠️ A node with nothing on it is measured, not unknown: the
            # allocations were read, and none of them sit here. Only a
            # refusal, which arrives as ``allocations is None``, means the
            # share cannot be told.
            allocated = per_node.get(str(node.get("ID") or ""), (0.0, 0.0, 0)) if allocations is not None else None
            item: dict[str, Any] = {
                "id": str(node.get("ID") or "")[:8],
                "title": str(node.get("Name") or node.get("ID") or "?"),
                "subtitle": " · ".join(word for word in words if word),
                "status": status,
            }
            share = None
            if allocated is not None:
                share = percent(allocated[0], capacity)
                item["cpu"] = share
                item["memory"] = human_bytes(allocated[1] * 1024 * 1024)
                item["memory_percent"] = percent(allocated[1] * 1024 * 1024, memory_total)
                item["subtitle"] += f" · {allocated[2]} allocations"
                cluster_cpu += allocated[0]
                cluster_capacity += capacity
            item["value"] = percent_text(share)
            items.append(item)
        limit = max(1, int(options.get("limit") or 10))
        rows = [{"label": "Clients ready", "value": f"{ready} of {len(items)}"}]
        if allocations is None:
            # ⚠️ Said out loud. A row of "?" with no reason looks like a card
            # that is broken rather than a token that may read one namespace.
            rows.append({"label": "Allocated", "value": "unknown: the token reads one namespace"})
        return WidgetData(
            status="bad" if any(item["status"] == "bad" for item in items)
            else ("warn" if any(item["status"] == "warn" for item in items) else "ok"),
            items=items[:limit],
            secondary=rows,
            metrics=measured({
                "nodes_ready": float(ready),
                "cpu_percent": percent(cluster_cpu, cluster_capacity) if allocations is not None else None,
            }),
        )

    @staticmethod
    def _summary_card(jobs: list[dict[str, Any]], nodes: list[dict[str, Any]], failures: dict[str, int]) -> WidgetData:
        running = 0
        waiting = 0
        for job in jobs:
            totals = _counts(job)
            running += totals["Running"]
            waiting += totals["Queued"] + totals["Starting"]
        failed = sum(failures.get(str(job.get("ID") or ""), 0) for job in jobs)
        ready = sum(1 for node in nodes if node.get("Status") == "ready")
        down = [node for node in nodes if NODE_STATUS.get(str(node.get("Status") or ""), "unknown") == "bad"]
        return WidgetData(
            status="bad" if failed or down else ("warn" if waiting or ready < len(nodes) else "ok"),
            primary={"label": "Allocations running", "value": running},
            secondary=[
                {"label": "Jobs", "value": len(jobs)},
                {"label": "Failed", "value": failed},
                {"label": "Clients ready", "value": f"{ready} of {len(nodes)}"},
            ],
            metrics=measured({"running": float(running), "failed": float(failed), "nodes_ready": float(ready)}),
        )

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "jobs":
            return self._jobs_card(await self._jobs(config, ctx), await self._failed(config, ctx), options)
        if widget_kind == "nodes":
            nodes = await self._nodes(config, ctx)
            return self._nodes_card(nodes, await self._allocations(config, ctx), options)
        return self._summary_card(await self._jobs(config, ctx), await self._nodes(config, ctx), await self._failed(config, ctx))

    # -- the buttons ---------------------------------------------------------

    async def action(self, widget_kind: str, action_id: str, params: dict[str, Any],
                     config: dict[str, Any], options: dict[str, Any], ctx: Context) -> str:
        identifier = path_segment(params.get("job"), "The job")
        if action_id == "stop":
            await self._request("DELETE", f"/job/{identifier}", config, ctx)
            ctx.forget_answers()
            return f"Job {identifier} stopped."
        if action_id not in ("scale_up", "scale_down"):
            raise AdapterError("Nomad has no such action.", code="no_such_action")
        group = path_segment(params.get("group"), "The task group")
        status = await self._json(f"/job/{identifier}/scale", config, ctx, cache=0)
        groups = (status or {}).get("TaskGroups") or {}
        if group not in groups or not isinstance(groups[group], dict):
            raise AdapterError(f"The job {identifier} has no task group {group}.", code="bad_param")
        desired = int(groups[group].get("Desired") or 0)
        target = desired + (1 if action_id == "scale_up" else -1)
        if target < 0:
            raise AdapterError(f"The group {group} is already at zero.", code="bad_param",
                               hint="Scale up to start it again.")
        await self._request(
            "POST", f"/job/{identifier}/scale", config, ctx,
            # ⚠️ Nomad refuses a scale request that carries neither Message nor
            # Error, and the message is kept with the scaling event, so this is
            # what somebody reading the job's history a week later will see.
            json_body={"Count": target, "Target": {"Group": group}, "Message": "scaled from nexdeck"},
        )
        ctx.forget_answers()
        return f"Task group {group} of {identifier} scaled from {desired} to {target}."

    # -- demo ----------------------------------------------------------------

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        jobs = [
            {"ID": "jellyfin", "Name": "jellyfin", "Type": "service", "Status": "running",
             "JobSummary": {"Summary": {"web": {"Running": 1}}}},
            {"ID": "whisper", "Name": "whisper", "Type": "service", "Status": "running",
             "JobSummary": {"Summary": {"gpu": {"Running": 0}}}},
            {"ID": "nightly-backup", "Name": "nightly-backup", "Type": "batch", "Status": "dead",
             "JobSummary": {"Summary": {"restic": {"Complete": 1}}}},
            {"ID": "traefik", "Name": "traefik", "Type": "system", "Status": "running",
             "JobSummary": {"Summary": {"proxy": {"Running": 3}}}},
            {"ID": "paperless", "Name": "paperless", "Type": "service", "Status": "running",
             "JobSummary": {"Summary": {"web": {"Running": 1}, "worker": {"Running": 2}}}},
        ]
        failures: dict[str, int] = {}
        if fake.flicker("nomad-job", tick, 0.1):
            jobs[4]["JobSummary"] = {"Summary": {"web": {"Running": 1}, "worker": {"Running": 1, "Failed": 1}}}
            failures["paperless"] = 1
        nodes = [
            {"ID": "aa11" + "0" * 28, "Name": "mac-mini", "Status": "ready", "Datacenter": "home",
             "SchedulingEligibility": "eligible", "NodeResources": {"Cpu": {"CpuShares": 24000}, "Memory": {"MemoryMB": 16384}}},
            {"ID": "bb22" + "0" * 28, "Name": "nuc", "Status": "ready", "Datacenter": "home",
             "SchedulingEligibility": "eligible", "NodeResources": {"Cpu": {"CpuShares": 12000}, "Memory": {"MemoryMB": 32768}}},
            {"ID": "cc33" + "0" * 28, "Name": "pi", "Status": "ready", "Datacenter": "home",
             "SchedulingEligibility": "eligible", "Drain": fake.flicker("nomad-drain", tick, 0.08),
             "NodeResources": {"Cpu": {"CpuShares": 6000}, "Memory": {"MemoryMB": 8192}}},
        ]
        if widget_kind == "summary":
            return self._summary_card(jobs, nodes, failures)
        if widget_kind == "jobs":
            return self._jobs_card(jobs, failures, options)
        allocations = []
        for index, node in enumerate(nodes):
            capacity = float(node["NodeResources"]["Cpu"]["CpuShares"])
            share = fake.walk(f"nomad-node{index}", tick, 18, 74) / 100
            allocations.append({
                "NodeID": node["ID"], "ClientStatus": "running",
                "AllocatedResources": {"Tasks": {"task": {
                    "Cpu": {"CpuShares": capacity * share},
                    "Memory": {"MemoryMB": float(node["NodeResources"]["Memory"]["MemoryMB"]) * share},
                }}},
            })
        return self._nodes_card(nodes, allocations, options)


ADAPTER = NomadAdapter()
