"""OpenDTU, against answers written from OpenDTU's Web API documentation and source (live data request).

Not run against a device: nothing here is measured, and the adapter is beta for that reason.
"""

from __future__ import annotations

import base64
import copy
from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context, Unreachable

DTU = "http://192.0.2.70"
CONFIG = {"url": DTU}
SIGNED = {"url": DTU, "password": "dtu-test-password"}
ADAPTER = get_adapter("opendtu")


def value(number: float, unit: str, decimals: int = 1) -> dict[str, Any]:
    return {"v": number, "u": unit, "d": decimals}


#: Two inverters at noon, one asleep, and a third that is limited to 60 per cent.
LIVE: dict[str, Any] = {
    "inverters": [
        {"serial": "114100000001", "name": "Roof south", "order": 0, "data_age": 2, "poll_enabled": True, "reachable": True, "producing": True,
         "limit_relative": 100, "limit_absolute": 800, "events": 0,
         "AC": {"0": {"Power": value(412.3, "W"), "Voltage": value(231.5, "V"), "YieldDay": value(2310, "Wh", 0)}},
         "DC": {"0": {"name": {"u": "Panel 1"}, "Power": value(214.0, "W")}},
         "INV": {"0": {"Temperature": value(41.25, "°C"), "Efficiency": value(96.4, "%")}}},
        {"serial": "114100000002", "name": "Roof east", "order": 1, "data_age": 1, "reachable": True, "producing": True,
         "limit_relative": 60, "limit_absolute": 480, "AC": {"0": {"Power": value(188.0, "W")}}, "INV": {"0": {}}},
        {"serial": "114100000003", "name": "Garage", "order": 2, "data_age": 8000, "reachable": False, "producing": False,
         "limit_relative": 100, "limit_absolute": 800, "AC": {}, "INV": {}},
    ],
    "total": {"Power": value(600.3, "W"), "YieldDay": value(4180, "Wh", 0), "YieldTotal": value(1423.456, "kWh", 3)},
    "hints": {"time_sync": False, "radio_problem": False, "default_password": False},
}


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


def fresh() -> Context:
    return Context(httpx.AsyncClient(), cache={})


def serve(live: Any = None) -> list[httpx.Request]:
    seen: list[httpx.Request] = []

    def reply(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=live if live is not None else LIVE)

    respx.get(f"{DTU}/api/livedata/status").mock(side_effect=reply)
    return seen


@respx.mock
async def test_the_test_counts_the_inverters(ctx: Context) -> None:
    serve()
    assert await ADAPTER.test(CONFIG, ctx) == "OpenDTU answers with 3 inverters."


@respx.mock
async def test_the_power_card_reads_each_value_in_its_own_unit(ctx: Context) -> None:
    serve()
    card = await ADAPTER.fetch("power", CONFIG, {}, ctx)
    # ⚠️ The day is in Wh, the total in kWh, in the same answer.
    assert card.status == "ok" and card.primary == {"label": "Solar power", "value": 600.3, "unit": "W"}
    assert [(row["label"], row["value"]) for row in card.secondary] == [("Today", "4.18 kWh"), ("Total", "1423 kWh"), ("Producing", 2)]
    assert card.metrics == {"power_w": 600.3, "yield_day_kwh": 4.18}
    live = copy.deepcopy(LIVE)
    live["total"]["YieldDay"] = value(4.18, "kWh", 3)
    serve(live)
    assert (await ADAPTER.fetch("power", CONFIG, {}, fresh())).metrics["yield_day_kwh"] == 4.18


@respx.mock
async def test_at_night_everything_sleeps_and_that_is_zero_not_an_error(ctx: Context) -> None:
    live = copy.deepcopy(LIVE)
    live["total"] = {}
    for one in live["inverters"]:
        one.update({"reachable": False, "producing": False, "AC": {}, "INV": {}})
    serve(live)
    card = await ADAPTER.fetch("power", CONFIG, {}, ctx)
    assert card.status == "ok" and card.primary["value"] == 0 and card.metrics == {"power_w": 0.0}
    assert card.secondary == [{"label": "Producing", "value": 0, "part": "producing"}]
    rows = (await ADAPTER.fetch("inverters", CONFIG, {}, fresh())).items
    assert [(row["value"], row["status"]) for row in rows] == [("Asleep", "unknown")] * 3


