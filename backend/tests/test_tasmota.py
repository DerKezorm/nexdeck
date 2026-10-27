"""Tasmota, against answers written from the Tasmota documentation (JSON status responses and commands).

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
from app.adapters.base import CACHE_PREFIX, AdapterError, AuthFailed, Context, Unreachable

TS = "http://192.0.2.50"
CONFIG = {"url": TS}
SIGNED = {"url": TS, "username": "admin", "password": "ts-test-password"}
ADAPTER = get_adapter("tasmota")

#: A plug with an energy chip, in the shape of the documentation's Status 0.
STATUS_PLUG: dict[str, Any] = {
    "Status": {"Module": 49, "DeviceName": "Plug", "FriendlyName": ["Washing machine"], "Topic": "tasmota_plug", "Power": 1},
    "StatusFWR": {"Version": "13.4.0(tasmota)", "BuildDateTime": "2024-02-01T10:00:00"},
    "StatusNET": {"Hostname": "plug", "IPAddress": "192.0.2.50", "Mac": "AA:BB:CC:00:00:01"},
    "StatusSTS": {"Time": "2026-10-27T12:00:00", "Uptime": "9T04:30:10", "UptimeSec": 794_410, "POWER": "ON",
                  "Wifi": {"SSId": "example", "RSSI": 72, "Signal": -64}},
    "StatusSNS": {"Time": "2026-10-27T12:00:00", "ENERGY": {
        "TotalStartTime": "2025-01-01T00:00:00", "Total": 412.6, "Yesterday": 1.82, "Today": 0.4, "Period": 3, "Power": 118,
        "ApparentPower": 121, "ReactivePower": 25, "Factor": 0.97, "Voltage": 231, "Current": 0.512}},
}


def multi() -> dict[str, Any]:
    """Four relays on one board, with no energy chip."""
    status = copy.deepcopy(STATUS_PLUG)
    status["Status"]["FriendlyName"] = ["Lamp", "Fan", "", "Pump"]
    status["StatusSTS"].pop("POWER")
    status["StatusSTS"].update({"POWER1": "ON", "POWER2": "OFF", "POWER3": "OFF", "POWER4": "ON"})
    del status["StatusSNS"]["ENERGY"]
    return status


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


def fresh() -> Context:
    return Context(httpx.AsyncClient(), cache={})


def serve(status: Any = None) -> list[httpx.Request]:
    """A fake device that writes down every request."""
    seen: list[httpx.Request] = []

    def reply(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        command = httpx.QueryParams(request.url.query.decode()).get("cmnd", "")
        if command.startswith("Power"):
            number = command.split()[0][5:] or "1"
            return httpx.Response(200, json={f"POWER{number if number != '1' else ''}": command.split()[1]})
        return httpx.Response(200, json=status if status is not None else STATUS_PLUG)

    respx.get(f"{TS}/cm").mock(side_effect=reply)
    return seen


@respx.mock
async def test_the_test_names_the_firmware_and_the_relays(ctx: Context) -> None:
    serve()
    assert await ADAPTER.test(CONFIG, ctx) == "Tasmota 13.4.0 answers with 1 relays."
    serve(multi())
    assert await ADAPTER.test(CONFIG, fresh()) == "Tasmota 13.4.0 answers with 4 relays."


@respx.mock
async def test_the_command_is_encoded_in_the_address_and_no_password_travels_in_it(ctx: Context) -> None:
    seen = serve()
    await ADAPTER.fetch("relay", SIGNED, {}, ctx)
    request = seen[0]
    assert request.url.query == b"cmnd=Status%200"
    assert b"password" not in request.url.query and "ts-test-password" not in str(request.url)
    # HTTP Basic, user admin by default; no header at all where the device has no password.
    assert request.headers["Authorization"] == "Basic " + base64.b64encode(b"admin:ts-test-password").decode()
    seen.clear()
    await ADAPTER.fetch("relay", CONFIG, {}, fresh())
    assert "Authorization" not in seen[0].headers
    seen.clear()
    await ADAPTER.fetch("relay", {**SIGNED, "username": "house"}, {}, fresh())
    assert seen[0].headers["Authorization"] == "Basic " + base64.b64encode(b"house:ts-test-password").decode()


@respx.mock
async def test_the_relay_card_of_a_plug(ctx: Context) -> None:
    serve()
    card = await ADAPTER.fetch("relay", CONFIG, {}, ctx)
    assert card.status == "ok" and card.primary == {"label": "Washing machine", "value": "On"}
    assert [(row["label"], row["value"]) for row in card.secondary] == [
        ("Device", "Plug"), ("Firmware", "13.4.0"), ("Wi-Fi signal", "72 %"), ("Up for", "9d 4h")]
    assert card.metrics == {"signal": 72.0}
    assert [(a.id, a.label, a.confirm, a.params) for a in card.actions] == [("off", "Turn off", True, {"relay": "1"})]


@respx.mock
async def test_each_relay_of_a_board_is_a_card_of_its_own(ctx: Context) -> None:
    serve(multi())
    fan = await ADAPTER.fetch("relay", CONFIG, {"relay": 2}, ctx)
    assert fan.primary == {"label": "Fan", "value": "Off"} and [(a.id, a.params) for a in fan.actions] == [("on", {"relay": "2"})]
    unnamed = await ADAPTER.fetch("relay", CONFIG, {"relay": "3"}, fresh())
    assert unnamed.primary == {"label": "Relay", "value": "Off"}
    pump = await ADAPTER.fetch("relay", CONFIG, {"relay": 4}, fresh())
    assert pump.primary == {"label": "Pump", "value": "On"} and pump.actions[0].id == "off"
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.fetch("relay", CONFIG, {"relay": 7}, fresh())
    assert caught.value.code == "no_relay" and "1, 2, 3, 4" in caught.value.hint


@respx.mock
async def test_an_old_firmware_has_the_name_as_text_and_the_uptime_as_text(ctx: Context) -> None:
    status = copy.deepcopy(STATUS_PLUG)
    status["Status"]["FriendlyName"] = "Old plug"
    del status["StatusSTS"]["UptimeSec"]
    serve(status)
    card = await ADAPTER.fetch("relay", CONFIG, {}, ctx)
    assert card.primary["label"] == "Old plug"
    assert ("Up for", "9d 4h") in [(row["label"], row["value"]) for row in card.secondary]


@respx.mock
async def test_the_energy_card(ctx: Context) -> None:
    serve()
    card = await ADAPTER.fetch("energy", CONFIG, {}, ctx)
    assert card.status == "ok" and card.primary == {"label": "Power", "value": 118.0, "unit": "W"}
    assert [(row["label"], row["value"]) for row in card.secondary] == [
        ("Voltage", "231 V"), ("Current", "0.51 A"), ("Today", "0.40 kWh"), ("Yesterday", "1.82 kWh"), ("Total", "412.60 kWh")]
    assert card.metrics == {"power_w": 118.0, "voltage_v": 231.0, "today_kwh": 0.4}


@respx.mock
async def test_a_device_that_does_not_measure_says_so_instead_of_showing_zero(ctx: Context) -> None:
    serve(multi())
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.fetch("energy", CONFIG, {}, ctx)
    assert caught.value.code == "no_energy" and "relay card" in caught.value.hint


@respx.mock
async def test_the_button_sends_power_with_the_relay_number_and_forgets_what_it_knew(ctx: Context) -> None:
    seen = serve()
    await ADAPTER.fetch("relay", CONFIG, {}, ctx)
    assert [key for key in ctx.cache if key.startswith(CACHE_PREFIX)]
    assert await ADAPTER.action("relay", "off", {"relay": "1"}, CONFIG, {}, ctx) == "Switched off."
    assert seen[-1].url.query == b"cmnd=Power1%20OFF"
    assert not [key for key in ctx.cache if key.startswith(CACHE_PREFIX)]
    assert await ADAPTER.action("relay", "on", {"relay": "4"}, CONFIG, {}, ctx) == "Switched on."
    assert seen[-1].url.query == b"cmnd=Power4%20ON"
    for bad in ("0", "33", "x", "1; Restart 1"):
        with pytest.raises(AdapterError) as caught:
            await ADAPTER.action("relay", "on", {"relay": bad}, CONFIG, {}, ctx)
        assert caught.value.code == "bad_param"
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.action("relay", "toggle", {"relay": "1"}, CONFIG, {}, ctx)
    assert caught.value.code == "no_such_action"


@respx.mock
async def test_the_password_warning_and_the_refusal_codes_are_a_refusal(ctx: Context) -> None:
    # The documentation says nothing about the code; the source answers a JSON warning. All three are read.
    respx.get(f"{TS}/cm").mock(return_value=httpx.Response(403, json={"WARNING": "Need user=<username>&password=<password>"}))
    with pytest.raises(AuthFailed) as caught:
        await ADAPTER.test(CONFIG, ctx)
    assert caught.value.message == "The device asks for a web password." and "WebPassword" in caught.value.hint
    with pytest.raises(AuthFailed) as caught:
        await ADAPTER.test(SIGNED, fresh())
    assert caught.value.message == "The device turned the user or the password down."
    respx.get(f"{TS}/cm").mock(return_value=httpx.Response(401, text="Unauthorized"))
    with pytest.raises(AuthFailed):
        await ADAPTER.fetch("relay", SIGNED, {}, fresh())
    respx.get(f"{TS}/cm").mock(return_value=httpx.Response(200, json={"WARNING": "Need user=<username>&password=<password>"}))
    with pytest.raises(AuthFailed):
        await ADAPTER.fetch("relay", SIGNED, {}, fresh())


@respx.mock
async def test_unreachable_and_not_tasmota(ctx: Context) -> None:
    respx.get(f"{TS}/cm").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(Unreachable):
        await ADAPTER.fetch("relay", CONFIG, {}, ctx)
    respx.get(f"{TS}/cm").mock(return_value=httpx.Response(200, text="<html>a router</html>"))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.fetch("relay", CONFIG, {}, fresh())
    assert caught.value.code == "not_tasmota"
    respx.get(f"{TS}/cm").mock(return_value=httpx.Response(200, json={"hello": "world"}))
    for call in (ADAPTER.test(CONFIG, fresh()), ADAPTER.fetch("relay", CONFIG, {}, fresh())):
        with pytest.raises(AdapterError) as caught:
            await call
        assert caught.value.code == "not_tasmota"
    respx.get(f"{TS}/cm").mock(return_value=httpx.Response(200, json={"Command": "Unknown"}))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.fetch("relay", CONFIG, {}, fresh())
    assert caught.value.code == "unknown_command"
    respx.get(f"{TS}/cm").mock(return_value=httpx.Response(500, json={}))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.fetch("relay", CONFIG, {}, fresh())
    assert caught.value.code == "http_error"
    respx.get(f"{TS}/cm").mock(return_value=httpx.Response(200, json=[1, 2]))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.fetch("relay", CONFIG, {}, fresh())
    assert caught.value.code == "not_tasmota"


@respx.mock
async def test_ignoring_tls_errors_goes_through_the_relaxed_client(ctx: Context, monkeypatch: pytest.MonkeyPatch) -> None:
    used: list[int] = []
    relaxed = httpx.AsyncClient()
    monkeypatch.setattr("app.adapters.base._relaxed_client", lambda: (used.append(1), relaxed)[1])
    serve()
    await ADAPTER.fetch("relay", {**CONFIG, "insecure": True}, {}, ctx)
    assert used
    used.clear()
    await ADAPTER.fetch("relay", CONFIG, {}, fresh())
    assert not used


@pytest.mark.parametrize("kind", [widget.kind for widget in ADAPTER.widgets])
def test_demo_has_every_card(kind: str) -> None:
    for tick in (0, 5, 50, 110):
        card = ADAPTER.demo(kind, {}, tick)
        assert card.primary and card.secondary
