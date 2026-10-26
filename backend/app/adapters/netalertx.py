"""NetAlertX: which devices are new on the network, which went offline, and a button to mark a new one as known.

Measured against NetAlertX 26.9.0 on 11.09.2026, scanning a Docker network of
its own with three dummy containers (one of them stopped once) every minute,
never a real network.

⚠️ The API is its own port, 20212 by default; the web interface is 20211.
A missing and a made-up token both get 403
``{"success": false, "message": "ERROR: Not authorized"}``.

⚠️ An ``app.conf`` without an ``API_TOKEN`` line gets a token drawn at every
start (``t_`` and twenty characters) that is written nowhere, so a card set up
with it stops working at the next restart. Saving the settings once writes it
down.

⚠️ A device that went offline while it is still new keeps ``devStatus: "New"``;
only ``devPresentLastScan: 0`` says it is gone. The cards read that field.

⚠️ Times such as ``devFirstConnection: "2026-09-11 21:05:47"`` carry no zone.
They are in NetAlertX's own ``TIMEZONE`` setting, which
``/settings/TIMEZONE`` hands out as ``{"success": true, "value": "UTC"}``.

⚠️ Marking as known is ``POST /device/<mac>/update-column`` with
``{"columnName": "devIsNew", "columnValue": 0}``: 200 ``{"success": true}``,
and the device's status turns from New to On-line. A MAC it does not know gets
404 ``{"error": "Device not found"}``, a column outside its list 422.

⚠️ ``devices`` minus ``connected`` in ``/devices/totals/named`` is exactly the
offline list of ``/devices/by-status?status=offline``.

⚠️ A container that restarts on a Docker network comes back with a new MAC
address: a new device, while its old entry stays behind as offline.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .base import (
    Action,
    Adapter,
    AdapterError,
    AuthFailed,
    Context,
    Field,
    WidgetData,
    WidgetType,
    ago,
    base_url,
    path_segment,
)

#: The names NetAlertX gives a device it could not name.
NO_NAME = {"", "(unknown)", "(name not found)"}
NETALERTX_TIME = "%Y-%m-%d %H:%M:%S"


def moment(raw: Any, zone: ZoneInfo) -> float | None:
    """``2026-09-11 21:05:47`` in NetAlertX's own zone, as seconds since the epoch."""
    try:
        return datetime.strptime(str(raw), NETALERTX_TIME).replace(tzinfo=zone).timestamp()
    except (TypeError, ValueError):
        return None


def _gone(device: dict[str, Any]) -> bool:
    return str(device.get("devPresentLastScan")) == "0"


def _row(device: dict[str, Any], words: tuple[str, ...]) -> dict[str, Any]:
    name = str(device.get("devName") or "").strip()
    address = str(device.get("devLastIP") or "")
    title = name if name not in NO_NAME else address or str(device.get("devMac") or "?")
    vendor = str(device.get("devVendor") or "")
    pieces = (address if title != address else "", "" if vendor.startswith("(") else vendor, *words)
    return {"title": title, "subtitle": " · ".join(piece for piece in pieces if piece)}


