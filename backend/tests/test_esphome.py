"""ESPHome, against the answers of the ESPHome device builder 2026.10.0 (27.10.2026).

No device could be online in the container, so ``online`` and ``offline`` are built from the dashboard's own front end
and from what older dashboards say in /ping.
"""

from __future__ import annotations

import base64
import copy
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context, Unreachable

ES = "http://esphome.example.com:6052"
CONFIG = {"url": ES}
SIGNED = {"url": ES, "username": "admin", "password": "es-test-password"}
ADAPTER = get_adapter("esphome")
FIXTURES = Path(__file__).parent / "fixtures"


def recorded(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


def fresh() -> Context:
    return Context(httpx.AsyncClient(), cache={})


def devices(**states: Any) -> dict[str, Any]:
    """The recorded device list with a state, an update and an offline time set on the devices named."""
    body = copy.deepcopy(recorded("esphome_devices.json"))
    for one in body["configured"]:
        for key, value in states.get(one["name"], {}).items():
            one[key] = value
    return body


def serve(body: Any = None, ping: Any = None) -> dict[str, list[str]]:
    seen: dict[str, list[str]] = {"auth": [], "paths": []}

    def reply(answer: Any) -> Any:
        def inner(request: httpx.Request) -> httpx.Response:
            seen["auth"].append(request.headers.get("Authorization", ""))
            seen["paths"].append(request.url.path)
            return httpx.Response(200, json=answer)
        return inner

    respx.get(f"{ES}/version").mock(side_effect=reply(recorded("esphome_version.json")))
    respx.get(f"{ES}/devices").mock(side_effect=reply(body if body is not None else recorded("esphome_devices.json")))
    respx.get(f"{ES}/ping").mock(side_effect=reply(ping if ping is not None else recorded("esphome_ping.json")))
    return seen


@respx.mock
async def test_the_test_names_the_version_and_counts_the_devices(ctx: Context) -> None:
    serve()
    assert await ADAPTER.test(CONFIG, ctx) == "ESPHome 2026.10.0 answers with 2 devices."


@respx.mock
async def test_devices_the_dashboard_cannot_probe_are_unknown_not_offline(ctx: Context) -> None:
    # ⚠️ What the container really answered: "state": "unknown" for everything, and nothing in /ping.
    seen = serve()
    card = await ADAPTER.fetch("overview", CONFIG, {}, ctx)
    assert card.status == "ok" and card.primary == {"label": "Devices online", "value": 0}
    assert {row["label"]: row["value"] for row in card.secondary} == {"Offline": 0, "Updates waiting": 0, "Devices": 2, "Dashboard": "2026.10.0"}
    assert card.metrics == {"online": 0.0, "offline": 0.0, "updates": 0.0}
    # This dashboard says state itself, so /ping is not asked.
    assert "/ping" not in seen["paths"]
    rows = (await ADAPTER.fetch("devices", CONFIG, {}, fresh())).items
    assert [(row["title"], row["value"], row["status"]) for row in rows] == [
        ("garage-relay", "Unknown", "unknown"), ("Kitchen sensor", "Unknown", "unknown")]


@respx.mock
async def test_online_offline_and_waiting_devices_are_counted_and_sorted(ctx: Context) -> None:
    serve(devices(**{"garage-relay": {"state": "offline", "offline_seconds": 5400},
                     "kitchen-sensor": {"state": "online", "update_available": True, "deployed_version": "2025.9.3"}}))
    card = await ADAPTER.fetch("overview", CONFIG, {}, ctx)
    assert card.status == "warn" and card.primary["value"] == 1
    assert {row["label"]: row["value"] for row in card.secondary}["Offline"] == 1
    assert {row["label"]: row["value"] for row in card.secondary}["Updates waiting"] == 1
    assert card.metrics == {"online": 1.0, "offline": 1.0, "updates": 1.0}
    rows = (await ADAPTER.fetch("devices", CONFIG, {}, fresh())).items
    # The offline one first, with how long; then the one with an update.
    assert [(row["title"], row["value"], row["status"]) for row in rows] == [("garage-relay", "Offline", "bad"), ("Kitchen sensor", "Update", "warn")]
    assert rows[0]["subtitle"] == "1h 30m · esp8266" and rows[1]["subtitle"] == "Temperature above the stove"
    assert rows[1]["url"] == "http://192.0.2.31:80"
    assert "url" not in rows[0]


@respx.mock
async def test_a_device_that_is_online_and_current_is_green(ctx: Context) -> None:
    serve(devices(**{"garage-relay": {"state": "online"}, "kitchen-sensor": {"state": "online"}}))
    rows = (await ADAPTER.fetch("devices", CONFIG, {}, ctx)).items
    assert [(row["value"], row["status"]) for row in rows] == [("Online", "ok"), ("Online", "ok")]
    assert (await ADAPTER.fetch("overview", CONFIG, {}, fresh())).status == "ok"


@respx.mock
async def test_an_older_dashboard_says_it_in_ping_and_compares_the_versions_itself(ctx: Context) -> None:
    body = recorded("esphome_devices.json")
    for one in body["configured"]:
        del one["state"], one["update_available"]
    body["configured"][1].update({"deployed_version": "2025.1.0", "current_version": "2025.2.0"})
    third = copy.deepcopy(body["configured"][0])
    third.update({"name": "hall", "configuration": "hall.yaml", "state": "online"})
    body["configured"].append(third)
    # null in /ping is a device the dashboard could not probe, and a state a device already has is not overwritten.
    seen = serve(body, ping={"garage-relay.yaml": False, "kitchen-sensor.yaml": True, "hall.yaml": False})
    card = await ADAPTER.fetch("overview", CONFIG, {}, ctx)
    assert "/ping" in seen["paths"]
    assert card.primary["value"] == 2 and {row["label"]: row["value"] for row in card.secondary}["Offline"] == 1
    assert card.metrics["updates"] == 1.0
    serve(body, ping={"garage-relay.yaml": None, "kitchen-sensor.yaml": True, "hall.yaml": True})
    card = await ADAPTER.fetch("overview", CONFIG, {}, fresh())
    assert card.primary["value"] == 2 and card.metrics["offline"] == 0.0
    # No /ping at all (404) costs the state and nothing else.
    serve(body)
    respx.get(f"{ES}/ping").mock(return_value=httpx.Response(404, text="Not Found"))
    assert (await ADAPTER.fetch("overview", CONFIG, {}, fresh())).primary["value"] == 1
    # A dashboard that says update_available itself is believed over a comparison of versions.
    body["configured"][1]["update_available"] = False
    serve(body)
    assert (await ADAPTER.fetch("overview", CONFIG, {}, fresh())).metrics["updates"] == 0.0
    # A device never built has no deployed version and is not "behind".
    body["configured"][1].update({"deployed_version": "", "current_version": "2025.2.0"})
    serve(body, ping={})
    assert (await ADAPTER.fetch("overview", CONFIG, {}, fresh())).metrics["updates"] == 0.0


@respx.mock
async def test_the_limit_and_the_empty_dashboard(ctx: Context) -> None:
    serve()
    assert len((await ADAPTER.fetch("devices", CONFIG, {"limit": 1}, ctx)).items) == 1
    serve({"configured": [], "importable": []})
    card = await ADAPTER.fetch("devices", CONFIG, {}, fresh())
    assert card.items == [] and card.meta["empty"] == "No device in the dashboard."


@respx.mock
async def test_the_dashboards_sign_in_is_basic_and_checked_by_the_devices(ctx: Context) -> None:
    seen = serve()
    await ADAPTER.test(SIGNED, ctx)
    assert set(seen["auth"]) == {"Basic " + base64.b64encode(b"admin:es-test-password").decode()}
    # ⚠️ /version is open, /devices is not: the test must ask for the devices to learn anything.
    respx.get(f"{ES}/devices").mock(return_value=httpx.Response(401, text="Authentication required"))
    with pytest.raises(AuthFailed) as caught:
        await ADAPTER.test(CONFIG, fresh())
    assert caught.value.message == "The ESPHome dashboard asks for a user and a password." and "USERNAME" in caught.value.hint
    with pytest.raises(AuthFailed) as caught:
        await ADAPTER.test(SIGNED, fresh())
    assert caught.value.message == "The ESPHome dashboard turned the user or the password down."


@respx.mock
async def test_unreachable_and_not_esphome(ctx: Context) -> None:
    respx.get(f"{ES}/version").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(Unreachable):
        await ADAPTER.test(CONFIG, ctx)
    respx.get(f"{ES}/version").mock(return_value=httpx.Response(200, text="<html>a router</html>"))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.test(CONFIG, fresh())
    assert caught.value.code == "not_esphome"
    respx.get(f"{ES}/version").mock(return_value=httpx.Response(200, json={"hello": "world"}))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.test(CONFIG, fresh())
    assert caught.value.code == "not_esphome"
    serve({"something": "else"})
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.fetch("devices", CONFIG, {}, fresh())
    assert caught.value.code == "not_esphome"
    respx.get(f"{ES}/devices").mock(return_value=httpx.Response(500, text="boom"))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.fetch("devices", CONFIG, {}, fresh())
    assert caught.value.code == "http_error"


@respx.mock
async def test_ignoring_tls_errors_goes_through_the_relaxed_client(ctx: Context, monkeypatch: pytest.MonkeyPatch) -> None:
    used: list[int] = []
    relaxed = httpx.AsyncClient()
    monkeypatch.setattr("app.adapters.base._relaxed_client", lambda: (used.append(1), relaxed)[1])
    serve()
    await ADAPTER.fetch("devices", {**CONFIG, "insecure": True}, {}, ctx)
    assert used
    used.clear()
    await ADAPTER.fetch("devices", CONFIG, {}, fresh())
    assert not used


@pytest.mark.parametrize("kind", [widget.kind for widget in ADAPTER.widgets])
def test_demo_has_every_card(kind: str) -> None:
    for tick in (0, 5, 50, 110):
        card = ADAPTER.demo(kind, {}, tick)
        assert card.primary or card.items
        assert card.secondary
