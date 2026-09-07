"""Proxmox VE: nodes, VMs and containers, with start, shutdown and reboot."""

from __future__ import annotations

from typing import Any

from . import demo as fake
from .base import (
    Action,
    Adapter,
    AdapterError,
    Context,
    Field,
    WidgetData,
    WidgetType,
    base_url,
    duration_short,
    human_bytes,
    path_segment,
    percent,
    status_from_percent,
)


class ProxmoxAdapter(Adapter):
    kind = "proxmox"
    label = "Proxmox VE"
    category = "hosts"
    description = "Node load, VMs and containers, start and stop."
    icon = "proxmox"
    docs_url = "https://pve.proxmox.com/wiki/Proxmox_VE_API"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="https://pve.example.com:8006"),
        Field("token_id", "API token ID", required=True, placeholder="nexdeck@pve!dashboard", help="Datacenter > Permissions > API Tokens. PVEAuditor is enough for reading."),
        Field("token_secret", "API token secret", type="password", secret=True, required=True),
        Field("insecure", "Ignore TLS errors", type="bool", default=True, help="Most installations use a self-signed certificate."),
    )
    widgets = (
        WidgetType(
            kind="node",
            label="Node",
            description="CPU, memory, storage and uptime of one node.",
            renderer="stats",
            default_size=(4, 2),
            refresh_seconds=20,
            metrics=("cpu", "memory"),
            options=(Field("node", "Node name", placeholder="pve", help="Empty means the first node."),),
        ),
        WidgetType(
            kind="guests",
            label="VMs and containers",
            description="Every guest with state and load, plus start, shutdown and reboot.",
            renderer="list",
            default_size=(4, 4),
            refresh_seconds=20,
            metrics=("running",),
            options=(
                Field("node", "Node name", placeholder="pve", help="Empty means all nodes."),
                Field("show_stopped", "Show stopped guests", type="bool", default=True),
            ),
        ),
        WidgetType(
            kind="summary",
            label="Cluster summary",
            description="Running guests and nodes in one number.",
            renderer="value",
            default_size=(2, 1),
            min_size=(1, 1),
            refresh_seconds=30,
            metrics=("running",),
        ),
    )

    def _headers(self, config: dict[str, Any]) -> dict[str, str]:
        return {"Authorization": f"PVEAPIToken={config.get('token_id', '')}={config.get('token_secret', '')}"}

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, cache: float = 5) -> Any:
        payload = await ctx.get_json(f"{base_url(config)}/api2/json{path}", headers=self._headers(config), verify=not config.get("insecure", True), cache_seconds=cache)
        return payload.get("data")

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        version = await self._get(config, ctx, "/version", cache=0)
        nodes = await self._get(config, ctx, "/nodes", cache=0)
        return f"Proxmox VE {version.get('version', '?')} with {len(nodes or [])} node(s)."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        nodes = await self._get(config, ctx, "/nodes") or []
        if widget_kind == "node":
            wanted = str(options.get("node") or "").strip()
            node = next((n for n in nodes if not wanted or n.get("node") == wanted), None)
            if node is None:
                raise AdapterError(f"There is no node named {wanted!r}.", code="no_such_node")
            cpu = round(float(node.get("cpu") or 0) * 100, 1)
            memory = percent(node.get("mem"), node.get("maxmem"))
            disk = percent(node.get("disk"), node.get("maxdisk"))
            return WidgetData(
                status="bad" if node.get("status") != "online" else status_from_percent(max(cpu, memory)),
                primary={"label": "CPU", "value": cpu, "unit": "%"},
                secondary=[
                    {"label": "Memory", "value": memory, "unit": "%", "metric": "memory"},
                    {"label": "Storage", "value": disk, "unit": "%"},
                    {"label": "Uptime", "value": duration_short(node.get("uptime"))},
                ],
                metrics={"cpu": cpu, "memory": memory},
                meta={"node": node.get("node")},
            )
        guests = await self._get(config, ctx, "/cluster/resources?type=vm") or []
        running = [g for g in guests if g.get("status") == "running"]
        if widget_kind == "summary":
            return WidgetData(
                primary={"label": "Running guests", "value": len(running), "unit": f"/ {len(guests)}"},
                secondary=[{"label": "Nodes", "value": len(nodes)}, {"label": "Online", "value": sum(1 for n in nodes if n.get("status") == "online")}],
                metrics={"running": float(len(running))},
            )
        wanted = str(options.get("node") or "").strip()
        items = []
        for guest in sorted(guests, key=lambda g: (g.get("node", ""), g.get("name", ""))):
            if wanted and guest.get("node") != wanted:
                continue
            state = guest.get("status", "unknown")
            if state != "running" and not options.get("show_stopped", True):
                continue
            item = {
                "id": f"{guest.get('node')}/{guest.get('type')}/{guest.get('vmid')}",
                "title": guest.get("name") or str(guest.get("vmid")),
                "subtitle": f"{'LXC' if guest.get('type') == 'lxc' else 'VM'} {guest.get('vmid')} · {guest.get('node')}" + (f" · {human_bytes(guest.get('mem'))}" if state == "running" else ""),
                "status": "ok" if state == "running" else "bad",
                "state": state,
                "actions": self._actions(state, guest),
            }
            if state == "running":
                item["cpu"] = round(float(guest.get("cpu") or 0) * 100, 1)
                item["memory_percent"] = percent(guest.get("mem"), guest.get("maxmem"))
            items.append(item)
        return WidgetData(status="ok", items=items, secondary=[{"label": "Running", "value": len(running)}, {"label": "Total", "value": len(guests)}], metrics={"running": float(len(running))})

    @staticmethod
    def _actions(state: str, guest: dict[str, Any]) -> list[dict[str, Any]]:
        params = {"node": guest.get("node"), "type": guest.get("type"), "vmid": guest.get("vmid")}
        if state == "running":
            return [
                Action(id="reboot", label="Reboot", icon="rotate-cw", confirm=True, params=params).model_dump(),
                Action(id="shutdown", label="Shut down", icon="square", confirm=True, danger=True, params=params).model_dump(),
            ]
        return [Action(id="start", label="Start", icon="play", params=params).model_dump()]

    async def action(self, widget_kind: str, action_id: str, params: dict[str, Any], config: dict[str, Any], options: dict[str, Any], ctx: Context) -> str:
        if action_id not in ("start", "shutdown", "reboot"):
            raise AdapterError("Unknown action.", code="no_such_action")
        node, kind, vmid = params.get("node"), params.get("type"), params.get("vmid")
        if not (node and kind and vmid):
            raise AdapterError("The guest was not named completely.", code="missing_param")
        node, kind, vmid = path_segment(node, "The node"), path_segment(kind, "The guest type"), path_segment(vmid, "The guest number")
        response = await ctx.request("POST", f"{base_url(config)}/api2/json/nodes/{node}/{kind}/{vmid}/status/{action_id}", headers=self._headers(config), verify=not config.get("insecure", True))
        if response.status_code >= 400:
            raise AdapterError(f"Proxmox answered with HTTP {response.status_code}.", code="http_error", hint="The token may lack the VM.PowerMgmt privilege.")
        return f"{action_id.capitalize()} sent to {vmid}."

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        cpu = fake.walk("pve-cpu", tick, 8, 41)
        memory = fake.walk("pve-mem", tick, 55, 68, period=600)
        if widget_kind == "node":
            return WidgetData(primary={"label": "CPU", "value": cpu, "unit": "%"},
                              secondary=[{"label": "Memory", "value": memory, "unit": "%", "metric": "memory"}, {"label": "Storage", "value": 44.2, "unit": "%"}, {"label": "Uptime", "value": duration_short(41 * 86400 + tick)}],
                              metrics={"cpu": cpu, "memory": memory}, meta={"node": "pve"})
        guests = [("media", "qemu", 101), ("homeassistant", "qemu", 102), ("pihole", "lxc", 201), ("nexdeck", "lxc", 202), ("backup", "lxc", 203), ("windows-test", "qemu", 110)]
        items = []
        running = 0
        for _index, (name, kind, vmid) in enumerate(guests):
            state = "stopped" if name == "windows-test" else "running"
            running += state == "running"
            guest = {"node": "pve", "type": kind, "vmid": vmid}
            item = {"id": f"pve/{kind}/{vmid}", "title": name, "subtitle": f"{'LXC' if kind == 'lxc' else 'VM'} {vmid} · pve", "status": "ok" if state == "running" else "bad", "state": state, "actions": self._actions(state, guest)}
            if state == "running":
                item["cpu"] = fake.walk(f"pve-{name}", tick, 0.3, 25 if kind == "lxc" else 60)
                item["memory_percent"] = fake.walk(f"pve-{name}-m", tick, 20, 80, period=500)
            items.append(item)
        if widget_kind == "summary":
            return WidgetData(primary={"label": "Running guests", "value": running, "unit": f"/ {len(guests)}"}, secondary=[{"label": "Nodes", "value": 1}, {"label": "Online", "value": 1}], metrics={"running": float(running)})
        return WidgetData(items=items, secondary=[{"label": "Running", "value": running}, {"label": "Total", "value": len(guests)}], metrics={"running": float(running)})


ADAPTER = ProxmoxAdapter()
