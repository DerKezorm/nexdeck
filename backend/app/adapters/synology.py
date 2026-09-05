"""Synology DSM: utilisation, volumes, disks and the Container Manager's containers through the web API.

The container calls (``SYNO.Docker.Container``, ``SYNO.Docker.Container.Resource``)
and the guest details (``SYNO.Virtualization.Guest``) are not in Synology's
published guides; they are what the Container Manager and the Virtual Machine
Manager themselves use, observed on DSM 7 in September 2026. The VM actions
follow the published Virtual Machine Manager API guide.
"""

from __future__ import annotations

from typing import Any

from . import demo as fake
from .base import (
    Action,
    Adapter,
    AdapterError,
    AuthFailed,
    Context,
    Field,
    WidgetData,
    WidgetType,
    base_url,
    human_bytes,
    percent,
    status_from_percent,
)

ERRORS = {400: "wrong account or password", 401: "the account is disabled", 402: "permission denied", 403: "two-factor authentication is required", 404: "the two-factor code was wrong"}
API_ERRORS = {101: "a parameter is missing", 102: "the API does not exist on this DSM", 103: "the method does not exist on this DSM", 104: "the API version is not supported", 105: "the session lacks permission", 119: "the session expired"}
#: The Virtual Machine Manager counts memory in KB.
KB = 1024


