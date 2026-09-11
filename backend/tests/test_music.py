"""The music player: what it reads from a media server, and how the sound gets through.

The answers below have the shape Jellyfin 10.11.11 and Plex 1.43.3 gave on
11.09.2026, with the names and ids replaced. The router tests hold the three
things that break without a sound: Range reaching the media server, the right
to act on the board, and addresses that only fetch what a playlist names.
"""

from __future__ import annotations

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.adapters import get_adapter
from app.adapters.base import AdapterError, Context
from app.adapters.music import ShelfQuery, SoundRequest, read_formats
from tests.conftest import CSRF, create_user, login, setup_admin

JELLYFIN = "http://jellyfin.example.com:8096"
PLEX = "http://plex.example.com:32400"
JF_CONFIG = {"url": JELLYFIN, "api_key": "k"}
PLEX_CONFIG = {"url": PLEX, "token": "t"}
ADMIN_ID = "a1b2c3"
USERS = [
    {"Id": "u9", "Name": "Kim", "Policy": {"IsAdministrator": False}},
    {"Id": ADMIN_ID, "Name": "Alex", "Policy": {"IsAdministrator": True}},
]


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


def _users() -> None:
    respx.get(f"{JELLYFIN}/Users").mock(return_value=httpx.Response(200, json=USERS))


# -- jellyfin ------------------------------------------------------------------


@respx.mock
async def test_jellyfin_album_page_has_covers_only_where_the_server_has_them(ctx: Context) -> None:
    """⚠️ Measured: an album without a cover answers its image address with 404."""
    _users()
    listing = respx.get(f"{JELLYFIN}/Users/{ADMIN_ID}/Items").mock(return_value=httpx.Response(200, json={
        "Items": [
            {"Id": "al1", "Name": "Slow Tide", "AlbumArtist": "Harbour Brass", "AlbumArtists": [{"Id": "ar1"}],
             "ProductionYear": 2025, "ChildCount": 12, "ImageTags": {"Primary": "tag"}},
            {"Id": "al2", "Name": "Low Light", "Artists": ["Kim Aster"], "ImageTags": {}},
        ],
        "TotalRecordCount": 2964,
    }))
    shelf = await get_adapter("jellyfin").music_shelf(JF_CONFIG, {}, "albums", ShelfQuery(offset=48), ctx)
    assert [album.title for album in shelf.albums] == ["Slow Tide", "Low Light"]
    assert shelf.albums[0].art.startswith("proxy:/Items/al1/Images/Primary")
    assert shelf.albums[0].artist_id == "ar1" and shelf.albums[0].tracks == 12
    assert shelf.albums[1].art == "" and shelf.albums[1].thumb == ""
    assert shelf.albums[1].artist == "Kim Aster"
    assert (shelf.total, shelf.next) == (2964, 50)
    query = dict(listing.calls.last.request.url.params)
    assert query["IncludeItemTypes"] == "MusicAlbum" and query["StartIndex"] == "48"
    assert query["SortBy"] == "DateCreated,SortName" and query["SortOrder"] == "Descending"


@respx.mock
async def test_jellyfin_album_tracks_carry_codec_depth_and_rate(ctx: Context) -> None:
    _users()
    respx.get(f"{JELLYFIN}/Users/{ADMIN_ID}/Items/al1").mock(return_value=httpx.Response(200, json={
        "Id": "al1", "Name": "Slow Tide", "AlbumArtist": "Harbour Brass", "ProductionYear": 2025, "ImageTags": {"Primary": "x"}}))
    respx.get(f"{JELLYFIN}/Users/{ADMIN_ID}/Items").mock(return_value=httpx.Response(200, json={"Items": [{
        "Id": "t1", "Name": "Landfall", "Album": "Slow Tide", "AlbumId": "al1", "AlbumPrimaryImageTag": "x",
        "Artists": ["Harbour Brass", "Kim Aster"], "ArtistItems": [{"Id": "ar1"}], "RunTimeTicks": 2_415_000_000,
        "IndexNumber": 2, "ParentIndexNumber": 1, "ImageTags": {},
        "MediaSources": [{"Container": "flac", "MediaStreams": [
            {"Type": "Audio", "Codec": "flac", "BitDepth": 24, "SampleRate": 48000, "BitRate": 1_706_690}]}],
    }]}))
    shelf = await get_adapter("jellyfin").music_shelf(JF_CONFIG, {}, "album", ShelfQuery(id="al1"), ctx)
    track = shelf.tracks[0]
    assert (shelf.title, shelf.subtitle) == ("Slow Tide", "Harbour Brass · 2025")
    assert track.artist == "Harbour Brass, Kim Aster" and track.duration == 241.5
    assert (track.codec, track.bit_depth, track.sample_rate, track.bitrate) == ("flac", 24, 48000, 1707)
    assert track.art.startswith("proxy:/Items/al1/"), "a track without its own picture takes the album's"


