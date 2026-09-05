"""Glances: host metrics from its REST API (v4, v3 as a fallback)."""

from __future__ import annotations

from typing import Any

from . import demo as fake
from .base import (
    Adapter,
    AdapterError,
    Context,
    Field,
    WidgetData,
    WidgetType,
    base_url,
    human_bytes,
    status_from_percent,
)

#: Docker mounts three files into every container, and Glances reports each of
#: them as a file system with the host disk's size. Seen against Glances 4 in a
#: container: three identical rows above the real ones.
FILES_NOT_DISKS = {"/etc/resolv.conf", "/etc/hostname", "/etc/hosts"}


class GlancesAdapter(Adapter):
    kind = "glances"
    label = "Glances"
    category = "monitoring"
    description = "CPU, memory, load, disks and sensors of the host running Glances."
    icon = "glances"
    docs_url = "https://glances.readthedocs.io/en/latest/api.html"
    #: Seen against a live Glances 4 (05.09.2026).
    beta = False
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://glances:61208"),
        Field("username", "User name", help="Only if Glances runs with a password."),
        Field("password", "Password", type="password", secret=True),
        Field("api_version", "API version", type="select", default="4", options=(("4", "4 (Glances 4.x)"), ("3", "3 (Glances 3.x)"))),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(kind="system", label="System", description="CPU, memory, load and the first sensor.", renderer="stats", default_size=(4, 2), refresh_seconds=15, metrics=("cpu", "memory")),
        WidgetType(kind="disks", label="File systems", description="Every mounted file system with usage.", renderer="list", default_size=(3, 2), refresh_seconds=120),
        WidgetType(kind="sensors", label="Sensors", description="Temperatures and fans.", renderer="list", default_size=(3, 2), refresh_seconds=60),
    )

    async def _get(self, config: dict[str, Any], ctx: Context, name: str, cache: float = 5) -> Any:
        auth = (str(config["username"]), str(config.get("password") or "")) if config.get("username") else None
        version = config.get("api_version") or "4"
        return await ctx.get_json(f"{base_url(config)}/api/{version}/{name}", auth=auth, verify=not config.get("insecure"), cache_seconds=cache)

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        system = await self._get(config, ctx, "system", cache=0)
        return f"Glances on {system.get('hostname', '?')} ({system.get('os_name', '?')}) answers."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "system":
            quick = await self._get(config, ctx, "quicklook")
            mem = await self._get(config, ctx, "mem")
            load = await self._get(config, ctx, "load")
            cpu = round(float(quick.get("cpu") or 0), 1)
            memory = round(float(mem.get("percent") or 0), 1)
            secondary = [{"label": "Memory", "value": memory, "unit": "%", "metric": "memory"}, {"label": "Load", "value": round(float(load.get("min1") or 0), 2)}]
            try:
                sensors = await self._get(config, ctx, "sensors", cache=30)
                first = next((s for s in sensors if s.get("type") == "temperature_core" or s.get("unit") == "C"), None)
                if first:
                    secondary.append({"label": "Temp", "value": first.get("value"), "unit": "°C"})
            except AdapterError:
                pass
            return WidgetData(status=status_from_percent(max(cpu, memory)), primary={"label": "CPU", "value": cpu, "unit": "%"}, secondary=secondary, metrics={"cpu": cpu, "memory": memory})
        if widget_kind == "disks":
            items = []
            for fs in await self._get(config, ctx, "fs", cache=60):
                mount = str(fs.get("mnt_point") or "?")
                if mount in FILES_NOT_DISKS:
                    continue
                used = round(float(fs.get("percent") or 0), 1)
                items.append({"title": mount, "subtitle": f"{human_bytes(fs.get('used'))} of {human_bytes(fs.get('size'))}", "progress": used, "value": f"{used:.0f}%", "status": status_from_percent(used)})
            return WidgetData(items=items)
        items = []
        for sensor in await self._get(config, ctx, "sensors", cache=30):
            value = sensor.get("value")
            unit = {"C": "°C", "R": "rpm"}.get(sensor.get("unit", ""), sensor.get("unit", ""))
            items.append({"title": sensor.get("label", "?"), "subtitle": sensor.get("type", ""), "value": f"{value} {unit}".strip(), "status": "warn" if sensor.get("warning") and value and value >= sensor["warning"] else "ok"})
        return WidgetData(items=items)

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        cpu = fake.walk("gl-cpu", tick, 3, 38)
        memory = fake.walk("gl-mem", tick, 45, 60, period=600)
        if widget_kind == "system":
            return WidgetData(primary={"label": "CPU", "value": cpu, "unit": "%"}, secondary=[{"label": "Memory", "value": memory, "unit": "%", "metric": "memory"}, {"label": "Load", "value": round(cpu / 25, 2)}, {"label": "Temp", "value": int(fake.walk("gl-t", tick, 42, 58)), "unit": "°C"}], metrics={"cpu": cpu, "memory": memory})
        if widget_kind == "disks":
            return WidgetData(items=[{"title": "/", "subtitle": "41.2 GB of 98.0 GB", "progress": 42.0, "value": "42%", "status": "ok"}, {"title": "/mnt/data", "subtitle": "7.1 TB of 8.0 TB", "progress": 88.7, "value": "89%", "status": "warn"}])
        return WidgetData(items=[{"title": "Package id 0", "subtitle": "temperature_core", "value": f"{int(fake.walk('s0', tick, 42, 58))} °C", "status": "ok"}, {"title": "nvme", "subtitle": "temperature_hdd", "value": f"{int(fake.walk('s1', tick, 35, 44))} °C", "status": "ok"}, {"title": "fan1", "subtitle": "fan_speed", "value": f"{int(fake.walk('s2', tick, 800, 1400))} rpm", "status": "ok"}])


ADAPTER = GlancesAdapter()
