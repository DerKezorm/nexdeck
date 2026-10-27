"""Owncast, against the answers of Owncast v0.3.0 (owncast/owncast, 27.10.2026).

Offline, and live with a test picture pushed over RTMP: the public status, the
administrator's status with the broadcaster's stream details, the 401 of a
wrong password and the disconnect. ``health`` is the one thing not seen (it was
``null`` all along); its shape is from Owncast's source.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context, Unreachable, outbound_client

BASE = "http://owncast.example.com:8080"
CONFIG = {"url": BASE, "stream_key": "a-made-up-stream-key"}
PUBLIC_ONLY = {"url": BASE}
ADAPTER = get_adapter("owncast")


def fresh() -> Context:
    return Context(outbound_client(guard=False), integration_id=1, widget_id=1, cache={})


@pytest.fixture
def ctx() -> Context:
    return fresh()


OFFLINE = {"serverTime": "2026-10-27T16:58:23.152281151Z", "lastConnectTime": None, "lastDisconnectTime": "2026-10-27T15:00:00Z",
           "versionNumber": "0.3.0", "streamTitle": "", "online": False}
LIVE = {"serverTime": "2026-10-27T17:12:30.5Z", "lastConnectTime": "2026-10-27T16:58:58Z", "lastDisconnectTime": None,
        "versionNumber": "0.3.0", "streamTitle": "Friday night build", "online": True}
ADMIN_OFFLINE = {"broadcaster": None, "currentBroadcast": None, "health": None, "streamTitle": "", "versionNumber": "0.3.0",
                 "viewerCount": 0, "overallPeakViewerCount": 1, "sessionPeakViewerCount": 1, "online": False}
ADMIN_LIVE = {
    "broadcaster": {"time": "2026-10-27T16:58:58.334580581Z", "remoteAddr": "192.0.2.10:44428",
                    "streamDetails": {"videoCodec": "H.264", "audioCodec": "AAC", "encoder": "Lavf60.16.100", "width": 640, "height": 360,
                                      "videoBitrate": 781, "audioBitrate": 67, "framerate": 30}},
    "currentBroadcast": {"outputSettings": [{"name": "", "videoPassthrough": False, "videoBitrate": 1200}], "latencyLevel": {"level": 2}},
    "health": None, "streamTitle": "Friday night build", "versionNumber": "0.3.0", "viewerCount": 12,
    "overallPeakViewerCount": 112, "sessionPeakViewerCount": 44, "online": True}


def owncast(public: dict, admin: dict) -> dict[str, respx.Route]:
    return {
        "public": respx.get(f"{BASE}/api/status").mock(return_value=httpx.Response(200, json=public)),
        "admin": respx.get(f"{BASE}/api/admin/status").mock(return_value=httpx.Response(200, json=admin)),
        "followers": respx.get(f"{BASE}/api/admin/followers").mock(return_value=httpx.Response(200, json={"results": [], "total": 281})),
    }


@respx.mock
async def test_a_live_stream_shows_how_long_who_watches_and_the_picture(ctx: Context) -> None:
    routes = owncast(LIVE, ADMIN_LIVE)
    data = await ADAPTER.fetch("stream", CONFIG, {}, ctx)
    assert (data.status, data.primary) == ("ok", {"label": "Stream", "value": "Live"})
    assert data.secondary == [
        {"label": "Title", "value": "Friday night build"}, {"label": "Live for", "value": "13m 32s"}, {"label": "Viewers", "value": 12},
        {"label": "Picture", "value": "640x360 at 30 fps"}, {"label": "Bitrate", "value": "781 kbit/s"}, {"label": "Followers", "value": 281}]
    assert data.metrics == {"viewers": 12.0}
    assert [(action.id, action.confirm, action.danger) for action in data.actions] == [("disconnect", True, True)]
    assert routes["admin"].calls.last.request.headers["authorization"].startswith("Basic ")
    assert "authorization" not in routes["public"].calls.last.request.headers
    assert data.link == BASE



@respx.mock
async def test_an_offline_stream_is_grey_says_for_how_long_and_offers_no_disconnect(ctx: Context) -> None:
    owncast(OFFLINE, ADMIN_OFFLINE)
    data = await ADAPTER.fetch("stream", CONFIG, {}, ctx)
    assert (data.status, data.primary["value"], data.actions) == ("unknown", "Offline", [])
    assert {"label": "Offline for", "value": "1h 58m"} in data.secondary
    assert data.metrics == {"viewers": 0.0}
    assert not any(row["label"] in ("Picture", "Bitrate", "Live for") for row in data.secondary)
    # A server that still counts somebody after the stream ended does not make the stream popular.
    counting = ADAPTER.stream_card(OFFLINE, {**ADMIN_OFFLINE, "viewerCount": 3})
    assert counting.metrics == {"viewers": 0.0} and {"label": "Viewers", "value": 0} in counting.secondary



@respx.mock
async def test_without_the_stream_key_only_the_public_status_is_read_and_nothing_can_be_pressed(ctx: Context) -> None:
    routes = owncast(LIVE, ADMIN_LIVE)
    data = await ADAPTER.fetch("stream", PUBLIC_ONLY, {}, ctx)
    assert not routes["admin"].called and data.actions == [] and data.metrics == {}
    assert [row["label"] for row in data.secondary] == ["Title", "Live for"]
    with pytest.raises(AdapterError) as failure:
        await ADAPTER.fetch("viewers", PUBLIC_ONLY, {}, ctx)
    assert failure.value.code == "needs_stream_key"


@respx.mock
async def test_an_unhealthy_stream_turns_the_card_yellow_with_the_message(ctx: Context) -> None:
    owncast(LIVE, {**ADMIN_LIVE, "health": {"healthy": False, "message": "Dropping frames", "representation": 0, "timestamp": "2026-10-27T17:12:00Z"}})
    data = await ADAPTER.fetch("stream", CONFIG, {}, ctx)
    assert data.status == "warn" and {"label": "Health", "value": "Dropping frames"} in data.secondary
    healthy = ADAPTER.stream_card(LIVE, {**ADMIN_LIVE, "health": {"healthy": True, "message": ""}})
    assert healthy.status == "ok" and not any(row["label"] == "Health" for row in healthy.secondary)


@respx.mock
async def test_the_viewers_card_has_the_peaks(ctx: Context) -> None:
    owncast(LIVE, ADMIN_LIVE)
    data = await ADAPTER.fetch("viewers", CONFIG, {}, ctx)
    assert (data.status, data.primary) == ("ok", {"label": "Viewers", "value": 12})
    assert data.secondary == [{"label": "Peak this session", "value": 44}, {"label": "Peak ever", "value": 112}]
    assert data.metrics == {"viewers": 12.0}


@respx.mock
async def test_the_viewers_of_an_offline_stream_are_none_even_if_the_server_still_counts(ctx: Context) -> None:
    owncast(OFFLINE, {**ADMIN_OFFLINE, "viewerCount": 3})
    data = await ADAPTER.fetch("viewers", CONFIG, {}, ctx)
    assert (data.status, data.primary["value"], data.metrics) == ("unknown", 0, {"viewers": 0.0})


@respx.mock
async def test_disconnecting_posts_with_the_key_and_a_refusal_is_not_swallowed(ctx: Context) -> None:
    route = respx.post(f"{BASE}/api/admin/disconnect").mock(return_value=httpx.Response(
        200, json={"message": "inbound stream disconnected", "success": True}))
    assert await ADAPTER.action("stream", "disconnect", {}, CONFIG, {}, ctx) == "The broadcaster is disconnected."
    assert route.calls.last.request.headers["authorization"].startswith("Basic ")
    route.mock(return_value=httpx.Response(401, text="Unauthorized"))
    with pytest.raises(AuthFailed):
        await ADAPTER.action("stream", "disconnect", {}, CONFIG, {}, ctx)
    with pytest.raises(AuthFailed):
        await ADAPTER.action("stream", "disconnect", {}, PUBLIC_ONLY, {}, ctx)
    with pytest.raises(AdapterError) as failure:
        await ADAPTER.action("stream", "delete", {}, CONFIG, {}, ctx)
    assert failure.value.code == "no_such_action"


@respx.mock
async def test_the_test_names_the_version_and_checks_the_key_when_there_is_one(ctx: Context) -> None:
    respx.get(f"{BASE}/api/status").mock(return_value=httpx.Response(200, json=LIVE))
    admin = respx.get(f"{BASE}/api/admin/status").mock(return_value=httpx.Response(401, text="Unauthorized"))
    assert await ADAPTER.test(PUBLIC_ONLY, ctx) == "Owncast 0.3.0 answers, the stream is live."
    assert await ADAPTER.running_version(PUBLIC_ONLY, fresh()) == "0.3.0"
    assert not admin.called
    with pytest.raises(AuthFailed) as failure:
        await ADAPTER.test(CONFIG, fresh())
    assert "stream key" in str(failure.value)
    admin.mock(return_value=httpx.Response(200, json=ADMIN_OFFLINE))
    respx.get(f"{BASE}/api/status").mock(return_value=httpx.Response(200, json=OFFLINE))
    assert await ADAPTER.test(CONFIG, fresh()) == "Owncast 0.3.0 answers, the stream is offline."


@respx.mock
async def test_something_else_at_the_address_is_not_taken_for_owncast(ctx: Context) -> None:
    respx.get(f"{BASE}/api/status").mock(return_value=httpx.Response(404, text="404 page not found"))
    with pytest.raises(AdapterError) as failure:
        await ADAPTER.test(PUBLIC_ONLY, ctx)
    assert failure.value.code == "not_owncast"
    respx.get(f"{BASE}/api/status").mock(return_value=httpx.Response(200, json={"hello": "world"}))
    with pytest.raises(AdapterError) as failure:
        await ADAPTER.test(PUBLIC_ONLY, fresh())
    assert failure.value.code == "not_owncast"
    respx.get(f"{BASE}/api/status").mock(return_value=httpx.Response(200, text="<html></html>"))
    with pytest.raises(AdapterError) as failure:
        await ADAPTER.test(PUBLIC_ONLY, fresh())
    assert failure.value.code == "not_json"


@respx.mock
async def test_an_unreachable_owncast(ctx: Context) -> None:
    respx.get(f"{BASE}/api/status").mock(side_effect=httpx.ConnectError("connection refused"))
    with pytest.raises(Unreachable):
        await ADAPTER.fetch("stream", PUBLIC_ONLY, {}, ctx)


def test_the_demo_fills_every_card() -> None:
    for tick in range(0, 400, 20):
        assert ADAPTER.demo("stream", {}, tick).primary
        assert ADAPTER.demo("viewers", {}, tick).primary
