"""UniFi Network: clients, devices and WAN throughput.

Two ways in. The Network Integration API (Network 9.0 and newer) takes an API
key created in the console, read-only and untouched by two-factor sign-in;
that is the way for nearly everyone. Older controllers still need a local
account without two-factor authentication and the classic cookie API
(``/proxy/network`` on UniFi OS consoles).
"""

from __future__ import annotations

import asyncio
import time
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
    duration_short,
)

#: Devices whose statistics are loaded for the list; more would mean a request per device.
STATS_LIMIT = 10
#: Integration API answers are kept this long so two widgets on one console cost one round.
CACHE_SECONDS = 20
KINDS = (("gateway", "Gateway"), ("accessPoint", "Access point"), ("switching", "Switch"))


def human_bits(bits_per_second: float) -> str:
    """Network throughput the way UniFi shows it: bits per second, not bytes."""
    value = float(bits_per_second)
    for unit in ("bit/s", "kbit/s", "Mbit/s", "Gbit/s"):
        if value < 1000 or unit == "Gbit/s":
            return f"{value:.0f} {unit}" if unit == "bit/s" else f"{value:.1f} {unit}"
        value /= 1000
    return f"{value:.1f} Gbit/s"


#: Security types of the Integration API and the classic API, in the words people use.
SECURITY = {
    "OPEN": "open", "WPA2_PERSONAL": "WPA2", "WPA3_PERSONAL": "WPA3", "WPA2_WPA3_PERSONAL": "WPA2/WPA3",
    "WPA2_ENTERPRISE": "WPA2 Enterprise", "WPA3_ENTERPRISE": "WPA3 Enterprise", "WPA2_WPA3_ENTERPRISE": "WPA2/WPA3 Enterprise",
    "open": "open", "wpapsk": "WPA2", "wpaeap": "WPA2 Enterprise", "wep": "WEP",
}
#: A Dream Machine reports only "switching" as its feature (Network 10.6); the model name tells.
GATEWAY_MODELS = ("DREAM MACHINE", "DREAM ROUTER", "DREAM WALL", "CLOUD GATEWAY", "GATEWAY", "UDM", "UDR", "UDW", "UCG", "UXG", "EXPRESS")


