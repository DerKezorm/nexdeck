"""Shelly: the relays you can switch, and the power they draw, on both generations.

⚠️ Not measured. A Shelly is a device, and there is no container for one.
Built from Shelly's API documentation (Gen1 device API and the Gen2+ RPC
documentation); every claim below is theirs.

``GET /shelly`` needs no sign-in and tells the generation: a Gen2+ device has
``gen`` (2, 3, 4) next to ``id``, ``model``, ``ver`` and ``auth_en``; a Gen1
device has ``type``, ``fw`` and ``auth``.

Gen1: ``GET /status`` has ``relays[]`` (``ison``), ``meters[]`` (``power`` in W,
``total`` in watt minutes), ``emeters[]`` (``power`` in W, ``total`` in Wh),
``temperature``, ``uptime``, ``wifi_sta.rssi`` and ``update.has_update``. A relay
is switched with ``GET /relay/N?turn=on|off``. Names are in ``GET /settings``
(``relays[].name``). Sign-in is HTTP Basic.

Gen2+: ``GET /rpc/Shelly.GetStatus`` has one entry per component: ``switch:N``
(``output``, ``apower`` in W, ``aenergy.total`` in Wh, ``temperature.tC``),
``pm1:N`` and ``em1:N`` (``apower``, ``act_power``), ``em:N`` (``total_act_power``),
``sys`` (``uptime``, ``available_updates``) and ``wifi`` (``rssi``). A switch is
set with ``GET /rpc/Switch.Set?id=N&on=true``. Names are in
``Shelly.GetConfig``. Sign-in is HTTP **Digest with SHA-256**, user ``admin``,
the realm is the device id; after repeated wrong tries the device answers 429.

⚠️ ``apower`` is missing on a switch without a measuring chip (a Plus 1), and
``output`` is missing on a component that cannot switch (``pm1``, ``em1``).
Those rows have a power and no button, or a button and no power.

⚠️ A Gen1 meter counts in watt minutes; 60 000 of them are a kilowatt hour.
"""

from __future__ import annotations

import re
from typing import Any

import httpx

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

ADDRESS_HINT = "Check the URL; it is the address of the device, as its web interface opens."
COMPONENT = re.compile(r"^(switch|pm1|em1):(\d+)$")


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


