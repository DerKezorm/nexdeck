"""Music: a player card's library, its sound, and its playlists, through the server.

All of it behind the right to act on the board: a page of the library, the
sound of one track, the pieces of an HLS playlist for a browser that plays
converted sound only that way, and the changes to playlists.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import asdict
from typing import Any
from urllib.parse import parse_qsl

import httpx
from fastapi import APIRouter, Request, Response, status
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask

from ..adapters import split_widget_kind
from ..adapters.base import AdapterError, Context, MediaSource, path_segment
from ..adapters.music import (
    NEEDS_ID,
    QUALITY_KBPS,
    SORTS,
    VIEWS,
    MusicLibrary,
    Playlist,
    ShelfQuery,
    Sound,
    SoundRequest,
    demo_shelf,
    demo_sound,
    read_formats,
)
from ..deps import DbSession, OptionalUser, board_for_viewer_id, error, kiosk_from_request
from ..models import Integration, Page, Widget
from ..schemas import PlaylistCreate, PlaylistEntries, PlaylistRename, PlaylistTracks
from ..services.collector import collector
from .widgets import _image_client

router = APIRouter(prefix="/api/v1", tags=["music"])

logger = logging.getLogger("nexdeck.music")

#: How many tracks the server relays at once.
#:
#: ⚠️ Its own count, not the cameras' ``STREAM_LIMIT``. A kiosk playing music
#: must not take the place the door camera needs, and one browser holds more
#: than one connection while it seeks: the old answer is still closing when the
#: new one starts.
AUDIO_LIMIT = 16
_audio_open = 0
#: A Range header as a browser sends one for media, and nothing longer.
RANGE = re.compile(r"^bytes=\d{0,15}-\d{0,15}$")
#: The pieces Jellyfin's HLS playlists name, relative to the track. Measured on
#: 10.11.11: ``main.m3u8`` from the master, ``hls1/main/<n>.ts`` from there.
HLS_PART = re.compile(r"^(main\.m3u8|hls1/main/\d{1,6}\.(ts|mp4|m4s|aac))$")
HLS_TYPE = "application/vnd.apple.mpegurl"
#: Tidy-up requests still running after their stream ended. Held, so the loop
#: does not drop them half way.
_tidying: set[asyncio.Task[None]] = set()


def _player(db: DbSession, widget_id: int, request: Request, user: OptionalUser) -> tuple[Widget, MusicLibrary, bool]:
    """The card, if it is a player and this person may play on its board.

    ⚠️ "act", not "view", decided on 11.09.2026: whoever may press the buttons
    on a board may play its music, and a kiosk only when its token allows
    actions. Looking at the board shows the newest albums and nothing more,
    because every address here makes the server call the media server with
    the connection's credentials.
    """
    widget = db.get(Widget, widget_id)
    if widget is None:
        raise error("not_found", "There is no such widget.", status.HTTP_404_NOT_FOUND)
    page = db.get(Page, widget.page_id)
    if page is None:
        # ⚠️ Not an ``assert``; see ``widgets._widget``.
        raise error("not_found", "There is no such widget.", status.HTTP_404_NOT_FOUND)
    _board, permission = board_for_viewer_id(db, page.board_id, user, kiosk_from_request(request, db))
    if permission not in ("act", "owner"):
        raise error("forbidden", "You may look at this board, but not play music on it.", status.HTTP_403_FORBIDDEN)
    try:
        adapter, kind = split_widget_kind(widget.kind)
    except KeyError as failure:
        raise error("not_a_player", "This card does not play music.", status.HTTP_404_NOT_FOUND) from failure
    if kind != "player" or not isinstance(adapter, MusicLibrary):
        raise error("not_a_player", "This card does not play music.", status.HTTP_404_NOT_FOUND)
    integration = db.get(Integration, widget.integration_id) if widget.integration_id else None
    if integration is None and not collector.is_demo(None):
        raise error("no_integration", "This card has no media server to play from.", status.HTTP_404_NOT_FOUND)
    return widget, adapter, collector.is_demo(integration)


async def _service(widget: Widget) -> tuple[dict[str, Any], Context]:
    try:
        _adapter, config, ctx = await collector.resolve_integration(int(widget.integration_id or 0))
    except AdapterError as failure:
        raise error(failure.code, failure.message, status.HTTP_404_NOT_FOUND) from failure
    return config, ctx


def _refused(failure: AdapterError) -> Exception:
    """A media server's refusal as the card reads it: its code, its words, and a gateway status."""
    return error(failure.code, failure.message, status.HTTP_502_BAD_GATEWAY)


