"""slskd, against the answers of slskd 0.26.2 (27.10.2026).

``/application``, the sign-in and the refusals are the measured ones from a
fresh container without a Soulseek account. The **transfer lists are not**:
they need a Soulseek connection. Their rows follow slskd's OpenAPI file
(users, each with directories, each with files); the names are made up.
"""

from __future__ import annotations

import json
import time

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context, Unreachable, outbound_client

BASE = "http://slskd.example.com:5030/api/v0"
KEY = {"url": "http://slskd.example.com:5030", "api_key": "slskd-example-key"}
SIGNIN = {"url": "http://slskd.example.com:5030", "username": "admin", "password": "a-made-up-word"}
ADAPTER = get_adapter("slskd")


def fresh() -> Context:
    return Context(outbound_client(guard=False), integration_id=1, widget_id=1, cache={})


@pytest.fixture
def ctx() -> Context:
    return fresh()


#: As a fresh slskd without an account answered.
OFFLINE = {
    "version": {"full": "0.26.2.0 (0.26.2.0+e472ecd7)", "current": "0.26.2.0", "latest": "0.26.2.0", "isUpdateAvailable": False,
                "isCanary": False, "isDevelopment": False},
    "pendingReconnect": False, "pendingRestart": False,
    "server": {"state": "None", "isConnected": False, "isConnecting": False, "isLoggedIn": False, "isLoggingIn": False, "isTransitioning": False},
    "shares": {"scanPending": False, "scanning": False, "ready": True, "faulted": False, "scanProgress": 1, "hosts": ["local"], "directories": 0, "files": 0},
    "rooms": [], "users": [],
}
ONLINE = {**OFFLINE, "server": {**OFFLINE["server"], "state": "Connected, LoggedIn", "isConnected": True, "isLoggedIn": True},
          "shares": {**OFFLINE["shares"], "directories": 1480, "files": 14230}}


def transfer(user: str, filename: str, state: str, percent: float = 0, speed: float = 0, size: int = 25165824, remaining: str = "") -> dict:
    return {"id": f"{user}-{filename}"[:36], "username": user, "direction": "Download", "filename": filename, "size": size, "state": state,
            "percentComplete": percent, "averageSpeed": speed, "bytesTransferred": int(size * percent / 100), "remainingTime": remaining or None}


def listing(*files: dict) -> list[dict]:
    return [{"username": file["username"], "directories": [{"directory": "Music", "fileCount": 1, "files": [file]}]} for file in files]


DOWNLOADS = listing(
    transfer("alex_example", "@@share\\Music\\Harbour Lights - 01 Departure.flac", "InProgress", 40.0, 2097152, remaining="00:03:20"),
    transfer("sam_example", "@@share\\Music\\Copper Sky - 05 Signal.mp3", "Queued, Remotely"),
    transfer("kim_example", "@@share\\Music\\Orbital - Remote.flac", "Completed, TimedOut"),
    transfer("robin_example", "@@share\\Music\\Quiet Harbour.flac", "Completed, Errored"),
    transfer("alex_example", "@@share\\Music\\Done.flac", "Completed, Succeeded", 100.0),
    transfer("alex_example", "@@share\\Music\\Second.flac", "InProgress", 90.0, 1048576, remaining="1.02:03:04"),
)


@respx.mock
async def test_the_status_card_says_connected_and_what_is_shared_and_on_the_move(ctx: Context) -> None:
    respx.get(f"{BASE}/application").mock(return_value=httpx.Response(200, json=ONLINE))
    respx.get(f"{BASE}/transfers/downloads").mock(return_value=httpx.Response(200, json=DOWNLOADS))
    route = respx.get(f"{BASE}/transfers/uploads").mock(return_value=httpx.Response(200, json=[]))
    data = await ADAPTER.fetch("status", KEY, {}, ctx)
    assert (data.status, data.primary) == ("ok", {"label": "Soulseek", "value": "Connected"})
    assert data.secondary == [{"label": "Download", "metric": "download", "value": 3.0, "unit": "MB/s"},
                              {"label": "Upload", "metric": "upload", "value": 0.0, "unit": "MB/s"},
                              {"label": "Downloading", "value": 2}, {"label": "Uploading", "value": 0},
                              {"label": "Shared files", "value": 14230}, {"label": "Shared folders", "value": 1480}]
    assert data.metrics == {"download": 3.0, "upload": 0.0}
    assert route.calls.last.request.headers["X-API-Key"] == "slskd-example-key"


