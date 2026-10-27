"""aria2, against the answers of aria2 1.36.0 (p3terx/aria2-pro, 27.10.2026).

The shapes are the measured ones: every number a string, a wrong secret as
HTTP 400, the same refusal inside a multicall as HTTP 200 with the fault in
the place of the answer, ``files[].uris`` fanned out per connection. The
names, addresses and sizes are made up.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context, Unreachable, outbound_client

BASE = "http://aria2.example.com:6800"
RPC = f"{BASE}/jsonrpc"
CONFIG = {"url": BASE, "secret": "example-secret"}
ADAPTER = get_adapter("aria2")


@pytest.fixture
def ctx() -> Context:
    return Context(outbound_client(guard=False), integration_id=1, widget_id=1, cache={})


def uris(address: str, state: str = "used", count: int = 3) -> list[dict[str, str]]:
    return [{"status": state, "uri": address} for _ in range(count)]


RUNNING = {
    "gid": "8c1d805943b379c5", "status": "active", "totalLength": "1073741824", "completedLength": "268435456",
    "downloadSpeed": "5242880", "uploadSpeed": "0",
    "files": [{"index": "1", "length": "1073741824", "completedLength": "268435456", "path": "/downloads/Copper.Sky.2025.2160p.mkv",
               "selected": "true", "uris": uris("https://files.example.com/Copper.Sky.2025.2160p.mkv")}],
}
TORRENT = {
    "gid": "b2", "status": "active", "totalLength": "2147483648", "completedLength": "1073741824", "downloadSpeed": "1048576",
    "uploadSpeed": "65536", "bittorrent": {"info": {"name": "Nightshift.2026.1080p"}, "mode": "multi"},
    "files": [{"index": "1", "path": "/downloads/Nightshift.2026.1080p/part1.mkv", "uris": []}],
}
SEEDING = {
    "gid": "c3", "status": "active", "totalLength": "1048576", "completedLength": "1048576", "downloadSpeed": "0", "uploadSpeed": "40960",
    "bittorrent": {"info": {"name": "Finished.And.Seeding"}}, "files": [{"index": "1", "path": "/downloads/Finished.And.Seeding", "uris": []}],
}
#: Not started yet: no file on disk, so no path and no length.
WAITING = {
    "gid": "a5", "status": "waiting", "totalLength": "0", "completedLength": "0", "downloadSpeed": "0",
    "files": [{"index": "1", "length": "0", "completedLength": "0", "path": "", "selected": "true",
               "uris": uris("https://files.example.com/pub/Harbour%20Lights.S03E04.mkv", "waiting")}],
}
PAUSED = {**WAITING, "gid": "a6", "status": "paused"}
FAILED = {
    "gid": "624e7a4ffd27c582", "status": "error", "totalLength": "0", "errorCode": "19",
    "errorMessage": "CUID#15 - Name resolution for example.invalid failed:Misformatted domain name",
    "files": [{"index": "1", "length": "0", "path": "", "uris": uris("http://example.invalid/a.iso")}],
}
DONE = {"gid": "d4", "status": "complete", "totalLength": "1048576", "errorCode": "0", "errorMessage": "",
        "files": [{"index": "1", "path": "/downloads/1Mb.dat", "uris": uris("https://files.example.com/1Mb.dat")}]}
VERSION = {"version": "1.36.0", "enabledFeatures": ["BitTorrent", "HTTPS"]}


def stat(**values: str) -> dict[str, str]:
    return {"downloadSpeed": "6291456", "uploadSpeed": "65536", "numActive": "2", "numWaiting": "2", "numStopped": "2",
            "numStoppedTotal": "9", **values}


def aria(answers: dict[str, Any], seen: list[dict[str, Any]] | None = None) -> None:
    """Answer a multicall by the names of the methods in it, as aria2 does."""
    def reply(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if seen is not None:
            seen.append(body)
        calls = body["params"][0] if body["method"] == "system.multicall" else [{"methodName": body["method"], "params": body["params"]}]
        results = []
        for call in calls:
            name = call["methodName"].removeprefix("aria2.")
            token = call["params"][0] if call["params"] else ""
            if token != "token:example-secret":
                results.append({"code": 1, "message": "Unauthorized"})
            else:
                results.append([answers[name]])
        if body["method"] == "system.multicall":
            return httpx.Response(200, json={"id": "nexdeck", "jsonrpc": "2.0", "result": results})
        if isinstance(results[0], dict):
            return httpx.Response(400, json={"id": "nexdeck", "jsonrpc": "2.0", "error": results[0]})
        return httpx.Response(200, json={"id": "nexdeck", "jsonrpc": "2.0", "result": results[0][0]})
    respx.post(RPC).mock(side_effect=reply)


QUEUE = {"getVersion": VERSION, "getGlobalStat": stat(), "tellActive": [RUNNING, TORRENT, SEEDING], "tellWaiting": [WAITING, PAUSED]}


@respx.mock
async def test_the_queue_names_each_download_and_leaves_the_seeding_one_out(ctx: Context) -> None:
    seen: list[dict[str, Any]] = []
    aria(QUEUE, seen)
    data = await ADAPTER.fetch("queue", CONFIG, {}, ctx)
    assert [(item["title"], item["progress"], item["status"]) for item in data.items] == [
        ("Copper.Sky.2025.2160p.mkv", 25.0, "ok"),
        ("Nightshift.2026.1080p", 50.0, "ok"),
        ("Harbour Lights.S03E04.mkv", 0.0, "warn"),
        ("Harbour Lights.S03E04.mkv", 0.0, "warn"),
    ]
    assert data.items[0]["subtitle"] == "1.0 GB · 2m 33s left"
    assert data.items[3]["subtitle"] == "paused"
    assert data.secondary == [{"label": "Speed", "value": "6.0 MB/s"}, {"label": "Queue", "value": 4}]
    assert data.status == "ok"
    # One request, the secret in every call inside it and not on the outside.
    assert len(seen) == 1 and seen[0]["method"] == "system.multicall"
    assert all(call["params"][0] == "token:example-secret" for call in seen[0]["params"][0])


@respx.mock
async def test_the_speed_card_counts_what_is_left_and_the_upload(ctx: Context) -> None:
    aria(QUEUE)
    data = await ADAPTER.fetch("speed", CONFIG, {}, ctx)
    assert data.primary == {"label": "Download", "value": 6.0, "unit": "MB/s"}
    assert {"label": "Queue", "value": 4} in data.secondary
    assert {"label": "Upload", "value": "64.0 KB/s"} in data.secondary
    assert data.metrics == {"download": 6.0, "upload": 0.06}
    assert [action.id for action in data.actions] == ["pause"]


@respx.mock
async def test_a_queue_of_only_paused_downloads_is_paused_and_offers_resume(ctx: Context) -> None:
    aria({**QUEUE, "getGlobalStat": stat(downloadSpeed="0", uploadSpeed="0", numActive="0"), "tellActive": [], "tellWaiting": [PAUSED]})
    data = await ADAPTER.fetch("speed", CONFIG, {}, ctx)
    assert data.status == "warn"
    assert data.primary["label"] == "Paused"
    assert [action.id for action in data.actions] == ["resume"]


@respx.mock
async def test_downloads_past_the_window_still_count(ctx: Context) -> None:
    aria({**QUEUE, "getGlobalStat": stat(numWaiting="250")})
    data = await ADAPTER.fetch("queue", CONFIG, {}, ctx)
    assert {"label": "Queue", "value": 250 + 2} in data.secondary


@respx.mock
async def test_pause_and_resume_call_pause_all_and_unpause_all(ctx: Context) -> None:
    seen: list[dict[str, Any]] = []
    aria({"pauseAll": "OK", "unpauseAll": "OK"}, seen)
    assert await ADAPTER.action("speed", "pause", {}, CONFIG, {}, ctx) == "Downloads paused."
    assert await ADAPTER.action("speed", "resume", {}, CONFIG, {}, ctx) == "Downloads resumed."
    assert [(call["method"], call["params"]) for call in seen] == [
        ("aria2.pauseAll", ["token:example-secret"]), ("aria2.unpauseAll", ["token:example-secret"])]


@respx.mock
async def test_the_stopped_card_puts_the_reason_under_a_failure_and_reads_newest_first(ctx: Context) -> None:
    seen: list[dict[str, Any]] = []
    aria({"getGlobalStat": stat(), "tellStopped": [FAILED, DONE]}, seen)
    data = await ADAPTER.fetch("stopped", CONFIG, {"limit": 5}, ctx)
    assert data.status == "bad"
    assert data.items[0] == {"id": "624e7a4ffd27c582", "title": "a.iso", "status": "bad", "value": "Failed",
                             "subtitle": "CUID#15 - Name resolution for example.invalid failed:Misformatted domain name"}
    assert data.items[1] == {"id": "d4", "title": "1Mb.dat", "subtitle": "1.0 MB", "value": "Done", "status": "ok"}
    assert data.metrics == {"failed": 1.0}
    assert data.secondary == [{"label": "Kept", "value": 2}, {"label": "Since start", "value": 9}]
    assert seen[0]["params"][0][1]["params"][1:3] == [-1, 5]


@respx.mock
async def test_clearing_the_list_forgets_records_and_is_only_offered_when_there_are_some(ctx: Context) -> None:
    aria({"getGlobalStat": stat(numStopped="0"), "tellStopped": []})
    data = await ADAPTER.fetch("stopped", CONFIG, {}, ctx)
    assert (data.status, data.actions, data.meta["empty"]) == ("ok", [], "Nothing has stopped yet.")
    seen: list[dict[str, Any]] = []
    aria({"purgeDownloadResult": "OK"}, seen)
    assert await ADAPTER.action("stopped", "purge", {}, CONFIG, {}, ctx) == "The list of stopped downloads is cleared."
    assert seen[0]["method"] == "aria2.purgeDownloadResult"
    card = ADAPTER.stopped_card(stat(), [DONE])
    assert [(one.id, one.confirm, one.danger) for one in card.actions] == [("purge", True, False)]


@respx.mock
async def test_the_test_names_the_version_and_the_queue(ctx: Context) -> None:
    aria(QUEUE)
    assert await ADAPTER.test(CONFIG, ctx) == "aria2 1.36.0 answers, 4 items in the queue."
    assert await ADAPTER.running_version(CONFIG, ctx) == "1.36.0"


@respx.mock
async def test_a_wrong_secret_is_a_refusal_of_the_credentials_in_both_shapes(ctx: Context) -> None:
    # Measured: HTTP 400 for a single call, HTTP 200 with the fault in the answer's place inside a multicall.
    aria(QUEUE)
    with pytest.raises(AuthFailed) as failure:
        await ADAPTER.fetch("queue", {**CONFIG, "secret": "wrong"}, {}, ctx)
    assert "rejected the RPC secret" in str(failure.value)
    with pytest.raises(AuthFailed):
        await ADAPTER.pause({**CONFIG, "secret": "wrong"}, ctx)
    with pytest.raises(AuthFailed) as failure:
        await ADAPTER.pause({"url": BASE}, ctx)
    assert "wants an RPC secret" in str(failure.value)


@respx.mock
async def test_a_url_with_the_endpoint_is_taken_as_it_is_and_no_secret_sends_no_token(ctx: Context) -> None:
    seen: list[dict[str, Any]] = []
    respx.post(RPC).mock(side_effect=lambda request: (seen.append(json.loads(request.content)), httpx.Response(
        200, json={"id": "nexdeck", "jsonrpc": "2.0", "result": "OK"}))[1])
    await ADAPTER.pause({"url": f"{BASE}/jsonrpc/"}, ctx)
    assert seen[0]["params"] == []


@respx.mock
async def test_something_else_at_the_address_is_not_taken_for_aria2(ctx: Context) -> None:
    respx.post(RPC).mock(return_value=httpx.Response(200, text="<html>AriaNg</html>"))
    with pytest.raises(AdapterError) as failure:
        await ADAPTER.test(CONFIG, ctx)
    assert failure.value.code == "not_aria2"
    respx.post(RPC).mock(return_value=httpx.Response(401, text="Unauthorized"))
    with pytest.raises(AuthFailed):
        await ADAPTER.test(CONFIG, ctx)
    respx.post(RPC).mock(return_value=httpx.Response(200, json={"jsonrpc": "2.0", "id": "nexdeck", "error": {"code": 1, "message": "No such method: aria2.nothing"}}))
    with pytest.raises(AdapterError) as failure:
        await ADAPTER.test(CONFIG, ctx)
    assert failure.value.code == "rpc_error"


@respx.mock
async def test_an_unreachable_aria2(ctx: Context) -> None:
    respx.post(RPC).mock(side_effect=httpx.ConnectError("connection refused"))
    with pytest.raises(Unreachable):
        await ADAPTER.fetch("queue", CONFIG, {}, ctx)


def test_a_finished_download_that_leaves_the_queue_is_reported() -> None:
    before = ADAPTER._widget("queue", {}, ADAPTER._snapshot(stat(), [{**RUNNING, "completedLength": "1048576000"}], []))
    after = ADAPTER._widget("queue", {}, ADAPTER._snapshot(stat(), [], []))
    assert [event.event for event in ADAPTER.detect("queue", before, after, {})] == ["download_done"]


def test_the_demo_fills_every_card() -> None:
    for tick in range(6):
        assert ADAPTER.demo("queue", {}, tick).items
        assert ADAPTER.demo("speed", {}, tick).primary
        assert ADAPTER.demo("stopped", {}, tick).items