class ShellyAdapter(Adapter):
    kind = "shelly"
    label = "Shelly"
    category = "other"
    description = "A Shelly relay or plug, Gen1 or Gen2 and newer: whether it is on, a button to switch it, and the power it draws."
    icon = "shelly"
    beta = True
    docs_url = "https://shelly-api-docs.shelly.cloud/gen2/"
    keywords = ("smart plug", "relay", "smart home", "energy", "Shelly Plus", "Shelly Pro")
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://192.0.2.40",
              help="The address of the device. Both generations are told apart by themselves."),
        Field("username", "User", placeholder="admin",
              help="Only a Gen1 device has a user of its own; a Gen2 or newer one is always admin."),
        Field("password", "Password", type="password", secret=True, help="Only if the device has a sign-in set."),
    )
    widgets = (
        WidgetType(
            kind="power", label="Power draw",
            description="The power all measuring channels of the device draw now, with the energy they have used, the temperature and the Wi-Fi signal.",
            renderer="value", default_size=(3, 2), refresh_seconds=30, metrics=("power_w", "temperature"),
            parts=(("energy", "Energy"), ("temperature", "Temperature"), ("signal", "Wi-Fi signal"), ("uptime", "Up for"), ("update", "Firmware")),
        ),
        WidgetType(
            kind="switches", label="Switches",
            description="Each relay of the device, on or off with the power it draws, and a button to switch it after a question.",
            renderer="list", default_size=(3, 2), refresh_seconds=30,
        ),
    )

    # -- talking to the device -----------------------------------------------

    async def _generation(self, config: dict[str, Any], ctx: Context) -> tuple[int, dict[str, Any]]:
        """1 or 2 and what ``/shelly`` said; this address needs no sign-in on either."""
        kept = ctx.cache.get("shelly_identity")
        if kept:
            return kept
        response = await ctx.request("GET", f"{base_url(config)}/shelly", headers={"Accept": "application/json"}, timeout=10.0, auth_errors=False)
        try:
            identity = response.json() if response.status_code == 200 else None
        except ValueError:
            identity = None
        if not isinstance(identity, dict) or not ("gen" in identity or "type" in identity):
            raise AdapterError("This address answers, but not the way a Shelly does.", code="not_shelly", hint=ADDRESS_HINT)
        found = (int(identity["gen"]) if isinstance(identity.get("gen"), int) else 2, identity) if "gen" in identity else (1, identity)
        ctx.cache["shelly_identity"] = found
        return found

    def _auth(self, config: dict[str, Any], ctx: Context, generation: int) -> Any:
        password = str(config.get("password") or "")
        if not password:
            return None
        if generation == 1:
            return (str(config.get("username") or "").strip() or "admin", password)
        # One Digest object for the connection: it remembers the device's nonce, which the device lets it reuse.
        return ctx.cache.setdefault("shelly_digest", httpx.DigestAuth("admin", password))

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, *, cache: float = 0, optional: bool = False) -> Any:
        generation, _ = await self._generation(config, ctx)
        response = await ctx.request(
            "GET", f"{base_url(config)}{path}", headers={"Accept": "application/json"}, auth=self._auth(config, ctx, generation),
            timeout=10.0, cache_seconds=cache, auth_errors=False)
        if response.status_code == 429:
            raise AdapterError("The device turned the sign-in away after too many tries.", code="rate_limited",
                               hint="Wait a few minutes, then check the password.")
        if response.status_code in (401, 403):
            error = AuthFailed("The device asks for a password." if not config.get("password") else "The device turned the password down.")
            error.hint = "Fill in the password set in the device's web interface" + (" (the user is admin)." if generation > 1 else ".")
            raise error
        if optional and response.status_code >= 400:
            return None
        if response.status_code >= 400:
            raise AdapterError(f"The device answered with HTTP {response.status_code}.", code="http_error", hint=ADDRESS_HINT)
        try:
            return response.json()
        except ValueError as error:
            raise AdapterError("This address answers with something other than a Shelly.", code="not_shelly", hint=ADDRESS_HINT) from error

    async def _device(self, config: dict[str, Any], ctx: Context) -> dict[str, Any]:
        """The device as one shape for both generations: channels (id, name, on, power, energy_kwh) and the rest."""
        generation, identity = await self._generation(config, ctx)
        if generation == 1:
            status = await self._get(config, ctx, "/status", cache=5)
            settings = await self._get(config, ctx, "/settings", cache=300, optional=True)
            return self._from_gen1(status, settings, identity)
        status = await self._get(config, ctx, "/rpc/Shelly.GetStatus", cache=5)
        names = await self._get(config, ctx, "/rpc/Shelly.GetConfig", cache=300, optional=True)
        return self._from_gen2(status, names, identity)

    @staticmethod
    def _from_gen1(status: Any, settings: Any, identity: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(status, dict):
            raise AdapterError("This address answers, but not the way a Shelly does.", code="not_shelly", hint=ADDRESS_HINT)
        relays = status.get("relays") if isinstance(status.get("relays"), list) else []
        meters = status.get("meters") if isinstance(status.get("meters"), list) else []
        emeters = status.get("emeters") if isinstance(status.get("emeters"), list) else []
        names = [one.get("name") for one in settings.get("relays", []) if isinstance(one, dict)] if isinstance(settings, dict) else []
        channels: list[dict[str, Any]] = []
        for index, relay in enumerate(relays):
            meter = meters[index] if index < len(meters) and isinstance(meters[index], dict) else {}
            total = _number(meter.get("total"))
            channels.append({"id": index, "name": str(names[index]).strip() if index < len(names) and names[index] else "",
                             "on": bool(relay.get("ison")) if isinstance(relay, dict) else None, "switch": True,
                             "power": _number(meter.get("power")), "energy_kwh": total / 60000.0 if total is not None else None})
        # A device with a meter and no relay (an EM) has a channel to read and none to press.
        for index, meter in enumerate(emeters):
            if isinstance(meter, dict):
                total = _number(meter.get("total"))
                channels.append({"id": 100 + index, "name": "", "on": None, "switch": False, "power": _number(meter.get("power")),
                                 "energy_kwh": total / 1000.0 if total is not None else None})
        if not relays:
            for index, meter in enumerate(meters):
                total = _number(meter.get("total")) if isinstance(meter, dict) else None
                channels.append({"id": 100 + index, "name": "", "on": None, "switch": False, "power": _number(meter.get("power")) if isinstance(meter, dict) else None,
                                 "energy_kwh": total / 60000.0 if total is not None else None})
        temperature = _number(status.get("temperature"))
        if temperature is None and isinstance(status.get("tmp"), dict):
            temperature = _number(status["tmp"].get("tC"))
        wifi = status.get("wifi_sta") if isinstance(status.get("wifi_sta"), dict) else {}
        update = status.get("update") if isinstance(status.get("update"), dict) else {}
        return {"generation": 1, "model": str(identity.get("type") or ""), "channels": channels, "temperature": temperature,
                "uptime": _number(status.get("uptime")), "rssi": _number(wifi.get("rssi")), "update": bool(update.get("has_update"))}

    @staticmethod
    def _from_gen2(status: Any, config: Any, identity: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(status, dict):
            raise AdapterError("This address answers, but not the way a Shelly does.", code="not_shelly", hint=ADDRESS_HINT)
        channels: list[dict[str, Any]] = []
        temperature: float | None = None
        for key in sorted(status, key=lambda name: (name.split(":")[0], int(name.split(":")[1]) if ":" in name and name.split(":")[1].isdigit() else 0)):
            matched = COMPONENT.match(key)
            part = status[key]
            if not matched or not isinstance(part, dict):
                if key.startswith("em:") and isinstance(part, dict):
                    channels.append({"id": 100 + int(key.split(":")[1] or 0), "name": "", "on": None, "switch": False,
                                     "power": _number(part.get("total_act_power")), "energy_kwh": None})
                continue
            kind, number = matched.group(1), int(matched.group(2))
            name = ""
            if isinstance(config, dict) and isinstance(config.get(key), dict):
                name = str(config[key].get("name") or "").strip()
            energy = part.get("aenergy") if isinstance(part.get("aenergy"), dict) else {}
            total = _number(energy.get("total"))
            power = _number(part.get("apower") if kind != "em1" else part.get("act_power"))
            channels.append({"id": number if kind == "switch" else 100 + number, "name": name,
                             "on": bool(part["output"]) if kind == "switch" and "output" in part else None, "switch": kind == "switch",
                             "power": power, "energy_kwh": total / 1000.0 if total is not None else None})
            tc = part.get("temperature")
            if temperature is None and isinstance(tc, dict):
                temperature = _number(tc.get("tC"))
        system = status.get("sys") if isinstance(status.get("sys"), dict) else {}
        wifi = status.get("wifi") if isinstance(status.get("wifi"), dict) else {}
        available = system.get("available_updates") if isinstance(system.get("available_updates"), dict) else {}
        return {"generation": 2, "model": str(identity.get("app") or identity.get("model") or ""), "channels": channels,
                "temperature": temperature, "uptime": _number(system.get("uptime")), "rssi": _number(wifi.get("rssi")),
                "update": bool(available.get("stable"))}

    # -- the hooks -----------------------------------------------------------

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        generation, identity = await self._generation(config, ctx)
        device = await self._device(config, ctx)
        model = device["model"] or "Shelly"
        version = str(identity.get("ver") or identity.get("fw") or "").split("/")[0].split("-")[0].lstrip("v")
        return f"Shelly {model} answers (generation {generation}, firmware {version or '?'}) with {sum(1 for one in device['channels'] if one['switch'])} relays."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        device = await self._device(config, ctx)
        return self._switches_card(device) if widget_kind == "switches" else self._power_card(device)

    async def action(self, widget_kind: str, action_id: str, params: dict[str, Any], config: dict[str, Any],
                     options: dict[str, Any], ctx: Context) -> str:
        if action_id not in ("on", "off"):
            raise AdapterError("Unknown relay action.", code="no_such_action")
        try:
            number = int(str(params.get("channel")))
        except ValueError:
            number = -1
        if not 0 <= number <= 7:
            raise AdapterError("That is not a relay number.", code="bad_param")
        generation, _ = await self._generation(config, ctx)
        path = f"/relay/{number}?turn={action_id}" if generation == 1 else f"/rpc/Switch.Set?id={number}&on={'true' if action_id == 'on' else 'false'}"
        await self._get(config, ctx, path)
        ctx.forget_answers()
        return "Switched on." if action_id == "on" else "Switched off."

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def _power_card(device: dict[str, Any]) -> WidgetData:
        measuring = [one for one in device["channels"] if one["power"] is not None]
        if not measuring:
            raise AdapterError("This device does not measure power.", code="no_energy",
                               hint="A Shelly without a power meter (a Plus 1, a 1) has the switches card only.")
        power = sum(one["power"] for one in measuring)
        energy = [one["energy_kwh"] for one in measuring if one["energy_kwh"] is not None]
        secondary: list[dict[str, Any]] = []
        if energy:
            secondary.append({"label": "Energy", "value": f"{sum(energy):.2f} kWh", "part": "energy"})
        if device["temperature"] is not None:
            secondary.append({"label": "Temperature", "value": f"{device['temperature']:.1f} °C", "part": "temperature"})
        if device["rssi"] is not None:
            secondary.append({"label": "Wi-Fi signal", "value": f"{device['rssi']:.0f} dBm", "part": "signal"})
        if device["uptime"] is not None:
            secondary.append({"label": "Up for", "value": duration_short(device["uptime"]), "part": "uptime"})
        if device["update"]:
            secondary.append({"label": "Firmware", "value": "Update available", "part": "update"})
        return WidgetData(
            primary={"label": "Power", "value": round(power, 1), "unit": "W"}, secondary=secondary,
            metrics=measured({"power_w": power, "temperature": device["temperature"]}),
        )

    @staticmethod
    def _switches_card(device: dict[str, Any]) -> WidgetData:
        switches = [one for one in device["channels"] if one["switch"]]
        rows = []
        for one in switches:
            name = one["name"] or ("Switch" if len(switches) == 1 else f"Switch {one['id'] + 1}")
            rows.append({
                "id": f"channel-{one['id']}", "title": name,
                "subtitle": f"{one['power']:.0f} W" if one["power"] is not None and one["on"] else "",
                "value": "On" if one["on"] else "Off", "status": "ok" if one["on"] else "unknown",
                "actions": [Action(id="off" if one["on"] else "on", label="Turn off" if one["on"] else "Turn on", icon="power", confirm=True,
                                   params={"channel": str(one["id"])})],
            })
        return WidgetData(items=rows, secondary=[{"label": "Switches on", "value": sum(1 for one in switches if one["on"])}],
                          meta={"empty": "This device has no relay.", "actions_visible": True})

    # -- demo ----------------------------------------------------------------

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        on = fake.flicker("shelly-relay", tick, 0.7)
        power = round(fake.walk("shelly-power", tick, 12, 1850, period=260), 1) if on else 0.0
        device = {
            "generation": 2, "model": "Plus2PM", "temperature": round(fake.walk("shelly-temp", tick, 31, 52), 1), "uptime": 86_400 * 21 + tick * 30,
            "rssi": round(fake.walk("shelly-wifi", tick, -78, -48)), "update": False,
            "channels": [
                {"id": 0, "name": "Boiler", "on": on, "switch": True, "power": power, "energy_kwh": 128.4 + tick * 0.01},
                {"id": 1, "name": "Pump", "on": True, "switch": True, "power": round(fake.walk("shelly-pump", tick, 40, 80), 1), "energy_kwh": 31.2},
            ],
        }
        return self._switches_card(device) if widget_kind == "switches" else self._power_card(device)


ADAPTER = ShellyAdapter()