@router.get("/widgets/{widget_id}/music/{view}", summary="A page of a player card's music library")
async def music_view(widget_id: int, view: str, request: Request, user: OptionalUser, db: DbSession,
                     id: str = "", q: str = "", sort: str = "newest", offset: int = 0) -> dict[str, Any]:
    """Albums, artists, playlists, one of each with its tracks, a search, a shuffle or a mix."""
    widget, adapter, demo = _player(db, widget_id, request, user)
    if view not in VIEWS:
        raise error("no_such_view", "The player does not show that.", status.HTTP_404_NOT_FOUND)
    if view == "mix" and not demo and "mix" not in adapter.music_features:
        raise error("no_such_view", "This media server makes no mixes.", status.HTTP_404_NOT_FOUND)
    if view in NEEDS_ID:
        if not id:
            raise error("bad_param", "Which one? The id is missing.")
        id = _segment(id, "That id")
    if len(q) > 100:
        raise error("bad_param", "A search is at most a hundred characters long.")
    query = ShelfQuery(id=id, q=q, sort=sort if sort in SORTS else "newest", offset=max(0, min(offset, 1_000_000)))
    options = dict(widget.options or {})
    if demo:
        return demo_shelf(view, query).to_dict()
    config, ctx = await _service(widget)
    try:
        shelf = await asyncio.wait_for(adapter.music_shelf(config, options, view, query, ctx), timeout=30)
    except AdapterError as failure:
        raise _refused(failure) from failure
    except TimeoutError as failure:
        raise error("timeout", "The media server did not answer within thirty seconds.", status.HTTP_504_GATEWAY_TIMEOUT) from failure
    return shelf.to_dict()


@router.get("/widgets/{widget_id}/audio/{track_id}", summary="The sound of one track, relayed by the server")
async def music_audio(widget_id: int, track_id: str, request: Request, user: OptionalUser, db: DbSession,
                      quality: str = "original", formats: str = "", start: float = 0) -> Response:
    """Relays the media server's answer as it comes, Range included.

    ⚠️ The browser's Range header goes to the media server and the 206 comes
    back unchanged. Without that no track can be skipped into, and Safari does
    not play a file at all.
    """
    global _audio_open
    widget, adapter, demo = _player(db, widget_id, request, user)
    track_id = _segment(track_id)
    wanted_range = request.headers.get("range", "")
    if wanted_range and not RANGE.match(wanted_range):
        wanted_range = ""
    if demo:
        # In a thread: the sound is made in Python, and half a second on the
        # event loop is half a second every other card waits.
        return _bytes_with_range(await asyncio.to_thread(demo_sound, track_id), "audio/wav", wanted_range)
    sound = SoundRequest(
        track_id=track_id, quality=quality if quality in QUALITY_KBPS else "original",
        formats=read_formats(formats), start=max(0.0, min(float(start), 86_400.0)),
    )
    config, ctx = await _service(widget)
    try:
        made = await adapter.music_source(config, dict(widget.options or {}), sound, ctx)
    except AdapterError as failure:
        raise _refused(failure) from failure
    if _audio_open >= AUDIO_LIMIT:
        raise error("too_many_streams", f"The server relays at most {AUDIO_LIMIT} tracks at once.", status.HTTP_503_SERVICE_UNAVAILABLE)
    # ⚠️ Counted before the first await, and given back on every way out, for
    # the reason the camera relay found: a check and a count with a network
    # round trip between them let a dozen browsers through at once.
    _audio_open += 1
    finished = False

    def finish() -> None:
        """Once, however the answer ends: the count goes back and a conversion is stopped."""
        nonlocal finished
        global _audio_open
        if finished:
            return
        finished = True
        _audio_open -= 1
        _tidy(adapter, config, made, ctx)

    try:
        response = await _open(made.source, bool(config.get("insecure")), wanted_range)
    except BaseException:
        finish()
        raise
    return _relay(response, on_close=finish)


