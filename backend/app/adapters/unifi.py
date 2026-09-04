"""UniFi Network: clients, devices and WAN throughput.

Talks to the controller's classic API with a local account (UniFi OS consoles
use ``/proxy/network``). Cookie and CSRF token live in the integration cache.
"""

from __future__ import annotations

from typing import Any

import httpx

from . import demo as fake
from .base import (
    Adapter,
    AdapterError,
    AuthFailed,
    Context,
    Field,
    Unreachable,
    WidgetData,
    WidgetType,
    base_url,
    human_rate,
)


class UnifiAdapter(Adapter):
    kind = "unifi"
    label = "UniFi Network"
    category = "network"
    description = "Connected clients, access points and switches, WAN traffic."
    icon = "unifi"
    docs_url = "https://ubntwiki.com/products/software/unifi-controller/api"
    fields = (
        Field("url", "Controller URL", type="url", required=True, placeholder="https://192.168.1.1"),
        Field("username", "User name", required=True, help="A local account without two-factor authentication."),
        Field("password", "Password", type="password", secret=True, required=True),
        Field("site", "Site", default="default"),
        Field("unifi_os", "UniFi OS console", type="bool", default=True, help="On for a Dream Machine or Cloud Key Gen2; off for the classic controller software."),
        Field("insecure", "Ignore TLS errors", type="bool", default=True),
    )
    widgets = (
        WidgetType(kind="summary", label="Network", description="Clients, devices and WAN throughput.", renderer="stats", default_size=(3, 2), refresh_seconds=30, metrics=("clients", "wan_down", "wan_up")),
        WidgetType(kind="devices", label="Devices", description="Access points, switches and gateways with state and load.", renderer="list", default_size=(3, 3), refresh_seconds=60),
    )

    def _client(self, config: dict[str, Any], ctx: Context) -> httpx.AsyncClient:
        client = ctx.cache.get("unifi_client")
        if client is None or client.is_closed:
            client = httpx.AsyncClient(base_url=base_url(config), verify=not config.get("insecure", True), timeout=15)
            ctx.cache["unifi_client"] = client
        return client

    def _prefix(self, config: dict[str, Any]) -> str:
        return "/proxy/network" if config.get("unifi_os", True) else ""

    async def _login(self, config: dict[str, Any], ctx: Context) -> None:
        client = self._client(config, ctx)
        path = "/api/auth/login" if config.get("unifi_os", True) else "/api/login"
        try:
            response = await client.post(path, json={"username": config.get("username", ""), "password": config.get("password", ""), "remember": True})
        except httpx.HTTPError as error:
            raise Unreachable(f"The UniFi controller could not be reached: {error.__class__.__name__}.") from error
        if response.status_code >= 400:
            raise AuthFailed("The UniFi controller rejected the user name or password.")
        ctx.cache["unifi_csrf"] = response.headers.get("x-csrf-token", "")

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, retry: bool = True) -> list[dict[str, Any]]:
        client = self._client(config, ctx)
        site = config.get("site") or "default"
        try:
            response = await client.get(f"{self._prefix(config)}/api/s/{site}{path}", headers={"x-csrf-token": ctx.cache.get("unifi_csrf", "")})
        except httpx.HTTPError as error:
            raise Unreachable(f"The UniFi controller could not be reached: {error.__class__.__name__}.") from error
        if response.status_code in (401, 403) and retry:
            await self._login(config, ctx)
            return await self._get(config, ctx, path, retry=False)
        if response.status_code >= 400:
            raise AdapterError(f"The UniFi controller answered with HTTP {response.status_code}.", code="http_error")
        return response.json().get("data") or []

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        health = await self._get(config, ctx, "/stat/health")
        return f"UniFi answers, {len(health)} subsystems reported."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        devices = await self._get(config, ctx, "/stat/device")
        if widget_kind == "devices":
            items = []
            for device in sorted(devices, key=lambda d: d.get("name") or d.get("model", "")):
                state = int(device.get("state") or 0)
                kind = {"uap": "Access point", "usw": "Switch", "ugw": "Gateway", "udm": "Console"}.get(device.get("type", ""), device.get("type", ""))
                subtitle = f"{kind} · {device.get('model', '')}"
                if device.get("num_sta") is not None:
                    subtitle += f" · {device.get('num_sta')} clients"
                items.append({"title": device.get("name") or device.get("model", "?"), "subtitle": subtitle, "status": "ok" if state == 1 else "bad",
                              "value": f"{round(float((device.get('system-stats') or {}).get('cpu') or 0))}% cpu" if device.get("system-stats") else ""})
            return WidgetData(items=items, status="bad" if any(i["status"] == "bad" for i in items) else "ok")
        health = await self._get(config, ctx, "/stat/health")
        clients = await self._get(config, ctx, "/stat/sta")
        wan = next((h for h in health if h.get("subsystem") == "wan"), {})
        wlan = next((h for h in health if h.get("subsystem") == "wlan"), {})
        down = float(wan.get("rx_bytes-r") or 0)
        up = float(wan.get("tx_bytes-r") or 0)
        offline = sum(1 for d in devices if int(d.get("state") or 0) != 1)
        return WidgetData(
            status="bad" if wan.get("status") == "error" else ("warn" if offline else "ok"),
            primary={"label": "Clients", "value": len(clients)},
            secondary=[
                {"label": "Wi-Fi", "value": wlan.get("num_user", 0)},
                {"label": "WAN down", "value": human_rate(down), "metric": "wan_down"},
                {"label": "WAN up", "value": human_rate(up), "metric": "wan_up"},
                {"label": "Devices", "value": f"{len(devices) - offline} / {len(devices)}"},
            ],
            metrics={"clients": float(len(clients)), "wan_down": round(down / 1024 / 1024, 2), "wan_up": round(up / 1024 / 1024, 2)},
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        if widget_kind == "devices":
            devices = [("Living room AP", "Access point · U6-Pro · 14 clients", "ok"), ("Office AP", "Access point · U6-Lite · 6 clients", "ok"), ("Core switch", "Switch · USW-24-PoE", "ok"), ("Garden AP", "Access point · U6-Mesh · 2 clients", "bad"), ("Gateway", "Console · UDM-Pro", "ok")]
            return WidgetData(status="bad", items=[{"title": n, "subtitle": s, "status": st, "value": f"{int(fake.walk(n, tick, 5, 40))}% cpu"} for n, s, st in devices])
        down = fake.walk("wan-down", tick, 2, 90) * 1024 * 1024
        up = fake.walk("wan-up", tick, 0.5, 12) * 1024 * 1024
        clients = fake.counter("clients", tick, 38, 0.001) % 60
        return WidgetData(primary={"label": "Clients", "value": clients},
                          secondary=[{"label": "Wi-Fi", "value": clients - 9}, {"label": "WAN down", "value": human_rate(down), "metric": "wan_down"}, {"label": "WAN up", "value": human_rate(up), "metric": "wan_up"}, {"label": "Devices", "value": "4 / 5"}],
                          metrics={"clients": float(clients), "wan_down": round(down / 1024 / 1024, 2), "wan_up": round(up / 1024 / 1024, 2)}, status="warn")


ADAPTER = UnifiAdapter()