class NetAlertXAdapter(Adapter):
    kind = "netalertx"
    label = "NetAlertX"
    category = "network"
    description = "New devices on the network, the ones that went offline, and a button to mark a new one as known."
    icon = "netalertx"
    #: Confirmed against a live instance on 2026-09-11.
    beta = False
    docs_url = "https://docs.netalertx.com/API/"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://netalertx:20212",
              help="The address of the API, port 20212 by default."),
        Field("token", "API token", type="password", secret=True, required=True,
              help="Settings > General > API token. Save the settings once, or NetAlertX draws a new token at every start."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(kind="new", label="New devices", description="Devices seen for the first time and not marked as known yet, the newest first, with a button to mark each as known.",
                   renderer="list", default_size=(3, 3), refresh_seconds=120, metrics=("new",),
                   options=(Field("limit", "Entries", type="number", default=10),)),
        WidgetType(kind="offline", label="Offline devices", description="Devices that were missing in the last scan, the most recently gone first.",
                   renderer="list", default_size=(3, 3), refresh_seconds=120, metrics=("offline",),
                   options=(Field("limit", "Entries", type="number", default=10),)),
        WidgetType(kind="summary", label="Devices", description="Devices online, the new ones and those that went offline.",
                   renderer="value", default_size=(3, 2), refresh_seconds=120, metrics=("online", "new", "offline")),
    )

    def _headers(self, config: dict[str, Any]) -> dict[str, str]:
        return {"Authorization": f"Bearer {config.get('token') or ''}"}

    @staticmethod
    def _answer(response: Any) -> Any:
        if response.status_code in (401, 403):
            raise AuthFailed("NetAlertX rejected the API token.")
        if response.status_code >= 400:
            raise AdapterError(f"NetAlertX answered with HTTP {response.status_code}.", code="http_error",
                               hint="Check the URL; it is the API port, 20212 by default, not the web interface.")
        try:
            return response.json()
        except ValueError as error:
            raise AdapterError("NetAlertX did not answer with JSON.", code="not_json",
                               hint="The URL probably points at the web interface or something else than the API.") from error

    async def _json(self, config: dict[str, Any], ctx: Context, path: str, params: dict[str, Any] | None = None, cache: float = 15) -> Any:
        response = await ctx.request("GET", f"{base_url(config)}{path}", headers=self._headers(config), params=params,
                                     verify=not config.get("insecure"), cache_seconds=cache, auth_errors=False)
        return self._answer(response)

    async def _devices(self, config: dict[str, Any], ctx: Context, status: str) -> list[dict[str, Any]]:
        devices = await self._json(config, ctx, "/devices/by-status", {"status": status})
        if not isinstance(devices, list):
            raise AdapterError("This address answers, but not the way NetAlertX does.", code="not_netalertx")
        return [one for one in devices if isinstance(one, dict)]

    async def _totals(self, config: dict[str, Any], ctx: Context, cache: float = 15) -> dict[str, int]:
        answer = await self._json(config, ctx, "/devices/totals/named", cache=cache)
        totals = answer.get("totals") if isinstance(answer, dict) else None
        if not isinstance(totals, dict) or "devices" not in totals:
            raise AdapterError("This address answers, but not the way NetAlertX does.", code="not_netalertx")
        return {key: int(value or 0) for key, value in totals.items() if isinstance(value, int | float)}

    async def _zone(self, config: dict[str, Any], ctx: Context) -> ZoneInfo:
        answer = await self._json(config, ctx, "/settings/TIMEZONE", cache=3600)
        try:
            return ZoneInfo(str((answer or {}).get("value") or "UTC"))
        except (ZoneInfoNotFoundError, ValueError):
            return ZoneInfo("UTC")

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        totals = await self._totals(config, ctx, cache=0)
        return f"NetAlertX answers with {totals.get('devices', 0)} devices, {totals.get('new', 0)} of them new."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "summary":
            return self._summary(await self._totals(config, ctx))
        zone = await self._zone(config, ctx)
        if widget_kind == "offline":
            return self._offline(await self._devices(config, ctx, "offline"), zone, options)
        return self._new(await self._devices(config, ctx, "new"), zone, options)

    async def action(self, widget_kind: str, action_id: str, params: dict[str, Any],
                     config: dict[str, Any], options: dict[str, Any], ctx: Context) -> str:
        if action_id != "known":
            raise AdapterError("Unknown device action.", code="no_such_action")
        mac = path_segment(params.get("mac"), "The device")
        response = await ctx.request("POST", f"{base_url(config)}/device/{mac}/update-column", headers=self._headers(config),
                                     json_body={"columnName": "devIsNew", "columnValue": 0},
                                     verify=not config.get("insecure"), auth_errors=False)
        if response.status_code == 404:
            raise AdapterError("NetAlertX has no such device any more.", code="action_failed")
        try:
            answer = self._answer(response)
        except AuthFailed:
            raise
        except AdapterError as refused:
            raise AdapterError(refused.message, code="action_failed", hint=refused.hint) from refused
        # ⚠️ The API says itself that 200 is not success; the body is.
        if not isinstance(answer, dict) or answer.get("success") is not True:
            detail = str((answer or {}).get("error") or (answer or {}).get("message") or "") if isinstance(answer, dict) else ""
            raise AdapterError(f"NetAlertX did not mark the device as known{': ' + detail if detail else ''}.", code="action_failed")
        ctx.forget_answers()
        return "Device marked as known."

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def _new(devices: list[dict[str, Any]], zone: ZoneInfo, options: dict[str, Any], now: float | None = None) -> WidgetData:
        fresh = [one for one in devices if str(one.get("devIsNew")) == "1" and str(one.get("devIsArchived") or "0") != "1"]
        fresh.sort(key=lambda one: (-(moment(one.get("devFirstConnection"), zone) or 0), str(one.get("devLastIP") or "")))
        items = []
        for device in fresh[: int(options.get("limit") or 10)]:
            row = _row(device, ("Offline",) if _gone(device) else ())
            row["status"] = "bad" if _gone(device) else "warn"
            row["value"] = ago(moment(device.get("devFirstConnection"), zone), now=now)
            mac = str(device.get("devMac") or "")
            if mac:
                row["actions"] = [Action(id="known", label="Mark as known", icon="check", confirm=True, params={"mac": mac})]
            items.append(row)
        return WidgetData(
            status="warn" if fresh else "ok",
            items=items,
            secondary=[{"label": "New", "value": len(fresh)}],
            # A wall display has no hovering, and marking a device is the thing to press here.
            meta={"empty": "No new devices.", "actions_visible": True},
            metrics={"new": float(len(fresh))},
        )

    @staticmethod
    def _offline(devices: list[dict[str, Any]], zone: ZoneInfo, options: dict[str, Any], now: float | None = None) -> WidgetData:
        gone = [one for one in devices if _gone(one) and str(one.get("devIsArchived") or "0") != "1"]
        gone.sort(key=lambda one: (-(moment(one.get("devLastConnection"), zone) or 0), str(one.get("devLastIP") or "")))
        items = []
        for device in gone[: int(options.get("limit") or 10)]:
            watched = str(device.get("devAlertDown")) == "1"
            row = _row(device, ("New",) if str(device.get("devIsNew")) == "1" else ())
            # A device somebody asked to be told about is a problem when it is gone; a phone that left is not.
            row["status"] = "bad" if watched else "unknown"
            row["value"] = ago(moment(device.get("devLastConnection"), zone), now=now)
            items.append(row)
        return WidgetData(
            status="bad" if any(item["status"] == "bad" for item in items) else "ok",
            items=items,
            secondary=[{"label": "Offline", "value": len(gone)}],
            meta={"empty": "Every device was there in the last scan."},
            metrics={"offline": float(len(gone))},
        )

    @staticmethod
    def _summary(totals: dict[str, int]) -> WidgetData:
        online = totals.get("connected", 0)
        offline = max(0, totals.get("devices", 0) - online)
        new = totals.get("new", 0)
        return WidgetData(
            status="warn" if new else "ok",
            primary={"label": "Online", "value": online},
            secondary=[{"label": "New", "value": new}, {"label": "Offline", "value": offline}],
            metrics={"online": float(online), "new": float(new), "offline": float(offline)},
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        visitor = tick % 4 != 0
        if widget_kind == "summary":
            return self._summary({"devices": 42 + (1 if visitor else 0), "connected": 35 + tick % 3, "new": 2 if visitor else 1})
        zone = ZoneInfo("UTC")
        now = datetime.now(zone)

        def at(minutes: int) -> str:
            return datetime.fromtimestamp(now.timestamp() - minutes * 60, zone).strftime(NETALERTX_TIME)

        devices = [
            {"devMac": "02:00:00:00:00:31", "devName": "(unknown)", "devLastIP": "192.0.2.31", "devVendor": "Espressif Inc.", "devIsNew": 1,
             "devPresentLastScan": 1, "devFirstConnection": at(12), "devLastConnection": at(1), "devAlertDown": 0},
            {"devMac": "02:00:00:00:00:18", "devName": "printer-hall", "devLastIP": "192.0.2.18", "devVendor": "Brother Industries", "devIsNew": 0,
             "devPresentLastScan": 0, "devFirstConnection": at(90000), "devLastConnection": at(35 + tick % 5), "devAlertDown": 1},
            {"devMac": "02:00:00:00:00:44", "devName": "phone-guest", "devLastIP": "192.0.2.44", "devVendor": "", "devIsNew": 0,
             "devPresentLastScan": 0, "devFirstConnection": at(4000), "devLastConnection": at(240), "devAlertDown": 0},
        ]
        if visitor:
            devices.append({"devMac": "02:00:00:00:00:52", "devName": "(unknown)", "devLastIP": "192.0.2.52", "devVendor": "(Unknown: locally administered)",
                            "devIsNew": 1, "devPresentLastScan": 0, "devFirstConnection": at(180), "devLastConnection": at(60), "devAlertDown": 0})
        if widget_kind == "offline":
            return self._offline(devices, zone, options)
        return self._new(devices, zone, options)


ADAPTER = NetAlertXAdapter()
