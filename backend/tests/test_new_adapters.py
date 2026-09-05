"""The ten integrations of the gap list, each against a recorded answer.

No test here touches the network. What is checked is the part that can be
wrong without anybody noticing: the shape a service answers with, and what the
card makes of it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, Context


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


# -- bazarr ------------------------------------------------------------------


@respx.mock
async def test_bazarr_counts_and_missing_languages(ctx: Context) -> None:
    config = {"url": "http://bazarr:6767", "api_key": "key"}
    respx.get("http://bazarr:6767/api/badges").mock(return_value=httpx.Response(200, json={"episodes": 7, "movies": 2, "providers": 1, "status": 0}))
    respx.get("http://bazarr:6767/api/episodes/wanted").mock(return_value=httpx.Response(200, json={"data": [
        {"seriesTitle": "Harbour Lights", "episode_number": "3x04", "missing_subtitles": [{"name": "German", "code2": "de"}]},
    ]}))
    respx.get("http://bazarr:6767/api/movies/wanted").mock(return_value=httpx.Response(200, json={"data": [
        {"title": "Copper Sky", "missing_subtitles": [{"name": "English"}, {"name": "German"}]},
    ]}))
    bazarr = get_adapter("bazarr")

    status = await bazarr.fetch("status", config, {}, ctx)
    assert status.primary == {"label": "Missing subtitles", "value": 9}
    assert status.status == "bad", "a throttled provider is worse than a queue"
    assert status.metrics == {"wanted": 9.0}
    assert respx.calls.last.request.headers["X-API-KEY"] == "key"

    wanted = await bazarr.fetch("wanted", config, {"limit": 8, "show": "all"}, ctx)
    assert [item["title"] for item in wanted.items] == ["Harbour Lights 3x04", "Copper Sky"]
    assert wanted.items[1]["subtitle"] == "English, German"

    only_movies = await bazarr.fetch("wanted", config, {"limit": 8, "show": "movies"}, ctx)
    assert [item["title"] for item in only_movies.items] == ["Copper Sky"]


# -- overseerr and jellyseerr -------------------------------------------------


@respx.mock
async def test_overseerr_and_jellyseerr_read_the_same_api(ctx: Context) -> None:
    for kind, host in (("overseerr", "http://overseerr:5055"), ("jellyseerr", "http://jellyseerr:5055")):
        respx.get(f"{host}/api/v1/request/count").mock(return_value=httpx.Response(200, json={"pending": 3, "approved": 40, "available": 38, "total": 43}))
        data = await get_adapter(kind).fetch("counts", {"url": host, "api_key": "k"}, {}, Context(httpx.AsyncClient(), cache={}))
        assert data.primary == {"label": "Pending", "value": 3}
        assert data.status == "warn"
        assert respx.calls.last.request.headers["X-Api-Key"] == "k"


@respx.mock
async def test_overseerr_names_itself_in_the_connection_test(ctx: Context) -> None:
    respx.get("http://overseerr:5055/api/v1/status").mock(return_value=httpx.Response(200, json={"version": "1.34.0"}))
    message = await get_adapter("overseerr").test({"url": "http://overseerr:5055", "api_key": "k"}, ctx)
    assert message == "Overseerr 1.34.0 answers."


# -- immich ------------------------------------------------------------------


@respx.mock
async def test_immich_library_storage_and_users(ctx: Context) -> None:
    config = {"url": "http://immich:2283", "api_key": "key"}
    respx.get("http://immich:2283/api/server/statistics").mock(return_value=httpx.Response(200, json={
        "photos": 48210, "videos": 1840, "usage": 1_500_000_000_000,
        "usageByUser": [{"userName": "Sam", "photos": 12400, "videos": 640, "usage": 420_000_000_000},
                        {"userName": "Alex", "photos": 31200, "videos": 900, "usage": 810_000_000_000}],
    }))
    respx.get("http://immich:2283/api/server/storage").mock(return_value=httpx.Response(200, json={
        "diskSizeRaw": 4_000_000_000_000, "diskUseRaw": 1_600_000_000_000, "diskUsagePercentage": 40.0,
    }))
    immich = get_adapter("immich")

    library = await immich.fetch("library", config, {}, ctx)
    assert library.primary == {"label": "Pictures", "value": 48210}
    assert respx.calls.last.request.headers["x-api-key"] == "key"

    storage = await immich.fetch("storage", config, {}, ctx)
    assert storage.primary["value"] == 40.0
    assert storage.status == "ok"

    users = await immich.fetch("users", config, {"limit": 6}, ctx)
    assert [item["title"] for item in users.items] == ["Alex", "Sam"], "the biggest first"


# -- traefik -----------------------------------------------------------------


@respx.mock
async def test_traefik_counts_broken_routers(ctx: Context) -> None:
    config = {"url": "http://traefik:8080"}
    respx.get("http://traefik:8080/api/overview").mock(return_value=httpx.Response(200, json={
        "http": {"routers": {"total": 18, "warnings": 0, "errors": 1},
                 "services": {"total": 15, "errors": 0},
                 "middlewares": {"total": 7, "errors": 0}},
    }))
    # The broken one stands last on purpose: only the sorting can bring it up.
    respx.get("http://traefik:8080/api/http/routers").mock(return_value=httpx.Response(200, json=[
        {"name": "deck@docker", "rule": "Host(`deck.example.com`)", "status": "enabled", "service": "nexdeck"},
        {"name": "photos@docker", "rule": "Host(`photos.example.com`)", "status": "disabled", "service": "immich"},
    ]))
    traefik = get_adapter("traefik")

    overview = await traefik.fetch("overview", config, {}, ctx)
    assert overview.status == "bad"
    assert overview.primary == {"label": "Routers", "value": 18}

    routers = await traefik.fetch("routers", config, {"limit": 10}, ctx)
    assert [item["title"] for item in routers.items] == ["photos", "deck"], "the broken one first"
    only = await traefik.fetch("routers", config, {"limit": 10, "only_problems": True}, ctx)
    assert [item["title"] for item in only.items] == ["photos"]


# -- nginx proxy manager -------------------------------------------------------


@respx.mock
async def test_npm_signs_in_once_and_warns_before_a_certificate_ends(ctx: Context) -> None:
    config = {"url": "http://npm:81", "email": "deck@example.com", "password": "pw"}
    token = respx.post("http://npm:81/api/tokens").mock(return_value=httpx.Response(200, json={"token": "jwt", "expires": "2026-09-06T00:00:00.000Z"}))
    soon = (datetime.now(UTC) + timedelta(days=4)).isoformat()
    later = (datetime.now(UTC) + timedelta(days=200)).isoformat()
    respx.get("http://npm:81/api/nginx/certificates").mock(return_value=httpx.Response(200, json=[
        {"nice_name": "example.com", "domain_names": ["example.com", "*.example.com"], "expires_on": later},
        {"nice_name": "intern.example.org", "domain_names": ["intern.example.org"], "expires_on": soon},
    ]))
    respx.get("http://npm:81/api/nginx/proxy-hosts").mock(return_value=httpx.Response(200, json=[
        {"domain_names": ["deck.example.com"], "forward_scheme": "http", "forward_host": "nexdeck", "forward_port": 8000, "enabled": 1, "certificate_id": 1},
        {"domain_names": ["old.example.com"], "forward_scheme": "http", "forward_host": "retired", "forward_port": 80, "enabled": 0, "certificate_id": 0},
    ]))
    npm = get_adapter("npm")

    certificates = await npm.fetch("certificates", config, {"limit": 8}, ctx)
    assert certificates.status == "bad", "four days left is a finding"
    assert [item["title"] for item in certificates.items] == ["intern.example.org", "example.com"]
    assert certificates.metrics["days_left"] == 3.0 or certificates.metrics["days_left"] == 4.0

    hosts = await npm.fetch("hosts", config, {"limit": 10}, ctx)
    assert [item["status"] for item in hosts.items] == ["ok", "unknown"]
    assert token.call_count == 1, "the token is kept, not asked for again"


@respx.mock
async def test_npm_refuses_a_wrong_account_readably(ctx: Context) -> None:
    respx.post("http://npm:81/api/tokens").mock(return_value=httpx.Response(401, json={"error": {"message": "no"}}))
    with pytest.raises(AdapterError) as failure:
        await get_adapter("npm").fetch("hosts", {"url": "http://npm:81", "email": "a@example.com", "password": "x"}, {}, ctx)
    assert failure.value.code == "auth_failed"


# -- peanut ------------------------------------------------------------------


@respx.mock
async def test_peanut_reads_the_first_ups_and_translates_its_flags(ctx: Context) -> None:
    config = {"url": "http://peanut:8080"}
    respx.get("http://peanut:8080/api/v1/devices").mock(return_value=httpx.Response(200, json=[{"name": "ups"}]))
    respx.get("http://peanut:8080/api/v1/devices/ups").mock(return_value=httpx.Response(200, json={
        "battery.charge": "100", "ups.load": "23", "battery.runtime": "1080",
        "ups.status": "OB DISCHRG", "device.model": "Example 1500VA", "input.voltage": "0.0",
    }))
    data = await get_adapter("peanut").fetch("ups", config, {}, ctx)
    assert data.status == "bad", "on battery is not a warning"
    assert data.primary == {"label": "Charge", "value": 100.0, "unit": "%"}
    assert [entry["value"] for entry in data.secondary if entry["label"] == "State"] == ["On battery, Discharging"]
    assert data.metrics["runtime"] == 1080.0


@respx.mock
async def test_peanut_says_when_there_is_no_ups(ctx: Context) -> None:
    respx.get("http://peanut:8080/api/v1/devices").mock(return_value=httpx.Response(200, json=[]))
    with pytest.raises(AdapterError) as failure:
        await get_adapter("peanut").fetch("ups", {"url": "http://peanut:8080"}, {}, ctx)
    assert failure.value.code == "no_device"


# -- scrutiny ------------------------------------------------------------------


@respx.mock
async def test_scrutiny_sorts_the_failing_disk_to_the_top(ctx: Context) -> None:
    respx.get("http://scrutiny:8080/api/summary").mock(return_value=httpx.Response(200, json={"data": {"summary": {
        "sda": {"device": {"device_name": "sda", "model_name": "Example SSD", "device_status": 0, "capacity": 1_000_000_000_000},
                "smart": {"temp": 33, "power_on_hours": 12800}},
        "sdb": {"device": {"device_name": "sdb", "model_name": "Example HDD", "device_status": 1, "capacity": 8_000_000_000_000},
                "smart": {"temp": 44, "power_on_hours": 34100}},
        "sdc": {"device": {"device_name": "sdc", "model_name": "Example HDD", "device_status": 0, "capacity": 8_000_000_000_000},
                "smart": {"temp": 58, "power_on_hours": 33900}},
    }}}))
    scrutiny = get_adapter("scrutiny")
    disks = await scrutiny.fetch("disks", {"url": "http://scrutiny:8080"}, {"limit": 10}, ctx)
    assert disks.status == "bad"
    assert [item["title"].split()[0] for item in disks.items] == ["sdb", "sdc", "sda"], "failing first, then the warm one"
    assert disks.items[1]["status"] == "warn", "58 °C is warm enough to say so"

    summary = await scrutiny.fetch("summary", {"url": "http://scrutiny:8080"}, {}, ctx)
    assert summary.primary == {"label": "Disks", "value": 3}
    assert summary.metrics == {"failing": 1.0, "hottest": 58.0}


# -- nextcloud -----------------------------------------------------------------


@respx.mock
async def test_nextcloud_reads_the_serverinfo_envelope(ctx: Context) -> None:
    config = {"url": "https://cloud.example.com", "token": "t"}
    respx.get("https://cloud.example.com/ocs/v2.php/apps/serverinfo/api/v1/info").mock(return_value=httpx.Response(200, json={
        "ocs": {"data": {
            "nextcloud": {"system": {"version": "31.0.2", "freespace": 410_000_000_000},
                          "storage": {"num_users": 14, "num_files": 184320}},
            "activeUsers": {"last5minutes": 2, "last1hour": 5, "last24hours": 11},
        }},
    }))
    nextcloud = get_adapter("nextcloud")
    overview = await nextcloud.fetch("overview", config, {}, ctx)
    assert overview.primary == {"label": "Users", "value": 14}
    assert respx.calls.last.request.headers["NC-Token"] == "t"

    activity = await nextcloud.fetch("activity", config, {}, ctx)
    assert [entry["value"] for entry in activity.secondary] == [2, 5, 11]


@respx.mock
async def test_nextcloud_without_a_token_or_account_says_so(ctx: Context) -> None:
    with pytest.raises(AdapterError) as failure:
        await get_adapter("nextcloud").fetch("overview", {"url": "https://cloud.example.com"}, {}, ctx)
    assert failure.value.code == "missing_fields"


# -- tautulli ------------------------------------------------------------------


@respx.mock
async def test_tautulli_reads_its_envelope_and_counts_transcodes(ctx: Context) -> None:
    config = {"url": "http://tautulli:8181", "api_key": "key"}
    respx.get("http://tautulli:8181/api/v2").mock(return_value=httpx.Response(200, json={"response": {"result": "success", "data": {
        "stream_count": "2", "stream_count_transcode": "1", "stream_count_direct_play": "1", "total_bandwidth": 24000,
        "sessions": [
            {"full_title": "The Quiet Harbour", "friendly_name": "Alex", "player": "Living room", "progress_percent": "42", "transcode_decision": "direct play"},
            {"full_title": "Harbour Lights S03E04", "friendly_name": "Sam", "player": "Bedroom TV", "progress_percent": "8", "transcode_decision": "transcode"},
        ],
    }}}))
    tautulli = get_adapter("tautulli")
    activity = await tautulli.fetch("activity", config, {}, ctx)
    assert [item["status"] for item in activity.items] == ["ok", "warn"]
    assert activity.items[0]["progress"] == 42.0
    counts = await tautulli.fetch("counts", config, {}, Context(httpx.AsyncClient(), cache={}))
    assert counts.primary == {"label": "Streams", "value": 2}


@respx.mock
async def test_tautulli_failure_message_reaches_the_card(ctx: Context) -> None:
    respx.get("http://tautulli:8181/api/v2").mock(return_value=httpx.Response(200, json={"response": {"result": "error", "message": "Invalid apikey"}}))
    with pytest.raises(AdapterError) as failure:
        await get_adapter("tautulli").fetch("counts", {"url": "http://tautulli:8181", "api_key": "bad"}, {}, ctx)
    assert "Invalid apikey" in failure.value.message


# -- gotify and ntfy as sources -------------------------------------------------


@respx.mock
async def test_gotify_shows_messages_with_their_application(ctx: Context) -> None:
    config = {"url": "http://gotify:80", "client_token": "client"}
    respx.get("http://gotify:80/message").mock(return_value=httpx.Response(200, json={"messages": [
        {"id": 9, "appid": 1, "title": "UPS on battery", "message": "Mains gone", "priority": 8},
        {"id": 8, "appid": 2, "title": "Backup finished", "message": "42 GB", "priority": 2},
    ]}))
    respx.get("http://gotify:80/application").mock(return_value=httpx.Response(200, json=[
        {"id": 1, "name": "PeaNUT"}, {"id": 2, "name": "Borg"},
    ]))
    gotify = get_adapter("gotify")
    messages = await gotify.fetch("messages", config, {"limit": 8, "min_priority": 0}, ctx)
    assert messages.status == "bad"
    assert [item["value"] for item in messages.items] == ["PeaNUT", "Borg"]
    assert respx.calls.last.request.headers["X-Gotify-Key"] == "client"

    quiet = await gotify.fetch("messages", config, {"limit": 8, "min_priority": 4}, ctx)
    assert [item["title"] for item in quiet.items] == ["UPS on battery"]


@respx.mock
async def test_ntfy_parses_one_message_per_line(ctx: Context) -> None:
    """ntfy answers with newline-separated JSON, not with one document, and it
    mixes keep-alive events into the same stream."""
    body = (
        '{"id":"1","event":"open","topic":"haus"}\n'
        '{"id":"2","event":"message","topic":"haus","title":"Door opened","message":"Front door","priority":3,"tags":["door"]}\n'
        '{"id":"3","event":"keepalive","topic":"haus"}\n'
        '{"id":"4","event":"message","topic":"haus","title":"UPS on battery","message":"Mains gone","priority":5}\n'
    )
    respx.get("https://ntfy.sh/haus/json").mock(return_value=httpx.Response(200, text=body))
    data = await get_adapter("ntfy").fetch("messages", {"url": "https://ntfy.sh", "topic": "haus"}, {"limit": 8, "since": "12h"}, ctx)
    assert [item["title"] for item in data.items] == ["UPS on battery", "Door opened"], "newest first"
    assert data.status == "bad", "priority five is loud"
    assert data.metrics == {"messages": 2.0}


@respx.mock
async def test_ntfy_without_a_topic_says_so(ctx: Context) -> None:
    with pytest.raises(AdapterError) as failure:
        await get_adapter("ntfy").fetch("messages", {"url": "https://ntfy.sh"}, {}, ctx)
    assert failure.value.code == "missing_fields"


# -- opnsense and pfsense --------------------------------------------------------


@respx.mock
async def test_opnsense_gateways_and_system(ctx: Context) -> None:
    config = {"url": "https://opnsense.example.com", "api_key": "k", "api_secret": "s", "insecure": False}
    respx.get("https://opnsense.example.com/api/routes/gateway/status").mock(return_value=httpx.Response(200, json={"items": [
        {"name": "WAN_DHCP", "address": "203.0.113.1", "status": "down", "status_translated": "Offline", "delay": "12.4 ms", "loss": "100 %"},
        {"name": "WAN2_LTE", "address": "198.51.100.1", "status": "none", "status_translated": "Online", "delay": "48 ms", "loss": "0 %"},
    ]}))
    respx.get("https://opnsense.example.com/api/diagnostics/system/systemResources").mock(return_value=httpx.Response(200, json={
        "memory": {"used": 2_000_000_000, "total": 8_000_000_000}, "loadavg": [0.42, 0.31, 0.28], "uptime": 1_140_000,
    }))
    respx.get("https://opnsense.example.com/api/core/firmware/status").mock(return_value=httpx.Response(200, json={"updates": 3, "product_version": "26.1"}))
    opnsense = get_adapter("opnsense")

    gateways = await opnsense.fetch("gateways", config, {}, ctx)
    assert gateways.status == "bad"
    assert [item["title"] for item in gateways.items] == ["WAN_DHCP", "WAN2_LTE"]
    assert gateways.metrics == {"gateways_down": 1.0}

    system = await opnsense.fetch("system", config, {}, ctx)
    assert system.primary == {"label": "Memory", "value": 25.0, "unit": "%"}
    assert system.status == "warn", "three waiting updates are worth a colour"
    assert [entry["value"] for entry in system.secondary if entry["label"] == "Updates"] == [3]


@respx.mock
async def test_pfsense_unwraps_the_package_envelope(ctx: Context) -> None:
    config = {"url": "https://pfsense.example.com", "api_key": "k"}
    respx.get("https://pfsense.example.com/api/v2/status/system").mock(return_value=httpx.Response(200, json={
        "code": 200, "status": "ok", "data": {"cpu_usage": 7.5, "mem_usage": 31.2, "uptime": 2_400_000, "temp": 41},
    }))
    data = await get_adapter("pfsense").fetch("system", config, {}, ctx)
    assert data.primary == {"label": "CPU", "value": 7.5, "unit": "%"}
    assert data.metrics == {"cpu": 7.5, "memory": 31.2}
    assert respx.calls.last.request.headers["X-API-Key"] == "k"
