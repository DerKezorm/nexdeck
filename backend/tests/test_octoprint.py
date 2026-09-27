"""OctoPrint, against the answers of OctoPrint 1.11.8 with its virtual printer (27.09.2026)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context, Unreachable

OP = "http://octoprint.example.com"
KEY = "op-test-key-for-the-cards"
CONFIG = {"url": OP, "api_key": KEY}
ADAPTER = get_adapter("octoprint")
REFUSED = {"error": "You don't have the permission to access the requested resource. It is either read-protected or not readable by the server."}


def flags(**on: bool) -> dict[str, bool]:
    names = ("cancelling", "closedOrError", "error", "finishing", "operational", "paused", "pausing", "printing", "ready",
             "resuming", "sdReady")
    return {name: on.get(name, False) for name in names}


def heater(actual: float, target: float = 0.0) -> dict[str, Any]:
    return {"actual": actual, "offset": 0, "target": target}


#: Two nozzles, a heated bed and a heated chamber, idle with T1 and the chamber heating.
PRINTER_TWO_HEADS = {"sd": {"ready": True},
                     "state": {"error": "", "flags": flags(operational=True, ready=True, sdReady=True), "text": "Operational"},
                     "temperature": {"bed": heater(21.3), "chamber": heater(39.91, 40.0), "tool0": heater(21.3),
                                     "tool1": heater(56.32, 215.0)}}
#: The default profile, printing.
PRINTER_PRINTING = {"sd": {"ready": True},
                    "state": {"error": "", "flags": flags(operational=True, printing=True, sdReady=True), "text": "Printing"},
                    "temperature": {"bed": heater(60.0, 60.0), "tool0": heater(200.0, 200.0)}}
#: Right after the pause command: the text still says Pausing, the flags already paused.
PRINTER_PAUSING = {"sd": {"ready": True},
                   "state": {"error": "", "flags": flags(operational=True, paused=True, sdReady=True), "text": "Pausing"},
                   "temperature": {"bed": heater(60.0, 60.0), "tool0": heater(200.0, 200.0)}}
NOT_OPERATIONAL = {"error": "Printer is not operational"}


def job(state: str, *, name: str | None = "calibration_cube.gcode", completion: float | None = None, print_time: int | None = None,
        left: int | None = None, origin: str | None = None, error: str | None = None, **details: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "job": {"averagePrintTime": None, "estimatedPrintTime": 237.69664783505385 if name else None,
                "filament": {"tool0": {"length": 210.0, "volume": 0.0}} if name else None,
                "file": {"date": 1790499940 if name else None, "display": name, "name": name, "origin": "local" if name else None,
                         "path": name, "size": 5364 if name else None},
                "lastPrintTime": None, "user": "printadmin" if name else None, **details},
        "progress": {"completion": completion, "filepos": None, "printTime": print_time, "printTimeLeft": left,
                     "printTimeLeftOrigin": origin},
        "state": state,
    }
    if error is not None:
        body["error"] = error
    return body


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


def serve(*, printer: Any = PRINTER_PRINTING, printer_status: int = 200, job_answer: Any = None) -> dict[str, list[str]]:
    """A fake OctoPrint that writes down which key each request carried."""
    keys: dict[str, list[str]] = {}

    def remember(path: str, answer: httpx.Response) -> Any:
        def reply(request: httpx.Request) -> httpx.Response:
            keys.setdefault(path, []).append(request.headers.get("X-Api-Key", ""))
            return answer
        return reply

    respx.get(f"{OP}/api/version").mock(side_effect=remember("version", httpx.Response(200, json={"api": "0.1", "server": "1.11.8", "text": "OctoPrint 1.11.8"})))
    respx.get(f"{OP}/api/printer").mock(side_effect=remember("printer", httpx.Response(printer_status, json=printer)))
    respx.get(f"{OP}/api/job").mock(side_effect=remember("job", httpx.Response(200, json=job_answer or job("Printing", completion=9.1, print_time=26, left=230, origin="linear"))))
    return keys


@respx.mock
async def test_the_test_names_the_version_and_the_state(ctx: Context) -> None:
    keys = serve()
    assert await ADAPTER.test(CONFIG, ctx) == "OctoPrint 1.11.8 answers. Printer: Printing."
    assert keys["version"] == [KEY] and keys["job"] == [KEY]


@respx.mock
async def test_the_printer_while_printing(ctx: Context) -> None:
    serve()
    card = await ADAPTER.fetch("printer", CONFIG, {}, ctx)
    assert card.status == "ok" and card.primary == {"label": "State", "value": "Printing"}
    assert [(row["label"], row["value"], row["part"]) for row in card.secondary] == [
        ("Nozzle", "200.0 / 200 °C", "nozzle"),
        ("Bed", "60.0 / 60 °C", "bed"),
    ]
    assert card.metrics == {"nozzle_temp": 200.0, "bed_temp": 60.0}


@respx.mock
async def test_two_nozzles_and_a_chamber_follow_the_profile(ctx: Context) -> None:
    serve(printer=PRINTER_TWO_HEADS)
    card = await ADAPTER.fetch("printer", CONFIG, {}, ctx)
    assert card.primary == {"label": "State", "value": "Ready"}
    assert [(row["label"], row["value"]) for row in card.secondary] == [
        ("Nozzle 1", "21.3 °C"), ("Nozzle 2", "56.3 / 215 °C"), ("Bed", "21.3 °C"), ("Chamber", "39.9 / 40 °C")]
    # ⚠️ A profile without a heated bed has no bed at all.
    no_bed = {**PRINTER_TWO_HEADS, "temperature": {"tool0": heater(21.3), "tool1": heater(21.3)}}
    respx.get(f"{OP}/api/printer").mock(return_value=httpx.Response(200, json=no_bed))
    card = await ADAPTER.fetch("printer", CONFIG, {}, Context(httpx.AsyncClient(), cache={}))
    assert [row["label"] for row in card.secondary] == ["Nozzle 1", "Nozzle 2"]
    assert card.metrics == {"nozzle_temp": 21.3}


@respx.mock
async def test_pausing_is_already_paused_and_both_are_yellow(ctx: Context) -> None:
    serve(printer=PRINTER_PAUSING)
    card = await ADAPTER.fetch("printer", CONFIG, {}, ctx)
    assert card.primary["value"] == "Pausing" and card.status == "warn"
    paused = {**PRINTER_PAUSING, "state": {**PRINTER_PAUSING["state"], "text": "Paused"}}
    respx.get(f"{OP}/api/printer").mock(return_value=httpx.Response(200, json=paused))
    card = await ADAPTER.fetch("printer", CONFIG, {}, Context(httpx.AsyncClient(), cache={}))
    assert card.primary["value"] == "Paused" and card.status == "warn"


@respx.mock
async def test_a_printer_that_is_not_connected_is_a_state_not_a_failure(ctx: Context) -> None:
    # ⚠️ 409 at /api/printer; the job endpoint still answers.
    serve(printer=NOT_OPERATIONAL, printer_status=409, job_answer=job("Offline", name=None))
    card = await ADAPTER.fetch("printer", CONFIG, {}, ctx)
    assert card.status == "unknown" and card.primary == {"label": "State", "value": "Offline"}
    assert card.meta["status_reason"] == "OctoPrint is not connected to the printer."
    assert card.metrics == {}


@respx.mock
async def test_a_firmware_error_says_what_the_firmware_said(ctx: Context) -> None:
    serve(printer=NOT_OPERATIONAL, printer_status=409,
          job_answer=job("Offline after error", name=None, error="Printer halted. kill() called!"))
    card = await ADAPTER.fetch("printer", CONFIG, {}, ctx)
    assert card.status == "bad" and card.primary["value"] == "Error"
    assert card.meta["status_reason"] == "Printer halted. kill() called!"
    job_card = await ADAPTER.fetch("job", CONFIG, {}, ctx)
    assert job_card.status == "bad" and job_card.primary == {"label": "Print job", "value": "Error"}
    # An error flag on a connected printer is red too.
    respx.get(f"{OP}/api/printer").mock(return_value=httpx.Response(200, json={
        **PRINTER_PRINTING, "state": {"error": "Thermal runaway", "flags": flags(error=True, closedOrError=True), "text": "Error"}}))
    card = await ADAPTER.fetch("printer", CONFIG, {}, Context(httpx.AsyncClient(), cache={}))
    assert card.status == "bad" and card.meta["status_reason"] == "Thermal runaway"


@respx.mock
async def test_the_job_while_printing_and_paused(ctx: Context) -> None:
    serve()
    card = await ADAPTER.fetch("job", CONFIG, {}, ctx)
    assert card.status == "ok" and card.primary == {"label": "Printing", "value": 9.1, "unit": "%"}
    assert [(row["label"], row["value"]) for row in card.secondary] == [
        ("File", "calibration_cube.gcode"), ("Elapsed", "26s"), ("Time left", "3m 50s")]
    assert card.metrics == {"progress": 9.1}
    respx.get(f"{OP}/api/job").mock(return_value=httpx.Response(200, json=job(
        "Paused", completion=23.620432513049963, print_time=41, left=215, origin="analysis")))
    card = await ADAPTER.fetch("job", CONFIG, {}, Context(httpx.AsyncClient(), cache={}))
    assert card.status == "warn" and card.primary == {"label": "Paused", "value": 23.6, "unit": "%"}


@respx.mock
async def test_a_print_still_heating_has_no_time_left_yet(ctx: Context) -> None:
    serve(job_answer=job("Printing", completion=None, print_time=None, left=None))
    card = await ADAPTER.fetch("job", CONFIG, {}, ctx)
    assert card.primary == {"label": "Printing", "value": None, "unit": ""}
    assert [row["label"] for row in card.secondary] == ["File"] and card.metrics == {}


@respx.mock
async def test_a_finished_print_stays_on_the_job(ctx: Context) -> None:
    # ⚠️ Operational with 100 % and nothing left: finished.
    serve(job_answer=job("Operational", completion=100.0, print_time=117, left=0, averagePrintTime=117.1, lastPrintTime=117.1))
    card = await ADAPTER.fetch("job", CONFIG, {}, ctx)
    assert card.status == "ok" and card.primary == {"label": "Finished", "value": 100.0, "unit": "%"}
    assert [(row["label"], row["value"]) for row in card.secondary] == [("File", "calibration_cube.gcode"), ("Elapsed", "1m 57s")]


@respx.mock
async def test_a_cancelled_print_looks_like_a_file_nobody_started(ctx: Context) -> None:
    # ⚠️ After cancelling, the progress is all null again.
    serve(job_answer=job("Operational", averagePrintTime=117.1, lastPrintTime=117.1))
    card = await ADAPTER.fetch("job", CONFIG, {}, ctx)
    assert card.primary == {"label": "Print job", "value": "Ready"}
    assert [(row["label"], row["value"]) for row in card.secondary] == [("File", "calibration_cube.gcode"), ("Estimated", "3m 57s")]
    respx.get(f"{OP}/api/job").mock(return_value=httpx.Response(200, json=job("Operational", name=None)))
    card = await ADAPTER.fetch("job", CONFIG, {}, Context(httpx.AsyncClient(), cache={}))
    assert card.primary == {"label": "Print job", "value": "Nothing selected"} and card.secondary == []


@respx.mock
async def test_the_job_of_a_printer_that_is_off(ctx: Context) -> None:
    serve(job_answer=job("Offline", name=None))
    card = await ADAPTER.fetch("job", CONFIG, {}, ctx)
    assert card.status == "unknown" and card.primary == {"label": "Print job", "value": "Offline"}


@respx.mock
async def test_a_wrong_key_and_a_key_without_rights_are_told_apart(ctx: Context) -> None:
    # ⚠️ Both are the same 403; /api/currentuser answers either with 200.
    respx.get(f"{OP}/api/version").mock(return_value=httpx.Response(403, json=REFUSED))
    who = respx.get(f"{OP}/api/currentuser")
    who.mock(return_value=httpx.Response(200, json={"groups": ["guests"], "name": None, "permissions": []}))
    with pytest.raises(AuthFailed, match="does not know this API key"):
        await ADAPTER.test(CONFIG, ctx)
    who.mock(return_value=httpx.Response(200, json={"groups": [], "name": "nobody_here", "permissions": []}))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.test(CONFIG, Context(httpx.AsyncClient(), cache={}))
    assert caught.value.code == "forbidden" and "nobody_here" in caught.value.message
    assert who.calls[-1].request.headers["X-Api-Key"] == KEY


@respx.mock
async def test_a_card_refused_is_refused_the_same_way(ctx: Context) -> None:
    respx.get(f"{OP}/api/job").mock(return_value=httpx.Response(403, json=REFUSED))
    respx.get(f"{OP}/api/currentuser").mock(return_value=httpx.Response(200, json={"groups": ["guests"], "name": None, "permissions": []}))
    with pytest.raises(AuthFailed):
        await ADAPTER.fetch("job", CONFIG, {}, ctx)


@respx.mock
async def test_unreachable_and_not_octoprint(ctx: Context) -> None:
    respx.get(f"{OP}/api/printer").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(Unreachable):
        await ADAPTER.fetch("printer", CONFIG, {}, ctx)
    respx.get(f"{OP}/api/job").mock(return_value=httpx.Response(200, text="<html>a router</html>"))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.fetch("job", CONFIG, {}, ctx)
    assert caught.value.code == "not_octoprint"
    respx.get(f"{OP}/api/job").mock(return_value=httpx.Response(200, json={"something": "else"}))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.fetch("job", CONFIG, {}, Context(httpx.AsyncClient(), cache={}))
    assert caught.value.code == "not_octoprint"
    respx.get(f"{OP}/api/printer").mock(return_value=httpx.Response(500, json={}))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.fetch("printer", CONFIG, {}, Context(httpx.AsyncClient(), cache={}))
    assert caught.value.code == "http_error"


@pytest.mark.parametrize("kind", [widget.kind for widget in ADAPTER.widgets])
def test_demo_has_every_card(kind: str) -> None:
    for tick in (0, 5, 50, 110):
        card = ADAPTER.demo(kind, {}, tick)
        assert card.primary and card.secondary
