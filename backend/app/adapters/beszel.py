"""Beszel: lightweight host metrics through its PocketBase API."""

from __future__ import annotations

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
    duration_short,
    status_from_percent,
)


class BeszelAdapter(Adapter):
    kind = "beszel"
    label = "Beszel"
    category = "monitoring"
    description = "CPU, memory, disk and temperature of every host Beszel watches."
    icon = "beszel"
    #: Seen against a live Beszel 0.19 with an agent (06.09.2026).
    beta = False
    docs_url = "https://beszel.dev/"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://beszel:8090"),
        Field("username", "E-mail or user name", required=True),
        Field("password", "Password", type="password", secret=True, required=True),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(kind="systems", label="Hosts", description="Every host with CPU and memory.", renderer="list", default_size=(3, 3), refresh_seconds=30, metrics=("cpu",)),
        WidgetType(kind="system", label="Host", description="CPU, memory, disk and temperature of one host.", renderer="stats", default_size=(4, 2), refresh_seconds=30, metrics=("cpu", "memory"), options=(Field("system", "Host name", placeholder="nas", help="Empty means the first host."),)),
    )

    async def _token(self, config: dict[str, Any], ctx: Context, force: bool = False) -> str:
        token = ctx.cache.get("beszel_token")
        if token and not force:
            return token
        response = await ctx.request("POST", f"{base_url(config)}/api/collections/users/auth-with-password",
                                     json_body={"identity": config.get("username", ""), "password": config.get("password", "")},
                                     verify=not config.get("insecure"))
        if response.status_code >= 400:
            raise AuthFailed("Beszel rejected the user name or password.")
        token = response.json().get("token", "")
        ctx.cache["beszel_token"] = token
        return token

    async def _systems(self, config: dict[str, Any], ctx: Context, retry: bool = True) -> list[dict[str, Any]]:
        token = await self._token(config, ctx)
        response = await ctx.request("GET", f"{base_url(config)}/api/collections/systems/records", params={"perPage": 200}, headers={"Authorization": token}, verify=not config.get("insecure"), cache_seconds=10)
        if response.status_code in (401, 403) and retry:
            await self._token(config, ctx, force=True)
            return await self._systems(config, ctx, retry=False)
        if response.status_code >= 400:
            raise AdapterError(f"Beszel answered with HTTP {response.status_code}.", code="http_error")
        return response.json().get("items") or []

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        systems = await self._systems(config, ctx)
        return f"Beszel answers with {len(systems)} hosts."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        systems = await self._systems(config, ctx)
        if widget_kind == "system":
            wanted = str(options.get("system") or "").strip().lower()
            system = next((s for s in systems if not wanted or str(s.get("name", "")).lower() == wanted), None)
            if system is None:
                raise AdapterError(f"Beszel knows no host named {wanted!r}.", code="no_such_host")
            info = system.get("info") or {}
            cpu = round(float(info.get("cpu") or 0), 1)
            memory = round(float(info.get("mp") or 0), 1)
            disk = round(float(info.get("dp") or 0), 1)
            return WidgetData(
                status="bad" if system.get("status") != "up" else status_from_percent(max(cpu, memory, disk)),
                primary={"label": "CPU", "value": cpu, "unit": "%"},
                secondary=[{"label": "Memory", "value": memory, "unit": "%", "metric": "memory"}, {"label": "Disk", "value": disk, "unit": "%"}, {"label": "Uptime", "value": duration_short(info.get("u"))}],
                metrics={"cpu": cpu, "memory": memory},
            )
        items = []
        for system in sorted(systems, key=lambda s: s.get("name", "")):
            info = system.get("info") or {}
            up = system.get("status") == "up"
            items.append({"title": system.get("name", "?"), "subtitle": f"mem {float(info.get('mp') or 0):.0f}% · disk {float(info.get('dp') or 0):.0f}%" if up else str(system.get("status", "")),
                          "status": "ok" if up else "bad", "cpu": round(float(info.get("cpu") or 0), 1) if up else None, "value": f"{float(info.get('cpu') or 0):.0f}%" if up else ""})
        return WidgetData(status="bad" if any(i["status"] == "bad" for i in items) else "ok", items=items,
                          metrics={"cpu": max((float(s.get("info", {}).get("cpu") or 0) for s in systems), default=0.0)})

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        hosts = ["nas", "pve", "pi-hole", "vps"]
        if widget_kind == "system":
            cpu = fake.walk("bz-cpu", tick, 5, 45)
            memory = fake.walk("bz-mem", tick, 40, 70, period=600)
            return WidgetData(primary={"label": "CPU", "value": cpu, "unit": "%"}, secondary=[{"label": "Memory", "value": memory, "unit": "%", "metric": "memory"}, {"label": "Disk", "value": 61.3, "unit": "%"}, {"label": "Uptime", "value": "12d 4h"}], metrics={"cpu": cpu, "memory": memory})
        items = [{"title": h, "subtitle": f"mem {int(fake.walk(h + 'm', tick, 30, 80, period=600))}% · disk {40 + i * 11}%", "status": "ok", "cpu": fake.walk(h, tick, 2, 40), "value": f"{fake.walk(h, tick, 2, 40):.0f}%"} for i, h in enumerate(hosts)]
        return WidgetData(items=items, metrics={"cpu": max(i["cpu"] for i in items)})


ADAPTER = BeszelAdapter()
