"""Homebridge, against the answers of Homebridge 2.4.0 with Homebridge UI 5.29.0 and homebridge-dummy (27.10.2026)."""

from __future__ import annotations

import copy
import json
import time
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import CACHE_PREFIX, AdapterError, AuthFailed, Context, Unreachable

HB = "http://homebridge.example.com:8581"
CONFIG = {"url": HB, "username": "nexdeck", "password": "hb-test-password"}
TOKEN = "hb-test-token"
ADAPTER = get_adapter("homebridge")
FIXTURES = Path(__file__).parent / "fixtures"
LOGIN = {"access_token": TOKEN, "token_type": "Bearer", "expires_in": 28800}
LAMP = "uniq-lamp"
SWITCH = "uniq-switch"
TEMPERATURE = "uniq-temp"
DOOR = "uniq-door"


def recorded(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


def fresh() -> Context:
    return Context(httpx.AsyncClient(), cache={})


def serve(*, accessories: Any = None, plugins: Any = None, version: Any = None, status: Any = None) -> dict[str, list[Any]]:
    """A fake Homebridge that writes down who signed in and which token each request carried."""
    seen: dict[str, list[Any]] = {"logins": [], "tokens": []}

    def login(request: httpx.Request) -> httpx.Response:
        seen["logins"].append(json.loads(request.content))
        return httpx.Response(201, json=LOGIN)

    def reply(answer: Any) -> Any:
        def inner(request: httpx.Request) -> httpx.Response:
            seen["tokens"].append(request.headers.get("Authorization", ""))
            return httpx.Response(200, json=answer)
        return inner

    respx.post(f"{HB}/api/auth/login").mock(side_effect=login)
    respx.get(f"{HB}/api/auth/settings").mock(return_value=httpx.Response(200, json=recorded("homebridge_settings.json")))
    respx.get(f"{HB}/api/status/homebridge").mock(side_effect=reply(status or recorded("homebridge_status_homebridge.json")))
    respx.get(f"{HB}/api/status/homebridge-version").mock(side_effect=reply(version or recorded("homebridge_status_homebridge-version.json")))
    respx.get(f"{HB}/api/status/cpu").mock(side_effect=reply(recorded("homebridge_status_cpu.json")))
    respx.get(f"{HB}/api/status/ram").mock(side_effect=reply(recorded("homebridge_status_ram.json")))
    respx.get(f"{HB}/api/status/uptime").mock(side_effect=reply(recorded("homebridge_status_uptime.json")))
    respx.get(f"{HB}/api/plugins").mock(side_effect=reply(plugins or recorded("homebridge_plugins.json")))
    respx.get(f"{HB}/api/accessories").mock(side_effect=reply(accessories or recorded("homebridge_accessories.json")))
    return seen


def accessory(kind: str, name: str, values: dict[str, Any], *, writable: bool = False, unique: str = "u1") -> dict[str, Any]:
    return {"type": kind, "humanType": kind, "serviceName": name, "uniqueId": unique, "values": values,
            "serviceCharacteristics": [{"type": "On", "canWrite": True}] if writable else []}


@respx.mock
async def test_the_test_names_both_versions_and_the_state(ctx: Context) -> None:
    serve()
    assert await ADAPTER.test(CONFIG, ctx) == "Homebridge 2.4.0 answers, web interface 5.29.0. Status: ok."
    assert await ADAPTER.running_version(CONFIG, fresh()) == "2.4.0"


@respx.mock
async def test_one_sign_in_serves_every_card_and_the_token_is_a_bearer(ctx: Context) -> None:
    seen = serve()
    await ADAPTER.fetch("status", CONFIG, {}, ctx)
    await ADAPTER.fetch("plugins", CONFIG, {}, ctx)
    await ADAPTER.fetch("accessories", CONFIG, {}, ctx)
    assert seen["logins"] == [{"username": "nexdeck", "password": "hb-test-password"}]
    assert set(seen["tokens"]) == {f"Bearer {TOKEN}"}


@respx.mock
async def test_the_status_card(ctx: Context) -> None:
    serve()
    card = await ADAPTER.fetch("status", CONFIG, {}, ctx)
    assert card.status == "ok" and card.primary == {"label": "Homebridge", "value": "Running"}
    rows = {row["label"]: row["value"] for row in card.secondary}
    # Memory counts what is not available, not what is not free: the cache is not a use.
    assert rows["Version"] == "2.4.0" and rows["Load"] == "3 %" and rows["Memory"] == "63 %" and rows["Up for"] == "46h 14m"
    assert card.metrics == {"cpu": 3.0, "memory": 63.1}


@respx.mock
async def test_a_homebridge_that_is_starting_or_down_is_yellow_or_red(ctx: Context) -> None:
    serve(status={"status": "pending"})
    card = await ADAPTER.fetch("status", CONFIG, {}, ctx)
    assert card.status == "warn" and card.primary["value"] == "Starting"
    serve(status={"status": "down"})
    card = await ADAPTER.fetch("status", CONFIG, {}, fresh())
    assert card.status == "bad" and card.primary["value"] == "Stopped"
    serve(status={"status": "up"})
    assert (await ADAPTER.fetch("status", CONFIG, {}, fresh())).status == "ok"


@respx.mock
async def test_a_newer_homebridge_shows_where_it_is_going(ctx: Context) -> None:
    version = recorded("homebridge_status_homebridge-version.json")
    version.update({"latestVersion": "2.5.0", "updateAvailable": True})
    serve(version=version)
    card = await ADAPTER.fetch("status", CONFIG, {}, ctx)
    assert {row["label"]: row["value"] for row in card.secondary}["Version"] == "2.4.0 → 2.5.0"


@respx.mock
async def test_plugins_with_an_update_come_first(ctx: Context) -> None:
    plugins = recorded("homebridge_plugins.json")
    # The one with the update is not first in Homebridge's own order.
    plugins[1].update({"latestVersion": "9.9.9", "updateAvailable": True})
    plugins[0]["disabled"] = True
    serve(plugins=plugins)
    card = await ADAPTER.fetch("plugins", CONFIG, {}, ctx)
    assert card.status == "warn"
    assert [(row["title"], row["value"], row["status"]) for row in card.items] == [
        (plugins[1]["displayName"], "Update", "warn"), (plugins[0]["displayName"], "Disabled", "unknown")]
    assert card.items[0]["subtitle"] == f"{plugins[1]['installedVersion']} → 9.9.9"
    assert card.secondary == [{"label": "Plugins", "value": 2}, {"label": "Updates", "value": 1}]
    card = await ADAPTER.fetch("plugins", CONFIG, {"limit": 1}, fresh())
    assert len(card.items) == 1


@respx.mock
async def test_the_accessories_leave_the_bridge_out_and_read_in_words(ctx: Context) -> None:
    serve()
    card = await ADAPTER.fetch("accessories", CONFIG, {}, ctx)
    rows = {row["title"]: row for row in card.items}
    assert set(rows) == {"Front Door", "Lamp", "Living Temp", "Test Switch", "Wall Outlet"}
    assert (rows["Front Door"]["value"], rows["Front Door"]["subtitle"]) == ("Closed", "Contact Sensor")
    assert rows["Lamp"]["value"] == "Off" and rows["Living Temp"]["value"] == "0.0 °C"
    on = rows["Lamp"]["actions"][0]
    assert (on.id, on.label, on.confirm, on.params) == ("on", "Turn on", True, {"accessory": LAMP})
    assert rows["Front Door"]["actions"] == [] and rows["Living Temp"]["actions"] == []
    assert card.secondary == [{"label": "Accessories", "value": 5}]


@respx.mock
async def test_what_the_sensors_say(ctx: Context) -> None:
    items = [
        accessory("TemperatureSensor", "T", {"CurrentTemperature": 21.46}),
        accessory("HumiditySensor", "H", {"CurrentRelativeHumidity": 48}),
        # ⚠️ 0 is a closed contact, 1 an open one.
        accessory("ContactSensor", "C open", {"ContactSensorState": 1}),
        accessory("MotionSensor", "M", {"MotionDetected": 1}),
        accessory("MotionSensor", "M quiet", {"MotionDetected": 0}),
        accessory("LeakSensor", "L", {"LeakDetected": 1}),
        accessory("LockMechanism", "Lock jam", {"LockCurrentState": 2}),
        accessory("LockMechanism", "Lock", {"LockCurrentState": 1}),
        accessory("WindowCovering", "Blind", {"CurrentPosition": 40}),
        accessory("Lightbulb", "Dimmed", {"On": 1, "Brightness": 35}, writable=True),
        accessory("Lightbulb", "Dimmed off", {"On": 0, "Brightness": 35}, writable=True),
        accessory("Valve", "Odd", {}),
    ]
    serve(accessories=items)
    rows = {row["title"]: (row["value"], row["status"]) for row in (await ADAPTER.fetch("accessories", CONFIG, {"limit": 50}, ctx)).items}
    assert rows == {
        "T": ("21.5 °C", "ok"), "H": ("48 %", "ok"), "C open": ("Open", "ok"), "M": ("Motion", "warn"), "M quiet": ("Clear", "ok"),
        "L": ("Leak", "bad"), "Lock jam": ("Jammed", "bad"), "Lock": ("Locked", "ok"), "Blind": ("40%", "ok"),
        "Dimmed": ("35%", "ok"), "Dimmed off": ("Off", "ok"), "Odd": ("?", "unknown")}


@respx.mock
async def test_only_a_switch_with_an_On_that_can_be_written_gets_a_button(ctx: Context) -> None:
    items = recorded("homebridge_accessories.json")
    for one in items:
        if one["uniqueId"] == SWITCH:
            one["serviceCharacteristics"][0]["canWrite"] = False
        if one["uniqueId"] == LAMP:
            one["values"]["On"] = 1
    serve(accessories=items)
    rows = {row["id"]: row for row in (await ADAPTER.fetch("accessories", CONFIG, {}, ctx)).items}
    assert rows[SWITCH]["actions"] == []
    assert [(a.id, a.label) for a in rows[LAMP]["actions"]] == [("off", "Turn off")]


@respx.mock
async def test_a_service_that_is_not_a_switch_gets_no_button_even_with_a_writable_On(ctx: Context) -> None:
    serve(accessories=[accessory("Speaker", "Speaker", {"On": 1}, writable=True), accessory("Fan", "Fan", {"On": 0}, writable=True, unique="u2")])
    rows = {row["title"]: row for row in (await ADAPTER.fetch("accessories", CONFIG, {}, ctx)).items}
    assert rows["Speaker"]["actions"] == [] and [a.id for a in rows["Fan"]["actions"]] == ["on"]


@respx.mock
async def test_one_accessory_as_a_number_with_its_history(ctx: Context) -> None:
    items = recorded("homebridge_accessories.json")
    for one in items:
        if one["uniqueId"] == TEMPERATURE:
            one["values"]["CurrentTemperature"] = 21.5
    serve(accessories=items)
    card = await ADAPTER.fetch("accessory", CONFIG, {"accessory": TEMPERATURE}, ctx)
    assert card.primary == {"label": "Living Temp", "value": 21.5, "unit": "°C"} and card.metrics == {"value": 21.5}
    card = await ADAPTER.fetch("accessory", CONFIG, {"accessory": SWITCH}, fresh())
    assert card.primary == {"label": "Test Switch", "value": "Off"} and card.metrics == {} and [a.id for a in card.actions] == ["on"]
    card = await ADAPTER.fetch("accessory", CONFIG, {"accessory": DOOR}, fresh())
    assert card.primary["value"] == "Closed"


@respx.mock
async def test_an_accessory_that_is_gone_and_a_bad_number_are_said(ctx: Context) -> None:
    serve()
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.fetch("accessory", CONFIG, {"accessory": "gone-id"}, ctx)
    assert caught.value.code == "no_accessory"
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.fetch("accessory", CONFIG, {"accessory": "../x"}, fresh())
    assert caught.value.code == "bad_param"


@respx.mock
async def test_the_choices_are_the_accessories_by_name(ctx: Context) -> None:
    serve()
    choices = await ADAPTER.choices("accessory", CONFIG, ctx)
    assert (SWITCH, "Test Switch (Switch)") in choices and len(choices) == 5
    assert choices == sorted(choices, key=lambda pair: pair[1].lower())


@respx.mock
async def test_the_button_puts_the_On_characteristic_and_forgets_what_it_knew(ctx: Context) -> None:
    serve()
    route = respx.put(f"{HB}/api/accessories/{SWITCH}").mock(return_value=httpx.Response(200, json={}))
    await ADAPTER.fetch("accessories", CONFIG, {}, ctx)
    assert [key for key in ctx.cache if key.startswith(CACHE_PREFIX)]
    assert await ADAPTER.action("accessories", "on", {"accessory": SWITCH}, CONFIG, {}, ctx) == "Switched on."
    request = route.calls[0].request
    assert json.loads(request.content) == {"characteristicType": "On", "value": True}
    assert request.headers["Authorization"] == f"Bearer {TOKEN}"
    assert not [key for key in ctx.cache if key.startswith(CACHE_PREFIX)]
    assert await ADAPTER.action("accessory", "off", {"accessory": SWITCH}, CONFIG, {}, ctx) == "Switched off."
    assert json.loads(route.calls[1].request.content)["value"] is False
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.action("accessories", "toggle", {"accessory": SWITCH}, CONFIG, {}, ctx)
    assert caught.value.code == "no_such_action"
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.action("accessories", "on", {"accessory": "a/../b"}, CONFIG, {}, ctx)
    assert caught.value.code == "bad_param"
    # ⚠️ A made-up number is 400 with Homebridge's own words.
    respx.put(f"{HB}/api/accessories/gone").mock(return_value=httpx.Response(
        400, json={"message": "Service with uniqueId of 'gone' not found.", "error": "Bad Request", "statusCode": 400}))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.action("accessories", "on", {"accessory": "gone"}, CONFIG, {}, fresh())
    assert "not found" in caught.value.message


@respx.mock
async def test_a_wrong_password_is_refused_and_not_tried_again_at_once(ctx: Context) -> None:
    # ⚠️ 403, not 401, for a wrong password and for a user that does not exist.
    login = respx.post(f"{HB}/api/auth/login").mock(return_value=httpx.Response(403, json={"message": "Forbidden", "statusCode": 403}))
    with pytest.raises(AuthFailed) as caught:
        await ADAPTER.fetch("status", CONFIG, {}, ctx)
    assert "turned the user or the password down" in caught.value.message and "setup wizard" in caught.value.hint
    with pytest.raises(AuthFailed):
        await ADAPTER.fetch("plugins", CONFIG, {}, ctx)
    assert login.call_count == 1
    # The memory runs out, and a corrected password is tried.
    ctx.cache["homebridge_refused"] = (time.monotonic() - 1, "old")
    serve()
    assert (await ADAPTER.fetch("status", CONFIG, {}, ctx)).status == "ok"


@respx.mock
async def test_a_token_that_runs_out_or_is_turned_down_is_replaced_once(ctx: Context) -> None:
    seen = serve()
    await ADAPTER.fetch("plugins", CONFIG, {}, ctx)
    ctx.cache["homebridge_token"] = (time.monotonic() - 1, TOKEN)
    ctx.forget_answers()
    await ADAPTER.fetch("plugins", CONFIG, {}, ctx)
    assert len(seen["logins"]) == 2
    # Homebridge restarted with a new secret: 401 once, then fine.
    answers = iter([httpx.Response(401, json={"message": "Unauthorized", "statusCode": 401}), httpx.Response(200, json=recorded("homebridge_plugins.json"))])
    respx.get(f"{HB}/api/plugins").mock(side_effect=lambda request: next(answers))
    ctx.forget_answers()
    assert (await ADAPTER.fetch("plugins", CONFIG, {}, ctx)).items
    assert len(seen["logins"]) == 3
    # Turned down again right after signing in: that is a refusal, not a loop.
    respx.get(f"{HB}/api/plugins").mock(return_value=httpx.Response(401, json={"message": "Unauthorized", "statusCode": 401}))
    ctx.forget_answers()
    with pytest.raises(AuthFailed):
        await ADAPTER.fetch("plugins", CONFIG, {}, ctx)
    assert len(seen["logins"]) == 4


@respx.mock
async def test_without_a_user_it_asks_for_one_unless_homebridge_has_no_sign_in(ctx: Context) -> None:
    serve()
    with pytest.raises(AuthFailed) as caught:
        await ADAPTER.fetch("status", {"url": HB}, {}, ctx)
    assert "asks for a sign-in" in caught.value.message
    settings = recorded("homebridge_settings.json")
    settings["formAuth"] = False
    respx.get(f"{HB}/api/auth/settings").mock(return_value=httpx.Response(200, json=settings))
    noauth = respx.post(f"{HB}/api/auth/noauth").mock(return_value=httpx.Response(201, json=LOGIN))
    card = await ADAPTER.fetch("status", {"url": HB}, {}, fresh())
    assert card.status == "ok" and noauth.call_count == 1 and not noauth.calls[0].request.content


@respx.mock
async def test_two_factor_and_a_login_without_a_token_are_said(ctx: Context) -> None:
    respx.post(f"{HB}/api/auth/login").mock(return_value=httpx.Response(412, json={"message": "2FA Code Required", "statusCode": 412}))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.fetch("status", CONFIG, {}, ctx)
    assert caught.value.code == "two_factor"
    respx.post(f"{HB}/api/auth/login").mock(return_value=httpx.Response(201, json={"hello": "world"}))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.fetch("status", CONFIG, {}, fresh())
    assert caught.value.code == "not_homebridge"
    respx.post(f"{HB}/api/auth/login").mock(return_value=httpx.Response(500, json={}))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.fetch("status", CONFIG, {}, fresh())
    assert caught.value.code == "http_error"


@respx.mock
async def test_unreachable_and_not_homebridge(ctx: Context) -> None:
    respx.get(f"{HB}/api/auth/settings").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(Unreachable):
        await ADAPTER.test(CONFIG, ctx)
    respx.get(f"{HB}/api/auth/settings").mock(return_value=httpx.Response(200, text="<html>a router</html>"))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.test(CONFIG, fresh())
    assert caught.value.code == "not_homebridge"
    respx.get(f"{HB}/api/auth/settings").mock(return_value=httpx.Response(200, json={"env": {}}))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.test(CONFIG, fresh())
    assert caught.value.code == "not_homebridge"
    serve()
    respx.get(f"{HB}/api/accessories").mock(return_value=httpx.Response(200, text="<html></html>"))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.fetch("accessories", CONFIG, {}, fresh())
    assert caught.value.code == "not_homebridge"
    respx.get(f"{HB}/api/accessories").mock(return_value=httpx.Response(200, json={"something": "else"}))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.fetch("accessories", CONFIG, {}, fresh())
    assert caught.value.code == "not_homebridge"
    respx.get(f"{HB}/api/accessories").mock(return_value=httpx.Response(500, json={"message": "boom"}))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.fetch("accessories", CONFIG, {}, fresh())
    assert caught.value.code == "http_error" and "boom" in caught.value.message


@respx.mock
async def test_ignoring_tls_errors_goes_through_the_relaxed_client(ctx: Context, monkeypatch: pytest.MonkeyPatch) -> None:
    used: list[int] = []
    relaxed = httpx.AsyncClient()
    monkeypatch.setattr("app.adapters.base._relaxed_client", lambda: (used.append(1), relaxed)[1])
    serve()
    await ADAPTER.fetch("plugins", {**CONFIG, "insecure": True}, {}, ctx)
    assert used
    used.clear()
    await ADAPTER.fetch("plugins", CONFIG, {}, fresh())
    assert not used


def test_the_demo_accessories_have_a_button_only_where_one_can_be_pressed() -> None:
    card = ADAPTER.demo("accessories", {}, 0)
    assert {row["title"]: bool(row["actions"]) for row in card.items}["Lamp"] is True
    assert {row["title"]: bool(row["actions"]) for row in card.items}["Front door"] is False
    assert copy.deepcopy(ADAPTER.demo_choices("accessory"))


@pytest.mark.parametrize("kind", [widget.kind for widget in ADAPTER.widgets])
def test_demo_has_every_card(kind: str) -> None:
    for tick in (0, 5, 50, 110):
        card = ADAPTER.demo(kind, {"accessory": "demo-temp"}, tick)
        assert card.primary or card.items
        assert card.secondary or kind == "accessory"
