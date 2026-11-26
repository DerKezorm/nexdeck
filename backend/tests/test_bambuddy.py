"""Bambuddy, against answers in the form of Bambuddy 1.3.2's code (tag v1.3.2, commit b7d894b).

The shapes come from ``PrinterResponse``, ``PrinterStatus``, ``AMSUnit`` and ``AMSTray`` in ``backend/app/schemas/printer.py``,
``ams_units_to_dicts`` and ``vt_trays_to_dicts`` in ``services/printer_manager.py``, ``ArchiveResponse`` in
``schemas/archive.py`` and ``PrintQueueItemResponse`` in ``schemas/print_queue.py``; the refusals from ``core/auth.py``.
"""

from __future__ import annotations

import copy
from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter, rawread
from app.adapters.base import AdapterError, AuthFailed, Context
from app.services import versions

BB = "http://bambuddy.example.com:8000"
API = f"{BB}/api/v1"
CONFIG = {"url": BB, "api_key": "bb_madeUpKeyForTests0123456789"}

PRINTERS = [
    {"id": 3, "name": "Garage P1S", "serial_number": "01P00A000000001", "ip_address": "192.0.2.10", "model": "P1S", "location": None,
     "auto_archive": True, "is_active": True, "nozzle_count": 1, "created_at": "2026-10-01T10:00:00", "updated_at": "2026-11-20T10:00:00"},
    {"id": 1, "name": "Workshop H2D", "serial_number": "09400A000000002", "ip_address": "192.0.2.11", "model": "H2D", "location": None,
     "auto_archive": True, "is_active": True, "nozzle_count": 2, "created_at": "2026-10-01T10:00:00", "updated_at": "2026-11-20T10:00:00"},
]


def tray(slot: int, kind: str, brand: str, colour: str, remain: int, **more: Any) -> dict[str, Any]:
    return {"id": slot, "tray_color": colour, "tray_type": kind, "tray_sub_brands": brand, "tray_id_name": None, "tray_info_idx": "GFA00",
            "remain": remain, "k": 0.02, "cali_idx": -1, "tag_uid": None, "tray_uuid": None, "nozzle_temp_min": 190, "nozzle_temp_max": 230,
            "drying_temp": None, "drying_time": None, "state": 11, "exists": True, **more}


STATUS: dict[str, Any] = {
    "id": 3, "name": "Garage P1S", "connected": True, "state": "RUNNING", "current_print": "Planter_v3", "subtask_name": "Planter_v3",
    "gcode_file": "/data/Metadata/plate_1.gcode", "progress": 42.0, "remaining_time": 95, "layer_num": 88, "total_layers": 210,
    "temperatures": {"bed": 64.8, "bed_target": 65.0, "nozzle": 219.6, "nozzle_target": 220.0, "nozzle_heating": False},
    "cover_url": "/api/v1/printers/3/cover", "hms_errors": [],
    "ams": [
        {"id": 0, "humidity": 21, "temp": 26.5, "is_ams_ht": False, "serial_number": "", "sw_ver": "", "dry_time": 0, "module_type": "ams",
         "ams_type": 1, "tray": [
             tray(0, "PLA", "PLA Basic", "F4EE2AFF", 72),
             tray(1, "PETG", "PETG HF", "0A2989FF", 9),
             {"id": 2, "tray_color": None, "tray_type": None, "remain": 0, "state": 9, "exists": False},
             tray(3, "PLA", "", "FFFFFFFF", -1, tag_uid=None, exists=True),
         ]},
        {"id": 128, "humidity": 18, "temp": 30.0, "is_ams_ht": True, "module_type": "n3s", "tray": [tray(0, "PA-CF", "PAHT-CF", "333333FF", 55)]},
    ],
    "ams_exists": True,
    "vt_tray": [{"id": 254, "tray_color": "000000FF", "tray_type": "TPU", "tray_sub_brands": "TPU 95A HF", "remain": 30, "k": None}],
    "sdcard": True, "wifi_signal": -51, "nozzles": [{"nozzle_type": "hardened_steel", "nozzle_diameter": "0.4"}],
    "stg_cur": -1, "stg_cur_name": None, "tray_now": 0, "firmware_version": "01.08.00.00",
}

