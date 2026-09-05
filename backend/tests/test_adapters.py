"""Adapters against recorded answers. No test here touches the network."""

from __future__ import annotations

import json
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
