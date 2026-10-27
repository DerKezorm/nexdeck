"""Shelly, against answers written from Shelly's Gen1 and Gen2+ API documentation.

Not run against a device: nothing here is measured, and the adapter is beta for that reason.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import re
from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import CACHE_PREFIX, AdapterError, AuthFailed, Context, Unreachable

SH = "http://192.0.2.40"
CONFIG = {"url": SH}
ADAPTER = get_adapter("shelly")

GEN2_IDENTITY = {"name": None, "id": "shellyplus2pm-aabbccddeeff", "mac": "AABBCCDDEEFF", "slot": 1, "model": "SNSW-102P16EU", "gen": 2,
                 "fw_id": "20240401-123456/1.2.5-gabcdef", "ver": "1.2.5", "app": "Plus2PM", "auth_en": False, "auth_domain": None}
GEN2_STATUS: dict[str, Any] = {
    "ble": {}, "cloud": {"connected": False}, "mqtt": {"connected": False}, "ws": {"connected": False},
    "switch:0": {"id": 0, "source": "init", "output": True, "apower": 312.4, "voltage": 231.2, "current": 1.45,
                 "aenergy": {"total": 11679.5, "by_minute": [0, 0, 0], "minute_ts": 1654511972}, "temperature": {"tC": 48.3, "tF": 118.9}},
    "switch:1": {"id": 1, "source": "WS_in", "output": False, "apower": 0, "voltage": 231.0, "current": 0,
                 "aenergy": {"total": 2500.0, "by_minute": [0, 0, 0], "minute_ts": 1654511972}, "temperature": {"tC": 48.3, "tF": 118.9}},
    "sys": {"mac": "AABBCCDDEEFF", "restart_required": False, "uptime": 273_600, "available_updates": {}},
    "wifi": {"sta_ip": "192.0.2.40", "status": "got ip", "ssid": "example", "rssi": -57},
}
GEN2_CONFIG = {"switch:0": {"id": 0, "name": "Boiler"}, "switch:1": {"id": 1, "name": None}}
GEN1_IDENTITY = {"type": "SHSW-25", "mac": "AABBCCDDEEFF", "auth": False, "fw": "20230913-114150/v1.14.0-gcb84623", "discoverable": False, "longid": 1}
GEN1_STATUS: dict[str, Any] = {
    "wifi_sta": {"connected": True, "ssid": "example", "ip": "192.0.2.40", "rssi": -61},
    "update": {"status": "idle", "has_update": True, "new_version": "v1.14.1", "old_version": "v1.14.0"},
    "uptime": 5400, "temperature": 51.2,
    "relays": [{"ison": True, "has_timer": False}, {"ison": False, "has_timer": False}],
    "meters": [{"power": 120.5, "is_valid": True, "total": 360_000}, {"power": 0.0, "is_valid": True, "total": 60_000}],
}
GEN1_SETTINGS = {"relays": [{"name": "Lamp"}, {"name": ""}]}


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


def fresh() -> Context:
    return Context(httpx.AsyncClient(), cache={})


def gen2(status: Any = None) -> list[httpx.Request]:
    seen: list[httpx.Request] = []

    def reply(answer: Any) -> Any:
        def inner(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json=answer)
        return inner

    respx.get(f"{SH}/shelly").mock(side_effect=reply(GEN2_IDENTITY))
    respx.get(f"{SH}/rpc/Shelly.GetStatus").mock(side_effect=reply(status if status is not None else GEN2_STATUS))
    respx.get(f"{SH}/rpc/Shelly.GetConfig").mock(side_effect=reply(GEN2_CONFIG))
    return seen


def gen1(status: Any = None) -> list[httpx.Request]:
    seen: list[httpx.Request] = []

    def reply(answer: Any) -> Any:
        def inner(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json=answer)
        return inner

    respx.get(f"{SH}/shelly").mock(side_effect=reply(GEN1_IDENTITY))
    respx.get(f"{SH}/status").mock(side_effect=reply(status if status is not None else GEN1_STATUS))
    respx.get(f"{SH}/settings").mock(side_effect=reply(GEN1_SETTINGS))
    return seen


@respx.mock
async def test_the_test_tells_the_generation_the_firmware_and_the_relays(ctx: Context) -> None:
    gen2()
    assert await ADAPTER.test(CONFIG, ctx) == "Shelly Plus2PM answers (generation 2, firmware 1.2.5) with 2 relays."
    respx.reset()
    gen1()
    assert await ADAPTER.test(CONFIG, fresh()) == "Shelly SHSW-25 answers (generation 1, firmware 20230913) with 2 relays."


@respx.mock
async def test_a_gen2_device_draws_power_on_both_channels(ctx: Context) -> None:
    gen2()
    card = await ADAPTER.fetch("power", CONFIG, {}, ctx)
    assert card.primary == {"label": "Power", "value": 312.4, "unit": "W"}
    assert [(row["label"], row["value"]) for row in card.secondary] == [
        ("Energy", "14.18 kWh"), ("Temperature", "48.3 °C"), ("Wi-Fi signal", "-57 dBm"), ("Up for", "3d 4h")]
    assert card.metrics == {"power_w": 312.4, "temperature": 48.3}


@respx.mock
async def test_a_gen2_device_lists_its_switches_with_the_names_from_the_config(ctx: Context) -> None:
    gen2()
    card = await ADAPTER.fetch("switches", CONFIG, {}, ctx)
    assert [(row["title"], row["subtitle"], row["value"], row["status"]) for row in card.items] == [
        ("Boiler", "312 W", "On", "ok"), ("Switch 2", "", "Off", "unknown")]
    first, second = (row["actions"][0] for row in card.items)
    assert (first.id, first.confirm, first.params) == ("off", True, {"channel": "0"})
    assert (second.id, second.params) == ("on", {"channel": "1"})
    assert card.secondary == [{"label": "Switches on", "value": 1}]


@respx.mock
async def test_a_gen1_device_counts_watt_minutes_and_has_its_names_in_the_settings(ctx: Context) -> None:
    gen1()
    card = await ADAPTER.fetch("power", CONFIG, {}, ctx)
    # ⚠️ 360 000 + 60 000 watt minutes are 7 kilowatt hours.
    assert card.primary["value"] == 120.5 and ("Energy", "7.00 kWh") in [(row["label"], row["value"]) for row in card.secondary]
    assert ("Firmware", "Update available") in [(row["label"], row["value"]) for row in card.secondary]
    rows = (await ADAPTER.fetch("switches", CONFIG, {}, fresh())).items
    assert [(row["title"], row["value"]) for row in rows] == [("Lamp", "On"), ("Switch 2", "Off")]


@respx.mock
async def test_components_without_a_relay_or_without_a_meter_are_each_half_a_card(ctx: Context) -> None:
    status = copy.deepcopy(GEN2_STATUS)
    del status["switch:1"], status["switch:0"]["apower"]
    status["pm1:0"] = {"id": 0, "apower": 55.5, "aenergy": {"total": 1000.0}}
    status["em:0"] = {"id": 0, "total_act_power": 2000.0}
    gen2(status)
    power = await ADAPTER.fetch("power", CONFIG, {}, ctx)
    assert power.primary["value"] == 2055.5
    rows = (await ADAPTER.fetch("switches", CONFIG, {}, fresh())).items
    # Only the switch is a row; the meters cannot be pressed.
    assert [row["title"] for row in rows] == ["Boiler"] and rows[0]["subtitle"] == ""
    status["switch:0"]["apower"] = 10.0
    del status["pm1:0"], status["em:0"], status["switch:0"]["apower"]
    gen2(status)
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.fetch("power", CONFIG, {}, fresh())
    assert caught.value.code == "no_energy" and "switches card" in caught.value.hint


@respx.mock
async def test_the_button_uses_the_call_of_the_generation_and_forgets_what_it_knew(ctx: Context) -> None:
    seen = gen2()
    await ADAPTER.fetch("switches", CONFIG, {}, ctx)
    assert [key for key in ctx.cache if key.startswith(CACHE_PREFIX)]
    respx.get(f"{SH}/rpc/Switch.Set").mock(return_value=httpx.Response(200, json={"was_on": True}))
    assert await ADAPTER.action("switches", "off", {"channel": "0"}, CONFIG, {}, ctx) == "Switched off."
    call = respx.calls[-1].request
    assert call.url.path == "/rpc/Switch.Set" and dict(call.url.params) == {"id": "0", "on": "false"}
    assert not [key for key in ctx.cache if key.startswith(CACHE_PREFIX)] and seen
    respx.reset()
    gen1()
    relay = respx.get(f"{SH}/relay/1").mock(return_value=httpx.Response(200, json={"ison": True}))
    assert await ADAPTER.action("switches", "on", {"channel": "1"}, CONFIG, {}, fresh()) == "Switched on."
    assert dict(relay.calls[0].request.url.params) == {"turn": "on"}
    for bad in ("-1", "8", "x", "0; Reboot"):
        with pytest.raises(AdapterError) as caught:
            await ADAPTER.action("switches", "on", {"channel": bad}, CONFIG, {}, fresh())
        assert caught.value.code == "bad_param"
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.action("switches", "toggle", {"channel": "0"}, CONFIG, {}, fresh())
    assert caught.value.code == "no_such_action"


def digest_device(realm: str, password: str) -> list[dict[str, str]]:
    """A Gen2 device that wants Digest with SHA-256 and checks the answer the way RFC 7616 computes it."""
    checked: list[dict[str, str]] = []

    def reply(request: httpx.Request) -> httpx.Response:
        header = request.headers.get("Authorization", "")
        if not header.startswith("Digest "):
            challenge = f'Digest qop="auth", realm="{realm}", nonce="abc123", algorithm=SHA-256'
            return httpx.Response(401, headers={"WWW-Authenticate": challenge}, text="Unauthorized")
        fields = {key: quoted or bare for key, quoted, bare in re.findall(r'(\w+)=(?:"([^"]*)"|([^,\s]+))', header[len("Digest "):])}
        checked.append(fields)
        ha1 = hashlib.sha256(f"admin:{realm}:{password}".encode()).hexdigest()
        ha2 = hashlib.sha256(f"GET:{fields['uri']}".encode()).hexdigest()
        expected = hashlib.sha256(f"{ha1}:{fields['nonce']}:{fields['nc']}:{fields['cnonce']}:{fields['qop']}:{ha2}".encode()).hexdigest()
        if fields.get("username") != "admin" or fields.get("response") != expected:
            return httpx.Response(401, text="Unauthorized")
        return httpx.Response(200, json=GEN2_STATUS if "GetStatus" in fields["uri"] else GEN2_CONFIG)

    respx.get(f"{SH}/shelly").mock(return_value=httpx.Response(200, json={**GEN2_IDENTITY, "auth_en": True}))
    respx.get(url__regex=rf"{re.escape(SH)}/rpc/.*").mock(side_effect=reply)
    return checked


@respx.mock
async def test_a_gen2_device_with_a_password_is_answered_in_digest_sha_256(ctx: Context) -> None:
    # ⚠️ The user is always admin, the realm is the device id, the hash is SHA-256.
    checked = digest_device("shellyplus2pm-aabbccddeeff", "sh-test-password")
    card = await ADAPTER.fetch("power", {**CONFIG, "username": "ignored", "password": "sh-test-password"}, {}, ctx)
    assert card.primary["value"] == 312.4
    assert checked and all(fields["username"] == "admin" and fields["algorithm"] == "SHA-256" for fields in checked)
    with pytest.raises(AuthFailed) as caught:
        await ADAPTER.fetch("power", {**CONFIG, "password": "wrong"}, {}, fresh())
    assert caught.value.message == "The device turned the password down." and "admin" in caught.value.hint


@respx.mock
async def test_a_gen1_device_with_a_password_gets_basic_with_the_user_given(ctx: Context) -> None:
    seen = gen1()
    await ADAPTER.fetch("power", {**CONFIG, "username": "house", "password": "sh-test-password"}, {}, ctx)
    assert seen[1].headers["Authorization"] == "Basic " + base64.b64encode(b"house:sh-test-password").decode()
    assert "Authorization" not in seen[0].headers
    seen.clear()
    await ADAPTER.fetch("power", {**CONFIG, "password": "sh-test-password"}, {}, fresh())
    assert seen[1].headers["Authorization"] == "Basic " + base64.b64encode(b"admin:sh-test-password").decode()


@respx.mock
async def test_a_missing_password_and_too_many_tries_are_said(ctx: Context) -> None:
    respx.get(f"{SH}/shelly").mock(return_value=httpx.Response(200, json=GEN1_IDENTITY))
    respx.get(f"{SH}/status").mock(return_value=httpx.Response(401, text="Unauthorized"))
    with pytest.raises(AuthFailed) as caught:
        await ADAPTER.fetch("power", CONFIG, {}, ctx)
    assert caught.value.message == "The device asks for a password."
    respx.get(f"{SH}/status").mock(return_value=httpx.Response(429, text="Too Many Requests"))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.fetch("power", CONFIG, {}, fresh())
    assert caught.value.code == "rate_limited"


@respx.mock
async def test_unreachable_and_not_a_shelly(ctx: Context) -> None:
    respx.get(f"{SH}/shelly").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(Unreachable):
        await ADAPTER.test(CONFIG, ctx)
    for answer in (httpx.Response(200, text="<html>a router</html>"), httpx.Response(200, json={"hello": "world"}), httpx.Response(404, text="no")):
        respx.get(f"{SH}/shelly").mock(return_value=answer)
        with pytest.raises(AdapterError) as caught:
            await ADAPTER.test(CONFIG, fresh())
        assert caught.value.code == "not_shelly"
    respx.get(f"{SH}/shelly").mock(return_value=httpx.Response(200, json=GEN1_IDENTITY))
    respx.get(f"{SH}/status").mock(return_value=httpx.Response(500, text="boom"))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.test(CONFIG, fresh())
    assert caught.value.code == "http_error"
    respx.get(f"{SH}/settings").mock(return_value=httpx.Response(200, json=GEN1_SETTINGS))
    respx.get(f"{SH}/status").mock(return_value=httpx.Response(200, json=[1]))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.test(CONFIG, fresh())
    assert caught.value.code == "not_shelly"


@respx.mock
async def test_names_that_cannot_be_read_cost_the_names_and_nothing_else(ctx: Context) -> None:
    gen2()
    respx.get(f"{SH}/rpc/Shelly.GetConfig").mock(return_value=httpx.Response(404, text="Not Found"))
    rows = (await ADAPTER.fetch("switches", CONFIG, {}, ctx)).items
    assert [row["title"] for row in rows] == ["Switch 1", "Switch 2"]


@pytest.mark.parametrize("kind", [widget.kind for widget in ADAPTER.widgets])
def test_demo_has_every_card(kind: str) -> None:
    for tick in (0, 5, 50, 110):
        card = ADAPTER.demo(kind, {}, tick)
        assert card.primary or card.items
        assert card.secondary