@respx.mock
async def test_jellyfin_original_lets_the_server_decide_by_what_the_browser_plays(ctx: Context) -> None:
    _users()
    sound = await get_adapter("jellyfin").music_source(
        JF_CONFIG, {}, SoundRequest(track_id="t1", formats=("flac", "mp3", "aac")), ctx)
    assert sound.source.url == f"{JELLYFIN}/Audio/t1/universal"
    params = sound.source.params
    containers = params["Container"].split(",")
    assert {"flac", "mp3", "m4a|aac"} <= set(containers)
    # ⚠️ ALAC comes in the same m4a box; a browser that did not name it must not get it as the file.
    assert "m4a|alac" not in containers
    assert params["MaxStreamingBitrate"] == 140_000_000 and params["TranscodingProtocol"] == "http"
    assert params["UserId"] == ADMIN_ID and params["DeviceId"] == "nexdeck"
    assert "StartTimeTicks" not in params and not sound.converted
    assert sound.source.headers["Authorization"].startswith('MediaBrowser Token="k"')


@respx.mock
async def test_jellyfin_less_than_original_converts_and_a_seek_asks_from_a_time(ctx: Context) -> None:
    _users()
    jellyfin = get_adapter("jellyfin")
    low = await jellyfin.music_source(JF_CONFIG, {}, SoundRequest(track_id="t1", quality="low", start=60.5), ctx)
    assert low.converted and low.session
    assert low.source.params["MaxStreamingBitrate"] == 128_000 and low.source.params["AudioBitRate"] == 128_000
    assert low.source.params["StartTimeTicks"] == 605_000_000
    hls = await jellyfin.music_source(JF_CONFIG, {}, SoundRequest(track_id="t1", quality="high", hls=True), ctx)
    assert hls.source.params["TranscodingProtocol"] == "hls" and hls.source.params["MaxStreamingBitrate"] == 320_000


@respx.mock
async def test_jellyfin_an_account_that_is_gone_is_an_error_not_somebody_else(ctx: Context) -> None:
    """Quietly playing as the administrator would show his playlists to whoever set up the card."""
    _users()
    with pytest.raises(AdapterError) as refused:
        await get_adapter("jellyfin").music_shelf(JF_CONFIG, {"account": "gone"}, "playlists", ShelfQuery(), ctx)
    assert refused.value.code == "no_such_account"


@respx.mock
async def test_jellyfin_search_asks_three_small_questions(ctx: Context) -> None:
    """⚠️ Measured: one mixed search for "the" came back as 58 tracks and 2 albums."""
    _users()

    def answer(request: httpx.Request) -> httpx.Response:
        kind = request.url.params["IncludeItemTypes"]
        return httpx.Response(200, json={"Items": [{"Id": f"{kind}-1", "Name": f"The {kind}", "Type": kind}]})

    route = respx.get(f"{JELLYFIN}/Users/{ADMIN_ID}/Items").mock(side_effect=answer)
    shelf = await get_adapter("jellyfin").music_shelf(JF_CONFIG, {}, "search", ShelfQuery(q="the"), ctx)
    assert sorted(call.request.url.params["IncludeItemTypes"] for call in route.calls) == ["Audio", "MusicAlbum", "MusicArtist"]
    assert all(call.request.url.params["SearchTerm"] == "the" for call in route.calls)
    assert [one.id for one in shelf.albums] == ["MusicAlbum-1"]
    assert [one.id for one in shelf.artists] == ["MusicArtist-1"]
    assert [one.id for one in shelf.tracks] == ["Audio-1"]


