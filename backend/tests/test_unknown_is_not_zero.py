"""A number nobody measured is not a zero.

⚠️ ``percent()`` answered 0.0 to "I do not know", and ``status_from_percent``
coloured that green. It is the common root of a set of cards that reported a
healthy nothing, and each of them went unnoticed for the same reason: a zero
looks like a measurement.

* Nextcloud stood at 0 percent used, because the fallback for a missing disk
  size was ``free + num_files * 0``, which by the rules of precedence is
  exactly ``free``: the total became the free space and the used space nothing.
* The UPS card showed a charge of 0 percent for every UPS that does not report
  ``battery.charge``, and small models genuinely do not.
* UniFi wrote 0 Mbit/s into the history whenever the statistics query failed,
  and a WAN that reads flat zero for an hour is a thing somebody acts on.
* Frigate coloured the recordings card green when the folder size was missing.
* The queue of an arr service counted the page it had asked for, not the queue.

The other half of the file is about numbers that were attached to the wrong
thing: UniFi paired statistics with devices by position in a list it had
filtered, and every Wake-on-LAN card in the house shared one "just woken".
"""

from __future__ import annotations

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import Context, measured, percent, percent_text, status_from_percent, worst


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


# -- the helpers themselves ----------------------------------------------------


def test_a_share_of_nothing_is_not_a_share_of_zero() -> None:
    assert percent(0, 200) == 0.0, "a genuine zero has to stay a zero"
    assert percent(50, 200) == 25.0
    assert percent(5, None) is None, "no whole to divide by"
    assert percent(5, 0) is None
    assert percent(None, 200) is None


def test_nothing_measured_is_not_coloured_green() -> None:
    assert status_from_percent(0.0) == "ok"
    assert status_from_percent(96.0) == "bad"
    assert status_from_percent(None) == "unknown", "an unknown share was answered with ok"


def test_the_worst_of_what_is_known_ignores_what_is_not() -> None:
    assert worst(12.0, None, 71.0) == 71.0
    assert worst(None, None) is None, "all of them missing is not a zero"
    assert worst() is None


def test_only_measured_numbers_reach_the_history() -> None:
    assert measured({"cpu": 4.0, "memory": None}) == {"cpu": 4.0}
    assert measured({"cpu": 0.0}) == {"cpu": 0.0}, "a measured zero belongs in the history"


def test_a_share_for_the_eye_says_when_it_does_not_know() -> None:
    assert percent_text(73.4) == "73%"
    assert percent_text(73.4, 1) == "73.4%"
    assert percent_text(None) == "?"


# -- the cards -----------------------------------------------------------------


def _nextcloud(**system: object) -> dict:
    return {"ocs": {"data": {"nextcloud": {
        "system": {"version": "34.0.3", "freespace": 4.0e11, **system},
        "storage": {"num_users": 14, "num_files": 91_000},
    }, "activeUsers": {}}}}


@respx.mock
async def test_nextcloud_says_it_cannot_size_the_disk_instead_of_showing_zero(ctx: Context) -> None:
    respx.get("https://cloud.example.com/ocs/v2.php/apps/serverinfo/api/v1/info").mock(
        return_value=httpx.Response(200, json=_nextcloud()))
    from app.adapters.base import AdapterError

    with pytest.raises(AdapterError) as refused:
        await get_adapter("nextcloud").fetch("storage", {"url": "https://cloud.example.com", "token": "t"}, {}, ctx)
    assert refused.value.code == "no_total"


@respx.mock
async def test_nextcloud_measures_the_disk_when_it_knows_it(ctx: Context) -> None:
    respx.get("https://cloud.example.com/ocs/v2.php/apps/serverinfo/api/v1/info").mock(
        return_value=httpx.Response(200, json=_nextcloud(disk_total=1.0e12)))
    data = await get_adapter("nextcloud").fetch("storage", {"url": "https://cloud.example.com", "token": "t"}, {}, ctx)
    assert data.primary == {"label": "Used", "value": 60.0, "unit": "%"}
    assert data.metrics == {"used_percent": 60.0}


@respx.mock
async def test_the_overview_records_no_share_it_cannot_work_out(ctx: Context) -> None:
    """⚠️ ``free_percent`` was written as a flat 0.0 on every single pass."""
    respx.get("https://cloud.example.com/ocs/v2.php/apps/serverinfo/api/v1/info").mock(
        return_value=httpx.Response(200, json=_nextcloud()))
    data = await get_adapter("nextcloud").fetch("overview", {"url": "https://cloud.example.com", "token": "t"}, {}, ctx)
    assert "free_percent" not in data.metrics, "a straight line at zero that looked like a measurement"
    assert data.metrics["users"] == 14.0


