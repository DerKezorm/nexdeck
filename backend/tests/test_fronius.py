"""Fronius, against answers written from the Solar API documentation (power flow realtime data).

Not run against an inverter: nothing here is measured, and the adapter is beta for that reason.
"""

from __future__ import annotations

import copy
from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, Context, Unreachable

FR = "http://192.0.2.60"
CONFIG = {"url": FR}
ADAPTER = get_adapter("fronius")
VERSION = {"APIVersion": 1, "BaseURL": "/solar_api/v1/", "CompatibilityRange": "1.6-2"}
HEAD = {"RequestArguments": {}, "Status": {"Code": 0, "Reason": "", "UserMessage": ""}, "Timestamp": "2026-10-27T12:00:00+01:00"}

#: A hybrid system at noon: 4.2 kW of sun, the house uses 1.1 kW, the battery takes 2.0 kW, 1.1 kW goes to the grid.
FLOW: dict[str, Any] = {
    "Head": HEAD,
    "Body": {"Data": {
        "Inverters": {"1": {"Battery_Mode": "normal", "DT": 99, "E_Day": 8200.5, "E_Total": 31_800_000.0, "E_Year": 4_120_000.0, "P": 4200.0, "SOC": 61.5}},
        "Site": {"E_Day": 8200.5, "E_Total": 31_800_000.0, "E_Year": 4_120_000.0, "Meter_Location": "grid", "Mode": "bidirectional",
                 "P_Akku": -2000.0, "P_Grid": -1100.0, "P_Load": -1100.0, "P_PV": 4200.0, "rel_Autonomy": 100.0, "rel_SelfConsumption": 73.8},
        "Version": "13"}},
}


def flow(**site: Any) -> dict[str, Any]:
    body = copy.deepcopy(FLOW)
    body["Body"]["Data"]["Site"].update(site)
    return body


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


def fresh() -> Context:
    return Context(httpx.AsyncClient(), cache={})


def serve(body: Any = None) -> None:
    respx.get(f"{FR}/solar_api/GetAPIVersion.cgi").mock(return_value=httpx.Response(200, json=VERSION))
    respx.get(f"{FR}/solar_api/v1/GetPowerFlowRealtimeData.fcgi").mock(return_value=httpx.Response(200, json=body if body is not None else FLOW))


@respx.mock
async def test_the_test_names_the_api_the_inverters_and_the_mode(ctx: Context) -> None:
    serve()
    assert await ADAPTER.test(CONFIG, ctx) == "Fronius Solar API 1 answers with 1 inverters. Mode: bidirectional."


@respx.mock
async def test_the_production_card(ctx: Context) -> None:
    serve()
    card = await ADAPTER.fetch("production", CONFIG, {}, ctx)
    assert card.status == "ok" and card.primary == {"label": "Solar power", "value": 4200, "unit": "W"}
    assert [(row["label"], row["value"]) for row in card.secondary] == [
        ("Today", "8.2 kWh"), ("This year", "4120 kWh"), ("Total", "31800 kWh"), ("Used by the house", "74 %"), ("Own supply", "100 %")]
    # Watts, as the inverter says them: the grid negative while feeding in, the house as a positive use.
    assert card.metrics == {"power_w": 4200.0, "grid_w": -1100.0, "home_w": 1100.0}


@respx.mock
async def test_at_night_the_system_makes_nothing_which_is_a_number(ctx: Context) -> None:
    # ⚠️ P_PV is null without sun, and P_Akku without a battery.
    serve(flow(P_PV=None, P_Akku=None, P_Grid=640.0, P_Load=-640.0, E_Day=None))
    card = await ADAPTER.fetch("production", CONFIG, {}, ctx)
    assert card.primary == {"label": "Solar power", "value": 0, "unit": "W"} and card.metrics["power_w"] == 0.0
    assert "Today" not in [row["label"] for row in card.secondary]


@respx.mock
async def test_the_flow_card_in_kilowatts_with_the_signs_of_the_inverter(ctx: Context) -> None:
    serve()
    card = await ADAPTER.fetch("flow", CONFIG, {}, ctx)
    assert card.meta["flow"] == {"solar": 4.2, "home": 1.1, "grid": -1.1, "battery": -2.0, "battery_soc": 61.5, "car": None}
    assert card.primary == {"label": "House", "value": 1.1, "unit": "kW"} and card.metrics == {"home": 1.1, "pv": 4.2, "grid": -1.1}


