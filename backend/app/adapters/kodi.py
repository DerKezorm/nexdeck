"""Kodi over its JSON-RPC web server.

⚠️ **Mostly unmeasured.** The only Kodi that could be run in a container here
was linuxserver/kodi-headless, which is Kodi 18.5 (JSON-RPC 10.3.0) without a
screen and without a library database. What it showed, on 27.10.2026:

* The web server is off by default (Settings, Services, Control, "Allow remote
  control via HTTP"); the port is 8080, the user ``kodi``, and the password
  empty until one is set. A request without the user and password the server
  has set answers **HTTP 401** with no body.
* ``JSONRPC.Ping`` answers ``"pong"``, ``Application.GetProperties`` answers
  ``{"muted", "name", "version": {"major", "minor", "revision", "tag"}, "volume"}``,
  ``Player.GetActivePlayers`` answers ``[]`` while nothing plays, and
  ``System.GetProperties`` and ``XBMC.GetInfoLabels`` answer.
* An error is **HTTP 200** with ``{"error": {"code", "message"}}``: ``-32601``
  "Method not found." for a method the Kodi does not have, and ``-32603``
  "Internal error." for every library call there, because that Kodi had no
  database to ask.

Everything else, what a running player gives and what a library counts, is
written after Kodi's JSON-RPC documentation (kodi.wiki, JSON-RPC API v12 and
newer) and has not been seen against a Kodi that plays. Hence beta, and the
reason the library and the playing card say so when the Kodi cannot answer.

⚠️ ``Player.GetProperties`` gives ``percentage`` as a number from 0 to 100,
``time`` and ``totaltime`` as ``{hours, minutes, seconds, milliseconds}`` and
``speed`` as 1 while it plays and 0 while it is paused.

⚠️ A picture is ``image://...`` in Kodi's own scheme and reaches a browser
only through the web server's ``/image/<that, percent-encoded>``; it is handed
out as ``proxy:`` so the password stays here. The image route takes no percent
sign in a path, so the picture travels as ``/image/<url-safe base64>`` and
``image_source`` puts Kodi's own form back.
"""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from . import demo as fake
from .base import (
    Action,
    Adapter,
    AdapterError,
    Allowed,
    AuthFailed,
    Context,
    Field,
    ImagePath,
    MediaSource,
    ReadCommands,
    WidgetData,
    WidgetType,
    base_url,
    duration_short,
)


@dataclass(frozen=True)
class _JsonRpcReads(Allowed):
    """The ``request`` of a GET to ``/jsonrpc`` when every call in it only gets: ``Player.GetActivePlayers``, ``JSONRPC.Ping``.

    ⚠️ Kodi takes a whole JSON-RPC call in the address, ``/jsonrpc?request={"method":"Application.Quit"}``, so a GET can stop
    a player or the application. The value is read as JSON, a batch included, and anything that is not plainly a getter is refused.
    """

    def __contains__(self, value: object) -> bool:
        try:
            calls = json.loads(str(value))
        except ValueError:
            return False
        calls = calls if isinstance(calls, list) else [calls]
        for call in calls:
            method = str(call.get("method") or "") if isinstance(call, dict) else ""
            space, _, name = method.partition(".")
            if not (space and (name.startswith("Get") or method in self.exact)):
                return False
        return bool(calls)


#: Kodi's players, by the id it gives them: audio, video, pictures.
PICTURES = "picture"
ITEM_FIELDS = ["title", "showtitle", "season", "episode", "artist", "album", "year", "thumbnail", "art", "file"]
PLAYER_FIELDS = ["time", "totaltime", "percentage", "speed"]
LIBRARY_COUNTS = (
    ("Movies", "VideoLibrary.GetMovies"),
    ("Series", "VideoLibrary.GetTVShows"),
    ("Episodes", "VideoLibrary.GetEpisodes"),
    ("Albums", "AudioLibrary.GetAlbums"),
    ("Songs", "AudioLibrary.GetSongs"),
)


def _seconds(clock: Any) -> float:
    if not isinstance(clock, dict):
        return 0.0
    try:
        return (float(clock.get("hours") or 0) * 3600 + float(clock.get("minutes") or 0) * 60
                + float(clock.get("seconds") or 0) + float(clock.get("milliseconds") or 0) / 1000)
    except (TypeError, ValueError):
        return 0.0


def _text(*values: Any) -> str:
    for value in values:
        if isinstance(value, list):
            value = ", ".join(str(one) for one in value if one)
        if value:
            return str(value)
    return ""


