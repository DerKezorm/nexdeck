"""NetAlertX, against the answers of a live NetAlertX 26.9.0 (11.09.2026) scanning a Docker test network."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context, Unreachable
from app.adapters.netalertx import NetAlertXAdapter, moment

FIXTURES = Path(__file__).parent / "fixtures"
NX = "http://netalertx.example.com:20212"
CONFIG = {"url": NX, "token": "t_madeuptokenmadeupto"}
UTC_ZONE = ZoneInfo("UTC")
#: Twenty minutes after the first scan found the test network.
NOW = datetime(2026, 9, 11, 21, 25, 47, tzinfo=UTC).timestamp()


def fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


NEW = fixture("netalertx_new.json")
OFFLINE = fixture("netalertx_offline.json")


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


def _rows(data: Any) -> list[tuple[Any, ...]]:
    return [(row["title"], row["subtitle"], row["status"], row["value"], [one.params["mac"] for one in row.get("actions", [])]) for row in data.items]


def test_new_devices_the_newest_first_with_a_button_each() -> None:
    archived = {**NEW[1], "devMac": "02:00:00:00:00:0a", "devLastIP": "192.0.2.99", "devIsArchived": 1}
    data = NetAlertXAdapter._new([*NEW, archived], UTC_ZONE, {}, now=NOW)
    # ⚠️ Measured: the two gone ones still say "New" in devStatus; devPresentLastScan 0 is what says they are gone.
    assert _rows(data) == [
        ("192.0.2.10", "", "warn", "11 min", ["02:00:00:00:00:05"]),
        ("192.0.2.1", "", "warn", "20 min", ["02:00:00:00:00:01"]),
        ("192.0.2.10", "Offline", "bad", "20 min", ["02:00:00:00:00:04"]),
        ("192.0.2.22", "", "warn", "20 min", ["02:00:00:00:00:02"]),
        ("192.0.2.23", "Offline", "bad", "20 min", ["02:00:00:00:00:03"]),
    ]
    first = data.items[0]["actions"][0]
    assert (first.id, first.label, first.confirm) == ("known", "Mark as known", True) and data.meta["actions_visible"] is True
    assert data.secondary == [{"label": "New", "value": 5}] and data.metrics == {"new": 5.0} and data.status == "warn"
    assert len(NetAlertXAdapter._new(NEW, UTC_ZONE, {"limit": 2}, now=NOW).items) == 2
    assert NetAlertXAdapter._new([], UTC_ZONE, {}, now=NOW).status == "ok"


def test_a_named_device_shows_its_address_and_vendor() -> None:
    named = {**NEW[1], "devName": "printer-hall", "devVendor": "Example Printers"}
    assert _rows(NetAlertXAdapter._new([named], UTC_ZONE, {}, now=NOW))[0][:2] == ("printer-hall", "192.0.2.22 · Example Printers")


def test_the_times_are_in_netalertx_own_zone() -> None:
    """⚠️ Measured: "2026-09-11 21:05:47" carries no zone; TIMEZONE says which."""
    assert moment("2026-09-11 21:05:47", ZoneInfo("Europe/Berlin")) == datetime(2026, 9, 11, 19, 5, 47, tzinfo=UTC).timestamp()
    assert NetAlertXAdapter._new(NEW[1:2], ZoneInfo("Europe/Berlin"), {}, now=NOW).items[0]["value"] == "2 h"
    assert moment("not a time", UTC_ZONE) is None


def test_offline_devices_the_most_recently_gone_first() -> None:
    # Out of a list where most are there, only the two that were missing in the last scan.
    data = NetAlertXAdapter._offline(NEW, UTC_ZONE, {}, now=NOW)
    assert _rows(data) == [("192.0.2.23", "New", "unknown", "11 min", []), ("192.0.2.10", "New", "unknown", "13 min", [])]
    assert data.status == "ok"
    data = NetAlertXAdapter._offline(OFFLINE, UTC_ZONE, {}, now=NOW)
    assert data.secondary == [{"label": "Offline", "value": 2}] and data.metrics == {"offline": 2.0}
    watched = [{**OFFLINE[0], "devAlertDown": 1}, OFFLINE[1]]
    data = NetAlertXAdapter._offline(watched, UTC_ZONE, {}, now=NOW)
    assert [row["status"] for row in data.items] == ["bad", "unknown"] and data.status == "bad"


def test_the_overview_takes_offline_as_devices_minus_connected() -> None:
    """⚠️ Measured: 6 devices, 4 connected, and the offline list held exactly 2."""
    data = NetAlertXAdapter._summary(fixture("netalertx_totals.json")["totals"])
    assert data.primary == {"label": "Online", "value": 4}
    assert data.secondary == [{"label": "New", "value": 5}, {"label": "Offline", "value": 2}]
    assert data.metrics == {"online": 4.0, "new": 5.0, "offline": 2.0} and data.status == "warn"
    assert NetAlertXAdapter._summary({"devices": 3, "connected": 3, "new": 0}).status == "ok"


@respx.mock
async def test_the_cards_ask_by_status_and_take_the_zone_from_the_settings(ctx: Context, monkeypatch: pytest.MonkeyPatch) -> None:
    respx.get(f"{NX}/settings/TIMEZONE").mock(return_value=httpx.Response(200, json={"success": True, "value": "Europe/Berlin"}))
    route = respx.get(f"{NX}/devices/by-status").mock(return_value=httpx.Response(200, json=NEW))
    seen: dict[str, Any] = {}
    original = NetAlertXAdapter._offline

    def spy(devices: list[dict[str, Any]], zone: ZoneInfo, options: dict[str, Any], now: float | None = None) -> Any:
        seen["zone"] = zone
        return original(devices, zone, options, now=NOW)

    monkeypatch.setattr(NetAlertXAdapter, "_offline", staticmethod(spy))
    data = await get_adapter("netalertx").fetch("offline", CONFIG, {}, ctx)
    assert route.calls.last.request.url.params["status"] == "offline"
    assert route.calls.last.request.headers["Authorization"] == "Bearer t_madeuptokenmadeupto"
    assert seen["zone"] == ZoneInfo("Europe/Berlin") and len(data.items) == 2
    await get_adapter("netalertx").fetch("new", CONFIG, {}, ctx)
    assert route.calls.last.request.url.params["status"] == "new"


@respx.mock
async def test_marking_a_device_as_known(ctx: Context) -> None:
    route = respx.post(f"{NX}/device/02:00:00:00:00:02/update-column").mock(return_value=httpx.Response(200, json={"success": True}))
    assert await get_adapter("netalertx").action("new", "known", {"mac": "02:00:00:00:00:02"}, CONFIG, {}, ctx) == "Device marked as known."
    assert json.loads(route.calls.last.request.content) == {"columnName": "devIsNew", "columnValue": 0}
    assert route.calls.last.request.headers["Authorization"] == "Bearer t_madeuptokenmadeupto"


@respx.mock
async def test_the_refusals_of_marking(ctx: Context) -> None:
    adapter = get_adapter("netalertx")
    address = f"{NX}/device/02:00:00:00:00:99/update-column"
    respx.post(address).mock(return_value=httpx.Response(404, json={"error": "Device not found", "success": False}))
    with pytest.raises(AdapterError) as gone:
        await adapter.action("new", "known", {"mac": "02:00:00:00:00:99"}, CONFIG, {}, ctx)
    assert (gone.value.code, gone.value.message) == ("action_failed", "NetAlertX has no such device any more.")
    # ⚠️ The API says so itself: 200 is not success, the body is.
    respx.post(address).mock(return_value=httpx.Response(200, json={"success": False, "error": "Database is locked"}))
    with pytest.raises(AdapterError) as refused:
        await adapter.action("new", "known", {"mac": "02:00:00:00:00:99"}, CONFIG, {}, ctx)
    assert refused.value.code == "action_failed" and "Database is locked" in refused.value.message
    respx.post(address).mock(return_value=httpx.Response(403, json={"error": "Forbidden", "message": "ERROR: Not authorized", "success": False}))
    with pytest.raises(AuthFailed):
        await adapter.action("new", "known", {"mac": "02:00:00:00:00:99"}, CONFIG, {}, ctx)
    with pytest.raises(AdapterError) as walked:
        await adapter.action("new", "known", {"mac": "../devices"}, CONFIG, {}, ctx)
    assert walked.value.code == "bad_param"
    with pytest.raises(AdapterError) as unknown:
        await adapter.action("new", "delete", {"mac": "02:00:00:00:00:02"}, CONFIG, {}, ctx)
    assert unknown.value.code == "no_such_action"


@respx.mock
async def test_a_rejected_token(ctx: Context) -> None:
    """⚠️ Measured: a missing and a made-up token both get this 403."""
    respx.get(f"{NX}/devices/totals/named").mock(return_value=httpx.Response(403, json={"error": "Forbidden", "message": "ERROR: Not authorized", "success": False}))
    with pytest.raises(AuthFailed):
        await get_adapter("netalertx").fetch("summary", CONFIG, {}, ctx)


@respx.mock
async def test_the_web_interface_port_is_not_the_api(ctx: Context) -> None:
    """Measured: the web interface answers the API's paths with 404."""
    respx.get(f"{NX}/devices/totals/named").mock(return_value=httpx.Response(404, text="<html>Not Found</html>"))
    with pytest.raises(AdapterError) as wrong:
        await get_adapter("netalertx").fetch("summary", CONFIG, {}, ctx)
    assert wrong.value.code == "http_error" and "20212" in wrong.value.hint