LAST = [
    {"id": 40, "printer_id": 1, "print_name": "Keychain", "status": "failed", "completed_at": "2026-11-25T18:00:00", "filename": "keychain.3mf"},
    {"id": 41, "printer_id": 3, "print_name": "Phone stand", "status": "completed", "completed_at": "2026-11-26T09:12:00", "filename": "stand.3mf"},
]


def status(**changes: Any) -> dict[str, Any]:
    made = copy.deepcopy(STATUS)
    made.update(changes)
    return made


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


def bambuddy(answers: dict[str, httpx.Response]) -> respx.Route:
    """One stand-in for Bambuddy that answers by path; anything it does not know gets its web page, as Bambuddy does."""
    page = httpx.Response(200, text="<!doctype html><html><body><div id=root></div></body></html>", headers={"content-type": "text/html"})
    return respx.route(host="bambuddy.example.com").mock(side_effect=lambda request: answers.get(request.url.path, page))


def answers(printer_status: dict[str, Any] | None = None, last: Any = None) -> dict[str, httpx.Response]:
    return {
        "/api/v1/printers/": httpx.Response(200, json=PRINTERS),
        "/api/v1/printers/3/status": httpx.Response(200, json=printer_status or STATUS),
        "/api/v1/archives/last-per-printer": last if isinstance(last, httpx.Response) else httpx.Response(200, json=LAST if last is None else last),
    }


# -- the connection ---------------------------------------------------------------


@respx.mock
async def test_the_connection_names_the_version_and_counts_the_printers_with_the_key(ctx: Context) -> None:
    route = bambuddy({"/api/v1/updates/version": httpx.Response(200, json={"version": "1.3.2", "repo": "maziggy/bambuddy"}),
                      "/api/v1/printers/": httpx.Response(200, json=PRINTERS)})
    said = await get_adapter("bambuddy").test(CONFIG, ctx)
    assert said == "Bambuddy 1.3.2 answers with 2 printers."
    assert [call.request.url.path for call in route.calls] == ["/api/v1/updates/version", "/api/v1/printers/"]
    assert all(call.request.headers["X-API-Key"] == CONFIG["api_key"] for call in route.calls)
    assert versions.version_in(said) == "1.3.2"
    assert versions.UPSTREAM["bambuddy"] == "maziggy/bambuddy"
    assert versions.compare(versions.version_in(said), versions.version_in("v1.3.2")) == "current"


@respx.mock
async def test_without_a_key_nothing_signs_the_request(ctx: Context) -> None:
    route = bambuddy(answers())
    await get_adapter("bambuddy").fetch("printer", {"url": BB}, {}, ctx)
    assert route.calls and all("X-API-Key" not in call.request.headers for call in route.calls)


@respx.mock
async def test_a_refused_key_is_said_as_such(ctx: Context) -> None:
    bambuddy({"/api/v1/printers/": httpx.Response(401, json={"detail": "Invalid API key"})})
    with pytest.raises(AuthFailed) as refused:
        await get_adapter("bambuddy").fetch("printer", CONFIG, {}, ctx)
    assert refused.value.code == "auth_failed"
    assert refused.value.message == "Bambuddy refused the API key."
    assert "Settings > API Keys" in refused.value.hint


@respx.mock
async def test_without_a_key_a_bambuddy_with_sign_in_asks_for_one(ctx: Context) -> None:
    bambuddy({"/api/v1/printers/": httpx.Response(401, json={"detail": "Authentication required"})})
    with pytest.raises(AuthFailed, match="asks for an API key"):
        await get_adapter("bambuddy").fetch("printers", {"url": BB}, {}, ctx)


