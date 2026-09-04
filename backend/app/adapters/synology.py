"""Synology DSM: utilisation, volumes and disks through the web API."""

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
    human_bytes,
    percent,
    status_from_percent,
)

ERRORS = {400: "wrong account or password", 401: "the account is disabled", 402: "permission denied", 403: "two-factor authentication is required", 404: "the two-factor code was wrong"}


class SynologyAdapter(Adapter):
    kind = "synology"
    label = "Synology DSM"
    category = "nas"
    description = "CPU, memory, network, volumes, disk temperatures and health."
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
            raise AdapterError(f"DSM answered {api} with error {code}.", code="dsm_error")
        return payload.get("data")

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        info = await self._api(config, ctx, "SYNO.Core.System", "info", cache=0)
        return f"{info.get('model', 'DSM')} with DSM {info.get('firmware_ver', '?')} answers."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
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

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
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