@respx.mock
async def test_an_address_that_is_not_netalertx(ctx: Context) -> None:
    respx.get(f"{NX}/settings/TIMEZONE").mock(return_value=httpx.Response(200, json={"success": True, "value": "UTC"}))
    respx.get(f"{NX}/devices/by-status").mock(return_value=httpx.Response(200, json={"status": "ok"}))
    with pytest.raises(AdapterError) as wrong:
        await get_adapter("netalertx").fetch("new", CONFIG, {}, ctx)
    assert wrong.value.code == "not_netalertx"
    respx.get(f"{NX}/devices/totals/named").mock(return_value=httpx.Response(200, json={"success": True}))
    with pytest.raises(AdapterError) as bare:
        await get_adapter("netalertx").fetch("summary", CONFIG, {}, ctx)
    assert bare.value.code == "not_netalertx"


@respx.mock
async def test_a_netalertx_that_does_not_answer(ctx: Context) -> None:
    respx.get(f"{NX}/devices/totals/named").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(Unreachable):
        await get_adapter("netalertx").fetch("summary", CONFIG, {}, ctx)


@respx.mock
async def test_the_connection_test(ctx: Context) -> None:
    respx.get(f"{NX}/devices/totals/named").mock(return_value=httpx.Response(200, json=fixture("netalertx_totals.json")))
    assert await get_adapter("netalertx").test(CONFIG, ctx) == "NetAlertX answers with 6 devices, 5 of them new."
