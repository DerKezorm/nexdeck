"""Music: what a player card needs from a media server, whichever one it is.

The card plays in the browser. The server lists the library and relays the
sound, so the media server's credentials never reach the browser and the
media server does not have to be reachable from outside.

Measured on 11.09.2026 against Jellyfin 10.11 and Plex 1.43, both carrying the
same library of about 34,800 tracks:

- 98 % FLAC, median 930 kbit/s, one track in ten above 1.1 Mbit/s. Over a
  phone's hotspot that stalls, which is why the card can ask for less.
- Both answer a Range request on the original file with 206. Seeking needs
  that, and Safari does not play a file at all without it.
- Converted sound comes as an MP3 stream with no length and no Range, from
  both. Seeking inside one means asking again from a point in time.
- Jellyfin also converts to HLS, which Safari plays by itself. Plex refuses
  HLS for music, also when the client says it is Safari or an iPhone.
- Playing without reporting leaves nothing behind: no activity log entry, no
  session, no play count. Plex does keep a device entry for every client
  identifier it sees, so nexdeck always sends the same one.
"""

from __future__ import annotations

import io
import math
import struct
import wave
from dataclasses import asdict, dataclass, field
from typing import Any

from .base import AdapterError, Context, Field, MediaSource, WidgetData, WidgetType

#: The views a card may ask for, and nothing else.
VIEWS = ("albums", "artists", "artist", "album", "playlists", "playlist", "search", "shuffle", "mix")
#: Views that name one thing and need its id.
NEEDS_ID = ("artist", "album", "playlist", "mix")
#: How an album page is ordered.
SORTS = ("newest", "name", "random")

#: How much of it the card asks for. ``None`` is the file as it is.
QUALITY_KBPS: dict[str, int | None] = {"original": None, "high": 320, "low": 128}

#: What a browser may say it plays, by codec. Anything else is dropped.
FORMATS = ("flac", "mp3", "aac", "alac", "opus", "vorbis", "wav")
#: What every browser nexdeck supports plays, for a request that names nothing.
DEFAULT_FORMATS = ("flac", "mp3", "aac")

ALBUM_PAGE = 48
ARTIST_PAGE = 60
PLAYLIST_LIMIT = 500
#: Track ids per write request. Both servers take a comma-separated list
#: (measured on 11.09.2026); an address with five hundred ids would not fit.
TRACKS_PER_WRITE = 50
SHUFFLE_SIZE = 100
#: How many of the newest albums the card's own refresh brings along.
PLAYER_ALBUMS = 24


@dataclass
class Track:
    id: str
    title: str
    artist: str = ""
    album: str = ""
    album_id: str = ""
    artist_id: str = ""
    #: Seconds. Unknown stays ``None``, never 0: a zero-length track would end the moment it starts.
    duration: float | None = None
    number: int | None = None
    disc: int | None = None
    #: ``proxy:`` paths through the image route, large for the cover and small for rows.
    art: str = ""
    thumb: str = ""
    codec: str = ""
    bit_depth: int | None = None
    sample_rate: int | None = None
    #: kbit/s
    bitrate: int | None = None
    #: The track's place in a playlist, which is what removing it names. Empty outside a playlist.
    entry: str = ""


@dataclass
class Album:
    id: str
    title: str
    artist: str = ""
    artist_id: str = ""
    year: int | None = None
    tracks: int | None = None
    art: str = ""
    thumb: str = ""


@dataclass
class Artist:
    id: str
    name: str
    art: str = ""
    thumb: str = ""


@dataclass
class Playlist:
    id: str
    title: str
    tracks: int | None = None
    duration: float | None = None
    art: str = ""
    thumb: str = ""
    #: False for a list the server fills by itself, such as Plex's smart playlists.
    editable: bool = True


@dataclass
class Shelf:
    """One answer to the card: a page of whatever it asked for."""

    title: str = ""
    subtitle: str = ""
    art: str = ""
    albums: list[Album] = field(default_factory=list)
    artists: list[Artist] = field(default_factory=list)
    playlists: list[Playlist] = field(default_factory=list)
    tracks: list[Track] = field(default_factory=list)
    total: int | None = None
    #: Where the next page starts, or ``None`` when this was the last one.
    next: int | None = None
    #: For a playlist: whether its tracks can be taken out and it renamed or deleted.
    editable: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ShelfQuery:
    id: str = ""
    q: str = ""
    sort: str = "newest"
    offset: int = 0


