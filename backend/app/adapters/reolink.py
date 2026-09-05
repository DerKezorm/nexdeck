"""Reolink: a Home Hub, an NVR or a single camera. State, snapshots, live video and findings.

Every Reolink device speaks the same HTTP API: ``POST /api.cgi?cmd=X&token=T``
with a list of commands as the body and a list of answers back. A login hands
out a token for an hour; the device allows only a handful of sessions, so the
token lives in the integration's shared context and is reused by every card,
by snapshots and by the live relay.

Measured at a Home Hub (firmware 3.3): asking a wired camera for its battery
blocks the hub for 15 seconds and ends in a timeout, so battery is asked only
where GetAbility lists one. An unused channel slot has no name and is offline.
Snap with ``snapType=sub`` is 57 kB where the full picture is 400 kB to 2.6 MB.
The HTTP-FLV stream plays with RTMP switched off and accepts the session token
instead of the account, so no password ever enters a URL.
"""

from __future__ import annotations

import json
import secrets
import time
from typing import Any

from .base import (
    Adapter,
    AdapterError,
    AuthFailed,
    Context,
    Field,
    MediaSource,
    WidgetData,
    WidgetType,
    base_url,
)

#: What the device answers instead of data, by ``rspCode``.
ERRORS = {
    -1: "a parameter is missing",
    -4: "a parameter is wrong",
    -5: "the device has reached its session limit",
    -6: "the session has expired",
    -7: "wrong user name or password",
    -8: "the device took too long",
    -9: "this device does not support the command",
    -12: "too many users are signed in",
    -13: "the device is busy",
}
#: Codes that mean "the device cannot do this", not "something broke".
UNSUPPORTED = (-1, -4, -9)
LOW_BATTERY = 20
#: After the device refused a login for want of sessions, wait this long before asking again.
LOGIN_COOLDOWN = 60.0
#: The detections a camera reports and how a row names them.
DETECTIONS = (("people", "Person"), ("vehicle", "Vehicle"), ("dog_cat", "Animal"), ("face", "Face"), ("package", "Package"))


class DeviceError(AdapterError):
    """The device answered a command with an error code."""

    def __init__(self, message: str, rsp_code: int) -> None:
        super().__init__(message, code="device_error")
        self.rsp_code = rsp_code


