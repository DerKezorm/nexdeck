"""Fronius: what the solar system makes, what the house uses, and what goes to or comes from the grid.

⚠️ Not measured. There is no Fronius inverter to run in a container, and the
Solar API is not simulated by anything free. Built from Fronius' "Solar API V1"
documentation (the power flow request) and the answers people publish of it;
every claim below is the documentation's.

``GET /solar_api/v1/GetPowerFlowRealtimeData.fcgi`` answers the state of the
whole site in one request: ``Body.Data.Site`` with ``P_PV``, ``P_Grid``,
``P_Load``, ``P_Akku`` (watts), ``E_Day``, ``E_Year``, ``E_Total`` (watt hours),
``rel_Autonomy`` and ``rel_SelfConsumption`` (per cent) and ``Mode``; and
``Body.Data.Inverters`` with an entry per inverter, ``SOC`` on one that has a
battery. ``Head.Status.Code`` is 0 when it worked.

⚠️ The signs: ``P_Grid`` is positive while the house takes from the grid and
negative while it feeds in; ``P_Load`` is *negative* while the house uses power;
``P_Akku`` is positive while the battery gives out. ``P_PV`` is ``null`` at night,
and ``P_Akku`` is ``null`` without a battery. ``P_Grid`` and ``P_Load`` are ``null``
in the mode ``produce-only``, which is an inverter without a meter: then the
consumption of the house is not known, and the flow card says so.

⚠️ The Solar API has no sign-in. Fronius lets a user switch it off in the
inverter's settings (Communication, Solar API), and the answer is then a 404 on
that address.
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
    measured,
)

ADDRESS_HINT = "Check the URL; it is the address of the inverter or its Datamanager, as its web interface opens."
NO_API_HINT = "Switch the Solar API on in the inverter's settings under Communication, Solar API."


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def _kilowatts(watts: float | None) -> float | None:
    return round(watts / 1000.0, 3) if watts is not None else None


class FroniusAdapter(Adapter):
    kind = "fronius"
    label = "Fronius"
    category = "other"
    description = "The power the solar system makes now, what the house uses, and what goes to or comes from the grid, with the energy of the day."
    icon = "fronius"
    beta = True
    docs_url = "https://www.fronius.com/en/solar-energy/installers-partners/technical-data/all-products/system-monitoring/open-interfaces/fronius-solar-api-json-"
    keywords = ("solar", "photovoltaic", "inverter", "energy")
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://192.0.2.60",
              help="The address of the inverter or its Datamanager. The Solar API has no sign-in."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(
            kind="production", label="Solar production",
            description="The power the solar system makes now, with the energy of today, this year and in total, and how much of it the house uses itself.",
            renderer="value", default_size=(3, 2), refresh_seconds=30, metrics=("power_w", "grid_w", "home_w"),
            parts=(("today", "Today"), ("year", "This year"), ("total", "Total"), ("selfuse", "Used by the house"), ("autonomy", "Own supply")),
        ),
        WidgetType(
            kind="flow", label="Energy flow",
            description="Solar, house, battery and grid as one picture, with the power moving between them. Needs a meter, which gives the house's use.",
            renderer="flow", default_size=(4, 3), refresh_seconds=15, metrics=("home", "pv", "grid"),
        ),
    )

    # -- talking to the inverter ---------------------------------------------

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, *, cache: float = 0) -> Any:
        response = await ctx.request(
            "GET", f"{base_url(config)}{path}", headers={"Accept": "application/json"}, verify=not config.get("insecure"),
            timeout=15.0, cache_seconds=cache, auth_errors=False)
        if response.status_code == 404:
            raise AdapterError("The inverter has no Solar API at this address.", code="no_api", hint=NO_API_HINT)
        if response.status_code >= 400:
            raise AdapterError(f"The inverter answered with HTTP {response.status_code}.", code="http_error", hint=ADDRESS_HINT)
        try:
            return response.json()
        except ValueError as error:
            raise AdapterError("This address answers with something other than a Fronius inverter.", code="not_fronius", hint=ADDRESS_HINT) from error

    async def _site(self, config: dict[str, Any], ctx: Context) -> tuple[dict[str, Any], dict[str, Any]]:
        """The ``Site`` and the ``Inverters`` of the power flow answer."""
        answer = await self._get(config, ctx, "/solar_api/v1/GetPowerFlowRealtimeData.fcgi", cache=5)
        head = answer.get("Head") if isinstance(answer, dict) and isinstance(answer.get("Head"), dict) else None
        data = (answer.get("Body") or {}).get("Data") if isinstance(answer, dict) and isinstance(answer.get("Body"), dict) else None
        if head is None or not isinstance(data, dict) or not isinstance(data.get("Site"), dict):
            raise AdapterError("This address answers, but not the way a Fronius inverter does.", code="not_fronius", hint=ADDRESS_HINT)
        status = head.get("Status") if isinstance(head.get("Status"), dict) else {}
        if status.get("Code") not in (0, None):
            raise AdapterError(f"The inverter reports: {str(status.get('Reason') or status.get('UserMessage') or 'an error').strip()}.",
                               code="inverter_error", hint="Look at the inverter's own page.")
        return data["Site"], data.get("Inverters") if isinstance(data.get("Inverters"), dict) else {}

    # -- the hooks -----------------------------------------------------------

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        version = await self._get(config, ctx, "/solar_api/GetAPIVersion.cgi")
        if not isinstance(version, dict) or "APIVersion" not in version:
            raise AdapterError("This address answers, but not the way a Fronius inverter does.", code="not_fronius", hint=ADDRESS_HINT)
        site, inverters = await self._site(config, ctx)
        return f"Fronius Solar API {version['APIVersion']} answers with {len(inverters)} inverters. Mode: {site.get('Mode') or '?'}."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        site, inverters = await self._site(config, ctx)
        return self._flow_card(site, inverters) if widget_kind == "flow" else self._production_card(site)

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def _production_card(site: dict[str, Any]) -> WidgetData:
        solar = _number(site.get("P_PV"))
        grid, load = _number(site.get("P_Grid")), _number(site.get("P_Load"))
        # ⚠️ null at night: the system makes nothing, which is a number.
        power = solar if solar is not None else 0.0
        secondary: list[dict[str, Any]] = []
        for key, label, part in (("E_Day", "Today", "today"), ("E_Year", "This year", "year"), ("E_Total", "Total", "total")):
            value = _number(site.get(key))
            if value is not None:
                secondary.append({"label": label, "value": f"{value / 1000:.1f} kWh" if key == "E_Day" else f"{value / 1000:.0f} kWh", "part": part})
        used = _number(site.get("rel_SelfConsumption"))
        if used is not None:
            secondary.append({"label": "Used by the house", "value": f"{used:.0f} %", "part": "selfuse"})
        autonomy = _number(site.get("rel_Autonomy"))
        if autonomy is not None:
            secondary.append({"label": "Own supply", "value": f"{autonomy:.0f} %", "part": "autonomy"})
        return WidgetData(
            primary={"label": "Solar power", "value": round(power), "unit": "W"},
            secondary=secondary,
            metrics=measured({"power_w": power, "grid_w": grid, "home_w": abs(load) if load is not None else None}),
        )

    @staticmethod
    def _flow_card(site: dict[str, Any], inverters: dict[str, Any]) -> WidgetData:
        load = _number(site.get("P_Load"))
        if load is None:
            raise AdapterError("This inverter has no meter, so the use of the house is not known.", code="no_meter",
                               hint="The energy flow needs a Fronius Smart Meter; the solar production card works without one.")
        solar, grid, battery = _number(site.get("P_PV")), _number(site.get("P_Grid")), _number(site.get("P_Akku"))
        soc = next((_number(one.get("SOC")) for one in inverters.values() if isinstance(one, dict) and _number(one.get("SOC")) is not None), None)
        home = round(abs(load) / 1000.0, 3)
        flow = {
            "solar": _kilowatts(solar if solar is not None else 0.0),
            "home": home,
            "grid": _kilowatts(grid),
            "battery": _kilowatts(battery),
            "battery_soc": round(soc, 1) if soc is not None else None,
            "car": None,
        }
        return WidgetData(
            primary={"label": "House", "value": home, "unit": "kW"},
            metrics=measured({"home": home, "pv": flow["solar"], "grid": flow["grid"]}),
            meta={"flow": flow},
        )

    # -- demo ----------------------------------------------------------------

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        solar = round(fake.walk("fronius-pv", tick, 200, 6200, period=600))
        load = round(fake.walk("fronius-load", tick, 380, 2400, period=240))
        battery = round(max(-2500.0, min(2500.0, load - solar - fake.walk("fronius-grid", tick, -300, 300))))
        site = {"P_PV": solar, "P_Load": -load, "P_Akku": battery, "P_Grid": round(load - solar - battery),
                "E_Day": 8200 + tick * 12, "E_Year": 4_120_000, "E_Total": 31_800_000, "rel_SelfConsumption": 64.2, "rel_Autonomy": 71.0}
        if widget_kind == "flow":
            return self._flow_card(site, {"1": {"SOC": round(fake.walk("fronius-soc", tick, 22, 97, period=900), 1)}})
        return self._production_card(site)


ADAPTER = FroniusAdapter()
