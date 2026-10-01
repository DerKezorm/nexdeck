"""evcc: where the power in the house goes, and what the car is doing.

One address answers everything: ``/api/state`` hands out the whole state, and
reading it needs no password. Two traps live in that answer. Older evcc wrapped
it in ``result``, and the charged energy is in watt hours although the
reference says kilowatt hours; both are handled here.
"""

from __future__ import annotations

from typing import Any

from . import demo as fake
from .base import Adapter, Context, Field, WidgetData, WidgetType, base_url

#: What evcc calls a mode, in words a card can show.
MODES = {"off": "Off", "now": "Fast", "minpv": "Solar and minimum", "pv": "Solar only", "smart": "Smart"}


def _kilowatts(watts: Any) -> float:
    return round(float(watts or 0) / 1000.0, 2)


def _grid_watts(state: dict[str, Any]) -> Any:
    grid = state.get("grid")
    return grid.get("power") if isinstance(grid, dict) else state.get("gridPower")


def _battery(state: dict[str, Any]) -> tuple[Any, Any]:
    """Battery power in watts (positive while it feeds the house) and its charge, from either shape evcc used."""
    battery = state.get("battery")
    power = state.get("batteryPower")
    soc = state.get("batterySoc")
    if isinstance(battery, dict):
        power = battery.get("power", power)
        soc = battery.get("soc", soc)
    elif isinstance(battery, list) and battery:
        # One entry per battery in newer evcc: the powers add up, the charge is the mean.
        powers = [float(one.get("power") or 0) for one in battery if isinstance(one, dict)]
        socs = [float(one["soc"]) for one in battery if isinstance(one, dict) and isinstance(one.get("soc"), (int, float))]
        power = sum(powers) if powers else power
        soc = sum(socs) / len(socs) if socs else soc
    return power, soc


def flow_of(state: dict[str, Any]) -> WidgetData:
    """Where the power goes, in kilowatts, for the energy flow card.

    Signs as evcc has them: the grid is positive while the house takes from
    it, the battery positive while it gives to the house. A battery or a car
    the installation does not have is left out, not drawn as zero.
    """
    battery_power, battery_soc = _battery(state)
    points = state.get("loadpoints") or []
    car = sum(float(point.get("chargePower") or 0) for point in points if isinstance(point, dict))
    has_battery = battery_power is not None or battery_soc is not None
    flow = {
        "solar": _kilowatts(state.get("pvPower")),
        "home": _kilowatts(state.get("homePower")),
        "grid": _kilowatts(_grid_watts(state)),
        "battery": _kilowatts(battery_power) if has_battery else None,
        "battery_soc": round(float(battery_soc), 1) if isinstance(battery_soc, (int, float)) else None,
        "car": _kilowatts(car) if points else None,
    }
    return WidgetData(
        primary={"label": "House", "value": flow["home"], "unit": "kW"},
        metrics={"home": flow["home"], "pv": flow["solar"], "grid": flow["grid"]},
        meta={"flow": flow},
    )