class ReolinkAdapter(Adapter):
    kind = "reolink"
    #: Confirmed against a live instance on 2026-09-05.
    beta = False
    label = "Reolink"
    category = "monitoring"
    description = "Cameras of a Reolink Home Hub, NVR or a single camera: state, snapshots, live video and findings."
    icon = "reolink"
    docs_url = "https://reolink.com/software-and-manual/"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="https://reolink", help="The hub, recorder or camera. HTTP or HTTPS must be switched on under Network > Advanced > Port settings."),
        Field("username", "User name", required=True, help="A separate account with the user role is enough for cameras, snapshots and live video."),
        Field("password", "Password", type="password", secret=True, required=True),
        Field("insecure", "Ignore TLS errors", type="bool", default=True, help="Reolink devices come with a self-signed certificate."),
    )
    widgets = (
        WidgetType(
            kind="cameras",
            label="Cameras",
            description="Every camera with its state, battery and what it detects right now.",
            renderer="list",
            default_size=(3, 3),
            refresh_seconds=15,
        ),
        WidgetType(
            kind="camera",
            label="Camera",
            description="One camera large: a fresh snapshot every few seconds, or live video.",
            renderer="camera",
            default_size=(4, 3),
            min_size=(2, 2),
            refresh_seconds=60,
            options=(
                Field("channel", "Channel", type="number", default=0, help="The camera's number on the hub or recorder, starting at 0; the Cameras card lists them in this order."),
                Field("mode", "Picture", type="select", default="live", options=(("live", "Live video"), ("snapshot", "Snapshot")), help="Live video falls back to snapshots when the browser cannot play it."),
                Field("interval", "Snapshot every (seconds)", type="number", default=10),
                Field("quality", "Quality", type="select", default="sub", options=(("sub", "Fluent"), ("main", "Clear")), help="Fluent is the small stream: small snapshots, H.264 on every model, but often only 10 frames per second. Clear is the full picture at full frame rate; on some models it is H.265, which browsers cannot play."),
            ),
        ),
        WidgetType(
            kind="findings",
            label="Findings",
            description="Cameras offline, batteries low, storage missing or not ready.",
            renderer="list",
            default_size=(3, 2),
            refresh_seconds=60,
        ),
    )

    # -- the device's API -----------------------------------------------------------

    @staticmethod
    def _verify(config: dict[str, Any]) -> bool:
        return not config.get("insecure", True)

    async def _token(self, config: dict[str, Any], ctx: Context, force: bool = False) -> str:
        """The session token, fetched once and kept until shortly before its lease ends."""
        cached = ctx.cache.get("reolink_token")
        if cached and not force and cached[1] > time.monotonic():
            return str(cached[0])
        if float(ctx.cache.get("reolink_login_blocked_until") or 0) > time.monotonic():
            raise AuthFailed("The device refused the login: the device has reached its session limit. Waiting a minute before asking again.")
        body = [{"cmd": "Login", "param": {"User": {"Version": "0", "userName": str(config.get("username") or ""), "password": str(config.get("password") or "")}}}]
        response = await ctx.request("POST", f"{base_url(config)}/api.cgi", params={"cmd": "Login"}, json_body=body, verify=self._verify(config))
        try:
            answer = self._answers(response, ["Login"])[0]
        except DeviceError as failure:
            if failure.rsp_code in (-5, -12):
                # Asking every 15 seconds would only keep the device busy; the sessions expire on their own.
                ctx.cache["reolink_login_blocked_until"] = time.monotonic() + LOGIN_COOLDOWN
            raise AuthFailed(f"The device refused the login: {ERRORS.get(failure.rsp_code, failure.rsp_code)}.") from failure
        token = (answer.get("value") or {}).get("Token") or {}
        if not token.get("name"):
            raise AuthFailed("The device did not hand out a session token.")
        lease = float(token.get("leaseTime") or 3600)
        ctx.cache["reolink_token"] = (str(token["name"]), time.monotonic() + max(60.0, lease - 60.0))
        return str(token["name"])

    @staticmethod
    def _answers(response: Any, commands: list[str]) -> list[dict[str, Any]]:
        """The device's answers, one per command; the first failed one raises."""
        try:
            payload = response.json()
        except ValueError as failure:
            raise AdapterError(
                "The device did not answer with JSON.", code="not_json",
                hint="Check the address; HTTP or HTTPS must be switched on in the device's port settings.",
            ) from failure
        if isinstance(payload, dict):
            payload = [payload]
        if not isinstance(payload, list):
            raise AdapterError("The device answered in an unknown shape.", code="not_json")
        for index, answer in enumerate(payload):
            if int(answer.get("code", 0) or 0) != 0:
                detail = answer.get("error") or {}
                rsp_code = int(detail.get("rspCode") or 0)
                command = commands[index] if index < len(commands) else str(answer.get("cmd") or "?")
                raise DeviceError(f"{command}: {ERRORS.get(rsp_code, detail.get('detail') or f'error {rsp_code}')}.", rsp_code)
        return payload

    async def _batch(self, config: dict[str, Any], ctx: Context, commands: list[tuple[str, dict[str, Any]]], retry: bool = True) -> list[dict[str, Any] | None]:
        """Several commands in one request. An unsupported command yields None; an expired session logs in again once."""
        token = await self._token(config, ctx)
        body = [{"cmd": cmd, "action": 0, "param": param} for cmd, param in commands]
        response = await ctx.request(
            "POST", f"{base_url(config)}/api.cgi", params={"cmd": commands[0][0], "token": token}, json_body=body, verify=self._verify(config),
        )
        try:
            payload = response.json()
        except ValueError as failure:
            raise AdapterError("The device did not answer with JSON.", code="not_json", hint="Check the address; HTTP or HTTPS must be switched on in the device's port settings.") from failure
        if isinstance(payload, dict):
            payload = [payload]
        results: list[dict[str, Any] | None] = []
        for index, (cmd, _param) in enumerate(commands):
            answer = payload[index] if isinstance(payload, list) and index < len(payload) else {}
            if int(answer.get("code", 0) or 0) == 0:
                results.append(answer.get("value") or {})
                continue
            detail = answer.get("error") or {}
            rsp_code = int(detail.get("rspCode") or 0)
            if rsp_code == -6 and retry:
                await self._token(config, ctx, force=True)
                return await self._batch(config, ctx, commands, retry=False)
            if rsp_code in UNSUPPORTED:
                results.append(None)
                continue
            raise DeviceError(f"{cmd}: {ERRORS.get(rsp_code, detail.get('detail') or f'error {rsp_code}')}.", rsp_code)
        return results

    async def _call(self, config: dict[str, Any], ctx: Context, cmd: str, param: dict[str, Any] | None = None, cache: float = 5.0) -> dict[str, Any] | None:
        """One command, cached for a few seconds so three cards share one answer."""
        key = f"reolink:{cmd}:{json.dumps(param or {}, sort_keys=True)}"
        hit = ctx.cache.get(key)
        if cache > 0 and hit and hit[0] > time.monotonic():
            return hit[1]
        value = (await self._batch(config, ctx, [(cmd, param or {})]))[0]
        if cache > 0:
            ctx.cache[key] = (time.monotonic() + cache, value)
        return value

    async def close(self, config: dict[str, Any], ctx: Context) -> None:
        """Log out: a Reolink device allows only a handful of sessions, and a token lives an hour."""
        cached = ctx.cache.pop("reolink_token", None)
        if not cached:
            return
        try:
            await ctx.request(
                "POST", f"{base_url(config)}/api.cgi", params={"cmd": "Logout", "token": str(cached[0])},
                json_body=[{"cmd": "Logout", "param": {}}], verify=self._verify(config), timeout=3.0,
            )
        except AdapterError:
            return

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        info = (await self._call(config, ctx, "GetDevInfo", cache=0)) or {}
        device = info.get("DevInfo") or {}
        return f"{device.get('model') or 'Reolink'} with firmware {device.get('firmVer') or '?'}, {device.get('channelNum') or 1} channel(s)."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "cameras":
            return await self._cameras(config, ctx)
        if widget_kind == "camera":
            return await self._camera(config, options, ctx)
        if widget_kind == "findings":
            return await self._findings(config, ctx)
        raise AdapterError(f"Unknown widget {widget_kind}.", code="no_such_widget")

    # -- the cameras -------------------------------------------------------------------

    async def _device(self, config: dict[str, Any], ctx: Context) -> dict[str, Any]:
        return ((await self._call(config, ctx, "GetDevInfo", cache=600)) or {}).get("DevInfo") or {}

    async def _channels(self, config: dict[str, Any], ctx: Context) -> list[dict[str, Any]]:
        """One row per camera. A single camera has no channel list and is its own channel 0."""
        device = await self._device(config, ctx)
        status = await self._call(config, ctx, "GetChannelstatus", cache=10)
        rows = [
            row for row in ((status or {}).get("status") or [])
            if isinstance(row, dict) and (str(row.get("name") or "").strip() or int(row.get("online", 0) or 0))
        ]
        if not rows:
            rows = [{"channel": 0, "name": device.get("name") or device.get("model") or "Camera", "online": 1}]
        return rows

    async def _abilities(self, config: dict[str, Any], ctx: Context) -> list[dict[str, Any]]:
        """What each channel can do, per GetAbility; empty when the device does not tell."""
        answer = await self._call(config, ctx, "GetAbility", {"User": {"userName": str(config.get("username") or "")}}, cache=600)
        return [entry for entry in ((answer or {}).get("Ability") or {}).get("abilityChn") or [] if isinstance(entry, dict)]

    @staticmethod
    def _can(abilities: list[dict[str, Any]], channel: int, name: str, default: bool) -> bool:
        if channel >= len(abilities):
            return default
        entry = abilities[channel].get(name)
        if not isinstance(entry, dict):
            return default
        return int(entry.get("ver") or 0) > 0

    async def _details(self, config: dict[str, Any], ctx: Context, channels: list[int]) -> dict[int, dict[str, Any]]:
        """Battery, AI and motion state of every online camera, in one request.

        Battery is asked only where the device lists one: a wired camera makes
        the hub wait 15 seconds for an answer that never comes.
        """
        if not channels:
            return {}
        key = "reolink:details:" + ",".join(str(c) for c in channels)
        hit = ctx.cache.get(key)
        if hit and hit[0] > time.monotonic():
            return hit[1]
        abilities = await self._abilities(config, ctx)
        commands: list[tuple[str, dict[str, Any]]] = []
        wanted: list[tuple[int, str]] = []
        for channel in channels:
            for cmd, ability, default in (("GetBatteryInfo", "battery", False), ("GetAiState", "supportAi", True), ("GetMdState", "alarmMd", True)):
                if self._can(abilities, channel, ability, default):
                    commands.append((cmd, {"channel": channel}))
                    wanted.append((channel, cmd))
        answers = await self._batch(config, ctx, commands) if commands else []
        found: dict[tuple[int, str], Any] = dict(zip(wanted, answers, strict=True))
        details: dict[int, dict[str, Any]] = {}
        for channel in channels:
            battery, ai, motion = found.get((channel, "GetBatteryInfo")), found.get((channel, "GetAiState")), found.get((channel, "GetMdState"))
            details[channel] = {
                "battery": (battery or {}).get("Battery") if battery else None,
                "detections": [label for key_, label in DETECTIONS if ((ai or {}).get(key_) or {}).get("alarm_state")],
                "motion": bool(int((motion or {}).get("state") or 0)),
            }
        ctx.cache[key] = (time.monotonic() + 5, details)
        return details

    @staticmethod
    def _battery_parts(battery: dict[str, Any] | None) -> tuple[int | None, bool]:
        """Percent and whether it charges; the charge state is a word on new firmware and a number on old."""
        if not battery:
            return None, False
        percent = battery.get("batteryPercent")
        if not isinstance(percent, (int, float)):
            return None, False
        state = str(battery.get("chargeStatus") or "").lower()
        charging = state.startswith("charg") and "complete" not in state
        return int(percent), charging

    async def _cameras(self, config: dict[str, Any], ctx: Context) -> WidgetData:
        rows = await self._channels(config, ctx)
        online_channels = [int(row.get("channel", 0)) for row in rows if int(row.get("online", 0) or 0)]
        details = await self._details(config, ctx, online_channels)
        items: list[dict[str, Any]] = []
        detecting = 0
        for row in rows:
            channel = int(row.get("channel", 0))
            online = bool(int(row.get("online", 0) or 0))
            sleeping = bool(int(row.get("sleep", 0) or 0))
            detail = details.get(channel) or {}
            percent, charging = self._battery_parts(detail.get("battery"))
            parts = ["offline" if not online else ("sleeping" if sleeping else "online")]
            if percent is not None:
                parts.append(f"battery {percent}%")
            if charging:
                parts.append("charging")
            found = list(detail.get("detections") or [])
            if detail.get("motion") and not found:
                found = ["Motion"]
            detecting += 1 if found else 0
            status = "bad" if not online else ("warn" if percent is not None and percent < LOW_BATTERY else "ok")
            items.append({
                "title": str(row.get("name") or f"Channel {channel}"),
                "subtitle": " · ".join(parts + found),
                "status": status,
                "value": f"{percent}%" if percent is not None else "",
            })
        online = sum(1 for row in rows if int(row.get("online", 0) or 0))
        return WidgetData(
            status="bad" if online < len(rows) else "ok",
            items=items,
            secondary=[{"label": "Cameras", "value": len(rows)}, {"label": "Online", "value": online}, {"label": "Detecting", "value": detecting}],
            metrics={"online": float(online), "detecting": float(detecting)},
            meta={"empty": "No cameras"},
        )

    async def _camera(self, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        channel = max(0, int(options.get("channel") or 0))
        rows = await self._channels(config, ctx)
        row = next((r for r in rows if int(r.get("channel", -1)) == channel), None)
        if row is None:
            raise AdapterError(f"There is no camera with channel number {channel}; the device has {len(rows)}.", code="no_channel")
        online = bool(int(row.get("online", 0) or 0))
        sleeping = bool(int(row.get("sleep", 0) or 0))
        mode = "snapshot" if str(options.get("mode") or "live") == "snapshot" else "live"
        quality = "main" if str(options.get("quality") or "sub") == "main" else "sub"
        return WidgetData(
            status="bad" if not online else "ok",
            items=[{
                "title": str(row.get("name") or f"Channel {channel}"),
                "subtitle": "offline" if not online else ("sleeping" if sleeping else ""),
                "status": "bad" if not online else ("unknown" if sleeping else "ok"),
                "art": f"proxy:/snap/{channel}/{quality}",
            }],
            meta={"mode": mode, "live": mode == "live" and online, "interval": max(5, int(options.get("interval") or 10)), "channel": channel, "empty": "No cameras"},
        )

    async def _findings(self, config: dict[str, Any], ctx: Context) -> WidgetData:
        device = await self._device(config, ctx)
        rows = await self._channels(config, ctx)
        details = await self._details(config, ctx, [int(row.get("channel", 0)) for row in rows if int(row.get("online", 0) or 0)])
        storage = await self._call(config, ctx, "GetHddInfo", cache=300)
        items: list[dict[str, Any]] = []
        for row in rows:
            name = str(row.get("name") or f"Channel {int(row.get('channel', 0))}")
            if not int(row.get("online", 0) or 0):
                items.append({"title": name, "subtitle": "offline", "status": "bad"})
                continue
            percent, _charging = self._battery_parts((details.get(int(row.get("channel", 0))) or {}).get("battery"))
            if percent is not None and percent < LOW_BATTERY:
                items.append({"title": name, "subtitle": f"battery {percent}%", "status": "warn"})
        if storage is not None:
            disks = [disk for disk in (storage.get("HddInfo") or []) if isinstance(disk, dict)]
            if not disks:
                items.append({"title": "Storage", "subtitle": "No storage", "status": "warn"})
            for disk in disks:
                if not int(disk.get("mount", 1) or 0) or not int(disk.get("format", 1) or 0):
                    items.append({"title": "Storage", "subtitle": "Storage not ready", "status": "warn"})
        order = {"bad": 0, "warn": 1, "unknown": 2}
        items.sort(key=lambda item: order.get(str(item["status"]), 3))
        bad = sum(1 for item in items if item["status"] == "bad")
        warn = sum(1 for item in items if item["status"] == "warn")
        meta: dict[str, Any] = {"empty": f"Reolink answers · {device.get('model') or device.get('name') or 'device'} · {len(rows)} cameras"}
        if bad or warn:
            meta["status_reason"] = f"{bad} error finding(s), {warn} warning(s)"
        return WidgetData(status="bad" if bad else ("warn" if warn else "ok"), items=items, meta=meta)

    # -- snapshots and live video ---------------------------------------------------------

    async def image_source(self, config: dict[str, Any], path: str, ctx: Context) -> MediaSource:
        """``/snap/<channel>[/<sub|main>]`` becomes the device's Snap command with the session token; never cached."""
        parts = path.strip("/").split("/")
        if len(parts) not in (2, 3) or parts[0] != "snap" or not parts[1].isdigit() or (len(parts) == 3 and parts[2] not in ("sub", "main")):
            raise AdapterError("Reolink images are snapshots: /snap/<channel>/<sub|main>.", code="bad_path")
        token = await self._token(config, ctx)
        return MediaSource(
            url=f"{base_url(config)}/cgi-bin/api.cgi",
            params={"cmd": "Snap", "channel": int(parts[1]), "snapType": parts[2] if len(parts) == 3 else "sub", "rs": secrets.token_hex(8), "token": token},
            cache_seconds=0,
            media_type="image/jpeg",
        )

    async def stream_source(self, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> MediaSource:
        """The camera's HTTP-FLV stream, with the session token instead of the account."""
        channel = max(0, int(options.get("channel") or 0))
        quality = "main" if str(options.get("quality") or "sub") == "main" else "sub"
        ports = ((await self._call(config, ctx, "GetNetPort", cache=600)) or {}).get("NetPort") or {}
        token = await self._token(config, ctx)
        return MediaSource(
            url=f"{base_url(config)}/flv",
            params={"port": int(ports.get("rtmpPort") or 1935), "app": "bcs", "stream": f"channel{channel}_{quality}.bcs", "token": token},
            cache_seconds=0,
            media_type="video/x-flv",
        )

    # -- demo ------------------------------------------------------------------------------

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        if widget_kind == "cameras":
            return WidgetData(
                status="bad",
                items=[
                    {"title": "Front door", "subtitle": "online · battery 84% · Person", "status": "ok", "value": "84%"},
                    {"title": "Garden", "subtitle": "online · battery 100% · charging", "status": "ok", "value": "100%"},
                    {"title": "Garage", "subtitle": "offline", "status": "bad", "value": ""},
                ],
                secondary=[{"label": "Cameras", "value": 3}, {"label": "Online", "value": 2}, {"label": "Detecting", "value": 1}],
                metrics={"online": 2.0, "detecting": 1.0},
                meta={"empty": "No cameras"},
            )
        if widget_kind == "camera":
            return WidgetData(
                items=[{"title": "Front door", "subtitle": "", "status": "ok", "art": ""}],
                meta={"mode": "snapshot", "live": False, "interval": 30, "channel": 0, "empty": "No cameras"},
            )
        return WidgetData(status="bad", items=[
            {"title": "Garage", "subtitle": "offline", "status": "bad"},
            {"title": "Garden", "subtitle": "battery 15%", "status": "warn"},
        ], meta={"status_reason": "1 error finding(s), 1 warning(s)", "empty": "Reolink answers · Home Hub · 3 cameras"})


ADAPTER = ReolinkAdapter()