@respx.mock
async def test_a_key_without_the_right_says_what_it_lacks(ctx: Context) -> None:
    bambuddy({"/api/v1/printers/": httpx.Response(403, json={"detail": "API key does not have 'can_read_status' permission"})})
    with pytest.raises(AuthFailed) as refused:
        await get_adapter("bambuddy").fetch("printer", CONFIG, {}, ctx)
    assert "can_read_status" in refused.value.message


@respx.mock
async def test_an_address_that_answers_with_a_web_page_is_not_taken_for_bambuddy(ctx: Context) -> None:
    bambuddy({})
    with pytest.raises(AdapterError) as wrong:
        await get_adapter("bambuddy").fetch("printer", CONFIG, {}, ctx)
    assert wrong.value.code == "not_bambuddy"
    assert wrong.value.message == "This address answers with something other than Bambuddy."


@respx.mock
async def test_the_printers_to_pick_from_are_bambuddy_s(ctx: Context) -> None:
    bambuddy(answers())
    adapter = get_adapter("bambuddy")
    assert await adapter.choices("printer", CONFIG, ctx) == [("3", "Garage P1S (P1S)"), ("1", "Workshop H2D (H2D)")]
    assert adapter.demo_choices("printer") and adapter.demo_choices("other") == []


# -- the printer card --------------------------------------------------------------


@respx.mock
async def test_a_printing_printer_shows_its_job_progress_time_left_and_temperatures(ctx: Context) -> None:
    route = bambuddy(answers())
    data = await get_adapter("bambuddy").fetch("printer", CONFIG, {}, ctx)
    asked = [call.request.url.path for call in route.calls]
    assert "/api/v1/printers/3/status" in asked, "without a pick the first printer Bambuddy lists"
    assert all(call.request.headers["X-API-Key"] == CONFIG["api_key"] for call in route.calls)
    assert data.status == "ok"
    assert data.primary == {"label": "Printing", "value": 42.0, "unit": "%"}
    assert data.secondary == [
        {"label": "Job", "value": "Planter_v3", "part": "job"},
        {"label": "Time left", "value": "1h 35m", "part": "left"},
        {"label": "Layer", "value": "88 / 210", "part": "layer"},
        {"label": "Nozzle", "value": "220 / 220 °C", "part": "nozzle"},
        {"label": "Bed", "value": "65 / 65 °C", "part": "bed"},
    ]
    assert data.metrics == {"progress": 42.0, "nozzle_temp": 219.6, "bed_temp": 64.8}


@pytest.mark.parametrize(("state", "word", "colour"), [
    ("IDLE", "Idle", "ok"), ("PREPARE", "Preparing", "ok"), ("SLICING", "Slicing", "ok"), ("FINISH", "Finished", "ok"),
    ("FAILED", "Failed", "bad"), ("unknown", "Unknown", "unknown"),
])
@respx.mock
async def test_the_printer_s_state_is_said_in_words(ctx: Context, state: str, word: str, colour: str) -> None:
    bambuddy(answers(status(state=state, progress=0.0, remaining_time=0)))
    data = await get_adapter("bambuddy").fetch("printer", CONFIG, {}, ctx)
    assert data.primary == {"label": "State", "value": word}
    assert data.status == colour
    assert "progress" not in data.metrics
    if word == "Failed":
        assert data.meta["status_reason"] == "The last print failed."


@respx.mock
async def test_a_paused_print_is_yellow_and_keeps_its_progress(ctx: Context) -> None:
    bambuddy(answers(status(state="PAUSE")))
    data = await get_adapter("bambuddy").fetch("printer", CONFIG, {}, ctx)
    assert data.status == "warn"
    assert data.primary == {"label": "Paused", "value": 42.0, "unit": "%"}