@respx.mock
async def test_the_inverters_card(ctx: Context) -> None:
    serve()
    card = await ADAPTER.fetch("inverters", CONFIG, {}, ctx)
    assert [(row["title"], row["value"], row["subtitle"], row["status"]) for row in card.items] == [
        ("Roof south", "412 W", "41 °C", "ok"), ("Roof east", "188 W", "60 %", "ok"), ("Garage", "Asleep", "", "unknown")]
    assert card.secondary == [{"label": "Inverters", "value": 3}] and card.status == "ok"


@respx.mock
async def test_an_inverter_that_answers_but_makes_nothing_is_idle_and_one_without_blocks_still_shows(ctx: Context) -> None:
    live = copy.deepcopy(LIVE)
    live["inverters"][1].update({"producing": False, "AC": {}})
    del live["inverters"][0]["AC"]
    live["inverters"][0]["producing"] = True
    serve(live)
    values = [(row["title"], row["value"]) for row in (await ADAPTER.fetch("inverters", CONFIG, {}, ctx)).items]
    # Newer OpenDTU sends the blocks only when one inverter is asked for.
    assert values == [("Roof south", "Producing"), ("Roof east", "Idle"), ("Garage", "Asleep")]


@respx.mock
async def test_a_radio_that_does_not_work_and_the_default_password_are_yellow(ctx: Context) -> None:
    live = copy.deepcopy(LIVE)
    live["hints"]["radio_problem"] = True
    serve(live)
    card = await ADAPTER.fetch("power", CONFIG, {}, ctx)
    assert card.status == "warn" and card.meta["status_reason"] == "The radio does not work."
    live["hints"] = {"default_password": True}
    serve(live)
    card = await ADAPTER.fetch("inverters", CONFIG, {}, fresh())
    assert card.status == "warn" and card.meta["status_reason"] == "OpenDTU still has its default password."


@respx.mock
async def test_the_password_goes_as_basic_for_the_user_admin_and_only_when_there_is_one(ctx: Context) -> None:
    seen = serve()
    await ADAPTER.fetch("power", SIGNED, {}, ctx)
    assert seen[0].headers["Authorization"] == "Basic " + base64.b64encode(b"admin:dtu-test-password").decode()
    seen.clear()
    await ADAPTER.fetch("power", CONFIG, {}, fresh())
    assert "Authorization" not in seen[0].headers


@respx.mock
async def test_a_missing_and_a_wrong_password_are_told_apart(ctx: Context) -> None:
    respx.get(f"{DTU}/api/livedata/status").mock(return_value=httpx.Response(401, text="Unauthorized"))
    with pytest.raises(AuthFailed) as caught:
        await ADAPTER.test(CONFIG, ctx)
    assert caught.value.message == "OpenDTU asks for a password." and "read-only access" in caught.value.hint
    with pytest.raises(AuthFailed) as caught:
        await ADAPTER.test(SIGNED, fresh())
    assert caught.value.message == "OpenDTU turned the password down."


@respx.mock
async def test_unreachable_and_not_opendtu(ctx: Context) -> None:
    respx.get(f"{DTU}/api/livedata/status").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(Unreachable):
        await ADAPTER.test(CONFIG, ctx)
    for answer in (httpx.Response(200, text="<html>a router</html>"), httpx.Response(200, json={"something": "else"}),
                   httpx.Response(200, json={"inverters": {}, "total": {}})):
        respx.get(f"{DTU}/api/livedata/status").mock(return_value=answer)
        with pytest.raises(AdapterError) as caught:
            await ADAPTER.test(CONFIG, fresh())
        assert caught.value.code == "not_opendtu"
    respx.get(f"{DTU}/api/livedata/status").mock(return_value=httpx.Response(500, text="boom"))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.test(CONFIG, fresh())
    assert caught.value.code == "http_error"


@respx.mock
async def test_ignoring_tls_errors_goes_through_the_relaxed_client(ctx: Context, monkeypatch: pytest.MonkeyPatch) -> None:
    used: list[int] = []
    relaxed = httpx.AsyncClient()
    monkeypatch.setattr("app.adapters.base._relaxed_client", lambda: (used.append(1), relaxed)[1])
    serve()
    await ADAPTER.fetch("power", {**CONFIG, "insecure": True}, {}, ctx)
    assert used
    used.clear()
    await ADAPTER.fetch("power", CONFIG, {}, fresh())
    assert not used


@pytest.mark.parametrize("kind", [widget.kind for widget in ADAPTER.widgets])
def test_demo_has_every_card(kind: str) -> None:
    for tick in (0, 5, 50, 110):
        card = ADAPTER.demo(kind, {}, tick)
        assert card.primary or card.items
        assert card.secondary
