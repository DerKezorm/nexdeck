"""Jellyfin, and by inheritance Emby: streams, library, recent covers, findings, users and the period's top."""

from __future__ import annotations

import asyncio
import secrets
import time
from collections import Counter, defaultdict
from datetime import UTC, datetime
from typing import Any

from .base import (
    AdapterError,
    Context,
    Field,
    MediaSource,
    WidgetData,
    WidgetType,
    base_url,
    human_bytes,
    path_segment,
)
from .media_base import Library, MediaAdapter, Stream
from .music import (
    ALBUM_PAGE,
    ARTIST_PAGE,
    PICKS,
    PLAYER_ALBUMS,
    PLAYLIST_LIMIT,
    QUALITY_KBPS,
    SHUFFLE_SIZE,
    Album,
    Artist,
    MusicLibrary,
    Playlist,
    Shelf,
    ShelfQuery,
    Sound,
    SoundRequest,
    Track,
    batches,
    demo_player,
    next_offset,
    player_data,
    player_widget,
    seconds,
    wants_random_picks,
    whole,
)

TICKS_PER_SECOND = 10_000_000
#: Which item types a "recently added" widget draws from, per choice.
KINDS = {"all": ("Movie", "Episode", "MusicAlbum"), "movies": ("Movie",), "series": ("Episode",), "music": ("MusicAlbum",)}
KIND_NAMES = {"Movie": "movie", "Episode": "episode", "Series": "show", "MusicAlbum": "album", "Audio": "track"}
#: Folders of Jellyfin's storage report, and how a card names them.
STORAGE_FOLDERS = (
    ("ProgramDataFolder", "Program data"), ("CacheFolder", "Cache"), ("TranscodingTempFolder", "Transcodes"),
    ("LogFolder", "Logs"), ("InternalMetadataFolder", "Metadata"), ("ImageCacheFolder", "Image cache"),
)
#: Activity log severities that are trouble; sign-in failures are counted on their own.
TROUBLE = ("Error", "Critical")
LOG_PAGE = 500
#: The window the activity question is rounded to.
LOG_BUCKET = 300
LOG_LIMIT = 5000
#: The DeviceId every request carries, so the server keeps one entry for nexdeck.
DEVICE_ID = "nexdeck"
#: What each codec a browser names is called in Jellyfin's container list.
#: ``m4a|aac`` is a container and the codec inside it, the way jellyfin-web
#: writes it; an ALAC file comes in the same m4a box and must not pass as AAC.
CONTAINERS = {
    "flac": ("flac",),
    "mp3": ("mp3",),
    "aac": ("aac", "m4a|aac", "m4b|aac"),
    "alac": ("m4a|alac",),
    "opus": ("opus", "ogg|opus", "webm|opus"),
    "vorbis": ("ogg|vorbis", "webma|vorbis"),
    "wav": ("wav",),
}


def containers_for(formats: tuple[str, ...]) -> str:
    """The container list of ``/Audio/{id}/universal`` for what a browser plays."""
    return ",".join(entry for name in formats for entry in CONTAINERS.get(name, ()))


def parse_time(value: Any) -> float:
    """An ISO timestamp of the API as seconds since the epoch; the API writes seven fractional digits, Python reads six."""
    text = str(value or "").strip()
    if not text:
        return 0.0
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    head, dot, tail = text.partition(".")
    if dot:
        digits = 0
        while digits < len(tail) and tail[digits].isdigit():
            digits += 1
        text = f"{head}.{tail[: min(digits, 6)] or '0'}{tail[digits:]}"
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return 0.0
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.timestamp()


def device_names(names: Counter[str]) -> str:
    """Two Chromes are two devices: the same name once, with how many there are."""
    return ", ".join(f"{name} ×{count}" if count > 1 else name for name, count in sorted(names.items()))