@respx.mock
async def test_a_slskd_without_a_connection_is_red_and_one_that_is_connecting_is_yellow(ctx: Context) -> None:
    respx.get(f"{BASE}/application").mock(return_value=httpx.Response(200, json=OFFLINE))
    respx.get(f"{BASE}/transfers/downloads").mock(return_value=httpx.Response(200, json=[]))
    respx.get(f"{BASE}/transfers/uploads").mock(return_value=httpx.Response(200, json=[]))
    data = await ADAPTER.fetch("status", KEY, {}, ctx)
    assert (data.status, data.primary["value"]) == ("bad", "Offline")
    connecting = {**OFFLINE, "server": {**OFFLINE["server"], "state": "Connecting", "isConnecting": True}}
    assert ADAPTER.status_card(connecting, [], []).status == "warn"


def test_a_faulted_share_index_or_a_scan_or_an_update_are_rows_and_the_fault_turns_the_card_yellow() -> None:
    faulted = {**ONLINE, "shares": {**ONLINE["shares"], "faulted": True}}
    card = ADAPTER.status_card(faulted, [], [])
    assert card.status == "warn" and {"label": "Share index", "value": "Faulted"} in card.secondary
    scanning = {**ONLINE, "shares": {**ONLINE["shares"], "scanning": True}}
    assert {"label": "Share index", "value": "Scanning"} in ADAPTER.status_card(scanning, [], []).secondary
    update = {**ONLINE, "version": {**ONLINE["version"], "latest": "0.27.0.0", "isUpdateAvailable": True}}
    card = ADAPTER.status_card(update, [], [])
    assert (card.status, {"label": "Update", "value": "0.27.0.0"} in card.secondary) == ("ok", True)


@respx.mock
async def test_the_download_list_puts_what_moves_first_then_the_queue_then_the_failures(ctx: Context) -> None:
    respx.get(f"{BASE}/transfers/downloads").mock(return_value=httpx.Response(200, json=DOWNLOADS))
    data = await ADAPTER.fetch("downloads", KEY, {}, ctx)
    assert [(item["title"], item["value"], item["status"]) for item in data.items] == [
        ("Second.flac", "90%", "ok"), ("Harbour Lights - 01 Departure.flac", "40%", "ok"),
        ("Copper Sky - 05 Signal.mp3", "", "unknown"), ("Orbital - Remote.flac", "", "warn"), ("Quiet Harbour.flac", "", "bad")]
    assert data.items[0]["subtitle"] == "alex_example · Transferring · 1.0 MB/s · 26h 3m left"
    assert data.items[1]["subtitle"] == "alex_example · Transferring · 2.0 MB/s · 3m 20s left"
    assert data.items[2]["subtitle"] == "sam_example · Queued by the other side · 24.0 MB"
    assert data.items[3]["subtitle"] == "kim_example · Timed out · 24.0 MB"
    assert data.items[1]["progress"] == 40.0 and data.items[2]["progress"] is None
    assert data.secondary == [{"label": "Transferring", "value": 2}, {"label": "Queued", "value": 1},
                              {"label": "Failed", "value": 2}, {"label": "Finished", "value": 1}]
    assert data.metrics == {"download": 3.0}
    assert data.status == "ok"
    assert [action.id for action in data.actions] == ["clear"]


@respx.mock
async def test_the_uploads_card_reads_its_own_list_and_records_the_upload_speed(ctx: Context) -> None:
    route = respx.get(f"{BASE}/transfers/uploads").mock(return_value=httpx.Response(200, json=listing(
        transfer("sam_example", "@@share\\Music\\Quiet Harbour.flac", "InProgress", 10.0, 524288))))
    data = await ADAPTER.fetch("uploads", KEY, {"limit": 3}, ctx)
    assert route.called and data.metrics == {"upload": 0.5} and len(data.items) == 1


