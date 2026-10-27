"""Your Spotify: how much has been listened to, and what was played last.

⚠️ **Not run against a working instance.** Your Spotify fills itself from a
Spotify account through an OAuth login, which needs a Spotify developer app
and a person's account, so no data could be had. What was read instead is the
server of the official image (yooooomi/your_spotify_server, the bundled
``apps/server/build/index.js``, 27.10.2026), which settles the routes and the
sign-in and nothing about the rows:

* The routes under ``/spotify`` take ``start`` and ``end`` as dates (``end``
  defaults to now), and ``GET /spotify/listened_to`` answers
  ``{"count": <number>}`` (0 for none), which is all the statistics card reads.
* A request is let in by a cookie that only the web interface's Spotify login
  makes, **or by the user's public token as ``?token=...``**. The public token
  is made in the web interface under Settings, "Public token" and gives a guest
  the statistics routes; it is the only way in here, since a program cannot do
  the Spotify login. It reads, it cannot change.
* Without a valid one the server answers **HTTP 401** (error code
  ``NOT_LOGGED``).
* ``GET /spotify/gethistory`` takes ``number`` and ``offset`` (and optionally
  ``start`` and ``end``) and answers the played tracks, newest first. The row
  is joined with its track, album and artists in a Mongo aggregation; its exact
  field names were not seen, so the card reads the likely ones and falls back to
  a plain "?" rather than failing.

Versions before 1.8.0 let a guest token read the user's Spotify tokens through
``/me`` (CVE-2024-28193). Nothing here calls ``/me``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from . import demo as fake
from .base import (
    Adapter,
    AdapterError,
    AuthFailed,
    Context,
    Field,
    WidgetData,
    WidgetType,
    ago,
    base_url,
)

#: The spans of the statistics card, in days.
SPANS = (("Today", 1), ("This week", 7), ("This month", 30))


def _name(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("name") or "")
    if isinstance(value, list) and value:
        return _name(value[0])
    return ""


def _row(entry: dict[str, Any]) -> dict[str, Any]:
    """One played track. The names of the fields follow the likely shape and every one has a way out."""
    track = entry.get("track") if isinstance(entry.get("track"), dict) else {}
    title = str(track.get("name") or entry.get("name") or "?")
    artist = _name(entry.get("artist")) or _name(entry.get("artists")) or _name(track.get("artists"))
    album = _name(entry.get("album"))
    return {
        "id": str(entry.get("_id") or entry.get("id") or f"{title}:{entry.get('played_at')}"),
        "title": title,
        "subtitle": " · ".join(piece for piece in (artist, album) if piece),
        "value": ago(entry.get("played_at")),
        "status": "ok",
    }


class YourspotifyAdapter(Adapter):
    kind = "yourspotify"
    label = "Your Spotify"
    category = "media"
    description = "How many tracks were played today, this week and this month, and the ones played last."
    icon = "your-spotify"
    docs_url = "https://github.com/Yooooomi/your_spotify"
    #: Built from the server's own code; never run against an instance with listening data.
    beta = True
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://your-spotify-server:8080",
              help="The server of Your Spotify (the API, port 8080), not the web interface."),
        Field("token", "Public token", type="password", secret=True, required=True,
              help="In Your Spotify under Settings, Public token. It lets a program read the statistics and change nothing."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    guide = (
        "In the web interface of Your Spotify, open Settings.",
        "Generate the public token and copy it.",
        "Use the address of the server (the API), which is not always the one of the web interface.",
    )
    widgets = (
        WidgetType(
            kind="stats",
            label="Listening",
            description="Tracks played today, this week and this month.",
            renderer="value",
            default_size=(3, 2),
            min_size=(1, 1),
            refresh_seconds=300,
            metrics=("week",),
        ),
        WidgetType(
            kind="recent",
            label="Played last",
            description="The tracks played last, with artist and how long ago.",
            renderer="list",
            default_size=(4, 3),
            refresh_seconds=120,
            options=(Field("limit", "Entries", type="number", default=8),),
        ),
    )

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, params: dict[str, Any]) -> Any:
        response = await ctx.request(
            "GET", f"{base_url(config)}{path}", params={**params, "token": str(config.get("token") or "")},
            verify=not config.get("insecure"), cache_seconds=30, auth_errors=False,
        )
        if response.status_code in (401, 403):
            raise AuthFailed("Your Spotify does not know this public token.")
        if response.status_code == 404:
            raise AdapterError("This address answers, but not the way the server of Your Spotify does.", code="not_yourspotify",
                               hint="Use the address of the server (the API, port 8080), not of the web interface.")
        if response.status_code >= 400:
            raise AdapterError(f"Your Spotify answered with HTTP {response.status_code}.", code="http_error")
        try:
            return response.json()
        except ValueError as error:
            raise AdapterError("Your Spotify did not answer with JSON.", code="not_json",
                               hint="The URL probably points at the web interface and not at the server.") from error

    async def _count(self, config: dict[str, Any], ctx: Context, days: int, now: datetime) -> int:
        answer = await self._get(config, ctx, "/spotify/listened_to", {"start": (now - timedelta(days=days)).isoformat(), "end": now.isoformat()})
        if not isinstance(answer, dict) or "count" not in answer:
            raise AdapterError("This address answers, but not the way Your Spotify does.", code="not_yourspotify")
        try:
            return max(0, int(answer["count"]))
        except (TypeError, ValueError):
            return 0

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        month = await self._count(config, ctx, 30, datetime.now(UTC))
        return f"Your Spotify answers, {month} tracks in the last 30 days."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        link = base_url(config)
        if widget_kind == "recent":
            limit = max(1, min(50, int(options.get("limit") or 8)))
            answer = await self._get(config, ctx, "/spotify/gethistory", {"number": limit, "offset": 0})
            return self.recent_card(answer, link)
        now = datetime.now(UTC)
        return self.stats_card({label: await self._count(config, ctx, days, now) for label, days in SPANS}, link)

    @staticmethod
    def stats_card(counts: dict[str, int], link: str | None = None) -> WidgetData:
        first, *rest = SPANS
        return WidgetData(
            primary={"label": first[0], "value": counts.get(first[0], 0)},
            secondary=[{"label": label, "value": counts.get(label, 0)} for label, _days in rest],
            metrics={"week": float(counts.get("This week", 0))},
            link=link,
        )

    @staticmethod
    def recent_card(answer: Any, link: str | None = None) -> WidgetData:
        entries = [one for one in answer if isinstance(one, dict)] if isinstance(answer, list) else []
        return WidgetData(items=[_row(one) for one in entries], link=link, meta={"empty": "Nothing was played yet."})

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        if widget_kind == "recent":
            now = datetime.now(UTC)
            names = [("Departure", "Harbour Lights", "Tide"), ("Signal", "Orbital Tide", "Copper Sky"), ("Quiet Harbour", "Alex Example", "Quiet Harbour"),
                     ("Remote", "Orbital Tide", "Copper Sky")]
            return self.recent_card([{"id": str(index), "track": {"name": title}, "artist": {"name": artist}, "album": {"name": album},
                                      "played_at": (now - timedelta(minutes=12 + index * 9 + tick // 30)).isoformat()}
                                     for index, (title, artist, album) in enumerate(names)])
        today = fake.counter("yourspotify-today", tick, 18, 0.01)
        return self.stats_card({"Today": today, "This week": 130 + today, "This month": 612 + today})


ADAPTER: Adapter = YourspotifyAdapter()
