"""The media block: audiobooks, music, books, transcoders and the cameras.

Each parser against a recorded answer. The point of every test here is the
shape a service answers with, because that is what breaks silently.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


# -- audiobookshelf ------------------------------------------------------------


@respx.mock
async def test_audiobookshelf_counts_books_and_podcasts_apart(ctx: Context) -> None:
    config = {"url": "http://abs:13378", "api_key": "key"}
    respx.get("http://abs:13378/api/libraries").mock(return_value=httpx.Response(200, json={"libraries": [
        {"id": "l1", "name": "Audiobooks", "mediaType": "book"},
        {"id": "l2", "name": "Podcasts", "mediaType": "podcast"},
    ]}))
    respx.get("http://abs:13378/api/libraries/l1/stats").mock(return_value=httpx.Response(200, json={"totalItems": 412, "totalSize": 800_000_000_000}))
    respx.get("http://abs:13378/api/libraries/l2/stats").mock(return_value=httpx.Response(200, json={"totalItems": 38, "totalSize": 140_000_000_000}))
    data = await get_adapter("audiobookshelf").fetch("library", config, {}, ctx)
    assert data.primary == {"label": "Books", "value": 412}
    assert [entry["value"] for entry in data.secondary if entry["label"] == "Podcasts"] == [38]
    assert respx.calls.last.request.headers["Authorization"] == "Bearer key"


# -- navidrome -----------------------------------------------------------------


@respx.mock
async def test_navidrome_signs_every_request_with_a_fresh_salt(ctx: Context) -> None:
    """The Subsonic API wants a token derived from password and salt; the
    password itself must never travel."""
    config = {"url": "http://navidrome:4533", "username": "kim", "password": "secret"}
    respx.get("http://navidrome:4533/rest/getNowPlaying").mock(return_value=httpx.Response(200, json={"subsonic-response": {
        "status": "ok", "nowPlaying": {"entry": [{"artist": "Harbour Brass", "title": "Slow Tide", "username": "kim", "playerName": "Living room"}]},
    }}))
    data = await get_adapter("navidrome").fetch("playing", config, {}, ctx)
    assert data.items[0]["title"] == "Harbour Brass - Slow Tide"
    query = dict(respx.calls.last.request.url.params)
    assert query["u"] == "kim" and query["c"] == "nexdeck"
    assert "p" not in query and "secret" not in str(respx.calls.last.request.url)
    assert len(query["t"]) == 32 and len(query["s"]) >= 8


@respx.mock
async def test_navidrome_refused_credentials_are_an_auth_failure(ctx: Context) -> None:
    respx.get("http://navidrome:4533/rest/ping").mock(return_value=httpx.Response(200, json={"subsonic-response": {
        "status": "failed", "error": {"code": 40, "message": "Wrong username or password"},
    }}))
    with pytest.raises(AdapterError) as failure:
        await get_adapter("navidrome").test({"url": "http://navidrome:4533", "username": "kim", "password": "no"}, ctx)
    assert failure.value.code == "auth_failed"


# -- komga and kavita ------------------------------------------------------------


@respx.mock
async def test_komga_counts_series_and_books(ctx: Context) -> None:
    config = {"url": "http://komga:25600", "api_key": "key"}
    respx.get("http://komga:25600/api/v1/libraries").mock(return_value=httpx.Response(200, json=[{"id": "1"}, {"id": "2"}]))
    respx.get("http://komga:25600/api/v1/series").mock(return_value=httpx.Response(200, json={"totalElements": 218}))
    respx.get("http://komga:25600/api/v1/books").mock(return_value=httpx.Response(200, json={"totalElements": 3140}))
    data = await get_adapter("komga").fetch("library", config, {}, ctx)
    assert data.primary == {"label": "Series", "value": 218}
    assert data.metrics == {"series": 218.0, "books": 3140.0}
    assert respx.calls.last.request.headers["X-API-Key"] == "key"


@respx.mock
async def test_kavita_fetches_a_token_once_and_reuses_it(ctx: Context) -> None:
    config = {"url": "http://kavita:5000", "api_key": "plugin-key"}
    login = respx.post("http://kavita:5000/api/Plugin/authenticate").mock(return_value=httpx.Response(200, json={"token": "jwt", "username": "kim"}))
    respx.get("http://kavita:5000/api/Library/libraries").mock(return_value=httpx.Response(200, json=[{"id": 1}, {"id": 2}, {"id": 3}]))
    respx.post("http://kavita:5000/api/Series/all-v2").mock(return_value=httpx.Response(200, json=[{"id": 1}]))
    kavita = get_adapter("kavita")
    data = await kavita.fetch("library", config, {}, ctx)
    assert data.primary == {"label": "Libraries", "value": 3}
    await kavita.fetch("library", config, {}, ctx)
    assert login.call_count == 1, "the token is kept in the integration's memory"


@respx.mock
async def test_kavita_rejected_key_says_so(ctx: Context) -> None:
    respx.post("http://kavita:5000/api/Plugin/authenticate").mock(return_value=httpx.Response(401))
    with pytest.raises(AuthFailed):
        await get_adapter("kavita").fetch("library", {"url": "http://kavita:5000", "api_key": "bad"}, {}, ctx)


# -- calibre-web -----------------------------------------------------------------


@respx.mock
async def test_calibreweb_signs_in_and_counts_the_shelf(ctx: Context) -> None:
    config = {"url": "http://calibre:8083", "username": "kim", "password": "pw"}
    respx.post("http://calibre:8083/login").mock(return_value=httpx.Response(302, headers={"set-cookie": "session=abc; Path=/"}))
    respx.get("http://calibre:8083/ajax/listbooks").mock(return_value=httpx.Response(200, json={
        "totalNotFiltered": 2480,
        "rows": [{"title": "A History of Harbours", "authors": ["R. Meyer"]}],
    }))
    calibre = get_adapter("calibreweb")
    data = await calibre.fetch("library", config, {}, ctx)
    assert data.primary == {"label": "Books", "value": 2480}
    assert respx.calls.last.request.headers["Cookie"] == "session=abc"


@respx.mock
async def test_calibreweb_says_when_the_address_moved(ctx: Context) -> None:
    """Calibre-Web has no API; when a version moves the address, the card must
    say that instead of showing a zero."""
    config = {"url": "http://calibre:8083", "username": "kim", "password": "pw"}
    respx.post("http://calibre:8083/login").mock(return_value=httpx.Response(200, headers={"set-cookie": "session=abc; Path=/"}))
    respx.get("http://calibre:8083/ajax/listbooks").mock(return_value=httpx.Response(200, text="<html>login</html>"))
    with pytest.raises(AdapterError) as failure:
        await get_adapter("calibreweb").fetch("library", config, {}, ctx)
    assert failure.value.code == "not_json"
    assert "table view" in failure.value.hint


# -- tdarr, unmanic, fileflows ------------------------------------------------------


@respx.mock
async def test_tdarr_reads_the_statistics_document(ctx: Context) -> None:
    config = {"url": "http://tdarr:8265"}
    respx.post("http://tdarr:8265/api/v2/cruddb").mock(return_value=httpx.Response(200, json={
        "totalFileCount": 18240, "table1Count": 12, "table2Count": 4820, "table3Count": 2,
    }))
    data = await get_adapter("tdarr").fetch("queue", config, {}, ctx)
    assert data.status == "bad", "two failed files are worth a red dot"
    assert data.primary == {"label": "Queued", "value": 12}
    assert data.metrics == {"queued": 12.0, "errors": 2.0}


@respx.mock
async def test_tdarr_nodes_show_what_they_are_doing(ctx: Context) -> None:
    respx.get("http://tdarr:8265/api/v2/get-nodes").mock(return_value=httpx.Response(200, json={
        "n1": {"nodeName": "basement", "nodeOS": "linux", "nodePaused": False, "workers": {"w1": {}, "w2": {}}},
        "n2": {"nodeName": "desktop", "nodeOS": "windows", "nodePaused": True, "workers": {}},
    }))
    data = await get_adapter("tdarr").fetch("nodes", {"url": "http://tdarr:8265"}, {}, ctx)
    assert [(item["title"], item["value"], item["status"]) for item in data.items] == [("basement", 2, "ok"), ("desktop", 0, "unknown")]


@respx.mock
async def test_unmanic_workers_and_queue(ctx: Context) -> None:
    config = {"url": "http://unmanic:8888"}
    respx.get("http://unmanic:8888/unmanic/api/v2/workers/status").mock(return_value=httpx.Response(200, json={"workers_status": [
        {"id": "w1", "name": "Worker 1", "idle": False, "current_file": "Harbour.mkv", "progress": {"percent": "41"}},
        {"id": "w2", "name": "Worker 2", "idle": True, "current_file": "", "progress": {}},
    ]}))
    respx.post("http://unmanic:8888/unmanic/api/v2/pending/tasks").mock(return_value=httpx.Response(200, json={"recordsTotal": 17, "results": []}))
    unmanic = get_adapter("unmanic")
    workers = await unmanic.fetch("workers", config, {}, ctx)
    assert [item["value"] for item in workers.items] == ["41%", ""]
    assert workers.items[1]["subtitle"] == "idle", "a waiting worker says so where the interface can translate it"
    queue = await unmanic.fetch("queue", config, {}, ctx)
    assert queue.primary == {"label": "Queued", "value": 17}
    assert queue.status == "warn"


@respx.mock
async def test_fileflows_status_and_running_files(ctx: Context) -> None:
    config = {"url": "http://fileflows:19200"}
    respx.get("http://fileflows:19200/api/status").mock(return_value=httpx.Response(200, json={"queue": 6, "processing": 2, "processed": 1420, "time": "18d 4h"}))
    respx.get("http://fileflows:19200/api/worker").mock(return_value=httpx.Response(200, json=[
        {"relativeFile": "movies/Copper.Sky.2025.mkv", "currentPartName": "Video Encode", "currentPartPercent": 42.5},
    ]))
    fileflows = get_adapter("fileflows")
    status = await fileflows.fetch("status", config, {}, ctx)
    assert status.primary == {"label": "Queued", "value": 6}
    running = await fileflows.fetch("running", config, {}, ctx)
    assert running.items[0]["title"] == "Copper.Sky.2025.mkv", "the path is cut down to the file"
    assert running.items[0]["progress"] == 42.5


# -- maintainerr and jellystat --------------------------------------------------------


@respx.mock
async def test_maintainerr_counts_what_is_on_its_way_out(ctx: Context) -> None:
    config = {"url": "http://maintainerr:6246"}
    respx.get("http://maintainerr:6246/api/collections").mock(return_value=httpx.Response(200, json=[
        {"title": "Watched over 90 days", "description": "Movies", "deleteAfterDays": 14, "isActive": True, "media": [{"id": 1}, {"id": 2}]},
        {"title": "Never watched", "description": "Sitting there", "deleteAfterDays": 60, "isActive": False, "media": []},
    ]))
    maintainerr = get_adapter("maintainerr")
    status = await maintainerr.fetch("status", config, {}, ctx)
    assert status.primary == {"label": "Media", "value": 2}
    assert [entry["value"] for entry in status.secondary if entry["label"] == "Active"] == [1]
    collections = await maintainerr.fetch("collections", config, {}, ctx)
    assert [item["value"] for item in collections.items] == ["2 · 14 d", "0 · 60 d"]
    assert collections.items[1]["status"] == "unknown", "a switched-off rule is not a warning"


@respx.mock
async def test_jellystat_libraries_and_most_watched(ctx: Context) -> None:
    config = {"url": "http://jellystat:3000", "api_key": "key"}
    respx.get("http://jellystat:3000/api/getLibraries").mock(return_value=httpx.Response(200, json=[
        {"Name": "Movies", "CollectionType": "movies", "Library_Count": 1284},
        {"Name": "Shows", "CollectionType": "tvshows", "Library_Count": 218},
    ]))
    respx.post("http://jellystat:3000/stats/getMostViewedByType").mock(return_value=httpx.Response(200, json=[
        {"Label": "Movies", "results": [{"Name": "The Quiet Harbour", "Plays": 14}, {"Name": "Copper Sky", "Plays": 5}]},
        {"Label": "Shows", "results": [{"Name": "Harbour Lights", "Plays": 11}]},
    ]))
    jellystat = get_adapter("jellystat")
    libraries = await jellystat.fetch("libraries", config, {}, ctx)
    assert [entry["value"] for entry in libraries.secondary if entry["label"] == "Items"] == [1502]
    assert respx.calls.last.request.headers["x-api-token"] == "key"
    watched = await jellystat.fetch("watched", config, {"days": 30, "limit": 6}, ctx)
    assert [item["title"] for item in watched.items] == ["The Quiet Harbour", "Harbour Lights", "Copper Sky"], "most plays first"


# -- frigate ---------------------------------------------------------------------------


@respx.mock
async def test_frigate_separates_cameras_from_the_rest_of_the_stats(ctx: Context) -> None:
    """``/api/stats`` mixes cameras and service data in one object; a camera
    that stopped delivering frames is the finding."""
    config = {"url": "http://frigate:5000"}
    respx.get("http://frigate:5000/api/stats").mock(return_value=httpx.Response(200, json={
        "driveway": {"camera_fps": 10.0, "detection_fps": 1.4, "process_fps": 10.0},
        "front_door": {"camera_fps": 0.0, "detection_fps": 0.0, "process_fps": 0.0},
        "detection_fps": 1.4,
        "detectors": {"coral": {"inference_speed": 8.1}},
        "service": {"storage": {"/media/frigate/recordings": {"used": 1_000_000, "total": 2_000_000}}},
        "cpu_usages": {},
    }))
    frigate = get_adapter("frigate")
    cameras = await frigate.fetch("cameras", config, {}, ctx)
    assert [item["title"] for item in cameras.items] == ["front door", "driveway"], "the dead one first"
    assert cameras.status == "bad"
    assert cameras.metrics == {"cameras": 2.0}

    status = await frigate.fetch("status", config, {}, ctx)
    assert status.primary == {"label": "Cameras", "value": 2}
    assert status.metrics["storage_percent"] == 50.0


@respx.mock
async def test_frigate_events_read_the_time_and_the_score(ctx: Context) -> None:
    respx.get("http://frigate:5000/api/events").mock(return_value=httpx.Response(200, json=[
        {"label": "person", "camera": "front_door", "start_time": 1_788_600_000, "top_score": 0.91, "has_clip": True},
        {"label": "car", "camera": "driveway", "start_time": 1_788_599_000, "score": 0.88, "has_clip": False},
    ]))
    data = await get_adapter("frigate").fetch("events", {"url": "http://frigate:5000"}, {"limit": 8}, ctx)
    assert [item["title"] for item in data.items] == ["Person", "Car"]
    assert [item["value"] for item in data.items] == ["91%", "88%"]
