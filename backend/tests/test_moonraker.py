"""Moonraker, against the answers of Moonraker (API 1.5.0) with Klipper ee2c6fb on a simulated microcontroller (27.10.2026).

A print that is running, paused or finished could not be recorded: the simulated printer cannot home, and a heater with
a target shuts it down. Those states are built from the documentation.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import CACHE_PREFIX, AdapterError, AuthFailed, Context, Unreachable

MR = "http://printer.example.com:7125"
KEY = "mr-test-key-for-the-cards"
CONFIG = {"url": MR, "api_key": KEY}
ADAPTER = get_adapter("moonraker")
FIXTURES = Path(__file__).parent / "fixtures"


def recorded(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


def fresh() -> Context:
    return Context(httpx.AsyncClient(), cache={})


def serve(*, server: Any = None, objects: Any = None, query: Any = None, printer_info: Any = None,
          printer_info_status: int = 200) -> dict[str, list[str]]:
    """A fake Moonraker that writes down which key each request carried and what was asked of /printer/objects/query."""
    seen: dict[str, list[str]] = {"keys": [], "query": []}

    def key_of(request: httpx.Request) -> None:
        seen["keys"].append(request.headers.get("X-Api-Key", ""))

    def reply(answer: httpx.Response, remember: bool = False) -> Any:
        def inner(request: httpx.Request) -> httpx.Response:
            key_of(request)
            if remember:
                seen["query"].append(request.url.query.decode())
            return answer
        return inner

    respx.get(f"{MR}/server/info").mock(side_effect=reply(httpx.Response(200, json=server or recorded("moonraker_server_info.json"))))
    respx.get(f"{MR}/printer/info").mock(side_effect=reply(httpx.Response(printer_info_status, json=printer_info or recorded("moonraker_printer_info.json"))))
    respx.get(f"{MR}/printer/objects/list").mock(side_effect=reply(httpx.Response(200, json=objects or recorded("moonraker_objects.json"))))
    respx.get(f"{MR}/printer/objects/query").mock(side_effect=reply(httpx.Response(200, json=query or recorded("moonraker_query_standby.json")), True))
    respx.get(f"{MR}/server/history/totals").mock(side_effect=reply(httpx.Response(200, json=recorded("moonraker_totals.json"))))
    return seen


def printing(**stats: Any) -> dict[str, Any]:
    """The idle answer with a print under way, as the documentation describes it."""
    body = copy.deepcopy(recorded("moonraker_query_standby.json"))
    status = body["result"]["status"]
    status["print_stats"].update({"filename": "parts/benchy.gcode", "state": "printing", "print_duration": 600.0,
                                  "total_duration": 660.0, "info": {"current_layer": 12, "total_layer": 200}, **stats})
    status["virtual_sdcard"].update({"progress": 0.25, "is_active": True})
    status["extruder"].update({"temperature": 209.8, "target": 210.0})
    status["heater_bed"].update({"temperature": 60.0, "target": 60.0})
    return body


@respx.mock
async def test_the_test_names_the_version_and_klipper(ctx: Context) -> None:
    serve()
    # ⚠️ A build without a git checkout calls itself "?".
    assert await ADAPTER.test(CONFIG, ctx) == "Moonraker answers. Klipper: Ready."
    server = recorded("moonraker_server_info.json")
    server["result"]["moonraker_version"] = "v0.9.3-77-g6bc6c6b"
    serve(server=server)
    assert await ADAPTER.test(CONFIG, fresh()) == "Moonraker v0.9.3-77-g6bc6c6b answers. Klipper: Ready."


@respx.mock
async def test_the_printer_idle(ctx: Context) -> None:
    seen = serve()
    card = await ADAPTER.fetch("printer", CONFIG, {}, ctx)
    assert card.status == "ok" and card.primary == {"label": "State", "value": "Ready"}
    assert [(row["label"], row["value"], row["part"]) for row in card.secondary] == [
        ("Nozzle", "103.3 °C", "nozzle"), ("Bed", "103.3 °C", "bed")]
    assert card.metrics == {"nozzle_temp": 103.26, "bed_temp": 103.26}
    # The key travels as a header on every request, and only what this printer has is asked for.
    assert set(seen["keys"]) == {KEY}
    assert seen["query"] == ["print_stats&display_status&virtual_sdcard&pause_resume&extruder&heater_bed"]


@respx.mock
async def test_two_nozzles_a_chamber_and_other_heaters_follow_the_printer(ctx: Context) -> None:
    objects = recorded("moonraker_objects.json")
    objects["result"]["objects"] += ["extruder1", "heater_generic dryer box", "temperature_sensor Chamber", "temperature_sensor raspberry_pi"]
    query = copy.deepcopy(recorded("moonraker_query_standby.json"))
    status = query["result"]["status"]
    status["extruder1"] = {"temperature": 56.3, "target": 215.0, "power": 0.4}
    status["heater_generic dryer box"] = {"temperature": 41.0, "target": 45.0, "power": 0.2}
    status["temperature_sensor Chamber"] = {"temperature": 38.5, "measured_min_temp": 20.1, "measured_max_temp": 38.6}
    seen = serve(objects=objects, query=query)
    card = await ADAPTER.fetch("printer", CONFIG, {}, ctx)
    assert [(row["label"], row["value"]) for row in card.secondary] == [
        ("Nozzle 1", "103.3 °C"), ("Nozzle 2", "56.3 / 215 °C"), ("Bed", "103.3 °C"),
        ("dryer box", "41.0 / 45 °C"), ("Chamber", "38.5 °C")]
    assert [row.get("part") for row in card.secondary] == ["nozzle", "nozzle", "bed", None, "chamber"]
    # ⚠️ Names with a space are asked for with %20; the Raspberry Pi's own sensor is not a chamber.
    assert "heater_generic%20dryer%20box" in seen["query"][0] and "temperature_sensor%20Chamber" in seen["query"][0]
    assert "raspberry_pi" not in seen["query"][0]


@respx.mock
async def test_a_print_that_stopped_with_an_error_says_why(ctx: Context) -> None:
    serve(query=recorded("moonraker_query_error.json"))
    card = await ADAPTER.fetch("printer", CONFIG, {}, ctx)
    assert card.status == "bad" and card.primary["value"] == "Error"
    assert card.meta["status_reason"] == "Must home axis first: 10.000 10.000 0.000 [0.000]"
    job = await ADAPTER.fetch("job", CONFIG, {}, Context(httpx.AsyncClient(), cache={}))
    assert job.status == "bad" and job.primary == {"label": "Print job", "value": "Error"}
    assert job.meta["status_reason"] == "Must home axis first: 10.000 10.000 0.000 [0.000]"
    assert [row["label"] for row in job.secondary] == ["File"] and job.actions == []


@respx.mock
async def test_the_job_while_printing(ctx: Context) -> None:
    serve(query=printing())
    card = await ADAPTER.fetch("job", CONFIG, {}, ctx)
    assert card.status == "ok" and card.primary == {"label": "Printing", "value": 25.0, "unit": "%"}
    # The folder is left off the file; the time left is the pace so far: 600 s took a quarter.
    assert [(row["label"], row["value"]) for row in card.secondary] == [
        ("File", "benchy.gcode"), ("Elapsed", "10m"), ("Time left", "30m"), ("Layer", "12 / 200")]
    assert card.metrics == {"progress": 25.0}
    assert [(a.id, a.confirm, a.danger) for a in card.actions] == [("pause", False, False), ("cancel", True, True)]
    hot = await ADAPTER.fetch("printer", CONFIG, {}, fresh())
    assert hot.primary["value"] == "Printing" and hot.secondary[0]["value"] == "209.8 / 210 °C"


@respx.mock
async def test_a_print_barely_started_has_no_time_left_yet(ctx: Context) -> None:
    body = printing(print_duration=3.0, info={"current_layer": None, "total_layer": None})
    body["result"]["status"]["virtual_sdcard"]["progress"] = 0.001
    serve(query=body)
    card = await ADAPTER.fetch("job", CONFIG, {}, ctx)
    assert [row["label"] for row in card.secondary] == ["File", "Elapsed"]


@respx.mock
async def test_paused_offers_resume_and_is_yellow(ctx: Context) -> None:
    serve(query=printing(state="paused"))
    card = await ADAPTER.fetch("job", CONFIG, {}, ctx)
    assert card.status == "warn" and card.primary["label"] == "Paused"
    assert [a.id for a in card.actions] == ["resume", "cancel"]


@respx.mock
async def test_finished_and_ready_and_cancelled(ctx: Context) -> None:
    serve(query=printing(state="complete", total_duration=3725.0))
    card = await ADAPTER.fetch("job", CONFIG, {}, ctx)
    assert card.primary == {"label": "Finished", "value": 100.0, "unit": "%"} and card.actions == []
    assert ("Elapsed", "1h 2m") in [(row["label"], row["value"]) for row in card.secondary]
    serve(query=printing(state="standby", filename=""))
    card = await ADAPTER.fetch("job", CONFIG, {}, fresh())
    assert card.primary == {"label": "Print job", "value": "Nothing selected"}
    serve(query=printing(state="standby"))
    assert (await ADAPTER.fetch("job", CONFIG, {}, fresh())).primary["value"] == "Ready"
    serve(query=printing(state="cancelled"))
    card = await ADAPTER.fetch("job", CONFIG, {}, fresh())
    assert card.status == "unknown" and card.primary["value"] == "Cancelled"


@respx.mock
async def test_klipper_not_ready_is_a_state_and_the_printer_is_not_asked(ctx: Context) -> None:
    # ⚠️ Klipper down: /server/info answers, every /printer address answers 503.
    server = recorded("moonraker_server_info_disconnected.json")
    seen = serve(server=server)
    card = await ADAPTER.fetch("printer", CONFIG, {}, ctx)
    assert card.status == "unknown" and card.primary == {"label": "State", "value": "Offline"}
    assert card.meta["status_reason"] == "Klipper is not running." and card.metrics == {}
    assert seen["query"] == []
    job = await ADAPTER.fetch("job", CONFIG, {}, fresh())
    assert job.primary["value"] == "Offline"


@respx.mock
async def test_a_printer_in_shutdown_says_what_klipper_said(ctx: Context) -> None:
    server = recorded("moonraker_server_info.json")
    server["result"]["klippy_state"] = "shutdown"
    message = "MCU 'mcu' shutdown: Timer too close\nThis often indicates the host computer is overloaded."
    seen = serve(server=server, printer_info={"result": {"state": "shutdown", "state_message": message}})
    card = await ADAPTER.fetch("printer", CONFIG, {}, ctx)
    assert card.status == "bad" and card.primary["value"] == "Shutdown" and card.meta["status_reason"] == message
    assert seen["query"] == []
    # Starting up is yellow, and Klipper answers 400 on /printer/info meanwhile.
    server["result"]["klippy_state"] = "startup"
    serve(server=server, printer_info={"error": {"code": 400, "message": "Printer is not ready"}}, printer_info_status=400)
    card = await ADAPTER.fetch("printer", CONFIG, {}, fresh())
    assert card.status == "warn" and card.primary["value"] == "Starting" and card.meta["status_reason"] == ""
    # A /printer/info that fails altogether costs the reason and nothing else.
    server["result"]["klippy_state"] = "shutdown"
    serve(server=server, printer_info={"error": {"code": 500, "message": "boom"}}, printer_info_status=500)
    card = await ADAPTER.fetch("printer", CONFIG, {}, fresh())
    assert card.status == "bad" and card.primary["value"] == "Shutdown" and card.meta["status_reason"] == ""


@respx.mock
async def test_the_print_history(ctx: Context) -> None:
    serve()
    card = await ADAPTER.fetch("history", CONFIG, {}, ctx)
    assert card.primary == {"label": "Prints", "value": 4} and card.metrics == {"jobs": 4.0}
    totals = recorded("moonraker_totals.json")
    totals["result"]["job_totals"].update({"total_jobs": 128.0, "total_print_time": 367200.0, "total_filament_used": 412_500_000.0, "longest_print": 61200.0})
    respx.get(f"{MR}/server/history/totals").mock(return_value=httpx.Response(200, json=totals))
    card = await ADAPTER.fetch("history", CONFIG, {}, fresh())
    # ⚠️ Filament is counted in millimetres.
    assert [(row["label"], row["value"]) for row in card.secondary] == [
        ("Print time", "4d 6h"), ("Filament", "412500.0 m"), ("Longest print", "17h")]
    respx.get(f"{MR}/server/history/totals").mock(return_value=httpx.Response(404, json={"error": {"code": 404, "message": "Not Found"}}))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.fetch("history", CONFIG, {}, fresh())
    assert caught.value.code == "no_history"


@respx.mock
async def test_the_buttons_post_to_the_print_and_carry_the_key(ctx: Context) -> None:
    routes = {name: respx.post(f"{MR}/printer/print/{name}").mock(return_value=httpx.Response(200, json={"result": "ok"}))
              for name in ("pause", "resume", "cancel")}
    assert await ADAPTER.action("job", "pause", {}, CONFIG, {}, ctx) == "Print paused."
    assert await ADAPTER.action("job", "resume", {}, CONFIG, {}, ctx) == "Print resumed."
    assert await ADAPTER.action("job", "cancel", {}, CONFIG, {}, ctx) == "Print cancelled."
    assert all(route.call_count == 1 and route.calls[0].request.headers["X-Api-Key"] == KEY for route in routes.values())
    # ⚠️ The card must not keep showing "Printing" for the seconds a remembered answer lasts.
    serve(query=printing())
    await ADAPTER.fetch("job", CONFIG, {}, ctx)
    assert [key for key in ctx.cache if key.startswith(CACHE_PREFIX)]
    await ADAPTER.action("job", "pause", {}, CONFIG, {}, ctx)
    assert not [key for key in ctx.cache if key.startswith(CACHE_PREFIX)]
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.action("job", "emergency_stop", {}, CONFIG, {}, ctx)
    assert caught.value.code == "no_such_action"
    # Klipper refusing is said in Klipper's words, without the traceback that comes with it.
    respx.post(f"{MR}/printer/print/pause").mock(return_value=httpx.Response(400, json={"error": {
        "code": 400, "message": "Printer is not ready", "traceback": "Traceback (most recent call last): secret path"}}))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.action("job", "pause", {}, CONFIG, {}, fresh())
    assert "Printer is not ready" in caught.value.message and "Traceback" not in caught.value.message


@respx.mock
async def test_a_missing_key_and_a_wrong_key_are_told_apart(ctx: Context) -> None:
    # ⚠️ Both are 401 "Unauthorized"; whether a key was sent is the only difference.
    respx.get(f"{MR}/server/info").mock(return_value=httpx.Response(401, json={"error": {"code": 401, "message": "Unauthorized"}}))
    with pytest.raises(AuthFailed) as caught:
        await ADAPTER.test({"url": MR}, ctx)
    assert "does not trust this client" in caught.value.message and "trusted_clients" in caught.value.hint
    with pytest.raises(AuthFailed) as caught:
        await ADAPTER.test(CONFIG, fresh())
    assert "does not know this API key" in caught.value.message


@respx.mock
async def test_ignoring_tls_errors_goes_through_the_relaxed_client(ctx: Context, monkeypatch: pytest.MonkeyPatch) -> None:
    used: list[int] = []
    relaxed = httpx.AsyncClient()
    monkeypatch.setattr("app.adapters.base._relaxed_client", lambda: (used.append(1), relaxed)[1])
    serve()
    await ADAPTER.fetch("printer", {**CONFIG, "insecure": True}, {}, ctx)
    assert used
    used.clear()
    await ADAPTER.fetch("printer", CONFIG, {}, fresh())
    assert not used


@respx.mock
async def test_unreachable_and_not_moonraker(ctx: Context) -> None:
    respx.get(f"{MR}/server/info").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(Unreachable):
        await ADAPTER.fetch("printer", CONFIG, {}, ctx)
    respx.get(f"{MR}/server/info").mock(return_value=httpx.Response(200, text="<html>a router</html>"))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.fetch("job", CONFIG, {}, fresh())
    assert caught.value.code == "not_moonraker"
    respx.get(f"{MR}/server/info").mock(return_value=httpx.Response(200, json={"result": {"hello": "world"}}))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.fetch("job", CONFIG, {}, fresh())
    assert caught.value.code == "not_moonraker"
    respx.get(f"{MR}/server/info").mock(return_value=httpx.Response(500, json={"error": {"code": 500, "message": "boom"}}))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.fetch("job", CONFIG, {}, fresh())
    assert caught.value.code == "http_error" and "boom" in caught.value.message


def test_the_link_goes_to_the_web_interface_when_there_is_one() -> None:
    assert ADAPTER.default_link({"url": MR}) == MR
    assert ADAPTER.default_link({"url": MR, "web_url": "http://printer.example.com/"}) == "http://printer.example.com"


@pytest.mark.parametrize("kind", [widget.kind for widget in ADAPTER.widgets])
def test_demo_has_every_card(kind: str) -> None:
    for tick in (0, 5, 50, 110):
        card = ADAPTER.demo(kind, {}, tick)
        assert card.primary and card.secondary