@dataclass(frozen=True)
class SoundRequest:
    track_id: str
    quality: str = "original"
    formats: tuple[str, ...] = DEFAULT_FORMATS
    #: Seconds into the track, for converted sound that cannot seek by Range.
    start: float = 0.0
    #: Converted sound as HLS, for a browser that plays HLS by itself.
    hls: bool = False


@dataclass
class Sound:
    """Where the sound of one track comes from, and what to tidy up afterwards."""

    source: MediaSource
    #: True when the media server is converting, which is work to stop when the browser leaves.
    converted: bool = False
    #: The media server's name for the conversion, handed back to stop it.
    session: str = ""


def next_offset(offset: int, got: int, total: int | None) -> int | None:
    """The start of the following page, or ``None`` when there is none."""
    if got <= 0 or total is None or offset + got >= total:
        return None
    return offset + got


def read_formats(text: str) -> tuple[str, ...]:
    """What the browser said it plays, kept to the names nexdeck knows."""
    named = tuple(dict.fromkeys(part.strip().lower() for part in str(text or "").split(",") if part.strip()))
    known = tuple(part for part in named if part in FORMATS)
    return known or DEFAULT_FORMATS


def seconds(value: Any, per_second: float = 1.0) -> float | None:
    try:
        number = float(value) / per_second
    except (TypeError, ValueError):
        return None
    return round(number, 3) if number > 0 else None


