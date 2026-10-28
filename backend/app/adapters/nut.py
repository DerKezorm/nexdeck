"""NUT: a UPS read straight from upsd, Network UPS Tools' own server, without PeaNUT in between.

Measured against NUT 2.8.2 on 27.10.2026: upsd and the dummy-ups driver in an
Alpine container, fed from a file of the variables a real UPS sends. The
dummy reloads the file when it changes, which is how the state was changed
from online to on battery and back.

⚠️ Port 3493, a text protocol, one line per command. ``LIST UPS`` answers
``BEGIN LIST UPS`` / ``UPS <name> "<description>"`` / ``END LIST UPS``, and
``LIST VAR <name>`` the same with ``VAR <name> <variable> "<value>"``. Reading
needs no login: ``USERNAME`` and ``PASSWORD`` are for commands and ``SET``,
which this adapter never sends. Values are quoted, ``\\"`` and ``\\\\`` escape
inside them. An error is one line, ``ERR <CODE>``: ``UNKNOWN-UPS`` for a name
upsd does not have, ``VAR-NOT-SUPPORTED`` for a variable the UPS does not
send, and, measured by killing the driver, ``DRIVER-NOT-CONNECTED`` for the
UPS whose driver died while upsd lives on. The server is asked ``VER``;
``VERSION`` is an unknown command.

⚠️ Variables are the UPS's own business. The dummy sent ``ups.realpower`` in
watts; many real ones send only ``ups.load`` and ``ups.realpower.nominal``,
and some neither. Watts are taken from the first and worked out from the
second and third, and left out when neither is there, never guessed from the
VA rating. ``battery.charge`` is missing on small models (a charge of 0 would
read as an empty battery), and ``battery.runtime`` is in seconds.

⚠️ What is not measured: ``ERR ACCESS-DENIED`` (an address upsd's access rules
turn away), ``ERR DATA-STALE`` (a UPS that stopped answering its driver) and
TLS (``STARTTLS`` answered ``FEATURE-NOT-CONFIGURED``). They are handled as
the NUT protocol document describes them.
"""

from __future__ import annotations

import asyncio
import re
import time
from typing import Any

from . import demo as fake
from .base import (
    Adapter,
    AdapterError,
    AuthFailed,
    Context,
    Detected,
    Field,
    Unreachable,
    WidgetData,
    WidgetType,
    duration_short,
    guard_outbound,
    measured,
    percent_primary,
    percent_text,
)

DEFAULT_PORT = 3493
TIMEOUT = 6.0
#: A UPS has a few dozen variables; a server that sends more is not upsd.
MAX_LINES = 2000
#: Three cards on one connection read the UPS once, not three times.
SHARED_SECONDS = 5.0
CACHE = "nut"
#: What upsd's names for a UPS may be made of (``ups.conf`` section names).
UPS_NAME = re.compile(r"^[A-Za-z0-9_.@-]{1,64}$")
VAR_LINE = re.compile(r'^VAR (\S+) (\S+) "(.*)"$')

#: What the status flags of ``ups.status`` mean. An unknown flag counts as a warning.
FLAGS = {
    "OL": ("On mains", "ok"),
    "OB": ("On battery", "bad"),
    "LB": ("Battery low", "bad"),
    "HB": ("Battery high", "ok"),
    "RB": ("Replace battery", "bad"),
    "CHRG": ("Charging", "warn"),
    "DISCHRG": ("Discharging", "warn"),
    "BYPASS": ("Bypass", "warn"),
    "CAL": ("Calibrating", "warn"),
    "OFF": ("Switched off", "bad"),
    "OVER": ("Overloaded", "bad"),
    "TRIM": ("Trimming voltage", "warn"),
    "BOOST": ("Boosting voltage", "warn"),
    "FSD": ("Shutdown forced", "bad"),
    "ALARM": ("Alarm", "bad"),
}
#: Where the server's own words for an error go in plain English.
ERRORS = {
    "UNKNOWN-UPS": "upsd has no UPS of that name.",
    "DRIVER-NOT-CONNECTED": "upsd is running, but the driver is not connected to the UPS.",
    "DATA-STALE": "The UPS stopped answering its driver.",
    "VAR-NOT-SUPPORTED": "The UPS does not send that value.",
}


def _unquote(text: str) -> str:
    return re.sub(r'\\(["\\])', r"\1", text)


