"""Docker Engine API over the socket or TCP.

Covers plain Docker, Synology's Container Manager, Unraid's Docker and any
other host that exposes the engine socket. Talks HTTP to the engine directly
through httpx, without the docker SDK.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from . import containers as containers_one
from . import demo as fake
from .base import (
    Action,
    Adapter,
    AdapterError,
    Context,
    Field,
    Unreachable,
    WidgetData,
    WidgetType,
    human_bytes,
    outbound_client,
    path_segment,
    percent,
    status_from_percent,
)

DEFAULT_HOST = "unix:///var/run/docker.sock"
STATS_PARALLEL = 8

CONTAINER_ACTIONS = {
    "start": Action(id="start", label="Start", icon="play"),
    "stop": Action(id="stop", label="Stop", icon="square", confirm=True, danger=True),
    "restart": Action(id="restart", label="Restart", icon="rotate-cw", confirm=True),
    "pause": Action(id="pause", label="Pause", icon="pause"),
    "unpause": Action(id="unpause", label="Resume", icon="play"),
}


def docker_client(config: dict[str, Any]) -> httpx.AsyncClient:
    """A client bound to the configured engine address."""
    host = str(config.get("host") or DEFAULT_HOST).strip()
    if host.startswith("unix://"):
        transport = httpx.AsyncHTTPTransport(uds=host[len("unix://"):])
        # ⚠️ The one client that does not go anywhere by name: the socket is a
        # file, and "docker" in the address is a placeholder httpx needs, not a
        # host anybody resolves. The outbound guard would refuse it for that.
        return outbound_client(guard=False, transport=transport, base_url="http://docker", timeout=20)
    if host.startswith("tcp://"):
        host = "http://" + host[len("tcp://"):]
    verify = not bool(config.get("insecure"))
    return outbound_client(base_url=host.rstrip("/"), timeout=20, verify=verify)


def _client(config: dict[str, Any], ctx: Context) -> httpx.AsyncClient:
    client = ctx.cache.get("docker_client")
    if client is None or client.is_closed:
        client = docker_client(config)
        ctx.cache["docker_client"] = client
    return client


async def engine_get(config: dict[str, Any], ctx: Context, path: str, params: dict[str, Any] | None = None) -> Any:
    client = _client(config, ctx)
    try:
        response = await client.get(path, params=params)
    except httpx.HTTPError as error:
        raise Unreachable(f"The Docker engine could not be reached: {error.__class__.__name__}.") from error
    if response.status_code == 403:
        raise AdapterError("The Docker engine refused the request.", code="forbidden",
                           hint="Is the socket mounted read-only, or is a socket proxy blocking this call?")
    if response.status_code >= 400:
        raise AdapterError(f"The Docker engine answered with HTTP {response.status_code}.", code="http_error")
    return response.json()


async def engine_post(config: dict[str, Any], ctx: Context, path: str) -> None:
    client = _client(config, ctx)
    try:
        response = await client.post(path)
    except httpx.HTTPError as error:
        raise Unreachable(f"The Docker engine could not be reached: {error.__class__.__name__}.") from error
    if response.status_code == 304:
        return
    if response.status_code >= 400:
        detail = ""
        try:
            detail = response.json().get("message", "")
        except ValueError:
            pass
        raise AdapterError(detail or f"The Docker engine answered with HTTP {response.status_code}.", code="action_failed")


def container_name(entry: dict[str, Any]) -> str:
    names = entry.get("Names") or []
    return names[0].lstrip("/") if names else entry.get("Id", "")[:12]


def cpu_percent(stats: dict[str, Any]) -> float | None:
    cpu = stats.get("cpu_stats") or {}
    pre = stats.get("precpu_stats") or {}
    try:
        cpu_delta = cpu["cpu_usage"]["total_usage"] - pre["cpu_usage"]["total_usage"]
        system_delta = cpu["system_cpu_usage"] - pre["system_cpu_usage"]
    except (KeyError, TypeError):
        return None
    if system_delta <= 0 or cpu_delta < 0:
        return None
    cpus = cpu.get("online_cpus") or len((cpu.get("cpu_usage") or {}).get("percpu_usage") or []) or 1
    return round(cpu_delta / system_delta * cpus * 100, 1)


def memory_used(stats: dict[str, Any]) -> tuple[float | None, float | None]:
    memory = stats.get("memory_stats") or {}
    usage = memory.get("usage")
    if usage is None:
        return None, None
    inner = memory.get("stats") or {}
    cache = inner.get("inactive_file", inner.get("cache", 0)) or 0
    return float(usage - cache), float(memory.get("limit") or 0) or None


class DockerAdapter(Adapter):
    kind = "docker"
    label = "Docker"
    category = "hosts"
    description = "Containers with state, CPU and memory; start, stop and restart; logs."
    icon = "docker"
    #: Seen against a live Docker 29.7.2 through a TCP proxy (06.09.2026),
    #: containers, summary, load and the log tailer.
    beta = False
    docs_url = "https://docs.docker.com/engine/api/"
    fields = (
        Field("host", "Engine address", default=DEFAULT_HOST, required=True,
              help="unix:///var/run/docker.sock (mount it into the container) or tcp://host:2375.",
              placeholder=DEFAULT_HOST),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(
            kind="containers",
            label="Containers",
            description="Every container with its state, CPU and memory, plus start, stop and restart.",
            renderer="list",
            default_size=(4, 4),
            min_size=(2, 2),
            refresh_seconds=15,
            metrics=("running",),
            options=(
                Field("filter", "Name filter", placeholder="media-", help="Only containers whose name contains this."),
                Field("show_stopped", "Show stopped containers", type="bool", default=True),
                Field("stats", "Load CPU and memory", type="bool", default=True, help="Costs one request per running container."),
            ),
        ),
        containers_one.one_of("container", "One container",
                              "Everything one container reports: CPU, memory, network, disk and its state."),
        WidgetType(
            kind="summary",
            label="Container summary",
            description="Running, stopped and total, in one number.",
            renderer="value",
            default_size=(2, 1),
            min_size=(1, 1),
            refresh_seconds=20,
            metrics=("running",),
        ),
        WidgetType(
            kind="load",
            label="Docker load",
            description="Combined CPU and memory of all running containers.",
            renderer="stats",
            default_size=(3, 2),
            refresh_seconds=20,
            metrics=("cpu", "memory"),
        ),
        WidgetType(
            kind="logs",
            label="Container logs",
            description="Live tail of one container's log.",
            renderer="log",
            default_size=(6, 4),
            min_size=(3, 2),
            refresh_seconds=3600,
            options=(
                Field("container", "Container name", required=True, placeholder="radarr"),
                Field("lines", "Lines to keep", type="number", default=200),
            ),
        ),
    )

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        version = await engine_get(config, ctx, "/version")
        return f"Docker {version.get('Version', '?')} on {version.get('Os', '?')}/{version.get('Arch', '?')}."

    async def list_containers(self, config: dict[str, Any], ctx: Context) -> list[dict[str, Any]]:
        return await engine_get(config, ctx, "/containers/json", params={"all": 1})

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "logs":
            return WidgetData(meta={"container": options.get("container") or "", "lines": int(options.get("lines") or 200)})
        containers = await self.list_containers(config, ctx)
        if widget_kind == "container":
            return await self._one(config, options, ctx, containers)
        running = [c for c in containers if c.get("State") == "running"]
        if widget_kind == "summary":
            stopped = len(containers) - len(running)
            return WidgetData(
                status="warn" if stopped else "ok",
                primary={"label": "Running", "value": len(running), "unit": f"/ {len(containers)}"},
                secondary=[{"label": "Stopped", "value": stopped}],
                metrics={"running": float(len(running))},
            )
        stats = await self._stats(config, ctx, running) if (widget_kind == "load" or options.get("stats", True)) else {}
        if widget_kind == "load":
            cpu = round(sum(s[0] or 0 for s in stats.values()), 1)
            memory = sum(s[1] or 0 for s in stats.values())
            return WidgetData(
                status=status_from_percent(cpu, 300, 600),
                primary={"label": "CPU", "value": cpu, "unit": "%"},
                secondary=[
                    {"label": "Memory", "value": human_bytes(memory), "metric": "memory"},
                    {"label": "Containers", "value": len(running)},
                ],
                metrics={"cpu": cpu, "memory": memory / (1024 * 1024)},
                meta={"cpu_unit": "%", "memory_unit": "MB"},
            )
        needle = str(options.get("filter") or "").lower()
        items = []
        for entry in sorted(containers, key=container_name):
            name = container_name(entry)
            if needle and needle not in name.lower():
                continue
            state = entry.get("State", "unknown")
            if state != "running" and not options.get("show_stopped", True):
                continue
            item: dict[str, Any] = {
                "id": entry.get("Id", "")[:12],
                "title": name,
                "subtitle": entry.get("Status", ""),
                "image": entry.get("Image", ""),
                "status": {"running": "ok", "paused": "warn", "restarting": "warn"}.get(state, "bad"),
                "state": state,
                "actions": self._actions_for(state, entry.get("Id", "")),
            }
            usage = stats.get(entry.get("Id", ""))
            if usage:
                cpu, mem, limit = usage
                item["cpu"] = cpu
                item["memory"] = human_bytes(mem)
                item["memory_percent"] = percent(mem, limit)
                item["value"] = f"{cpu:.0f}%" if cpu is not None else ""
            items.append(item)
        stopped = [i for i in items if i["state"] != "running"]
        return WidgetData(
            status="warn" if stopped else "ok",
            items=items,
            secondary=[{"label": "Running", "value": len(items) - len(stopped)}, {"label": "Stopped", "value": len(stopped)}],
            metrics={"running": float(len(running))},
        )

    async def choices(self, field: str, config: dict[str, Any], ctx: Context) -> list[tuple[str, str]]:
        """The containers on this engine, for the field that picks one."""
        if field != "which":
            return []
        found = await self.list_containers(config, ctx)
        return [(container_name(entry), container_name(entry)) for entry in sorted(found, key=container_name)]

    async def _one(self, config: dict[str, Any], options: dict[str, Any], ctx: Context,
                   found: list[dict[str, Any]]) -> WidgetData:
        """One container, with everything the engine says about it.

        ⚠️ Held by name, not by id. A container keeps its name and gets a new
        id every time it is rebuilt, so a card pinned to an id would go blank
        the first time somebody pulled a new image.
        """
        wanted = str(options.get("which") or "").strip()
        if not wanted:
            raise AdapterError("No container picked yet.", code="nothing_picked",
                               hint="Pick one in the widget settings.")
        entry = next((one for one in found if container_name(one) == wanted), None)
        if entry is None:
            raise AdapterError(f"There is no container called {wanted!r} on this engine any more.",
                               code="gone", hint="It may have been renamed or removed.")
        state = str(entry.get("State", "unknown"))
        history = bool(options.get("history", True))
        cpu = used = limit = None
        extra: list[dict[str, Any]] = []
        if state == "running":
            try:
                stats = await engine_get(config, ctx, f"/containers/{entry['Id']}/stats", params={"stream": "false"})
            except AdapterError:
                stats = {}
            cpu = cpu_percent(stats)
            used, limit = memory_used(stats)
            # ⚠️ These four are in every answer the engine gives and were
            # thrown away by every card until now. They are the numbers people
            # open a container's page for.
            networks = (stats.get("networks") or {}).values()
            got_in = sum(float(one.get("rx_bytes") or 0) for one in networks)
            got_out = sum(float(one.get("tx_bytes") or 0) for one in networks)
            if networks:
                extra.append({"label": "Network in", "value": human_bytes(got_in)})
                extra.append({"label": "Network out", "value": human_bytes(got_out)})
            blocks = ((stats.get("blkio_stats") or {}).get("io_service_bytes_recursive") or [])
            read = sum(float(one.get("value") or 0) for one in blocks if str(one.get("op", "")).lower() == "read")
            wrote = sum(float(one.get("value") or 0) for one in blocks if str(one.get("op", "")).lower() == "write")
            if blocks:
                extra.append({"label": "Disk read", "value": human_bytes(read)})
                extra.append({"label": "Disk written", "value": human_bytes(wrote)})
            pids = (stats.get("pids_stats") or {}).get("current")
            if pids is not None:
                extra.append({"label": "Processes", "value": int(pids)})
        if entry.get("Status"):
            extra.append({"label": "Running since", "value": str(entry["Status"])})
        if entry.get("Image"):
            extra.append({"label": "Image", "value": str(entry["Image"])})
        return containers_one.card(
            title=wanted, state=state, ok_states=("running",),
            cpu=cpu, memory_used=used, memory_limit=limit,
            extra=extra, history=history,
            actions=self._actions_for(state, entry.get("Id", "")),
        )

    async def _stats(self, config: dict[str, Any], ctx: Context, running: list[dict[str, Any]]) -> dict[str, tuple[float | None, float | None, float | None]]:
        semaphore = asyncio.Semaphore(STATS_PARALLEL)

        async def one(entry: dict[str, Any]) -> tuple[str, tuple[float | None, float | None, float | None]]:
            async with semaphore:
                try:
                    stats = await engine_get(config, ctx, f"/containers/{entry['Id']}/stats", params={"stream": "false"})
                except AdapterError:
                    return entry["Id"], (None, None, None)
            used, limit = memory_used(stats)
            return entry["Id"], (cpu_percent(stats), used, limit)

        results = await asyncio.gather(*(one(c) for c in running))
        return dict(results)

    @staticmethod
    def _actions_for(state: str, container_id: str) -> list[dict[str, Any]]:
        if state == "running":
            names = ("restart", "stop", "pause")
        elif state == "paused":
            names = ("unpause", "stop")
        else:
            names = ("start",)
        actions = []
        for name in names:
            action = CONTAINER_ACTIONS[name].model_copy()
            action.params = {"id": container_id}
            actions.append(action.model_dump())
        return actions

    async def action(self, widget_kind: str, action_id: str, params: dict[str, Any], config: dict[str, Any],
                     options: dict[str, Any], ctx: Context) -> str:
        if action_id not in CONTAINER_ACTIONS:
            raise AdapterError("Unknown container action.", code="no_such_action")
        container_id = str(params.get("id") or "")
        if not container_id:
            raise AdapterError("No container was named.", code="missing_param")
        container_id = path_segment(container_id, "The container")
        await engine_post(config, ctx, f"/containers/{container_id}/{action_id}")
        return f"Container {action_id} sent."

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        if widget_kind == "container":
            return containers_one.demo_card(str(options.get("which") or "nexview"), tick)
        names = ["radarr", "sonarr", "jellyfin", "nexview", "sabnzbd", "pihole", "traefik", "postgres", "uptime-kuma", "nexmail"]
        if widget_kind == "logs":
            return WidgetData(meta={"container": options.get("container") or "radarr", "lines": 200})
        items = []
        running = 0
        for index, name in enumerate(names):
            down = name == "sabnzbd" and fake.flicker("sab-down", tick, 0.6)
            state = "exited" if down else "running"
            cpu = fake.walk(f"cpu-{name}", tick, 0.2, 18 if name != "jellyfin" else 65)
            mem = fake.walk(f"mem-{name}", tick, 60, 900) * 1024 * 1024
            if state == "running":
                running += 1
            items.append({
                "id": f"{index:012x}", "title": name, "subtitle": "Up 3 days" if state == "running" else "Exited (1) 4 minutes ago",
                "image": f"ghcr.io/example/{name}:latest", "status": "ok" if state == "running" else "bad", "state": state,
                "cpu": cpu if state == "running" else None, "memory": human_bytes(mem) if state == "running" else "",
                "memory_percent": percent(mem, 4 * 1024 ** 3) if state == "running" else 0,
                "value": f"{cpu:.0f}%" if state == "running" else "",
                "actions": self._actions_for(state, f"{index:012x}"),
            })
        if widget_kind == "summary":
            return WidgetData(
                status="warn" if running < len(names) else "ok",
                primary={"label": "Running", "value": running, "unit": f"/ {len(names)}"},
                secondary=[{"label": "Stopped", "value": len(names) - running}],
                metrics={"running": float(running)},
            )
        if widget_kind == "load":
            cpu = round(sum(i["cpu"] or 0 for i in items), 1)
            memory = sum(fake.walk(f"mem-{n}", tick, 60, 900) for n in names)
            return WidgetData(
                primary={"label": "CPU", "value": cpu, "unit": "%"},
                secondary=[{"label": "Memory", "value": f"{memory / 1024:.1f} GB", "metric": "memory"}, {"label": "Containers", "value": running}],
                metrics={"cpu": cpu, "memory": memory},
                meta={"cpu_unit": "%", "memory_unit": "MB"},
            )
        return WidgetData(
            status="warn" if running < len(names) else "ok",
            items=items,
            secondary=[{"label": "Running", "value": running}, {"label": "Stopped", "value": len(names) - running}],
            metrics={"running": float(running)},
        )


ADAPTER = DockerAdapter()
