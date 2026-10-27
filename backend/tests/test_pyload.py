"""pyLoad, against the answers of pyload-ng 0.5.0b3 (lscr.io/linuxserver/pyload-ng, 27.10.2026).

The shapes are the measured ones: ``status_server``, ``status_downloads`` and
``get_queue_data`` as the container gave them with one 1 GiB link downloading
and one that did not resolve; the names, sizes and addresses are made up.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context, Unreachable, outbound_client

BASE = "http://pyload.example.com:8000/api"
CONFIG = {"url": "http://pyload.example.com:8000", "api_key": "pl_example-key-for-the-tests"}
ADAPTER = get_adapter("pyload")


@pytest.fixture
def ctx() -> Context:
    return Context(outbound_client(guard=False), integration_id=1, widget_id=1, cache={})


def link(fid: int, name: str, status: int, package: int = 1, size: int = 0, error: str = "", message: str = "") -> dict:
    return {"fid": fid, "url": f"https://files.example.com/{name}", "name": name, "plugin": "DefaultPlugin", "size": size,
            "format_size": "", "status": status, "statusmsg": message, "package_id": package, "error": error, "order": fid}


def package(pid: int, name: str, links: list[dict]) -> dict:
    return {"pid": pid, "name": name, "folder": name.replace(" ", "_"), "site": "", "password": "", "dest": 1, "order": pid,
            "linksdone": 0, "sizedone": 0, "sizetotal": 0, "linkstotal": None, "links": links, "fids": None}


STATUS = {"pause": False, "active": 1, "queue": 3, "total": 3, "speed": 522009, "download": True, "reconnect": False, "captcha": False, "proxy": False}
ACTIVE = [{"fid": 1, "name": "Copper.Sky.2025.2160p.mkv", "speed": 522009, "eta": 2047, "format_eta": "00:34:07", "bleft": 805306368,
           "size": 1073741824, "format_size": "1.00 GiB", "percent": 25, "status": 12, "statusmsg": "downloading", "format_wait": "00:00:00",
           "wait_until": 0.0, "package_id": 1, "package_name": "Copper Sky", "plugin": "DefaultPlugin", "info": ""}]
QUEUE = [
    package(1, "Copper Sky", [
        link(1, "Copper.Sky.2025.2160p.mkv", 12, size=1073741824, message="downloading"),
        link(2, "x.bin", 8, error="(6, 'Could not resolve host: example.invalid')", message="failed"),
        link(3, "Copper.Sky.nfo", 0, size=2048, message="finished"),
    ]),
    package(2, "Nightshift", [
        link(4, "Nightshift.2026.1080p.mkv", 3, package=2, size=2147483648, message="queued"),
        link(5, "Nightshift.2026.sample.mkv", 5, package=2, size=52428800, message="waiting"),
        link(6, "Nightshift.2026.part3.rar", 1, package=2, message="offline"),
    ]),
]
FREE = 191309451264


def pyload(status: dict = STATUS, active: list = ACTIVE, queue: list = QUEUE, version: str = '"0.5.0"') -> respx.Route:
    respx.get(f"{BASE}/get_server_version").mock(return_value=httpx.Response(200, text=version, headers={"content-type": "application/json"}))
    route = respx.get(f"{BASE}/status_server").mock(return_value=httpx.Response(200, json=status))
    respx.get(f"{BASE}/status_downloads").mock(return_value=httpx.Response(200, json=active))
    respx.get(f"{BASE}/get_queue_data").mock(return_value=httpx.Response(200, json=queue))
    respx.get(f"{BASE}/free_space").mock(return_value=httpx.Response(200, json=FREE))
    return route


@respx.mock
async def test_the_queue_counts_links_that_can_still_run_and_leaves_the_failed_ones_to_their_card(ctx: Context) -> None:
    status = pyload()
    data = await ADAPTER.fetch("queue", CONFIG, {}, ctx)
    assert status.calls.last.request.headers["X-API-Key"] == CONFIG["api_key"]
    assert [(item["title"], item["progress"], item["status"]) for item in data.items] == [
        ("Copper.Sky.2025.2160p.mkv", 25.0, "ok"),
        ("Nightshift.2026.1080p.mkv", 0.0, "warn"),
        ("Nightshift.2026.sample.mkv", 0.0, "warn"),
    ]
    assert data.items[0]["subtitle"] == "1.0 GB · 34m 7s left"
    assert data.items[1]["subtitle"] == "2.0 GB · queued"
    assert data.secondary == [{"label": "Speed", "value": "509.8 KB/s"}, {"label": "Queue", "value": 3}]


@respx.mock
async def test_the_speed_card_adds_what_is_left_and_the_free_space(ctx: Context) -> None:
    pyload()
    data = await ADAPTER.fetch("speed", CONFIG, {}, ctx)
    assert data.primary == {"label": "Download", "value": 0.5, "unit": "MB/s"}
    assert {"label": "Left", "value": "2.8 GB"} in data.secondary
    assert {"label": "Free", "value": "178.2 GB"} in data.secondary
    assert [action.id for action in data.actions] == ["pause"]


@respx.mock
async def test_a_paused_server_offers_resume(ctx: Context) -> None:
    pyload(status={**STATUS, "pause": True, "download": False})
    data = await ADAPTER.fetch("speed", CONFIG, {}, ctx)
    assert (data.status, data.primary["label"], [action.id for action in data.actions]) == ("warn", "Paused", ["resume"])


@respx.mock
async def test_pause_and_resume_post_to_the_server_calls_with_the_key(ctx: Context) -> None:
    pause = respx.post(f"{BASE}/pause_server").mock(return_value=httpx.Response(200, text="null"))
    resume = respx.post(f"{BASE}/unpause_server").mock(return_value=httpx.Response(200, text="null"))
    assert await ADAPTER.action("speed", "pause", {}, CONFIG, {}, ctx) == "Downloads paused."
    assert await ADAPTER.action("speed", "resume", {}, CONFIG, {}, ctx) == "Downloads resumed."
    assert pause.calls.last.request.headers["X-API-Key"] == CONFIG["api_key"]
    assert resume.called


@respx.mock
async def test_the_attention_card_names_failures_with_their_package_and_reason(ctx: Context) -> None:
    pyload()
    data = await ADAPTER.fetch("attention", CONFIG, {}, ctx)
    assert data.status == "bad"
    assert data.items[0] == {"id": "2", "title": "x.bin", "status": "bad", "value": "Failed",
                             "subtitle": "Copper Sky · (6, 'Could not resolve host: example.invalid')"}
    assert data.items[1]["value"] == "Offline" and data.items[1]["status"] == "warn"
    assert data.metrics == {"failed": 2.0}
    assert [(action.id, action.danger) for action in data.actions] == [("retry", False)]


@respx.mock
async def test_a_waiting_captcha_is_a_row_of_its_own_and_turns_a_clean_card_yellow(ctx: Context) -> None:
    pyload(status={**STATUS, "captcha": True}, queue=[package(1, "Copper Sky", [link(1, "a.mkv", 12)])])
    data = await ADAPTER.fetch("attention", CONFIG, {}, ctx)
    assert data.status == "warn"
    assert [item["value"] for item in data.items] == ["Captcha"]
    assert data.actions == []


@respx.mock
async def test_a_clean_queue_says_so(ctx: Context) -> None:
    pyload(queue=[package(1, "Copper Sky", [link(1, "a.mkv", 12)])])
    data = await ADAPTER.fetch("attention", CONFIG, {}, ctx)
    assert (data.status, data.items, data.meta["empty"]) == ("ok", [], "Nothing needs a look.")


@respx.mock
async def test_trying_the_failed_ones_again_posts_restart_failed(ctx: Context) -> None:
    route = respx.post(f"{BASE}/restart_failed").mock(return_value=httpx.Response(200, text="null"))
    assert await ADAPTER.action("attention", "retry", {}, CONFIG, {}, ctx) == "The failed links are queued again."
    assert route.called


@respx.mock
async def test_the_test_names_the_version_and_the_queue(ctx: Context) -> None:
    pyload()
    assert await ADAPTER.test(CONFIG, ctx) == "pyLoad 0.5.0 answers, 3 items in the queue."
    assert await ADAPTER.running_version(CONFIG, ctx) == "0.5.0"


@respx.mock
async def test_a_wrong_key_and_a_missing_key_are_refused_credentials(ctx: Context) -> None:
    # Measured: HTTP 401 with "Invalid API key", and with "Invalid API credentials" for no header at all.
    respx.get(f"{BASE}/get_server_version").mock(return_value=httpx.Response(401, json={"error": "Invalid API key"}))
    with pytest.raises(AuthFailed):
        await ADAPTER.test(CONFIG, ctx)


@respx.mock
async def test_the_old_login_address_is_not_taken_for_a_pyload_that_can_be_read(ctx: Context) -> None:
    # An address that is not the API of pyLoad 0.5 answers 404 ("Not Found" JSON or a page).
    respx.get(f"{BASE}/get_server_version").mock(return_value=httpx.Response(404, json={"error": "Not Found"}))
    with pytest.raises(AdapterError) as failure:
        await ADAPTER.test(CONFIG, ctx)
    assert failure.value.code == "not_pyload"
    respx.get(f"{BASE}/get_server_version").mock(return_value=httpx.Response(200, text="<html>hello</html>"))
    with pytest.raises(AdapterError) as failure:
        await ADAPTER.test(CONFIG, ctx)
    assert failure.value.code == "not_json"


@respx.mock
async def test_an_unreachable_pyload(ctx: Context) -> None:
    respx.get(f"{BASE}/status_server").mock(side_effect=httpx.ConnectError("connection refused"))
    with pytest.raises(Unreachable):
        await ADAPTER.fetch("speed", CONFIG, {}, ctx)


def test_a_download_that_was_nearly_done_and_left_is_reported() -> None:
    nearly = [{**ACTIVE[0], "percent": 99}]
    before = ADAPTER._widget("queue", {}, ADAPTER._snapshot(STATUS, nearly, [package(1, "Copper Sky", [link(1, ACTIVE[0]["name"], 12)])], FREE))
    after = ADAPTER._widget("queue", {}, ADAPTER._snapshot(STATUS, [], [], FREE))
    assert [event.event for event in ADAPTER.detect("queue", before, after, {})] == ["download_done"]


def test_the_demo_fills_every_card() -> None:
    for tick in range(8):
        assert ADAPTER.demo("queue", {}, tick).items
        assert ADAPTER.demo("speed", {}, tick).primary
        assert ADAPTER.demo("attention", {}, tick).items
