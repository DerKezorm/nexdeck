"""Issue #32: the M3U Editor cards against the answers of its API.

The answers are shaped after what M3U Editor 0.13.1 sent on a test instance
with a made-up playlist, a made-up guide, viewers on the embedded proxy and
three recordings; the refusals after the same instance. Every moment is
counted from the moment the test runs, so nothing here turns red on a date.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context

URL = "https://m3u.example.com"
# Built when the test runs: a token-shaped literal stops the scanners before a push.
TOKEN = "|".join(("1", "made-up-for-these-tests"))
CONFIG = {"url": URL, "api_key": TOKEN}
M3U = get_adapter("m3ueditor")
SOURCE = "a2eb6236-522a-48dd-9df7-16676b01909c"
GUIDE = "a2eb6236-64e3-44ae-a36e-5639ff19baf3"


def _ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


def _at(**delta: float) -> str:
    """A moment with its offset, as M3U Editor writes most of them."""
    return (datetime.now(UTC) + timedelta(**delta)).astimezone().isoformat(timespec="seconds")


def _utc_plain(**delta: float) -> str:
    """A moment as the proxy writes it: UTC, without a zone."""
    return (datetime.now(UTC) + timedelta(**delta)).strftime("%Y-%m-%d %H:%M:%S")


def _playlist(name: str = "Example TV", uuid: str = SOURCE, kind: str = "playlist", **extra: Any) -> dict[str, Any]:
    source = kind == "playlist"
    return {
        "name": name, "uuid": uuid, "type": kind, "total_channels": 4, "enabled_channels": 4, "live_channels": 4,
        "vod_channels": 0, "groups_count": 4, "proxy_enabled": True, "active_streams": 0,
        "last_sync": _at(hours=-2) if source else None, "status": "completed" if source else None,
        "source_type": "unknown" if source else None, **extra,
    }


def _guide(name: str = "Example Guide", uuid: str = GUIDE, **extra: Any) -> dict[str, Any]:
    return {"name": name, "uuid": uuid, "channel_count": 3, "last_sync": _at(hours=-2), "status": "completed",
            "source_type": "url", "is_processing": False, **extra}


def _client(name: str = "admin") -> dict[str, Any]:
    return {"ip": "172.17.0.1", "username": name, "connected_at": _utc_plain(minutes=-6), "duration": "6 minutes",
            "bytes_received": "26.25 MB", "bandwidth": "N/A", "is_active": True}


def _stream(number: int, title: str, clients: list[dict[str, Any]], kbps: float = 5905.56, **extra: Any) -> dict[str, Any]:
    return {
        "stream_id": f"stream{number}", "source_url": f"http://172.17.0.1:8088/ch{number}.ts",
        "current_url": f"http://172.17.0.1:8088/ch{number}.ts", "format": "LIVE CONTINUOUS",
        "status": "active" if clients else "idle", "client_count": len(clients), "bandwidth_kbps": kbps,
        "bytes_transferred": "26.25 MB", "uptime": "6 minutes", "started_at": _utc_plain(minutes=-6),
        "process_running": bool(clients),
        "model": {"type": "channel", "id": str(number), "channel_number": None, "playlist_uuid": SOURCE, "title": title,
                  "logo": f"{URL}/placeholder.png"},
        "clients": clients, "has_failover": False, "error_count": 0, "segments_served": 0, "transcoding": False,
        "transcoding_format": None, "failover_urls": [], "failover_resolver_url": None, "current_failover_index": -1,
        "failover_attempts": 0, "last_failover_time": None, "using_failover": False, **extra,
    }


def _streams(*streams: dict[str, Any]) -> respx.Route:
    clients = sum(len(s["clients"]) for s in streams)
    return respx.get(f"{URL}/proxy/streams/active").mock(return_value=httpx.Response(200, json={
        "success": True, "streams": list(streams),
        "globalStats": {"total_streams": len(streams), "active_streams": sum(1 for s in streams if s["clients"]),
                        "total_clients": clients, "total_bandwidth_kbps": round(sum(s["bandwidth_kbps"] for s in streams), 2),
                        "avg_clients_per_stream": "1.50"},
        "systemStats": []}))


def _recording(number: int, channel: int, status: str, start: dict[str, float], end: dict[str, float],
               title: str | None = None, **extra: Any) -> dict[str, Any]:
    return {
        "id": number, "channel": channel, "start_time": _at(**start), "end_time": _at(**end), "task_id": None,
        "custom_properties": {
            "status": status,
            "program": {"id": None, "tvg_id": None, "title": title, "sub_title": None, "description": None,
                        "start_time": _at(**start), "end_time": _at(**end), "season": None, "episode": None},
            "season": None, "episode": None, "rating": None, "poster_url": None, "file_url": None, "output_file_url": None,
            "file_name": None, "bytes_written": None, "started_at": None, "ended_at": None, "interrupted_reason": None,
            "uuid": f"rec-{number}", **extra,
        },
    }


def _channel(number: int, title: str) -> respx.Route:
    return respx.get(f"{URL}/channel/{number}").mock(return_value=httpx.Response(200, json={
        "success": True, "data": {"id": number, "title": title, "name": title, "enabled": True, "is_vod": False,
                                  "group_title": "News", "playlist": {"id": 1, "name": "Example TV", "uuid": SOURCE}}}))


def _lists(playlists: list[dict[str, Any]] | None = None, guides: list[dict[str, Any]] | None = None) -> None:
    respx.get(f"{URL}/user/playlists").mock(return_value=httpx.Response(200, json=[_playlist()] if playlists is None else playlists))
    respx.get(f"{URL}/user/epgs").mock(return_value=httpx.Response(200, json=[_guide()] if guides is None else guides))


# -- the overview --------------------------------------------------------------


@respx.mock
async def test_the_overview_counts_streams_viewers_and_the_channels_of_real_playlists_only() -> None:
    """A custom playlist is made of the channels of the real ones; counting it too counted them twice."""
    _lists([_playlist(), _playlist("Family", "custom-1", "custom_playlist", enabled_channels=3, total_channels=3)])
    route = _streams(_stream(1, "Example News", [_client(), _client("kids")]), _stream(2, "Example Sport", [_client()], kbps=6548.06))
    card = await M3U.fetch("overview", CONFIG, {}, _ctx())
    assert route.calls[0].request.headers["Authorization"] == f"Bearer {TOKEN}"
    assert route.calls[0].request.headers["Accept"] == "application/json"
    assert card.status == "ok"
    assert card.primary == {"label": "Streams", "value": 2}
    assert card.secondary == [{"label": "Viewers", "value": 3}, {"label": "Bandwidth", "value": "12.5 Mbit/s"},
                              {"label": "Playlists", "value": 2}, {"label": "Channels", "value": 4}, {"label": "Guides", "value": 1}]
    assert card.metrics == {"streams": 2.0, "viewers": 3.0}
    assert card.meta["status_reason"] == ""


@respx.mock
async def test_a_failed_an_old_and_a_never_synced_source_turn_the_overview_amber() -> None:
    _lists(
        [_playlist(status="failed"), _playlist("Old TV", "old", last_sync=_at(hours=-80)), _playlist("New TV", "new", last_sync=None, status="completed"),
         _playlist("Busy TV", "busy", status="processing", last_sync=None)],
        [_guide(last_sync=_at(hours=-30))],
    )
    _streams()
    card = await M3U.fetch("overview", CONFIG, {}, _ctx())
    assert card.status == "warn"
    assert card.meta["status_reason"] == "Example TV: the last sync failed. · Old TV: last synced 3 d ago. · New TV: never synced."
    card = await M3U.fetch("overview", CONFIG, {"stale_hours": 24}, _ctx())
    assert card.meta["status_reason"].endswith("Example Guide: last synced 1 d ago.")


@respx.mock
async def test_without_the_proxy_integration_the_overview_says_so_and_stays_green() -> None:
    """Both proxy routes are only there while the proxy integration is on."""
    _lists()
    respx.get(f"{URL}/proxy/streams/active").mock(return_value=httpx.Response(404, json={"message": "Not found."}))
    card = await M3U.fetch("overview", CONFIG, {}, _ctx())
    assert card.status == "ok"
    assert card.primary == {"label": "Streams", "value": 0}
    assert [part["label"] for part in card.secondary] == ["Viewers", "Playlists", "Channels", "Guides"]
    assert card.meta["status_reason"] == "The stream proxy is switched off in M3U Editor."
    streams = await M3U.fetch("streams", CONFIG, {}, _ctx())
    assert streams.items == [] and streams.meta["empty"] == "The stream proxy is switched off in M3U Editor."


@respx.mock
async def test_a_proxy_that_does_not_answer_turns_the_overview_amber_and_breaks_the_streams_card() -> None:
    _lists()
    respx.get(f"{URL}/proxy/streams/active").mock(return_value=httpx.Response(200, json={
        "success": False, "error": "Unknown error connecting to m3u-proxy"}))
    card = await M3U.fetch("overview", CONFIG, {}, _ctx())
    assert card.status == "warn"
    assert card.meta["status_reason"] == "The stream proxy does not answer."
    with pytest.raises(AdapterError) as caught:
        await M3U.fetch("streams", CONFIG, {}, _ctx())
    assert caught.value.code == "proxy_down"


# -- active streams ------------------------------------------------------------


@respx.mock
async def test_the_streams_show_channel_viewers_bandwidth_and_never_an_address() -> None:
    """Measured: ``proxy_enabled`` stays false for the embedded proxy while it carries streams,
    so the card goes by the streams themselves. ``started_at`` is UTC without a zone."""
    _streams(_stream(2, "Example Sport", [_client("kids")], kbps=6548.06),
             _stream(1, "Example News", [_client(), _client("kids")]),
             _stream(3, "Example Docs", [], kbps=0))
    card = await M3U.fetch("streams", CONFIG, {}, _ctx())
    assert [(row["title"], row["subtitle"], row["value"], row["status"]) for row in card.items] == [
        ("Example News", "2 viewer(s) · admin, kids · started 6 min ago", "5.9 Mbit/s", "ok"),
        ("Example Sport", "1 viewer(s) · kids · started 6 min ago", "6.5 Mbit/s", "ok"),
        ("Example Docs", "0 viewer(s) · started 6 min ago", "Idle", "unknown"),
    ]
    assert card.secondary == [{"label": "Viewers", "value": 3}, {"label": "Bandwidth", "value": "12.5 Mbit/s"}]
    assert "172.17.0.1" not in repr(card.model_dump())
    hidden = await M3U.fetch("streams", CONFIG, {"viewers": False}, _ctx())
    assert hidden.items[0]["subtitle"] == "2 viewer(s) · started 6 min ago"


@respx.mock
async def test_a_stream_on_a_failover_source_or_with_errors_turns_amber() -> None:
    _streams(_stream(1, "Example News", [_client()], using_failover=True, current_failover_index=1),
             _stream(2, "Example Sport", [_client()], error_count=3, transcoding=True))
    card = await M3U.fetch("streams", CONFIG, {}, _ctx())
    assert card.status == "warn"
    assert [row["subtitle"] for row in card.items] == [
        "1 viewer(s) · admin · started 6 min ago · On a failover source",
        "1 viewer(s) · admin · started 6 min ago · 3 error(s) · Transcoding",
    ]
    assert {row["status"] for row in card.items} == {"warn"}


@respx.mock
async def test_a_start_time_far_ahead_shows_no_age_rather_than_a_wrong_one() -> None:
    _streams(_stream(1, "Example News", [_client()], started_at=_utc_plain(hours=2)))
    card = await M3U.fetch("streams", CONFIG, {}, _ctx())
    assert card.items[0]["subtitle"] == "1 viewer(s) · admin"


# -- playlists and guides ------------------------------------------------------


@respx.mock
async def test_playlists_show_channels_groups_and_sync_and_only_a_real_one_has_a_button() -> None:
    _lists([
        _playlist(vod_channels=1, total_channels=5, enabled_channels=5, groups_count=5, active_streams=1),
        _playlist("Broken TV", "broken", status="failed", last_sync=_at(minutes=-10)),
        _playlist("Busy TV", "busy", status="processing"),
        _playlist("Family", "custom-1", "custom_playlist", enabled_channels=3, total_channels=3, groups_count=1),
    ])
    card = await M3U.fetch("playlists", CONFIG, {}, _ctx())
    assert [(row["title"], row["subtitle"], row["value"], row["status"]) for row in card.items] == [
        ("Example TV", "5 of 5 channels on · 1 VOD · 5 groups · 1 streaming · synced 2 h ago", "Synced", "ok"),
        ("Broken TV", "4 of 4 channels on · 4 groups · last try 10 min ago", "Failed", "bad"),
        ("Busy TV", "4 of 4 channels on · 4 groups · synced 2 h ago", "Syncing", "ok"),
        ("Family", "Custom playlist · 3 of 3 channels on · 1 groups", "", "ok"),
    ]
    assert [[a.id for a in row.get("actions", [])] for row in card.items] == [["sync"], ["sync"], [], []]
    assert card.items[0]["actions"][0].params == {"uuid": SOURCE}
    assert card.status == "warn"


@respx.mock
async def test_guides_show_channels_and_sync_and_one_being_read_has_no_button() -> None:
    _lists(guides=[_guide(), _guide("Broken Guide", "broken", channel_count=0, status="failed", last_sync=_at(minutes=-1)),
                   _guide("Busy Guide", "busy", is_processing=True), _guide("New Guide", "new", last_sync=None, status="pending")])
    card = await M3U.fetch("epgs", CONFIG, {}, _ctx())
    assert [(row["title"], row["subtitle"], row["value"], row["status"]) for row in card.items] == [
        ("Example Guide", "3 channels · synced 2 h ago", "Synced", "ok"),
        ("Broken Guide", "0 channels · last try 1 min ago", "Failed", "bad"),
        ("Busy Guide", "3 channels · synced 2 h ago", "Syncing", "ok"),
        ("New Guide", "3 channels · Never synced", "Pending", "ok"),
    ]
    assert [[a.id for a in row.get("actions", [])] for row in card.items] == [["sync"], ["sync"], [], []]


# -- recordings ----------------------------------------------------------------


@respx.mock
async def test_recordings_running_first_then_planned_then_the_last_ones_with_channel_names() -> None:
    respx.get(f"{URL}/recordings/").mock(return_value=httpx.Response(200, json=[
        _recording(1, 3, "completed", {"minutes": -40}, {"minutes": -5}, bytes_written=13_631_488),
        _recording(2, 1, "recording", {"minutes": -5}, {"minutes": 20}, title="Example News hour 3"),
        _recording(3, 2, "scheduled", {"hours": 24}, {"hours": 25}),
        _recording(4, 2, "scheduled", {"hours": 3}, {"hours": 4}, title="Cup Final"),
        _recording(5, 3, "failed", {"hours": -30}, {"hours": -29}, interrupted_reason="Stream ended early"),
    ]))
    _channel(1, "Example News")
    _channel(2, "Example Sport")
    respx.get(f"{URL}/channel/3").mock(return_value=httpx.Response(404, json={"success": False}))
    card = await M3U.fetch("recordings", CONFIG, {}, _ctx())
    assert [(row["title"], row["subtitle"], row["value"], row["status"]) for row in card.items] == [
        ("Example News hour 3", "Example News · ends in 20 min", "Recording", "ok"),
        ("Cup Final", "Example Sport", "in 3 h", "ok"),
        ("Example Sport", "Example Sport", "in 24 h", "ok"),
        ("?", "Channel 3 · ended 5 min ago · 13.0 MB", "Done", "ok"),
        ("?", "Channel 3 · ended 1 d ago · Stream ended early", "Failed", "bad"),
    ]
    assert card.secondary == [{"label": "Recording", "value": 1}, {"label": "Scheduled", "value": 2}]
    assert card.status == "warn"
    upcoming = await M3U.fetch("recordings", CONFIG, {"show": "upcoming", "limit": 2}, _ctx())
    assert [row["value"] for row in upcoming.items] == ["Recording", "in 3 h"]


@respx.mock
async def test_without_a_dvr_the_recordings_card_says_what_to_set_up() -> None:
    """Measured: 403 with the same words for an account without a DVR and for a token without View."""
    respx.get(f"{URL}/recordings/").mock(return_value=httpx.Response(403, json={
        "detail": "You do not have permission to perform this action."}))
    with pytest.raises(AdapterError) as caught:
        await M3U.fetch("recordings", CONFIG, {}, _ctx())
    assert caught.value.code == "no_dvr"
    assert "No DVR is set up" in str(caught.value)


# -- refusals ------------------------------------------------------------------


@respx.mock
async def test_a_refused_token_and_a_login_page_are_told_apart() -> None:
    respx.get(f"{URL}/user/playlists").mock(return_value=httpx.Response(401, json={"message": "Unauthenticated."}))
    with pytest.raises(AuthFailed):
        await M3U.test(CONFIG, _ctx())
    respx.get(f"{URL}/user/playlists").mock(return_value=httpx.Response(200, text="<html>login</html>"))
    with pytest.raises(AdapterError) as caught:
        await M3U.fetch("playlists", CONFIG, {}, _ctx())
    assert caught.value.code == "not_json"


@respx.mock
async def test_the_connection_test_counts_playlists_and_guides() -> None:
    _lists([_playlist(), _playlist("Family", "custom-1", "custom_playlist")])
    assert await M3U.test(CONFIG, _ctx()) == "M3U Editor answers · 2 playlist(s) · 1 guide(s)"


# -- the buttons ---------------------------------------------------------------


@respx.mock
async def test_sync_sends_force_as_one_to_the_playlist_and_the_guide() -> None:
    """Measured: ``force=true`` is turned away with 422 by Laravel's boolean check."""
    _lists()
    playlist = respx.get(f"{URL}/playlist/{SOURCE}/sync").mock(return_value=httpx.Response(200, json={
        "message": 'Playlist "Example TV" is currently being synced...'}))
    guide = respx.get(f"{URL}/epg/{GUIDE}/sync").mock(return_value=httpx.Response(200, json={
        "message": 'EPG "Example Guide" is currently being synced...'}))
    assert await M3U.action("playlists", "sync", {"uuid": SOURCE}, CONFIG, {}, _ctx()) == "The sync has started."
    assert await M3U.action("epgs", "sync", {"uuid": GUIDE}, CONFIG, {}, _ctx()) == "The sync has started."
    assert playlist.calls[0].request.url.params["force"] == "1"
    assert guide.calls[0].request.url.params["force"] == "1"


