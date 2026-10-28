"""Traccar: which tracked devices are online, and how long ago each was heard from, with its battery.

Measured on 28.10.2026 against Traccar 6.16.0 (traccar/traccar, the built-in
H2 database) with a user token and three invented devices, two of which sent
a position through the OsmAnd protocol.

⚠️ The token is the user's own (Account > Token in the web interface), sent
as ``Authorization: Bearer``. A token that is not one made by this server is
HTTP **400**, not 401: ``nope`` got 400 with a Java stack trace as the body,
and no token at all 401 with a stack trace. Both are refusals, and neither
body is shown. A new server (``/api/server`` says ``newServer``) lets the
first visitor register as administrator.

⚠️ ``/api/devices`` has ``status`` (``online``, ``offline`` or ``unknown``),
``lastUpdate`` (null for a device never heard from) and ``positionId``, which
is 0 for a device with no position yet. ``/api/positions`` answers the latest
position of each device, with the device in ``deviceId`` (not the position's
own ``id``, which is a different number), ``speed`` in knots, ``attributes.
batteryLevel`` as a percent where the tracker reports one, and
``attributes.motion``. Positions are read for the battery and for motion; the
coordinates are not shown, since a dashboard in a hallway is no place for
where the car is.

``/api/server`` answers the version without a token.
"""

from __future__ import annotations

import time
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
    ago,
    base_url,
)

URL_HINT = "Check the URL; it is the address of the Traccar web interface itself, without /api."
LOW_BATTERY = 20


