"""M3U Editor: the playlists and guides it serves, the streams its proxy carries and its recordings.

Built for issue #32 from M3U Editor's routes (``routes/web.php``) and their
controllers in the source of 0.13.1, then measured against a live M3U Editor
0.13.1 (all in one, embedded proxy) with a made-up playlist of four channels,
a made-up guide, three viewers on two channels and three recordings.

- One API token from API Tokens in M3U Editor, sent as ``Authorization:
  Bearer``. Without ``Accept: application/json`` a refused token is sent on to
  the login page with a 302; with it the answer is 401.
- ``/user/playlists`` lists every kind of playlist: ``playlist`` (a source
  M3U Editor syncs), ``custom_playlist``, ``merged_playlist`` and
  ``playlist_alias``. The last three are built from the channels of the first
  kind, so the overview counts channels of real playlists only; only those
  carry a sync time and a status, and only those can be synced.
- ``/proxy/status`` says ``proxy_enabled: false`` and ``health: disabled`` for
  the embedded proxy too. Measured: both stayed so while three viewers
  watched through it. The flag means an external proxy, so the cards read
  ``/proxy/streams/active`` instead, which is what the proxy carries now.
  Both routes are missing (404) when the proxy integration is switched off.
- A stream's ``started_at`` and a viewer's ``connected_at`` are UTC without
  a zone; the other times carry their offset.
- ``/recordings`` is the Dispatcharr-compatible DVR. It answers 403 both when
  the token lacks the View ability and when the account has no DVR set up,
  with the same words, so the card says both. A recording names its channel
  by number only; ``/channel/{id}`` gives the name.
- Syncing a playlist or a guide is ``GET /playlist/{uuid}/sync`` and
  ``GET /epg/{uuid}/sync``. M3U Editor asks no token there (the uuid is the
  key) and allows five a minute. ``force`` must be ``1``: Laravel's boolean
  check turns ``force=true`` away with a 422 (measured).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from . import demo as fake
from .base import (
    Action,
    Adapter,
    AdapterError,
    AuthFailed,
    Context,
    Field,
    WidgetData,
    WidgetType,
    ago,
    base_url,
    human_bytes,
    path_segment,
)

#: What a playlist is, in words; only the first kind is synced from a source.
KINDS = {"playlist": "Playlist", "custom_playlist": "Custom playlist", "merged_playlist": "Merged playlist",
         "playlist_alias": "Playlist alias"}

#: A sync's state in words, and its colour. M3U Editor's own ``Status``.
SYNC = {
    "pending": ("Pending", "ok"),
    "processing": ("Syncing", "ok"),
    "completed": ("Synced", "ok"),
    "failed": ("Failed", "bad"),
    "cancelled": ("Cancelled", "warn"),
}

#: A recording's state in words, and its colour. M3U Editor's ``DvrRecordingStatus``.
RECORDING = {
    "scheduled": ("Scheduled", "ok"),
    "recording": ("Recording", "ok"),
    "post_processing": ("Processing", "ok"),
    "completed": ("Done", "ok"),
    "purged": ("Removed", "unknown"),
    "failed": ("Failed", "bad"),
    "cancelled": ("Cancelled", "unknown"),
}
RUNNING = ("recording", "post_processing")

RECORDINGS_SHOWN = (("all", "Running, planned and recent"), ("upcoming", "Running and planned"))

#: A channel's name changes rarely.
CHANNEL_SECONDS = 3600
#: At most this many channels are asked for their name in one go.
CHANNEL_LIMIT = 20

NO_DVR = "No DVR is set up for this account in M3U Editor, or the API token lacks the View ability."


def _when(value: Any, *, utc: bool = False) -> datetime | None:
    """An ISO time, or M3U Editor's ``2026-10-06 20:30:00``, which is UTC."""
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        if not utc:
            return None
        moment = moment.replace(tzinfo=UTC)
    return moment


