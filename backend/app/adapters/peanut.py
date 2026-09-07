"""The UPS, read through PeaNUT.

The one measurement that is only interesting when it is bad. NUT itself speaks
its own TCP protocol; PeaNUT puts a REST interface in front of it, and that is
what this adapter talks to.
"""

from __future__ import annotations

from typing import Any

from . import demo as fake
from .base import (
    Adapter,
    AdapterError,
    Context,
    Field,
    WidgetData,
    WidgetType,
    base_url,
    duration_short,
    percent_primary,
    percent_text,
)

#: What the NUT status flags mean. Everything unknown counts as a warning.
FLAGS = {
    "OL": ("On mains", "ok"),
    "OB": ("On battery", "bad"),
    "LB": ("Battery low", "bad"),
    "RB": ("Replace battery", "bad"),
    "CHRG": ("Charging", "warn"),
    "DISCHRG": ("Discharging", "warn"),
    "BYPASS": ("Bypass", "warn"),
    "OFF": ("Switched off", "bad"),
    "OVER": ("Overloaded", "bad"),
    "TRIM": ("Trimming voltage", "warn"),
    "BOOST": ("Boosting voltage", "warn"),
}


class PeanutAdapter(Adapter):
    kind = "peanut"
    label = "UPS (PeaNUT)"
    category = "monitoring"
    description = "Charge, load and the runtime left, from a NUT server through PeaNUT."
    icon = "peanut"
    docs_url = "https://github.com/Brandawg93/PeaNUT"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://peanut:8080"),
        Field("device", "Device", help="The name of the UPS in NUT. Empty takes the first one."),
        Field("username", "User name", help="Only if PeaNUT is set up with a sign-in."),
        Field("password", "Password", type="password", secret=True),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(
            kind="ups",
            label="UPS",
            description="Charge as a gauge, with load, runtime and what the UPS is doing.",
            renderer="gauge",
            default_size=(2, 2),
            refresh_seconds=30,
            metrics=("charge", "load", "runtime"),
        ),
        WidgetType(
            kind="details",
            label="UPS details",
            description="Voltage, load, temperature and the model, one line each.",
            renderer="stats",
            default_size=(3, 2),
            refresh_seconds=60,
        ),
    )

    def _auth(self, config: dict[str, Any]) -> tuple[str, str] | None:
        user = str(config.get("username") or "")
        return (user, str(config.get("password") or "")) if user else None

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, cache: float = 15) -> Any:
        return await ctx.get_json(
            f"{base_url(config)}/api/v1{path}",
            auth=self._auth(config),
            verify=not config.get("insecure"),
            cache_seconds=cache,
        )

    async def _device(self, config: dict[str, Any], ctx: Context, cache: float = 15) -> tuple[str, dict[str, Any]]:
        """The chosen UPS with its variables, or the first one PeaNUT knows."""
        wanted = str(config.get("device") or "").strip()
        if not wanted:
            devices = await self._get(config, ctx, "/devices", cache=300)
            names = [str(entry.get("name") or entry) for entry in devices] if isinstance(devices, list) else []
            if not names:
                raise AdapterError("PeaNUT knows no UPS.", code="no_device", hint="Check the NUT connection of PeaNUT.")
            wanted = names[0]
        payload = await self._get(config, ctx, f"/devices/{wanted}", cache=cache)
        variables = payload.get("vars") if isinstance(payload, dict) and "vars" in payload else payload
        return wanted, (variables if isinstance(variables, dict) else {})

    @staticmethod
    def _number(variables: dict[str, Any], key: str) -> float | None:
        value = variables.get(key)
        if value is None:
            return None
        try:
            return float(str(value).split()[0])
        except (TypeError, ValueError):
            return None

    def _state(self, variables: dict[str, Any]) -> tuple[str, str]:
        raw = str(variables.get("ups.status") or "").strip()
        words = [FLAGS.get(flag, (flag, "warn")) for flag in raw.split() if flag]
        if not words:
            return "Unknown", "warn"
        text = ", ".join(word for word, _ in words)
        level = "bad" if any(state == "bad" for _, state in words) else ("warn" if any(state == "warn" for _, state in words) else "ok")
        return text, level

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        name, variables = await self._device(config, ctx, cache=0)
        model = variables.get("device.model") or variables.get("ups.model") or "UPS"
        return f"PeaNUT answers for {name} ({model})."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        name, variables = await self._device(config, ctx)
        charge = self._number(variables, "battery.charge")
        load = self._number(variables, "ups.load")
        runtime = self._number(variables, "battery.runtime")
        text, level = self._state(variables)

        if widget_kind == "details":
            rows = [
                ("Model", variables.get("device.model") or variables.get("ups.model") or "?"),
                ("State", text),
                ("Load", f"{load:.0f} %" if load is not None else "?"),
                ("Input voltage", f"{self._number(variables, 'input.voltage') or '?'} V"),
                ("Output voltage", f"{self._number(variables, 'output.voltage') or '?'} V"),
                ("Battery voltage", f"{self._number(variables, 'battery.voltage') or '?'} V"),
                ("Runtime", duration_short(runtime) if runtime is not None else "?"),
            ]
            return WidgetData(
                status=level,
                secondary=[{"label": label, "value": value} for label, value in rows] + [{"label": "Device", "value": name}],
            )

        return WidgetData(
            status=level if level != "ok" else ("warn" if charge is not None and charge < 50 else "ok"),
            # ⚠️ A UPS that does not report ``battery.charge`` had this card
            # showing a charge of 0 percent, which reads as an empty battery
            # rather than as a UPS that keeps that number to itself. Small
            # models genuinely do not send it.
            primary=percent_primary("Charge", round(charge, 0) if charge is not None else None),
            secondary=[
                {"label": "State", "value": text},
                {"label": "Load", "value": percent_text(load)},
                {"label": "Runtime", "value": duration_short(runtime) if runtime is not None else "?"},
            ],
            metrics={
                **({"charge": round(charge, 1)} if charge is not None else {}),
                **({"load": round(load, 1)} if load is not None else {}),
                **({"runtime": round(runtime, 0)} if runtime is not None else {}),
            },
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        outage = fake.flicker("peanut-outage", tick, 0.06)
        charge = fake.walk("peanut-charge", tick, 88, 100) if not outage else fake.walk("peanut-drain", tick, 42, 86)
        load = fake.walk("peanut-load", tick, 14, 38)
        runtime = 60 * (18 if not outage else 9)
        text, level = ("On battery, Discharging", "bad") if outage else ("On mains", "ok")
        if widget_kind == "details":
            rows = [
                ("Model", "Example 1500VA"),
                ("State", text),
                ("Load", f"{load:.0f} %"),
                ("Input voltage", "231.0 V" if not outage else "0.0 V"),
                ("Output voltage", "230.0 V"),
                ("Battery voltage", "27.1 V"),
                ("Runtime", duration_short(runtime)),
            ]
            return WidgetData(
                status=level,
                secondary=[{"label": label, "value": value} for label, value in rows] + [{"label": "Device", "value": "ups"}],
            )
        return WidgetData(
            status=level,
            primary={"label": "Charge", "value": round(charge), "unit": "%"},
            secondary=[
                {"label": "State", "value": text},
                {"label": "Load", "value": f"{load:.0f} %"},
                {"label": "Runtime", "value": duration_short(runtime)},
            ],
            metrics={"charge": charge, "load": load, "runtime": float(runtime)},
        )


ADAPTER = PeanutAdapter()