def _ups(**variables: object) -> None:
    """One UPS called "ups", with the variables a small model actually sends."""
    respx.get("http://nut.example.com:8080/api/v1/devices").mock(
        return_value=httpx.Response(200, json=[{"name": "ups"}]))
    respx.get("http://nut.example.com:8080/api/v1/devices/ups").mock(
        return_value=httpx.Response(200, json={"vars": {"ups.status": "OL", "device.model": "Eaton 3S", **variables}}))


@respx.mock
async def test_a_ups_that_keeps_its_charge_to_itself_shows_no_charge(ctx: Context) -> None:
    _ups()
    data = await get_adapter("peanut").fetch("ups", {"url": "http://nut.example.com:8080"}, {}, ctx)
    assert data.primary["value"] is None, "0 percent reads as an empty battery"
    assert data.primary["unit"] == "", "and a dash with a percent sign after it reads as one too"
    assert "charge" not in data.metrics


@respx.mock
async def test_a_ups_that_reports_its_charge_still_shows_it(ctx: Context) -> None:
    _ups(**{"battery.charge": "42"})
    data = await get_adapter("peanut").fetch("ups", {"url": "http://nut.example.com:8080"}, {}, ctx)
    assert data.primary["value"] == 42
    assert data.metrics["charge"] == 42.0
    assert data.status == "warn", "under half is worth a colour"


# -- numbers attached to the wrong thing ---------------------------------------

UNIFI = "https://udm"
UNIFI_API = f"{UNIFI}/proxy/network/integration/v1"
SITE = "88f7af54-98f8-306a-a1c7-c9349722b1f6"
UNIFI_CONFIG = {"url": UNIFI, "api_key": "nd-key", "site": "default", "unifi_os": True, "insecure": True}


def _unifi(devices: list[dict], *, gateway_stats: httpx.Response) -> None:
    respx.get(f"{UNIFI_API}/info").mock(return_value=httpx.Response(200, json={"applicationVersion": "9.1.120"}))
    respx.get(f"{UNIFI_API}/sites").mock(return_value=httpx.Response(200, json={
        "offset": 0, "limit": 200, "count": 1, "totalCount": 1,
        "data": [{"id": SITE, "internalReference": "default", "name": "Home"}]}))
    respx.get(f"{UNIFI_API}/sites/{SITE}/devices").mock(return_value=httpx.Response(200, json={
        "offset": 0, "limit": 200, "count": len(devices), "totalCount": len(devices), "data": devices}))
    respx.get(f"{UNIFI_API}/sites/{SITE}/clients").mock(return_value=httpx.Response(200, json={
        "offset": 0, "limit": 200, "count": 0, "totalCount": 0, "data": []}))
    respx.get(f"{UNIFI_API}/sites/{SITE}/devices/gw/statistics/latest").mock(return_value=gateway_stats)
    for device in devices:
        if device.get("id") and device["id"] != "gw":
            respx.get(f"{UNIFI_API}/sites/{SITE}/devices/{device['id']}/statistics/latest").mock(
                return_value=httpx.Response(200, json={"cpuUtilizationPct": device.pop("_cpu", 0)}))


@respx.mock
async def test_unifi_does_not_hand_a_device_the_load_of_the_next_one(ctx: Context) -> None:
    """⚠️ The answers were paired with the devices by position, in a list the
    request had filtered: every device without an id shifted the rest by one.
    """
    _unifi([
        {"id": "gw", "name": "Dream Machine", "model": "UDM-Pro", "state": "ONLINE", "features": ["gateway"]},
        {"name": "Nameless", "model": "USW-Flex", "state": "ONLINE", "features": ["switching"]},
        {"id": "ap1", "name": "Living room", "model": "U6-Pro", "state": "ONLINE", "features": ["accessPoint"], "_cpu": 33.7},
    ], gateway_stats=httpx.Response(200, json={"cpuUtilizationPct": 12.4, "uplink": {"rxRateBps": 8e7, "txRateBps": 8e6}}))

    devices = await get_adapter("unifi").fetch("devices", UNIFI_CONFIG, {}, ctx)
    shown = {item["title"]: item["value"] for item in devices.items}
    assert shown["Dream Machine"] == "12% cpu"
    assert shown["Living room"] == "34% cpu", "the load of the device above it"
    assert shown["Nameless"] == "", "there is no statistics query for a device without an id"


