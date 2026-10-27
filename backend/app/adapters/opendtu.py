"""OpenDTU: what the micro inverters behind it make, and whether they answer.

⚠️ Not measured. OpenDTU is firmware for an ESP32 with a radio chip that talks
to Hoymiles inverters; there is no container for it, and the radio cannot be
simulated. Built from OpenDTU's Web API documentation and its source (the
live data request); every claim below is theirs.

``GET /api/livedata/status`` answers the state of the whole system: ``total``
(``Power``, ``YieldDay``, ``YieldTotal``), ``inverters`` and ``hints``. Every
value is an object ``{"v": 201.4, "u": "W", "d": 1}``: the number, its unit and
the decimals it is shown with. An inverter has ``serial``, ``name``,
``reachable``, ``producing``, ``data_age`` (seconds), ``limit_relative`` and
``limit_absolute`` and, depending on the version, ``AC``, ``DC`` and ``INV`` blocks
keyed by the number of the channel as text ("0"). Newer versions send the
blocks only when asked for one inverter (``?inv=<serial>``), so every one is
read where it is there and left out where it is not.

⚠️ ``YieldDay`` comes in Wh and ``YieldTotal`` in kWh in the same answer. The
unit is read from the value, not assumed.

⚠️ An inverter that is not reachable is the normal state at night: the panels
make nothing, the inverter sleeps, and OpenDTU has nobody to ask. So it is
grey, not red. A radio that does not work is the ``radio_problem`` hint.

⚠️ Reading needs no sign-in when "Allow readonly access to API" is on in
OpenDTU's security settings, which it is by default; otherwise the user is
``admin`` and the password is the one of the web interface (HTTP Basic).
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
    measured,
)

ADDRESS_HINT = "Check the URL; it is the address of OpenDTU's web interface, usually the device's IP address."


def _value(block: Any, key: str) -> tuple[float | None, str]:
    """The number and the unit of one ``{"v", "u", "d"}`` value."""
    entry = block.get(key) if isinstance(block, dict) else None
    if not isinstance(entry, dict) or isinstance(entry.get("v"), bool) or not isinstance(entry.get("v"), int | float):
        return None, ""
    return float(entry["v"]), str(entry.get("u") or "")


def _kwh(block: Any, key: str) -> float | None:
    number, unit = _value(block, key)
    if number is None:
        return None
    return number / 1000.0 if unit == "Wh" else number


def _first(blocks: Any) -> dict[str, Any]:
    """The first channel of an ``AC``, ``DC`` or ``INV`` block."""
    if not isinstance(blocks, dict) or not blocks:
        return {}
    one = blocks.get("0") if "0" in blocks else blocks[sorted(blocks)[0]]
    return one if isinstance(one, dict) else {}


class OpenDtuAdapter(Adapter):
    kind = "opendtu"
    label = "OpenDTU"
    category = "other"
    description = "The power your Hoymiles micro inverters make now, the energy of the day, and which inverters answer."
    icon = "opendtu"
    beta = True
    docs_url = "https://github.com/tbnobody/OpenDTU/blob/master/docs/Web-API.md"
    keywords = ("solar", "Hoymiles", "micro inverter", "energy", "ESP32")
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://192.0.2.70",
              help="The address of OpenDTU's web interface."),
        Field("password", "Password", type="password", secret=True,
              help="Only if read-only access to the API is switched off in OpenDTU. The user is admin."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(
            kind="power", label="Solar power",
            description="The power all inverters make together now, with the energy of today and in total, and how many of them are producing.",
            renderer="value", default_size=(3, 2), refresh_seconds=30, metrics=("power_w", "yield_day_kwh"),
            parts=(("today", "Today"), ("total", "Total"), ("producing", "Producing")),
        ),
        WidgetType(
            kind="inverters", label="Inverters",
            description="Each inverter with its power, whether it answers, and its temperature and power limit where OpenDTU says them.",
            renderer="list", default_size=(3, 3), refresh_seconds=30,
        ),
    )

    # -- talking to OpenDTU --------------------------------------------------

    async def _live(self, config: dict[str, Any], ctx: Context) -> dict[str, Any]:
        password = str(config.get("password") or "")
        response = await ctx.request(
            "GET", f"{base_url(config)}/api/livedata/status", headers={"Accept": "application/json"},
            auth=("admin", password) if password else None, verify=not config.get("insecure"), timeout=15.0,
            cache_seconds=5, auth_errors=False)
        if response.status_code in (401, 403):
            error = AuthFailed("OpenDTU asks for a password." if not password else "OpenDTU turned the password down.")
            error.hint = "Fill in the password of OpenDTU's web interface (the user is admin), or switch on read-only access to the API in its security settings."
            raise error
        if response.status_code >= 400:
            raise AdapterError(f"OpenDTU answered with HTTP {response.status_code}.", code="http_error", hint=ADDRESS_HINT)
        try:
            live = response.json()
        except ValueError as error:
            raise AdapterError("This address answers with something other than OpenDTU.", code="not_opendtu", hint=ADDRESS_HINT) from error
        if not isinstance(live, dict) or not isinstance(live.get("inverters"), list) or not isinstance(live.get("total"), dict):
            raise AdapterError("This address answers, but not the way OpenDTU does.", code="not_opendtu", hint=ADDRESS_HINT)
        return live

    # -- the hooks -----------------------------------------------------------

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        live = await self._live(config, ctx)
        return f"OpenDTU answers with {len(live['inverters'])} inverters."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        live = await self._live(config, ctx)
        return self._inverters_card(live) if widget_kind == "inverters" else self._power_card(live)

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def _problem(live: dict[str, Any]) -> str:
        hints = live.get("hints") if isinstance(live.get("hints"), dict) else {}
        if hints.get("radio_problem"):
            return "The radio does not work."
        return "OpenDTU still has its default password." if hints.get("default_password") else ""

    @classmethod
    def _power_card(cls, live: dict[str, Any]) -> WidgetData:
        total = live["total"]
        power, _ = _value(total, "Power")
        today, total_kwh = _kwh(total, "YieldDay"), _kwh(total, "YieldTotal")
        inverters = [one for one in live["inverters"] if isinstance(one, dict)]
        producing = sum(1 for one in inverters if one.get("producing"))
        secondary: list[dict[str, Any]] = []
        if today is not None:
            secondary.append({"label": "Today", "value": f"{today:.2f} kWh", "part": "today"})
        if total_kwh is not None:
            secondary.append({"label": "Total", "value": f"{total_kwh:.0f} kWh", "part": "total"})
        secondary.append({"label": "Producing", "value": producing, "part": "producing"})
        problem = cls._problem(live)
        return WidgetData(
            status="warn" if problem else "ok",
            primary={"label": "Solar power", "value": round(power, 1) if power is not None else 0, "unit": "W"},
            secondary=secondary,
            metrics=measured({"power_w": power if power is not None else 0.0, "yield_day_kwh": today}),
            meta={"status_reason": problem},
        )

    @classmethod
    def _inverters_card(cls, live: dict[str, Any]) -> WidgetData:
        rows = []
        for one in sorted((one for one in live["inverters"] if isinstance(one, dict)), key=lambda one: (one.get("order") or 0, str(one.get("name")))):
            power, _ = _value(_first(one.get("AC")), "Power")
            temperature, _ = _value(_first(one.get("INV")), "Temperature")
            limit = one.get("limit_relative")
            reachable, producing = bool(one.get("reachable")), bool(one.get("producing"))
            details = [f"{temperature:.0f} °C"] if temperature is not None else []
            if isinstance(limit, int | float) and not isinstance(limit, bool) and limit < 100:
                details.append(f"{limit:.0f} %")
            rows.append({
                "id": one.get("serial"), "title": str(one.get("name") or one.get("serial") or "?"),
                "subtitle": " · ".join(details),
                "value": f"{power:.0f} W" if producing and power is not None else "Producing" if producing else "Asleep" if not reachable else "Idle",
                "status": "ok" if producing else "unknown",
            })
        problem = cls._problem(live)
        return WidgetData(
            status="warn" if problem else "ok", items=rows,
            secondary=[{"label": "Inverters", "value": len(rows)}],
            meta={"empty": "No inverter is set up in OpenDTU.", "status_reason": problem},
        )

    # -- demo ----------------------------------------------------------------

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        sun = fake.walk("opendtu-sun", tick, 0.05, 1.0, period=500)

        def block(value: float, unit: str) -> dict[str, Any]:
            return {"v": value, "u": unit, "d": 1}

        names = (("Roof south", 0, 1.0), ("Roof east", 1, 0.8), ("Garage", 2, 0.6))
        inverters = [
            {"serial": f"1141000000{index}", "name": name, "order": index, "reachable": True, "producing": sun * factor > 0.1,
             "data_age": 2, "limit_relative": 100 if index else 70,
             "AC": {"0": {"Power": block(round(sun * factor * 380, 1), "W")}}, "INV": {"0": {"Temperature": block(round(24 + sun * 18, 1), "°C")}}}
            for name, index, factor in names
        ]
        total = sum(one["AC"]["0"]["Power"]["v"] for one in inverters)
        live = {"total": {"Power": block(round(total, 1), "W"), "YieldDay": block(round(3200 + tick * 8.0), "Wh"), "YieldTotal": block(1423.5, "kWh")},
                "inverters": inverters, "hints": {"radio_problem": False, "default_password": False, "time_sync": False}}
        return self._inverters_card(live) if widget_kind == "inverters" else self._power_card(live)


ADAPTER = OpenDtuAdapter()