class EvccAdapter(Adapter):
    kind = "evcc"
    label = "evcc"
    category = "other"
    description = "House, solar, grid and battery, and what the wallbox is charging."
    icon = "evcc"
    #: Seen against a live evcc 0.315.0 (06.09.2026).
    beta = False
    docs_url = "https://docs.evcc.io/en/integrations/rest-api/"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://evcc:7070"),
        Field("token", "API key", type="password", secret=True, help="Only if evcc was set up to guard reading as well."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(
            kind="energy",
            label="Energy",
            description="House, solar, grid and battery, one line each.",
            renderer="stats",
            default_size=(3, 2),
            refresh_seconds=30,
            metrics=("home", "pv", "grid", "battery"),
        ),
        WidgetType(
            kind="flow",
            label="Energy flow",
            description="Solar, house, battery, grid and car as one picture, with the power moving between them.",
            renderer="flow",
            default_size=(4, 3),
            refresh_seconds=15,
            metrics=("home", "pv", "grid"),
        ),
        WidgetType(
            kind="charging",
            label="Charging",
            description="One line per charging point with its mode and what the car has taken.",
            renderer="list",
            default_size=(4, 2),
            refresh_seconds=30,
            metrics=("charging", "charge_power"),
        ),
    )

    async def _state(self, config: dict[str, Any], ctx: Context, cache: float = 20) -> dict[str, Any]:
        headers = {"Accept": "application/json"}
        key = str(config.get("token") or "")
        if key:
            headers["Authorization"] = f"Bearer {key}"
        payload = await ctx.get_json(
            f"{base_url(config)}/api/state",
            headers=headers,
            verify=not config.get("insecure"),
            cache_seconds=cache,
        )
        state = payload if isinstance(payload, dict) else {}
        # evcc wrapped the state in "result" until 0.30; the shim in its own
        # code is still there, so the wrapper is still met in the wild.
        if "loadpoints" not in state and isinstance(state.get("result"), dict):
            return state["result"]
        return state

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        state = await self._state(config, ctx, cache=0)
        points = len(state.get("loadpoints") or [])
        return f"evcc {state.get('version', '?')} answers with {points} charging points."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        state = await self._state(config, ctx)

        if widget_kind == "charging":
            items = []
            charging = 0
            power = 0.0
            for point in state.get("loadpoints") or []:
                if point.get("charging"):
                    charging += 1
                power += float(point.get("chargePower") or 0)
                vehicle = str(point.get("vehicleTitle") or "").strip()
                title = str(point.get("title") or "?")
                soc = point.get("vehicleSoc")
                items.append({
                    "title": f"{title} · {vehicle}" if vehicle else title,
                    # The mode alone, so the interface can put it in German.
                    "subtitle": MODES.get(str(point.get("mode") or "").lower(), ""),
                    "value": f"{_kilowatts(point.get('chargePower'))} kW" if point.get("charging") else "",
                    "progress": float(soc) if isinstance(soc, (int, float)) and soc else None,
                    "status": "ok" if point.get("charging") else ("warn" if point.get("connected") else "unknown"),
                })
            return WidgetData(
                items=items,
                secondary=[{"label": "Charging", "value": charging}, {"label": "Power", "value": f"{_kilowatts(power)} kW"}],
                metrics={"charging": float(charging), "charge_power": power},
                meta={"empty": "No charging point."},
            )

        if widget_kind == "flow":
            return flow_of(state)

        battery = state.get("battery")
        battery_soc = state.get("batterySoc")
        if battery_soc is None and isinstance(battery, dict):
            battery_soc = battery.get("soc")
        grid = state.get("grid")
        grid_power = grid.get("power") if isinstance(grid, dict) else state.get("gridPower")
        rows = [
            {"label": "Solar", "value": _kilowatts(state.get("pvPower")), "unit": "kW"},
            {"label": "Grid", "value": _kilowatts(grid_power), "unit": "kW"},
        ]
        if battery_soc is not None:
            rows.append({"label": "Battery", "value": round(float(battery_soc), 1), "unit": "%"})
        return WidgetData(
            primary={"label": "House", "value": _kilowatts(state.get("homePower")), "unit": "kW"},
            secondary=rows,
            metrics={
                "home": _kilowatts(state.get("homePower")),
                "pv": _kilowatts(state.get("pvPower")),
                "grid": _kilowatts(grid_power),
                "battery": float(battery_soc or 0),
            },
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        solar = fake.walk("evcc-pv", tick, 0.2, 6.4, period=600)
        house = fake.walk("evcc-home", tick, 0.3, 1.9, period=240)
        charging = fake.flicker("evcc-charging", tick, 0.6)
        car = 7.4 if charging else 0.0

        if widget_kind == "charging":
            items = [
                {
                    "title": "Garage · Kombi",
                    "subtitle": MODES["pv"],
                    "value": f"{car} kW" if charging else "",
                    "progress": fake.walk("evcc-soc", tick, 42, 92, period=1200),
                    "status": "ok" if charging else "warn",
                },
                {"title": "Carport", "subtitle": MODES["off"], "value": "", "progress": None, "status": "unknown"},
            ]
            return WidgetData(
                items=items,
                secondary=[{"label": "Charging", "value": 1 if charging else 0}, {"label": "Power", "value": f"{car} kW"}],
                metrics={"charging": 1.0 if charging else 0.0, "charge_power": car * 1000},
                meta={"empty": "No charging point."},
            )

        grid = round(house + car - solar, 2)
        if widget_kind == "flow":
            battery = round(min(2.5, max(-2.5, house + car - solar - grid * 0.4)), 2)
            return WidgetData(
                primary={"label": "House", "value": house, "unit": "kW"},
                metrics={"home": house, "pv": solar, "grid": round(grid - battery, 2)},
                meta={"flow": {"solar": round(solar, 2), "home": round(house, 2), "grid": round(grid - battery, 2), "battery": battery,
                               "battery_soc": round(fake.walk("evcc-battery", tick, 24, 98, period=1500), 1), "car": car}},
            )
        return WidgetData(
            primary={"label": "House", "value": house, "unit": "kW"},
            secondary=[
                {"label": "Solar", "value": solar, "unit": "kW"},
                {"label": "Grid", "value": grid, "unit": "kW"},
                {"label": "Battery", "value": fake.walk("evcc-battery", tick, 24, 98, period=1500), "unit": "%"},
            ],
            metrics={"home": house, "pv": solar, "grid": grid, "battery": fake.walk("evcc-battery", tick, 24, 98, period=1500)},
        )


ADAPTER = EvccAdapter()