async def test_jellyfin_hls_piece_never_carries_a_key(ctx: Context) -> None:
    source = await get_adapter("jellyfin").music_hls_part(
        JF_CONFIG, {}, "t1", "hls1/main/3.ts", {"PlaySessionId": "s", "api_key": "stolen", "ApiKey": "x"}, ctx)
    assert source.url == f"{JELLYFIN}/Audio/t1/hls1/main/3.ts"
    assert source.params == {"PlaySessionId": "s"}


# -- plex ------------------------------------------------------------------------


def _plex_track(codec: str, bitrate: int, part: str = "/library/parts/88/1700000000/file.flac") -> None:
    respx.get(f"{PLEX}/library/metadata/501").mock(return_value=httpx.Response(200, json={"MediaContainer": {"Metadata": [{
        "type": "track", "ratingKey": "501", "title": "Landfall",
        "Media": [{"audioCodec": codec, "bitrate": bitrate, "container": codec, "Part": [{"key": part}]}],
    }]}}))


@respx.mock
async def test_plex_plays_the_file_itself_when_the_browser_plays_its_codec(ctx: Context) -> None:
    _plex_track("flac", 930)
    sound = await get_adapter("plex").music_source(PLEX_CONFIG, {}, SoundRequest(track_id="501", formats=("flac", "mp3")), ctx)
    assert sound.source.url == f"{PLEX}/library/parts/88/1700000000/file.flac"
    assert not sound.converted
    # One client identifier, always: Plex keeps a device entry for every one it sees.
    assert sound.source.headers["X-Plex-Client-Identifier"] == "nexdeck"


@respx.mock
async def test_plex_converts_what_the_browser_cannot_play_and_what_is_too_big(ctx: Context) -> None:
    plex = get_adapter("plex")
    _plex_track("alac", 900)
    unplayable = await plex.music_source(PLEX_CONFIG, {}, SoundRequest(track_id="501", formats=("flac", "mp3")), ctx)
    assert unplayable.source.url == f"{PLEX}/music/:/transcode/universal/start.mp3"
    assert unplayable.converted and unplayable.source.params["musicBitrate"] == 320
    assert "X-Plex-Client-Profile-Extra" not in unplayable.source.params, "measured: with a profile Plex answered 400"

    ctx.cache.clear()
    respx.routes.clear()
    _plex_track("flac", 930)
    low = await plex.music_source(PLEX_CONFIG, {}, SoundRequest(track_id="501", quality="low", start=90), ctx)
    assert low.converted and low.source.params["maxAudioBitrate"] == 128 and low.source.params["offset"] == 90

    ctx.cache.clear()
    respx.routes.clear()
    _plex_track("mp3", 128, part="/library/parts/9/1/file.mp3")
    fits = await plex.music_source(PLEX_CONFIG, {}, SoundRequest(track_id="501", quality="low"), ctx)
    assert not fits.converted and fits.source.url.endswith("/file.mp3"), "a track that already fits is not converted again"


@respx.mock
async def test_plex_never_relays_a_key_that_is_not_a_part(ctx: Context) -> None:
    """The key comes from the server and is fetched with the owner's token."""
    _plex_track("flac", 930, part="/:/prefs")
    sound = await get_adapter("plex").music_source(PLEX_CONFIG, {}, SoundRequest(track_id="501"), ctx)
    assert sound.source.url.endswith("/music/:/transcode/universal/start.mp3")


def test_plex_cover_goes_through_the_scaler_with_the_thumb_encoded() -> None:
    art, thumb = get_adapter("plex")._cover("/library/metadata/5/thumb/17")
    assert art.startswith("proxy:/photo/:/transcode?width=800")
    assert thumb.startswith("proxy:/photo/:/transcode?width=240")
    assert "url=%2Flibrary%2Fmetadata%2F5%2Fthumb%2F17" in art
    # The image route refuses anything with a scheme in it.
    assert "://" not in art