@router.get("/widgets/{widget_id}/audio/{track_id}/hls/{part:path}", summary="A piece of a track's HLS playlist, relayed by the server")
async def music_hls(widget_id: int, track_id: str, part: str, request: Request, user: OptionalUser, db: DbSession,
                    quality: str = "low", formats: str = "") -> Response:
    """For a browser that plays converted sound only as HLS, which is Safari.

    ``master.m3u8`` asks the media server for the playlist; everything the
    playlist names after that resolves relative to it and arrives here as
    ``part``, held to the shapes the media server writes.
    """
    widget, adapter, demo = _player(db, widget_id, request, user)
    track_id = _segment(track_id)
    if demo or "hls" not in adapter.music_features:
        raise error("no_hls", "This media server does not hand out music as HLS.", status.HTTP_404_NOT_FOUND)
    if part != "master.m3u8" and not HLS_PART.match(part):
        raise error("bad_path", "That is not a piece of a playlist.", status.HTTP_404_NOT_FOUND)
    if len(request.url.query) > 2000:
        raise error("bad_param", "That address is longer than any playlist writes.")
    config, ctx = await _service(widget)
    options = dict(widget.options or {})
    try:
        if part == "master.m3u8":
            sound = SoundRequest(track_id=track_id, quality=quality if quality in QUALITY_KBPS else "low",
                                 formats=read_formats(formats), hls=True)
            source = (await adapter.music_source(config, options, sound, ctx)).source
        else:
            source = await adapter.music_hls_part(config, options, track_id, part, dict(parse_qsl(request.url.query)), ctx)
    except AdapterError as failure:
        raise _refused(failure) from failure
    response = await _open(source, bool(config.get("insecure")), request.headers.get("range", "") if RANGE.match(request.headers.get("range", "")) else "")
    # ⚠️ By what came back, not by the name that was asked for. A track that
    # already fits the quality is handed out as it is, playlist request or
    # not, and reading a whole file into memory as a playlist is how a
    # Raspberry Pi runs out of it.
    if "mpegurl" in response.headers.get("content-type", "").lower():
        body = await response.aread()
        await response.aclose()
        return Response(content=body, media_type=HLS_TYPE, headers={"Cache-Control": "no-store"})
    return _relay(response, on_close=lambda: None)


# -- playlists ---------------------------------------------------------------------


def _playlist_name(text: str) -> str:
    name = text.strip()
    if not name or any(ord(char) < 32 or ord(char) == 127 for char in name):
        raise error("bad_name", "A playlist needs a name, and a name has no control characters.")
    return name


def _actor(user: OptionalUser, request: Request) -> str:
    return user.username if user is not None else f"kiosk ({request.client.host if request.client else '?'})"


async def _change(widget: Widget, adapter: MusicLibrary, work: Any) -> Any:
    """Run one change at the media server, and forget what was remembered about it either way."""
    config, ctx = await _service(widget)
    try:
        return await asyncio.wait_for(work(config, dict(widget.options or {}), ctx), timeout=60)
    except AdapterError as failure:
        raise _refused(failure) from failure
    except TimeoutError as failure:
        raise error("timeout", "The media server did not answer within a minute.", status.HTTP_504_GATEWAY_TIMEOUT) from failure
    finally:
        # ⚠️ Also after a failure: a change that timed out may still have been made.
        ctx.forget_answers()


