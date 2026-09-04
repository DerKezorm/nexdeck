"""Unraid through its GraphQL API (Unraid 7 with the API plugin or built-in)."""

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
    percent,
    status_from_percent,
)

QUERY = """
{
  info { os { uptime } cpu { brand } }
  metrics { cpu { percentTotal } memory { percentTotal used total } }
  array { state capacity { kilobytes { used total free } } parities { name status temp } disks { name status temp fsSize fsUsed } }
  docker { containers { names state } }
  vms { domain { name state } }
}
"""


class UnraidAdapter(Adapter):
    kind = "unraid"
    label = "Unraid"
    category = "nas"
    description = "Array, disks, CPU, memory, containers and VMs through the GraphQL API."
    icon = "unraid"
    docs_url = "https://docs.unraid.net/API/"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="https://tower.local"),
        Field("api_key", "API key", type="password", secret=True, required=True, help="Settings > Management Access > API Keys"),
        Field("insecure", "Ignore TLS errors", type="bool", default=True),
    )
    widgets = (
        WidgetType(kind="system", label="System", description="CPU, memory, array usage and uptime.", renderer="stats", default_size=(4, 2), refresh_seconds=20, metrics=("cpu", "memory")),
        WidgetType(kind="array", label="Array disks", description="Every array disk with usage, temperature and status.", renderer="list", default_size=(3, 3), refresh_seconds=120),
        WidgetType(kind="guests", label="Containers and VMs", description="Running and stopped containers and VMs.", renderer="value", default_size=(2, 2), min_size=(1, 1), refresh_seconds=30, metrics=("running",)),
    )

    async def _query(self, config: dict[str, Any], ctx: Context, cache: float = 5) -> dict[str, Any]:
        key = "unraid:last"
        hit = ctx.cache.get(key)
        import time

        if hit and hit[0] > time.monotonic() and cache:
            return hit[1]
        response = await ctx.request(
            "POST", f"{base_url(config)}/graphql", json_body={"query": QUERY},
            headers={"x-api-key": str(config.get("api_key") or ""), "Content-Type": "application/json"},
            verify=not config.get("insecure", True),
        )
        if response.status_code >= 400:
            raise AdapterError(f"Unraid answered with HTTP {response.status_code}.", code="http_error")
        payload = response.json()
        if payload.get("errors"):
            raise AdapterError(str(payload["errors"][0].get("message", "Unraid refused the query.")), code="graphql_error",
                               hint="The API key may lack read permissions for some resources.")
        data = payload.get("data") or {}
        ctx.cache[key] = (time.monotonic() + cache, data)
        return data

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        data = await self._query(config, ctx, cache=0)
        return f"Unraid answers, array is {((data.get('array') or {}).get('state') or '?')}."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        data = await self._query(config, ctx)
        metrics = data.get("metrics") or {}
        array = data.get("array") or {}
        if widget_kind == "system":
            cpu = round(float((metrics.get("cpu") or {}).get("percentTotal") or 0), 1)
            memory = round(float((metrics.get("memory") or {}).get("percentTotal") or 0), 1)
            kb = (array.get("capacity") or {}).get("kilobytes") or {}
            used = percent(float(kb.get("used") or 0), float(kb.get("total") or 0))
            uptime = ((data.get("info") or {}).get("os") or {}).get("uptime") or ""
            return WidgetData(
                status="bad" if array.get("state") not in ("STARTED", "started", None) else status_from_percent(max(cpu, memory, used)),
                primary={"label": "CPU", "value": cpu, "unit": "%"},
                secondary=[{"label": "Memory", "value": memory, "unit": "%", "metric": "memory"}, {"label": "Array", "value": used, "unit": "%"}, {"label": "Since", "value": str(uptime)[:10]}],
                metrics={"cpu": cpu, "memory": memory},
            )
        if widget_kind == "array":
            items = []
            for disk in list(array.get("parities") or []) + list(array.get("disks") or []):
                used = percent(float(disk.get("fsUsed") or 0), float(disk.get("fsSize") or 0)) if disk.get("fsSize") else None
                item = {"title": disk.get("name", "?"), "subtitle": str(disk.get("status", "")), "value": f"{disk.get('temp', '?')} °C", "status": "ok" if str(disk.get("status", "")).upper().startswith("DISK_OK") else "warn"}
                if used is not None:
                    item["progress"] = used
                items.append(item)
            return WidgetData(items=items)
        containers = (data.get("docker") or {}).get("containers") or []
        vms = ((data.get("vms") or {}).get("domain") or [])
        running_c = sum(1 for c in containers if str(c.get("state", "")).upper() == "RUNNING")
        running_v = sum(1 for v in vms if str(v.get("state", "")).upper() == "RUNNING")
        return WidgetData(
            primary={"label": "Containers running", "value": running_c, "unit": f"/ {len(containers)}"},
            secondary=[{"label": "VMs", "value": f"{running_v} / {len(vms)}"}],
            metrics={"running": float(running_c)},
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        cpu = fake.walk("unraid-cpu", tick, 6, 35)
        memory = fake.walk("unraid-mem", tick, 40, 52, period=600)
        if widget_kind == "system":
            return WidgetData(primary={"label": "CPU", "value": cpu, "unit": "%"},
                              secondary=[{"label": "Memory", "value": memory, "unit": "%", "metric": "memory"}, {"label": "Array", "value": 71.3, "unit": "%"}, {"label": "Since", "value": "2026-07-19"}],
                              metrics={"cpu": cpu, "memory": memory})
        if widget_kind == "array":
            return WidgetData(items=[{"title": n, "subtitle": "DISK_OK", "value": f"{int(fake.walk(n, tick, 33, 40, period=900))} °C", "status": "ok", "progress": p} for n, p in [("parity", 0), ("disk1", 88), ("disk2", 64), ("disk3", 41), ("cache", 55)]])
        return WidgetData(primary={"label": "Containers running", "value": 14, "unit": "/ 16"}, secondary=[{"label": "VMs", "value": "2 / 3"}], metrics={"running": 14.0})


ADAPTER = UnraidAdapter()
