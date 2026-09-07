"""Portainer: Docker through Portainer's API, for hosts that only expose that."""

from __future__ import annotations

from typing import Any

from . import containers as containers_one
from .base import (
    Adapter,
    AdapterError,
    Context,
    Field,
    WidgetData,
    WidgetType,
    base_url,
    human_bytes,
    path_segment,
)
from .docker import CONTAINER_ACTIONS, DockerAdapter, container_name, cpu_percent, memory_used


class PortainerAdapter(Adapter):
    kind = "portainer"
    label = "Portainer"
    category = "hosts"
    description = "Containers of a Portainer environment with start, stop and restart."
    icon = "portainer"
    docs_url = "https://app.swaggerhub.com/apis/portainer/portainer-ce/"
    #: Seen against a live Portainer 2.34 (05.09.2026).
    beta = False
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="https://portainer:9443"),
        Field("api_key", "Access token", type="password", secret=True, required=True, help="User menu > My account > Access tokens"),
        Field("endpoint_id", "Environment", type="text", default="",
              placeholder="automatically",
              help="Leave empty. Only needed when this Portainer manages several environments, and the test then names them."),
        Field("insecure", "Ignore TLS errors", type="bool", default=True),
    )
    widgets = (
        containers_one.one_of("container", "One container",
                              "Everything one container reports through Portainer: CPU, memory, network, disk and its state."),
        WidgetType(
            kind="containers",
            label="Containers",
            description="Every container of the environment with state and actions.",
            renderer="list",
            default_size=(4, 4),
            refresh_seconds=20,
            metrics=("running",),
            options=(Field("filter", "Name filter"), Field("show_stopped", "Show stopped containers", type="bool", default=True)),
        ),
        WidgetType(
            kind="summary",
            label="Environment summary",
            description="Running and stopped containers of the environment.",
            renderer="value",
            default_size=(2, 1),
            min_size=(1, 1),
            refresh_seconds=30,
            metrics=("running",),
        ),
    )

    def _headers(self, config: dict[str, Any]) -> dict[str, str]:
        return {"X-API-Key": str(config.get("api_key") or "")}

    def _wanted(self, config: dict[str, Any]) -> int | None:
        """The environment somebody typed, or None for "work it out"."""
        raw = str(config.get("endpoint_id") or "").strip()
        if not raw:
            return None
        try:
            return int(float(raw))
        except (TypeError, ValueError):
            return None

    async def _environments(self, config: dict[str, Any], ctx: Context, cache_seconds: int = 300) -> dict[int, str]:
        rows = await ctx.get_json(
            f"{base_url(config)}/api/endpoints", headers=self._headers(config),
            verify=not config.get("insecure", True), cache_seconds=cache_seconds,
        )
        found: dict[int, str] = {}
        for entry in rows if isinstance(rows, list) else []:
            try:
                found[int(entry.get("Id"))] = str(entry.get("Name") or "?")
            except (TypeError, ValueError):
                continue
        return found

    async def _endpoint(self, config: dict[str, Any], ctx: Context, cache_seconds: int = 300) -> int:
        """Which environment to talk to.

        ⚠️ This used to be a number field with a default of 1, and the
        connection test never looked at it. A Portainer whose environment is
        not number 1 tested green and every card went red a moment later,
        which is the worst possible order to learn it in. Now the field is
        empty by default and the adapter asks.
        """
        known = await self._environments(config, ctx, cache_seconds)
        wanted = self._wanted(config)
        if not known:
            raise AdapterError(
                "Portainer answers, but shows no environment.",
                code="no_environments",
                hint="Add an environment in Portainer, or check that the token may see it.",
            )
        if wanted is None:
            if len(known) == 1:
                return next(iter(known))
            raise AdapterError(
                "This Portainer manages several environments, so one has to be named.",
                code="which_environment",
                hint=f"Put one of these numbers in the environment field: {self._offer(known)}.",
            )
        if wanted not in known:
            raise AdapterError(
                f"Portainer has no environment {wanted}.",
                code="no_such_endpoint",
                hint=f"Available: {self._offer(known)}. Leave the field empty to let nexdeck pick when there is only one.",
            )
        return wanted

    @staticmethod
    def _offer(known: dict[int, str]) -> str:
        return ", ".join(f"{number} ({name})" for number, name in sorted(known.items()))

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        """Answers, and answers about the environment the cards will use.

        The test has to fail wherever a card would fail. A green test followed
        by a red card is worse than a red test.
        """
        known = await self._environments(config, ctx, cache_seconds=0)
        chosen = await self._endpoint(config, ctx, cache_seconds=0)
        if len(known) == 1:
            return f"Portainer answers. Environment {chosen} ({known[chosen]})."
        return f"Portainer answers. Using environment {chosen} ({known[chosen]}) of {self._offer(known)}."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        endpoint = await self._endpoint(config, ctx)
        containers = await ctx.get_json(
            f"{base_url(config)}/api/endpoints/{endpoint}/docker/containers/json", params={"all": 1},
            headers=self._headers(config), verify=not config.get("insecure", True), cache_seconds=5,
        )
        running = [c for c in containers if c.get("State") == "running"]
        if widget_kind == "container":
            return await self._one(config, options, ctx, containers, endpoint)
        if widget_kind == "summary":
            return WidgetData(
                status="warn" if len(running) < len(containers) else "ok",
                primary={"label": "Running", "value": len(running), "unit": f"/ {len(containers)}"},
                secondary=[{"label": "Stopped", "value": len(containers) - len(running)}],
                metrics={"running": float(len(running))},
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
            items.append({
                "id": entry.get("Id", "")[:12], "title": name, "subtitle": entry.get("Status", ""), "image": entry.get("Image", ""),
                "status": "ok" if state == "running" else ("warn" if state == "paused" else "bad"), "state": state,
                "actions": DockerAdapter._actions_for(state, entry.get("Id", "")),
            })
        return WidgetData(status="warn" if len(running) < len(containers) else "ok", items=items,
                          secondary=[{"label": "Running", "value": len(running)}, {"label": "Stopped", "value": len(containers) - len(running)}],
                          metrics={"running": float(len(running))})

    async def choices(self, field: str, config: dict[str, Any], ctx: Context) -> list[tuple[str, str]]:
        """The containers of the chosen environment, for the field that picks one."""
        if field != "which":
            return []
        endpoint = await self._endpoint(config, ctx)
        found = await ctx.get_json(
            f"{base_url(config)}/api/endpoints/{endpoint}/docker/containers/json", params={"all": 1},
            headers=self._headers(config), verify=not config.get("insecure", True), cache_seconds=5,
        )
        return [(container_name(one), container_name(one)) for one in sorted(found, key=container_name)]

    async def _one(self, config: dict[str, Any], options: dict[str, Any], ctx: Context,
                   found: list[dict[str, Any]], endpoint: str) -> WidgetData:
        """One container, through Portainer's Docker proxy.

        ⚠️ Portainer reaches the same engine, so the same numbers are there;
        the container cards simply never asked for them. Held by name, because
        an id changes every time a container is rebuilt.
        """
        wanted = str(options.get("which") or "").strip()
        if not wanted:
            raise AdapterError("No container picked yet.", code="nothing_picked",
                               hint="Pick one in the widget settings.")
        entry = next((one for one in found if container_name(one) == wanted), None)
        if entry is None:
            raise AdapterError(f"There is no container called {wanted!r} in this environment any more.",
                               code="gone", hint="It may have been renamed or removed.")
        state = str(entry.get("State", "unknown"))
        cpu = used = limit = None
        extra: list[dict[str, Any]] = []
        if state == "running":
            try:
                stats = await ctx.get_json(
                    f"{base_url(config)}/api/endpoints/{endpoint}/docker/containers/{entry['Id']}/stats",
                    params={"stream": "false"}, headers=self._headers(config),
                    verify=not config.get("insecure", True), cache_seconds=5,
                )
            except AdapterError:
                stats = {}
            cpu = cpu_percent(stats)
            used, limit = memory_used(stats)
            networks = (stats.get("networks") or {}).values()
            if networks:
                extra.append({"label": "Network in", "value": human_bytes(sum(float(one.get("rx_bytes") or 0) for one in networks))})
                extra.append({"label": "Network out", "value": human_bytes(sum(float(one.get("tx_bytes") or 0) for one in networks))})
            pids = (stats.get("pids_stats") or {}).get("current")
            if pids is not None:
                extra.append({"label": "Processes", "value": int(pids)})
        if entry.get("Status"):
            extra.append({"label": "Running since", "value": str(entry["Status"])})
        if entry.get("Image"):
            extra.append({"label": "Image", "value": str(entry["Image"])})
        return containers_one.card(
            title=wanted, state=state, ok_states=("running",),
            cpu=cpu, memory_used=used, memory_limit=limit, extra=extra,
            history=bool(options.get("history", True)),
            actions=DockerAdapter._actions_for(state, entry.get("Id", "")),
        )

    async def action(self, widget_kind: str, action_id: str, params: dict[str, Any], config: dict[str, Any], options: dict[str, Any], ctx: Context) -> str:
        if action_id not in CONTAINER_ACTIONS:
            raise AdapterError("Unknown container action.", code="no_such_action")
        container_id = path_segment(params.get("id"), "The container")
        response = await ctx.request(
            "POST", f"{base_url(config)}/api/endpoints/{await self._endpoint(config, ctx)}/docker/containers/{container_id}/{action_id}",
            headers=self._headers(config), verify=not config.get("insecure", True),
        )
        if response.status_code >= 400 and response.status_code != 304:
            raise AdapterError(f"Portainer answered with HTTP {response.status_code}.", code="http_error")
        return f"Container {action_id} sent."

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        if widget_kind == "container":
            return containers_one.demo_card(str(options.get("which") or "nexview"), tick, disk=False)
        data = DockerAdapter().demo("summary" if widget_kind == "summary" else "containers", options, tick)
        for item in data.items:
            item.pop("cpu", None)
            item.pop("memory", None)
            item.pop("memory_percent", None)
            item.pop("value", None)
        return data


ADAPTER = PortainerAdapter()