def _art(item: dict[str, Any], *keys: str) -> str:
    art = item.get("art") if isinstance(item.get("art"), dict) else {}
    picture = _text(*(art.get(key) for key in keys), item.get("thumbnail") if "poster" in keys or "thumb" in keys else "")
    return f"proxy:/image/{base64.urlsafe_b64encode(picture.encode()).decode().rstrip('=')}" if picture else ""


def _row(item: dict[str, Any], properties: dict[str, Any]) -> dict[str, Any]:
    kind = str(item.get("type") or "")
    title = _text(item.get("title"), item.get("label"), str(item.get("file") or "").replace("\\", "/").rsplit("/", 1)[-1], "?")
    if kind == "episode":
        season, episode = item.get("season"), item.get("episode")
        code = f"S{int(season):02d}E{int(episode):02d}" if isinstance(season, int) and isinstance(episode, int) and season >= 0 and episode >= 0 else ""
        subtitle = " ".join(piece for piece in (_text(item.get("showtitle")), code) if piece)
    elif kind in ("song", "musicvideo"):
        subtitle = " · ".join(piece for piece in (_text(item.get("artist")), _text(item.get("album"))) if piece)
    else:
        year = item.get("year")
        subtitle = str(year) if isinstance(year, int) and year > 0 else ""
    total, played = _seconds(properties.get("totaltime")), _seconds(properties.get("time"))
    progress = float(properties.get("percentage") or 0) or (100.0 * played / total if total else 0.0)
    row: dict[str, Any] = {
        "title": title,
        "subtitle": subtitle,
        "progress": round(max(0.0, min(100.0, progress)), 1),
        "remaining": duration_short(total - played) if total > played else "",
        "state": "playing" if properties.get("speed") else "paused",
        "art": _art(item, "poster", "thumb", "album.thumb"),
    }
    backdrop = _art(item, "fanart", "tvshow.fanart")
    if backdrop:
        row["backdrop"] = backdrop
    return row


