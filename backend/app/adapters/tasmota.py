"""Tasmota: a relay you can switch, and what the plug has drawn.

⚠️ Not measured. There is no Tasmota to run in a container: it is firmware for
an ESP chip, and the flasher needs the chip. This is built from the Tasmota
documentation (the command page and the JSON status responses) and from what
its source says about the web server. Every claim below is the documentation's
and not a measurement.

One address does everything: ``GET /cm?cmnd=<command>`` answers JSON. ``Status 0``
returns all status blocks in one answer: ``Status`` (names, topic), ``StatusFWR``
(firmware version), ``StatusNET``, ``StatusSTS`` (``POWER`` or ``POWER1`` to
``POWERn`` as ``"ON"`` and ``"OFF"``, ``Uptime``, ``Wifi``) and ``StatusSNS``
(sensors; ``ENERGY`` on a plug that measures).

⚠️ With a web password set (``WebPassword``), the web server checks it for
``/cm`` too. Tasmota takes it as ``user=`` and ``password=`` in the address, or
as HTTP Basic. Basic is used here: an address with a password in it ends up in
logs. A wrong password answers with a JSON warning ("Need user=<username>&password=<password>")
and a 4xx code; the source says 403, the documentation says nothing, so 401 and
403 and that warning are all read as a refusal.

⚠️ The energy figures are in kilowatt hours (``Today``, ``Yesterday``, ``Total``),
``Power`` in watts. A device without a measuring chip has no ``ENERGY`` block at
all. ``FriendlyName`` is a list on current firmware and a plain text on old
firmware. ``POWER`` is used on a device with one relay, ``POWER1`` and up on one
with several. ``Uptime`` is ``"1T02:33:26"`` (days, T, time) and ``UptimeSec``
is the same in seconds on current firmware.

⚠️ A command is a GET request. That is how Tasmota is built, and why a button
here asks first.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

from . import demo as fake
from .base import (
    Action,
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

ADDRESS_HINT = "Check the URL; it is the address Tasmota's web interface opens at, usually the device's IP address."
POWER_KEY = re.compile(r"^POWER(\d*)$")


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def _seconds(sts: dict[str, Any]) -> float | None:
    """How long the device has been up."""
    given = _number(sts.get("UptimeSec"))
    if given is not None:
        return given
    found = re.match(r"^(?:(\d+)T)?(\d+):(\d+):(\d+)$", str(sts.get("Uptime") or ""))
    if not found:
        return None
    days, hours, minutes, seconds = (int(part or 0) for part in found.groups())
    return float(days * 86400 + hours * 3600 + minutes * 60 + seconds)


def relays_of(status: dict[str, Any]) -> list[tuple[int, str, bool]]:
    """The relays of a device as ``(number, name, on)``, in order."""
    sts = status.get("StatusSTS") if isinstance(status.get("StatusSTS"), dict) else {}
    names = (status.get("Status") or {}).get("FriendlyName") if isinstance(status.get("Status"), dict) else None
    if isinstance(names, str):
        names = [names]
    found: list[tuple[int, str, bool]] = []
    for key, value in sts.items():
        matched = POWER_KEY.match(key)
        if not matched:
            continue
        number = int(matched.group(1) or 1)
        name = str(names[number - 1]).strip() if isinstance(names, list) and 0 < number <= len(names) and names[number - 1] else ""
        found.append((number, name, str(value).upper() == "ON"))
    return sorted(found)


class TasmotaAdapter(Adapter):
    kind = "tasmota"
    label = "Tasmota"
    category = "other"
    description = "A Tasmota plug or relay: whether it is on, a button to switch it, and the power it draws with the energy of the day."
    icon = "tasmota"
    beta = True
    docs_url = "https://tasmota.github.io/docs/Commands/"
    keywords = ("smart plug", "Sonoff", "smart home", "energy")
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://192.0.2.50",
              help="The address of the device, as its web interface opens."),
        Field("username", "User", placeholder="admin", help="Only if the device has a web password. Tasmota's user is admin unless changed."),
        Field("password", "Password", type="password", secret=True, help="The web password of the device (WebPassword)."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(
            kind="relay", label="Relay",
            description="Whether the relay is on, with a button to switch it after a question, and how well the device is connected. One card for each relay of the device.",
            renderer="value", default_size=(2, 2), refresh_seconds=30, metrics=("signal",),
            options=(Field("relay", "Relay", type="number", default=1, help="The number of the relay, 1 for a plug."),),
            parts=(("name", "Device"), ("firmware", "Firmware"), ("signal", "Wi-Fi signal"), ("uptime", "Up for")),
        ),
        WidgetType(
            kind="energy", label="Power draw",
            description="The power the plug draws now, its voltage and current, and the energy of today, yesterday and in total. Needs a device that measures.",
            renderer="value", default_size=(3, 2), refresh_seconds=30, metrics=("power_w", "voltage_v", "today_kwh"),
            parts=(("voltage", "Voltage"), ("current", "Current"), ("today", "Today"), ("yesterday", "Yesterday"), ("total", "Total")),
        ),
    )

    # -- talking to the device -----------------------------------------------

    async def _command(self, config: dict[str, Any], ctx: Context, command: str, *, cache: float = 0) -> dict[str, Any]:
        user = str(config.get("username") or "").strip() or "admin"
        password = str(config.get("password") or "")
        response = await ctx.request(
            "GET", f"{base_url(config)}/cm?cmnd={quote(command, safe='')}", headers={"Accept": "application/json"},
            auth=(user, password) if password else None, verify=not config.get("insecure"), timeout=10.0,
            cache_seconds=cache, auth_errors=False)
        try:
            body = response.json()
        except ValueError as error:
            if response.status_code in (401, 403):
                body = None
            else:
                raise AdapterError("This address answers with something other than Tasmota.", code="not_tasmota", hint=ADDRESS_HINT) from error
        if response.status_code in (401, 403) or (isinstance(body, dict) and "WARNING" in body):
            error_ = AuthFailed("The device turned the user or the password down." if password else "The device asks for a web password.")
            error_.hint = "Fill in the web password of the device (WebPassword); the user is admin unless it was changed."
            raise error_
        if response.status_code >= 400:
            raise AdapterError(f"The device answered with HTTP {response.status_code}.", code="http_error", hint=ADDRESS_HINT)
        if not isinstance(body, dict):
            raise AdapterError("This address answers, but not the way Tasmota does.", code="not_tasmota", hint=ADDRESS_HINT)
        if body.get("Command") == "Unknown":
            raise AdapterError("The device does not know that command.", code="unknown_command", hint="Update Tasmota.")
        return body

    async def _status(self, config: dict[str, Any], ctx: Context) -> dict[str, Any]:
        status = await self._command(config, ctx, "Status 0", cache=5)
        if "StatusSTS" not in status and "Status" not in status:
            raise AdapterError("This address answers, but not the way Tasmota does.", code="not_tasmota", hint=ADDRESS_HINT)
        return status

    # -- the hooks -----------------------------------------------------------

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        status = await self._command(config, ctx, "Status 0")
        firmware = status.get("StatusFWR") if isinstance(status.get("StatusFWR"), dict) else {}
        version = str(firmware.get("Version") or "").split("(", 1)[0]
        if not version and "Status" not in status:
            raise AdapterError("This address answers, but not the way Tasmota does.", code="not_tasmota", hint=ADDRESS_HINT)
        return f"Tasmota {version or '?'} answers with {len(relays_of(status))} relays."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        status = await self._status(config, ctx)
        return self._energy_card(status) if widget_kind == "energy" else self._relay_card(status, options.get("relay"))

    async def action(self, widget_kind: str, action_id: str, params: dict[str, Any], config: dict[str, Any],
                     options: dict[str, Any], ctx: Context) -> str:
        if action_id not in ("on", "off"):
            raise AdapterError("Unknown relay action.", code="no_such_action")
        try:
            number = int(str(params.get("relay") or "1"))
        except ValueError:
            number = 0
        if not 1 <= number <= 32:
            raise AdapterError("That is not a relay number.", code="bad_param")
        await self._command(config, ctx, f"Power{number} {action_id.upper()}")
        ctx.forget_answers()
        return "Switched on." if action_id == "on" else "Switched off."

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def _relay_card(status: dict[str, Any], wanted: Any = 1) -> WidgetData:
        try:
            number = int(str(wanted if wanted not in (None, "") else 1))
        except ValueError:
            number = 1
        relays = relays_of(status)
        info = status.get("Status") if isinstance(status.get("Status"), dict) else {}
        sts = status.get("StatusSTS") if isinstance(status.get("StatusSTS"), dict) else {}
        firmware = status.get("StatusFWR") if isinstance(status.get("StatusFWR"), dict) else {}
        wifi = sts.get("Wifi") if isinstance(sts.get("Wifi"), dict) else {}
        signal = _number(wifi.get("RSSI"))
        secondary: list[dict[str, Any]] = []
        device = str(info.get("DeviceName") or "").strip()
        if device:
            secondary.append({"label": "Device", "value": device, "part": "name"})
        if firmware.get("Version"):
            secondary.append({"label": "Firmware", "value": str(firmware["Version"]).split("(", 1)[0], "part": "firmware"})
        if signal is not None:
            secondary.append({"label": "Wi-Fi signal", "value": f"{signal:.0f} %", "part": "signal"})
        seconds = _seconds(sts)
        if seconds is not None:
            secondary.append({"label": "Up for", "value": duration_short(seconds), "part": "uptime"})
        chosen = next((relay for relay in relays if relay[0] == number), None)
        if chosen is None:
            raise AdapterError(f"This device has no relay {number}.", code="no_relay",
                               hint="It has " + (", ".join(str(relay[0]) for relay in relays) or "none") + ". Set the relay number in the card's settings.")
        _, name, on = chosen
        return WidgetData(
            primary={"label": name or "Relay", "value": "On" if on else "Off"}, secondary=secondary,
            actions=[Action(id="off" if on else "on", label="Turn off" if on else "Turn on", icon="power", confirm=True,
                            params={"relay": str(number)})],
            metrics=measured({"signal": signal}), meta={"actions_visible": True},
        )

    @staticmethod
    def _energy_card(status: dict[str, Any]) -> WidgetData:
        sns = status.get("StatusSNS") if isinstance(status.get("StatusSNS"), dict) else {}
        energy = sns.get("ENERGY") if isinstance(sns.get("ENERGY"), dict) else None
        if energy is None:
            raise AdapterError("This device does not measure power.", code="no_energy",
                               hint="Only a plug or module with a measuring chip has an ENERGY block; use the relay card instead.")
        power, voltage, current = _number(energy.get("Power")), _number(energy.get("Voltage")), _number(energy.get("Current"))
        today = _number(energy.get("Today"))
        secondary: list[dict[str, Any]] = []
        if voltage is not None:
            secondary.append({"label": "Voltage", "value": f"{voltage:g} V", "part": "voltage"})
        if current is not None:
            secondary.append({"label": "Current", "value": f"{current:.2f} A", "part": "current"})
        for key, label, part in (("Today", "Today", "today"), ("Yesterday", "Yesterday", "yesterday"), ("Total", "Total", "total")):
            value = _number(energy.get(key))
            if value is not None:
                secondary.append({"label": label, "value": f"{value:.2f} kWh", "part": part})
        return WidgetData(
            primary={"label": "Power", "value": power if power is not None else 0, "unit": "W"},
            secondary=secondary,
            metrics=measured({"power_w": power, "voltage_v": voltage, "today_kwh": today}),
        )

    # -- demo ----------------------------------------------------------------

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        on = fake.flicker("tasmota-relay", tick, 0.7)
        power = round(fake.walk("tasmota-power", tick, 35, 420, period=200)) if on else 0
        status: dict[str, Any] = {
            "Status": {"DeviceName": "Plug", "FriendlyName": ["Washing machine"]},
            "StatusFWR": {"Version": "13.4.0(tasmota)"},
            "StatusSTS": {"UptimeSec": 86_400 * 9 + tick * 30, "POWER": "ON" if on else "OFF", "Wifi": {"RSSI": round(fake.walk("tasmota-wifi", tick, 55, 90))}},
            "StatusSNS": {"ENERGY": {"Power": power, "Voltage": 230, "Current": round(power / 230, 3), "Today": round(0.4 + tick * 0.001, 3),
                                     "Yesterday": 1.82, "Total": 412.6}},
        }
        return self._energy_card(status) if widget_kind == "energy" else self._relay_card(status)


ADAPTER = TasmotaAdapter()