@respx.mock
async def test_plex_search_uses_the_library_filter_not_the_hub_search(ctx: Context) -> None:
    """⚠️ Measured: the hub search took 4.3 s and brought films along; the filter 0.3 s."""
    respx.get(f"{PLEX}/library/sections").mock(return_value=httpx.Response(200, json={"MediaContainer": {"Directory": [
        {"key": "3", "type": "movie", "title": "Films"}, {"key": "7", "type": "artist", "title": "Music"}]}}))
    hubs = respx.get(f"{PLEX}/hubs/search").mock(return_value=httpx.Response(200, json={}))

    def answer(request: httpx.Request) -> httpx.Response:
        kind = request.url.params["type"]
        entry = {"9": {"ratingKey": "10", "title": "The Album", "type": "album"},
                 "8": {"ratingKey": "20", "title": "The Artist", "type": "artist"},
                 "10": {"ratingKey": "30", "title": "The Track", "type": "track"}}[kind]
        return httpx.Response(200, json={"MediaContainer": {"Metadata": [entry]}})

    library = respx.get(f"{PLEX}/library/sections/7/all").mock(side_effect=answer)
    shelf = await get_adapter("plex").music_shelf(PLEX_CONFIG, {}, "search", ShelfQuery(q="the"), ctx)
    assert not hubs.called
    assert all(call.request.url.params["title"] == "the" for call in library.calls)
    assert ([one.id for one in shelf.albums], [one.id for one in shelf.artists], [one.id for one in shelf.tracks]) == (["10"], ["20"], ["30"])


def test_plex_jellyfin_and_emby_offer_the_same_card() -> None:
    """One card under one name: what the servers share is written once, and nobody forgets a server."""
    players = {kind: get_adapter(kind).widget("player") for kind in ("plex", "jellyfin", "emby")}
    for kind, player in players.items():
        assert player.renderer == "player", kind
        names = [field.name for field in player.options]
        assert names[:2] == ["idle_art", "idle_pick"], f"{kind} lacks the shared cover settings"
        assert "music_library" in names, kind
    assert [field.name for field in players["jellyfin"].options] == [field.name for field in players["emby"].options]


@respx.mock
async def test_emby_plays_through_the_same_route_with_its_own_key_header(ctx: Context) -> None:
    """Emby runs on Jellyfin's code, unmeasured (no music on the Emby at hand), so at least its request shape is held."""
    config = {"url": "http://emby.example.com:8096", "api_key": "e"}
    respx.get("http://emby.example.com:8096/Users").mock(return_value=httpx.Response(200, json=USERS))
    sound = await get_adapter("emby").music_source(config, {}, SoundRequest(track_id="t1"), ctx)
    assert sound.source.url == "http://emby.example.com:8096/Audio/t1/universal"
    assert sound.source.headers == {"X-Emby-Token": "e"}
    assert sound.source.params["UserId"] == ADMIN_ID


@respx.mock
async def test_jellyfin_random_covers_ride_apart_from_the_newest(ctx: Context) -> None:
    """The items are also the library's "New" tab; a random pick must not end up there."""
    _users()

    def answer(request: httpx.Request) -> httpx.Response:
        params = request.url.params
        if params.get("SortBy") == "Random":
            assert params.get("ImageTypes") == "Primary", "a random pick of albums without covers is a pick of discs"
            return httpx.Response(200, json={"Items": [{"Id": "r1", "Name": "Picked", "ImageTags": {"Primary": "x"}}]})
        if params.get("IncludeItemTypes") == "MusicAlbum":
            return httpx.Response(200, json={"Items": [{"Id": "n1", "Name": "Newest"}], "TotalRecordCount": 1})
        return httpx.Response(200, json={"Items": [], "TotalRecordCount": 5})

    route = respx.get(f"{JELLYFIN}/Users/{ADMIN_ID}/Items").mock(side_effect=answer)
    jellyfin = get_adapter("jellyfin")
    plain = await jellyfin.fetch("player", JF_CONFIG, {}, ctx)
    assert "picks" not in plain.meta["music"]
    assert not any(call.request.url.params.get("SortBy") == "Random" for call in route.calls), "no random pick unless asked for"
    random = await jellyfin.fetch("player", JF_CONFIG, {"idle_pick": "random"}, ctx)
    assert [item["id"] for item in random.items] == ["n1"]
    assert [one["id"] for one in random.meta["music"]["picks"]] == ["r1"]