class KodiAdapter(Adapter):
    kind = "kodi"
    label = "Kodi"
    category = "media"
    description = "What Kodi plays, whether it is playing or paused, the library, with play or pause, stop, mute and a library update."
    icon = "kodi"
    docs_url = "https://kodi.wiki/view/JSON-RPC_API"
    #: Measured only as far as a headless Kodi 18.5 goes (sign-in, ping, properties, errors); a player was never seen.
    beta = True
    raw_read_commands = ReadCommands(params={"request": _JsonRpcReads(exact=frozenset({"JSONRPC.Ping", "JSONRPC.Version", "JSONRPC.Permission"}))})
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://kodi:8080",
              help="The web server of Kodi, switched on under Settings, Services, Control."),
        Field("username", "User name", default="kodi"),
        Field("password", "Password", type="password", secret=True,
              help="Leave empty when Kodi's web server has no password."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    guide = (
        "In Kodi, open Settings, then Services, then Control.",
        "Switch on Allow remote control via HTTP, and set a user name and a password.",
        "The adapter reads what plays and the library, and presses play or pause, stop, mute and the library update.",
    )
    widgets = (
        WidgetType(
            kind="nowplaying",
            label="Now playing",
            description="What Kodi plays, with its picture, progress and time left.",
            renderer="nowplaying",
            default_size=(4, 3),
            refresh_seconds=15,
            metrics=("players",),
            options=(Field("backdrop", "Picture of what plays behind the card", type="bool", default=True),),
        ),
        WidgetType(
            kind="status",
            label="Kodi status",
            description="Whether Kodi plays, pauses or waits, the volume, and buttons for play or pause, stop, mute and a library update.",
            renderer="value",
            default_size=(3, 2),
            min_size=(1, 1),
            refresh_seconds=15,
            metrics=("players",),
        ),
        WidgetType(
            kind="library",
            label="Library",
            description="Movies, series, episodes, albums and songs in Kodi's library.",
            renderer="value",
            default_size=(2, 2),
            min_size=(1, 1),
            refresh_seconds=600,
        ),
    )

    # -- the wire ------------------------------------------------------------

    #: Kodi's pictures, and nothing else of the web server: the one segment is the picture's own address, encoded.
    image_paths = (ImagePath(r"/image/[A-Za-z0-9_-]{1,2048}"),)

    async def image_source(self, config: dict[str, Any], path: str, ctx: Context) -> MediaSource:
        """``/image/<base64>`` back to Kodi's ``/image/<image://..., percent-encoded>``, fetched with the web user.

        ⚠️ Only an ``image://`` address. Kodi's ``/vfs/`` serves any file it can
        read, so a picture that decodes to anything else is refused.
        """
        try:
            token = path[len("/image/"):]
            picture = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)).decode()
        except (binascii.Error, ValueError) as failure:
            raise AdapterError("That is not a picture Kodi hands out.", code="bad_path") from failure
        if not picture.startswith("image://"):
            raise AdapterError("That is not a picture Kodi hands out.", code="bad_path")
        return MediaSource(url=f"{base_url(config)}/image/{quote(picture, safe='')}", headers=self.image_headers(config))

    def image_headers(self, config: dict[str, Any]) -> dict[str, str]:
        import base64

        if not config.get("password") and not config.get("username"):
            return {}
        pair = f"{config.get('username') or 'kodi'}:{config.get('password') or ''}".encode()
        return {"Authorization": "Basic " + base64.b64encode(pair).decode()}

    def _auth(self, config: dict[str, Any]) -> tuple[str, str] | None:
        # A Kodi without a password wants no sign-in, and one with a password wants the user too.
        if not config.get("password"):
            return None
        return (str(config.get("username") or "kodi"), str(config["password"]))

    async def _rpc(self, config: dict[str, Any], ctx: Context, method: str, params: dict[str, Any] | None = None) -> Any:
        response = await ctx.request(
            "POST", f"{base_url(config)}/jsonrpc",
            json_body={"jsonrpc": "2.0", "method": method, "params": params or {}, "id": 1},
            auth=self._auth(config), verify=not config.get("insecure"), auth_errors=False,
        )
        if response.status_code in (401, 403):
            raise AuthFailed("Kodi rejected the user name or the password." if config.get("password") else "Kodi wants a user name and a password.")
        if response.status_code == 404:
            raise AdapterError("This address answers, but not the way Kodi does.", code="not_kodi",
                               hint="Use the address of Kodi's web server, usually port 8080, and switch it on under Settings, Services, Control.")
        if response.status_code >= 400:
            raise AdapterError(f"Kodi answered with HTTP {response.status_code}.", code="http_error")
        try:
            answer = response.json()
        except ValueError as error:
            raise AdapterError("Kodi did not answer with JSON.", code="not_json",
                               hint="The URL probably points at something else than Kodi.") from error
        if not isinstance(answer, dict) or answer.get("jsonrpc") != "2.0":
            raise AdapterError("This address answers, but not the way Kodi does.", code="not_kodi")
        if isinstance(answer.get("error"), dict):
            fault = answer["error"]
            raise AdapterError(f"Kodi refused {method}: {fault.get('message') or 'an error'}", code=f"kodi_{fault.get('code', 'error')}",
                               hint="Kodi's own message; a library call fails when the Kodi has no library database.")
        return answer.get("result")

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        properties = await self._rpc(config, ctx, "Application.GetProperties", {"properties": ["name", "version"]})
        version = (properties or {}).get("version") or {}
        number = f"{version.get('major')}.{version.get('minor')}" if version.get("major") is not None else ""
        return f"Kodi {number} answers." if number else "Kodi answers."

    # -- the cards -----------------------------------------------------------

    async def _players(self, config: dict[str, Any], ctx: Context) -> list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]]:
        """Every player that is active, as (player, item, properties); a picture slideshow is not something that plays."""
        found = []
        for player in await self._rpc(config, ctx, "Player.GetActivePlayers") or []:
            if not isinstance(player, dict) or player.get("type") == PICTURES or player.get("playerid") is None:
                continue
            identifier = player["playerid"]
            item = (await self._rpc(config, ctx, "Player.GetItem", {"playerid": identifier, "properties": ITEM_FIELDS}) or {}).get("item") or {}
            properties = await self._rpc(config, ctx, "Player.GetProperties", {"playerid": identifier, "properties": PLAYER_FIELDS}) or {}
            found.append((player, item, properties))
        return found

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        link = base_url(config)
        if widget_kind == "library":
            counts: dict[str, int] = {}
            failure: AdapterError | None = None
            for label, method in LIBRARY_COUNTS:
                try:
                    answer = await self._rpc(config, ctx, method, {"limits": {"start": 0, "end": 1}})
                except AdapterError as error:
                    if error.code in ("kodi_-32603", "kodi_-32601"):
                        failure = error
                        continue
                    raise
                counts[label] = int(((answer or {}).get("limits") or {}).get("total") or 0)
            if not counts:
                raise failure or AdapterError("Kodi has no library to count.", code="no_library")

            return self.library_card(counts, link)
        players = await self._players(config, ctx)
        if widget_kind == "nowplaying":
            return self.nowplaying_card(players, options, link)
        properties = await self._rpc(config, ctx, "Application.GetProperties", {"properties": ["volume", "muted", "name", "version"]})
        return self.status_card(players, properties or {}, link)

    @staticmethod
    def nowplaying_card(players: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]], options: dict[str, Any], link: str | None = None) -> WidgetData:
        rows = [_row(item, properties) for _player, item, properties in players]
        if not options.get("backdrop", True):
            for row in rows:
                row.pop("backdrop", None)
        return WidgetData(
            items=rows,
            secondary=[{"label": "Playing", "value": sum(1 for row in rows if row["state"] == "playing")}],
            metrics={"players": float(len(rows))},
            link=link,
        )

    @staticmethod
    def status_card(players: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]], properties: dict[str, Any], link: str | None = None) -> WidgetData:
        muted = bool(properties.get("muted"))
        secondary: list[dict[str, Any]] = []
        actions = [Action(id="mute", label="Unmute" if muted else "Mute", icon="speaker")]

        if players:
            player, item, played = players[0]
            row = _row(item, played)
            state = row["state"]
            word = "Playing" if state == "playing" else "Paused"
            secondary.append({"label": "Now", "value": row["title"]})
            params = {"playerid": player["playerid"]}
            actions = [
                Action(id="playpause", label="Pause" if state == "playing" else "Play", icon="pause" if state == "playing" else "play", params=params),
                Action(id="stop", label="Stop", icon="square", confirm=True, params=params),
                *actions,
            ]
        else:
            word = "Idle"
        secondary.append({"label": "Volume", "value": f"{int(properties.get('volume') or 0)}%{' (muted)' if muted else ''}"})
        version = properties.get("version") if isinstance(properties.get("version"), dict) else {}
        if version.get("major") is not None:
            secondary.append({"label": "Version", "value": f"{version.get('major')}.{version.get('minor')}"})
        actions.append(Action(id="scan", label="Update the video library", icon="refresh-cw"))
        return WidgetData(
            status="ok",
            primary={"label": "Kodi", "value": word},
            secondary=secondary,
            metrics={"players": float(len(players))},
            actions=actions,
            link=link,
        )

    @staticmethod
    def library_card(counts: dict[str, int], link: str | None = None) -> WidgetData:
        pairs = list(counts.items())
        first = pairs[0] if pairs else ("Movies", 0)
        return WidgetData(
            primary={"label": first[0], "value": first[1]},
            secondary=[{"label": label, "value": value} for label, value in pairs[1:]],
            link=link,
        )

    async def action(self, widget_kind: str, action_id: str, params: dict[str, Any], config: dict[str, Any],
                     options: dict[str, Any], ctx: Context) -> str:
        if action_id == "mute":
            await self._rpc(config, ctx, "Application.SetMute", {"mute": "toggle"})
            return "Muting toggled."
        if action_id == "scan":
            await self._rpc(config, ctx, "VideoLibrary.Scan")
            return "Kodi looks for new files."
        if action_id in ("playpause", "stop"):
            try:
                identifier = int(params.get("playerid"))
            except (TypeError, ValueError):
                raise AdapterError("No player was named.", code="missing_param") from None
            if action_id == "playpause":
                await self._rpc(config, ctx, "Player.PlayPause", {"playerid": identifier, "play": "toggle"})
                return "Play or pause pressed."
            await self._rpc(config, ctx, "Player.Stop", {"playerid": identifier})
            return "Stopped."
        raise AdapterError("Unknown action.", code="no_such_action")

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        if widget_kind == "library":
            return self.library_card({"Movies": 1284, "Series": 96, "Episodes": 3190, "Albums": 412, "Songs": 5120})
        paused = fake.flicker("kodi-paused", tick // 15, 0.25)
        progress = (fake.walk("kodi-progress", tick, 0, 100, period=500) + tick * 0.1) % 100
        total = 6300.0
        item = {"type": "episode", "title": "Departure", "showtitle": "Harbour Lights", "season": 3, "episode": 4}
        properties = {"percentage": progress, "speed": 0 if paused else 1,
                      "time": {"hours": 0, "minutes": int(total * progress / 100 // 60), "seconds": 0, "milliseconds": 0},
                      "totaltime": {"hours": 1, "minutes": 45, "seconds": 0, "milliseconds": 0}}
        players = [({"playerid": 1, "type": "video"}, item, properties)]
        if widget_kind == "nowplaying":
            return self.nowplaying_card(players, options)
        return self.status_card(players, {"volume": 65, "muted": False, "version": {"major": 21, "minor": 2}})


ADAPTER: Adapter = KodiAdapter()
