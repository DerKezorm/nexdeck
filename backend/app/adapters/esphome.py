"""ESPHome: which of your devices are online, and which run an older firmware than the dashboard offers.

Measured on 27.10.2026 against the ESPHome device builder 2026.10.0
(``esphome/esphome``, its dashboard on port 6052) with three device
configurations in it, with and without the dashboard's own sign-in. The
dashboard is the only part of ESPHome that talks HTTP to somebody else: a
device itself speaks the native API (protobuf, usually encrypted) and only
answers HTTP when it has the ``web_server`` component, which is a page of its
own and not an API this adapter relies on.

⚠️ Not measured: a device that is online. The container cannot ping anything,
and the dashboard answers ``"state": "unknown"`` and ``null`` in ``/ping`` for
every device it cannot probe. What the dashboard says for one that answers
(``state`` ``online``, ``offline``) is taken from its own front end, and older
dashboards say it in ``/ping`` as ``true`` and ``false``. Both are read.

⚠️ With ``USERNAME`` and ``PASSWORD`` set the dashboard answers 401 "Authentication
required" on ``/devices`` and ``/ping`` and asks for Basic. ``/version`` stays
open, so it proves nothing about the sign-in; the test asks for the devices.

⚠️ A configuration is listed whether or not it was ever built: ``deployed_version``
is empty until a firmware was compiled, and ``update_available`` stays false.
A file of the folder that is not a device (``secrets.yaml`` is left out by the
dashboard, a helper file is not) is listed as a device without a platform.
"""

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
    measured,
)

ADDRESS_HINT = "Check the URL; it is the address of the ESPHome dashboard, usually port 6052."


def _text(value: Any) -> str:
    return str(value).strip() if isinstance(value, str) else ""


