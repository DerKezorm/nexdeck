"""Unraid through its GraphQL API (Unraid 7 with the API plugin or built-in).

⚠️ **One part at a time.** The five parts the cards read, ``info``,
``metrics``, ``array``, ``docker`` and ``vms``, are all declared non-null on
Unraid's ``Query`` type. GraphQL answers an error in a non-null field by
nulling its parent, and at the top that is the whole answer: ``data: null``.
So when a single part failed, a switched-off VM service or a key that may not
read Docker, every card of the connection showed the same error, including
the ones that never needed that part (issue #3 is a candidate). Each part is
now its own request, the cards ask only for what they show, and a part that
fails leaves a question mark where it belonged instead of taking the rest
along.
"""

from __future__ import annotations

import asyncio
import time
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
    worst,
)

#: One query per top-level part, so that one refusal cannot null the others.
PARTS = {
    "info": "{ info { os { uptime } cpu { brand } } }",
    "metrics": "{ metrics { cpu { percentTotal } memory { percentTotal used total } } }",
    "array": "{ array { state capacity { kilobytes { used total free } } parities { name status temp } disks { name status temp fsSize fsUsed } } }",
    "docker": "{ docker { containers { names state } } }",
    "vms": "{ vms { domain { name state } } }",
}

#: What each card reads; the first part is the one it cannot do without.
NEEDS = {
    "system": ("metrics", "array", "info"),
    "array": ("array",),
    "guests": ("docker", "vms"),
}


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

    async def _part(self, config: dict[str, Any], ctx: Context, part: str, cache: float) -> Any:
        """One part of the answer, or the AdapterError that explains why not."""
        key = f"unraid:{part}"
        hit = ctx.cache.get(key)
        if cache and hit and hit[0] > time.monotonic():
            return hit[1]
        response = await ctx.request(
            "POST", f"{base_url(config)}/graphql", json_body={"query": PARTS[part]},
            headers={"x-api-key": str(config.get("api_key") or ""), "Content-Type": "application/json"},
            verify=not config.get("insecure", True),
        )
        if response.status_code >= 400:
            raise AdapterError(f"Unraid answered with HTTP {response.status_code}.", code="http_error")
        payload = response.json()
        value = (payload.get("data") or {}).get(part)
        if value is None:
            errors = payload.get("errors") or [{}]
            raise AdapterError(f"Unraid refused the {part} part: {errors[0].get('message') or 'no data'}", code="graphql_error",
                               hint="The API key may lack read permission for it, or the service behind it is switched off.")
        ctx.cache[key] = (time.monotonic() + cache, value)
        return value

    async def _parts(self, config: dict[str, Any], ctx: Context, parts: tuple[str, ...], cache: float = 5) -> dict[str, Any]:
        """Each part asked for, as its value or as the error it failed with."""
        answers = await asyncio.gather(*(self._part(config, ctx, part, cache) for part in parts), return_exceptions=True)
        found: dict[str, Any] = {}
        for part, answer in zip(parts, answers, strict=True):
            # Anything but a readable refusal (a cancelled task, a bug) is not ours to hide.
            if isinstance(answer, BaseException) and not isinstance(answer, AdapterError):
                raise answer
            found[part] = answer
        return found

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        found = await self._parts(config, ctx, tuple(PARTS), cache=0)
        failed = [part for part, value in found.items() if isinstance(value, AdapterError)]
        if len(failed) == len(found):
            raise found[failed[0]]
        array = found["array"] if not isinstance(found["array"], AdapterError) else {}
        text = f"Unraid answers, array is {array.get('state') or '?'}."
        if failed:
            text += " Not readable: " + "; ".join(found[part].message for part in failed)
        return text

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        needs = NEEDS.get(widget_kind, NEEDS["guests"])
        found = await self._parts(config, ctx, needs)
        # Without its first part a card has nothing to show; the others may be missing.
        if isinstance(found[needs[0]], AdapterError):
            raise found[needs[0]]

        def part(name: str) -> dict[str, Any] | None:
            value = found.get(name)
            return None if isinstance(value, AdapterError) else (value or {})

        if widget_kind == "system":
            metrics = part("metrics") or {}
            array = part("array")
            info = part("info")
            cpu = round(float((metrics.get("cpu") or {}).get("percentTotal") or 0), 1)
            memory = round(float((metrics.get("memory") or {}).get("percentTotal") or 0), 1)
            used = None
            if array is not None:
                kb = (array.get("capacity") or {}).get("kilobytes") or {}
                used = percent(float(kb.get("used") or 0), float(kb.get("total") or 0))
            uptime = ((info or {}).get("os") or {}).get("uptime") or ""
            stopped = array is not None and array.get("state") not in ("STARTED", "started", None)
            return WidgetData(
                status="bad" if stopped else status_from_percent(worst(cpu, memory, used)),
                primary={"label": "CPU", "value": cpu, "unit": "%"},
                secondary=[
                    {"label": "Memory", "value": memory, "unit": "%", "metric": "memory"},
                    {"label": "Array", "value": used, "unit": "%"} if used is not None else {"label": "Array", "value": "?"},
                    {"label": "Since", "value": str(uptime)[:10] if info is not None else "?"},
                ],
                metrics={"cpu": cpu, "memory": memory},
            )
        if widget_kind == "array":
            array = part("array") or {}
            items = []
            for disk in list(array.get("parities") or []) + list(array.get("disks") or []):
                used = percent(float(disk.get("fsUsed") or 0), float(disk.get("fsSize") or 0)) if disk.get("fsSize") else None
                item = {"title": disk.get("name", "?"), "subtitle": str(disk.get("status", "")), "value": f"{disk.get('temp', '?')} °C", "status": "ok" if str(disk.get("status", "")).upper().startswith("DISK_OK") else "warn"}
                if used is not None:
                    item["progress"] = used
                items.append(item)
            return WidgetData(items=items)
        containers = (part("docker") or {}).get("containers") or []
        running_c = sum(1 for c in containers if str(c.get("state", "")).upper() == "RUNNING")
        vms = part("vms")
        if vms is None:
            # A switched-off VM service is an ordinary Unraid, not a broken card.
            vm_text = "?"
        else:
            domains = vms.get("domain") or []
            vm_text = f"{sum(1 for v in domains if str(v.get('state', '')).upper() == 'RUNNING')} / {len(domains)}"
        return WidgetData(
            primary={"label": "Containers running", "value": running_c, "unit": f"/ {len(containers)}"},
            secondary=[{"label": "VMs", "value": vm_text}],
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