@respx.mock
async def test_unifi_writes_no_throughput_it_could_not_read(ctx: Context) -> None:
    """⚠️ A failed statistics query became 0 Mbit/s in the history, on every
    pass, and a WAN that reads flat zero for an hour is acted on.
    """
    _unifi([{"id": "gw", "name": "Dream Machine", "model": "UDM-Pro", "state": "ONLINE", "features": ["gateway"]}],
           gateway_stats=httpx.Response(500, json={"statusCode": 500}))

    summary = await get_adapter("unifi").fetch("summary", UNIFI_CONFIG, {}, ctx)
    assert "wan_down" not in summary.metrics and "wan_up" not in summary.metrics
    chips = {chip["label"]: chip["value"] for chip in summary.secondary}
    assert chips["WAN down"] == "?", "and the card says so rather than showing 0 bit/s"


@respx.mock
async def test_unifi_still_records_a_throughput_of_zero_that_was_measured(ctx: Context) -> None:
    """A gateway that genuinely moves nothing is a measurement, not a gap."""
    _unifi([{"id": "gw", "name": "Dream Machine", "model": "UDM-Pro", "state": "ONLINE", "features": ["gateway"]}],
           gateway_stats=httpx.Response(200, json={"uplink": {"rxRateBps": 0, "txRateBps": 0}}))

    summary = await get_adapter("unifi").fetch("summary", UNIFI_CONFIG, {}, ctx)
    assert summary.metrics["wan_down"] == 0.0


async def test_waking_one_machine_does_not_mark_every_other_card_woken(ctx: Context, monkeypatch: pytest.MonkeyPatch) -> None:
    """⚠️ Cards without a connection all share one cache, and the wake time was
    filed under a single key. Pressing Wake on one machine put "Woken 0 s" on
    every Wake-on-LAN card in the house and told each of them that their
    machine had not answered yet.
    """
    monkeypatch.setattr("app.adapters.wol._send", lambda packet, broadcast, port: None)

    async def asleep(host: str, port: int, timeout: float = 2.0) -> bool:
        return False

    monkeypatch.setattr("app.adapters.wol.reachable", asleep)
    wol = get_adapter("wol")
    mine = {"mac": "00:1A:2B:3C:4D:5E", "host": "workstation", "check_port": 22}
    theirs = {"mac": "AA:BB:CC:DD:EE:FF", "host": "printer", "check_port": 9100}

    await wol.action("wake", "wake", {}, mine, {}, ctx)
    woken = await wol.fetch("wake", mine, {}, ctx)
    untouched = await wol.fetch("wake", theirs, {}, ctx)

    assert any(row["label"] == "Woken" for row in woken.secondary), "the machine that was woken says so"
    assert not any(row["label"] == "Woken" for row in untouched.secondary), "and no other card does"
    assert untouched.meta["status_reason"] == "The machine is asleep."
    assert woken.meta["status_reason"] == "The machine has not answered yet."


async def test_a_card_with_nothing_to_knock_on_records_no_state(ctx: Context) -> None:
    """A zero there is a machine reported as asleep, on a card that cannot know."""
    blind = await get_adapter("wol").fetch("wake", {"mac": "00:1A:2B:3C:4D:5E"}, {}, ctx)
    assert blind.status == "unknown"
    assert blind.metrics == {}, "0.0 in the history reads as a machine that is off"


# -- counting the whole thing --------------------------------------------------

RADARR = "http://radarr.example.com:7878"


@respx.mock
async def test_the_arr_queue_counts_the_queue_and_not_the_page(ctx: Context) -> None:
    """⚠️ One request asks for a hundred entries and the count was the length
    of what came back, so a queue of 340 read as 100 and stopped moving, and
    the history along with it.
    """
    records = [{"id": number, "title": f"Film {number}", "size": 1000, "sizeleft": 400, "status": "downloading"}
               for number in range(100)]
    respx.get(f"{RADARR}/api/v3/queue").mock(return_value=httpx.Response(200, json={
        "page": 1, "pageSize": 100, "totalRecords": 340, "records": records}))

    data = await get_adapter("radarr").fetch("queue", {"url": RADARR, "api_key": "k" * 32}, {}, ctx)
    assert data.metrics == {"queued": 340.0}
    assert {chip["label"]: chip["value"] for chip in data.secondary} == {"In queue": 340}
    assert len(data.items) == 8, "and it still only draws the first few rows"
    assert data.items[0]["value"] == "60%"


