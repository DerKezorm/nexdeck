"""Adapters against recorded answers. No test here touches the network."""

from __future__ import annotations

import json
import time
from datetime import UTC
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from app.adapters import all_adapters, get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context, WidgetData

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


# -- every adapter -----------------------------------------------------------


def test_every_widget_has_demo_data() -> None:
    adapters = all_adapters()
    assert len(adapters) >= 30, "the catalogue shrank"
    seen: set[str] = set()
    checked = 0
    for adapter in adapters:
        assert adapter.kind and adapter.label and adapter.description and adapter.icon, adapter
        for widget in adapter.widgets:
            full = f"{adapter.kind}.{widget.kind}"
            assert full not in seen, f"duplicate widget kind {full}"
            seen.add(full)
            options = {f.name: f.default for f in widget.options}
            for tick in (0, 42, 900):
                data = adapter.demo(widget.kind, options, tick)
                assert isinstance(data, WidgetData)
                assert data.status in ("ok", "warn", "bad", "unknown")
                json.dumps(data.model_dump())
            checked += 1
    assert checked >= 60


def test_demo_data_moves_between_ticks() -> None:
    radarr = get_adapter("radarr")
    first = radarr.demo("queue", {"limit": 8}, 0).items[0]["progress"]
    later = radarr.demo("queue", {"limit": 8}, 300).items[0]["progress"]
    assert first != later


# -- radarr ------------------------------------------------------------------


@respx.mock
async def test_radarr_queue_status_and_calendar(ctx: Context) -> None:
    config = {"url": "http://radarr:7878", "api_key": "key"}
    respx.get("http://radarr:7878/api/v3/queue").mock(return_value=httpx.Response(200, json=fixture("radarr_queue.json")))
    respx.get("http://radarr:7878/api/v3/health").mock(return_value=httpx.Response(200, json=[{"type": "warning", "message": "Indexer unavailable"}]))
    respx.get("http://radarr:7878/api/v3/queue/status").mock(return_value=httpx.Response(200, json={"totalCount": 2}))
    respx.get("http://radarr:7878/api/v3/movie").mock(return_value=httpx.Response(200, json=[{"monitored": True, "hasFile": False}, {"monitored": True, "hasFile": True}, {"monitored": False, "hasFile": False}]))
    respx.get("http://radarr:7878/api/v3/calendar").mock(return_value=httpx.Response(200, json=[{"title": "Copper Sky", "digitalRelease": "2026-09-08T00:00:00Z", "hasFile": False}]))
    radarr = get_adapter("radarr")
    queue = await radarr.fetch("queue", config, {"limit": 8}, ctx)
    assert [i["title"] for i in queue.items] == ["Copper Sky", "Nightshift"]
    assert queue.items[0]["progress"] == 75.0
    assert queue.metrics == {"queued": 2.0}
    assert respx.calls.last.request.headers["X-Api-Key"] == "key"
    status = await radarr.fetch("status", config, {}, ctx)
    assert status.status == "warn"
    assert status.primary == {"label": "movies", "value": 3}
    assert status.metrics == {"queued": 2.0, "missing": 1.0}
    calendar = await radarr.fetch("calendar", config, {"days": 7}, ctx)
    assert calendar.items[0]["date"] == "2026-09-08"
    assert calendar.items[0]["source"] == "Radarr"


@respx.mock
async def test_radarr_rejected_key_is_an_auth_failure(ctx: Context) -> None:
    respx.get("http://radarr:7878/api/v3/queue").mock(return_value=httpx.Response(401))
    with pytest.raises(AuthFailed):
        await get_adapter("radarr").fetch("queue", {"url": "http://radarr:7878", "api_key": "bad"}, {}, ctx)


@respx.mock
async def test_unreachable_service_is_reported_readably(ctx: Context) -> None:
    respx.get("http://radarr:7878/api/v3/queue").mock(side_effect=httpx.ConnectError("boom"))
    with pytest.raises(AdapterError) as failure:
        await get_adapter("radarr").fetch("queue", {"url": "http://radarr:7878", "api_key": "k"}, {}, ctx)
    assert failure.value.code == "unreachable"


# -- sonarr ------------------------------------------------------------------


@respx.mock
async def test_sonarr_queue_titles_include_episode_codes(ctx: Context) -> None:
    respx.get("http://sonarr:8989/api/v3/queue").mock(return_value=httpx.Response(200, json={"records": [
        {"id": 1, "title": "raw.name", "series": {"title": "Harbour Lights"}, "episode": {"seasonNumber": 3, "episodeNumber": 4}, "size": 100, "sizeleft": 50, "status": "downloading", "timeleft": "00:10:00"},
    ]}))
    data = await get_adapter("sonarr").fetch("queue", {"url": "http://sonarr:8989", "api_key": "k"}, {"limit": 5}, ctx)
    assert data.items[0]["title"] == "Harbour Lights S03E04"
    assert data.items[0]["progress"] == 50.0


# -- sabnzbd -----------------------------------------------------------------


@respx.mock
async def test_sabnzbd_queue_and_pause(ctx: Context) -> None:
    config = {"url": "http://sab:8080", "api_key": "abc"}
    respx.get("http://sab:8080/api").mock(return_value=httpx.Response(200, json=fixture("sabnzbd_queue.json")))
    sab = get_adapter("sabnzbd")
    speed = await sab.fetch("speed", config, {}, ctx)
    assert speed.primary["value"] == 12.5
    assert speed.secondary[0] == {"label": "Queue", "value": 2}
    assert speed.actions[0].id == "pause"
    queue = await sab.fetch("queue", config, {"limit": 8}, ctx)
    assert queue.items[0]["title"] == "Copper.Sky.2025.2160p"
    assert queue.items[0]["progress"] == 42.0
    assert "MB" in queue.items[0]["subtitle"] or "GB" in queue.items[0]["subtitle"]
    call = respx.calls.last.request
    assert call.url.params["apikey"] == "abc" and call.url.params["mode"] == "queue"
    message = await sab.action("queue", "pause", {}, config, {}, ctx)
    assert message == "Downloads paused."
    assert respx.calls.last.request.url.params["mode"] == "pause"


@respx.mock
async def test_sabnzbd_error_payload_becomes_adapter_error(ctx: Context) -> None:
    respx.get("http://sab:8080/api").mock(return_value=httpx.Response(200, json={"status": False, "error": "API Key Incorrect"}))
    with pytest.raises(AdapterError) as failure:
        await get_adapter("sabnzbd").fetch("speed", {"url": "http://sab:8080", "api_key": "x"}, {}, ctx)
    assert "API Key Incorrect" in failure.value.message


# -- pi-hole -----------------------------------------------------------------


@respx.mock
async def test_pihole_logs_in_once_and_reuses_the_session(ctx: Context) -> None:
    config = {"url": "http://pi.hole", "password": "pw"}
    auth = respx.post("http://pi.hole/api/auth").mock(return_value=httpx.Response(200, json={"session": {"valid": True, "sid": "S1"}}))
    respx.get("http://pi.hole/api/stats/summary").mock(return_value=httpx.Response(200, json={"queries": {"total": 1000, "blocked": 250, "percent_blocked": 25.0}, "clients": {"active": 7}}))
    respx.get("http://pi.hole/api/dns/blocking").mock(return_value=httpx.Response(200, json={"blocking": "enabled"}))
    pihole = get_adapter("pihole")
    data = await pihole.fetch("summary", config, {}, ctx)
    assert data.primary["value"] == 25.0 and data.status == "ok"
    assert data.actions[0].id == "disable"
    await pihole.fetch("summary", config, {}, ctx)
    assert auth.call_count == 1, "the sid is cached per integration"
    assert respx.calls.last.request.headers["sid"] == "S1"


@respx.mock
async def test_pihole_wrong_password(ctx: Context) -> None:
    respx.post("http://pi.hole/api/auth").mock(return_value=httpx.Response(401, json={"session": {"valid": False}}))
    with pytest.raises(AuthFailed):
        await get_adapter("pihole").fetch("summary", {"url": "http://pi.hole", "password": "no"}, {}, ctx)


# -- jellyfin ----------------------------------------------------------------


@respx.mock
async def test_jellyfin_sessions_and_counts(ctx: Context) -> None:
    config = {"url": "http://jf:8096", "api_key": "tok"}
    respx.get("http://jf:8096/Sessions").mock(return_value=httpx.Response(200, json=fixture("jellyfin_sessions.json")))
    respx.get("http://jf:8096/Items/Counts").mock(return_value=httpx.Response(200, json={"MovieCount": 12, "SeriesCount": 3, "EpisodeCount": 40}))
    jellyfin = get_adapter("jellyfin")
    playing = await jellyfin.fetch("nowplaying", config, {"limit": 6}, ctx)
    assert len(playing.items) == 1, "sessions without an item are not streams"
    stream = playing.items[0]
    assert stream["title"] == "Harbour Lights S03E04"
    assert stream["progress"] == 50.0
    assert stream["state"] == "paused"
    assert "Transcode" in stream["subtitle"]
    assert 'MediaBrowser Token="tok"' in respx.calls.last.request.headers["Authorization"]
    library = await jellyfin.fetch("library", config, {}, ctx)
    assert library.primary == {"label": "Movies", "value": 12}


# -- docker ------------------------------------------------------------------


