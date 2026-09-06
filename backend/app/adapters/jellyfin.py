"""Jellyfin, and by inheritance Emby: streams, library, recent covers, findings, users and the period's top."""

from __future__ import annotations

import time
from collections import Counter, defaultdict
from datetime import UTC, datetime
from typing import Any

from .base import AdapterError, Context, Field, WidgetData, WidgetType, base_url, human_bytes
from .media_base import MediaAdapter, Stream

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


class JellyfinAdapter(MediaAdapter):
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
    )

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
        return super().demo(widget_kind, options, tick)


ADAPTER = JellyfinAdapter()