@respx.mock
async def test_plex_random_covers_come_from_a_random_sort(ctx: Context) -> None:
    respx.get(f"{PLEX}/library/sections").mock(return_value=httpx.Response(200, json={"MediaContainer": {"Directory": [
        {"key": "7", "type": "artist", "title": "Music"}]}}))

    def answer(request: httpx.Request) -> httpx.Response:
        params = request.url.params
        if params.get("sort") == "random":
            return httpx.Response(200, json={"MediaContainer": {"Metadata": [{"ratingKey": "44", "title": "Picked", "thumb": "/t"}]}})
        return httpx.Response(200, json={"MediaContainer": {"Metadata": [{"ratingKey": "1", "title": "Newest"}], "totalSize": 1}})

    respx.get(f"{PLEX}/library/sections/7/all").mock(side_effect=answer)
    data = await get_adapter("plex").fetch("player", PLEX_CONFIG, {"idle_pick": "random"}, ctx)
    assert [item["id"] for item in data.items] == ["1"]
    assert [one["id"] for one in data.meta["music"]["picks"]] == ["44"]


# -- playlists -------------------------------------------------------------------


@respx.mock
async def test_jellyfin_makes_a_playlist_with_query_parameters_and_batches_the_rest(ctx: Context) -> None:
    """The query form is the one Emby knows too; measured on 10.11.11 it works on Jellyfin."""
    _users()
    made = respx.post(f"{JELLYFIN}/Playlists").mock(return_value=httpx.Response(200, json={"Id": "p1"}))
    added = respx.post(f"{JELLYFIN}/Playlists/p1/Items").mock(return_value=httpx.Response(204))
    ids = [f"t{number}" for number in range(120)]
    playlist = await get_adapter("jellyfin").music_playlist_create(JF_CONFIG, {}, "Evening", ids, ctx)
    first = made.calls.last.request.url.params
    assert (playlist.id, first["Name"], first["MediaType"], first["UserId"]) == ("p1", "Evening", "Audio", ADMIN_ID)
    assert first["Ids"].split(",") == ids[:50]
    assert [call.request.url.params["Ids"].split(",") for call in added.calls] == [ids[50:100], ids[100:]]


@respx.mock
async def test_jellyfin_leaves_out_what_the_playlist_already_has(ctx: Context) -> None:
    """⚠️ Measured: Jellyfin adds a track twice when asked, Plex does not."""
    _users()
    respx.get(f"{JELLYFIN}/Playlists/p1/Items").mock(return_value=httpx.Response(200, json={"Items": [{"Id": "t1", "PlaylistItemId": "e1"}]}))
    added = respx.post(f"{JELLYFIN}/Playlists/p1/Items").mock(return_value=httpx.Response(204))
    await get_adapter("jellyfin").music_playlist_add(JF_CONFIG, {}, "p1", ["t1", "t2", "t2"], ctx)
    assert [call.request.url.params["Ids"] for call in added.calls] == ["t2"]


@respx.mock
async def test_jellyfin_renames_through_the_item_and_deletes_only_playlists(ctx: Context) -> None:
    """⚠️ Measured: the playlist route answers an API key with 400; the item route takes the whole item back."""
    _users()
    respx.get(f"{JELLYFIN}/Users/{ADMIN_ID}/Items/p1").mock(return_value=httpx.Response(200, json={"Id": "p1", "Type": "Playlist", "Name": "Old", "Tags": ["x"]}))
    renamed = respx.post(f"{JELLYFIN}/Items/p1").mock(return_value=httpx.Response(204))
    jellyfin = get_adapter("jellyfin")
    await jellyfin.music_playlist_rename(JF_CONFIG, {}, "p1", "New", ctx)
    import json as jsonlib

    assert jsonlib.loads(renamed.calls.last.request.content) == {"Id": "p1", "Type": "Playlist", "Name": "New", "Tags": ["x"]}
    respx.get(f"{JELLYFIN}/Users/{ADMIN_ID}/Items/al1").mock(return_value=httpx.Response(200, json={"Id": "al1", "Type": "MusicAlbum"}))
    deleted = respx.delete(f"{JELLYFIN}/Items/al1").mock(return_value=httpx.Response(204))
    with pytest.raises(AdapterError) as refused:
        await jellyfin.music_playlist_delete(JF_CONFIG, {}, "al1", ctx)
    assert refused.value.code == "not_a_playlist" and not deleted.called, "the same address deletes an album"