@router.post("/widgets/{widget_id}/music/playlists", status_code=status.HTTP_201_CREATED, summary="Make a playlist on a player card's media server")
async def playlist_create(widget_id: int, body: PlaylistCreate, request: Request, user: OptionalUser, db: DbSession) -> dict[str, Any]:
    widget, adapter, demo = _player(db, widget_id, request, user)
    name = _playlist_name(body.name)
    ids = [_segment(one) for one in body.track_ids]
    if demo:
        return asdict(Playlist(id="d-new", title=name, tracks=len(ids)))
    made = await _change(widget, adapter, lambda config, options, ctx: adapter.music_playlist_create(config, options, name, ids, ctx))
    logger.info("Playlist %r made with %d track(s) through %r by %s.", name, len(ids), widget.title, _actor(user, request))
    return asdict(made)


@router.post("/widgets/{widget_id}/music/playlists/{playlist_id}/tracks", summary="Add tracks to a playlist on a player card's media server")
async def playlist_add(widget_id: int, playlist_id: str, body: PlaylistTracks, request: Request, user: OptionalUser, db: DbSession) -> dict[str, Any]:
    widget, adapter, demo = _player(db, widget_id, request, user)
    playlist = _segment(playlist_id, "That playlist")
    ids = [_segment(one) for one in body.track_ids]
    if not demo:
        await _change(widget, adapter, lambda config, options, ctx: adapter.music_playlist_add(config, options, playlist, ids, ctx))
        logger.info("%d track(s) added to playlist %s through %r by %s.", len(ids), playlist, widget.title, _actor(user, request))
    return {"ok": True}


@router.delete("/widgets/{widget_id}/music/playlists/{playlist_id}/tracks", summary="Take tracks out of a playlist on a player card's media server")
async def playlist_remove(widget_id: int, playlist_id: str, body: PlaylistEntries, request: Request, user: OptionalUser, db: DbSession) -> dict[str, Any]:
    widget, adapter, demo = _player(db, widget_id, request, user)
    playlist = _segment(playlist_id, "That playlist")
    entries = [_segment(one, "That entry") for one in body.entries]
    if not demo:
        await _change(widget, adapter, lambda config, options, ctx: adapter.music_playlist_remove(config, options, playlist, entries, ctx))
        logger.info("%d track(s) taken out of playlist %s through %r by %s.", len(entries), playlist, widget.title, _actor(user, request))
    return {"ok": True}


@router.patch("/widgets/{widget_id}/music/playlists/{playlist_id}", summary="Rename a playlist on a player card's media server")
async def playlist_rename(widget_id: int, playlist_id: str, body: PlaylistRename, request: Request, user: OptionalUser, db: DbSession) -> dict[str, Any]:
    widget, adapter, demo = _player(db, widget_id, request, user)
    playlist = _segment(playlist_id, "That playlist")
    name = _playlist_name(body.name)
    if not demo:
        await _change(widget, adapter, lambda config, options, ctx: adapter.music_playlist_rename(config, options, playlist, name, ctx))
        logger.info("Playlist %s renamed to %r through %r by %s.", playlist, name, widget.title, _actor(user, request))
    return {"ok": True}


@router.delete("/widgets/{widget_id}/music/playlists/{playlist_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a playlist on a player card's media server")
async def playlist_delete(widget_id: int, playlist_id: str, request: Request, user: OptionalUser, db: DbSession) -> None:
    widget, adapter, demo = _player(db, widget_id, request, user)
    playlist = _segment(playlist_id, "That playlist")
    if not demo:
        await _change(widget, adapter, lambda config, options, ctx: adapter.music_playlist_delete(config, options, playlist, ctx))
        logger.info("Playlist %s deleted through %r by %s.", playlist, widget.title, _actor(user, request))


def _segment(value: str, what: str = "The track") -> str:
    """An id as one segment of an address, or a refusal the caller can read."""
    try:
        return path_segment(value, what)
    except AdapterError as failure:
        raise error(failure.code, failure.message) from failure