@respx.mock
async def test_a_printer_bambuddy_is_not_connected_to_is_offline(ctx: Context) -> None:
    # What _printer_status answers when there is no MQTT state: id, name, connected and the defaults.
    bambuddy(answers({"id": 3, "name": "Garage P1S", "connected": False, "state": None, "temperatures": None, "hms_errors": [],
                      "ams": [], "vt_tray": [], "awaiting_plate_clear": False}))
    data = await get_adapter("bambuddy").fetch("printer", CONFIG, {}, ctx)
    assert data.status == "unknown"
    assert data.primary == {"label": "State", "value": "Offline"}
    assert data.meta["status_reason"] == "Bambuddy is not connected to this printer."
    assert data.metrics == {}


@respx.mock
async def test_an_hms_error_turns_the_card_red_and_says_why(ctx: Context) -> None:
    errors = [{"code": "0x0C00", "attr": 1, "module": 12, "severity": 3, "description": "Just so you know."},
              {"code": "0x0300", "attr": 2, "module": 3, "severity": 2, "description": "The filament ran out."},
              {"code": "0x0500", "attr": 3, "module": 5, "severity": 1, "full_code": "0500-0100-0002-0001", "description": "Nozzle clog."}]
    bambuddy(answers(status(hms_errors=errors)))
    data = await get_adapter("bambuddy").fetch("printer", CONFIG, {}, ctx)
    assert (data.status, data.meta["status_reason"]) == ("bad", "Nozzle clog.")


@respx.mock
async def test_an_hms_warning_turns_the_card_yellow_and_a_notice_leaves_it(ctx: Context) -> None:
    bambuddy(answers(status(hms_errors=[{"code": "0x0300", "module": 3, "severity": 2, "full_code": "0300-1000-0002-0002", "description": None}])))
    data = await get_adapter("bambuddy").fetch("printer", CONFIG, {}, ctx)
    assert (data.status, data.meta["status_reason"]) == ("warn", "HMS 0300-1000-0002-0002")
    ctx.cache.clear()
    respx.clear()
    bambuddy(answers(status(hms_errors=[{"code": "0x0C00", "module": 12, "severity": 3, "description": "Just so you know."}])))
    data = await get_adapter("bambuddy").fetch("printer", CONFIG, {}, ctx)
    assert (data.status, data.meta["status_reason"]) == ("ok", "")


@respx.mock
async def test_two_nozzles_and_a_chamber_are_each_shown(ctx: Context) -> None:
    temps = {"nozzle": 250.0, "nozzle_target": 250.0, "nozzle_2": 31.0, "nozzle_2_target": 0.0, "bed": 90.0, "bed_target": 90.0,
             "chamber": 44.0}
    bambuddy(answers(status(temperatures=temps)))
    data = await get_adapter("bambuddy").fetch("printer", CONFIG, {}, ctx)
    shown = {row["label"]: row["value"] for row in data.secondary}
    assert (shown["Nozzle 1"], shown["Nozzle 2"], shown["Bed"], shown["Chamber"]) == ("250 / 250 °C", "31 °C", "90 / 90 °C", "44 °C")


@respx.mock
async def test_a_picked_printer_is_the_one_asked(ctx: Context) -> None:
    replies = answers()
    replies["/api/v1/printers/1/status"] = httpx.Response(200, json=status(id=1, name="Workshop H2D", state="IDLE"))
    route = bambuddy(replies)
    data = await get_adapter("bambuddy").fetch("printer", CONFIG, {"printer": "1"}, ctx)
    assert "/api/v1/printers/1/status" in [call.request.url.path for call in route.calls]
    assert "/api/v1/printers/3/status" not in [call.request.url.path for call in route.calls]
    assert {"label": "Last print failed", "value": "Keychain", "part": "last"} in data.secondary


@respx.mock
async def test_a_printer_that_is_gone_or_hidden_from_the_key_is_said(ctx: Context) -> None:
    bambuddy(answers())
    with pytest.raises(AdapterError) as gone:
        await get_adapter("bambuddy").fetch("printer", CONFIG, {"printer": "7"}, ctx)
    assert gone.value.code == "no_printer"