@respx.mock
async def test_an_empty_list_says_so_and_offers_no_clearing(ctx: Context) -> None:
    respx.get(f"{BASE}/transfers/downloads").mock(return_value=httpx.Response(200, json=[]))
    data = await ADAPTER.fetch("downloads", KEY, {}, ctx)
    assert (data.items, data.actions, data.meta["empty"]) == ([], [], "Nothing is on the move.")


def test_a_flat_list_of_transfers_is_read_too_and_rows_that_are_not_transfers_are_passed_over() -> None:
    flat = [transfer("alex_example", "Song.flac", "InProgress", 5.0, 1024), {"username": "x", "state": "Queued"}, "junk", None]
    card = ADAPTER.transfers_card("downloads", flat, {})
    assert [item["title"] for item in card.items] == ["Song.flac"]
    assert ADAPTER.transfers_card("downloads", {"unexpected": True}, {}).items == []



@respx.mock
async def test_clearing_deletes_the_finished_records_in_the_direction_of_the_card(ctx: Context) -> None:
    route = respx.delete(f"{BASE}/transfers/downloads/all/completed").mock(return_value=httpx.Response(204))
    assert await ADAPTER.action("downloads", "clear", {}, KEY, {}, ctx) == "The finished transfers are cleared from the list."
    assert route.calls.last.request.headers["X-API-Key"] == "slskd-example-key"
    other = respx.delete(f"{BASE}/transfers/uploads/all/completed").mock(return_value=httpx.Response(204))
    await ADAPTER.action("uploads", "clear", {}, KEY, {}, ctx)
    assert other.called
    for widget, action in (("status", "clear"), ("downloads", "delete")):
        with pytest.raises(AdapterError) as failure:
            await ADAPTER.action(widget, action, {}, KEY, {}, ctx)
        assert failure.value.code == "no_such_action"


@respx.mock
async def test_the_sign_in_is_made_once_kept_and_made_again_when_the_token_is_refused(ctx: Context) -> None:
    expires = int(time.time()) + 604800
    login = respx.post(f"{BASE}/session").mock(side_effect=[
        httpx.Response(200, json={"token": "first-made-up-token", "expires": expires, "name": "admin", "tokenType": "Bearer"}),
        httpx.Response(200, json={"token": "second-made-up-token", "expires": expires, "name": "admin", "tokenType": "Bearer"})])
    seen: list[str] = []

    def application(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("authorization", ""))
        return httpx.Response(401) if request.headers["authorization"] == "Bearer first-made-up-token" and len(seen) > 1 else httpx.Response(200, json=ONLINE)
    respx.get(f"{BASE}/application").mock(side_effect=application)
    respx.get(f"{BASE}/transfers/downloads").mock(return_value=httpx.Response(200, json=[]))
    respx.get(f"{BASE}/transfers/uploads").mock(return_value=httpx.Response(200, json=[]))
    await ADAPTER.fetch("status", SIGNIN, {}, ctx)
    assert json.loads(login.calls.last.request.content) == {"username": "admin", "password": "a-made-up-word"}
    assert login.call_count == 1
    await ADAPTER.fetch("status", SIGNIN, {}, fresh_with(ctx))
    assert login.call_count == 2 and seen[-1] == "Bearer second-made-up-token"


def fresh_with(ctx: Context) -> Context:
    """A new fetch on the same connection: its answers are forgotten, its token is not."""
    ctx.forget_answers()
    return ctx


@respx.mock
async def test_a_wrong_password_a_wrong_key_and_no_credentials_are_refused_credentials(ctx: Context) -> None:
    respx.post(f"{BASE}/session").mock(return_value=httpx.Response(401))
    with pytest.raises(AuthFailed) as failure:
        await ADAPTER.test(SIGNIN, ctx)
    assert "user name or the password" in str(failure.value)
    respx.get(f"{BASE}/application").mock(return_value=httpx.Response(401))
    with pytest.raises(AuthFailed) as failure:
        await ADAPTER.test(KEY, fresh())
    assert "API key" in str(failure.value)
    with pytest.raises(AuthFailed) as failure:
        await ADAPTER.test({"url": KEY["url"]}, fresh())
    assert "API key, or a user name" in str(failure.value)


