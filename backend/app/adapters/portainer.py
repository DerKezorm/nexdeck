"""Portainer: Docker through Portainer's API, for hosts that only expose that."""

from __future__ import annotations

from typing import Any

from .base import Adapter, AdapterError, Context, Field, WidgetData, WidgetType, base_url
from .docker import CONTAINER_ACTIONS, DockerAdapter, container_name


class PortainerAdapter(Adapter):
    kind = "portainer"
    label = "Portainer"
    category = "hosts"
    description = "Containers of a Portainer environment with start, stop and restart."
    icon = "portainer"
    docs_url = "https://app.swaggerhub.com/apis/portainer/portainer-ce/"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="https://portainer:9443"),
        Field("api_key", "Access token", type="password", secret=True, required=True, help="User menu > My account > Access tokens"),
        Field("endpoint_id", "Environment ID", type="number", default=1, help="Environments list, the number in the URL."),
        Field("insecure", "Ignore TLS errors", type="bool", default=True),
    )
    widgets = (
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

    def _endpoint(self, config: dict[str, Any]) -> int:
        try:
            return int(float(config.get("endpoint_id") or 1))
        except (TypeError, ValueError):
            return 1

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        endpoints = await ctx.get_json(f"{base_url(config)}/api/endpoints", headers=self._headers(config), verify=not config.get("insecure", True), cache_seconds=0)
        names = ", ".join(f"{e.get('Id')}: {e.get('Name')}" for e in endpoints)
        return f"Portainer answers. Environments: {names or 'none'}."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        endpoint = self._endpoint(config)
        containers = await ctx.get_json(
            f"{base_url(config)}/api/endpoints/{endpoint}/docker/containers/json", params={"all": 1},
            headers=self._headers(config), verify=not config.get("insecure", True), cache_seconds=5,
        )
        running = [c for c in containers if c.get("State") == "running"]
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

    async def action(self, widget_kind: str, action_id: str, params: dict[str, Any], config: dict[str, Any], options: dict[str, Any], ctx: Context) -> str:
        if action_id not in CONTAINER_ACTIONS:
            raise AdapterError("Unknown container action.", code="no_such_action")
        container_id = str(params.get("id") or "")
        if not container_id:
            raise AdapterError("No container was named.", code="missing_param")
        response = await ctx.request(
            "POST", f"{base_url(config)}/api/endpoints/{self._endpoint(config)}/docker/containers/{container_id}/{action_id}",
            headers=self._headers(config), verify=not config.get("insecure", True),
        )
        if response.status_code >= 400 and response.status_code != 304:
            raise AdapterError(f"Portainer answered with HTTP {response.status_code}.", code="http_error")
        return f"Container {action_id} sent."

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        data = DockerAdapter().demo("summary" if widget_kind == "summary" else "containers", options, tick)
        for item in data.items:
            item.pop("cpu", None)
            item.pop("memory", None)
            item.pop("memory_percent", None)
            item.pop("value", None)
        return data


ADAPTER = PortainerAdapter()