@respx.mock
async def test_plex_writes_playlists_with_its_server_address_and_refuses_smart_ones(ctx: Context) -> None:
    respx.get(f"{PLEX}/identity").mock(return_value=httpx.Response(200, json={"MediaContainer": {"machineIdentifier": "m1"}}))
    made = respx.post(f"{PLEX}/playlists").mock(return_value=httpx.Response(200, json={"MediaContainer": {"Metadata": [{"ratingKey": "90"}]}}))
    plex = get_adapter("plex")
    playlist = await plex.music_playlist_create(PLEX_CONFIG, {}, "Evening", ["501", "502"], ctx)
    params = made.calls.last.request.url.params
    assert playlist.id == "90" and params["type"] == "audio" and params["smart"] == "0"
    assert params["uri"] == "server://m1/com.plexapp.plugins.library/library/metadata/501,502"

    respx.get(f"{PLEX}/playlists/91").mock(return_value=httpx.Response(200, json={"MediaContainer": {"Metadata": [{"smart": True, "playlistType": "audio"}]}}))
    removed = respx.delete(url__startswith=f"{PLEX}/playlists/91").mock(return_value=httpx.Response(200))
    with pytest.raises(AdapterError) as refused:
        await plex.music_playlist_remove(PLEX_CONFIG, {}, "91", ["7"], ctx)
    assert refused.value.code == "smart_playlist" and not removed.called


def test_looking_is_not_enough_to_change_a_playlist(client: TestClient) -> None:
    setup_admin(client)
    board, widget_id = _player_card(client, demo=True)
    made = client.post(f"/api/v1/widgets/{widget_id}/music/playlists", json={"name": "Evening", "track_ids": ["d-a1-t1"]}, headers=CSRF)
    assert made.status_code == 201, made.text
    kim = create_user(client, "kim")
    client.put(f"/api/v1/boards/{board['slug']}/shares", json={"shares": [{"user_id": kim["id"], "level": "view"}]}, headers=CSRF)
    viewer = TestClient(client.app)
    login(viewer, "kim", "another-long-password")
    for method, address, body in (
        ("POST", f"/api/v1/widgets/{widget_id}/music/playlists", {"name": "Mine", "track_ids": ["d-a1-t1"]}),
        ("POST", f"/api/v1/widgets/{widget_id}/music/playlists/d-p1/tracks", {"track_ids": ["d-a1-t1"]}),
        ("DELETE", f"/api/v1/widgets/{widget_id}/music/playlists/d-p1/tracks", {"entries": ["d-e1"]}),
        ("PATCH", f"/api/v1/widgets/{widget_id}/music/playlists/d-p1", {"name": "Renamed"}),
        ("DELETE", f"/api/v1/widgets/{widget_id}/music/playlists/d-p1", None),
    ):
        answer = viewer.request(method, address, json=body, headers=CSRF)
        assert answer.status_code == 403, f"{method} {address}: {answer.status_code}"


def test_a_playlist_name_is_a_name(client: TestClient) -> None:
    setup_admin(client)
    _board, widget_id = _player_card(client, demo=True)
    for name in ("   ", "Line\nbreak"):
        answer = client.post(f"/api/v1/widgets/{widget_id}/music/playlists", json={"name": name, "track_ids": ["d-a1-t1"]}, headers=CSRF)
        assert answer.status_code == 400 and answer.json()["detail"]["code"] == "bad_name", name


def test_formats_a_browser_names_are_kept_to_known_ones() -> None:
    assert read_formats("FLAC, mp3,evil,mp3") == ("flac", "mp3")
    assert read_formats("") == ("flac", "mp3", "aac")


# -- through the server ---------------------------------------------------------------