@respx.mock
async def test_without_a_battery_and_in_the_dark_the_flow_leaves_the_battery_out(ctx: Context) -> None:
    body = flow(P_PV=None, P_Akku=None, P_Grid=900.0, P_Load=-900.0)
    del body["Body"]["Data"]["Inverters"]["1"]["SOC"]
    serve(body)
    shown = (await ADAPTER.fetch("flow", CONFIG, {}, ctx)).meta["flow"]
    assert shown["battery"] is None and shown["battery_soc"] is None and shown["solar"] == 0.0 and shown["grid"] == 0.9


@respx.mock
async def test_an_inverter_without_a_meter_cannot_draw_the_flow_but_still_shows_production(ctx: Context) -> None:
    # ⚠️ Mode produce-only: P_Grid and P_Load are null.
    serve(flow(Mode="produce-only", P_Grid=None, P_Load=None, P_Akku=None))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.fetch("flow", CONFIG, {}, ctx)
    assert caught.value.code == "no_meter" and "Smart Meter" in caught.value.hint
    card = await ADAPTER.fetch("production", CONFIG, {}, fresh())
    assert card.primary["value"] == 4200 and card.metrics == {"power_w": 4200.0}


@respx.mock
async def test_the_inverters_own_error_is_said(ctx: Context) -> None:
    body = copy.deepcopy(FLOW)
    body["Head"]["Status"] = {"Code": 8, "Reason": "Request is not supported", "UserMessage": ""}
    serve(body)
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.fetch("production", CONFIG, {}, ctx)
    assert caught.value.code == "inverter_error" and "Request is not supported" in caught.value.message


@respx.mock
async def test_a_switched_off_api_unreachable_and_not_fronius(ctx: Context) -> None:
    respx.get(f"{FR}/solar_api/GetAPIVersion.cgi").mock(return_value=httpx.Response(404, text="Not Found"))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.test(CONFIG, ctx)
    assert caught.value.code == "no_api" and "Communication" in caught.value.hint
    respx.get(f"{FR}/solar_api/GetAPIVersion.cgi").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(Unreachable):
        await ADAPTER.test(CONFIG, fresh())
    respx.get(f"{FR}/solar_api/GetAPIVersion.cgi").mock(return_value=httpx.Response(200, text="<html>a router</html>"))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.test(CONFIG, fresh())
    assert caught.value.code == "not_fronius"
    respx.get(f"{FR}/solar_api/GetAPIVersion.cgi").mock(return_value=httpx.Response(200, json={"hello": "world"}))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.test(CONFIG, fresh())
    assert caught.value.code == "not_fronius"
    respx.get(f"{FR}/solar_api/v1/GetPowerFlowRealtimeData.fcgi").mock(return_value=httpx.Response(200, json={"Head": {}, "Body": {"Data": {}}}))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.fetch("production", CONFIG, {}, fresh())
    assert caught.value.code == "not_fronius"
    respx.get(f"{FR}/solar_api/v1/GetPowerFlowRealtimeData.fcgi").mock(return_value=httpx.Response(500, text="boom"))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.fetch("production", CONFIG, {}, fresh())
    assert caught.value.code == "http_error"


@respx.mock
async def test_ignoring_tls_errors_goes_through_the_relaxed_client(ctx: Context, monkeypatch: pytest.MonkeyPatch) -> None:
    used: list[int] = []
    relaxed = httpx.AsyncClient()
    monkeypatch.setattr("app.adapters.base._relaxed_client", lambda: (used.append(1), relaxed)[1])
    serve()
    await ADAPTER.fetch("production", {**CONFIG, "insecure": True}, {}, ctx)
    assert used
    used.clear()
    await ADAPTER.fetch("production", CONFIG, {}, fresh())
    assert not used


@pytest.mark.parametrize("kind", [widget.kind for widget in ADAPTER.widgets])
def test_demo_has_every_card(kind: str) -> None:
    for tick in (0, 5, 50, 110):
        card = ADAPTER.demo(kind, {}, tick)
        assert card.primary
        assert card.secondary or kind == "flow"
        if kind == "flow":
            assert card.meta["flow"]["home"] > 0 and card.meta["flow"]["battery_soc"] is not None