class EsphomeAdapter(Adapter):
    kind = "esphome"
    label = "ESPHome"
    category = "other"
    description = "How many of your ESPHome devices are online, which are offline, and which run an older firmware than the dashboard offers."
    icon = "esphome"
    beta = True
    docs_url = "https://esphome.io/guides/getting_started_command_line/"
    keywords = ("smart home", "ESP32", "ESP8266", "device builder")
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://esphome:6052",
              help="The address of the ESPHome dashboard (device builder)."),
        Field("username", "User", help="Only if the dashboard has USERNAME and PASSWORD set."),
        Field("password", "Password", type="password", secret=True),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(
            kind="overview", label="ESPHome overview",
            description="How many devices are online and offline, how many wait for a firmware update, and the version of the dashboard.",
            renderer="value", default_size=(3, 2), refresh_seconds=60, metrics=("online", "offline", "updates"),
            parts=(("offline", "Offline"), ("updates", "Updates waiting"), ("devices", "Devices"), ("version", "Dashboard")),
        ),
        WidgetType(
            kind="devices", label="Devices",
            description="Every device of the dashboard, the offline ones first, then those with an update waiting.",
            renderer="list", default_size=(3, 3), refresh_seconds=60,
            options=(Field("limit", "Entries", type="number", default=12),),
        ),
    )

    # -- talking to the dashboard --------------------------------------------

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, *, cache: float = 0, allow: tuple[int, ...] = ()) -> Any:
        user = str(config.get("username") or "").strip()
        response = await ctx.request(
            "GET", f"{base_url(config)}{path}", headers={"Accept": "application/json"},
            auth=(user, str(config.get("password") or "")) if user else None, verify=not config.get("insecure"),
            timeout=15.0, cache_seconds=cache, auth_errors=False)
        if response.status_code in (401, 403):
            error = AuthFailed("The ESPHome dashboard asks for a user and a password." if not user
                               else "The ESPHome dashboard turned the user or the password down.")
            error.hint = "Fill in the user and the password the dashboard was started with (USERNAME and PASSWORD)."
            raise error
        if response.status_code in allow:
            return None
        if response.status_code >= 400:
            raise AdapterError(f"The ESPHome dashboard answered with HTTP {response.status_code}.", code="http_error", hint=ADDRESS_HINT)
        try:
            return response.json()
        except ValueError as error:
            raise AdapterError("This address answers with something other than the ESPHome dashboard.", code="not_esphome", hint=ADDRESS_HINT) from error

    async def _devices(self, config: dict[str, Any], ctx: Context) -> list[dict[str, Any]]:
        listed = await self._get(config, ctx, "/devices", cache=10)
        if not isinstance(listed, dict) or not isinstance(listed.get("configured"), list):
            raise AdapterError("This address answers, but not the way the ESPHome dashboard does.", code="not_esphome", hint=ADDRESS_HINT)
        devices = [one for one in listed["configured"] if isinstance(one, dict)]
        if any("state" not in one for one in devices):
            # An older dashboard says whether a device answers in /ping, as true and false.
            ping = await self._get(config, ctx, "/ping", cache=10, allow=(404,))
            for one in devices:
                if "state" not in one and isinstance(ping, dict):
                    answer = ping.get(one.get("configuration"))
                    one["state"] = "online" if answer is True else "offline" if answer is False else "unknown"
        return devices

    # -- the hooks -----------------------------------------------------------

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        version = await self._get(config, ctx, "/version")
        if not isinstance(version, dict) or "version" not in version:
            raise AdapterError("This address answers, but not the way the ESPHome dashboard does.", code="not_esphome", hint=ADDRESS_HINT)
        # /version is open even when the dashboard has a sign-in, so the devices are what proves the credentials.
        devices = await self._devices(config, ctx)
        return f"ESPHome {version['version']} answers with {len(devices)} devices."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        devices = await self._devices(config, ctx)
        if widget_kind == "devices":
            return self._devices_card(devices, options)
        version = await self._get(config, ctx, "/version", cache=300)
        return self._overview(devices, str(version.get("version") or "") if isinstance(version, dict) else "")

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def _behind(device: dict[str, Any]) -> bool:
        """Whether the firmware on the device is older than what the dashboard would build now."""
        if isinstance(device.get("update_available"), bool):
            return bool(device["update_available"])
        deployed, current = _text(device.get("deployed_version")), _text(device.get("current_version"))
        return bool(deployed and current and deployed != current)

    @classmethod
    def _overview(cls, devices: list[dict[str, Any]], version: str) -> WidgetData:
        online = sum(1 for one in devices if one.get("state") == "online")
        offline = sum(1 for one in devices if one.get("state") == "offline")
        updates = sum(1 for one in devices if cls._behind(one))
        secondary: list[dict[str, Any]] = [
            {"label": "Offline", "value": offline, "part": "offline"},
            {"label": "Updates waiting", "value": updates, "part": "updates"},
            {"label": "Devices", "value": len(devices), "part": "devices"},
        ]
        if version:
            secondary.append({"label": "Dashboard", "value": version, "part": "version"})
        return WidgetData(
            status="warn" if offline or updates else "ok",
            primary={"label": "Devices online", "value": online},
            secondary=secondary,
            metrics=measured({"online": float(online), "offline": float(offline), "updates": float(updates)}),
        )

    @classmethod
    def _devices_card(cls, devices: list[dict[str, Any]], options: dict[str, Any]) -> WidgetData:
        try:
            limit = max(1, min(100, int(options.get("limit") or 12)))
        except (TypeError, ValueError):
            limit = 12

        def order(one: dict[str, Any]) -> tuple[int, str]:
            return (0 if one.get("state") == "offline" else 1 if cls._behind(one) else 2, _text(one.get("friendly_name") or one.get("name")).lower())

        rows = []
        for one in sorted(devices, key=order)[:limit]:
            behind = cls._behind(one)
            state = one.get("state")
            seconds = one.get("offline_seconds")
            word = "Offline" if state == "offline" else "Update" if behind else "Online" if state == "online" else "Unknown"
            row: dict[str, Any] = {
                "id": one.get("configuration"), "title": _text(one.get("friendly_name") or one.get("name")) or "?",
                "subtitle": _text(one.get("comment")) or _text(one.get("target_platform")),
                "value": word, "status": "bad" if state == "offline" else "warn" if behind else "ok" if state == "online" else "unknown",
            }
            if state == "offline" and isinstance(seconds, int | float) and seconds > 0:
                row["subtitle"] = " · ".join(part for part in (duration_short(seconds), row["subtitle"]) if part)
            port = one.get("web_port")
            if isinstance(port, int) and one.get("address"):
                row["url"] = f"http://{one['address']}:{port}"
            rows.append(row)
        return WidgetData(items=rows, secondary=[{"label": "Devices", "value": len(devices)}], meta={"empty": "No device in the dashboard."})

    # -- demo ----------------------------------------------------------------

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        garage_down = fake.flicker("esphome-garage", tick, 0.35)
        devices = [
            {"configuration": f"{slug}.yaml", "name": slug, "friendly_name": friendly, "comment": comment, "state": state,
             "target_platform": "esp32", "update_available": behind, "offline_seconds": seconds}
            for slug, friendly, comment, state, behind, seconds in (
                ("kitchen-sensor", "Kitchen sensor", "Temperature above the stove", "online", False, None),
                ("garage-relay", "Garage relay", "", "offline" if garage_down else "online", False, 540 if garage_down else None),
                ("hall-light", "Hall light", "Dimmer behind the door", "online", True, None),
                ("garden-valve", "Garden valve", "", "online", False, None),
            )
        ]
        if widget_kind == "devices":
            return self._devices_card(devices, options)
        return self._overview(devices, "2026.10.0")


ADAPTER = EsphomeAdapter()