class TraccarAdapter(Adapter):
    kind = "traccar"
    label = "Traccar"
    category = "other"
    description = "How many tracked devices are online, which are moving, and when each was last heard from."
    icon = "traccar"
    beta = True
    docs_url = "https://www.traccar.org/traccar-api/"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://traccar:8082"),
        Field("token", "Token", type="password", secret=True, required=True,
              help="Account > Token in the web interface. It is the user's own, and sees that user's devices."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(kind="summary", label="Devices online", description="How many devices are online, with those offline and those moving.",
                   renderer="value", default_size=(3, 2), refresh_seconds=60, metrics=("online",),
                   parts=(("offline", "Offline"), ("moving", "Moving"), ("total", "Devices"))),
        WidgetType(kind="devices", label="Devices", description="Each device with its battery and when it was last heard from, the offline ones first.",
                   renderer="list", default_size=(3, 3), refresh_seconds=60,
                   options=(Field("offline", "Only offline devices", type="bool", default=False),
                            Field("limit", "Entries", type="number", default=12))),
    )

    # -- talking to Traccar --------------------------------------------------

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, cache: float = 10) -> Any:
        response = await ctx.request(
            "GET", f"{base_url(config)}/api{path}", headers={"Authorization": f"Bearer {config.get('token') or ''}", "Accept": "application/json"},
            verify=not config.get("insecure"), cache_seconds=cache, auth_errors=False,
        )
        # ⚠️ A token that is not one of this server's is 400, not 401; see the top of the file.
        if response.status_code in (400, 401, 403):
            raise AuthFailed("Traccar rejected the token.")
        if response.status_code >= 400:
            raise AdapterError(f"Traccar answered with HTTP {response.status_code}.", code="http_error", hint=URL_HINT)
        try:
            return response.json()
        except ValueError as error:
            raise AdapterError("Traccar did not answer with JSON.", code="not_json",
                               hint="The URL probably points at a login page or a reverse proxy.") from error

    async def _list(self, config: dict[str, Any], ctx: Context, path: str) -> list[dict[str, Any]]:
        answer = await self._get(config, ctx, path)
        if not isinstance(answer, list):
            raise AdapterError("This address answers, but not the way Traccar does.", code="not_traccar", hint=URL_HINT)
        return [one for one in answer if isinstance(one, dict) and not one.get("disabled")]

    # -- the hooks -----------------------------------------------------------

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        server = await self._get(config, ctx, "/server", cache=0)
        if not isinstance(server, dict) or "version" not in server:
            raise AdapterError("This address answers, but not the way Traccar does.", code="not_traccar", hint=URL_HINT)
        devices = await self._list(config, ctx, "/devices")
        return f"Traccar {server['version']} answers with {len(devices)} devices."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        devices = await self._list(config, ctx, "/devices")
        positions = await self._list(config, ctx, "/positions")
        base = base_url(config)
        if widget_kind == "devices":
            return self._devices(devices, positions, options, base)
        return self._summary(devices, positions, base)

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def _by_device(positions: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        # ⚠️ The device is deviceId; the position's own id is another number.
        return {str(one.get("deviceId")): one for one in positions}

    @classmethod
    def _summary(cls, devices: list[dict[str, Any]], positions: list[dict[str, Any]], base: str) -> WidgetData:
        latest = cls._by_device(positions)
        online = sum(1 for one in devices if one.get("status") == "online")
        offline = sum(1 for one in devices if one.get("status") == "offline")
        moving = sum(1 for one in devices if one.get("status") == "online" and (latest.get(str(one.get("id"))) or {}).get("attributes", {}).get("motion") is True)
        return WidgetData(
            status="ok",
            primary={"label": "Online", "value": online},
            secondary=[
                {"label": "Offline", "value": offline, "part": "offline"},
                {"label": "Moving", "value": moving, "part": "moving"},
                {"label": "Devices", "value": len(devices), "part": "total"},
            ],
            link=base,
            metrics={"online": float(online)},
        )

    @classmethod
    def _devices(cls, devices: list[dict[str, Any]], positions: list[dict[str, Any]], options: dict[str, Any], base: str) -> WidgetData:
        latest = cls._by_device(positions)
        rank = {"offline": 0, "unknown": 1, "online": 2}
        shown = sorted(devices, key=lambda one: (rank.get(str(one.get("status")), 1), str(one.get("name") or "").lower()))
        if options.get("offline") is True:
            shown = [one for one in shown if one.get("status") != "online"]
        items = []
        for device in shown[: max(1, int(options.get("limit") or 12))]:
            status = str(device.get("status") or "unknown")
            battery = ((latest.get(str(device.get("id"))) or {}).get("attributes") or {}).get("batteryLevel")
            low = isinstance(battery, int | float) and battery < LOW_BATTERY
            items.append({
                "title": str(device.get("name") or device.get("uniqueId") or "?"),
                "subtitle": f"{round(battery)} %" if isinstance(battery, int | float) else "",
                "value": ago(device.get("lastUpdate")) or "never",
                "status": "ok" if status == "online" and not low else "unknown" if status == "unknown" else "warn",
            })
        return WidgetData(status="ok", items=items, link=base, meta={"empty": "Every device is online." if options.get("offline") is True else "No devices yet."})

    # -- demo ----------------------------------------------------------------

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        base = "https://traccar.example.com"
        now = time.time()
        stamp = lambda seconds: time.strftime("%Y-%m-%dT%H:%M:%S.000+00:00", time.gmtime(now - seconds))  # noqa: E731
        van_online = not fake.flicker("traccar-van", tick, 0.15)
        devices = [
            {"id": 1, "name": "Delivery van", "status": "online" if van_online else "offline", "lastUpdate": stamp(40 if van_online else 3600)},
            {"id": 2, "name": "Spare bike", "status": "online", "lastUpdate": stamp(300)},
            {"id": 3, "name": "Old trailer", "status": "offline", "lastUpdate": stamp(5 * 86400)},
        ]
        positions = [
            {"deviceId": 1, "attributes": {"batteryLevel": 76.0, "motion": van_online}},
            {"deviceId": 2, "attributes": {"batteryLevel": 14.0, "motion": False}},
        ]
        if widget_kind == "devices":
            return self._devices(devices, positions, options, base)
        return self._summary(devices, positions, base)


ADAPTER = TraccarAdapter()