@respx.mock
async def test_a_queue_entry_of_unknown_size_shows_no_progress(ctx: Context) -> None:
    """A zero there looked like a download that has not started."""
    respx.get(f"{RADARR}/api/v3/queue").mock(return_value=httpx.Response(200, json={"totalRecords": 1, "records": [
        {"id": 1, "title": "Unknown size", "sizeleft": 0, "status": "downloading"},
    ]}))
    data = await get_adapter("radarr").fetch("queue", {"url": RADARR, "api_key": "k" * 32}, {}, ctx)
    assert data.items[0]["progress"] is None
    assert data.items[0]["value"] == "?"


# -- units that are read, not guessed ------------------------------------------

SPEEDTEST = "http://speedtest.example.com:8080"


@respx.mock
async def test_speedtest_reads_the_unit_off_the_field_instead_of_the_size(ctx: Context) -> None:
    """⚠️ The unit used to be guessed from the number: above 100000 it was
    taken as bytes per second, below it as megabits. A line that genuinely
    measures under 0.8 Mbit/s therefore came out as tens of thousands of Mbps.
    """
    respx.get(f"{SPEEDTEST}/api/v1/results/latest").mock(return_value=httpx.Response(200, json={"data": {
        "download_bits": 94_000_000, "upload_bits": 12_000_000, "ping": 8.4, "created_at": "2026-09-07T06:00:00",
    }}))
    data = await get_adapter("speedtest").fetch("latest", {"url": SPEEDTEST}, {}, ctx)
    assert data.primary["value"] == 94.0
    assert data.metrics == {"download": 94.0, "upload": 12.0, "ping": 8.4}


@respx.mock
async def test_a_slow_line_is_not_read_as_a_fast_one(ctx: Context) -> None:
    """90000 bytes per second is 0.7 Mbit/s, and used to be reported as 90000."""
    respx.get(f"{SPEEDTEST}/api/v1/results/latest").mock(return_value=httpx.Response(200, json={"data": {
        "download": 90_000, "upload": 20_000, "ping": 61.0, "created_at": "2026-09-07T06:00:00",
    }}))
    data = await get_adapter("speedtest").fetch("latest", {"url": SPEEDTEST}, {}, ctx)
    assert data.primary["value"] == 0.7
    assert data.metrics["upload"] == 0.2


# -- a box that is offered has to do something ---------------------------------


async def test_transmission_honours_the_tls_box(ctx: Context, monkeypatch: pytest.MonkeyPatch) -> None:
    """⚠️ The field was offered, saved and shown, and never read: the RPC call
    posted straight to the shared client and walked past everything the
    context does around a call. A Transmission behind a self-signed
    certificate was simply unreachable, with nothing pointing at the box.
    """
    seen: list[bool] = []

    async def note(self: Context, method: str, url: str, **kwargs: object) -> httpx.Response:
        seen.append(bool(kwargs.get("verify", True)))
        return httpx.Response(200, json={"result": "success", "arguments": {"torrents": []}})

    monkeypatch.setattr(Context, "request", note)
    adapter = get_adapter("transmission")
    await adapter.fetch("summary", {"url": "https://box.example.com:9091", "insecure": True}, {}, ctx)
    await adapter.fetch("summary", {"url": "https://box.example.com:9091"}, {}, ctx)
    assert seen and seen[0] is False, "the box was ticked and the call still verified"
    assert seen[-1] is True, "and without the box it still verifies"


def test_the_home_assistant_socket_honours_the_tls_box() -> None:
    """The same box, on the one connection that is not HTTP.

    ⚠️ Everything the adapter fetched honoured ``insecure`` and the WebSocket
    did not, so a Home Assistant behind a self-signed certificate showed its
    cards and never received a state change: the socket failed to open every
    twenty seconds, which reads as "reconnecting", not as "the certificate".
    """
    import ssl

    from app.services.hass_ws import ssl_options

    relaxed = ssl_options("wss://home.example.com/api/websocket", {"insecure": True})
    assert relaxed["ssl"].verify_mode == ssl.CERT_NONE and relaxed["ssl"].check_hostname is False
    assert ssl_options("wss://home.example.com/api/websocket", {}) == {}, "without the box it verifies"
    assert ssl_options("ws://home.example.com/api/websocket", {"insecure": True}) == {}, "and plain ws has no certificate to relax"
