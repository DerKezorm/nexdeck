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