async def test_docker_containers_stats_and_actions(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.adapters import docker as docker_module

    containers = fixture("docker_containers.json")
    posted: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/containers/json":
            return httpx.Response(200, json=containers)
        if path.endswith("/stats"):
            return httpx.Response(200, json=fixture("docker_stats.json"))
        if path == "/version":
            return httpx.Response(200, json={"Version": "27.1.0", "Os": "linux", "Arch": "amd64"})
        if request.method == "POST":
            posted.append(path)
            return httpx.Response(204)
        return httpx.Response(404)

    monkeypatch.setattr(docker_module, "docker_client", lambda config: httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://docker"))
    ctx = Context(httpx.AsyncClient(), integration_id=1, cache={})
    docker = get_adapter("docker")
    assert "27.1.0" in await docker.test({"host": "unix:///var/run/docker.sock"}, ctx)
    data = await docker.fetch("containers", {"host": "unix:///var/run/docker.sock"}, {"stats": True, "show_stopped": True}, ctx)
    assert [i["title"] for i in data.items] == ["radarr", "sabnzbd"]
    running = data.items[0]
    assert running["status"] == "ok" and running["cpu"] == 10.0
    assert running["actions"][0]["id"] == "restart"
    stopped = data.items[1]
    assert stopped["status"] == "bad" and stopped["actions"][0]["id"] == "start"
    assert data.metrics == {"running": 1.0}
    summary = await docker.fetch("summary", {"host": "unix:///var/run/docker.sock"}, {}, ctx)
    assert summary.primary["value"] == 1 and summary.status == "warn"
    message = await docker.action("containers", "restart", {"id": "abc123"}, {"host": "unix:///var/run/docker.sock"}, {}, ctx)
    assert "restart" in message
    assert posted == ["/containers/abc123/restart"]
    with pytest.raises(AdapterError):
        await docker.action("containers", "explode", {"id": "abc123"}, {"host": "unix:///var/run/docker.sock"}, {}, ctx)


def test_docker_cpu_percent_formula() -> None:
    from app.adapters.docker import cpu_percent, memory_used

    stats = fixture("docker_stats.json")
    assert cpu_percent(stats) == 10.0
    used, limit = memory_used(stats)
    assert used == 100 * 1024 * 1024 - 10 * 1024 * 1024
    assert limit == 4 * 1024 ** 3


# -- json api ----------------------------------------------------------------


@respx.mock
async def test_json_api_value_with_thresholds(ctx: Context) -> None:
    respx.get("http://svc/api/status").mock(return_value=httpx.Response(200, json={"data": {"temperature": "31.4", "items": [{"name": "a", "n": 1}, {"name": "b", "n": 2}]}}))
    api = get_adapter("jsonapi")
    config = {"url": "http://svc/api", "token": "t"}
    value = await api.fetch("value", config, {"path": "/status", "value_path": "data.temperature", "unit": "°C", "decimals": 1, "warn_above": 30}, ctx)
    assert value.primary["value"] == 31.4 and value.status == "warn"
    assert respx.calls.last.request.headers["Authorization"] == "Bearer t"
    listed = await api.fetch("list", config, {"path": "/status", "items_path": "data.items", "title_path": "name", "value_path": "n"}, ctx)
    assert [i["title"] for i in listed.items] == ["a", "b"]
    with pytest.raises(AdapterError) as failure:
        await api.fetch("value", config, {"path": "/status", "value_path": "data.missing"}, ctx)
    assert failure.value.code == "path_error"


# -- uptime kuma -------------------------------------------------------------


@respx.mock
async def test_uptime_kuma_parses_prometheus_metrics(ctx: Context) -> None:
    text = (FIXTURES / "uptimekuma_metrics.txt").read_text(encoding="utf-8")
    respx.get("http://kuma:3001/metrics").mock(return_value=httpx.Response(200, text=text))
    kuma = get_adapter("uptimekuma")
    data = await kuma.fetch("monitors", {"url": "http://kuma:3001", "api_key": "uk1_x"}, {"limit": 12}, ctx)
    assert data.status == "bad"
    assert data.items[0]["title"] == "SABnzbd" and data.items[0]["status"] == "bad"
    assert data.items[1]["value"] == "18 ms"
    assert data.metrics == {"down": 1.0}
    assert respx.calls.last.request.headers["Authorization"].startswith("Basic ")


# -- weather -----------------------------------------------------------------


@respx.mock
async def test_weather_maps_codes_and_days(ctx: Context) -> None:
    respx.get("https://api.open-meteo.com/v1/forecast").mock(return_value=httpx.Response(200, json=fixture("open_meteo.json")))
    data = await get_adapter("weather").fetch("current", {}, {"latitude": 52.5, "longitude": 13.4, "place": "Berlin", "days": 3}, ctx)
    assert data.primary == {"label": "Berlin", "value": 21.4, "unit": "°C"}
    assert data.meta["condition"] == "partly-cloudy"
    assert [d["condition"] for d in data.items] == ["clear", "rain", "snow"]
    with pytest.raises(AdapterError) as failure:
        await get_adapter("weather").fetch("current", {}, {}, ctx)
    assert failure.value.code == "missing_location"


@respx.mock
async def test_weather_looks_up_a_place_name(ctx: Context) -> None:
    """A town is enough: the geocoder supplies the coordinates, once a day."""
    geocoder = respx.get("https://geocoding-api.open-meteo.com/v1/search").mock(return_value=httpx.Response(200, json={"results": [{"name": "Aachen", "latitude": 50.7762, "longitude": 6.0838}]}))
    forecast = respx.get("https://api.open-meteo.com/v1/forecast").mock(return_value=httpx.Response(200, json=fixture("open_meteo.json")))
    data = await get_adapter("weather").fetch("current", {}, {"place": "Aachen", "days": 3}, ctx)
    assert data.primary["label"] == "Aachen"
    assert geocoder.calls.last.request.url.params["name"] == "Aachen"
    assert forecast.calls.last.request.url.params["latitude"] == "50.7762"
    # The second fetch reuses the cached coordinates instead of asking again.
    await get_adapter("weather").fetch("current", {}, {"place": "Aachen", "days": 3}, ctx)
    assert geocoder.call_count == 1
    # Coordinates win over the place name when both are set.
    await get_adapter("weather").fetch("current", {}, {"place": "Aachen", "latitude": 52.5, "longitude": 13.4}, ctx)
    assert forecast.calls.last.request.url.params["latitude"] == "52.5"
    assert geocoder.call_count == 1


@respx.mock
async def test_weather_unknown_place_is_a_readable_error(ctx: Context) -> None:
    respx.get("https://geocoding-api.open-meteo.com/v1/search").mock(return_value=httpx.Response(200, json={"generationtime_ms": 0.4}))
    with pytest.raises(AdapterError) as failure:
        await get_adapter("weather").fetch("current", {}, {"place": "Nowhere-at-all"}, ctx)
    assert failure.value.code == "place_not_found"
    assert "Nowhere-at-all" in failure.value.message


# -- home assistant ----------------------------------------------------------


@respx.mock
async def test_home_assistant_entity_and_toggle(ctx: Context) -> None:
    config = {"url": "http://ha:8123", "token": "llat"}
    respx.get("http://ha:8123/api/states/light.kitchen").mock(return_value=httpx.Response(200, json={"entity_id": "light.kitchen", "state": "on", "attributes": {"friendly_name": "Kitchen"}, "last_changed": "2026-09-05T10:11:12+00:00"}))
    call = respx.post("http://ha:8123/api/services/light/turn_off").mock(return_value=httpx.Response(200, json=[]))
    ha = get_adapter("homeassistant")
    data = await ha.fetch("entity", config, {"entity_id": "light.kitchen"}, ctx)
    assert data.primary["value"] == "on" and data.actions[0].id == "light.turn_off"
    assert respx.calls.last.request.headers["Authorization"] == "Bearer llat"
    await ha.action("entity", "light.turn_off", {"entity_id": "light.kitchen"}, config, {}, ctx)
    assert call.called
    # Live states from the WebSocket listener win over REST.
    ctx.cache["hass_states"] = {"sensor.temp": {"entity_id": "sensor.temp", "state": "21.5", "attributes": {"unit_of_measurement": "°C", "friendly_name": "Temp"}}}
    live = await ha.fetch("entity", config, {"entity_id": "sensor.temp"}, ctx)
    assert live.primary == {"label": "Temp", "value": 21.5, "unit": "°C"}
    assert live.metrics == {"value": 21.5}


# -- unifi -------------------------------------------------------------------

UNIFI = "https://udm"
UNIFI_API = f"{UNIFI}/proxy/network/integration/v1"
SITE = "88f7af54-98f8-306a-a1c7-c9349722b1f6"


def _unifi_integration_routes() -> None:
    respx.get(f"{UNIFI_API}/info").mock(return_value=httpx.Response(200, json={"applicationVersion": "9.1.120"}))
    respx.get(f"{UNIFI_API}/sites").mock(return_value=httpx.Response(200, json={"offset": 0, "limit": 200, "count": 1, "totalCount": 1, "data": [{"id": SITE, "internalReference": "default", "name": "Home"}]}))
    respx.get(f"{UNIFI_API}/sites/{SITE}/devices").mock(return_value=httpx.Response(200, json={"offset": 0, "limit": 200, "count": 3, "totalCount": 3, "data": [
        {"id": "gw", "name": "Dream Machine", "model": "UniFi Dream Machine PRO SE", "state": "ONLINE", "ipAddress": "192.168.1.1", "features": ["switching"]},
        {"id": "ap1", "name": "Living room", "model": "U6-Pro", "state": "ONLINE", "ipAddress": "192.168.1.20", "features": ["accessPoint"], "firmwareUpdatable": True},
        {"id": "sw1", "name": "Garage", "model": "USW-Flex", "state": "OFFLINE", "ipAddress": "192.168.1.30", "features": ["switching"]},
    ]}))
    respx.get(f"{UNIFI_API}/sites/{SITE}/devices/gw/statistics/latest").mock(return_value=httpx.Response(200, json={"uptimeSec": 86400, "cpuUtilizationPct": 12.4, "memoryUtilizationPct": 41.0, "uplink": {"txRateBps": 8_000_000, "rxRateBps": 80_000_000}}))
    respx.get(f"{UNIFI_API}/sites/{SITE}/devices/ap1/statistics/latest").mock(return_value=httpx.Response(200, json={"uptimeSec": 3600, "cpuUtilizationPct": 33.7, "memoryUtilizationPct": 50.0}))
    respx.get(f"{UNIFI_API}/sites/{SITE}/devices/sw1/statistics/latest").mock(return_value=httpx.Response(404, json={"statusCode": 404}))
    respx.get(f"{UNIFI_API}/sites/{SITE}/clients").mock(return_value=httpx.Response(200, json={"offset": 0, "limit": 200, "count": 3, "totalCount": 3, "data": [
        {"id": "c1", "name": "phone", "type": "WIRELESS", "ipAddress": "192.168.1.101"},
        {"id": "c2", "name": "laptop", "type": "WIRELESS", "ipAddress": "192.168.1.102"},
        {"id": "c3", "name": "nas", "type": "WIRED", "ipAddress": "192.168.1.10"},
    ]}))


@respx.mock
async def test_unifi_api_key_summary_and_devices(ctx: Context) -> None:
    """The Integration API path: key in the header, WAN from the gateway's uplink, clients counted from the console's total."""
    _unifi_integration_routes()
    config = {"url": UNIFI, "api_key": "nd-key", "site": "default", "unifi_os": True, "insecure": True}
    adapter = get_adapter("unifi")
    assert (await adapter.test(config, ctx)) == "UniFi Network 9.1.120 answers, site 'default' found."
    summary = await adapter.fetch("summary", config, {}, ctx)
    assert summary.primary == {"label": "Clients", "value": 3}
    assert summary.status == "warn", "one switch is offline"
    chips = {chip["label"]: chip["value"] for chip in summary.secondary}
    assert chips["Wi-Fi"] == 2 and chips["Devices"] == "2 / 3"
    assert chips["WAN down"] == "80.0 Mbit/s" and chips["WAN up"] == "8.0 Mbit/s", "shown in bits, as UniFi shows them"
    assert summary.metrics["wan_down"] == 80.0
    assert summary.metrics["clients"] == 3.0
    assert summary.meta["status_reason"] == "1 device(s) offline"
    devices = await adapter.fetch("devices", config, {}, ctx)
    assert [item["title"] for item in devices.items] == ["Dream Machine", "Garage", "Living room"], "gateway first, then whatever is offline, then the rest"
    assert devices.items[0]["subtitle"] == "Gateway · UniFi Dream Machine PRO SE · 192.168.1.1" and devices.items[0]["value"] == "12% cpu"
    assert devices.items[1]["status"] == "bad" and devices.items[1]["value"] == ""
    assert devices.status == "warn", "the same rule as the summary: yellow while the gateway answers"
    assert devices.meta["status_reason"] == "1 device(s) offline"
    findings = await adapter.fetch("findings", config, {}, ctx)
    assert findings.status == "warn"
    assert [(item["title"], item["status"], item["subtitle"]) for item in findings.items] == [
        ("Garage", "warn", "Switch · USW-Flex · offline"),
        ("Living room", "unknown", "Access point · U6-Pro · firmware update available"),
    ]
    assert findings.meta["empty"] == "UniFi answers · 3 devices online · 3 clients"
    console = await adapter.fetch("console", config, {}, ctx)
    rows = {item["title"]: item for item in console.items}
    assert rows["Dream Machine"]["subtitle"] == "UniFi Dream Machine PRO SE · 192.168.1.1" and rows["Dream Machine"]["value"] == "24h"
    assert rows["Network application"]["subtitle"] == "9.1.120"
    assert rows["Devices"]["subtitle"] == "1 gateway · 1 switch · 1 access point" and rows["Devices"]["value"] == "2 / 3"
    assert rows["Firmware"]["subtitle"] == "1 update(s) available" and rows["Firmware"]["status"] == "unknown"
    assert rows["Clients"]["subtitle"] == "2 wireless · 1 wired" and rows["Clients"]["value"] == "3"
    assert rows["WAN"]["subtitle"] == "↓ 80.0 Mbit/s · ↑ 8.0 Mbit/s"
    assert console.metrics == {"wan_down": 80.0, "wan_up": 8.0}
    sent = respx.calls.last.request
    assert sent.headers["x-api-key"] == "nd-key"
    # The site list and the device list were fetched once each, not once per widget.
    assert respx.get(f"{UNIFI_API}/sites").call_count == 1
    assert respx.get(f"{UNIFI_API}/sites/{SITE}/devices").call_count == 1


@respx.mock
async def test_unifi_api_key_errors_are_readable(ctx: Context) -> None:
    respx.get(f"{UNIFI_API}/info").mock(return_value=httpx.Response(401, json={"statusCode": 401}))
    adapter = get_adapter("unifi")
    with pytest.raises(AuthFailed):
        await adapter.test({"url": UNIFI, "api_key": "wrong"}, ctx)
    respx.get(f"{UNIFI_API}/info").mock(return_value=httpx.Response(404, text="not found"))
    with pytest.raises(AdapterError) as failure:
        await adapter.test({"url": UNIFI, "api_key": "nd-key"}, ctx)
    assert failure.value.code == "no_integration_api"
    with pytest.raises(AdapterError) as missing:
        await adapter.fetch("summary", {"url": UNIFI}, {}, ctx)
    assert missing.value.code == "missing_credentials"
    respx.get(f"{UNIFI_API}/sites").mock(return_value=httpx.Response(200, json={"totalCount": 1, "data": [{"id": SITE, "internalReference": "default", "name": "Home"}]}))
    with pytest.raises(AdapterError) as site:
        await adapter.fetch("summary", {"url": UNIFI, "api_key": "nd-key", "site": "garage"}, {}, ctx)
    assert site.value.code == "site_not_found" and "default" in site.value.message


@respx.mock
async def test_unifi_local_account_logs_in_and_reads_the_classic_api(ctx: Context) -> None:
    """Without a key the old way still works: cookie login, then the classic endpoints."""
    respx.post(f"{UNIFI}/api/auth/login").mock(return_value=httpx.Response(200, json={}, headers={"x-csrf-token": "csrf-1"}))
    calls = {"health": 0}

    def health(request: httpx.Request) -> httpx.Response:
        calls["health"] += 1
        if calls["health"] == 1:
            return httpx.Response(401, json={})
        assert request.headers["x-csrf-token"] == "csrf-1"
        return httpx.Response(200, json={"data": [{"subsystem": "wan", "status": "ok", "rx_bytes-r": 1048576, "tx_bytes-r": 524288}, {"subsystem": "wlan", "num_user": 5}]})

    respx.get(f"{UNIFI}/proxy/network/api/s/default/stat/health").mock(side_effect=health)
    respx.get(f"{UNIFI}/proxy/network/api/s/default/stat/device").mock(return_value=httpx.Response(200, json={"data": [{"name": "AP", "type": "uap", "model": "U6", "state": 1, "num_sta": 5}]}))
    respx.get(f"{UNIFI}/proxy/network/api/s/default/stat/sta").mock(return_value=httpx.Response(200, json={"data": [{}, {}, {}, {}, {}, {}, {}]}))
    config = {"url": UNIFI, "username": "nexdeck", "password": "secret", "site": "default", "unifi_os": True, "insecure": True}
    summary = await get_adapter("unifi").fetch("summary", config, {}, ctx)
    assert summary.primary == {"label": "Clients", "value": 7}
    assert {chip["label"]: chip["value"] for chip in summary.secondary}["WAN down"] == "8.4 Mbit/s", "the classic API counts bytes"
    assert calls["health"] == 2, "a 401 triggers one login and one retry"


@respx.mock
async def test_unifi_follows_the_http_to_https_redirect_and_names_html_answers(ctx: Context) -> None:
    """A Dream Machine answers http with a redirect to https; a page instead of data gets a hint, not a JSON error."""
    respx.get("http://udm/proxy/network/integration/v1/info").mock(return_value=httpx.Response(302, headers={"location": "https://udm/proxy/network/integration/v1/info"}))
    respx.get("https://udm/proxy/network/integration/v1/info").mock(return_value=httpx.Response(200, json={"applicationVersion": "9.1.120"}))
    respx.get("http://udm/proxy/network/integration/v1/sites").mock(return_value=httpx.Response(302, headers={"location": "https://udm/proxy/network/integration/v1/sites"}))
    respx.get("https://udm/proxy/network/integration/v1/sites").mock(return_value=httpx.Response(200, json={"totalCount": 1, "data": [{"id": SITE, "internalReference": "default", "name": "Home"}]}))
    adapter = get_adapter("unifi")
    assert "9.1.120" in await adapter.test({"url": "http://udm", "api_key": "nd-key"}, ctx)
    respx.get("https://udm/proxy/network/integration/v1/info").mock(return_value=httpx.Response(200, text="<html>login</html>", headers={"content-type": "text/html"}))
    with pytest.raises(AdapterError) as failure:
        await adapter.test({"url": "https://udm", "api_key": "nd-key"}, Context(httpx.AsyncClient(), integration_id=2, widget_id=2, cache={}))
    assert failure.value.code == "not_json" and "https://" in failure.value.hint


@respx.mock
async def test_unifi_findings_are_calm_when_everything_runs(ctx: Context) -> None:
    respx.get(f"{UNIFI_API}/sites").mock(return_value=httpx.Response(200, json={"totalCount": 1, "data": [{"id": SITE, "internalReference": "default", "name": "Home"}]}))
    respx.get(f"{UNIFI_API}/sites/{SITE}/devices").mock(return_value=httpx.Response(200, json={"totalCount": 2, "data": [
        {"id": "gw", "name": "Dream Machine", "model": "UDM-SE", "state": "ONLINE", "features": ["switching"]},
        {"id": "ap1", "name": "Living room", "model": "U6-Pro", "state": "ONLINE", "features": ["accessPoint"]},
    ]}))
    respx.get(f"{UNIFI_API}/sites/{SITE}/devices/gw/statistics/latest").mock(return_value=httpx.Response(200, json={"uptimeSec": 120, "cpuUtilizationPct": 95.0, "memoryUtilizationPct": 40.0, "uplink": {"txRateBps": 1, "rxRateBps": 1}}))
    respx.get(f"{UNIFI_API}/sites/{SITE}/clients").mock(return_value=httpx.Response(200, json={"totalCount": 41, "data": []}))
    findings = await get_adapter("unifi").fetch("findings", {"url": UNIFI, "api_key": "nd-key"}, {}, ctx)
    # A strained, freshly restarted gateway is worth two rows; nothing is offline, so the card stays green.
    assert findings.status == "ok"
    assert [(item["subtitle"], item["status"]) for item in findings.items] == [("CPU 95%", "warn"), ("restarted 2 min ago", "unknown")]
    calm_ctx = Context(httpx.AsyncClient(), integration_id=3, widget_id=3, cache={})
    respx.get(f"{UNIFI_API}/sites/{SITE}/devices/gw/statistics/latest").mock(return_value=httpx.Response(200, json={"uptimeSec": 86400, "cpuUtilizationPct": 12.0, "memoryUtilizationPct": 40.0}))
    calm = await get_adapter("unifi").fetch("findings", {"url": UNIFI, "api_key": "nd-key"}, {}, calm_ctx)
    assert calm.items == [] and calm.meta["empty"] == "UniFi answers · 2 devices online · 41 clients"


@respx.mock
async def test_unifi_wlans_describe_each_network(ctx: Context) -> None:
    respx.get(f"{UNIFI_API}/sites").mock(return_value=httpx.Response(200, json={"totalCount": 1, "data": [{"id": SITE, "internalReference": "default", "name": "Home"}]}))
    respx.get(f"{UNIFI_API}/sites/{SITE}/networks").mock(return_value=httpx.Response(200, json={"totalCount": 2, "data": [
        {"id": "n1", "name": "Default", "vlanId": 1, "enabled": True, "default": True},
        {"id": "n2", "name": "Guests", "vlanId": 80, "enabled": True, "default": False},
    ]}))
    respx.get(f"{UNIFI_API}/sites/{SITE}/wifi/broadcasts").mock(return_value=httpx.Response(200, json={"totalCount": 3, "data": [
        {"type": "STANDARD", "id": "w1", "name": "Home", "enabled": True, "network": {"type": "NATIVE"}, "securityConfiguration": {"type": "WPA2_WPA3_PERSONAL"}, "broadcastingFrequenciesGHz": [2.4, 5]},
        {"type": "STANDARD", "id": "w2", "name": "Guests", "enabled": True, "network": {"type": "SPECIFIC", "networkId": "n2"}, "securityConfiguration": {"type": "OPEN"}, "broadcastingDeviceFilter": {"type": "DEVICES", "deviceIds": ["a", "b", "c"]}, "broadcastingFrequenciesGHz": [2.4, 5], "hotspotConfiguration": {}},
        {"type": "IOT_OPTIMIZED", "id": "w3", "name": "Things", "enabled": False, "network": {"type": "NATIVE"}, "securityConfiguration": {"type": "WPA2_PERSONAL"}, "broadcastingDeviceFilter": {"type": "DEVICES", "deviceIds": ["a"]}},
    ]}))
    data = await get_adapter("unifi").fetch("wifi", {"url": UNIFI, "api_key": "nd-key"}, {}, ctx)
    assert data.status == "ok"
    assert [(item["title"], item["subtitle"], item["status"]) for item in data.items] == [
        ("Guests", "Guests (VLAN 80) · open · 2.4 + 5 GHz · guest portal · on 3 access points", "ok"),
        ("Home", "Default (VLAN 1) · WPA2/WPA3 · 2.4 + 5 GHz · all access points", "ok"),
        ("Things", "Default (VLAN 1) · WPA2 · IoT · on 1 access point · off", "unknown"),
    ], "enabled first, then by name; switched-off WLANs go last and grey"


@respx.mock
async def test_unifi_wlans_over_the_classic_api(ctx: Context) -> None:
    respx.post(f"{UNIFI}/api/auth/login").mock(return_value=httpx.Response(200, json={}, headers={"x-csrf-token": "c"}))
    respx.get(f"{UNIFI}/proxy/network/api/s/default/rest/wlanconf").mock(return_value=httpx.Response(200, json={"data": [
        {"name": "Home", "enabled": True, "security": "wpapsk", "wpa3_support": True, "wlan_bands": ["2g", "5g"], "networkconf_id": "n1"},
        {"name": "Guests", "enabled": True, "security": "open", "is_guest": True, "wlan_bands": ["5g"], "networkconf_id": "n2"},
    ]}))
    respx.get(f"{UNIFI}/proxy/network/api/s/default/rest/networkconf").mock(return_value=httpx.Response(200, json={"data": [{"_id": "n1", "name": "Default", "vlan": 1}, {"_id": "n2", "name": "Guests", "vlan": 80}]}))
    data = await get_adapter("unifi").fetch("wifi", {"url": UNIFI, "username": "u", "password": "p"}, {}, ctx)
    assert [item["subtitle"] for item in data.items] == [
        "Guests (VLAN 80) · open · 5 GHz · guest portal · all access points",
        "Default (VLAN 1) · WPA2/WPA3 · 2.4 + 5 GHz · all access points",
    ]


# -- synology containers -------------------------------------------------------

NAS = "https://nas.example.com:5001"


def _dsm(handler):
    """One DSM entry point, many APIs: the handler picks by api and method."""
    respx.get(f"{NAS}/webapi/auth.cgi").mock(return_value=httpx.Response(200, json={"success": True, "data": {"sid": "sid-1"}}))

    def route(request: httpx.Request) -> httpx.Response:
        params = request.url.params
        return httpx.Response(200, json=handler(params.get("api"), params.get("method"), params))

    respx.get(f"{NAS}/webapi/entry.cgi").mock(side_effect=route)


@respx.mock
async def test_synology_containers_with_load_and_actions(ctx: Context) -> None:
    seen: list[tuple[str, str, str]] = []

    def handler(api: str, method: str, params) -> dict:
        seen.append((api, method, params.get("name", "")))
        if api == "SYNO.Docker.Container" and method == "list":
            assert params.get("type") == "all" and params.get("limit") == "-1"
            return {"success": True, "data": {"total": 3, "containers": [
                {"id": "c1", "name": "nexview", "image": "ghcr.io/derkezorm/nexview:latest", "status": "running", "up_status": "Up 3 days (healthy)"},
                {"id": "c2", "name": "paperless", "image": "paperless-ngx", "status": "running", "up_status": "Up 6 hours (unhealthy)"},
                {"id": "c3", "name": "backup", "image": "restic/restic", "status": "stopped", "up_status": "Exited (0) 5 months ago"},
            ]}}
        if api == "SYNO.Docker.Container.Resource" and method == "get":
            return {"success": True, "data": {"resources": [{"name": "nexview", "cpu": 1.24, "memory": 210632704, "memoryPercent": 0.31}, {"name": "paperless", "cpu": 3.8, "memory": 1200000000, "memoryPercent": 12.06}]}}
        if api == "SYNO.Docker.Container" and method in ("start", "stop", "restart"):
            return {"success": True, "data": {}}
        return {"success": False, "error": {"code": 101}}

    _dsm(handler)
    config = {"url": NAS, "username": "nexdeck", "password": "secret", "insecure": True}
    adapter = get_adapter("synology")
    data = await adapter.fetch("containers", config, {}, ctx)
    assert data.status == "warn", "one container is unhealthy"
    assert [item["title"] for item in data.items] == ["nexview", "paperless", "backup"], "running first, then by name"
    assert data.items[0]["subtitle"] == "ghcr.io/derkezorm/nexview:latest · Up 3 days" and data.items[0]["cpu"] == 1.2 and data.items[0]["memory_percent"] == 0.3 and data.items[0]["value"] == "200.9 MB"
    assert data.items[1]["subtitle"] == "paperless-ngx · Up 6 hours · unhealthy" and data.items[1]["status"] == "warn"
    assert data.items[2]["status"] == "unknown" and "cpu" not in data.items[2] and [a.id for a in data.items[2]["actions"]] == ["start"]
    assert [a.id for a in data.items[0]["actions"]] == ["stop", "restart"] and all(a.confirm for a in data.items[0]["actions"])
    assert {chip["label"]: chip["value"] for chip in data.secondary} == {"Running": 2, "Stopped": 1}
    assert data.metrics == {"running": 2.0}
    filtered = await adapter.fetch("containers", config, {"filter": "pap", "show_stopped": False}, ctx)
    assert [item["title"] for item in filtered.items] == ["paperless"]
    # The card sends back exactly the params the action carried; nothing else names the container.
    restart = next(a for a in data.items[1]["actions"] if a.id == "restart")
    message = await adapter.action("containers", "restart", restart.params, config, {}, ctx)
    assert message == "paperless: restart requested."
    with pytest.raises(AdapterError) as nameless:
        await adapter.action("containers", "restart", {}, config, {}, ctx)
    assert nameless.value.code == "bad_params"
    assert ("SYNO.Docker.Container", "restart", "paperless") in seen
    with pytest.raises(AdapterError) as failure:
        await adapter.action("containers", "explode", {"id": "paperless"}, config, {}, ctx)
    assert failure.value.code == "no_such_action"


@respx.mock
async def test_synology_virtual_machines_with_usage_and_actions(ctx: Context) -> None:
    seen: list[tuple[str, str, str]] = []

    def handler(api: str, method: str, params) -> dict:
        seen.append((api, method, params.get("guest_id", "")))
        if api == "SYNO.Virtualization.Guest" and method == "list":
            assert params.get("version") == "2"
            return {"success": True, "data": {"guests": [
                {"guest_id": "g1", "name": "Home Assistant", "status": "running", "status_type": "healthy", "host_name": "storage-nas", "vcpu_num": 2, "vram_size": 4194304, "ip": "192.168.1.40"},
                {"guest_id": "g2", "name": "Lab", "status": "shutdown", "status_type": "", "host_name": "storage-nas", "vcpu_num": 1, "vram_size": 2097152, "ip": ""},
                {"guest_id": "g3", "name": "Small", "status": "running", "status_type": "healthy", "host_name": "storage-nas", "vcpu_num": 1, "vram_size": 1048576, "ip": ""},
            ]}}
        if api == "SYNO.Virtualization.Guest" and method == "get":
            if params.get("guest_id") == "g3":
                # The hypervisor reports more than the configured size: overhead, shown as full.
                return {"success": True, "data": {"guest_id": "g3", "vcpu_usage": 2, "ram_used": 1177600}}
            return {"success": True, "data": {"guest_id": params.get("guest_id"), "vcpu_usage": 12, "ram_used": 2621440}}
        if api == "SYNO.Virtualization.API.Guest.Action":
            return {"success": True, "data": {}}
        return {"success": False, "error": {"code": 103}}

    _dsm(handler)
    config = {"url": NAS, "username": "nexdeck", "password": "secret", "insecure": True}
    adapter = get_adapter("synology")
    data = await adapter.fetch("vms", config, {}, ctx)
    assert data.status == "ok"
    assert [item["title"] for item in data.items] == ["Home Assistant", "Small", "Lab"], "running first, then by name"
    assert data.items[1]["memory_percent"] == 100.0 and data.items[1]["value"] == "1.1 GB"
    first = data.items[0]
    assert first["subtitle"] == "storage-nas · 2 vCPU · 4.0 GB RAM · 192.168.1.40"
    assert first["cpu"] == 12.0 and first["memory_percent"] == 62.5 and first["value"] == "2.5 GB"
    assert [a.id for a in first["actions"]] == ["shutdown", "reboot"] and first["actions"][0].params == {"guest_id": "g1"}
    assert data.items[2]["subtitle"] == "storage-nas · 1 vCPU · 2.0 GB RAM · shutdown" and data.items[2]["status"] == "unknown"
    assert [a.id for a in data.items[2]["actions"]] == ["poweron"] and "cpu" not in data.items[2]
    assert ("SYNO.Virtualization.Guest", "get", "g2") not in seen, "no detail call for a guest that is off"
    assert {chip["label"]: chip["value"] for chip in data.secondary} == {"Running": 2, "Stopped": 1}
    assert await adapter.action("vms", "reboot", first["actions"][1].params, config, {}, ctx) == "Virtual machine: reboot requested."
    assert ("SYNO.Virtualization.API.Guest.Action", "reboot", "g1") in seen
    with pytest.raises(AdapterError) as failure:
        await adapter.action("vms", "poweron", {}, config, {}, ctx)
    assert failure.value.code == "bad_params"


@respx.mock
async def test_synology_unknown_method_is_named(ctx: Context) -> None:
    _dsm(lambda api, method, params: {"success": False, "error": {"code": 103}})
    with pytest.raises(AdapterError) as failure:
        await get_adapter("synology").fetch("vms", {"url": NAS, "username": "u", "password": "p"}, {}, ctx)
    assert "the method does not exist on this DSM" in failure.value.message


# -- plex ----------------------------------------------------------------------

PLEX = "http://plex:32400"


@respx.mock
async def test_plex_recently_added_merges_sections_newest_first(ctx: Context) -> None:
    respx.get(f"{PLEX}/library/sections").mock(return_value=httpx.Response(200, json={"MediaContainer": {"Directory": [
        {"key": "1", "type": "movie", "title": "Movies"}, {"key": "2", "type": "show", "title": "Series"}, {"key": "3", "type": "artist", "title": "Music"}, {"key": "4", "type": "photo", "title": "Photos"},
    ]}}))
    respx.get(f"{PLEX}/library/sections/1/recentlyAdded").mock(return_value=httpx.Response(200, json={"MediaContainer": {"Metadata": [
        {"type": "movie", "title": "Orbital", "year": 2025, "thumb": "/library/metadata/10/thumb/1", "addedAt": 200},
    ]}}))
    respx.get(f"{PLEX}/library/sections/2/recentlyAdded").mock(return_value=httpx.Response(200, json={"MediaContainer": {"Metadata": [
        {"type": "season", "title": "Season 3", "parentTitle": "Harbour Lights", "thumb": "/library/metadata/20/thumb/1", "addedAt": 300},
        {"type": "episode", "title": "Landfall", "grandparentTitle": "Harbour Lights", "parentIndex": 3, "index": 4, "grandparentThumb": "/library/metadata/21/thumb/1", "addedAt": 100},
    ]}}))
    respx.get(f"{PLEX}/library/sections/3/recentlyAdded").mock(return_value=httpx.Response(200, json={"MediaContainer": {"Metadata": [
        {"type": "album", "title": "Aurora Fields", "parentTitle": "Northern Sky", "thumb": "/library/metadata/30/thumb/1", "addedAt": 250},
    ]}}))
    config = {"url": PLEX, "token": "tok"}
    data = await get_adapter("plex").fetch("recent", config, {"kind": "all", "limit": 8}, ctx)
    assert [(item["title"], item["subtitle"]) for item in data.items] == [("Harbour Lights", "Season 3"), ("Aurora Fields", "Northern Sky"), ("Orbital", "2025"), ("Harbour Lights", "S03E04 · Landfall")], "newest first across sections, photos skipped; an album shows its title over the artist"
    assert data.items[0]["art"] == "proxy:/library/metadata/20/thumb/1", "the browser gets a path, never the token"
    movies = await get_adapter("plex").fetch("recent", config, {"kind": "movies", "limit": 8}, ctx)
    assert [item["title"] for item in movies.items] == ["Orbital"]
    sent = respx.get(f"{PLEX}/library/sections/1/recentlyAdded").calls.last.request
    assert sent.headers["X-Plex-Token"] == "tok" and sent.url.params["X-Plex-Container-Size"] == "8"
    assert get_adapter("plex").demo("recent", {"kind": "music", "limit": 8}, 0).items == [{"title": "Aurora Fields", "subtitle": "Northern Sky", "art": "", "kind": "album"}]


def test_media_library_card_has_three_forms() -> None:
    plex = get_adapter("plex")
    number = plex.demo("library", {}, 0)
    assert number.primary["label"] == "Movies" and [chip["label"] for chip in number.secondary] == ["Series", "Artists", "Playing"]
    assert number.metrics == {}, "the streams line has no business under a library count"
    movies = plex.demo("library", {"show": "movies"}, 0)
    assert movies.primary == {"label": "Movies", "value": 1284} and [chip["label"] for chip in movies.secondary] == ["Playing"]
    music = plex.demo("library", {"show": "music"}, 0)
    assert music.primary["label"] == "Artists"
    icons = plex.demo("library", {"style": "icons"}, 0)
    assert icons.meta["renderer"] == "counters"
    assert [(item["label"], item["icon"]) for item in icons.items] == [("Movies", "lucide:film"), ("Series", "lucide:tv"), ("Artists", "lucide:speaker"), ("Playing", "lucide:play")]
    single_with_icons = plex.demo("library", {"show": "series", "style": "icons"}, 0)
    assert "renderer" not in single_with_icons.meta, "the style only applies when everything is shown"


def _plex_server_routes(*, release: bool = False, mapping: str = "mapped", refreshing: bool = False, host_cpu: float = 20.6, process_cpu: float = 0.05, transcodes: int = 0) -> None:
    import time

    now = int(time.time())
    respx.get(f"{PLEX}/").mock(return_value=httpx.Response(200, json={"MediaContainer": {"version": "1.42.0.9000", "friendlyName": "nas", "myPlexMappingState": mapping, "transcoderActiveVideoSessions": transcodes}}))
    respx.get(f"{PLEX}/library/sections").mock(return_value=httpx.Response(200, json={"MediaContainer": {"Directory": [
        {"key": "1", "type": "movie", "title": "Movies", "refreshing": refreshing, "scannedAt": now - 3600},
        {"key": "3", "type": "artist", "title": "Music", "refreshing": False, "scannedAt": now - 12 * 86400},
    ]}}))
    respx.get(f"{PLEX}/updater/status").mock(return_value=httpx.Response(200, json={"MediaContainer": {"size": 1 if release else 0, "canInstall": False, "checkedAt": now, "status": 0, **({"Release": [{"version": "1.42.1.9100", "state": "available"}]} if release else {})}}))
    respx.get(f"{PLEX}/myplex/account").mock(return_value=httpx.Response(200, json={"MyPlex": {"username": "owner@example.com", "mappingState": mapping, "mappingError": "" if mapping == "mapped" else "publisherror", "signInState": "ok", "publicAddress": "203.0.113.5"}}))
    respx.get(f"{PLEX}/activities").mock(return_value=httpx.Response(200, json={"MediaContainer": {"size": 0}}))
    respx.get(f"{PLEX}/statistics/resources").mock(return_value=httpx.Response(200, json={"MediaContainer": {"StatisticsResources": [
        {"timespan": 6, "at": now - 10, "hostCpuUtilization": 99.0, "processCpuUtilization": 0.5, "hostMemoryUtilization": 60.0, "processMemoryUtilization": 0.3},
        {"timespan": 6, "at": now - 5, "hostCpuUtilization": host_cpu, "processCpuUtilization": process_cpu, "hostMemoryUtilization": 61.2, "processMemoryUtilization": 0.308},
    ]}}))


@respx.mock
async def test_plex_findings_calm_and_with_problems(ctx: Context) -> None:
    _plex_server_routes()
    config = {"url": PLEX, "token": "tok"}
    calm = await get_adapter("plex").fetch("findings", config, {"scan_days": 30}, ctx)
    assert calm.status == "ok" and calm.items == [] and calm.meta["empty"] == "Plex answers · 1.42.0.9000 · 2 libraries"
    default = await get_adapter("plex").fetch("findings", config, {}, ctx)
    assert [(item["title"], item["status"]) for item in default.items] == [("Music", "warn")], "a library last scanned 12 days ago exceeds the 7-day default"
    assert default.items[0]["subtitle"] == "Music last scanned 12 days ago"
    assert default.meta["status_reason"] == "0 error finding(s), 1 warning(s)"
    respx.reset()
    _plex_server_routes(release=True, mapping="waiting", refreshing=True, host_cpu=95.0, process_cpu=85.0, transcodes=3)
    # A fresh context: the calm answers above are cached per integration for minutes.
    loud = await get_adapter("plex").fetch("findings", config, {}, Context(httpx.AsyncClient(), integration_id=2, widget_id=2, cache={}))
    subtitles = [item["subtitle"] for item in loud.items]
    assert loud.status == "bad"
    assert subtitles[0].startswith("Remote access is not working"), "red comes first"
    assert "Update 1.42.1.9100 available" in subtitles
    assert "Movies is being scanned" in subtitles
    assert "Plex uses 85% CPU" in subtitles and "The host is at 95% CPU" in subtitles
    assert "3 video transcodes running" in subtitles
    assert loud.meta["status_reason"] == "1 error finding(s), 3 warning(s)"


@respx.mock
async def test_plex_server_load_takes_the_latest_sample(ctx: Context) -> None:
    _plex_server_routes(host_cpu=20.6, process_cpu=0.05)
    data = await get_adapter("plex").fetch("load", {"url": PLEX, "token": "tok"}, {}, ctx)
    assert data.primary == {"label": "Plex CPU", "value": 0.1, "unit": "%"}, "the newest sample, not the first"
    assert {chip["label"]: chip["value"] for chip in data.secondary} == {"Plex RAM": 0.3, "Host CPU": 20.6, "Host RAM": 61.2}
    assert data.metrics == {"plex_cpu": 0.1, "plex_memory": 0.3, "host_cpu": 20.6, "host_memory": 61.2}
    assert data.status == "ok"


def _plex_history_routes() -> None:
    import time

    now = int(time.time())
    respx.get(f"{PLEX}/accounts").mock(return_value=httpx.Response(200, json={"MediaContainer": {"Account": [
        {"id": 1, "name": "Alex"}, {"id": 2, "name": "Sam"}, {"id": 3, "name": "Kim"},
        {"id": 4, "name": ""}, {"id": 5, "name": ""}, {"id": 838679209, "name": ""},
    ]}}))
    respx.get(f"{PLEX}/devices").mock(return_value=httpx.Response(200, json={"MediaContainer": {"Device": [{"id": 7, "name": "Living room TV", "platform": "Android"}, {"id": 8, "name": "", "platform": "iOS"}, {"id": 9, "name": "Living room TV", "platform": "Android"}]}}))
    respx.get(f"{PLEX}/status/sessions/history/all").mock(return_value=httpx.Response(200, json={"MediaContainer": {"Metadata": [
        {"type": "episode", "title": "Landfall", "grandparentTitle": "Harbour Lights", "grandparentThumb": "/library/metadata/20/thumb/1", "viewedAt": now - 3600, "accountID": 1, "deviceID": 7},
        {"type": "episode", "title": "Slack Water", "grandparentTitle": "Harbour Lights", "grandparentThumb": "/library/metadata/20/thumb/1", "viewedAt": now - 7200, "accountID": 1, "deviceID": 8},
        {"type": "movie", "title": "Orbital", "thumb": "/library/metadata/10/thumb/1", "viewedAt": now - 10000, "accountID": 2, "deviceID": 7},
        {"type": "movie", "title": "Old One", "thumb": "/library/metadata/11/thumb/1", "viewedAt": now - 40 * 86400, "accountID": 3, "deviceID": 7},
        {"type": "movie", "title": "Orbital", "thumb": "/library/metadata/10/thumb/1", "viewedAt": now - 500, "accountID": 838679209, "deviceID": 7},
        {"type": "episode", "title": "Ebb", "grandparentTitle": "Harbour Lights", "grandparentThumb": "/library/metadata/20/thumb/1", "viewedAt": now - 900, "accountID": 1, "deviceID": 9},
    ]}}))


@respx.mock
async def test_plex_users_and_devices_from_the_history(ctx: Context) -> None:
    _plex_history_routes()
    data = await get_adapter("plex").fetch("users", {"url": PLEX, "token": "tok"}, {"days": 1}, ctx)
    assert [(item["title"], item["subtitle"], item["status"], item["value"]) for item in data.items] == [
        ("Alex", "3 play(s) · Living room TV ×2, iOS", "ok", "3"),
        ("Account 838679209", "1 play(s) · Living room TV", "ok", "1"),
        ("Sam", "1 play(s) · Living room TV", "ok", "1"),
        ("Kim", "no activity", "unknown", ""),
    ], "active accounts first; two devices of one name are two; empty account slots vanish unless they played something; old plays excluded"
    assert {chip["label"]: chip["value"] for chip in data.secondary} == {"Accounts": 4, "Active": 3, "Devices": 3}
    sent = respx.get(f"{PLEX}/status/sessions/history/all").calls.last.request
    assert sent.url.params["sort"] == "viewedAt:desc" and "viewedAt%3E=" in str(sent.url) or "viewedAt>" in str(sent.url)


@respx.mock
async def test_plex_top_counts_plays_per_title(ctx: Context) -> None:
    _plex_history_routes()
    data = await get_adapter("plex").fetch("top", {"url": PLEX, "token": "tok"}, {"days": "7", "limit": 6}, ctx)
    assert [(item["title"], item["subtitle"], item["art"]) for item in data.items] == [
        ("Harbour Lights", "3 play(s)", "proxy:/library/metadata/20/thumb/1"),
        ("Orbital", "2 play(s)", "proxy:/library/metadata/10/thumb/1"),
    ], "episodes count for their series; a play older than the period is out"
    month = await get_adapter("plex").fetch("top", {"url": PLEX, "token": "tok"}, {"days": "30", "limit": 1}, ctx)
    assert [item["title"] for item in month.items] == ["Harbour Lights"]


@respx.mock
async def test_plex_history_walks_every_page(ctx: Context) -> None:
    import time

    now = int(time.time())
    respx.get(f"{PLEX}/accounts").mock(return_value=httpx.Response(200, json={"MediaContainer": {"Account": [{"id": 1, "name": "Alex"}]}}))
    respx.get(f"{PLEX}/devices").mock(return_value=httpx.Response(200, json={"MediaContainer": {"Device": [{"id": 7, "name": "Apple TV"}, {"id": 9, "name": "Apple TV"}]}}))

    def page(request: httpx.Request) -> httpx.Response:
        start = int(request.url.params.get("X-Plex-Container-Start") or 0)
        rows = [{"type": "movie", "title": f"Film {n}", "viewedAt": now - n, "accountID": 1, "deviceID": 7 if n % 2 else 9} for n in range(start, min(start + 500, 1200))]
        return httpx.Response(200, json={"MediaContainer": {"totalSize": 1200, "size": len(rows), "offset": start, "Metadata": rows}})

    route = respx.get(f"{PLEX}/status/sessions/history/all").mock(side_effect=page)
    data = await get_adapter("plex").fetch("users", {"url": PLEX, "token": "tok"}, {"days": 1}, ctx)
    assert data.items[0]["subtitle"] == "1200 play(s) · Apple TV ×2"
    assert {chip["label"]: chip["value"] for chip in data.secondary} == {"Accounts": 1, "Active": 1, "Devices": 2}
    assert route.call_count == 3, "500 + 500 + 200"


# -- jellyfin and emby: the operator cards ------------------------------------------

JF = "http://jf:8096"


def _iso(seconds_ago: float) -> str:
    from datetime import datetime, timedelta

    moment = datetime.now(UTC) - timedelta(seconds=seconds_ago)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.1234567Z")


def _jellyfin_routes(base: str = JF, *, loud: bool = False, playback: tuple[str, ...] = ("VideoPlayback", "AudioPlayback"), failed: str = "AuthenticationFailed", numeric_users: bool = False) -> None:
    # Emby's activity log carries the internal user number, not the user's id; /Users/{number} resolves it.
    u1, u2 = ("1", "2") if numeric_users else ("u1", "u2")
    respx.get(f"{base}/Users/1").mock(return_value=httpx.Response(200, json={"Id": "u1", "Name": "Alex"}))
    respx.get(f"{base}/Users/2").mock(return_value=httpx.Response(200, json={"Id": "u2", "Name": "Sam"}))
    respx.get(f"{base}/System/Info").mock(return_value=httpx.Response(200, json={"Version": "10.11.0", "ServerName": "nas", "HasPendingRestart": loud, "HasUpdateAvailable": False}))
    shows: dict[str, Any] = {"Name": "Shows", "CollectionType": "tvshows"}
    if loud:
        shows.update({"RefreshStatus": "Running", "RefreshProgress": 40})
    respx.get(f"{base}/Library/VirtualFolders").mock(return_value=httpx.Response(200, json=[{"Name": "Movies", "CollectionType": "movies"}, shows]))
    tasks: list[dict[str, Any]] = [{"Name": "Scan media library", "State": "Idle", "LastExecutionResult": {"Status": "Completed"}}]
    if loud:
        tasks += [
            {"Name": "Clean transcode directory", "State": "Idle", "LastExecutionResult": {"Status": "Failed", "ErrorMessage": "Access denied"}},
            {"Name": "Refresh guide", "State": "Running", "CurrentProgressPercentage": 12.5},
        ]
    respx.get(f"{base}/ScheduledTasks").mock(return_value=httpx.Response(200, json=tasks))
    respx.get(f"{base}/Sessions").mock(return_value=httpx.Response(200, json=[]))
    respx.get(f"{base}/Plugins").mock(return_value=httpx.Response(200, json=[{"Name": "Trakt", "Status": "Malfunctioned" if loud else "Active"}]))
    storage = {
        "ProgramDataFolder": {"Path": "/config", "DeviceId": "sda1", "FreeSpace": 2 * 1024**3, "UsedSpace": 98 * 1024**3},
        "CacheFolder": {"Path": "/config/cache", "DeviceId": "sda1", "FreeSpace": 2 * 1024**3, "UsedSpace": 98 * 1024**3},
        "Libraries": [{"Name": "Movies", "Folders": [{"Path": "/media/movies", "FreeSpace": 500 * 1024**3, "UsedSpace": 3000 * 1024**3}]}],
    }
    respx.get(f"{base}/System/Storage").mock(return_value=httpx.Response(200, json=storage) if loud else httpx.Response(404))
    entries: list[dict[str, Any]] = [
        {"Type": playback[0], "UserId": u1, "ItemId": "e1", "Date": _iso(3600), "Severity": "Information"},
        {"Type": playback[0], "UserId": u1, "ItemId": "e2", "Date": _iso(7200), "Severity": "Information"},
        {"Type": playback[-1], "UserId": u1, "ItemId": "m1", "Date": _iso(9000), "Severity": "Information"},
        {"Type": "SessionStarted", "UserId": u2, "Date": _iso(600), "Severity": "Information"},
        {"Type": playback[0], "UserId": u2, "ItemId": "m1", "Date": _iso(40 * 86400), "Severity": "Information"},
    ]
    if loud:
        entries = [{"Type": "TaskCompleted", "Name": "Scan media library failed", "Date": _iso(50), "Severity": "Error"}] + entries
        entries += [{"Type": failed, "Name": "Failed sign-in", "Date": _iso(100 + n), "Severity": "Error"} for n in range(6)]
    respx.get(f"{base}/System/ActivityLog/Entries").mock(return_value=httpx.Response(200, json={"Items": entries, "TotalRecordCount": len(entries)}))
    respx.get(f"{base}/Users").mock(return_value=httpx.Response(200, json=[
        {"Id": "u1", "Name": "Alex", "LastActivityDate": _iso(3600), "Policy": {"IsAdministrator": True}},
        {"Id": "u2", "Name": "Sam", "LastActivityDate": _iso(600), "Policy": {}},
        {"Id": "u3", "Name": "Kim", "LastActivityDate": _iso(40 * 86400), "Policy": {"IsDisabled": True}},
    ]))
    respx.get(f"{base}/Devices").mock(return_value=httpx.Response(200, json={"Items": [
        {"Id": "d1", "Name": "Living room TV", "AppName": "Android TV", "LastUserName": "Alex", "DateLastActivity": _iso(3600)},
        {"Id": "d2", "Name": "Chrome", "AppName": "Jellyfin Web", "LastUserName": "Alex", "DateLastActivity": _iso(7000)},
        {"Id": "d3", "Name": "Chrome", "AppName": "Jellyfin Web", "LastUserName": "Alex", "DateLastActivity": _iso(9000)},
        {"Id": "d4", "Name": "iPhone", "AppName": "Swiftfin", "LastUserName": "Sam", "DateLastActivity": _iso(40 * 86400)},
    ], "TotalRecordCount": 4}))

    def items(request: httpx.Request) -> httpx.Response:
        params = request.url.params
        if params.get("Ids"):
            return httpx.Response(200, json={"Items": [
                {"Id": "e1", "Type": "Episode", "Name": "Landfall", "SeriesId": "s1", "SeriesName": "Harbour Lights"},
                {"Id": "e2", "Type": "Episode", "Name": "Slack Water", "SeriesId": "s1", "SeriesName": "Harbour Lights"},
                {"Id": "m1", "Type": "Movie", "Name": "Orbital", "ProductionYear": 2025},
            ]})
        rows: dict[str, list[dict[str, Any]]] = {
            "Movie": [
                {"Id": "m1", "Type": "Movie", "Name": "Orbital", "ProductionYear": 2025, "DateCreated": _iso(500)},
                {"Id": "m2", "Type": "Movie", "Name": "The Quiet Harbour", "ProductionYear": 2026, "DateCreated": _iso(90000)},
            ],
            "Episode": [
                {"Id": "e3", "Type": "Episode", "Name": "Ebb", "SeriesId": "s1", "SeriesName": "Harbour Lights", "ParentIndexNumber": 3, "IndexNumber": 5, "DateCreated": _iso(100)},
                {"Id": "e4", "Type": "Episode", "Name": "Flow", "SeriesId": "s1", "SeriesName": "Harbour Lights", "ParentIndexNumber": 3, "IndexNumber": 4, "DateCreated": _iso(200)},
                {"Id": "e5", "Type": "Episode", "Name": "Pilot", "SeriesId": "s2", "SeriesName": "Tide Lines", "ParentIndexNumber": 1, "IndexNumber": 1, "DateCreated": _iso(3000)},
            ],
            "MusicAlbum": [{"Id": "a1", "Type": "MusicAlbum", "Name": "Northern Sky", "AlbumArtist": "Aurora Fields", "DateCreated": _iso(1000)}],
        }
        kind = str(params.get("IncludeItemTypes") or "")
        return httpx.Response(200, json={"Items": rows.get(kind, []), "TotalRecordCount": len(rows.get(kind, []))})

    respx.get(f"{base}/Items").mock(side_effect=items)


@respx.mock
async def test_jellyfin_recently_added_one_row_per_series(ctx: Context) -> None:
    _jellyfin_routes()
    data = await get_adapter("jellyfin").fetch("recent", {"url": JF, "api_key": "tok"}, {"kind": "all", "limit": 8}, ctx)
    assert [(item["title"], item["subtitle"], item["art"]) for item in data.items] == [
        ("Harbour Lights", "S03E05 · Ebb", "proxy:/Items/s1/Images/Primary?maxHeight=400"),
        ("Orbital", "2025", "proxy:/Items/m1/Images/Primary?maxHeight=400"),
        ("Northern Sky", "Aurora Fields", "proxy:/Items/a1/Images/Primary?maxHeight=400"),
        ("Tide Lines", "S01E01 · Pilot", "proxy:/Items/s2/Images/Primary?maxHeight=400"),
        ("The Quiet Harbour", "2026", "proxy:/Items/m2/Images/Primary?maxHeight=400"),
    ], "newest first across the types; a series appears once, with its newest episode"
    movies = await get_adapter("jellyfin").fetch("recent", {"url": JF, "api_key": "tok"}, {"kind": "movies", "limit": 1}, ctx)
    assert [item["title"] for item in movies.items] == ["Orbital"]


@respx.mock
async def test_jellyfin_findings_calm_and_with_problems(ctx: Context) -> None:
    _jellyfin_routes()
    calm = await get_adapter("jellyfin").fetch("findings", {"url": JF, "api_key": "tok"}, {}, ctx)
    assert calm.status == "ok" and calm.items == []
    assert calm.meta == {"empty": "Jellyfin answers · 10.11.0 · 2 libraries"}, "a missing storage report (Emby, older Jellyfin) is no finding"
    _jellyfin_routes(loud=True)
    loud = await get_adapter("jellyfin").fetch("findings", {"url": JF, "api_key": "tok"}, {}, Context(httpx.AsyncClient()))
    assert [(item["title"], item["subtitle"], item["status"]) for item in loud.items] == [
        ("Trakt", "Plugin malfunctioned", "bad"),
        ("Jellyfin", "A restart is pending", "warn"),
        ("Clean transcode directory", "The last run failed · Access denied", "warn"),
        ("Sign-in", "6 failed sign-ins in 24 h", "warn"),
        ("Activity log", "1 error(s) in 24 h · Scan media library failed", "warn"),
        ("Program data", "2.0 GB free", "warn"),
        ("Refresh guide", "running · 12%", "unknown"),
        ("Shows", "Shows is being scanned · 40%", "unknown"),
    ], "worst first; failed sign-ins are their own row and not counted as errors; one full disk is one row"
    assert loud.status == "bad" and loud.meta["status_reason"] == "1 error finding(s), 5 warning(s)"


@respx.mock
async def test_jellyfin_users_and_devices_from_the_activity_log(ctx: Context) -> None:
    _jellyfin_routes()
    data = await get_adapter("jellyfin").fetch("users", {"url": JF, "api_key": "tok"}, {"days": 1}, ctx)
    assert [(item["title"], item["subtitle"], item["status"], item["value"]) for item in data.items] == [
        ("Alex", "3 play(s) · Chrome ×2, Living room TV", "ok", "3"),
        ("Sam", "signed in, no plays", "ok", ""),
        ("Kim", "disabled", "unknown", ""),
    ], "plays from the activity log, devices by their last user and last activity; the old play and the old device are out"
    assert {chip["label"]: chip["value"] for chip in data.secondary} == {"Accounts": 3, "Active": 2, "Devices": 3}
    sent = respx.get(f"{JF}/System/ActivityLog/Entries").calls.last.request
    assert sent.url.params["Limit"] == "500" and sent.url.params["MinDate"].endswith("Z")


@respx.mock
async def test_jellyfin_top_groups_episodes_by_series(ctx: Context) -> None:
    _jellyfin_routes()
    data = await get_adapter("jellyfin").fetch("top", {"url": JF, "api_key": "tok"}, {"days": "7", "limit": 6}, ctx)
    assert [(item["title"], item["subtitle"], item["art"]) for item in data.items] == [
        ("Harbour Lights", "2 play(s)", "proxy:/Items/s1/Images/Primary?maxHeight=400"),
        ("Orbital", "1 play(s)", "proxy:/Items/m1/Images/Primary?maxHeight=400"),
    ], "two episodes of one series are two plays of the series, with the series poster"
    month = await get_adapter("jellyfin").fetch("top", {"url": JF, "api_key": "tok"}, {"days": "30", "limit": 6}, ctx)
    assert [item["subtitle"] for item in month.items] == ["2 play(s)", "1 play(s)"], "the 40-day-old play stays out of the month too"
    lookups = [call.request for call in respx.get(f"{JF}/Items").calls if call.request.url.params.get("Ids")]
    assert sorted(lookups[0].url.params["Ids"].split(",")) == ["e1", "e2", "m1"]


@respx.mock
async def test_emby_reads_its_own_activity_log_names(ctx: Context) -> None:
    base = "http://emby:8096"
    _jellyfin_routes(base, loud=True, playback=("playback.start",), failed="user.authenticationfailed", numeric_users=True)
    emby = get_adapter("emby")
    users = await emby.fetch("users", {"url": base, "api_key": "tok"}, {"days": 1}, ctx)
    assert [(item["title"], item["subtitle"]) for item in users.items][:2] == [("Alex", "3 play(s) · Chrome ×2, Living room TV"), ("Sam", "signed in, no plays")], "the log's user numbers are resolved to accounts"
    assert respx.get(f"{base}/Users/1").call_count == 1 and respx.get(f"{base}/Users/2").call_count == 0, "only numbers with plays in the period are looked up, once each"
    assert respx.calls.last.request.headers["X-Emby-Token"] == "tok"
    findings = await emby.fetch("findings", {"url": base, "api_key": "tok"}, {}, ctx)
    subtitles = [item["subtitle"] for item in findings.items]
    assert "6 failed sign-ins in 24 h" in subtitles
    assert "1 error(s) in 24 h · Scan media library failed" in subtitles, "Emby marks failed sign-ins as errors; they are not counted twice"
    assert findings.meta["empty"] == "Emby answers · 10.11.0 · 2 libraries"


# -- reolink ------------------------------------------------------------------------

REO = "http://cam"


class _Reolink:
    """A Reolink device behind respx: answers batched commands from a table and counts logins."""

    def __init__(self, **answers: Any) -> None:
        self.answers: dict[str, Any] = {
            "GetDevInfo": {"DevInfo": {"model": "Reolink Home Hub", "name": "Hub", "firmVer": "v3.5.1", "channelNum": 3}},
            "GetChannelstatus": {"count": 4, "status": [
                {"channel": 0, "name": "Front door", "online": 1, "sleep": 0},
                {"channel": 1, "name": "Garden", "online": 1, "sleep": 1},
                {"channel": 2, "name": "Garage", "online": 0},
                {"channel": 3, "name": "", "online": 0},
            ]},
            "GetAbility": {"Ability": {"abilityChn": [
                {"battery": {"permit": 0, "ver": 0}, "supportAi": {"permit": 6, "ver": 1}, "alarmMd": {"permit": 6, "ver": 1}},
                {"battery": {"permit": 6, "ver": 1}, "supportAi": {"permit": 6, "ver": 1}, "alarmMd": {"permit": 6, "ver": 1}},
                {"battery": {"permit": 0, "ver": 0}, "supportAi": {"permit": 6, "ver": 1}, "alarmMd": {"permit": 6, "ver": 1}},
                {"battery": {"permit": 0, "ver": 0}, "supportAi": {"permit": 0, "ver": 0}, "alarmMd": {"permit": 0, "ver": 0}},
            ]}},
            "GetBatteryInfo": lambda param: {"Battery": {"batteryPercent": 15, "chargeStatus": "charging"}},
            "GetAiState": lambda param: {"channel": param["channel"], "people": {"alarm_state": 1 if param["channel"] == 0 else 0, "support": 1}, "vehicle": {"alarm_state": 0, "support": 1}, "dog_cat": {"alarm_state": 0, "support": 1}},
            "GetMdState": {"state": 0},
            "GetHddInfo": {"HddInfo": [{"number": 0, "capacity": 953869, "size": 12000, "format": 1, "mount": 1}]},
            "GetNetPort": {"NetPort": {"rtmpEnable": 1, "rtmpPort": 1935, "httpPort": 80}},
        }
        self.answers.update(answers)
        self.logins = 0
        self.bodies: list[list[dict[str, Any]]] = []
        self.limit = False

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"[]")
        self.bodies.append(body)
        if body and body[0].get("cmd") == "Login":
            self.logins += 1
            if self.limit:
                return httpx.Response(200, json=[{"cmd": "Login", "code": 1, "error": {"rspCode": -5, "detail": "max session"}}])
            user = body[0]["param"]["User"]
            if user["password"] != "pw":
                return httpx.Response(200, json=[{"cmd": "Login", "code": 1, "error": {"rspCode": -7, "detail": "login failed"}}])
            return httpx.Response(200, json=[{"cmd": "Login", "code": 0, "value": {"Token": {"leaseTime": 3600, "name": f"T{self.logins}"}}}])
        if request.url.params.get("token") != f"T{self.logins}":
            return httpx.Response(200, json=[{"cmd": c.get("cmd"), "code": 1, "error": {"rspCode": -6, "detail": "please login first"}} for c in body])
        out = []
        for command in body:
            answer = self.answers.get(command["cmd"], "unsupported")
            if callable(answer):
                answer = answer(command.get("param") or {})
            if answer == "unsupported":
                out.append({"cmd": command["cmd"], "code": 1, "error": {"rspCode": -9, "detail": "not support"}})
            else:
                out.append({"cmd": command["cmd"], "code": 0, "value": answer})
        return httpx.Response(200, json=out)


CONFIG = {"url": REO, "username": "nexdeck", "password": "pw", "insecure": False}


@respx.mock
async def test_reolink_cameras_card_batches_battery_and_detections(ctx: Context) -> None:
    device = _Reolink()
    respx.post(f"{REO}/api.cgi").mock(side_effect=device)
    data = await get_adapter("reolink").fetch("cameras", CONFIG, {}, ctx)
    assert [(item["title"], item["subtitle"], item["status"], item["value"]) for item in data.items] == [
        ("Front door", "online · Person", "ok", ""),
        ("Garden", "sleeping · battery 15% · charging", "warn", "15%"),
        ("Garage", "offline", "bad", ""),
    ], "a wired camera has no battery line, a sleeping battery camera is fine, a low one warns, an offline one is bad; the empty slot is no camera"
    assert {chip["label"]: chip["value"] for chip in data.secondary} == {"Cameras": 3, "Online": 2, "Detecting": 1}
    assert data.status == "bad"
    assert device.logins == 1
    asked = [(command["cmd"], command["param"].get("channel")) for body in device.bodies for command in body if command.get("cmd") == "GetBatteryInfo"]
    assert asked == [("GetBatteryInfo", 1)], "battery is asked only where GetAbility lists one; a wired camera would block the hub for 15 s"
    assert max(len(body) for body in device.bodies) == 5, "battery, AI and motion of both online cameras travel in one request"
    again = await get_adapter("reolink").fetch("cameras", CONFIG, {}, ctx)
    assert again.items == data.items and device.logins == 1, "the token is reused"


@respx.mock
async def test_reolink_logs_in_again_when_the_session_expired(ctx: Context) -> None:
    device = _Reolink()
    respx.post(f"{REO}/api.cgi").mock(side_effect=device)
    ctx.cache["reolink_token"] = ("stale", time.monotonic() + 3000)
    result = await get_adapter("reolink").test(CONFIG, ctx)
    assert result == "Reolink Home Hub with firmware v3.5.1, 3 channel(s)."
    assert device.logins == 1, "a stale token costs one new login, not an error"
    with pytest.raises(AuthFailed):
        await get_adapter("reolink").test({**CONFIG, "password": "wrong"}, Context(httpx.AsyncClient(), cache={}))


@respx.mock
async def test_reolink_single_camera_is_its_own_channel(ctx: Context) -> None:
    device = _Reolink(GetChannelstatus="unsupported", GetDevInfo={"DevInfo": {"model": "RLC-810A", "name": "Driveway", "firmVer": "v3.1", "channelNum": 1}}, GetAbility="unsupported", GetBatteryInfo="unsupported", GetAiState="unsupported", GetHddInfo="unsupported")
    respx.post(f"{REO}/api.cgi").mock(side_effect=device)
    data = await get_adapter("reolink").fetch("cameras", CONFIG, {}, ctx)
    assert [(item["title"], item["subtitle"], item["status"]) for item in data.items] == [("Driveway", "online", "ok")], "no channel list, no battery: one plain row"
    findings = await get_adapter("reolink").fetch("findings", CONFIG, {}, ctx)
    assert findings.items == [] and findings.meta == {"empty": "Reolink answers · RLC-810A · 1 cameras"}, "a camera without a card is not a storage finding"


@respx.mock
async def test_reolink_findings_offline_low_battery_and_storage(ctx: Context) -> None:
    device = _Reolink(GetHddInfo={"HddInfo": [{"number": 0, "capacity": 953869, "size": 0, "format": 0, "mount": 1}]})
    respx.post(f"{REO}/api.cgi").mock(side_effect=device)
    data = await get_adapter("reolink").fetch("findings", CONFIG, {}, ctx)
    assert [(item["title"], item["subtitle"], item["status"]) for item in data.items] == [
        ("Garage", "offline", "bad"),
        ("Garden", "battery 15%", "warn"),
        ("Storage", "Storage not ready", "warn"),
    ]
    assert data.status == "bad" and data.meta["status_reason"] == "1 error finding(s), 2 warning(s)"
    assert data.meta["empty"] == "Reolink answers · Reolink Home Hub · 3 cameras"
    empty = _Reolink(GetHddInfo={"HddInfo": []})
    respx.post(f"{REO}/api.cgi").mock(side_effect=empty)
    without = await get_adapter("reolink").fetch("findings", CONFIG, {}, Context(httpx.AsyncClient(), cache={}))
    assert ("Storage", "No storage", "warn") in [(item["title"], item["subtitle"], item["status"]) for item in without.items]


@respx.mock
async def test_reolink_camera_card_snapshot_and_stream_sources(ctx: Context) -> None:
    device = _Reolink()
    respx.post(f"{REO}/api.cgi").mock(side_effect=device)
    reolink = get_adapter("reolink")
    card = await reolink.fetch("camera", CONFIG, {"channel": 1, "mode": "live", "interval": 10}, ctx)
    assert card.items == [{"title": "Garden", "subtitle": "sleeping", "status": "unknown", "art": "proxy:/snap/1/sub"}]
    clear = await reolink.fetch("camera", CONFIG, {"channel": 1, "quality": "main"}, ctx)
    assert clear.items[0]["art"] == "proxy:/snap/1/main"
    assert card.meta == {"mode": "live", "live": True, "interval": 10, "channel": 1, "empty": "No cameras"}
    offline = await reolink.fetch("camera", CONFIG, {"channel": 2, "mode": "live"}, ctx)
    assert offline.status == "bad" and offline.meta["live"] is False, "no live video from an offline camera"
    with pytest.raises(AdapterError) as missing:
        await reolink.fetch("camera", CONFIG, {"channel": 7}, ctx)
    assert missing.value.code == "no_channel"
    snapshot = await reolink.image_source(CONFIG, "/snap/1/main", ctx)
    assert snapshot.url == f"{REO}/cgi-bin/api.cgi" and snapshot.cache_seconds == 0
    assert snapshot.params["cmd"] == "Snap" and snapshot.params["channel"] == 1 and snapshot.params["snapType"] == "main" and snapshot.params["token"] == "T1" and snapshot.params["rs"]
    assert (await reolink.image_source(CONFIG, "/snap/1", ctx)).params["snapType"] == "sub", "the small picture unless asked otherwise"
    for bad in ("/library/metadata/1/thumb", "/snap/x", "/snap/1/huge"):
        with pytest.raises(AdapterError):
            await reolink.image_source(CONFIG, bad, ctx)
    stream = await reolink.stream_source(CONFIG, {"channel": 1, "quality": "main"}, ctx)
    assert stream.url == f"{REO}/flv" and stream.media_type == "video/x-flv"
    assert stream.params == {"port": 1935, "app": "bcs", "stream": "channel1_main.bcs", "token": "T1"}, "the session token instead of the account; RTMP need not be switched on"


@respx.mock
async def test_reolink_hands_back_its_session_and_backs_off_at_the_limit(ctx: Context) -> None:
    device = _Reolink()
    respx.post(f"{REO}/api.cgi").mock(side_effect=device)
    reolink = get_adapter("reolink")
    await reolink.fetch("cameras", CONFIG, {}, ctx)
    await reolink.close(CONFIG, ctx)
    logouts = [body for body in device.bodies if body and body[0].get("cmd") == "Logout"]
    assert len(logouts) == 1 and "reolink_token" not in ctx.cache, "the session goes back to the device"
    await reolink.close(CONFIG, ctx)
    assert len([body for body in device.bodies if body and body[0].get("cmd") == "Logout"]) == 1, "nothing cached, nothing sent"
    device.limit = True
    fresh = Context(httpx.AsyncClient(), cache={})
    with pytest.raises(AuthFailed) as refused:
        await reolink.fetch("cameras", CONFIG, {}, fresh)
    assert "session limit" in str(refused.value)
    logins = device.logins
    with pytest.raises(AuthFailed):
        await reolink.fetch("cameras", CONFIG, {}, fresh)
    assert device.logins == logins, "within the cooldown the device is not asked again"


# -- qbittorrent: two generations of the same sign-in --------------------------

QB = "http://qbittorrent:8080"
QB_CONFIG = {"url": QB, "username": "admin", "password": "secret"}


def _qbittorrent_routes(login: httpx.Response) -> None:
    """Everything needs a cookie; without one the API answers 403."""
    signed_in = {"value": False}

    def sign_in(request: httpx.Request) -> httpx.Response:
        signed_in["value"] = login.status_code < 400
        return login

    def guarded(payload: object):
        def answer(request: httpx.Request) -> httpx.Response:
            if not signed_in["value"]:
                return httpx.Response(403, text="Forbidden")
            return httpx.Response(200, json=payload)
        return answer

    respx.post(f"{QB}/api/v2/auth/login").mock(side_effect=sign_in)
    respx.get(f"{QB}/api/v2/transfer/info").mock(side_effect=guarded({"dl_info_speed": 2048, "up_info_speed": 512}))
    respx.get(f"{QB}/api/v2/torrents/info").mock(side_effect=guarded([
        {"name": "lab-sample.bin", "size": 4194304, "progress": 0.25, "state": "stalledDL", "hash": "abc", "eta": 8640000},
    ]))


@respx.mock
async def test_qbittorrent_understands_the_answer_of_version_five(ctx: Context) -> None:
    """5.x answers the sign-in with 204 and no body at all. Read as the old
    "200 Ok." the connection test fails while every card works, because the
    session cookie arrives with that 204 either way."""
    _qbittorrent_routes(httpx.Response(204))
    assert "1 items" in await get_adapter("qbittorrent").test(QB_CONFIG, ctx)


@respx.mock
async def test_qbittorrent_still_understands_the_answer_of_version_four(ctx: Context) -> None:
    _qbittorrent_routes(httpx.Response(200, text="Ok."))
    data = await get_adapter("qbittorrent").fetch("queue", QB_CONFIG, {}, ctx)
    assert data.items[0]["title"] == "lab-sample.bin"


@respx.mock
async def test_qbittorrent_reads_a_refused_sign_in_as_a_refusal(ctx: Context) -> None:
    """4.x says 200 with "Fails.", 5.x says 401. Both mean the same thing."""
    for refusal in (httpx.Response(200, text="Fails."), httpx.Response(401, text="Unauthorized")):
        respx.clear()
        _qbittorrent_routes(refusal)
        with pytest.raises(AuthFailed):
            await get_adapter("qbittorrent").test(QB_CONFIG, Context(httpx.AsyncClient(), cache={}))
