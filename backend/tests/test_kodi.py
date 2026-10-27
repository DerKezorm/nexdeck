"""Kodi, against what a headless Kodi 18.5 (linuxserver/kodi-headless, 27.10.2026) answered, and Kodi's JSON-RPC documentation for the rest.

Measured: the 401 without the right user and password, ``Application.GetProperties``,
``Player.GetActivePlayers`` as ``[]``, the HTTP 200 carrying ``-32601`` and ``-32603``.
**Not measured**: a running player (``Player.GetItem``, ``Player.GetProperties``) and the
library counts; the rows below follow the wiki, and the names are made up.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context, Unreachable, outbound_client

BASE = "http://kodi.example.com:8080"
CONFIG = {"url": BASE, "username": "kodi", "password": "a-made-up-word"}
OPEN = {"url": BASE}
ADAPTER = get_adapter("kodi")


def fresh() -> Context:
    return Context(outbound_client(guard=False), integration_id=1, widget_id=1, cache={})


@pytest.fixture
def ctx() -> Context:
    return fresh()


APPLICATION = {"muted": False, "name": "Kodi", "version": {"major": 18, "minor": 5, "revision": "20200109-nogitfound", "tag": "stable"}, "volume": 100}
EPISODE = {"type": "episode", "id": 40, "label": "Departure", "title": "Departure", "showtitle": "Harbour Lights", "season": 3, "episode": 4, "year": 2025,
           "thumbnail": "image://video@%2fmedia%2fshow.jpg/", "art": {"poster": "image://poster.jpg/", "fanart": "image://fanart.jpg/"}, "file": "/media/tv/s03e04.mkv"}
SONG = {"type": "song", "label": "Signal", "title": "Signal", "artist": ["Orbital Tide"], "album": "Copper Sky", "thumbnail": "image://cover.jpg/", "art": {}}
PLAYING = {"time": {"hours": 0, "minutes": 26, "seconds": 15, "milliseconds": 0}, "totaltime": {"hours": 1, "minutes": 45, "seconds": 0, "milliseconds": 0},
           "percentage": 25.0, "speed": 1}
PAUSED = {**PLAYING, "speed": 0}


def kodi(answers: dict[str, Any], seen: list[dict[str, Any]] | None = None, password: str = "a-made-up-word") -> respx.Route:
    """Kodi's one address: the method decides, an error is a 200 with the fault in it."""
    def reply(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if seen is not None:
            seen.append(body)
        if password and request.headers.get("authorization") is None:
            return httpx.Response(401)
        answer = answers.get(body["method"], KeyError)
        if answer is KeyError:
            return httpx.Response(200, json={"id": 1, "jsonrpc": "2.0", "error": {"code": -32601, "message": "Method not found."}})
        if isinstance(answer, tuple):
            return httpx.Response(200, json={"id": 1, "jsonrpc": "2.0", "error": {"code": answer[0], "message": answer[1]}})
        return httpx.Response(200, json={"id": 1, "jsonrpc": "2.0", "result": answer})
    return respx.post(f"{BASE}/jsonrpc").mock(side_effect=reply)


def video(speed: dict[str, Any] = PLAYING, item: dict[str, Any] = EPISODE) -> dict[str, Any]:
    return {"Player.GetActivePlayers": [{"playerid": 1, "playertype": "internal", "type": "video"}], "Player.GetItem": {"item": item},
            "Player.GetProperties": speed, "Application.GetProperties": {**APPLICATION, "volume": 65}}


@respx.mock
async def test_an_episode_plays_with_its_show_and_number_its_progress_and_time_left(ctx: Context) -> None:
    seen: list[dict[str, Any]] = []
    kodi(video(), seen)
    data = await ADAPTER.fetch("nowplaying", CONFIG, {}, ctx)
    row = data.items[0]
    assert (row["title"], row["subtitle"], row["progress"], row["remaining"], row["state"]) == ("Departure", "Harbour Lights S03E04", 25.0, "1h 18m", "playing")
    assert row["art"] == "proxy:/image/image%3A%2F%2Fposter.jpg%2F"
    assert row["backdrop"] == "proxy:/image/image%3A%2F%2Ffanart.jpg%2F"
    assert data.metrics == {"players": 1.0}
    assert [call["method"] for call in seen] == ["Player.GetActivePlayers", "Player.GetItem", "Player.GetProperties"]
    assert seen[1]["params"] == {"playerid": 1, "properties": ["title", "showtitle", "season", "episode", "artist", "album", "year", "thumbnail", "art", "file"]}
    without = await ADAPTER.fetch("nowplaying", CONFIG, {"backdrop": False}, fresh())
    assert "backdrop" not in without.items[0]


@respx.mock
async def test_a_song_names_the_artist_and_album_and_falls_back_to_the_thumbnail_for_its_picture(ctx: Context) -> None:
    kodi(video(PAUSED, SONG))
    row = (await ADAPTER.fetch("nowplaying", CONFIG, {}, ctx)).items[0]
    assert (row["title"], row["subtitle"], row["state"]) == ("Signal", "Orbital Tide · Copper Sky", "paused")
    assert row["art"] == "proxy:/image/image%3A%2F%2Fcover.jpg%2F"


@respx.mock
async def test_a_film_without_a_title_is_named_by_its_file_and_a_picture_slideshow_is_not_listed(ctx: Context) -> None:
    answers = video(item={"type": "movie", "label": "", "title": "", "year": 1999, "file": "C:\\Films\\Quiet.Harbour.1999.mkv"})
    answers["Player.GetActivePlayers"].append({"playerid": 2, "type": "picture"})
    kodi(answers)
    data = await ADAPTER.fetch("nowplaying", CONFIG, {}, ctx)
    assert [(row["title"], row["subtitle"]) for row in data.items] == [("Quiet.Harbour.1999.mkv", "1999")]


@respx.mock
async def test_nothing_playing_is_an_empty_list_and_an_idle_status_with_no_play_buttons(ctx: Context) -> None:
    kodi({"Player.GetActivePlayers": [], "Application.GetProperties": APPLICATION})
    nothing = await ADAPTER.fetch("nowplaying", CONFIG, {}, ctx)
    assert (nothing.items, nothing.metrics) == ([], {"players": 0.0})
    status = await ADAPTER.fetch("status", CONFIG, {}, fresh())
    assert (status.status, status.primary) == ("ok", {"label": "Kodi", "value": "Idle"})
    assert [action.id for action in status.actions] == ["mute", "scan"]
    assert {"label": "Version", "value": "18.5"} in status.secondary and {"label": "Volume", "value": "100%"} in status.secondary


@respx.mock
async def test_the_status_card_offers_pause_or_play_by_state_and_a_confirmed_stop_with_the_player_id(ctx: Context) -> None:
    kodi(video())
    playing = await ADAPTER.fetch("status", CONFIG, {}, ctx)
    assert (playing.primary["value"], {"label": "Now", "value": "Departure"} in playing.secondary) == ("Playing", True)
    assert [(a.id, a.label, a.confirm, a.params) for a in playing.actions] == [
        ("playpause", "Pause", False, {"playerid": 1}), ("stop", "Stop", True, {"playerid": 1}), ("mute", "Mute", False, {}),
        ("scan", "Update the video library", False, {})]
    kodi(video(PAUSED))
    paused = await ADAPTER.fetch("status", CONFIG, {}, fresh())
    assert (paused.primary["value"], paused.actions[0].label) == ("Paused", "Play")


def test_a_muted_kodi_offers_unmute_and_says_so_in_the_volume() -> None:
    card = ADAPTER.status_card([], {**APPLICATION, "muted": True, "volume": 40})
    assert card.actions[0].label == "Unmute" and {"label": "Volume", "value": "40% (muted)"} in card.secondary


@respx.mock
async def test_the_buttons_call_the_methods_of_kodi_with_the_player(ctx: Context) -> None:
    seen: list[dict[str, Any]] = []
    kodi({"Player.PlayPause": {"speed": 0}, "Player.Stop": "OK", "Application.SetMute": True, "VideoLibrary.Scan": "OK"}, seen)
    await ADAPTER.action("status", "playpause", {"playerid": 1}, CONFIG, {}, ctx)
    await ADAPTER.action("status", "stop", {"playerid": "2"}, CONFIG, {}, ctx)
    await ADAPTER.action("status", "mute", {}, CONFIG, {}, ctx)
    await ADAPTER.action("status", "scan", {}, CONFIG, {}, ctx)
    assert [(call["method"], call["params"]) for call in seen] == [
        ("Player.PlayPause", {"playerid": 1, "play": "toggle"}), ("Player.Stop", {"playerid": 2}),
        ("Application.SetMute", {"mute": "toggle"}), ("VideoLibrary.Scan", {})]
    for params in ({}, {"playerid": "x"}):
        with pytest.raises(AdapterError) as failure:
            await ADAPTER.action("status", "stop", params, CONFIG, {}, ctx)
        assert failure.value.code == "missing_param"
    with pytest.raises(AdapterError) as failure:
        await ADAPTER.action("status", "shutdown", {}, CONFIG, {}, ctx)
    assert failure.value.code == "no_such_action"


@respx.mock
async def test_the_library_counts_what_kodi_has_and_leaves_out_what_it_cannot_say(ctx: Context) -> None:
    def total(count: int) -> dict[str, Any]:
        return {"limits": {"start": 0, "end": 1, "total": count}, "movies": []}
    kodi({"VideoLibrary.GetMovies": total(1284), "VideoLibrary.GetTVShows": total(96), "VideoLibrary.GetEpisodes": total(3190),
          "AudioLibrary.GetAlbums": (-32603, "Internal error."), "AudioLibrary.GetSongs": (-32601, "Method not found.")})
    data = await ADAPTER.fetch("library", CONFIG, {}, ctx)
    assert data.primary == {"label": "Movies", "value": 1284}
    assert data.secondary == [{"label": "Series", "value": 96}, {"label": "Episodes", "value": 3190}]


@respx.mock
async def test_a_kodi_without_a_library_says_so_as_measured(ctx: Context) -> None:
    # The headless Kodi 18.5 answered -32603 "Internal error." to every library call.
    kodi({name: (-32603, "Internal error.") for name in ("VideoLibrary.GetMovies", "VideoLibrary.GetTVShows", "VideoLibrary.GetEpisodes",
                                                        "AudioLibrary.GetAlbums", "AudioLibrary.GetSongs")})
    with pytest.raises(AdapterError) as failure:
        await ADAPTER.fetch("library", CONFIG, {}, ctx)
    assert failure.value.code == "kodi_-32603" and "Internal error." in str(failure.value)


@respx.mock
async def test_the_test_names_the_version_and_sends_the_user_and_password_only_when_a_password_is_set(ctx: Context) -> None:
    route = kodi({"Application.GetProperties": APPLICATION})
    assert await ADAPTER.test(CONFIG, ctx) == "Kodi 18.5 answers."
    assert await ADAPTER.running_version(CONFIG, fresh()) == "18.5"
    assert route.calls.last.request.headers["authorization"].startswith("Basic ")
    open_route = kodi({"Application.GetProperties": APPLICATION}, password="")
    await ADAPTER.test(OPEN, fresh())
    assert "authorization" not in open_route.calls.last.request.headers


@respx.mock
async def test_the_picture_is_asked_for_with_the_password_and_not_the_browser(ctx: Context) -> None:
    headers = ADAPTER.image_headers(CONFIG)
    assert headers["Authorization"].startswith("Basic ") and ADAPTER.image_headers(OPEN) == {}


@respx.mock
async def test_a_missing_or_wrong_password_is_refused_credentials(ctx: Context) -> None:
    kodi({"Application.GetProperties": APPLICATION})
    with pytest.raises(AuthFailed) as failure:
        await ADAPTER.test(OPEN, ctx)
    assert "wants a user name" in str(failure.value)
    respx.post(f"{BASE}/jsonrpc").mock(return_value=httpx.Response(401))
    with pytest.raises(AuthFailed) as failure:
        await ADAPTER.test(CONFIG, fresh())
    assert "rejected" in str(failure.value)


@respx.mock
async def test_an_error_in_a_200_is_an_error_and_something_else_at_the_address_is_not_kodi(ctx: Context) -> None:
    kodi({"Application.GetProperties": (-32601, "Method not found.")})
    with pytest.raises(AdapterError) as failure:
        await ADAPTER.test(CONFIG, ctx)
    assert failure.value.code == "kodi_-32601"
    respx.post(f"{BASE}/jsonrpc").mock(return_value=httpx.Response(404, text="nothing"))
    with pytest.raises(AdapterError) as failure:
        await ADAPTER.test(CONFIG, fresh())
    assert failure.value.code == "not_kodi"
    respx.post(f"{BASE}/jsonrpc").mock(return_value=httpx.Response(200, json={"hello": "world"}))
    with pytest.raises(AdapterError) as failure:
        await ADAPTER.test(CONFIG, fresh())
    assert failure.value.code == "not_kodi"
    respx.post(f"{BASE}/jsonrpc").mock(return_value=httpx.Response(200, text="<html></html>"))
    with pytest.raises(AdapterError) as failure:
        await ADAPTER.test(CONFIG, fresh())
    assert failure.value.code == "not_json"


@respx.mock
async def test_an_unreachable_kodi(ctx: Context) -> None:
    respx.post(f"{BASE}/jsonrpc").mock(side_effect=httpx.ConnectError("connection refused"))
    with pytest.raises(Unreachable):
        await ADAPTER.fetch("status", CONFIG, {}, ctx)


def test_the_demo_fills_every_card() -> None:
    for tick in range(0, 300, 15):
        assert ADAPTER.demo("nowplaying", {}, tick).items
        assert ADAPTER.demo("status", {}, tick).primary
        assert ADAPTER.demo("library", {}, tick).primary