class JellyfinAdapter(MediaAdapter, MusicLibrary):
    kind = "jellyfin"
    #: Confirmed against a live instance on 2026-09-05.
    beta = False
    label = "Jellyfin"
    description = "Active streams, library size and what was added last, with covers."
    icon = "jellyfin"
    docs_url = "https://api.jellyfin.org/"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://jellyfin:8096"),
        Field("api_key", "API key", type="password", secret=True, required=True, help="Dashboard > API Keys"),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    token_header = "Authorization"
    #: Activity log types that mean "someone started playing", and the type of a failed sign-in.
    PLAYBACK_TYPES = ("VideoPlayback", "AudioPlayback")
    SIGNIN_FAILED = "AuthenticationFailed"
    widgets = MediaAdapter.widgets + (
        WidgetType(
            kind="recent",
            label="Recently added",
            description="The newest movies, series or albums with their covers.",
            renderer="posters",
            default_size=(4, 3),
            min_size=(2, 2),
            refresh_seconds=300,
            options=(
                Field("kind", "Type", type="select", default="all", options=(("all", "Everything"), ("movies", "Movies"), ("series", "Series"), ("music", "Music"))),
                Field("limit", "Items", type="number", default=8),
            ),
        ),
        WidgetType(
            kind="findings",
            label="Findings",
            description="Does the server run, and what needs a look: pending restarts, failed tasks, scans, sign-in failures, disk space.",
            renderer="list",
            default_size=(3, 2),
            refresh_seconds=60,
        ),
        WidgetType(
            kind="users",
            label="Users and devices",
            description="Every account with access, who was active, and on which devices.",
            renderer="list",
            default_size=(3, 3),
            refresh_seconds=300,
            options=(Field("days", "Active within (days)", type="number", default=1),),
        ),
        WidgetType(
            kind="top",
            label="Top of the week",
            description="The most watched titles with their covers, and how often.",
            renderer="posters",
            default_size=(4, 3),
            min_size=(2, 2),
            refresh_seconds=900,
            options=(
                Field("days", "Period", type="select", default="7", options=(("7", "7 days"), ("30", "30 days"))),
                Field("limit", "Items", type="number", default=6),
            ),
        ),
        player_widget((
            Field("account", "Account", type="choices",
                  help="Whose view of the library and whose playlists the card uses. Nothing is reported back: plays do not count on the server."),
            Field("music_library", "Music library", type="choices", help="Empty means every music library."),
        )),
    )
    #: Both measured on Jellyfin 10.11.11: ``/Items/{id}/InstantMix`` and HLS
    #: from ``/Audio/{id}/universal``. Emby inherits them unmeasured, because the
    #: Emby server at hand had no music on it.
    music_features = ("mix", "hls")

    # -- plumbing ----------------------------------------------------------------

    def _headers(self, config: dict[str, Any]) -> dict[str, str]:
        token = str(config.get("api_key") or "")
        if self.token_header == "Authorization":
            return {"Authorization": f'MediaBrowser Token="{token}", Client="nexdeck", Device="nexdeck", DeviceId="nexdeck", Version="1"'}
        return {self.token_header: token}

    def image_headers(self, config: dict[str, Any]) -> dict[str, str]:
        return self._headers(config)

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, params: dict[str, Any] | None = None, cache: float = 5) -> Any:
        return await ctx.get_json(f"{base_url(config)}{path}", headers=self._headers(config), params=params, verify=not config.get("insecure"), cache_seconds=cache)

    async def _optional(self, config: dict[str, Any], ctx: Context, path: str, params: dict[str, Any] | None = None, cache: float = 5) -> Any:
        """A GET the server may not know: Emby has no storage report, a limited key no plugin list."""
        try:
            return await self._get(config, ctx, path, params=params, cache=cache)
        except AdapterError:
            return None

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        info = await self._get(config, ctx, "/System/Info", cache=0)
        return f"{self.label} {info.get('Version', '?')} on {info.get('ServerName', '?')}."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "recent":
            return await self._recent(config, options, ctx)
        if widget_kind == "findings":
            return await self._findings(config, options, ctx)
        if widget_kind == "users":
            return await self._users(config, options, ctx)
        if widget_kind == "top":
            return await self._top(config, options, ctx)
        if widget_kind == "player":
            return await self._player(config, options, ctx)
        return await super().fetch(widget_kind, config, options, ctx)

    @staticmethod
    def _art(item_id: Any) -> str:
        return f"proxy:/Items/{item_id}/Images/Primary?maxHeight=400" if item_id else ""

    # -- streams and library (the shared media shape) ----------------------------

    async def sessions(self, config: dict[str, Any], ctx: Context) -> list[Stream]:
        payload = await self._get(config, ctx, "/Sessions", params={"ActiveWithinSeconds": 300})
        streams = []
        for session in payload or []:
            item = session.get("NowPlayingItem")
            if not item:
                continue
            duration = float(item.get("RunTimeTicks") or 0) / TICKS_PER_SECOND
            position = float((session.get("PlayState") or {}).get("PositionTicks") or 0) / TICKS_PER_SECOND
            progress = 100.0 * position / duration if duration else 0.0
            title = item.get("Name", "?")
            if item.get("Type") == "Episode":
                title = f"{item.get('SeriesName', '?')} S{int(item.get('ParentIndexNumber') or 0):02d}E{int(item.get('IndexNumber') or 0):02d}"
            transcoding_info = session.get("TranscodingInfo") or {}
            transcoding = bool(transcoding_info) and not transcoding_info.get("IsVideoDirect", True)
            height = None
            for stream in item.get("MediaStreams") or []:
                if stream.get("Type") == "Video":
                    height = stream.get("Height")
                    break
            quality = f"{height}p" if height else ""
            subtitle = " · ".join(p for p in [session.get("UserName", ""), session.get("DeviceName", ""), quality, "Transcode" if transcoding else "Direct play"] if p)
            streams.append(Stream(
                title=title, subtitle=subtitle, user=session.get("UserName", ""), progress=progress,
                remaining_seconds=(duration - position) if duration else None,
                paused=bool((session.get("PlayState") or {}).get("IsPaused")), transcoding=transcoding,
                art=self._art(item.get("SeriesId") or item.get("Id")),
            ))
        return streams

    async def counts(self, config: dict[str, Any], ctx: Context) -> dict[str, int]:
        payload = await self._get(config, ctx, "/Items/Counts", cache=600)
        return {
            "Movies": int(payload.get("MovieCount") or 0),
            "Series": int(payload.get("SeriesCount") or 0),
            "Episodes": int(payload.get("EpisodeCount") or 0),
        }

    # -- recently added ----------------------------------------------------------

    async def _recent(self, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        """The newest items of the chosen types, one poster each; a series appears once, with its newest episode."""
        wanted = KINDS.get(str(options.get("kind") or "all"), KINDS["all"])
        limit = max(1, min(40, int(options.get("limit") or 8)))
        items: list[dict[str, Any]] = []
        for item_type in wanted:
            payload = await self._get(config, ctx, "/Items", cache=120, params={
                "SortBy": "DateCreated", "SortOrder": "Descending", "Recursive": "true", "IncludeItemTypes": item_type,
                "Limit": limit * 5 if item_type == "Episode" else limit,
                "Fields": "DateCreated,ProductionYear,SeriesId,ParentIndexNumber,IndexNumber,AlbumArtist",
            })
            seen: set[str] = set()
            for entry in (payload or {}).get("Items") or []:
                series = str(entry.get("SeriesId") or "")
                if item_type == "Episode" and series:
                    if series in seen:
                        continue
                    seen.add(series)
                items.append(self._poster(entry))
        items.sort(key=lambda item: item.get("added_at") or 0, reverse=True)
        return WidgetData(items=items[:limit], meta={"empty": "Nothing new"})

    def _poster(self, entry: dict[str, Any]) -> dict[str, Any]:
        kind = str(entry.get("Type") or "")
        title = str(entry.get("Name") or "?")
        subtitle = str(entry.get("ProductionYear") or "")
        art_id = entry.get("Id")
        if kind == "Episode":
            title, subtitle = str(entry.get("SeriesName") or title), f"S{int(entry.get('ParentIndexNumber') or 0):02d}E{int(entry.get('IndexNumber') or 0):02d} · {title}"
            art_id = entry.get("SeriesId") or art_id
        elif kind == "MusicAlbum":
            subtitle = str(entry.get("AlbumArtist") or subtitle)
        return {"title": title, "subtitle": subtitle, "art": self._art(art_id), "kind": KIND_NAMES.get(kind, kind.lower()), "added_at": parse_time(entry.get("DateCreated"))}

    # -- activity log: findings, users, top -----------------------------------------

    async def _log(self, config: dict[str, Any], ctx: Context, days: int) -> list[dict[str, Any]]:
        """The activity log of the period, page by page, newest first."""
        # Rounded to the cache window, so two widgets share one answer.
        since = (int(time.time()) // LOG_BUCKET) * LOG_BUCKET - days * 86400
        min_date = datetime.fromtimestamp(since, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        rows: list[dict[str, Any]] = []
        start = 0
        while True:
            payload = await self._get(config, ctx, "/System/ActivityLog/Entries", cache=60, params={"MinDate": min_date, "StartIndex": start, "Limit": LOG_PAGE})
            page = (payload or {}).get("Items") or []
            rows.extend(entry for entry in page if parse_time(entry.get("Date")) >= since)
            start += len(page)
            if not page or start >= int((payload or {}).get("TotalRecordCount") or 0) or start >= LOG_LIMIT:
                break
        return rows

    # -- the libraries, and looking for new files ------------------------------

    async def library_list(self, config: dict[str, Any], ctx: Context) -> list[Library]:
        """⚠️ One call, and it already says whether a scan is running.

        ``/Library/VirtualFolders`` carries ``RefreshStatus`` and
        ``RefreshProgress`` per library, which is more than Plex hands out
        anywhere but its activity list. The findings card has read the same
        two fields since it was written.
        """
        folders = await self._get(config, ctx, "/Library/VirtualFolders", cache=60) or []
        rows: list[Library] = []
        for folder in folders:
            item_id = str(folder.get("ItemId") or "")
            if not item_id:
                continue
            state = str(folder.get("RefreshStatus") or "").lower()
            progress = folder.get("RefreshProgress")
            rows.append(Library(
                id=item_id,
                name=str(folder.get("Name") or "Library"),
                kind=str(folder.get("CollectionType") or ""),
                scanning=bool(state) and state not in ("idle", "completed", "cancelled", "failed"),
                progress=float(progress) if isinstance(progress, (int, float)) else None,
            ))
        return rows

    #: ⚠️ Measured on 08.09.2026 against live Jellyfin and Emby instances:
    #: ``POST /Items/{id}/Refresh`` on a library folder answers 204 and then
    #: does nothing. The "Scan media library" task does not run, the folder's
    #: ``RefreshStatus`` never moves, and ``metadataRefreshMode=ValidationOnly``
    #: changes neither. Only ``/Library/Refresh`` runs, and it reads
    #: everything. The specification says none of this; it took three calls
    #: against a real server, and the first version of this adapter shipped a
    #: per-library button that quietly did nothing.
    #:
    #: If per library is ever wanted here, ``POST /Library/Media/Updated`` is
    #: the next thing to measure: it is how Sonarr and Radarr tell Jellyfin
    #: that one path changed. It needs the library's path, which
    #: ``/Library/VirtualFolders`` carries in ``Locations``.
    can_scan_one = False

    async def rescan(self, config: dict[str, Any], target: str, ctx: Context) -> str:
        """Look for new files. Everything, because one library does not work.

        ⚠️ Deliberately with no parameters at all. ``replaceAllMetadata`` and
        ``replaceAllImages`` default to false, and naming them here even as
        false would put a rewrite of the whole library one typo away.
        """
        await self._post(config, ctx, "/Library/Refresh")
        return f"{self.label} is looking for new files in every library."

    async def _post(self, config: dict[str, Any], ctx: Context, path: str) -> None:
        response = await ctx.request(
            "POST", f"{base_url(config)}{path}", headers=self._headers(config),
            verify=not config.get("insecure"), timeout=20.0,
        )
        if response.status_code >= 400:
            raise AdapterError(f"{self.label} answered with HTTP {response.status_code}.", code="action_failed")

    async def _findings(self, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        """What an operator would want to know about the server itself, one row per finding."""
        info = await self._get(config, ctx, "/System/Info", cache=60) or {}
        folders = await self._get(config, ctx, "/Library/VirtualFolders", cache=120) or []
        tasks = await self._get(config, ctx, "/ScheduledTasks", cache=30) or []
        sessions = await self._get(config, ctx, "/Sessions", params={"ActiveWithinSeconds": 300}) or []
        log = await self._log(config, ctx, 1)
        plugins = await self._optional(config, ctx, "/Plugins", cache=600) or []
        storage = await self._optional(config, ctx, "/System/Storage", cache=300)
        items: list[dict[str, Any]] = []
        if info.get("HasUpdateAvailable"):
            items.append({"title": self.label, "subtitle": "Update available", "status": "unknown"})
        if info.get("HasPendingRestart"):
            items.append({"title": self.label, "subtitle": "A restart is pending", "status": "warn"})
        for task in tasks:
            name = str(task.get("Name") or "Task")
            if task.get("State") == "Running":
                progress = task.get("CurrentProgressPercentage")
                items.append({"title": name, "subtitle": "running" + (f" · {int(progress)}%" if isinstance(progress, (int, float)) else ""), "status": "unknown"})
                continue
            result = task.get("LastExecutionResult") or {}
            if result.get("Status") in ("Failed", "Aborted"):
                items.append({"title": name, "subtitle": "The last run failed" + f" · {result.get('ErrorMessage') or result.get('Status')}", "status": "warn"})
        for folder in folders:
            name = str(folder.get("Name") or "Library")
            state = str(folder.get("RefreshStatus") or "")
            if state and state.lower() not in ("idle", "completed", "cancelled", "failed"):
                progress = folder.get("RefreshProgress")
                items.append({"title": name, "subtitle": f"{name} is being scanned" + (f" · {int(progress)}%" if isinstance(progress, (int, float)) else ""), "status": "unknown"})
        transcodes = sum(1 for session in sessions if session.get("NowPlayingItem") and session.get("TranscodingInfo") and not (session.get("TranscodingInfo") or {}).get("IsVideoDirect", True))
        if transcodes >= 3:
            items.append({"title": "Transcoder", "subtitle": f"{transcodes} video transcodes running", "status": "unknown"})
        failed = sum(1 for entry in log if entry.get("Type") == self.SIGNIN_FAILED)
        if failed >= 5:
            items.append({"title": "Sign-in", "subtitle": f"{failed} failed sign-ins in 24 h", "status": "warn"})
        errors = [entry for entry in log if entry.get("Severity") in TROUBLE and entry.get("Type") != self.SIGNIN_FAILED]
        if errors:
            items.append({"title": "Activity log", "subtitle": f"{len(errors)} error(s) in 24 h · {errors[0].get('Name') or errors[0].get('Type')}", "status": "warn"})
        for plugin in plugins:
            state = str(plugin.get("Status") or "")
            if state == "Malfunctioned":
                items.append({"title": str(plugin.get("Name") or "Plugin"), "subtitle": "Plugin malfunctioned", "status": "bad"})
            elif state == "Restart":
                items.append({"title": str(plugin.get("Name") or "Plugin"), "subtitle": "Plugin needs a restart", "status": "unknown"})
        for name, folder in self._storage(storage):
            free, used = folder.get("FreeSpace"), folder.get("UsedSpace")
            if isinstance(free, (int, float)) and isinstance(used, (int, float)) and free + used > 0 and free < 0.05 * (free + used):
                items.append({"title": name, "subtitle": f"{human_bytes(free)} free", "status": "warn"})
        order = {"bad": 0, "warn": 1, "unknown": 2}
        items.sort(key=lambda item: order.get(str(item["status"]), 3))
        bad = sum(1 for item in items if item["status"] == "bad")
        warn = sum(1 for item in items if item["status"] == "warn")
        meta: dict[str, Any] = {"empty": f"{self.label} answers · {info.get('Version', '?')} · {len(folders)} libraries"}
        if bad or warn:
            meta["status_reason"] = f"{bad} error finding(s), {warn} warning(s)"
        return WidgetData(status="bad" if bad else ("warn" if warn else "ok"), items=items, meta=meta)

    @staticmethod
    def _storage(report: Any) -> list[tuple[str, dict[str, Any]]]:
        """The folders of Jellyfin's storage report, each device once."""
        if not isinstance(report, dict):
            return []
        candidates = [(label, report.get(key)) for key, label in STORAGE_FOLDERS]
        for library in report.get("Libraries") or []:
            for folder in library.get("Folders") or []:
                candidates.append((str(library.get("Name") or "Library"), folder))
        folders: list[tuple[str, dict[str, Any]]] = []
        seen: set[str] = set()
        for label, folder in candidates:
            if not isinstance(folder, dict):
                continue
            key = str(folder.get("DeviceId") or folder.get("Path") or label)
            if key in seen:
                continue
            seen.add(key)
            folders.append((label, folder))
        return folders

    async def _users(self, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        days = max(1, int(options.get("days") or 1))
        since = time.time() - days * 86400
        users = await self._get(config, ctx, "/Users", cache=600) or []
        devices = ((await self._get(config, ctx, "/Devices", cache=300)) or {}).get("Items") or []
        log = await self._log(config, ctx, days)
        known = {str(user.get("Id") or "") for user in users}
        plays: Counter[str] = Counter()
        for log_id, count in Counter(str(entry.get("UserId") or "") for entry in log if entry.get("Type") in self.PLAYBACK_TYPES).items():
            plays[log_id if log_id in known else await self._resolve_user(config, ctx, log_id)] += count
        used: dict[str, Counter[str]] = defaultdict(Counter)
        active_devices: set[str] = set()
        for device in devices:
            if parse_time(device.get("DateLastActivity")) < since:
                continue
            active_devices.add(str(device.get("Id") or device.get("ReportedDeviceId") or device.get("Name") or len(active_devices)))
            used[str(device.get("LastUserName") or "")][str(device.get("CustomName") or device.get("Name") or device.get("AppName") or "?")] += 1
        items: list[dict[str, Any]] = []
        for user in users:
            name = str(user.get("Name") or "?")
            count = plays.get(str(user.get("Id") or ""), 0)
            seen = parse_time(user.get("LastActivityDate")) >= since
            names = device_names(used[name]) if used.get(name) else ""
            if (user.get("Policy") or {}).get("IsDisabled"):
                subtitle, status = "disabled", "unknown"
            elif count:
                subtitle, status = f"{count} play(s)" + (f" · {names}" if names else ""), "ok"
            elif seen:
                subtitle, status = "signed in, no plays" + (f" · {names}" if names else ""), "ok"
            else:
                subtitle, status = "no activity", "unknown"
            items.append({"title": name, "subtitle": subtitle, "status": status, "value": str(count) if count else "", "plays": count, "seen": seen})
        items.sort(key=lambda item: (-int(item["plays"]), not item["seen"], str(item["title"]).lower()))
        for item in items:
            item.pop("plays", None)
            item.pop("seen", None)
        active = sum(1 for item in items if item["status"] == "ok")
        return WidgetData(
            items=items,
            secondary=[{"label": "Accounts", "value": len(users)}, {"label": "Active", "value": active}, {"label": "Devices", "value": len(active_devices)}],
            metrics={"active": float(active)},
            meta={"empty": "No accounts"},
        )

    async def _resolve_user(self, config: dict[str, Any], ctx: Context, log_id: str) -> str:
        """Emby writes its internal user number into the activity log; the user list carries the long id."""
        if not log_id or not log_id.isalnum():
            return log_id
        payload = await self._optional(config, ctx, f"/Users/{log_id}", cache=600)
        return str((payload or {}).get("Id") or log_id)

    async def _top(self, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        days = 30 if str(options.get("days") or "7") == "30" else 7
        limit = max(1, min(40, int(options.get("limit") or 6)))
        log = await self._log(config, ctx, days)
        by_item: Counter[str] = Counter(str(entry.get("ItemId")) for entry in log if entry.get("Type") in self.PLAYBACK_TYPES and entry.get("ItemId"))
        resolved: dict[str, dict[str, Any]] = {}
        ids = sorted(by_item)
        for offset in range(0, len(ids), 50):
            payload = await self._get(config, ctx, "/Items", cache=600, params={"Ids": ",".join(ids[offset:offset + 50]), "Fields": "SeriesId,AlbumId,ProductionYear"})
            for item in (payload or {}).get("Items") or []:
                resolved[str(item.get("Id"))] = item
        plays: Counter[str] = Counter()
        posters: dict[str, dict[str, Any]] = {}
        for item_id, count in by_item.items():
            item = resolved.get(item_id)
            if not item:
                continue
            kind = str(item.get("Type") or "")
            if kind == "Episode":
                key, title, art_id = str(item.get("SeriesId") or item_id), str(item.get("SeriesName") or item.get("Name") or "?"), item.get("SeriesId") or item.get("Id")
            elif kind == "Audio":
                key, title, art_id = str(item.get("AlbumId") or item_id), str(item.get("Album") or item.get("Name") or "?"), item.get("AlbumId") or item.get("Id")
            else:
                key, title, art_id = item_id, str(item.get("Name") or "?"), item.get("Id")
            plays[key] += count
            posters.setdefault(key, {"title": title, "art": self._art(art_id), "kind": KIND_NAMES.get(kind, kind.lower())})
        items = [{**posters[key], "subtitle": f"{count} play(s)"} for key, count in plays.most_common(limit)]
        return WidgetData(items=items, meta={"empty": "Nothing watched"})

    # -- music: the player card ----------------------------------------------------

    async def _listener(self, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> str:
        """The account the card browses the library as.

        ⚠️ A key belongs to no account (measured: ``/Users/Me`` answers a key
        with 400), and the item routes want one. The card names an account, or
        the first administrator stands in. One that was named and is gone is an
        error rather than a quiet switch to somebody else's playlists.
        """
        users = await self._get(config, ctx, "/Users", cache=600) or []
        wanted = str(options.get("account") or "")
        if wanted:
            if any(str(user.get("Id")) == wanted for user in users):
                return wanted
            raise AdapterError("The account this card plays as is no longer on the server.", code="no_such_account",
                               hint="Pick another account in the card's settings.")
        chosen = next((user for user in users if (user.get("Policy") or {}).get("IsAdministrator")), None) or (users[0] if users else None)
        if not chosen:
            raise AdapterError("The server has no account to play as.", code="no_account")
        return str(chosen.get("Id"))

    async def _items(self, config: dict[str, Any], ctx: Context, account: str, cache: float = 60, **params: Any) -> dict[str, Any]:
        return await self._get(config, ctx, f"/Users/{account}/Items", params={"Recursive": "true", **params}, cache=cache) or {}

    @staticmethod
    def _scope(options: dict[str, Any]) -> dict[str, str]:
        library = str(options.get("music_library") or "")
        return {"ParentId": path_segment(library, "The music library")} if library else {}

    @staticmethod
    def _cover(item_id: Any) -> tuple[str, str]:
        """A large cover for the player and a small one for rows, both through the image route."""
        if not item_id:
            return "", ""
        return (f"proxy:/Items/{item_id}/Images/Primary?maxWidth=800&maxHeight=800&quality=90",
                f"proxy:/Items/{item_id}/Images/Primary?maxWidth=240&maxHeight=240&quality=85")

    def _album(self, entry: dict[str, Any]) -> Album:
        # ⚠️ Only when the item says it has one. Measured: an album without a
        # cover answers the image address with 404, and a grid of those is a
        # grid of broken pictures instead of placeholders.
        art, thumb = self._cover(entry.get("Id") if (entry.get("ImageTags") or {}).get("Primary") else None)
        artists = entry.get("AlbumArtists") or []
        return Album(
            id=str(entry.get("Id") or ""), title=str(entry.get("Name") or "?"),
            artist=str(entry.get("AlbumArtist") or ", ".join(str(one) for one in entry.get("Artists") or [])),
            artist_id=str((artists[0] or {}).get("Id") or "") if artists else "",
            year=whole(entry.get("ProductionYear")), tracks=whole(entry.get("ChildCount")), art=art, thumb=thumb,
        )

    def _track(self, entry: dict[str, Any]) -> Track:
        source = (entry.get("MediaSources") or [{}])[0]
        audio = next((one for one in source.get("MediaStreams") or [] if one.get("Type") == "Audio"), {})
        album_id = str(entry.get("AlbumId") or "")
        if album_id and entry.get("AlbumPrimaryImageTag"):
            art, thumb = self._cover(album_id)
        else:
            art, thumb = self._cover(entry.get("Id") if (entry.get("ImageTags") or {}).get("Primary") else None)
        performers = entry.get("ArtistItems") or []
        bitrate = whole(audio.get("BitRate") or source.get("Bitrate"))
        return Track(
            id=str(entry.get("Id") or ""), title=str(entry.get("Name") or "?"),
            artist=", ".join(str(one) for one in entry.get("Artists") or []) or str(entry.get("AlbumArtist") or ""),
            album=str(entry.get("Album") or ""), album_id=album_id,
            artist_id=str((performers[0] or {}).get("Id") or "") if performers else "",
            duration=seconds(entry.get("RunTimeTicks"), TICKS_PER_SECOND), number=whole(entry.get("IndexNumber")),
            disc=whole(entry.get("ParentIndexNumber")), art=art, thumb=thumb,
            codec=str(audio.get("Codec") or source.get("Container") or entry.get("Container") or "").lower(),
            bit_depth=whole(audio.get("BitDepth")), sample_rate=whole(audio.get("SampleRate")),
            bitrate=round(bitrate / 1000) if bitrate else None,
        )

    def _playlist(self, entry: dict[str, Any]) -> Playlist:
        art, thumb = self._cover(entry.get("Id") if (entry.get("ImageTags") or {}).get("Primary") else None)
        return Playlist(id=str(entry.get("Id") or ""), title=str(entry.get("Name") or "?"), tracks=whole(entry.get("ChildCount")),
                        duration=seconds(entry.get("RunTimeTicks"), TICKS_PER_SECOND), art=art, thumb=thumb)

    async def _player(self, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        account = await self._listener(config, options, ctx)
        scope = self._scope(options)
        newest = await self._items(config, ctx, account, cache=300, IncludeItemTypes="MusicAlbum", SortBy="DateCreated,SortName",
                                   SortOrder="Descending", Limit=PLAYER_ALBUMS, Fields="ChildCount,ProductionYear", **scope)
        artists = await self._items(config, ctx, account, cache=600, IncludeItemTypes="MusicArtist", Limit=0, **scope)
        tracks = await self._items(config, ctx, account, cache=600, IncludeItemTypes="Audio", Limit=0, **scope)
        picks = None
        if wants_random_picks(options):
            # ⚠️ Only albums with a cover. Measured on 10.11.11: many albums of
            # the library have none, and a random pick of discs is no picture.
            chosen = await self._items(config, ctx, account, cache=0, IncludeItemTypes="MusicAlbum", SortBy="Random", ImageTypes="Primary",
                                       Limit=PICKS, Fields="ChildCount,ProductionYear", EnableTotalRecordCount="false", **scope)
            picks = [self._album(entry) for entry in chosen.get("Items") or []]
        return player_data(
            [self._album(entry) for entry in newest.get("Items") or []],
            {"Albums": whole(newest.get("TotalRecordCount")), "Artists": whole(artists.get("TotalRecordCount")),
             "Tracks": whole(tracks.get("TotalRecordCount"))},
            self.music_features,
            picks,
        )

    async def music_shelf(self, config: dict[str, Any], options: dict[str, Any], view: str, query: ShelfQuery, ctx: Context) -> Shelf:
        account = await self._listener(config, options, ctx)
        scope = self._scope(options)
        if view == "albums":
            order = {"newest": ("DateCreated,SortName", "Descending"), "name": ("SortName", "Ascending"), "random": ("Random", "Ascending")}
            sort_by, direction = order.get(query.sort, order["newest"])
            payload = await self._items(config, ctx, account, cache=0 if query.sort == "random" else 120, IncludeItemTypes="MusicAlbum",
                                        SortBy=sort_by, SortOrder=direction, StartIndex=query.offset, Limit=ALBUM_PAGE,
                                        Fields="ChildCount,ProductionYear", **scope)
            albums = [self._album(entry) for entry in payload.get("Items") or []]
            total = whole(payload.get("TotalRecordCount"))
            return Shelf(albums=albums, total=total, next=next_offset(query.offset, len(albums), total))
        if view == "artists":
            # ⚠️ Artists as items, not ``/Artists/AlbumArtists``. Measured on
            # 10.11.11: sixty album artists took 4.5 s, sixty artist items 0.75 s.
            payload = await self._items(config, ctx, account, cache=300, IncludeItemTypes="MusicArtist", SortBy="SortName",
                                        StartIndex=query.offset, Limit=ARTIST_PAGE, **scope)
            artists = []
            for entry in payload.get("Items") or []:
                art, thumb = self._cover(entry.get("Id") if (entry.get("ImageTags") or {}).get("Primary") else None)
                artists.append(Artist(id=str(entry.get("Id") or ""), name=str(entry.get("Name") or "?"), art=art, thumb=thumb))
            total = whole(payload.get("TotalRecordCount"))
            return Shelf(artists=artists, total=total, next=next_offset(query.offset, len(artists), total))
        if view == "artist":
            artist_id = path_segment(query.id, "The artist")
            about = await self._get(config, ctx, f"/Users/{account}/Items/{artist_id}", cache=300) or {}
            payload = await self._items(config, ctx, account, cache=120, IncludeItemTypes="MusicAlbum", AlbumArtistIds=artist_id,
                                        SortBy="ProductionYear,SortName", SortOrder="Descending", Fields="ChildCount,ProductionYear")
            albums = [self._album(entry) for entry in payload.get("Items") or []]
            art, _thumb = self._cover(artist_id if (about.get("ImageTags") or {}).get("Primary") else None)
            return Shelf(title=str(about.get("Name") or ""), art=art, albums=albums, total=len(albums))
        if view == "album":
            album_id = path_segment(query.id, "The album")
            about = self._album(await self._get(config, ctx, f"/Users/{account}/Items/{album_id}", cache=300) or {"Id": album_id})
            payload = await self._items(config, ctx, account, cache=120, ParentId=album_id, IncludeItemTypes="Audio",
                                        SortBy="ParentIndexNumber,IndexNumber,SortName", Fields="MediaSources")
            tracks = [self._track(entry) for entry in payload.get("Items") or []]
            subtitle = " · ".join(part for part in (about.artist, str(about.year or "")) if part)
            return Shelf(title=about.title, subtitle=subtitle, art=about.art, tracks=tracks, total=len(tracks))
        if view == "playlists":
            payload = await self._items(config, ctx, account, cache=120, IncludeItemTypes="Playlist", MediaTypes="Audio",
                                        SortBy="SortName", Fields="ChildCount")
            playlists = [self._playlist(entry) for entry in payload.get("Items") or []]
            return Shelf(playlists=playlists, total=len(playlists))
        if view == "playlist":
            playlist_id = path_segment(query.id, "The playlist")
            about = self._playlist(await self._get(config, ctx, f"/Users/{account}/Items/{playlist_id}", cache=300) or {"Id": playlist_id})
            # ⚠️ The playlist route, not ``ParentId``: only this one keeps the order somebody put the tracks in.
            payload = await self._get(config, ctx, f"/Playlists/{playlist_id}/Items", cache=60,
                                      params={"UserId": account, "Limit": PLAYLIST_LIMIT}) or {}
            tracks = []
            for entry in payload.get("Items") or []:
                track = self._track(entry)
                track.entry = str(entry.get("PlaylistItemId") or "")
                tracks.append(track)
            return Shelf(title=about.title, art=about.art, tracks=tracks, total=whole(payload.get("TotalRecordCount")) or len(tracks), editable=True)
        if view == "search":
            words = query.q.strip()
            if not words:
                return Shelf()
            # Three small questions at once rather than one mixed one: measured,
            # the mixed search for "the" came back as 58 tracks and 2 albums.
            found = await asyncio.gather(
                self._items(config, ctx, account, cache=30, SearchTerm=words, IncludeItemTypes="MusicAlbum", Limit=20, Fields="ChildCount,ProductionYear", **scope),
                self._items(config, ctx, account, cache=30, SearchTerm=words, IncludeItemTypes="MusicArtist", Limit=12, **scope),
                self._items(config, ctx, account, cache=30, SearchTerm=words, IncludeItemTypes="Audio", Limit=30, **scope),
            )
            albums = [self._album(entry) for entry in found[0].get("Items") or []]
            artists = []
            for entry in found[1].get("Items") or []:
                art, thumb = self._cover(entry.get("Id") if (entry.get("ImageTags") or {}).get("Primary") else None)
                artists.append(Artist(id=str(entry.get("Id") or ""), name=str(entry.get("Name") or "?"), art=art, thumb=thumb))
            tracks = [self._track(entry) for entry in found[2].get("Items") or []]
            return Shelf(albums=albums, artists=artists, tracks=tracks, total=len(albums) + len(artists) + len(tracks))
        if view == "shuffle":
            payload = await self._items(config, ctx, account, cache=0, IncludeItemTypes="Audio", SortBy="Random", Limit=SHUFFLE_SIZE,
                                        EnableTotalRecordCount="false", **scope)
            tracks = [self._track(entry) for entry in payload.get("Items") or []]
            return Shelf(tracks=tracks, total=len(tracks))
        if view == "mix":
            item_id = path_segment(query.id, "The item")
            payload = await self._get(config, ctx, f"/Items/{item_id}/InstantMix", cache=0,
                                      params={"UserId": account, "Limit": SHUFFLE_SIZE}) or {}
            tracks = [self._track(entry) for entry in payload.get("Items") or []]
            return Shelf(tracks=tracks, total=len(tracks))
        raise AdapterError("The card asked for something the player does not show.", code="no_such_view")

    async def music_source(self, config: dict[str, Any], options: dict[str, Any], sound: SoundRequest, ctx: Context) -> Sound:
        """``/Audio/{id}/universal`` decides by itself: the file as it is when the
        browser plays its container and the bitrate fits, converted otherwise.

        Measured on 10.11.11: the file comes with Content-Length and answers
        Range with 206 through this route too; converted sound is chunked MP3
        without Range, or an HLS playlist when HLS is asked for.
        """
        account = await self._listener(config, options, ctx)
        track = path_segment(sound.track_id, "The track")
        limit = QUALITY_KBPS.get(sound.quality)
        session = secrets.token_hex(8)
        params: dict[str, Any] = {
            "UserId": account, "DeviceId": DEVICE_ID, "PlaySessionId": session,
            "Container": containers_for(sound.formats),
            "MaxStreamingBitrate": limit * 1000 if limit else 140_000_000,
            "AudioBitRate": (limit or 320) * 1000,
        }
        if sound.hls:
            params.update({"TranscodingContainer": "ts", "TranscodingProtocol": "hls", "AudioCodec": "aac"})
        else:
            params.update({"TranscodingContainer": "mp3", "TranscodingProtocol": "http", "AudioCodec": "mp3"})
            if sound.start > 0:
                params["StartTimeTicks"] = int(sound.start * TICKS_PER_SECOND)
        return Sound(
            source=MediaSource(url=f"{base_url(config)}/Audio/{track}/universal", headers=self._headers(config),
                               params=params, cache_seconds=0),
            converted=limit is not None, session=session,
        )

    async def music_hls_part(self, config: dict[str, Any], options: dict[str, Any], track_id: str, part: str,
                             query: dict[str, str], ctx: Context) -> MediaSource:
        """A playlist or segment the HLS playlist names, relative to the track.

        ⚠️ The addresses in Jellyfin's playlists are relative and carry no key
        (measured: a segment asked for without one answers 401), so the
        browser can follow them through nexdeck unchanged. The router has
        already held ``part`` to the three shapes Jellyfin writes.
        """
        track = path_segment(track_id, "The track")
        kept = {name: value for name, value in query.items() if name.lower() not in ("api_key", "apikey")}
        return MediaSource(url=f"{base_url(config)}/Audio/{track}/{part}", headers=self._headers(config), params=kept, cache_seconds=0)

    async def music_stop(self, config: dict[str, Any], sound: Sound, ctx: Context) -> None:
        await ctx.request(
            "DELETE", f"{base_url(config)}/Videos/ActiveEncodings", headers=self._headers(config),
            params={"DeviceId": DEVICE_ID, "PlaySessionId": sound.session}, verify=not config.get("insecure"), timeout=5.0,
        )

    # -- music: playlists ----------------------------------------------------------

    async def _write(self, config: dict[str, Any], ctx: Context, method: str, path: str,
                     params: dict[str, Any] | None = None, body: Any = None) -> Any:
        response = await ctx.request(method, f"{base_url(config)}{path}", headers=self._headers(config), params=params,
                                     json_body=body, verify=not config.get("insecure"), timeout=20.0)
        if response.status_code >= 400:
            raise AdapterError(f"{self.label} refused the change to the playlist with HTTP {response.status_code}.", code="playlist_refused")
        return response.json() if response.content and "json" in response.headers.get("content-type", "") else None

    async def _entries(self, config: dict[str, Any], ctx: Context, account: str, playlist_id: str) -> list[dict[str, Any]]:
        payload = await self._get(config, ctx, f"/Playlists/{playlist_id}/Items", cache=0, params={"UserId": account, "Limit": PLAYLIST_LIMIT}) or {}
        return payload.get("Items") or []

    async def music_playlist_create(self, config: dict[str, Any], options: dict[str, Any], name: str,
                                    track_ids: list[str], ctx: Context) -> Playlist:
        """Query parameters rather than a JSON body: the form Emby knows too, and measured to work on Jellyfin 10.11.11."""
        account = await self._listener(config, options, ctx)
        first, *rest = batches([path_segment(one, "The track") for one in track_ids]) or [[]]
        made = await self._write(config, ctx, "POST", "/Playlists", params={"Name": name, "Ids": ",".join(first), "UserId": account, "MediaType": "Audio"})
        playlist_id = str((made or {}).get("Id") or "")
        if not playlist_id:
            raise AdapterError(f"{self.label} did not say which playlist it made.", code="playlist_refused")
        for batch in rest:
            await self._write(config, ctx, "POST", f"/Playlists/{playlist_id}/Items", params={"Ids": ",".join(batch), "UserId": account})
        return Playlist(id=playlist_id, title=name, tracks=len(track_ids))

    async def music_playlist_add(self, config: dict[str, Any], options: dict[str, Any], playlist_id: str,
                                 track_ids: list[str], ctx: Context) -> None:
        """⚠️ Leaves out what is already there. Measured on 10.11.11: Jellyfin
        adds a track a second time when asked, Plex does not, and a button that
        does two different things on two servers is a button nobody trusts."""
        account = await self._listener(config, options, ctx)
        playlist = path_segment(playlist_id, "The playlist")
        present = {str(entry.get("Id")) for entry in await self._entries(config, ctx, account, playlist)}
        wanted = list(dict.fromkeys(path_segment(one, "The track") for one in track_ids if one not in present))
        for batch in batches(wanted):
            await self._write(config, ctx, "POST", f"/Playlists/{playlist}/Items", params={"Ids": ",".join(batch), "UserId": account})

    async def music_playlist_remove(self, config: dict[str, Any], options: dict[str, Any], playlist_id: str,
                                    entries: list[str], ctx: Context) -> None:
        playlist = path_segment(playlist_id, "The playlist")
        for batch in batches([path_segment(one, "The entry") for one in entries]):
            await self._write(config, ctx, "DELETE", f"/Playlists/{playlist}/Items", params={"EntryIds": ",".join(batch)})

    async def music_playlist_rename(self, config: dict[str, Any], options: dict[str, Any], playlist_id: str,
                                    name: str, ctx: Context) -> None:
        """⚠️ Through the item, not ``POST /Playlists/{id}``. Measured on 10.11.11:
        the playlist route answers an API key with 400 "Error processing
        request.", whatever the body; the item route takes the whole item back
        with the new name."""
        account = await self._listener(config, options, ctx)
        playlist = path_segment(playlist_id, "The playlist")
        item = await self._get(config, ctx, f"/Users/{account}/Items/{playlist}", cache=0) or {}
        if item.get("Type") != "Playlist":
            raise AdapterError("That is not a playlist.", code="not_a_playlist")
        await self._write(config, ctx, "POST", f"/Items/{playlist}", body={**item, "Name": name})

    async def music_playlist_delete(self, config: dict[str, Any], options: dict[str, Any], playlist_id: str,
                                    ctx: Context) -> None:
        account = await self._listener(config, options, ctx)
        playlist = path_segment(playlist_id, "The playlist")
        # ⚠️ Asked first: the same address deletes any item, an album or a film included.
        item = await self._get(config, ctx, f"/Users/{account}/Items/{playlist}", cache=0) or {}
        if item.get("Type") != "Playlist":
            raise AdapterError("That is not a playlist.", code="not_a_playlist")
        await self._write(config, ctx, "DELETE", f"/Items/{playlist}")

    async def choices(self, field: str, config: dict[str, Any], ctx: Context) -> list[tuple[str, str]]:
        if field == "account":
            users = await self._get(config, ctx, "/Users", cache=60) or []
            return [(str(user.get("Id")), str(user.get("Name") or "?")) for user in users if not (user.get("Policy") or {}).get("IsDisabled")]
        if field == "music_library":
            account = await self._listener(config, {}, ctx)
            views = (await self._get(config, ctx, f"/Users/{account}/Views", cache=60) or {}).get("Items") or []
            return [(str(view.get("Id")), str(view.get("Name") or "?")) for view in views if view.get("CollectionType") == "music"]
        return await super().choices(field, config, ctx)

    def demo_choices(self, field: str) -> list[tuple[str, str]]:
        if field == "account":
            return [("demo-alex", "Alex"), ("demo-sam", "Sam")]
        if field == "music_library":
            return [("demo-music", "Music")]
        return super().demo_choices(field)

    # -- demo --------------------------------------------------------------------------

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        if widget_kind == "recent":
            titles = [("The Quiet Harbour", "2026", "movie"), ("Harbour Lights", "S03E04 · Landfall", "episode"), ("Orbital", "2025", "movie"), ("Northern Sky", "Aurora Fields", "album"), ("Tide Lines", "S01E01 · Pilot", "episode"), ("Glass Bridge", "2026", "movie")]
            wanted = KINDS.get(str(options.get("kind") or "all"), KINDS["all"])
            allowed = {"movie": "Movie", "episode": "Episode", "album": "MusicAlbum"}
            items = [{"title": title, "subtitle": subtitle, "art": "", "kind": kind} for title, subtitle, kind in titles if allowed[kind] in wanted]
            return WidgetData(items=items[: int(options.get("limit") or 8)], meta={"empty": "Nothing new"})
        if widget_kind == "findings":
            return WidgetData(status="warn", items=[
                {"title": self.label, "subtitle": "A restart is pending", "status": "warn"},
                {"title": "Clean transcode directory", "subtitle": "The last run failed · error 13 (Access denied)", "status": "warn"},
                {"title": "Shows", "subtitle": "Shows is being scanned · 40%", "status": "unknown"},
            ], meta={"status_reason": "0 error finding(s), 2 warning(s)", "empty": f"{self.label} answers · 10.11.0 · 3 libraries"})
        if widget_kind == "users":
            return WidgetData(items=[
                {"title": "Alex", "subtitle": "6 play(s) · Living room TV, iPhone", "status": "ok", "value": "6"},
                {"title": "Sam", "subtitle": "2 play(s) · Bedroom TV", "status": "ok", "value": "2"},
                {"title": "Kim", "subtitle": "no activity", "status": "unknown", "value": ""},
            ], secondary=[{"label": "Accounts", "value": 3}, {"label": "Active", "value": 2}, {"label": "Devices", "value": 3}], metrics={"active": 2.0}, meta={"empty": "No accounts"})
        if widget_kind == "top":
            rows = [("Harbour Lights", 14, "episode"), ("The Quiet Harbour", 5, "movie"), ("Northern Sky", 4, "track"), ("Orbital", 2, "movie")]
            return WidgetData(items=[{"title": title, "subtitle": f"{count} play(s)", "art": "", "kind": kind} for title, count, kind in rows[: int(options.get("limit") or 6)]], meta={"empty": "Nothing watched"})
        if widget_kind == "player":
            return demo_player(self.music_features, options, tick)
        return super().demo(widget_kind, options, tick)


ADAPTER = JellyfinAdapter()