def whole(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


#: What the card shows while nothing plays. Asked for after the first test on
#: 11.09.2026: one big cover beside the card's name read as "this is playing".
IDLE_ART = Field(
    "idle_art", "Covers while nothing plays", type="select", default="four",
    options=(("four", "Four covers"), ("one", "One cover")),
    help="Pressing a cover opens its album; the round button on it plays the album.",
)
#: Which albums those covers are. Random ones are picked again at every refresh of the card.
IDLE_PICK = Field(
    "idle_pick", "Which albums", type="select", default="newest",
    options=(("newest", "The newest"), ("random", "Picked at random")),
    help="Random albums change whenever the card refreshes itself.",
)
#: How many albums a random pick asks for: as many as the card can show.
PICKS = 4


def player_widget(options: tuple[Any, ...] = ()) -> WidgetType:
    """The one player card, the same on every media server that offers it.

    ⚠️ The options every server shares are written here, not in each adapter:
    Plex, Jellyfin and Emby must never offer three different cards under one name.
    """
    return WidgetType(
        kind="player",
        label="Music player",
        description="Plays the music library in the browser: covers, albums, artists, playlists, search and a queue.",
        renderer="player",
        default_size=(4, 4),
        min_size=(2, 2),
        refresh_seconds=900,
        options=(IDLE_ART, IDLE_PICK, *options),
    )


def wants_random_picks(options: dict[str, Any]) -> bool:
    return str(options.get("idle_pick") or "") == "random"


def player_data(albums: list[Album], counts: dict[str, int | None], features: tuple[str, ...],
                picks: list[Album] | None = None) -> WidgetData:
    """What the card's own refresh carries: the newest albums and how big the library is.

    Everything past that is asked for when somebody opens it, because a card
    that nobody touches must not walk the library every quarter of an hour.

    ⚠️ Random covers ride apart from the newest albums, in ``meta``. The items
    are also the library's "New" tab, and a random pick there would be a tab
    that says new and shows anything.
    """
    music: dict[str, Any] = {"features": list(features)}
    if picks is not None:
        music["picks"] = [asdict(album) for album in picks]
    return WidgetData(
        items=[{**asdict(album), "subtitle": album.artist, "kind": "album"} for album in albums],
        secondary=[{"label": label, "value": value} for label, value in counts.items() if value is not None],
        meta={"music": music, "empty": "No music in this library"},
    )


class MusicLibrary:
    """What a media server adapter implements to offer the player card.

    A mixin next to the adapter's own base, so the router can ask
    ``isinstance(adapter, MusicLibrary)`` instead of trusting a widget kind.
    """

    #: What the card may offer beyond playing: ``mix`` for a mix built from
    #: one album, artist or track, and ``hls`` for converted sound as HLS.
    music_features: tuple[str, ...] = ()

    async def music_shelf(self, config: dict[str, Any], options: dict[str, Any], view: str,
                          query: ShelfQuery, ctx: Context) -> Shelf:
        raise NotImplementedError

    async def music_source(self, config: dict[str, Any], options: dict[str, Any],
                           sound: SoundRequest, ctx: Context) -> Sound:
        raise NotImplementedError

    async def music_hls_part(self, config: dict[str, Any], options: dict[str, Any], track_id: str,
                             part: str, query: dict[str, str], ctx: Context) -> MediaSource:
        raise AdapterError("This media server does not hand out music as HLS.", code="no_hls")

    async def music_stop(self, config: dict[str, Any], sound: Sound, ctx: Context) -> None:
        """Tell the media server that nobody listens to a conversion any more."""
        return None

    # -- playlists ---------------------------------------------------------------
    #
    # Decided on 11.09.2026: create, add tracks, remove tracks, rename, delete.
    # A playlist is written on the connection's account, the same one the card
    # browses as. Measured the same day on Jellyfin 10.11.11 and Plex 1.43.3
    # with a throwaway playlist that was deleted afterwards.

    async def music_playlist_create(self, config: dict[str, Any], options: dict[str, Any], name: str,
                                    track_ids: list[str], ctx: Context) -> Playlist:
        raise AdapterError("This media server's playlists cannot be changed from here.", code="no_playlist_edits")

    async def music_playlist_add(self, config: dict[str, Any], options: dict[str, Any], playlist_id: str,
                                 track_ids: list[str], ctx: Context) -> None:
        raise AdapterError("This media server's playlists cannot be changed from here.", code="no_playlist_edits")

    async def music_playlist_remove(self, config: dict[str, Any], options: dict[str, Any], playlist_id: str,
                                    entries: list[str], ctx: Context) -> None:
        raise AdapterError("This media server's playlists cannot be changed from here.", code="no_playlist_edits")

    async def music_playlist_rename(self, config: dict[str, Any], options: dict[str, Any], playlist_id: str,
                                    name: str, ctx: Context) -> None:
        raise AdapterError("This media server's playlists cannot be changed from here.", code="no_playlist_edits")

    async def music_playlist_delete(self, config: dict[str, Any], options: dict[str, Any], playlist_id: str,
                                    ctx: Context) -> None:
        raise AdapterError("This media server's playlists cannot be changed from here.", code="no_playlist_edits")


def batches(ids: list[str], size: int = TRACKS_PER_WRITE) -> list[list[str]]:
    return [ids[start:start + size] for start in range(0, len(ids), size)]


# ---------------------------------------------------------------------------
# Demo: a library that does not exist, and a sound that does
# ---------------------------------------------------------------------------

#: Seconds of every demo track. Short, because the sound is made on the spot.
DEMO_SECONDS = 20
_DEMO_ALBUMS = (
    ("d-a1", "Aurora Fields", "Northern Sky", 2026),
    ("d-a2", "Slow Tide", "Harbour Brass", 2025),
    ("d-a3", "Glass Bridge", "The Ferrymen", 2024),
    ("d-a4", "Low Light", "Kim Aster", 2026),
    ("d-a5", "Orbital", "Signal Choir", 2023),
    ("d-a6", "Salt and Cedar", "Harbour Brass", 2022),
)
_DEMO_TITLES = ("Opening", "Landfall", "Blue Hour", "Driftwood", "Second Wind", "Afterglow")


def _demo_tracks(album_id: str) -> list[Track]:
    album = next((one for one in _DEMO_ALBUMS if one[0] == album_id), _DEMO_ALBUMS[0])
    return [
        Track(id=f"{album[0]}-t{number}", title=title, artist=album[2], album=album[1], album_id=album[0],
              artist_id=f"d-{album[2].lower().replace(' ', '-')}", duration=float(DEMO_SECONDS), number=number,
              disc=1, codec="flac", bit_depth=16, sample_rate=44100, bitrate=900)
        for number, title in enumerate(_DEMO_TITLES, start=1)
    ]


def _demo_album(entry: tuple[str, str, str, int]) -> Album:
    return Album(id=entry[0], title=entry[1], artist=entry[2], artist_id=f"d-{entry[2].lower().replace(' ', '-')}",
                 year=entry[3], tracks=len(_DEMO_TITLES))


def demo_player(features: tuple[str, ...], options: dict[str, Any] | None = None, tick: int = 0) -> WidgetData:
    albums = [_demo_album(one) for one in _DEMO_ALBUMS]
    # A pick that moves with the clock, so a demo card set to random shows it.
    picks = [albums[(tick + step * 2) % len(albums)] for step in range(PICKS)] if wants_random_picks(options or {}) else None
    return player_data(albums, {"Albums": len(_DEMO_ALBUMS), "Artists": 5, "Tracks": len(_DEMO_ALBUMS) * len(_DEMO_TITLES)},
                       features, picks)


def demo_shelf(view: str, query: ShelfQuery) -> Shelf:
    albums = [_demo_album(one) for one in _DEMO_ALBUMS]
    if view == "albums":
        return Shelf(albums=albums, total=len(albums))
    if view == "artists":
        names = sorted({one.artist for one in albums})
        return Shelf(artists=[Artist(id=f"d-{name.lower().replace(' ', '-')}", name=name) for name in names], total=len(names))
    if view == "artist":
        mine = [one for one in albums if one.artist_id == query.id]
        return Shelf(title=mine[0].artist if mine else "", albums=mine, total=len(mine))
    if view == "album":
        album = next((one for one in albums if one.id == query.id), albums[0])
        tracks = _demo_tracks(album.id)
        return Shelf(title=album.title, subtitle=album.artist, tracks=tracks, total=len(tracks))
    if view == "playlists":
        return Shelf(playlists=[Playlist(id="d-p1", title="Evening", tracks=12, duration=240.0)], total=1)
    if view in ("playlist", "shuffle", "mix"):
        tracks = _demo_tracks("d-a1") + _demo_tracks("d-a2")
        if view == "playlist":
            for number, track in enumerate(tracks, start=1):
                track.entry = f"d-e{number}"
        return Shelf(title="Evening" if view == "playlist" else "", tracks=tracks, total=len(tracks), editable=view == "playlist")
    if view == "search":
        wanted = query.q.lower()
        hits = [one for one in albums if wanted in one.title.lower() or wanted in one.artist.lower()]
        tracks = [track for one in hits for track in _demo_tracks(one.id)][:30]
        return Shelf(albums=hits, tracks=tracks, total=len(hits) + len(tracks))
    return Shelf()


#: Made sounds, by track. A demo board has a few dozen tracks at most.
_demo_sounds: dict[str, bytes] = {}
#: A pentatonic scale, so any three notes of it sound like they belong together.
_NOTES = (220.0, 247.5, 277.2, 330.0, 370.0)


def demo_sound(track_id: str) -> bytes:
    """A soft chord that breathes, different for every track, as a WAV file.

    Small on purpose: 16 kHz, mono, twenty seconds. A demo card should play
    something when its button is pressed rather than show an error, and a
    recording would be a file in the repository somebody holds the rights to.
    """
    hit = _demo_sounds.get(track_id)
    if hit is not None:
        return hit
    rate = 16_000
    seed = sum(ord(char) for char in track_id)
    chord = [_NOTES[(seed + step * 2) % len(_NOTES)] * (1 + step // 2) for step in range(3)]
    frames = bytearray()
    total = rate * DEMO_SECONDS
    for index in range(total):
        moment = index / rate
        # Fades in and out over two seconds, and swells slowly in between.
        envelope = min(1.0, moment / 2, (DEMO_SECONDS - moment) / 2) * (0.7 + 0.3 * math.sin(moment * 0.9))
        value = sum(math.sin(2 * math.pi * pitch * moment) for pitch in chord) / len(chord)
        frames += struct.pack("<h", int(value * envelope * 9000))
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(bytes(frames))
    made = buffer.getvalue()
    if len(_demo_sounds) >= 48:
        _demo_sounds.clear()
    _demo_sounds[track_id] = made
    return made