@respx.mock
async def test_the_test_names_the_version_and_whether_soulseek_is_connected(ctx: Context) -> None:
    respx.get(f"{BASE}/application").mock(return_value=httpx.Response(200, json=ONLINE))
    assert await ADAPTER.test(KEY, ctx) == "slskd 0.26.2.0 answers, connected to Soulseek."
    assert await ADAPTER.running_version(KEY, ctx) == "0.26.2.0"
    respx.get(f"{BASE}/application").mock(return_value=httpx.Response(200, json=OFFLINE))
    assert await ADAPTER.test(KEY, fresh()) == "slskd 0.26.2.0 answers, not connected to Soulseek."


@respx.mock
async def test_something_else_at_the_address_is_not_taken_for_slskd(ctx: Context) -> None:
    respx.get(f"{BASE}/application").mock(return_value=httpx.Response(404, text="nothing"))
    with pytest.raises(AdapterError) as failure:
        await ADAPTER.test(KEY, ctx)
    assert failure.value.code == "not_slskd"
    respx.get(f"{BASE}/application").mock(return_value=httpx.Response(200, json={"hello": "world"}))
    with pytest.raises(AdapterError) as failure:
        await ADAPTER.test(KEY, fresh())
    assert failure.value.code == "not_slskd"
    respx.get(f"{BASE}/application").mock(return_value=httpx.Response(200, text="<html></html>"))
    with pytest.raises(AdapterError) as failure:
        await ADAPTER.test(KEY, fresh())
    assert failure.value.code == "not_json"


@respx.mock
async def test_an_unreachable_slskd(ctx: Context) -> None:
    respx.get(f"{BASE}/application").mock(side_effect=httpx.ConnectError("connection refused"))
    with pytest.raises(Unreachable):
        await ADAPTER.fetch("status", KEY, {}, ctx)


def test_a_download_nearly_done_that_left_the_list_finished_and_a_cleared_one_did_not() -> None:
    before = ADAPTER.transfers_card("downloads", listing(
        transfer("alex_example", "Song.flac", "InProgress", 97.0, 1024), transfer("sam_example", "Other.flac", "InProgress", 10.0, 1024)), {})
    after = ADAPTER.transfers_card("downloads", [], {})
    found = ADAPTER.detect("downloads", before, after, {})
    assert [(event.event, event.title) for event in found] == [("download_done", "Song.flac finished")]
    assert ADAPTER.detect("uploads", before, after, {}) == [] and ADAPTER.detect("downloads", None, after, {}) == []


def test_the_demo_fills_every_card() -> None:
    for tick in range(0, 300, 37):
        assert ADAPTER.demo("status", {}, tick).primary
        assert ADAPTER.demo("downloads", {}, tick).items
        assert ADAPTER.demo("uploads", {}, tick).items


def test_connected_to_the_server_but_not_signed_in_is_not_connected_to_soulseek() -> None:
    def card(**flags: bool):  # noqa: ANN202
        return ADAPTER.status_card({**ONLINE, "server": {**OFFLINE["server"], **flags}}, [], [])
    assert (card(isConnected=True).status, card(isConnected=True).primary["value"]) == ("bad", "Offline")
    for flag in ("isConnecting", "isLoggingIn", "isTransitioning"):
        assert (card(**{flag: True}).status, card(**{flag: True}).primary["value"]) == ("warn", "Connecting")


@respx.mock
async def test_a_token_about_to_run_out_is_made_again_before_it_is_used(ctx: Context) -> None:
    login = respx.post(f"{BASE}/session").mock(return_value=httpx.Response(
        200, json={"token": "new-made-up-token", "expires": int(time.time()) + 604800}))
    respx.get(f"{BASE}/application").mock(return_value=httpx.Response(200, json=ONLINE))
    ctx.cache["slskd_token"] = ("old-made-up-token", time.time() + 30)
    await ADAPTER.test(SIGNIN, ctx)
    assert login.call_count == 1
    ctx.cache["slskd_token"] = ("kept-made-up-token", time.time() + 3600)
    await ADAPTER.test(SIGNIN, fresh_with(ctx))
    assert login.call_count == 1