class SynologyAdapter(Adapter):
    kind = "synology"
    #: Confirmed against a live instance on 2026-09-05.
    beta = False
    label = "Synology DSM"
    category = "nas"
    description = "CPU, memory, volumes, disk temperatures and health, plus the containers of the Container Manager."
    icon = "synology"
    docs_url = "https://global.download.synology.com/download/Document/Software/DeveloperGuide/Os/DSM/All/enu/DSM_Login_Web_API_Guide_enu.pdf"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="https://nas.local:5001"),
        Field("username", "User name", required=True, help="A dedicated user without two-factor authentication works best."),
        Field("password", "Password", type="password", secret=True, required=True),
        Field("insecure", "Ignore TLS errors", type="bool", default=True),
    )
    widgets = (
        WidgetType(
            kind="system",
            label="System",
            description="CPU, memory, temperature and the fullest volume.",
            renderer="stats",
            default_size=(4, 2),
            refresh_seconds=20,
            metrics=("cpu", "memory"),
        ),
        WidgetType(
            kind="volumes",
            label="Volumes",
            description="Every volume with usage and health.",
            renderer="list",
            default_size=(3, 2),
            refresh_seconds=300,
        ),
        WidgetType(
            kind="disks",
            label="Disks",
            description="Every disk with temperature and status.",
            renderer="list",
            default_size=(3, 3),
            refresh_seconds=120,
        ),
        WidgetType(
            kind="vms",
            label="Virtual machines",
            description="The VMs of the Virtual Machine Manager with state, CPU and memory, plus start, shutdown and restart.",
            renderer="list",
            default_size=(3, 2),
            refresh_seconds=30,
            metrics=("running",),
        ),
        WidgetType(
            kind="containers",
            label="Containers",
            description="The containers of the Container Manager with state, CPU and memory, plus start, stop and restart.",
            renderer="list",
            default_size=(3, 3),
            refresh_seconds=30,
            metrics=("running",),
            options=(
                Field("filter", "Name filter", help="Only containers whose name contains this."),
                Field("show_stopped", "Show stopped containers", type="bool", default=True),
            ),
        ),
    )

    async def _sid(self, config: dict[str, Any], ctx: Context, force: bool = False) -> str:
        sid = ctx.cache.get("syno_sid")
        if sid and not force:
            return sid
        payload = await ctx.get_json(
            f"{base_url(config)}/webapi/auth.cgi",
            params={"api": "SYNO.API.Auth", "version": "6", "method": "login", "account": config.get("username", ""),
                    "passwd": config.get("password", ""), "session": "nexdeck", "format": "sid"},
            verify=not config.get("insecure", True), cache_seconds=0,
        )
        if not payload.get("success"):
            code = int((payload.get("error") or {}).get("code", 0))
            raise AuthFailed(f"DSM refused the login: {ERRORS.get(code, f'error {code}')}.")
        sid = payload["data"]["sid"]
        ctx.cache["syno_sid"] = sid
        return sid

    async def _api(self, config: dict[str, Any], ctx: Context, api: str, method: str, version: str = "1", extra: dict[str, Any] | None = None, cache: float = 5, retry: bool = True) -> Any:
        sid = await self._sid(config, ctx)
        params = {"api": api, "version": version, "method": method, "_sid": sid}
        params.update(extra or {})
        payload = await ctx.get_json(f"{base_url(config)}/webapi/entry.cgi", params=params, verify=not config.get("insecure", True), cache_seconds=cache)
        if not payload.get("success"):
            code = int((payload.get("error") or {}).get("code", 0))
            if code in (105, 106, 107, 119) and retry:
                await self._sid(config, ctx, force=True)
                return await self._api(config, ctx, api, method, version, extra, cache, retry=False)
            reason = API_ERRORS.get(code, f"error {code}")
            raise AdapterError(f"DSM answered {api}.{method} with {reason}.", code="dsm_error")
        return payload.get("data")

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        info = await self._api(config, ctx, "SYNO.Core.System", "info", cache=0)
        return f"{info.get('model', 'DSM')} with DSM {info.get('firmware_ver', '?')} answers."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "containers":
            return await self._containers(config, options, ctx)
        if widget_kind == "vms":
            return await self._vms(config, ctx)
        if widget_kind == "system":
            util = await self._api(config, ctx, "SYNO.Core.System.Utilization", "get")
            info = await self._api(config, ctx, "SYNO.Core.System", "info", cache=60)
            storage = await self._api(config, ctx, "SYNO.Storage.CGI.Storage", "load_info", cache=120)
            cpu_block = util.get("cpu") or {}
            cpu = float(cpu_block.get("user_load", 0)) + float(cpu_block.get("system_load", 0)) + float(cpu_block.get("other_load", 0))
            memory = float((util.get("memory") or {}).get("real_usage", 0))
            volumes = storage.get("volumes") or []
            fullest = max((percent((v.get("size") or {}).get("used"), (v.get("size") or {}).get("total")) for v in volumes), default=0.0)
            temperature = info.get("temperature")
            return WidgetData(
                status=status_from_percent(max(cpu, memory, fullest)),
                primary={"label": "CPU", "value": round(cpu, 1), "unit": "%"},
                secondary=[
                    {"label": "Memory", "value": round(memory, 1), "unit": "%", "metric": "memory"},
                    {"label": "Volume", "value": fullest, "unit": "%"},
                    {"label": "Temp", "value": temperature, "unit": "°C"},
                ],
                metrics={"cpu": round(cpu, 1), "memory": round(memory, 1)},
            )
        storage = await self._api(config, ctx, "SYNO.Storage.CGI.Storage", "load_info", cache=60)
        if widget_kind == "volumes":
            items = []
            for volume in storage.get("volumes") or []:
                size = volume.get("size") or {}
                used = percent(size.get("used"), size.get("total"))
                items.append({
                    "title": volume.get("display_name") or volume.get("id", "?"),
                    "subtitle": f"{human_bytes(float(size.get('used') or 0))} of {human_bytes(float(size.get('total') or 0))} · {volume.get('status', '?')}",
                    "progress": used, "value": f"{used:.0f}%",
                    "status": "ok" if volume.get("status") == "normal" and used < 90 else "warn",
                })
            return WidgetData(items=items)
        items = []
        for disk in storage.get("disks") or []:
            items.append({
                "title": disk.get("name") or disk.get("id", "?"),
                "subtitle": f"{disk.get('model', '')} · {disk.get('status', '?')}",
                "value": f"{disk.get('temp', '?')} °C",
                "status": "ok" if disk.get("status") == "normal" else "bad",
            })
        return WidgetData(items=items)

    async def _containers(self, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        listing = await self._api(config, ctx, "SYNO.Docker.Container", "list", extra={"limit": "-1", "offset": "0", "type": "all"}, cache=10)
        resources = await self._api(config, ctx, "SYNO.Docker.Container.Resource", "get", cache=10)
        load = {row.get("name"): row for row in (resources or {}).get("resources") or []}
        needle = str(options.get("filter") or "").strip().lower()
        items: list[dict[str, Any]] = []
        running = stopped = 0
        for container in sorted((listing or {}).get("containers") or [], key=lambda c: (c.get("status") != "running", str(c.get("name") or "").lower())):
            name = str(container.get("name") or "?")
            if needle and needle not in name.lower():
                continue
            is_running = container.get("status") == "running"
            running += is_running
            stopped += not is_running
            if not is_running and not options.get("show_stopped", True):
                continue
            up_status = str(container.get("up_status") or container.get("status") or "")
            unhealthy = "(unhealthy)" in up_status
            for marker in (" (healthy)", " (unhealthy)"):
                up_status = up_status.replace(marker, "")
            parts = [str(container.get("image") or ""), up_status]
            if unhealthy:
                parts.append("unhealthy")
            usage = load.get(name) or {}
            item: dict[str, Any] = {
                "id": container.get("id") or name,
                "title": name,
                "subtitle": " · ".join(part for part in parts if part),
                "status": ("warn" if unhealthy else "ok") if is_running else "unknown",
                # The card sends an action's params back; the container's name rides along in them.
                "actions": [Action(id="stop", label="Stop", icon="square", confirm=True, params={"name": name}), Action(id="restart", label="Restart", icon="rotate-cw", confirm=True, params={"name": name})] if is_running else [Action(id="start", label="Start", icon="play", params={"name": name})],
            }
            if is_running and isinstance(usage.get("cpu"), (int, float)):
                item["cpu"] = round(float(usage["cpu"]), 1)
            if is_running and isinstance(usage.get("memoryPercent"), (int, float)):
                item["memory_percent"] = round(float(usage["memoryPercent"]), 1)
            if is_running and isinstance(usage.get("memory"), (int, float)):
                item["value"] = human_bytes(float(usage["memory"]))
            items.append(item)
        return WidgetData(
            status="warn" if any(item["status"] == "warn" for item in items) else "ok",
            items=items,
            secondary=[{"label": "Running", "value": running}, {"label": "Stopped", "value": stopped}],
            metrics={"running": float(running)},
            meta={"empty": "No containers"},
        )

    async def _vms(self, config: dict[str, Any], ctx: Context) -> WidgetData:
        """Every guest of the Virtual Machine Manager; usage comes from one detail call per running guest."""
        listing = await self._api(config, ctx, "SYNO.Virtualization.Guest", "list", version="2", cache=10)
        guests = sorted((listing or {}).get("guests") or [], key=lambda g: (g.get("status") != "running", str(g.get("name") or "").lower()))
        items: list[dict[str, Any]] = []
        running = 0
        for guest in guests:
            guest_id = str(guest.get("guest_id") or "")
            name = str(guest.get("name") or guest.get("guest_name") or "?")
            is_running = guest.get("status") == "running"
            running += is_running
            detail: dict[str, Any] = {}
            if is_running and guest_id:
                try:
                    detail = await self._api(config, ctx, "SYNO.Virtualization.Guest", "get", version="2", extra={"guest_id": guest_id}, cache=10) or {}
                except AdapterError:
                    detail = {}
            ram_total = float(guest.get("vram_size") or 0) * KB
            ram_used = float(detail.get("ram_used") or 0) * KB
            parts = [str(guest.get("host_name") or ""), f"{guest.get('vcpu_num', '?')} vCPU", f"{human_bytes(ram_total)} RAM"]
            if guest.get("ip"):
                parts.append(str(guest["ip"]))
            if not is_running:
                parts.append(str(guest.get("status") or "off"))
            healthy = str(guest.get("status_type") or "healthy") == "healthy"
            item: dict[str, Any] = {
                "id": guest_id or name,
                "title": name,
                "subtitle": " · ".join(part for part in parts if part),
                "status": ("ok" if healthy else "warn") if is_running else "unknown",
                "actions": [Action(id="shutdown", label="Shut down", icon="square", confirm=True, params={"guest_id": guest_id}), Action(id="reboot", label="Restart", icon="rotate-cw", confirm=True, params={"guest_id": guest_id})] if is_running else [Action(id="poweron", label="Start", icon="play", params={"guest_id": guest_id})],
            }
            usage = detail.get("vcpu_usage")
            if is_running and isinstance(usage, (int, float)):
                item["cpu"] = round(float(usage), 1)
            if is_running and ram_total > 0 and ram_used > 0:
                # The hypervisor's figure includes its own overhead and can exceed the configured size.
                item["memory_percent"] = min(100.0, round(100 * ram_used / ram_total, 1))
                item["value"] = human_bytes(ram_used)
            items.append(item)
        return WidgetData(
            status="warn" if any(item["status"] == "warn" for item in items) else "ok",
            items=items,
            secondary=[{"label": "Running", "value": running}, {"label": "Stopped", "value": len(items) - running}],
            metrics={"running": float(running)},
            meta={"empty": "No virtual machines"},
        )

    async def action(self, widget_kind: str, action_id: str, params: dict[str, Any], config: dict[str, Any], options: dict[str, Any], ctx: Context) -> str:
        if widget_kind == "vms":
            if action_id not in ("poweron", "shutdown", "reboot"):
                raise AdapterError("This widget has no such action.", code="no_such_action")
            guest_id = str(params.get("guest_id") or "")
            if not guest_id:
                raise AdapterError("Which virtual machine?", code="bad_params")
            await self._api(config, ctx, "SYNO.Virtualization.API.Guest.Action", action_id, extra={"guest_id": guest_id}, cache=0)
            return f"Virtual machine: {action_id} requested."
        if widget_kind != "containers" or action_id not in ("start", "stop", "restart"):
            raise AdapterError("This widget has no such action.", code="no_such_action")
        name = str(params.get("id") or params.get("name") or "")
        if not name:
            raise AdapterError("Which container?", code="bad_params")
        # start, stop and restart are all confirmed against a live Container Manager (DSM 7, September 2026).
        await self._api(config, ctx, "SYNO.Docker.Container", action_id, extra={"name": name}, cache=0)
        return f"{name}: {action_id} requested."

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        if widget_kind == "vms":
            rows = [("Home Assistant", "storage-nas · 2 vCPU · 4.0 GB RAM · 192.168.1.40", "ok", 12.0, 61.3, "2.5 GB"), ("Windows 11", "storage-nas · 4 vCPU · 16.0 GB RAM", "ok", 38.0, 72.9, "11.7 GB"), ("Lab", "storage-nas · 1 vCPU · 2.0 GB RAM · shutdown", "unknown", None, None, "")]
            items = []
            for name, subtitle, status, cpu, memory, size in rows:
                item: dict[str, Any] = {"id": name, "title": name, "subtitle": subtitle, "status": status, "value": size,
                                        "actions": [Action(id="shutdown", label="Shut down", icon="square", confirm=True, params={"guest_id": name}), Action(id="reboot", label="Restart", icon="rotate-cw", confirm=True, params={"guest_id": name})] if status != "unknown" else [Action(id="poweron", label="Start", icon="play", params={"guest_id": name})]}
                if cpu is not None:
                    item["cpu"] = round(fake.walk(f"syno-vm-{name}", tick, max(1.0, cpu - 8), cpu + 8), 1)
                    item["memory_percent"] = memory
                items.append(item)
            return WidgetData(status="ok", items=items, secondary=[{"label": "Running", "value": 2}, {"label": "Stopped", "value": 1}], metrics={"running": 2.0}, meta={"empty": "No virtual machines"})
        if widget_kind == "containers":
            rows = [("nexview", "ghcr.io/derkezorm/nexview:latest", "Up 3 days", "ok", 1.2, 8.4, "412.0 MB"), ("gotify", "gotify/server", "Up 3 days", "ok", 0.1, 0.3, "21.5 MB"), ("paperless", "ghcr.io/paperless-ngx/paperless-ngx", "Up 6 hours", "warn", 3.8, 12.1, "1.1 GB"), ("backup", "restic/restic", "Exited (0) 5 months ago", "unknown", None, None, "")]
            items = []
            for name, image, up, status, cpu, memory, size in rows:
                item: dict[str, Any] = {"id": name, "title": name, "subtitle": f"{image} · {up}" + (" · unhealthy" if status == "warn" else ""), "status": status, "value": size,
                                        "actions": [Action(id="stop", label="Stop", icon="square", confirm=True, params={"name": name}), Action(id="restart", label="Restart", icon="rotate-cw", confirm=True, params={"name": name})] if status != "unknown" else [Action(id="start", label="Start", icon="play", params={"name": name})]}
                if cpu is not None:
                    item["cpu"] = round(fake.walk(f"syno-c-{name}", tick, max(0.1, cpu - 1), cpu + 2), 1)
                    item["memory_percent"] = memory
                items.append(item)
            return WidgetData(status="warn", items=items, secondary=[{"label": "Running", "value": 3}, {"label": "Stopped", "value": 1}], metrics={"running": 3.0}, meta={"empty": "No containers"})
        cpu = fake.walk("syno-cpu", tick, 4, 22)
        memory = fake.walk("syno-mem", tick, 30, 38, period=600)
        if widget_kind == "system":
            return WidgetData(status="warn", primary={"label": "CPU", "value": cpu, "unit": "%"},
                              secondary=[{"label": "Memory", "value": memory, "unit": "%", "metric": "memory"}, {"label": "Volume", "value": 82.4, "unit": "%"}, {"label": "Temp", "value": int(fake.walk("syno-temp", tick, 39, 44, period=900)), "unit": "°C"}],
                              metrics={"cpu": cpu, "memory": memory})
        if widget_kind == "volumes":
            return WidgetData(items=[
                {"title": "Volume 1", "subtitle": "28.7 TB of 34.9 TB · normal", "progress": 82.4, "value": "82%", "status": "warn"},
                {"title": "Volume 2", "subtitle": "1.1 TB of 3.6 TB · normal", "progress": 30.2, "value": "30%", "status": "ok"},
            ])
        return WidgetData(items=[{"title": f"Drive {i + 1}", "subtitle": "WD Red Plus 12TB · normal", "value": f"{int(fake.walk(f'disk{i}', tick, 34, 41, period=900))} °C", "status": "ok"} for i in range(6)])


ADAPTER = SynologyAdapter()