@respx.mock
async def test_a_bambuddy_without_printers_says_so(ctx: Context) -> None:
    bambuddy({"/api/v1/printers/": httpx.Response(200, json=[])})
    with pytest.raises(AdapterError) as none:
        await get_adapter("bambuddy").fetch("ams", CONFIG, {}, ctx)
    assert none.value.code == "no_printer"


@respx.mock
async def test_an_idle_printer_names_its_last_print_and_not_the_old_job(ctx: Context) -> None:
    bambuddy(answers(status(state="FINISH", progress=100.0)))
    data = await get_adapter("bambuddy").fetch("printer", CONFIG, {}, ctx)
    labels = [row["label"] for row in data.secondary]
    assert {"label": "Last print", "value": "Phone stand", "part": "last"} in data.secondary
    assert "Job" not in labels, "the line of the last print says it"


@respx.mock
async def test_a_running_print_shows_no_last_print(ctx: Context) -> None:
    bambuddy(answers(last=[{**LAST[1], "status": "printing", "print_name": "Planter_v3"}]))
    data = await get_adapter("bambuddy").fetch("printer", CONFIG, {}, ctx)
    assert all(row["part"] != "last" for row in data.secondary)


@pytest.mark.parametrize("outcome", [("stopped", "Last print stopped"), ("cancelled", "Last print cancelled")])
@respx.mock
async def test_how_the_last_print_ended_is_in_its_label(ctx: Context, outcome: tuple[str, str]) -> None:
    bambuddy(answers(status(state="IDLE"), last=[{**LAST[1], "status": outcome[0]}]))
    data = await get_adapter("bambuddy").fetch("printer", CONFIG, {}, ctx)
    assert {"label": outcome[1], "value": "Phone stand", "part": "last"} in data.secondary


@respx.mock
async def test_an_older_bambuddy_without_the_last_prints_still_shows_the_printer(ctx: Context) -> None:
    # Before the route, /archives/last-per-printer is /archives/{archive_id} with a word for a number: 422.
    bambuddy(answers(status(state="IDLE"), last=httpx.Response(422, json={"detail": [{"type": "int_parsing"}]})))
    data = await get_adapter("bambuddy").fetch("printer", CONFIG, {}, ctx)
    assert data.primary == {"label": "State", "value": "Idle"}
    assert all(row["part"] != "last" for row in data.secondary)


@respx.mock
async def test_a_refusal_of_the_last_prints_is_not_swallowed(ctx: Context) -> None:
    bambuddy(answers(last=httpx.Response(403, json={"detail": "API key does not have 'can_read_status' permission"})))
    with pytest.raises(AuthFailed):
        await get_adapter("bambuddy").fetch("printer", CONFIG, {}, ctx)


# -- the AMS card ------------------------------------------------------------------


@respx.mock
async def test_the_ams_shows_each_slot_with_its_filament_colour_and_what_is_left(ctx: Context) -> None:
    bambuddy(answers())
    data = await get_adapter("bambuddy").fetch("ams", CONFIG, {}, ctx)
    rows = {item["title"]: item for item in data.items}
    assert list(rows) == ["A1 · PLA Basic", "A2 · PETG HF", "A3", "A4 · PLA", "HT-A · PAHT-CF", "Ext · TPU 95A HF"]
    assert rows["A1 · PLA Basic"] == {"id": "0-0", "title": "A1 · PLA Basic", "subtitle": "PLA", "value": 72, "unit": "%", "progress": 72.0,
                                      "status": "ok", "swatch": "#f4ee2a"}
    assert (rows["A2 · PETG HF"]["status"], rows["A2 · PETG HF"]["swatch"]) == ("warn", "#0a2989")
    assert (rows["A3"]["subtitle"], rows["A3"]["status"], rows["A3"]["value"]) == ("Empty", "unknown", "")
    assert "swatch" not in rows["A3"]
    # A spool without a tag reports -1: no level, and not "running low".
    assert (rows["A4 · PLA"]["value"], rows["A4 · PLA"]["status"], rows["A4 · PLA"]["subtitle"]) == ("?", "unknown", "")
    assert "progress" not in rows["A4 · PLA"]
    assert rows["HT-A · PAHT-CF"]["subtitle"] == "PA-CF"
    assert data.status == "warn"
    assert data.secondary == [{"label": "Spools", "value": 5}, {"label": "Running low", "value": 1}]