def _number(variables: dict[str, str], key: str) -> float | None:
    try:
        return float(str(variables.get(key, "")).split()[0])
    except (IndexError, ValueError):
        return None


def _bad_line(line: str) -> AdapterError:
    word = line.split(" ", 1)[1].strip() if line.startswith("ERR ") else ""
    if word == "ACCESS-DENIED":
        return AuthFailed("upsd turned this address away.")
    return AdapterError(ERRORS.get(word) or f"upsd answered {line[:60]!r}.", code=f"nut_{word.lower().replace('-', '_')}" if word else "not_nut",
                        hint="Check the name of the UPS and that its driver runs." if word else "The port is 3493 of upsd, not a web page.")


async def _send(writer: asyncio.StreamWriter, line: str) -> None:
    writer.write((line + "\n").encode("ascii", "replace"))
    await writer.drain()


async def _read_block(reader: asyncio.StreamReader, what: str) -> list[str]:
    """The lines between ``BEGIN LIST <what>`` and ``END LIST <what>``; an ``ERR`` line instead is an error."""
    lines: list[str] = []
    began = False
    while len(lines) < MAX_LINES:
        raw = await asyncio.wait_for(reader.readline(), TIMEOUT)
        if not raw:
            raise AdapterError("upsd closed the connection.", code="not_nut", hint="The port is 3493 of upsd, not a web page.")
        line = raw.decode("utf-8", "replace").rstrip("\r\n")
        if not began:
            if line == f"BEGIN LIST {what}":
                began = True
                continue
            raise _bad_line(line)
        if line == f"END LIST {what}":
            return lines
        lines.append(line)
    raise AdapterError("upsd sent far more than a UPS has.", code="not_nut")


def _target(config: dict[str, Any]) -> tuple[str, int]:
    host = str(config.get("host") or "").strip()
    for scheme in ("nut://", "tcp://", "http://", "https://"):
        if host.lower().startswith(scheme):
            host = host[len(scheme):]
    host = host.strip("/")
    port_text = str(config.get("port") or "").strip()
    if host.count(":") == 1:
        host, _, typed = host.partition(":")
        port_text = port_text or typed
    host = host.strip("[]").strip()
    if not host:
        raise AdapterError("This connection names no server.", code="bad_url", hint="Enter the address of the machine upsd runs on.")
    try:
        port = int(port_text) if port_text else DEFAULT_PORT
    except ValueError:
        port = 0
    if not 0 < port < 65536:
        raise AdapterError("That is not a port number.", code="bad_url", hint="upsd listens on 3493 unless somebody changed it.")
    # ⚠️ Not HTTP, and the same rule as every other connection: link-local and the cloud metadata service are barred.
    guard_outbound(f"http://{f'[{host}]' if ':' in host else host}:{port}")
    return host, port


async def read_ups(config: dict[str, Any]) -> tuple[str, dict[str, str], list[str]]:
    """The chosen UPS (the first one without a name), its variables, and the names upsd knows."""
    host, port = _target(config)
    wanted = str(config.get("ups") or "").strip()
    if wanted and not UPS_NAME.match(wanted):
        raise AdapterError("That is not a name upsd can have for a UPS.", code="bad_param", hint="Use the name from ups.conf, such as ups.")
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), TIMEOUT)
    except TimeoutError as error:
        raise Unreachable("upsd did not answer in time.") from error
    except OSError as error:
        raise Unreachable(f"upsd could not be reached: {error.__class__.__name__}.") from error
    try:
        await _send(writer, "LIST UPS")
        names = []
        for line in await _read_block(reader, "UPS"):
            found = re.match(r"^UPS (\S+) ", line)
            if found:
                names.append(found.group(1))
        if not names:
            raise AdapterError("upsd knows no UPS.", code="no_device", hint="Check ups.conf and that the driver started.")
        name = wanted or names[0]
        if name not in names:
            raise AdapterError(f"upsd has no UPS called {name}.", code="no_such_ups", hint="It has: " + ", ".join(names[:8]) + ".")
        await _send(writer, f"LIST VAR {name}")
        variables: dict[str, str] = {}
        for line in await _read_block(reader, f"VAR {name}"):
            found = VAR_LINE.match(line)
            if found and found.group(1) == name:
                variables[found.group(2)] = _unquote(found.group(3))
        try:
            await _send(writer, "LOGOUT")
        except OSError:
            pass
        return name, variables, names
    except (TimeoutError, asyncio.IncompleteReadError) as error:
        raise Unreachable("upsd did not answer in time.") from error
    except (ConnectionError, OSError) as error:
        raise Unreachable(f"upsd could not be reached: {error.__class__.__name__}.") from error
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except OSError:
            pass