class UnifiAdapter(Adapter):
    kind = "unifi"
    #: Confirmed against a live instance on 2026-09-05.
    beta = False
    label = "UniFi Network"
    category = "network"
    description = "Connected clients, access points and switches, WAN traffic."
    icon = "unifi"
    docs_url = "https://developer.ui.com/site-manager-api/"
    fields = (
        Field("url", "Controller URL", type="url", required=True, placeholder="https://192.168.1.1"),
        Field("api_key", "API key", type="password", secret=True, help="Network 9.0 or newer: Settings > Control Plane > Integrations > Create API Key. Read-only, no account and no two-factor exception needed."),
        Field("username", "User name", help="Only without an API key: a local account without two-factor authentication."),
        Field("password", "Password", type="password", secret=True, help="Only without an API key."),
        Field("site", "Site", default="default", help="The internal site name, usually default."),
        Field("unifi_os", "UniFi OS console", type="bool", default=True, help="On for a Dream Machine or Cloud Key Gen2; off for the classic controller software."),
        Field("insecure", "Ignore TLS errors", type="bool", default=True),
    )
    widgets = (
        # Five rows of figures need three grid rows; at two, the last row is cut off.
        WidgetType(kind="summary", label="Network", description="Clients, devices and WAN throughput.", renderer="stats", default_size=(3, 3), refresh_seconds=30, metrics=("clients", "wan_down", "wan_up")),
        WidgetType(kind="console", label="Console", description="The console at a glance: gateway, uptime, versions, firmware state, device and client counts, WAN throughput.", renderer="list", default_size=(3, 3), refresh_seconds=60, metrics=("wan_down", "wan_up")),
        WidgetType(kind="devices", label="Devices", description="Access points, switches and gateways with state and load.", renderer="list", default_size=(3, 3), refresh_seconds=60),
        WidgetType(kind="findings", label="Findings", description="Does the console run, and what is wrong: offline devices, odd device states, firmware updates, a strained gateway.", renderer="list", default_size=(3, 2), refresh_seconds=60),
        WidgetType(kind="wifi", label="WLANs", description="Every wireless network with its VLAN, security, bands and the access points that carry it.", renderer="list", default_size=(3, 2), refresh_seconds=300),
    )

    # -- shared ----------------------------------------------------------------

    def _client(self, config: dict[str, Any], ctx: Context) -> httpx.AsyncClient:
        client = ctx.cache.get("unifi_client")
        if client is None or client.is_closed:
            # UniFi OS answers plain http with a redirect to https; following it
            # makes an http:// address work instead of failing on the redirect page.
            client = httpx.AsyncClient(base_url=base_url(config), verify=not config.get("insecure", True), timeout=15, follow_redirects=True)
            ctx.cache["unifi_client"] = client
        return client

    def _prefix(self, config: dict[str, Any]) -> str:
        return "/proxy/network" if config.get("unifi_os", True) else ""

    @staticmethod
    def _uses_api_key(config: dict[str, Any]) -> bool:
        return bool(str(config.get("api_key") or "").strip())

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        if self._uses_api_key(config):
            info = await self._api(config, ctx, "/info")
            site = await self._site(config, ctx)
            return f"UniFi Network {info.get('applicationVersion', '?')} answers, site {site['internalReference']!r} found."
        self._require_account(config)
        health = await self._get(config, ctx, "/stat/health")
        return f"UniFi answers, {len(health)} subsystems reported."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if self._uses_api_key(config):
            return await self._fetch_api(widget_kind, config, ctx)
        self._require_account(config)
        return await self._fetch_legacy(widget_kind, config, ctx)

    @staticmethod
    def _require_account(config: dict[str, Any]) -> None:
        if not (config.get("username") and config.get("password")):
            raise AdapterError(
                "Enter an API key, or a user name and password.", code="missing_credentials",
                hint="Network 9.0 and newer offer API keys under Settings > Control Plane > Integrations.",
            )

    # -- Integration API (API key) ---------------------------------------------

    async def _api(self, config: dict[str, Any], ctx: Context, path: str, params: dict[str, Any] | None = None) -> Any:
        """One GET against the Integration API, cached briefly per integration."""
        key = f"unifi_api:{path}:{sorted((params or {}).items())}"
        hit = ctx.cache.get(key)
        if hit and hit[0] > time.monotonic():
            return hit[1]
        client = self._client(config, ctx)
        headers = {"X-API-KEY": str(config.get("api_key", "")).strip(), "Accept": "application/json"}
        try:
            response = await client.get(f"{self._prefix(config)}/integration/v1{path}", headers=headers, params=params)
        except httpx.HTTPError as error:
            raise Unreachable(f"The UniFi console could not be reached: {error.__class__.__name__}.") from error
        if response.status_code in (401, 403):
            raise AuthFailed("The UniFi console rejected the API key.")
        if response.status_code == 404 and path == "/info":
            raise AdapterError(
                "The console has no Integration API; it needs Network 9.0 or newer.", code="no_integration_api",
                hint="Update the Network application, or use a local account instead of the key.",
            )
        if response.status_code >= 400:
            raise AdapterError(f"The UniFi console answered with HTTP {response.status_code}.", code="http_error")
        if "json" not in response.headers.get("content-type", "").lower():
            raise AdapterError(
                "The UniFi console answered with a page instead of data.", code="not_json",
                hint="Use https:// and the console's own address, without a port. The Integration API needs Network 9.0 or newer.",
            )
        try:
            payload = response.json()
        except ValueError as error:
            raise AdapterError("The UniFi console did not answer with JSON.", code="not_json",
                               hint="Use https:// and the console's own address, without a port.") from error
        ctx.cache[key] = (time.monotonic() + CACHE_SECONDS, payload)
        return payload

    async def _pages(self, config: dict[str, Any], ctx: Context, path: str, limit: int = 200, max_pages: int = 5) -> tuple[list[dict[str, Any]], int]:
        """Every row of a paged list, and the total the console reports."""
        rows: list[dict[str, Any]] = []
        total = 0
        for page in range(max_pages):
            payload = await self._api(config, ctx, path, {"offset": page * limit, "limit": limit})
            data = payload.get("data") or []
            rows.extend(data)
            total = int(payload.get("totalCount") or len(rows))
            if len(rows) >= total or not data:
                break
        return rows, total

    async def _site(self, config: dict[str, Any], ctx: Context) -> dict[str, Any]:
        wanted = str(config.get("site") or "default").strip()
        sites, _ = await self._pages(config, ctx, "/sites")
        for site in sites:
            if site.get("internalReference") == wanted or site.get("name") == wanted or site.get("id") == wanted:
                return site
        names = ", ".join(str(s.get("internalReference") or s.get("name")) for s in sites) or "none"
        raise AdapterError(f"The site {wanted!r} does not exist on this console; it knows: {names}.", code="site_not_found",
                           hint="Use the internal site name, usually default.")

    async def _stats(self, config: dict[str, Any], ctx: Context, site_id: str, device_id: str) -> dict[str, Any]:
        try:
            return await self._api(config, ctx, f"/sites/{site_id}/devices/{device_id}/statistics/latest")
        except AdapterError:
            return {}

    @staticmethod
    def _is_gateway(device: dict[str, Any]) -> bool:
        model = str(device.get("model") or "").upper()
        return "gateway" in (device.get("features") or []) or any(token in model for token in GATEWAY_MODELS)

    def _rank(self, device: dict[str, Any]) -> int:
        """Gateways first, then access points, then switches, then the rest."""
        if self._is_gateway(device):
            return 0
        features = device.get("features") or []
        return next((index for index, (feature, _label) in enumerate(KINDS) if feature in features), len(KINDS))

    def _kind(self, device: dict[str, Any]) -> str:
        if self._is_gateway(device):
            return "Gateway"
        features = device.get("features") or []
        for feature, label in KINDS:
            if feature in features:
                return label
        return "Device"

    async def _fetch_api(self, widget_kind: str, config: dict[str, Any], ctx: Context) -> WidgetData:
        site = await self._site(config, ctx)
        site_id = str(site["id"])
        if widget_kind == "wifi":
            return await self._wifi_api(config, ctx, site_id)
        devices, _ = await self._pages(config, ctx, f"/sites/{site_id}/devices")
        online = [d for d in devices if str(d.get("state", "")).upper() == "ONLINE"]
        offline = len(devices) - len(online)
        gateway_down = any(self._is_gateway(d) and str(d.get("state", "")).upper() != "ONLINE" for d in devices)
        # Both widgets follow one rule: red only when the gateway is gone, yellow for any other device.
        status = "bad" if gateway_down else ("warn" if offline else "ok")
        if widget_kind == "findings":
            _rows, clients = await self._pages(config, ctx, f"/sites/{site_id}/clients")
            gateway = next((d for d in devices if self._is_gateway(d)), None)
            gateway_stats = await self._stats(config, ctx, site_id, str(gateway["id"])) if gateway and gateway.get("id") else {}
            return self._findings(devices, clients, gateway, gateway_stats, status, offline)
        if widget_kind == "devices":
            ordered = sorted(devices, key=lambda d: (0 if self._is_gateway(d) else 1, 0 if str(d.get("state", "")).upper() != "ONLINE" else 1, self._rank(d), d.get("name") or ""))
            stats = await asyncio.gather(*(self._stats(config, ctx, site_id, str(d["id"])) for d in ordered[:STATS_LIMIT] if d.get("id")))
            items = []
            for index, device in enumerate(ordered):
                stat = stats[index] if index < len(stats) else {}
                cpu = stat.get("cpuUtilizationPct")
                subtitle = f"{self._kind(device)} · {device.get('model', '')}"
                if device.get("ipAddress"):
                    subtitle += f" · {device['ipAddress']}"
                items.append({
                    "title": device.get("name") or device.get("model", "?"),
                    "subtitle": subtitle,
                    "status": "ok" if str(device.get("state", "")).upper() == "ONLINE" else "bad",
                    "value": f"{round(float(cpu))}% cpu" if isinstance(cpu, (int, float)) else "",
                })
            return WidgetData(items=items, status=status, meta=self._offline_meta(offline))
        clients, total = await self._pages(config, ctx, f"/sites/{site_id}/clients")
        wireless = sum(1 for c in clients if str(c.get("type", "")).upper() == "WIRELESS")
        gateway = next((d for d in devices if self._is_gateway(d)), None)
        uplink = (await self._stats(config, ctx, site_id, str(gateway["id"]))).get("uplink") or {} if gateway and gateway.get("id") else {}
        # The Integration API reports the uplink in bits per second, and so does UniFi's own interface.
        down = float(uplink.get("rxRateBps") or 0)
        up = float(uplink.get("txRateBps") or 0)
        if widget_kind == "console":
            info = await self._api(config, ctx, "/info")
            return self._console(devices, clients, total, gateway, await self._stats(config, ctx, site_id, str(gateway["id"])) if gateway and gateway.get("id") else {}, str(info.get("applicationVersion") or "?"), down, up, status, offline)
        return WidgetData(
            status=status,
            primary={"label": "Clients", "value": total},
            secondary=[
                {"label": "Wi-Fi", "value": wireless},
                {"label": "WAN down", "value": human_bits(down), "metric": "wan_down"},
                {"label": "WAN up", "value": human_bits(up), "metric": "wan_up"},
                {"label": "Devices", "value": f"{len(online)} / {len(devices)}"},
            ],
            metrics={"clients": float(total), "wan_down": round(down / 1e6, 2), "wan_up": round(up / 1e6, 2)},
            meta=self._offline_meta(offline),
        )

    def _console(self, devices: list[dict[str, Any]], clients: list[dict[str, Any]], total: int, gateway: dict[str, Any] | None, gateway_stats: dict[str, Any], version: str, down: float, up: float, status: str, offline: int) -> WidgetData:
        """The console's own overview card, as far as the Network API tells: no ISP, WAN address or latencies."""
        gateways = sum(1 for d in devices if self._is_gateway(d))
        access_points = sum(1 for d in devices if not self._is_gateway(d) and "accessPoint" in (d.get("features") or []))
        switches = len(devices) - gateways - access_points
        online = sum(1 for d in devices if str(d.get("state", "")).upper() == "ONLINE")
        wireless = sum(1 for c in clients if str(c.get("type", "")).upper() == "WIRELESS")
        updates = sum(1 for d in devices if d.get("firmwareUpdatable"))
        items: list[dict[str, Any]] = []
        if gateway is not None:
            uptime = gateway_stats.get("uptimeSec")
            items.append({
                "title": gateway.get("name") or gateway.get("model", "Gateway"),
                "subtitle": " · ".join(part for part in (str(gateway.get("model") or ""), str(gateway.get("ipAddress") or "")) if part),
                "status": "ok" if str(gateway.get("state", "")).upper() == "ONLINE" else "bad",
                "value": duration_short(uptime) if isinstance(uptime, (int, float)) else "",
            })
        items.append({"title": "Network application", "subtitle": version, "status": "ok", "value": ""})
        items.append({
            "title": "Devices",
            "subtitle": " · ".join((f"{gateways} gateway" if gateways == 1 else f"{gateways} gateways", f"{switches} switch" if switches == 1 else f"{switches} switches", f"{access_points} access point" if access_points == 1 else f"{access_points} access points")),
            "status": "warn" if offline else "ok",
            "value": f"{online} / {len(devices)}",
        })
        items.append({"title": "Firmware", "subtitle": "all devices up to date" if not updates else f"{updates} update(s) available", "status": "ok" if not updates else "unknown", "value": ""})
        items.append({"title": "Clients", "subtitle": f"{wireless} wireless · {max(0, total - wireless)} wired", "status": "ok", "value": str(total)})
        items.append({"title": "WAN", "subtitle": f"↓ {human_bits(down)} · ↑ {human_bits(up)}", "status": "ok", "value": ""})
        return WidgetData(
            status=status,
            items=items,
            secondary=[{"label": "WAN down", "value": human_bits(down), "metric": "wan_down"}, {"label": "WAN up", "value": human_bits(up), "metric": "wan_up"}],
            metrics={"wan_down": round(down / 1e6, 2), "wan_up": round(up / 1e6, 2)},
            meta=self._offline_meta(offline),
        )

    async def _wifi_api(self, config: dict[str, Any], ctx: Context, site_id: str) -> WidgetData:
        """One row per WLAN. The API knows no clients per WLAN, so the row tells what the WLAN is instead."""
        wlans, _ = await self._pages(config, ctx, f"/sites/{site_id}/wifi/broadcasts")
        networks, _ = await self._pages(config, ctx, f"/sites/{site_id}/networks")
        by_id = {str(network.get("id")): network for network in networks}
        default = next((network for network in networks if network.get("default")), None)
        items: list[dict[str, Any]] = []
        for wlan in sorted(wlans, key=lambda w: (not w.get("enabled", True), str(w.get("name") or "").lower())):
            reference = wlan.get("network") or {}
            network = by_id.get(str(reference.get("networkId"))) if reference.get("type") == "SPECIFIC" else default
            parts = [self._network_label(network)] if network else []
            parts.append(SECURITY.get(str((wlan.get("securityConfiguration") or {}).get("type") or ""), str((wlan.get("securityConfiguration") or {}).get("type") or "?")))
            bands = wlan.get("broadcastingFrequenciesGHz") or []
            if bands:
                parts.append(" + ".join(f"{float(band):g}" for band in bands) + " GHz")
            if wlan.get("type") == "IOT_OPTIMIZED":
                parts.append("IoT")
            if "hotspotConfiguration" in wlan:
                parts.append("guest portal")
            device_filter = wlan.get("broadcastingDeviceFilter") or {}
            if device_filter.get("type") == "DEVICES":
                count = len(device_filter.get("deviceIds") or [])
                parts.append(f"on {count} access point" if count == 1 else f"on {count} access points")
            else:
                parts.append("all access points")
            enabled = bool(wlan.get("enabled", True))
            if not enabled:
                parts.append("off")
            items.append({"title": wlan.get("name") or "?", "subtitle": " · ".join(parts), "status": "ok" if enabled else "unknown"})
        return WidgetData(status="ok", items=items, meta={"empty": "No WLANs configured"})

    @staticmethod
    def _network_label(network: dict[str, Any]) -> str:
        name = str(network.get("name") or "")
        vlan = network.get("vlanId")
        if name and vlan is not None:
            return f"{name} (VLAN {vlan})"
        return name or f"VLAN {vlan}"

    def _findings(self, devices: list[dict[str, Any]], clients: int, gateway: dict[str, Any] | None, gateway_stats: dict[str, Any], status: str, offline: int) -> WidgetData:
        """The answer to "does my UniFi run, and what is wrong": one row per finding, or one calm line.

        Red: the gateway is offline. Yellow: another device is offline or in an
        odd state, or the gateway is strained. Grey: worth knowing, nothing
        broken (a firmware update, a fresh restart).
        """
        items: list[dict[str, Any]] = []
        for device in sorted(devices, key=lambda d: (0 if self._is_gateway(d) else 1, d.get("name") or "")):
            name = device.get("name") or device.get("model", "?")
            head = f"{self._kind(device)} · {device.get('model', '')}"
            state = str(device.get("state") or "").upper()
            if state == "OFFLINE":
                items.append({"title": name, "subtitle": f"{head} · offline", "status": "bad" if self._is_gateway(device) else "warn"})
            elif state and state != "ONLINE":
                items.append({"title": name, "subtitle": f"{head} · {state.lower().replace('_', ' ')}", "status": "warn"})
            if device.get("firmwareUpdatable"):
                items.append({"title": name, "subtitle": f"{head} · firmware update available", "status": "unknown"})
        if gateway is not None:
            name = gateway.get("name") or gateway.get("model", "?")
            cpu = gateway_stats.get("cpuUtilizationPct")
            memory = gateway_stats.get("memoryUtilizationPct")
            uptime = gateway_stats.get("uptimeSec")
            if isinstance(cpu, (int, float)) and cpu >= 90:
                items.append({"title": name, "subtitle": f"CPU {cpu:.0f}%", "status": "warn"})
            if isinstance(memory, (int, float)) and memory >= 90:
                items.append({"title": name, "subtitle": f"memory {memory:.0f}%", "status": "warn"})
            if isinstance(uptime, (int, float)) and uptime < 600:
                items.append({"title": name, "subtitle": f"restarted {int(uptime // 60)} min ago", "status": "unknown"})
        order = {"bad": 0, "warn": 1, "unknown": 2}
        items.sort(key=lambda item: order.get(str(item["status"]), 3))
        calm = f"UniFi answers · {len(devices)} devices online · {clients} clients"
        return WidgetData(status=status, items=items, meta={**self._offline_meta(offline), "empty": calm})

    @staticmethod
    def _offline_meta(offline: int) -> dict[str, Any]:
        """The dot says why it is yellow or red: how many devices are not answering."""
        return {"status_reason": f"{offline} device(s) offline"} if offline else {}

    # -- classic cookie API (local account) -------------------------------------

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

    async def _fetch_legacy(self, widget_kind: str, config: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "wifi":
            return await self._wifi_legacy(config, ctx)
        devices = await self._get(config, ctx, "/stat/device")
        if widget_kind == "findings":
            return await self._findings_legacy(devices, config, ctx)
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
        # The classic API counts bytes per second; shown as bits, like UniFi does.
        down = float(wan.get("rx_bytes-r") or 0) * 8
        up = float(wan.get("tx_bytes-r") or 0) * 8
        offline = sum(1 for d in devices if int(d.get("state") or 0) != 1)
        if widget_kind == "console":
            sysinfo = await self._get(config, ctx, "/stat/sysinfo")
            version = str((sysinfo[0] if sysinfo else {}).get("version") or "?")
            gateway = next((d for d in devices if d.get("type") in ("ugw", "udm")), None)
            shaped = [{**d, "features": ["accessPoint"] if d.get("type") == "uap" else ["switching"], "state": "ONLINE" if int(d.get("state") or 0) == 1 else "OFFLINE", "ipAddress": d.get("ip"), "firmwareUpdatable": bool(d.get("upgradable"))} for d in devices]
            shaped_gateway = next((d for d in shaped if d.get("type") in ("ugw", "udm")), None)
            if shaped_gateway is not None:
                shaped_gateway["features"] = ["gateway"]
            stats = {"uptimeSec": gateway.get("uptime")} if gateway else {}
            wireless = [{"type": "WIRELESS"} for _ in range(int(wlan.get("num_user") or 0))]
            return self._console(shaped, wireless, len(clients), shaped_gateway, stats, version, down, up, "bad" if wan.get("status") == "error" else ("warn" if offline else "ok"), offline)
        return WidgetData(
            status="bad" if wan.get("status") == "error" else ("warn" if offline else "ok"),
            primary={"label": "Clients", "value": len(clients)},
            secondary=[
                {"label": "Wi-Fi", "value": wlan.get("num_user", 0)},
                {"label": "WAN down", "value": human_bits(down), "metric": "wan_down"},
                {"label": "WAN up", "value": human_bits(up), "metric": "wan_up"},
                {"label": "Devices", "value": f"{len(devices) - offline} / {len(devices)}"},
            ],
            metrics={"clients": float(len(clients)), "wan_down": round(down / 1e6, 2), "wan_up": round(up / 1e6, 2)},
        )

    async def _wifi_legacy(self, config: dict[str, Any], ctx: Context) -> WidgetData:
        wlans = await self._get(config, ctx, "/rest/wlanconf")
        networks = {str(n.get("_id")): n for n in await self._get(config, ctx, "/rest/networkconf")}
        bands = {"2g": "2.4", "5g": "5", "6e": "6"}
        items: list[dict[str, Any]] = []
        for wlan in sorted(wlans, key=lambda w: (not w.get("enabled", True), str(w.get("name") or "").lower())):
            network = networks.get(str(wlan.get("networkconf_id") or ""))
            parts = [self._network_label({"name": network.get("name"), "vlanId": network.get("vlan")})] if network else []
            security = SECURITY.get(str(wlan.get("security") or ""), str(wlan.get("security") or "?"))
            parts.append("WPA2/WPA3" if wlan.get("wpa3_support") and security == "WPA2" else security)
            chosen = [bands[b] for b in wlan.get("wlan_bands") or [] if b in bands]
            if chosen:
                parts.append(" + ".join(chosen) + " GHz")
            if wlan.get("is_guest"):
                parts.append("guest portal")
            parts.append("all access points")
            enabled = bool(wlan.get("enabled", True))
            if not enabled:
                parts.append("off")
            items.append({"title": wlan.get("name") or "?", "subtitle": " · ".join(parts), "status": "ok" if enabled else "unknown"})
        return WidgetData(status="ok", items=items, meta={"empty": "No WLANs configured"})

    async def _findings_legacy(self, devices: list[dict[str, Any]], config: dict[str, Any], ctx: Context) -> WidgetData:
        health = await self._get(config, ctx, "/stat/health")
        clients = await self._get(config, ctx, "/stat/sta")
        kinds = {"uap": "Access point", "usw": "Switch", "ugw": "Gateway", "udm": "Gateway"}
        items: list[dict[str, Any]] = []
        offline = 0
        gateway_down = False
        for device in sorted(devices, key=lambda d: (0 if d.get("type") in ("ugw", "udm") else 1, d.get("name") or "")):
            name = device.get("name") or device.get("model", "?")
            head = f"{kinds.get(device.get('type', ''), device.get('type', ''))} · {device.get('model', '')}"
            is_gateway = device.get("type") in ("ugw", "udm")
            if int(device.get("state") or 0) != 1:
                offline += 1
                gateway_down = gateway_down or is_gateway
                items.append({"title": name, "subtitle": f"{head} · offline", "status": "bad" if is_gateway else "warn"})
            if device.get("upgradable"):
                items.append({"title": name, "subtitle": f"{head} · firmware update available", "status": "unknown"})
        wan = next((h for h in health if h.get("subsystem") == "wan"), {})
        if wan.get("status") == "error":
            items.insert(0, {"title": "WAN", "subtitle": "WAN is down", "status": "bad"})
        order = {"bad": 0, "warn": 1, "unknown": 2}
        items.sort(key=lambda item: order.get(str(item["status"]), 3))
        status = "bad" if gateway_down or wan.get("status") == "error" else ("warn" if offline else "ok")
        calm = f"UniFi answers · {len(devices)} devices online · {len(clients)} clients"
        return WidgetData(status=status, items=items, meta={**self._offline_meta(offline), "empty": calm})

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        if widget_kind == "wifi":
            return WidgetData(status="ok", items=[
                {"title": "Home", "subtitle": "Default (VLAN 1) · WPA3 · 2.4 + 5 GHz · all access points", "status": "ok"},
                {"title": "Guests", "subtitle": "Guests (VLAN 80) · open · 2.4 + 5 GHz · guest portal · on 3 access points", "status": "ok"},
                {"title": "IoT", "subtitle": "IoT (VLAN 90) · WPA2 · 2.4 GHz · IoT · all access points", "status": "ok"},
                {"title": "Workshop", "subtitle": "Default (VLAN 1) · WPA2 · 5 GHz · on 1 access point · off", "status": "unknown"},
            ], meta={"empty": "No WLANs configured"})
        if widget_kind == "findings":
            return WidgetData(status="warn", items=[
                {"title": "Garden AP", "subtitle": "Access point · U6-Mesh · offline", "status": "warn"},
                {"title": "Core switch", "subtitle": "Switch · USW-24-PoE · firmware update available", "status": "unknown"},
            ], meta={"status_reason": "1 device(s) offline", "empty": "UniFi answers · 5 devices online · 38 clients"})
        if widget_kind == "devices":
            devices = [("Living room AP", "Access point · U6-Pro · 14 clients", "ok"), ("Office AP", "Access point · U6-Lite · 6 clients", "ok"), ("Core switch", "Switch · USW-24-PoE", "ok"), ("Garden AP", "Access point · U6-Mesh · 2 clients", "bad"), ("Gateway", "Console · UDM-Pro", "ok")]
            return WidgetData(status="bad", items=[{"title": n, "subtitle": s, "status": st, "value": f"{int(fake.walk(n, tick, 5, 40))}% cpu"} for n, s, st in devices])
        down = fake.walk("wan-down", tick, 20, 900) * 1e6
        up = fake.walk("wan-up", tick, 2, 40) * 1e6
        clients = fake.counter("clients", tick, 38, 0.001) % 60
        if widget_kind == "console":
            return WidgetData(status="warn", items=[
                {"title": "Dream Machine", "subtitle": "UDM-PRO · 192.168.1.1", "status": "ok", "value": "11d 8h"},
                {"title": "Network application", "subtitle": "10.6.101", "status": "ok", "value": ""},
                {"title": "Devices", "subtitle": "1 gateway · 2 switches · 3 access points", "status": "warn", "value": "5 / 6"},
                {"title": "Firmware", "subtitle": "1 update(s) available", "status": "unknown", "value": ""},
                {"title": "Clients", "subtitle": f"{clients - 9} wireless · 9 wired", "status": "ok", "value": str(clients)},
                {"title": "WAN", "subtitle": f"↓ {human_bits(down)} · ↑ {human_bits(up)}", "status": "ok", "value": ""},
            ], secondary=[{"label": "WAN down", "value": human_bits(down), "metric": "wan_down"}, {"label": "WAN up", "value": human_bits(up), "metric": "wan_up"}],
                metrics={"wan_down": round(down / 1e6, 2), "wan_up": round(up / 1e6, 2)}, meta={"status_reason": "1 device(s) offline"})
        return WidgetData(primary={"label": "Clients", "value": clients},
                          secondary=[{"label": "Wi-Fi", "value": clients - 9}, {"label": "WAN down", "value": human_bits(down), "metric": "wan_down"}, {"label": "WAN up", "value": human_bits(up), "metric": "wan_up"}, {"label": "Devices", "value": "4 / 5"}],
                          metrics={"clients": float(clients), "wan_down": round(down / 1e6, 2), "wan_up": round(up / 1e6, 2)}, status="warn")


ADAPTER = UnifiAdapter()