@respx.mock
async def test_the_line_for_running_low_and_the_external_spool_are_the_card_s_to_set(ctx: Context) -> None:
    bambuddy(answers())
    data = await get_adapter("bambuddy").fetch("ams", CONFIG, {"low_percent": 60, "external": False}, ctx)
    assert [item["title"] for item in data.items if item["status"] == "warn"] == ["A2 · PETG HF", "HT-A · PAHT-CF"]
    assert all(not item["title"].startswith("Ext") for item in data.items)


@respx.mock
async def test_a_slot_with_a_spool_that_names_no_filament_is_not_empty(ctx: Context) -> None:
    unit = {"id": 1, "is_ams_ht": False, "module_type": "ams", "tray": [{"id": 0, "tray_type": "", "tray_color": "00000000", "remain": 0, "exists": True}]}
    bambuddy(answers(status(ams=[unit], vt_tray=[])))
    data = await get_adapter("bambuddy").fetch("ams", CONFIG, {}, ctx)
    assert [(item["title"], item["subtitle"]) for item in data.items] == [("B1", "Unknown filament")]


@respx.mock
async def test_an_ams_3h_names_its_slots_as_bambuddy_does(ctx: Context) -> None:
    unit = {"id": 0, "is_ams_ht": False, "module_type": "n10a", "tray": [tray(6, "PLA", "PLA Silk", "C0C0C0FF", 80)]}
    bambuddy(answers(status(ams=[unit], vt_tray=[])))
    data = await get_adapter("bambuddy").fetch("ams", CONFIG, {}, ctx)
    assert data.items[0]["title"] == "3H-7 · PLA Silk"


@respx.mock
async def test_a_printer_without_ams_or_spool_says_so(ctx: Context) -> None:
    bambuddy(answers(status(ams=[], vt_tray=[])))
    data = await get_adapter("bambuddy").fetch("ams", CONFIG, {}, ctx)
    assert data.items == [] and data.meta["empty"] == "This printer has no AMS and no external spool."


# -- the printers card -------------------------------------------------------------


@respx.mock
async def test_the_printers_card_lists_every_printer_with_its_state_and_progress(ctx: Context) -> None:
    replies = answers()
    replies["/api/v1/printers/1/status"] = httpx.Response(200, json=status(
        id=1, name="Workshop H2D", state="FAILED", hms_errors=[{"code": "x", "module": 1, "severity": 1, "description": "Clog."}]))
    bambuddy(replies)
    data = await get_adapter("bambuddy").fetch("printers", CONFIG, {}, ctx)
    assert [(item["title"], item["subtitle"], item["value"], item["status"]) for item in data.items] == [
        ("Garage P1S", "Planter_v3", "42 %", "ok"), ("Workshop H2D", "H2D", "Failed", "bad")]
    assert data.items[0]["progress"] == 42.0
    assert data.status == "bad"
    assert data.secondary == [{"label": "Printers", "value": 2}, {"label": "Printing", "value": 1}]


# -- the queue card ----------------------------------------------------------------


QUEUE = [
    {"id": 21, "printer_id": 3, "status": "pending", "position": 2, "archive_name": "Cable clips x20", "printer_name": "Garage P1S",
     "print_time_seconds": 2700, "archive_id": 7, "library_file_id": None},
    {"id": 20, "printer_id": 3, "status": "printing", "position": 1, "archive_name": "Planter_v3", "printer_name": "Garage P1S",
     "print_time_seconds": 15120, "archive_id": 6, "library_file_id": None},
    {"id": 22, "printer_id": None, "target_model": "H2D", "status": "pending", "position": 3, "archive_name": None,
     "library_file_name": "Hinge bracket", "printer_name": None, "print_time_seconds": None, "archive_id": None, "library_file_id": 4},
]