def state_of(variables: dict[str, str]) -> tuple[str, str, bool]:
    """The words for ``ups.status``, their colour, and whether the UPS runs on its battery."""
    flags = str(variables.get("ups.status") or "").split()
    if not flags:
        return "Unknown", "warn", False
    words = [FLAGS.get(flag, (flag, "warn")) for flag in flags]
    level = "bad" if any(colour == "bad" for _word, colour in words) else "warn" if any(colour == "warn" for _word, colour in words) else "ok"
    return " · ".join(word for word, _colour in words), level, "OB" in flags


def power_of(variables: dict[str, str]) -> float | None:
    """Watts: what the UPS says, or its rated watts times its load. Nothing else is a number worth showing."""
    direct = _number(variables, "ups.realpower")
    if direct is not None:
        return round(direct, 1)
    nominal, load = _number(variables, "ups.realpower.nominal"), _number(variables, "ups.load")
    return round(nominal * load / 100, 1) if nominal is not None and load is not None else None


class NutAdapter(Adapter):
    kind = "nut"
    label = "NUT"
    category = "monitoring"
    description = "Charge, runtime, load, power and input voltage of a UPS, read from upsd itself, red while it runs on battery."
    icon = "nut"
    #: Measured on 2026-10-27 against NUT 2.8.2 with the dummy driver, not yet a real UPS.
    beta = True
    docs_url = "https://networkupstools.org/docs/developer-guide.chunked/net-protocol.html"
    keywords = ("ups", "network ups tools", "upsd", "battery")
    fields = (
        Field("host", "Server", required=True, placeholder="nut.example.com",
              help="The machine upsd runs on. It has to listen on a network address (LISTEN in upsd.conf), and reading needs no login."),
        Field("port", "Port", type="number", help="Empty means 3493."),
        Field("ups", "UPS", placeholder="ups", help="The name from ups.conf. Empty takes the first one upsd knows."),
    )
    widgets = (
        WidgetType(kind="ups", label="UPS", description="Charge as a gauge, with the state, load, runtime and power; red while the UPS runs on battery.",
                   renderer="gauge", default_size=(2, 2), refresh_seconds=20, metrics=("charge", "load", "runtime", "power", "input_voltage")),
        WidgetType(kind="power", label="UPS power", description="What the UPS delivers in watts, with the load and the voltage that comes in.",
                   renderer="value", default_size=(2, 2), refresh_seconds=30, metrics=("power", "input_voltage")),
        WidgetType(kind="details", label="UPS details", description="State, charge, runtime, load, power, voltages, temperature and the model, one line each.",
                   renderer="stats", default_size=(3, 3), refresh_seconds=60),
    )

    async def _read(self, config: dict[str, Any], ctx: Context) -> tuple[str, dict[str, str]]:
        kept = ctx.cache.get(CACHE)
        if isinstance(kept, tuple) and kept[0] > time.monotonic():
            return kept[1], kept[2]
        name, variables, _names = await read_ups(config)
        ctx.cache[CACHE] = (time.monotonic() + SHARED_SECONDS, name, variables)
        return name, variables

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        name, variables, names = await read_ups(config)
        model = variables.get("device.model") or variables.get("ups.model") or "UPS"
        more = f", {len(names)} UPS in all" if len(names) > 1 else ""
        return f"upsd answers for {name} ({model}){more}."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        name, variables = await self._read(config, ctx)
        return self._card(widget_kind, name, variables)

    def detect(self, widget_kind: str, before: WidgetData | None, after: WidgetData, options: dict[str, Any]) -> list[Detected]:
        """The mains went away, and came back. Never on the first look: a UPS that was already on battery is not news."""
        if widget_kind != "ups" or before is None or before.error or after.error:
            return []
        was, now = before.meta.get("on_battery"), after.meta.get("on_battery")
        if was is None or now is None or was == now:
            return []
        name = str(after.meta.get("ups") or "UPS")
        value = (after.primary or {}).get("value")
        charge = f"{value:.0f}%" if isinstance(value, int | float) else ""
        if now:
            left = next((row["value"] for row in after.secondary if row.get("label") == "Runtime"), "")
            body = ", ".join(part for part in (f"charge {charge}" if charge else "", f"about {left} left" if left and left != "?" else "") if part)
            return [Detected(event="ups_on_battery", title=f"{name} runs on battery", body=body, level="bad", key=f"ups_on_battery:{name}", quiet_seconds=300)]
        return [Detected(event="ups_online", title=f"{name} is back on mains", body=f"charge {charge}" if charge else "", level="ok",
                         key=f"ups_online:{name}", quiet_seconds=300)]

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def _card(widget_kind: str, name: str, variables: dict[str, str]) -> WidgetData:
        charge = _number(variables, "battery.charge")
        load = _number(variables, "ups.load")
        runtime = _number(variables, "battery.runtime")
        watts = power_of(variables)
        volts_in = _number(variables, "input.voltage")
        text, level, on_battery = state_of(variables)
        # The UPS says what it calls low (battery.charge.low, battery.charge.warning); without that, under half is a warning.
        low, warning = _number(variables, "battery.charge.low"), _number(variables, "battery.charge.warning")
        if charge is not None and level != "bad" and low is not None and charge <= low:
            level = "bad"
        elif charge is not None and level == "ok" and charge <= (warning if warning is not None else 50):
            level = "warn"
        metrics = measured({"charge": None if charge is None else round(charge, 1), "load": None if load is None else round(load, 1),
                            "runtime": None if runtime is None else round(runtime), "power": watts,
                            "input_voltage": None if volts_in is None else round(volts_in, 1)})
        meta = {"on_battery": on_battery, "ups": name}
        runtime_text = duration_short(runtime) if runtime is not None else "?"

        if widget_kind == "power":
            return WidgetData(
                status=level,
                primary={"label": "Power", "value": watts, "unit": "W" if watts is not None else ""},
                secondary=[{"label": "State", "value": text}, {"label": "Load", "value": percent_text(load)},
                           {"label": "Input voltage", "value": f"{volts_in:.0f} V" if volts_in is not None else "?"}],
                metrics={key: value for key, value in metrics.items() if key in ("power", "input_voltage")},
                meta=meta,
            )
        if widget_kind == "details":
            def volts(key: str) -> str:
                value = _number(variables, key)
                return f"{value:.1f} V" if value is not None else "?"

            temperature = _number(variables, "ups.temperature")
            rows = [
                ("Model", variables.get("device.model") or variables.get("ups.model") or "?"),
                ("State", text),
                ("Charge", percent_text(charge)),
                ("Runtime", runtime_text),
                ("Load", percent_text(load)),
                ("Power", f"{watts:.0f} W" if watts is not None else "?"),
                ("Input voltage", volts("input.voltage")),
                ("Output voltage", volts("output.voltage")),
                ("Battery voltage", volts("battery.voltage")),
                ("Temperature", f"{temperature:.1f} °C" if temperature is not None else "?"),
            ]
            return WidgetData(status=level, secondary=[{"label": label, "value": value} for label, value in rows] + [{"label": "Device", "value": name}], meta=meta)
        return WidgetData(
            status=level,
            # ⚠️ A UPS that does not send battery.charge is not at 0 percent; the dial then has nothing to show.
            primary=percent_primary("Charge", round(charge) if charge is not None else None),
            secondary=[{"label": "State", "value": text}, {"label": "Load", "value": percent_text(load)},
                       {"label": "Runtime", "value": runtime_text},
                       {"label": "Power", "value": f"{watts:.0f} W" if watts is not None else "?"}],
            metrics=metrics,
            meta=meta,
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        outage = fake.flicker("nut-outage", tick, 0.06)
        charge = fake.walk("nut-drain", tick, 42, 86) if outage else fake.walk("nut-charge", tick, 92, 100)
        load = fake.walk("nut-load", tick, 14, 38)
        variables = {
            "ups.status": "OB DISCHRG" if outage else "OL", "battery.charge": f"{charge}", "battery.charge.low": "20", "battery.charge.warning": "50",
            "battery.runtime": f"{60 * (9 if outage else 18)}", "battery.voltage": "27.1", "ups.load": f"{load}", "ups.realpower.nominal": "900",
            "input.voltage": "0.0" if outage else f"{fake.walk('nut-line', tick, 228, 233)}", "output.voltage": "230.0", "ups.temperature": "31.5",
            "device.model": "Example 1500VA",
        }
        return self._card(widget_kind, "ups", variables)


ADAPTER = NutAdapter()