def _player_card(client: TestClient, kind: str = "jellyfin", demo: bool = False) -> tuple[dict, int]:
    config = JF_CONFIG if kind == "jellyfin" else PLEX_CONFIG
    integration = client.post("/api/v1/integrations", json={"kind": kind, "name": kind, "config": config, "demo": demo}, headers=CSRF)
    assert integration.status_code == 201, integration.text
    board = client.post("/api/v1/boards", json={"name": "Music"}, headers=CSRF).json()
    made = client.post(f"/api/v1/pages/{board['pages'][0]['id']}/widgets",
                       json={"kind": f"{kind}.player", "integration_id": integration.json()["id"]}, headers=CSRF)
    assert made.status_code == 201, made.text
    return board, int(made.json()["widget"]["id"])


def test_a_demo_card_plays_a_sound_that_can_be_skipped_into(client: TestClient) -> None:
    setup_admin(client)
    _board, widget_id = _player_card(client, demo=True)
    album = client.get(f"/api/v1/widgets/{widget_id}/music/album", params={"id": "d-a2"})
    assert album.status_code == 200, album.text
    track = album.json()["tracks"][0]
    whole = client.get(f"/api/v1/widgets/{widget_id}/audio/{track['id']}")
    assert whole.status_code == 200 and whole.headers["content-type"] == "audio/wav"
    assert whole.headers["accept-ranges"] == "bytes" and whole.content[:4] == b"RIFF"
    part = client.get(f"/api/v1/widgets/{widget_id}/audio/{track['id']}", headers={"Range": "bytes=100-199"})
    assert part.status_code == 206
    assert part.content == whole.content[100:200]
    assert part.headers["content-range"] == f"bytes 100-199/{len(whole.content)}"


@respx.mock
def test_the_sound_arrives_with_the_range_the_browser_asked_for(client: TestClient) -> None:
    """⚠️ Without Range no track can be skipped into, and Safari plays nothing."""
    from app.routers import music

    setup_admin(client)
    _board, widget_id = _player_card(client)
    respx.get(f"{JELLYFIN}/Users").mock(return_value=httpx.Response(200, json=USERS))
    upstream = respx.get(f"{JELLYFIN}/Audio/t1/universal").mock(return_value=httpx.Response(
        206, content=b"x" * 1000,
        headers={"content-type": "audio/flac", "content-range": "bytes 1000-1999/47855594", "accept-ranges": "bytes", "content-length": "1000"}))
    answer = client.get(f"/api/v1/widgets/{widget_id}/audio/t1", params={"formats": "flac,mp3"}, headers={"Range": "bytes=1000-1999"})
    assert answer.status_code == 206, answer.text
    assert answer.headers["content-range"] == "bytes 1000-1999/47855594"
    assert answer.headers["accept-ranges"] == "bytes" and answer.content == b"x" * 1000
    sent = upstream.calls.last.request
    assert sent.headers["Range"] == "bytes=1000-1999"
    assert sent.url.params["Container"].startswith("flac,mp3")
    assert music._audio_open == 0, "the count goes back when the sound has been delivered"