def _until(moment: datetime | None, now: datetime) -> str:
    """How long until a moment: "in 5 d"; empty once it has passed."""
    if moment is None:
        return ""
    seconds = (moment - now).total_seconds()
    if seconds <= 0:
        return ""
    if seconds < 3600:
        return f"in {max(1, round(seconds / 60))} min"
    if seconds < 48 * 3600:
        return f"in {round(seconds / 3600)} h"
    return f"in {round(seconds / 86400)} d"


def _since(moment: datetime | None, now: datetime) -> str:
    """How long ago, in the units of :func:`ago`; empty for a moment ahead.

    ⚠️ A clock far ahead means a zone was read wrong; better nothing than a
    wrong age.
    """
    if moment is None or moment - now > timedelta(minutes=5):
        return ""
    return ago(moment.isoformat(), now.timestamp())


def _mbit(kbps: Any) -> str:
    try:
        value = float(kbps)
    except (TypeError, ValueError):
        return ""
    return f"{value / 1000:.1f} Mbit/s"


def _number(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _hours(options: dict[str, Any]) -> int:
    try:
        wanted = int(options.get("stale_hours") or 48)
    except (TypeError, ValueError):
        wanted = 48
    return max(1, min(24 * 60, wanted))


def _limit(options: dict[str, Any], default: int = 8) -> int:
    try:
        wanted = int(options.get("limit") or default)
    except (TypeError, ValueError):
        wanted = default
    return max(1, min(100, wanted))


class M3uEditorAdapter(Adapter):
    kind = "m3ueditor"
    label = "M3U Editor"
    category = "media"
    description = "M3U Editor's playlists and guides with their last sync, what its stream proxy carries right now, and its recordings."
    icon = "m3u-editor"
    docs_url = "https://github.com/sparkison/m3u-editor"
    keywords = ("IPTV", "M3U", "Xtream", "EPG", "DVR", "playlist")
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://m3u-editor:36400"),
        Field("api_key", "API token", type="password", secret=True, required=True,
              help="A token from API Tokens in M3U Editor. The View ability is enough for every card; "
                   "the recordings also need a DVR set up for the account."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(
            kind="overview",
            label="M3U Editor overview",
            description="The streams the proxy carries now, their viewers and bandwidth, and the playlists, channels and guides; amber when a sync failed or is old.",
            renderer="value",
            default_size=(3, 2),
            min_size=(1, 1),
            refresh_seconds=60,
            metrics=("streams", "viewers"),
            options=(
                Field("stale_hours", "Old after (hours)", type="number", default=48,
                      help="A playlist or a guide synced longer ago than this turns the card amber."),
            ),
        ),
        WidgetType(
            kind="streams",
            label="Active streams",
            description="The channels the proxy carries now, with their viewers, how long they run and their bandwidth; a stream on a failover source or with errors turns amber.",
            renderer="list",
            default_size=(4, 3),
            refresh_seconds=30,
            options=(
                Field("viewers", "Show who watches", type="bool", default=True,
                      help="The user names of the viewers. Their addresses are never shown."),
            ),
        ),
        WidgetType(
            kind="playlists",
            label="Playlists",
            description="Every playlist with its channels and groups, the last sync and its state, and a button to sync it.",
            renderer="list",
            default_size=(4, 3),
            refresh_seconds=300,
        ),
        WidgetType(
            kind="epgs",
            label="Guides",
            description="The program guides (EPG) with their channels, the last sync and its state, and a button to sync one.",
            renderer="list",
            default_size=(4, 3),
            refresh_seconds=300,
        ),
        WidgetType(
            kind="recordings",
            label="Recordings",
            description="What the DVR records now, what it will record next and what it recorded last.",
            renderer="list",
            default_size=(4, 3),
            refresh_seconds=60,
            options=(
                Field("show", "Show", type="select", default="all", options=RECORDINGS_SHOWN),
                Field("limit", "Entries", type="number", default=8, help="Between 1 and 100."),
            ),
        ),
    )

    # -- talking to M3U Editor -----------------------------------------------

    def _headers(self, config: dict[str, Any]) -> dict[str, str]:
        return {"Authorization": f"Bearer {str(config.get('api_key') or '').strip()}", "Accept": "application/json"}

    async def _call(self, config: dict[str, Any], ctx: Context, path: str, *, cache: float = 0,
                    missing_ok: bool = False) -> Any:
        response = await ctx.request(
            "GET", f"{base_url(config)}{path}", headers=self._headers(config),
            verify=not config.get("insecure"), cache_seconds=cache, auth_errors=False,
        )
        if response.status_code == 401:
            raise AuthFailed("M3U Editor turned the API token away.")
        if response.status_code == 403 and path.startswith("/recordings"):
            raise AdapterError(NO_DVR, code="no_dvr",
                               hint="Set up the DVR in M3U Editor, or give the token the View ability.")
        if response.status_code == 403:
            raise AuthFailed()
        if response.status_code == 404 and missing_ok:
            return None
        if response.status_code >= 300:
            raise AdapterError(f"M3U Editor answered with HTTP {response.status_code}.", code="http_error",
                               hint="Check the URL." if response.status_code in (302, 404) else "")
        try:
            return response.json()
        except ValueError as error:
            raise AdapterError("M3U Editor did not answer with JSON.", code="not_json",
                               hint="The URL probably points at a login page or a reverse proxy.") from error

    async def _playlists(self, config: dict[str, Any], ctx: Context, cache: float = 30) -> list[dict[str, Any]]:
        found = await self._call(config, ctx, "/user/playlists", cache=cache)
        return [row for row in found if isinstance(row, dict)] if isinstance(found, list) else []

    async def _epgs(self, config: dict[str, Any], ctx: Context, cache: float = 30) -> list[dict[str, Any]]:
        found = await self._call(config, ctx, "/user/epgs", cache=cache)
        return [row for row in found if isinstance(row, dict)] if isinstance(found, list) else []

    async def _streams(self, config: dict[str, Any], ctx: Context) -> dict[str, Any] | None:
        """What the proxy carries now; None when the proxy integration is off."""
        found = await self._call(config, ctx, "/proxy/streams/active", cache=10, missing_ok=True)
        return found if isinstance(found, dict) else None

    # -- the hooks -----------------------------------------------------------

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        playlists = await self._playlists(config, ctx, cache=0)
        epgs = await self._epgs(config, ctx, cache=0)
        return f"M3U Editor answers · {len(playlists)} playlist(s) · {len(epgs)} guide(s)"

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "overview":
            return await self._overview(config, ctx, options)
        if widget_kind == "streams":
            return await self._streams_card(config, ctx, options)
        if widget_kind == "playlists":
            return self._playlists_card(await self._playlists(config, ctx))
        if widget_kind == "epgs":
            return self._epgs_card(await self._epgs(config, ctx))
        if widget_kind == "recordings":
            return await self._recordings(config, ctx, options)
        raise AdapterError("Unknown widget.", code="unknown_widget")

    @staticmethod
    def _sync_reasons(name: str, status: str, last: datetime | None, now: datetime, stale: timedelta) -> list[str]:
        if status == "failed":
            return [f"{name}: the last sync failed."]
        if status in ("pending", "processing"):
            return []
        if last is None:
            return [f"{name}: never synced."]
        if now - last > stale:
            return [f"{name}: last synced {_since(last, now) or 'long'} ago."]
        return []

    async def _overview(self, config: dict[str, Any], ctx: Context, options: dict[str, Any]) -> WidgetData:
        playlists, epgs, streams = await asyncio.gather(
            self._playlists(config, ctx), self._epgs(config, ctx), self._streams(config, ctx))
        now = datetime.now(UTC)
        stale = timedelta(hours=_hours(options))
        reasons: list[str] = []
        notes: list[str] = []
        sources = [row for row in playlists if row.get("type") == "playlist"]
        for row in sources:
            reasons += self._sync_reasons(str(row.get("name") or "?"), str(row.get("status") or "").lower(),
                                          _when(row.get("last_sync")), now, stale)
        for row in epgs:
            reasons += self._sync_reasons(str(row.get("name") or "?"), str(row.get("status") or "").lower(),
                                          _when(row.get("last_sync")), now, stale)

        active = viewers = 0
        bandwidth = ""
        if streams is None:
            notes.append("The stream proxy is switched off in M3U Editor.")
        elif streams.get("success") is False:
            reasons.append("The stream proxy does not answer.")
        else:
            totals = streams.get("globalStats") or {}
            active = _number(totals.get("active_streams"))
            viewers = _number(totals.get("total_clients"))
            bandwidth = _mbit(totals.get("total_bandwidth_kbps"))

        enabled = sum(_number(row.get("enabled_channels")) for row in sources)
        secondary: list[dict[str, Any]] = [{"label": "Viewers", "value": viewers}]
        if bandwidth:
            secondary.append({"label": "Bandwidth", "value": bandwidth})
        secondary += [
            {"label": "Playlists", "value": len(playlists)},
            {"label": "Channels", "value": enabled},
            {"label": "Guides", "value": len(epgs)},
        ]
        return WidgetData(
            status="warn" if reasons else "ok",
            primary={"label": "Streams", "value": active},
            secondary=secondary,
            metrics={"streams": float(active), "viewers": float(viewers)},
            meta={"status_reason": " · ".join(reasons + notes)},
        )

    async def _streams_card(self, config: dict[str, Any], ctx: Context, options: dict[str, Any]) -> WidgetData:
        streams = await self._streams(config, ctx)
        if streams is None:
            return WidgetData(status="unknown", items=[], meta={"empty": "The stream proxy is switched off in M3U Editor."})
        if streams.get("success") is False:
            raise AdapterError("The stream proxy does not answer.", code="proxy_down",
                               hint="M3U Editor could not reach its m3u-proxy.")
        now = datetime.now(UTC)
        show_viewers = options.get("viewers", True) is not False
        rows = []
        for stream in streams.get("streams") or []:
            if not isinstance(stream, dict):
                continue
            model: dict[str, Any] = stream["model"] if isinstance(stream.get("model"), dict) else {}
            clients = [c for c in stream.get("clients") or [] if isinstance(c, dict)]
            count = _number(stream.get("client_count"))
            parts = [f"{count} viewer(s)"]
            if show_viewers:
                names = sorted({str(c.get("username")) for c in clients if c.get("username")})
                if names:
                    parts.append(", ".join(names))
            started = _since(_when(stream.get("started_at"), utc=True), now)
            if started:
                parts.append(f"started {started} ago")
            failover = bool(stream.get("using_failover"))
            errors = _number(stream.get("error_count"))
            if failover:
                parts.append("On a failover source")
            if errors:
                parts.append(f"{errors} error(s)")
            if stream.get("transcoding"):
                parts.append("Transcoding")
            idle = stream.get("status") != "active"
            rows.append({
                "id": str(stream.get("stream_id") or ""),
                "title": str(model.get("title") or stream.get("source_url") or "?"),
                "subtitle": " · ".join(parts),
                "value": "Idle" if idle else _mbit(stream.get("bandwidth_kbps")),
                "status": "warn" if failover or errors else "unknown" if idle else "ok",
            })
        rows.sort(key=lambda row: (row["status"] == "unknown", row["title"].lower()))
        totals = streams.get("globalStats") or {}
        secondary = [{"label": "Viewers", "value": _number(totals.get("total_clients"))}]
        bandwidth = _mbit(totals.get("total_bandwidth_kbps"))
        if bandwidth:
            secondary.append({"label": "Bandwidth", "value": bandwidth})
        return WidgetData(
            status="warn" if any(row["status"] == "warn" for row in rows) else "ok",
            items=rows,
            secondary=secondary,
            meta={"empty": "Nobody is watching."},
        )

    @staticmethod
    def _sync_row(status: str, last: datetime | None, now: datetime) -> tuple[str, str, str]:
        """The value, the colour and the time part of a playlist or guide row."""
        word, colour = SYNC.get(status, (status.capitalize() or "?", "unknown"))
        when = _since(last, now)
        if not when:
            return word, colour, "Never synced"
        # M3U Editor stamps a failed run too.
        return word, colour, f"last try {when} ago" if status == "failed" else f"synced {when} ago"

    def _playlists_card(self, playlists: list[dict[str, Any]]) -> WidgetData:
        now = datetime.now(UTC)
        rows = []
        for row in playlists:
            kind = str(row.get("type") or "")
            uuid = str(row.get("uuid") or "")
            parts = [] if kind == "playlist" else [KINDS.get(kind, "Playlist")]
            parts.append(f"{_number(row.get('enabled_channels'))} of {_number(row.get('total_channels'))} channels on")
            if _number(row.get("vod_channels")):
                parts.append(f"{_number(row.get('vod_channels'))} VOD")
            parts.append(f"{_number(row.get('groups_count'))} groups")
            if _number(row.get("active_streams")):
                parts.append(f"{_number(row.get('active_streams'))} streaming")
            entry: dict[str, Any] = {"id": uuid, "title": str(row.get("name") or "?")}
            if kind == "playlist":
                status = str(row.get("status") or "").lower()
                value, colour, when = self._sync_row(status, _when(row.get("last_sync")), now)
                parts.append(when)
                entry |= {"value": value, "status": colour}
                if uuid and status not in ("pending", "processing"):
                    entry["actions"] = [Action(id="sync", label="Sync", icon="refresh-cw", params={"uuid": uuid})]
            else:
                entry |= {"value": "", "status": "ok"}
            entry["subtitle"] = " · ".join(parts)
            rows.append(entry)
        return WidgetData(
            status="warn" if any(row["status"] == "bad" for row in rows) else "ok",
            items=rows,
            meta={"empty": "No playlist yet."},
        )

    def _epgs_card(self, epgs: list[dict[str, Any]]) -> WidgetData:
        now = datetime.now(UTC)
        rows = []
        for row in epgs:
            uuid = str(row.get("uuid") or "")
            status = "processing" if row.get("is_processing") else str(row.get("status") or "").lower()
            value, colour, when = self._sync_row(status, _when(row.get("last_sync")), now)
            entry: dict[str, Any] = {
                "id": uuid,
                "title": str(row.get("name") or "?"),
                "subtitle": " · ".join([f"{_number(row.get('channel_count'))} channels", when]),
                "value": value,
                "status": colour,
            }
            if uuid and status not in ("pending", "processing"):
                entry["actions"] = [Action(id="sync", label="Sync", icon="refresh-cw", params={"uuid": uuid})]
            rows.append(entry)
        return WidgetData(
            status="warn" if any(row["status"] == "bad" for row in rows) else "ok",
            items=rows,
            meta={"empty": "No guide yet."},
        )

    async def _channel_names(self, config: dict[str, Any], ctx: Context, numbers: list[int]) -> dict[int, str]:
        gate = asyncio.Semaphore(4)

        async def one(number: int) -> str:
            async with gate:
                try:
                    found = await self._call(config, ctx, f"/channel/{number}", cache=CHANNEL_SECONDS)
                except AdapterError:
                    return ""
            data = found.get("data") if isinstance(found, dict) else None
            if not isinstance(data, dict):
                return ""
            return str(data.get("title") or data.get("name") or "")

        wanted = numbers[:CHANNEL_LIMIT]
        names = await asyncio.gather(*(one(number) for number in wanted))
        return {number: name for number, name in zip(wanted, names, strict=True) if name}

    async def _recordings(self, config: dict[str, Any], ctx: Context, options: dict[str, Any]) -> WidgetData:
        found = await self._call(config, ctx, "/recordings/", cache=20)
        recordings = [row for row in found if isinstance(row, dict)] if isinstance(found, list) else []
        now = datetime.now(UTC)
        upcoming_only = options.get("show") == "upcoming"
        def state(row: dict[str, Any]) -> str:
            return str((row.get("custom_properties") or {}).get("status") or "")

        def order(row: dict[str, Any]) -> tuple[int, float]:
            """Running first, ending soonest; then the planned ones, next first; then the rest, newest first."""
            kind = state(row)
            start = _when(row.get("start_time")) or now
            end = _when(row.get("end_time")) or start
            if kind in RUNNING:
                return 0, end.timestamp()
            if kind == "scheduled":
                return 1, start.timestamp()
            return 2, -end.timestamp()

        shown = [row for row in recordings if not upcoming_only or state(row) in ("scheduled", *RUNNING)]
        shown.sort(key=order)
        shown = shown[:_limit(options)]
        names = await self._channel_names(config, ctx, sorted({_number(row.get("channel")) for row in shown if row.get("channel")}))

        rows = []
        for row in shown:
            props = row.get("custom_properties") or {}
            kind = state(row)
            word, colour = RECORDING.get(kind, (kind.capitalize() or "?", "unknown"))
            program: dict[str, Any] = props["program"] if isinstance(props.get("program"), dict) else {}
            number = _number(row.get("channel"))
            start, end = _when(row.get("start_time")), _when(row.get("end_time"))
            parts = [names.get(number) or f"Channel {number}"]
            value = word
            if kind == "scheduled":
                value = _until(start, now) or word
            elif kind in RUNNING and _until(end, now):
                parts.append(f"ends {_until(end, now)}")
            elif kind in ("completed", "failed", "cancelled", "purged") and _since(end, now):
                parts.append(f"ended {_since(end, now)} ago")
            written = props.get("bytes_written")
            if isinstance(written, int | float) and written > 0:
                parts.append(human_bytes(written))
            if kind == "failed" and props.get("interrupted_reason"):
                parts.append(str(props["interrupted_reason"])[:120])
            rows.append({
                "id": _number(row.get("id")),
                "title": str(program.get("title") or names.get(number) or "?"),
                "subtitle": " · ".join(parts),
                "value": value,
                "status": colour,
            })
        running = sum(1 for row in recordings if state(row) in RUNNING)
        planned = sum(1 for row in recordings if state(row) == "scheduled")
        return WidgetData(
            status="warn" if any(row["status"] == "bad" for row in rows) else "ok",
            items=rows,
            secondary=[{"label": "Recording", "value": running}, {"label": "Scheduled", "value": planned}],
            meta={"empty": "Nothing is planned." if upcoming_only else "No recording yet."},
        )

    async def action(self, widget_kind: str, action_id: str, params: dict[str, Any], config: dict[str, Any],
                     options: dict[str, Any], ctx: Context) -> str:
        if action_id != "sync" or widget_kind not in ("playlists", "epgs"):
            raise AdapterError("Unknown action.", code="no_such_action")
        uuid = path_segment(params.get("uuid"), "playlist" if widget_kind == "playlists" else "guide")
        # Only one the account itself lists: the sync route asks no token, so
        # nexdeck makes sure the uuid is one of this account's.
        rows = await (self._playlists(config, ctx, cache=0) if widget_kind == "playlists" else self._epgs(config, ctx, cache=0))
        mine = {str(row.get("uuid")) for row in rows if widget_kind == "epgs" or row.get("type") == "playlist"}
        if uuid not in mine:
            raise AdapterError("M3U Editor does not list that one for this token.", code="not_found")
        prefix = "playlist" if widget_kind == "playlists" else "epg"
        response = await ctx.request(
            "GET", f"{base_url(config)}/{prefix}/{uuid}/sync", headers=self._headers(config),
            params={"force": "1"}, verify=not config.get("insecure"), auth_errors=False,
        )
        if response.status_code == 429:
            raise AdapterError("M3U Editor allows five syncs a minute; try again shortly.", code="rate_limited")
        if response.status_code >= 300:
            raise AdapterError(f"M3U Editor answered with HTTP {response.status_code}.", code="http_error")
        ctx.forget_answers()
        return "The sync has started."

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        if widget_kind == "overview":
            streams = 3 + int(fake.walk("m3u-streams", tick, 0, 3))
            viewers = streams + 2
            return WidgetData(
                status="ok",
                primary={"label": "Streams", "value": streams},
                secondary=[{"label": "Viewers", "value": viewers}, {"label": "Bandwidth", "value": f"{streams * 6.2:.1f} Mbit/s"},
                           {"label": "Playlists", "value": 4}, {"label": "Channels", "value": 1284}, {"label": "Guides", "value": 2}],
                metrics={"streams": float(streams), "viewers": float(viewers)},
                meta={"status_reason": ""},
            )
        if widget_kind == "streams":
            rows = [("Harbour News HD", "2 viewer(s) · anna, ben · started 41 min ago", "8.3 Mbit/s", "ok"),
                    ("Northfield Sports 1", "1 viewer(s) · living-room · started 2 h ago · On a failover source", "6.1 Mbit/s", "warn"),
                    ("Quiet Valley Docs", "1 viewer(s) · kids · started 12 min ago", "4.4 Mbit/s", "ok")]
            return WidgetData(status="warn", items=[
                {"id": str(index), "title": title, "subtitle": subtitle, "value": value, "status": status}
                for index, (title, subtitle, value, status) in enumerate(rows, start=1)],
                secondary=[{"label": "Viewers", "value": 4}, {"label": "Bandwidth", "value": "18.8 Mbit/s"}],
                meta={"empty": "Nobody is watching."})
        if widget_kind == "playlists":
            rows = [("Example IPTV", "812 of 2140 channels on · 96 groups · synced 3 h ago", "Synced", "ok"),
                    ("Free channels", "164 of 164 channels on · 12 groups · synced 1 d ago", "Synced", "ok"),
                    ("Family", "Custom playlist · 58 of 58 channels on · 6 groups", "", "ok")]
            return WidgetData(status="ok", items=[
                {"id": str(index), "title": title, "subtitle": subtitle, "value": value, "status": status,
                 **({"actions": [Action(id="sync", label="Sync", icon="refresh-cw", params={"uuid": str(index)})]} if value else {})}
                for index, (title, subtitle, value, status) in enumerate(rows, start=1)], meta={"empty": "No playlist yet."})
        if widget_kind == "epgs":
            rows = [("Example guide", "1840 channels · synced 5 h ago", "Synced", "ok"),
                    ("Sports guide", "212 channels · synced 3 d ago", "Failed", "bad")]
            return WidgetData(status="warn", items=[
                {"id": str(index), "title": title, "subtitle": subtitle, "value": value, "status": status,
                 "actions": [Action(id="sync", label="Sync", icon="refresh-cw", params={"uuid": str(index)})]}
                for index, (title, subtitle, value, status) in enumerate(rows, start=1)], meta={"empty": "No guide yet."})
        rows = [("Evening Report", "Harbour News HD · ends in 24 min", "Recording", "ok"),
                ("Cup Final", "Northfield Sports 1", "in 3 h", "ok"),
                ("Deep Sea Worlds", "Quiet Valley Docs", "in 1 d", "ok"),
                ("Morning Show", "Harbour News HD · ended 9 h ago · 2.1 GB", "Done", "ok")]
        return WidgetData(status="ok", items=[
            {"id": index, "title": title, "subtitle": subtitle, "value": value, "status": status}
            for index, (title, subtitle, value, status) in enumerate(rows, start=1)],
            secondary=[{"label": "Recording", "value": 1}, {"label": "Scheduled", "value": 2}],
            meta={"empty": "No recording yet."})


ADAPTER = M3uEditorAdapter()