async def _open(source: MediaSource, insecure: bool, wanted_range: str) -> httpx.Response:
    client = _image_client(insecure)
    headers = dict(source.headers)
    if wanted_range:
        headers["Range"] = wanted_range
    upstream = client.build_request("GET", source.url, headers=headers, params=source.params or None,
                                    timeout=httpx.Timeout(20.0, read=60.0))
    try:
        response = await client.send(upstream, stream=True)
    except httpx.HTTPError as failure:
        raise error("unreachable", f"The media server did not deliver the sound: {failure.__class__.__name__}.",
                    status.HTTP_502_BAD_GATEWAY) from failure
    if response.status_code == status.HTTP_416_RANGE_NOT_SATISFIABLE:
        await response.aclose()
        raise error("bad_range", "That part of the track does not exist.", status.HTTP_416_RANGE_NOT_SATISFIABLE)
    if response.status_code >= 400:
        await response.aclose()
        raise error("no_sound", f"The media server answered with HTTP {response.status_code}.", status.HTTP_502_BAD_GATEWAY)
    return response


def _relay(response: httpx.Response, on_close: Any) -> StreamingResponse:
    """The media server's bytes as they arrive, with the headers a player needs to seek."""
    kept = {name: response.headers[name] for name in ("content-length", "content-range", "accept-ranges", "content-encoding")
            if name in response.headers}

    async def relay():
        try:
            # Every chunk goes out as it arrives, like the camera relay: a
            # buffer here is a stall in the player.
            async for chunk in response.aiter_raw():
                yield chunk
        finally:
            on_close()
            await response.aclose()

    async def after() -> None:
        # ⚠️ A second way to the same end. A browser that gives up before the
        # first byte never starts the generator above, so its ``finally`` never
        # runs; the count stayed taken and the media server's answer open. The
        # background task runs once the response is over, however it ended.
        on_close()
        await response.aclose()

    media_type = response.headers.get("content-type") or "application/octet-stream"
    return StreamingResponse(relay(), status_code=response.status_code, media_type=media_type,
                             headers={**kept, "Cache-Control": "no-store"}, background=BackgroundTask(after))


def _tidy(adapter: MusicLibrary, config: dict[str, Any], sound: Sound, ctx: Context) -> None:
    """Stop a conversion nobody listens to any more, without holding up the answer."""
    if not sound.converted:
        return

    async def stop() -> None:
        try:
            await asyncio.wait_for(adapter.music_stop(config, sound, ctx), timeout=6)
        except Exception as failure:  # noqa: BLE001 - the media server ends it by itself later
            logger.debug("A conversion could not be stopped: %s", failure.__class__.__name__)

    task = asyncio.get_running_loop().create_task(stop())
    _tidying.add(task)
    task.add_done_callback(_tidying.discard)


def _bytes_with_range(content: bytes, media_type: str, wanted_range: str) -> Response:
    """Bytes held in memory, answering Range the way a file server would."""
    size = len(content)
    headers = {"Accept-Ranges": "bytes", "Cache-Control": "no-store"}
    if not wanted_range:
        return Response(content=content, media_type=media_type, headers=headers)
    first_text, _, last_text = wanted_range.removeprefix("bytes=").partition("-")
    if first_text:
        first = int(first_text)
        last = min(int(last_text), size - 1) if last_text else size - 1
    else:
        # "bytes=-500" is the last five hundred.
        first = max(0, size - int(last_text or 0))
        last = size - 1
    if first >= size or first > last:
        return Response(status_code=status.HTTP_416_RANGE_NOT_SATISFIABLE, headers={"Content-Range": f"bytes */{size}"})
    return Response(content=content[first:last + 1], status_code=status.HTTP_206_PARTIAL_CONTENT, media_type=media_type,
                    headers={**headers, "Content-Range": f"bytes {first}-{last}/{size}"})