@respx.mock
async def test_the_queue_shows_what_prints_and_what_waits_in_order(ctx: Context) -> None:
    route = bambuddy({"/api/v1/queue/": httpx.Response(200, json=QUEUE)})
    data = await get_adapter("bambuddy").fetch("queue", CONFIG, {}, ctx)
    sent = route.calls.last.request
    assert dict(sent.url.params) == {"status": "pending,printing"}
    assert sent.headers["X-API-Key"] == CONFIG["api_key"]
    assert [(item["title"], item["subtitle"], item["value"], item["status"]) for item in data.items] == [
        ("Planter_v3", "Printing · Garage P1S", "4h 12m", "ok"), ("Cable clips x20", "Garage P1S", "45m", "unknown"),
        ("Hinge bracket", "H2D", "", "unknown")]
    assert data.secondary == [{"label": "Waiting", "value": 2}, {"label": "Printing", "value": 1}]
    assert data.metrics == {"waiting": 2.0}


@respx.mock
async def test_the_queue_of_one_printer_and_its_limit(ctx: Context) -> None:
    route = bambuddy({"/api/v1/queue/": httpx.Response(200, json=QUEUE)})
    data = await get_adapter("bambuddy").fetch("queue", CONFIG, {"printer": "3", "limit": 1}, ctx)
    assert dict(route.calls.last.request.url.params) == {"status": "pending,printing", "printer_id": "3"}
    assert len(data.items) == 1 and data.secondary[0] == {"label": "Waiting", "value": 2}


@respx.mock
async def test_a_printer_that_is_no_number_never_reaches_the_address(ctx: Context) -> None:
    route = bambuddy({"/api/v1/queue/": httpx.Response(200, json=QUEUE)})
    with pytest.raises(AdapterError):
        await get_adapter("bambuddy").fetch("queue", CONFIG, {"printer": "3&status=completed"}, ctx)
    assert not route.calls


@respx.mock
async def test_an_empty_queue_says_so(ctx: Context) -> None:
    bambuddy({"/api/v1/queue/": httpx.Response(200, json=[])})
    data = await get_adapter("bambuddy").fetch("queue", CONFIG, {}, ctx)
    assert data.items == [] and data.meta["empty"] == "The queue is empty."


# -- custom cards and the demo --------------------------------------------------------


def test_a_custom_card_may_not_stop_the_camera() -> None:
    adapter = get_adapter("bambuddy")
    with pytest.raises(AdapterError):
        rawread.refuse_a_command(adapter, "/api/v1/printers/3/camera/stop")
    rawread.refuse_a_command(adapter, "/api/v1/printers/3/status")


def test_the_adapter_only_reads_and_keeps_its_key_secret() -> None:
    adapter = get_adapter("bambuddy")
    assert adapter.beta is True
    assert adapter.secret_field_names() == {"api_key"}
    assert "action" not in type(adapter).__dict__ and not adapter.deeds, "no button: the cards never control a printer"


@pytest.mark.parametrize("kind", ["printer", "ams", "printers", "queue"])
@pytest.mark.parametrize("tick", [0, 60, 130])
def test_every_card_has_a_demo(kind: str, tick: int) -> None:
    data = get_adapter("bambuddy").demo(kind, {}, tick)
    assert data.primary or data.items


def test_the_demo_of_the_second_printer_is_another_printer() -> None:
    adapter = get_adapter("bambuddy")
    assert adapter.demo("ams", {"printer": "2"}, 0).meta["empty"]
    assert adapter.demo("printer", {"printer": "2"}, 0).primary == {"label": "State", "value": "Idle"}