@respx.mock
def test_music_counts_apart_from_the_cameras(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """A kiosk playing music must not take the place the door camera needs, nor the other way round."""
    from app.routers import music, widgets

    setup_admin(client)
    _board, widget_id = _player_card(client)
    respx.get(f"{JELLYFIN}/Users").mock(return_value=httpx.Response(200, json=USERS))
    respx.get(f"{JELLYFIN}/Audio/t1/universal").mock(return_value=httpx.Response(200, content=b"sound"))
    monkeypatch.setattr(widgets, "_streams_open", widgets.STREAM_LIMIT)
    assert client.get(f"/api/v1/widgets/{widget_id}/audio/t1").status_code == 200, "cameras at their limit leave music alone"
    monkeypatch.setattr(music, "_audio_open", music.AUDIO_LIMIT)
    full = client.get(f"/api/v1/widgets/{widget_id}/audio/t1")
    assert full.status_code == 503 and full.json()["detail"]["code"] == "too_many_streams"


def test_looking_at_a_board_is_not_enough_to_play(client: TestClient) -> None:
    """Decided on 11.09.2026: whoever may act on a board may play its music."""
    setup_admin(client)
    board, widget_id = _player_card(client, demo=True)
    kim = create_user(client, "kim")
    shared = client.put(f"/api/v1/boards/{board['slug']}/shares", json={"shares": [{"user_id": kim["id"], "level": "view"}]}, headers=CSRF)
    assert shared.status_code == 200, shared.text
    viewer = TestClient(client.app)
    login(viewer, "kim", "another-long-password")
    assert viewer.get(f"/api/v1/boards/{board['slug']}").status_code == 200, "kim may look at the board"
    for address in (f"/api/v1/widgets/{widget_id}/music/albums", f"/api/v1/widgets/{widget_id}/audio/d-a1-t1"):
        refused = viewer.get(address)
        assert refused.status_code == 403, address
        assert refused.json()["detail"]["code"] == "forbidden"

    client.put(f"/api/v1/boards/{board['slug']}/shares", json={"shares": [{"user_id": kim["id"], "level": "act"}]}, headers=CSRF)
    assert viewer.get(f"/api/v1/widgets/{widget_id}/music/albums").status_code == 200


def test_a_kiosk_plays_only_when_its_token_allows_actions(client: TestClient) -> None:
    setup_admin(client)
    board, widget_id = _player_card(client, demo=True)
    for allowed, expected in ((False, 403), (True, 200)):
        token = client.post(f"/api/v1/boards/{board['slug']}/kiosk-tokens", json={"name": f"hall {allowed}", "allow_actions": allowed},
                            headers=CSRF).json()["token"]
        display = TestClient(client.app)
        assert display.get(f"/api/v1/widgets/{widget_id}/music/albums", headers={"X-Kiosk-Token": token}).status_code == expected


def _asked_for(fragment: str) -> list[str]:
    """What reached the media server and names this piece.

    Looked up by content rather than by "was anything called": the card's own
    refresh runs in the background of every test here and asks the server for
    its newest albums whenever it likes.
    """
    return [str(call.request.url) for call in respx.calls if fragment in str(call.request.url)]


@respx.mock
def test_an_id_that_is_not_one_segment_never_reaches_the_media_server(client: TestClient) -> None:
    setup_admin(client)
    _board, widget_id = _player_card(client)
    respx.route(url__startswith=JELLYFIN).mock(return_value=httpx.Response(200, json=USERS))
    for bad in ("..x", ".hidden", "a b"):
        answer = client.get(f"/api/v1/widgets/{widget_id}/audio/{bad}")
        assert answer.status_code == 400, f"{bad!r}: {answer.status_code}"
        assert client.get(f"/api/v1/widgets/{widget_id}/music/album", params={"id": bad}).status_code == 400
    assert _asked_for("/Audio/") == []
    assert _asked_for("hidden") == [] and _asked_for("..x") == []


@respx.mock
def test_hls_pieces_are_held_to_what_the_playlist_writes(client: TestClient) -> None:
    """The part of the address comes from the browser; only the shapes Jellyfin writes are fetched."""
    setup_admin(client)
    _board, widget_id = _player_card(client)
    respx.route(url__startswith=JELLYFIN).mock(return_value=httpx.Response(200, json=USERS))
    for bad in ("System/Info", "main.m3u8.bak", "hls1/main/x.ts", "hls1/../../Users", "universal"):
        answer = client.get(f"/api/v1/widgets/{widget_id}/audio/t1/hls/{bad}")
        assert answer.status_code == 404, f"{bad!r}: {answer.status_code}"
    assert _asked_for("/Audio/") == [] and _asked_for("/System/") == []

    respx.routes.clear()
    respx.get(f"{JELLYFIN}/Audio/t1/hls1/main/0.ts").mock(return_value=httpx.Response(200, content=b"ts", headers={"content-type": "video/mp2t"}))
    segment = client.get(f"/api/v1/widgets/{widget_id}/audio/t1/hls/hls1/main/0.ts", params={"PlaySessionId": "s"})
    assert segment.status_code == 200 and segment.content == b"ts"


def test_a_mix_is_refused_where_the_server_makes_none(client: TestClient) -> None:
    setup_admin(client)
    _board, widget_id = _player_card(client, kind="plex")
    answer = client.get(f"/api/v1/widgets/{widget_id}/music/mix", params={"id": "501"})
    assert answer.status_code == 404 and answer.json()["detail"]["code"] == "no_such_view"
