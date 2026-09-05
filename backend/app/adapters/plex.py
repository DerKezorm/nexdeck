"""Plex Media Server: streams, library, recent covers, findings, load, users and the week's top."""

from __future__ import annotations

import time
from collections import Counter, defaultdict
from typing import Any

from .base import Context, Field, WidgetData, WidgetType, base_url, status_from_percent
from .media_base import MediaAdapter, Stream

#: Which Plex library types a "recently added" widget draws from.
KINDS = {"all": ("movie", "show", "artist"), "movies": ("movie",), "series": ("show",), "music": ("artist",)}
HISTORY_PAGE = 500
HISTORY_LIMIT = 5000


def device_names(ids: set[int], devices: dict[int, str]) -> str:
    """Two Apple TVs are two devices: the same name once, with how many there are."""
    names = Counter(devices.get(device_id, f"Device {device_id}") for device_id in ids)
    return ", ".join(f"{name} ×{count}" if count > 1 else name for name, count in sorted(names.items()))


class PlexAdapter(MediaAdapter):
    kind = "plex"
    #: Confirmed against a live instance on 2026-09-05.
    beta = False
    label = "Plex"
    description = "Active streams, library size and what was added last, with covers."
    icon = "plex"
    docs_url = "https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://plex:32400"),
        Field(
            "token", "Plex token", type="password", secret=True, required=True, helper="plex-signin",
            help="Filled in by the sign-in below. By hand: in Plex Web open any item, choose Get Info, then View XML, and copy the value after X-Plex-Token=. The server owner's token sees every stream; a shared user's only their own.",
        ),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
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
            description="Does the server run, and what needs a look: updates, remote access, scans, load.",
            renderer="list",
            default_size=(3, 2),
            refresh_seconds=60,
            options=(Field("scan_days", "Scan age (days)", type="number", default=7, help="Warn when a library was last scanned longer ago than this."),),
        ),
        WidgetType(
            kind="load",
            label="Server load",
            description="CPU and memory of the Plex process and of its host, with history.",
            renderer="stats",
            default_size=(3, 2),
            refresh_seconds=15,
            metrics=("plex_cpu", "plex_memory", "host_cpu", "host_memory"),
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
        return {"Accept": "application/json", "X-Plex-Token": str(config.get("token") or ""), "X-Plex-Client-Identifier": "nexdeck"}

    def image_headers(self, config: dict[str, Any]) -> dict[str, str]:
        return {"X-Plex-Token": str(config.get("token") or ""), "X-Plex-Client-Identifier": "nexdeck"}

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, cache: float = 5, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> Any:
        return await ctx.get_json(
            f"{base_url(config)}{path}", headers={**self._headers(config), **(headers or {})}, params=params,
            verify=not config.get("insecure"), cache_seconds=cache,
        )

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        identity = await self._get(config, ctx, "/", cache=0)
        container = identity.get("MediaContainer", {})
        return f"Plex {container.get('version', '?')} on {container.get('friendlyName', '?')}."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "recent":
            return await self._recent(config, options, ctx)
        if widget_kind == "findings":
            return await self._findings(config, options, ctx)
        if widget_kind == "load":
            return await self._load(config, ctx)
        if widget_kind == "users":
            return await self._users(config, options, ctx)
        if widget_kind == "top":
            return await self._top(config, options, ctx)
        return await super().fetch(widget_kind, config, options, ctx)

    # -- streams and library (the shared media shape) ----------------------------

    async def sessions(self, config: dict[str, Any], ctx: Context) -> list[Stream]:
        payload = await self._get(config, ctx, "/status/sessions")
        streams = []
        for item in (payload.get("MediaContainer") or {}).get("Metadata") or []:
            duration = float(item.get("duration") or 0)
            offset = float(item.get("viewOffset") or 0)
            progress = 100.0 * offset / duration if duration else 0.0
            title = item.get("title", "?")
            if item.get("type") == "episode":
                title = f"{item.get('grandparentTitle', '?')} S{int(item.get('parentIndex') or 0):02d}E{int(item.get('index') or 0):02d}"
            player = item.get("Player") or {}
            media = (item.get("Media") or [{}])[0]
            transcode = item.get("TranscodeSession") or {}
            transcoding = bool(transcode) and transcode.get("videoDecision") == "transcode"
            quality = media.get("videoResolution", "")
            quality = f"{quality}p" if quality and quality.isdigit() else quality.upper()
            subtitle = " · ".join(p for p in [(item.get("User") or {}).get("title", ""), player.get("title", ""), quality, "Transcode" if transcoding else "Direct play"] if p)
            art = item.get("thumb") or item.get("grandparentThumb") or ""
            streams.append(Stream(
                title=title, subtitle=subtitle, user=(item.get("User") or {}).get("title", ""), progress=progress,
                remaining_seconds=(duration - offset) / 1000 if duration else None,
                paused=player.get("state") == "paused", transcoding=transcoding,
                art=f"proxy:{art}" if art else "",
            ))
        return streams

    async def counts(self, config: dict[str, Any], ctx: Context) -> dict[str, int]:
        sections = await self._get(config, ctx, "/library/sections", cache=600)
        counts: dict[str, int] = {}
        for section in (sections.get("MediaContainer") or {}).get("Directory") or []:
            key = section.get("key")
            if not key:
                continue
            payload = await self._get(
                config, ctx, f"/library/sections/{key}/all", cache=600,
                headers={"X-Plex-Container-Size": "0", "X-Plex-Container-Start": "0"}, params={"X-Plex-Container-Size": 0},
            )
            total = int((payload.get("MediaContainer") or {}).get("totalSize") or 0)
            label = {"movie": "Movies", "show": "Series", "artist": "Artists", "photo": "Photos"}.get(section.get("type"), section.get("title", "Items"))
            counts[label] = counts.get(label, 0) + total
        return counts

    # -- recently added ----------------------------------------------------------

    async def _recent(self, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        """The newest items of the chosen library types, one poster each."""
        wanted = KINDS.get(str(options.get("kind") or "all"), KINDS["all"])
        limit = max(1, min(40, int(options.get("limit") or 8)))
        sections = await self._get(config, ctx, "/library/sections", cache=600)
        items: list[dict[str, Any]] = []
        for section in (sections.get("MediaContainer") or {}).get("Directory") or []:
            if section.get("type") not in wanted or not section.get("key"):
                continue
            payload = await self._get(
                config, ctx, f"/library/sections/{section['key']}/recentlyAdded", cache=120,
                headers={"X-Plex-Container-Start": "0", "X-Plex-Container-Size": str(limit)}, params={"X-Plex-Container-Start": 0, "X-Plex-Container-Size": limit},
            )
            for entry in (payload.get("MediaContainer") or {}).get("Metadata") or []:
                items.append(self._poster(entry))
        items.sort(key=lambda item: item.get("added_at") or 0, reverse=True)
        return WidgetData(items=items[:limit], meta={"empty": "Nothing new"})

    @staticmethod
    def _poster(entry: dict[str, Any]) -> dict[str, Any]:
        kind = str(entry.get("type") or "")
        title = str(entry.get("title") or "?")
        subtitle = str(entry.get("year") or "")
        art = entry.get("thumb") or ""
        if kind == "season":
            title, subtitle = str(entry.get("parentTitle") or title), title
            art = entry.get("thumb") or entry.get("parentThumb") or ""
        elif kind == "episode":
            title, subtitle = str(entry.get("grandparentTitle") or title), f"S{int(entry.get('parentIndex') or 0):02d}E{int(entry.get('index') or 0):02d} · {title}"
            art = entry.get("grandparentThumb") or entry.get("thumb") or ""
        elif kind == "album":
            subtitle = str(entry.get("parentTitle") or subtitle)
        elif kind == "track":
            title, subtitle = str(entry.get("parentTitle") or title), str(entry.get("grandparentTitle") or "")
            art = entry.get("parentThumb") or entry.get("thumb") or ""
        return {"title": title, "subtitle": subtitle, "art": f"proxy:{art}" if art else "", "kind": kind, "added_at": int(entry.get("addedAt") or 0)}

    # -- findings ------------------------------------------------------------------

    async def _resources(self, config: dict[str, Any], ctx: Context) -> dict[str, Any]:
        """The latest of the six-second samples Plex keeps of its own and the host's load."""
        payload = await self._get(config, ctx, "/statistics/resources", cache=10, params={"timespan": 6})
        samples = (payload.get("MediaContainer") or {}).get("StatisticsResources") or []
        return max(samples, key=lambda s: s.get("at") or 0) if samples else {}

    async def _findings(self, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        """What an operator would want to know about the server itself, one row per finding."""
        identity = (await self._get(config, ctx, "/", cache=60)).get("MediaContainer") or {}
        sections = ((await self._get(config, ctx, "/library/sections", cache=120)).get("MediaContainer") or {}).get("Directory") or []
        updater = (await self._get(config, ctx, "/updater/status", cache=600)).get("MediaContainer") or {}
        account = (await self._get(config, ctx, "/myplex/account", cache=300)).get("MyPlex") or {}
        activities = ((await self._get(config, ctx, "/activities", cache=10)).get("MediaContainer") or {}).get("Activity") or []
        resources = await self._resources(config, ctx)
        scan_days = max(1, int(options.get("scan_days") or 7))
        now = time.time()
        items: list[dict[str, Any]] = []
        for release in updater.get("Release") or []:
            items.append({"title": "Plex Media Server", "subtitle": f"Update {release.get('version', '?')} available", "status": "unknown"})
        if account:
            if account.get("signInState") not in (None, "", "ok"):
                items.append({"title": "plex.tv", "subtitle": "Not signed in to plex.tv", "status": "warn"})
            elif account.get("mappingState") not in (None, "", "mapped", "unknown") or account.get("mappingError"):
                items.append({"title": "plex.tv", "subtitle": f"Remote access is not working · {account.get('mappingError') or account.get('mappingState')}", "status": "bad"})
        for activity in activities:
            progress = activity.get("progress")
            label = str(activity.get("title") or activity.get("type") or "Activity")
            items.append({"title": label, "subtitle": f"{activity.get('subtitle') or 'running'}" + (f" · {int(progress)}%" if isinstance(progress, (int, float)) else ""), "status": "unknown"})
        for section in sections:
            name = str(section.get("title") or "Library")
            if section.get("refreshing"):
                items.append({"title": name, "subtitle": f"{name} is being scanned", "status": "unknown"})
                continue
            scanned = float(section.get("scannedAt") or 0)
            if scanned and now - scanned > scan_days * 86400:
                items.append({"title": name, "subtitle": f"{name} last scanned {int((now - scanned) // 86400)} days ago", "status": "warn"})
        process_cpu = resources.get("processCpuUtilization")
        host_cpu = resources.get("hostCpuUtilization")
        if isinstance(process_cpu, (int, float)) and process_cpu >= 80:
            items.append({"title": "Plex Media Server", "subtitle": f"Plex uses {process_cpu:.0f}% CPU", "status": "warn"})
        if isinstance(host_cpu, (int, float)) and host_cpu >= 90:
            items.append({"title": "Host", "subtitle": f"The host is at {host_cpu:.0f}% CPU", "status": "warn"})
        transcodes = int(identity.get("transcoderActiveVideoSessions") or 0)
        if transcodes >= 3:
            items.append({"title": "Transcoder", "subtitle": f"{transcodes} video transcodes running", "status": "unknown"})
        order = {"bad": 0, "warn": 1, "unknown": 2}
        items.sort(key=lambda item: order.get(str(item["status"]), 3))
        bad = sum(1 for item in items if item["status"] == "bad")
        warn = sum(1 for item in items if item["status"] == "warn")
        meta: dict[str, Any] = {"empty": f"Plex answers · {identity.get('version', '?')} · {len(sections)} libraries"}
        if bad or warn:
            meta["status_reason"] = f"{bad} error finding(s), {warn} warning(s)"
        return WidgetData(status="bad" if bad else ("warn" if warn else "ok"), items=items, meta=meta)

    # -- server load -----------------------------------------------------------------

    async def _load(self, config: dict[str, Any], ctx: Context) -> WidgetData:
        sample = await self._resources(config, ctx)
        plex_cpu = round(float(sample.get("processCpuUtilization") or 0), 1)
        plex_memory = round(float(sample.get("processMemoryUtilization") or 0), 1)
        host_cpu = round(float(sample.get("hostCpuUtilization") or 0), 1)
        host_memory = round(float(sample.get("hostMemoryUtilization") or 0), 1)
        return WidgetData(
            status=status_from_percent(max(host_cpu, host_memory)),
            primary={"label": "Plex CPU", "value": plex_cpu, "unit": "%"},
            secondary=[
                {"label": "Plex RAM", "value": plex_memory, "unit": "%", "metric": "plex_memory"},
                {"label": "Host CPU", "value": host_cpu, "unit": "%", "metric": "host_cpu"},
                {"label": "Host RAM", "value": host_memory, "unit": "%", "metric": "host_memory"},
            ],
            metrics={"plex_cpu": plex_cpu, "plex_memory": plex_memory, "host_cpu": host_cpu, "host_memory": host_memory},
        )

    # -- history: users, devices, top ------------------------------------------------

    async def _history(self, config: dict[str, Any], ctx: Context, days: int) -> list[dict[str, Any]]:
        """Every play of the period. Plex hands out one page per call, so this walks the pages."""
        since = int(time.time()) - days * 86400
        rows: list[dict[str, Any]] = []
        start = 0
        while True:
            payload = await self._get(
                config, ctx, "/status/sessions/history/all", cache=120,
                headers={"X-Plex-Container-Start": str(start), "X-Plex-Container-Size": str(HISTORY_PAGE)},
                params={"sort": "viewedAt:desc", "viewedAt>": since, "X-Plex-Container-Start": start, "X-Plex-Container-Size": HISTORY_PAGE},
            )
            container = payload.get("MediaContainer") or {}
            page = container.get("Metadata") or []
            rows.extend(entry for entry in page if int(entry.get("viewedAt") or 0) >= since)
            start += len(page)
            if not page or start >= int(container.get("totalSize") or 0) or start >= HISTORY_LIMIT:
                break
        return rows

    async def _users(self, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        days = max(1, int(options.get("days") or 1))
        accounts = ((await self._get(config, ctx, "/accounts", cache=600)).get("MediaContainer") or {}).get("Account") or []
        devices = {int(d.get("id") or 0): str(d.get("name") or d.get("platform") or "?") for d in ((await self._get(config, ctx, "/devices", cache=600)).get("MediaContainer") or {}).get("Device") or []}
        history = await self._history(config, ctx, days)
        plays: Counter[int] = Counter()
        used: dict[int, set[int]] = defaultdict(set)
        for entry in history:
            account_id = int(entry.get("accountID") or 0)
            plays[account_id] += 1
            device_id = int(entry.get("deviceID") or 0)
            if device_id:
                used[account_id].add(device_id)
        # Plex keeps empty account slots (managed users that never were, shared users
        # that left); only named accounts are people. A nameless one that did play
        # something still gets a row, so the count of plays adds up.
        named = [account for account in accounts if str(account.get("name") or "").strip()]
        known = {int(account.get("id") or 0) for account in named}
        for account_id in sorted(plays):
            if account_id not in known:
                named.append({"id": account_id, "name": f"Account {account_id}"})
        items: list[dict[str, Any]] = []
        for account in named:
            account_id = int(account.get("id") or 0)
            count = plays.get(account_id, 0)
            items.append({
                "title": str(account.get("name") or "?"),
                "subtitle": (f"{count} play(s)" + (f" · {device_names(used[account_id], devices)}" if used.get(account_id) else "")) if count else "no activity",
                "status": "ok" if count else "unknown",
                "value": str(count) if count else "",
                "plays": count,
            })
        items.sort(key=lambda item: (-int(item["plays"]), str(item["title"]).lower()))
        for item in items:
            item.pop("plays", None)
        active = sum(1 for item in items if item["status"] == "ok")
        used_devices = {device for names in used.values() for device in names}
        return WidgetData(
            items=items,
            secondary=[{"label": "Accounts", "value": len(named)}, {"label": "Active", "value": active}, {"label": "Devices", "value": len(used_devices)}],
            metrics={"active": float(active)},
            meta={"empty": "No accounts"},
        )

    async def _top(self, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        days = 30 if str(options.get("days") or "7") == "30" else 7
        limit = max(1, min(40, int(options.get("limit") or 6)))
        history = await self._history(config, ctx, days)
        plays: Counter[str] = Counter()
        posters: dict[str, dict[str, Any]] = {}
        for entry in history:
            kind = str(entry.get("type") or "")
            if kind in ("episode", "track"):
                title = str(entry.get("grandparentTitle") or entry.get("title") or "?")
                art = entry.get("grandparentThumb") or entry.get("parentThumb") or entry.get("thumb") or ""
            else:
                title = str(entry.get("title") or "?")
                art = entry.get("thumb") or ""
            plays[title] += 1
            posters.setdefault(title, {"title": title, "art": f"proxy:{art}" if art else "", "kind": kind})
        items = []
        for title, count in plays.most_common(limit):
            items.append({**posters[title], "subtitle": f"{count} play(s)"})
        return WidgetData(items=items, meta={"empty": "Nothing watched"})

    # -- demo --------------------------------------------------------------------------

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        if widget_kind == "recent":
            titles = [("The Quiet Harbour", "2026", "movie"), ("Harbour Lights", "Season 3", "season"), ("Orbital", "2025", "movie"), ("Aurora Fields", "Northern Sky", "album"), ("Tide Lines", "Season 1", "season"), ("Glass Bridge", "2026", "movie")]
            wanted = KINDS.get(str(options.get("kind") or "all"), KINDS["all"])
            allowed = {"movie": "movie", "season": "show", "album": "artist"}
            items = [{"title": title, "subtitle": subtitle, "art": "", "kind": kind} for title, subtitle, kind in titles if allowed[kind] in wanted]
            return WidgetData(items=items[: int(options.get("limit") or 8)], meta={"empty": "Nothing new"})
        if widget_kind == "findings":
            return WidgetData(status="warn", items=[
                {"title": "Music", "subtitle": "Music last scanned 12 days ago", "status": "warn"},
                {"title": "Plex Media Server", "subtitle": "Update 1.42.1 available", "status": "unknown"},
            ], meta={"status_reason": "0 error finding(s), 1 warning(s)", "empty": "Plex answers · 1.42.0 · 3 libraries"})
        if widget_kind == "load":
            from . import demo as fake

            plex_cpu = fake.walk("plex-cpu", tick, 2, 35)
            host_cpu = fake.walk("plex-host-cpu", tick, 10, 60)
            return WidgetData(
                status="ok",
                primary={"label": "Plex CPU", "value": plex_cpu, "unit": "%"},
                secondary=[{"label": "Plex RAM", "value": 4.2, "unit": "%", "metric": "plex_memory"}, {"label": "Host CPU", "value": host_cpu, "unit": "%", "metric": "host_cpu"}, {"label": "Host RAM", "value": 61.3, "unit": "%", "metric": "host_memory"}],
                metrics={"plex_cpu": plex_cpu, "plex_memory": 4.2, "host_cpu": host_cpu, "host_memory": 61.3},
            )
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


ADAPTER = PlexAdapter()