@respx.mock
async def test_sync_only_reaches_a_uuid_the_token_lists() -> None:
    """The sync route asks no token: the uuid is the key. nexdeck syncs only what the account lists."""
    _lists([_playlist(), _playlist("Family", "custom-1", "custom_playlist")])
    sync = respx.get(url__regex=rf"{URL}/(playlist|epg)/.*/sync").mock(return_value=httpx.Response(200, json={}))
    for uuid in ("someone-elses", "custom-1", GUIDE):
        with pytest.raises(AdapterError) as caught:
            await M3U.action("playlists", "sync", {"uuid": uuid}, CONFIG, {}, _ctx())
        assert caught.value.code == "not_found"
    with pytest.raises(AdapterError):
        await M3U.action("epgs", "sync", {"uuid": SOURCE}, CONFIG, {}, _ctx())
    with pytest.raises(AdapterError):
        await M3U.action("playlists", "sync", {"uuid": "../user"}, CONFIG, {}, _ctx())
    assert sync.call_count == 0


@respx.mock
async def test_a_sixth_sync_in_a_minute_is_told_in_words() -> None:
    _lists()
    respx.get(f"{URL}/playlist/{SOURCE}/sync").mock(return_value=httpx.Response(429, json={"message": "Too Many Attempts."}))
    with pytest.raises(AdapterError) as caught:
        await M3U.action("playlists", "sync", {"uuid": SOURCE}, CONFIG, {}, _ctx())
    assert caught.value.code == "rate_limited"


def test_every_card_has_a_demo() -> None:
    for widget in M3U.widgets:
        data = M3U.demo(widget.kind, {}, 3)
        assert data.items or data.primary, widget.kind
