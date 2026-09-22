"""nexcrate: the films, series and music of the nexapps family, read through its API.

nexcrate replaces Radarr, Sonarr and Lidarr and says so in its own API,
``/api/v1``, with a key that starts with ``nxc_`` and travels as a Bearer
token. A connection gets that key by pairing, the way nexbeat does: nexdeck
asks nexcrate for one, shows the code, and the owner confirms it in nexcrate
(``routers/nexcrate.py``). A key typed in by hand works the same.

What shapes the cards, read from nexcrate's API on 22.09.2026:

- There is no count of the library. The cards read ``/titles`` in pages
  once and then only what changed since (``after`` → ``next_after``), kept in
  the connection's memory, so a library of thousands costs one small request
  a minute after the first. An answer of 410 means the marker is older than
  nexcrate keeps changes, and the reading starts over.
- A title's state is the weightiest of its versions: problem, downloading,
  incomplete, upgrade, available, wanted, unmonitored.
- ``/titles/why`` says per title why it is not there yet, as a code with
  params, without asking any indexer. That is the card no Arr can offer.
- nexcrate serves no pictures to a key. Posters come from TMDB by the path
  nexcrate names, album covers from the Cover Art Archive, both through
  nexdeck's own image route so the browser never leaves the house.
- The buttons on a stuck download are the ones nexcrate itself lists in
  ``problem.actions``; they need a key with ``operate``.
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from .base import (
    Action,
    Adapter,
    AdapterError,
    AuthFailed,
    Context,
    Field,
    MediaSource,
    WidgetData,
    WidgetType,
    ago,
    base_url,
    human_bytes,
    ring_of,
)

API = "/api/v1"
#: The weightiest state first; a title shows the first its versions have.
PRECEDENCE = ("problem", "downloading", "incomplete", "upgrade", "available", "wanted", "unmonitored")
KINDS = {"movie": "Films", "series": "Series", "album": "Albums", "artist": "Artists"}
KIND_CHOICES = (("", "Everything"), ("movie", "Films"), ("series", "Series"), ("album", "Music"))
#: Where the whole library is kept between two readings, in the connection's memory.
TITLES = "nexcrate:titles"
#: The buttons a stuck download may carry, as nexcrate names them.
DOWNLOAD_ACTIONS = {
    "retry": Action(id="retry", label="Try again", icon="rotate-cw", confirm=True),
    "search": Action(id="search", label="Search again", icon="search", confirm=True),
    "remove": Action(id="remove", label="Remove and search again", icon="trash-2", confirm=True, danger=True),
    "clear": Action(id="clear", label="Clear", icon="x", confirm=True),
}
#: Why a title is not there yet, in words, by nexcrate's code.
BECAUSE = {
    "not_released": "Not released yet",
    "no_date": "No release date known",
    "not_found": "Nothing found at the last search",
    "no_fitting_release": "Only releases the profile refuses",
    "searching_soon": "Next search",
    "search_limit": "Search limit reached, next search",
    "waiting_delay": "Waiting out the delay",
    "held": "Held back",
    "version_not_ready": "The version is not set up",
    "wish_searching": "A search is running",
    "downloading": "Downloading",
    "problem": "Stuck",
    "artist_frozen": "The artist is frozen",
}
LEVEL = {"error": "bad", "warning": "warn", "notice": "ok"}
#: nexcrate's findings in words that can be translated, by code.
FINDINGS = {
    "indexer_none": "No indexer is set up",
    "indexer_failing": "An indexer fails",
    "download_client_none": "No download program is set up",
    "download_client_failing": "A download program fails",
    "tmdb_token_missing": "The TMDB key is missing",
    "folder_missing": "A library folder is missing",
    "folder_not_writable": "A library folder cannot be written to",
    "disk_full": "A disk is almost full",
    "version_not_ready": "A version is not set up",
}
AUTOMATIC_OFF = {
    "movie": "The automatic search for films is off",
    "series": "The automatic search for series is off",
    "album": "The automatic search for music is off",
}

REFUSALS = {
    "api_key_missing": "nexcrate wants a key. Pair this connection with nexcrate, or enter a key from nexcrate's settings.",
    "api_key_invalid": "nexcrate does not know this key, or it was revoked. Pair the connection again.",
}


def _stamp(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment.replace(tzinfo=moment.tzinfo or UTC).timestamp()


def _state(title: dict[str, Any]) -> str:
    states = {str(version.get("state") or "") for version in title.get("versions") or [] if isinstance(version, dict)}
    return next((state for state in PRECEDENCE if state in states), "unmonitored")


def _name(title: dict[str, Any]) -> str:
    name = str(title.get("name") or "?")
    year = title.get("year")
    return f"{name} ({year})" if year else name


def _until(value: Any) -> str:
    """How long until a moment, as short as ``ago`` says how long since one."""
    moment = _stamp(value)
    if moment is None:
        return ""
    seconds = moment - time.time()
    if seconds <= 60:
        return "now"
    if seconds < 3600:
        return f"in {round(seconds / 60)} min"
    if seconds < 86400:
        return f"in {round(seconds / 3600)} h"
    return f"in {round(seconds / 86400)} d"


def _eta(seconds: Any) -> str:
    if not isinstance(seconds, (int, float)) or seconds <= 0:
        return ""
    minutes = int(seconds // 60)
    return f"{minutes // 60} h {minutes % 60} min" if minutes >= 60 else f"{max(1, minutes)} min"


class NexcrateAdapter(Adapter):
    kind = "nexcrate"
    label = "nexcrate"
    category = "media"
    description = "Films, series and music from nexcrate: the library, the downloads, what is stuck, what comes next and why something is still missing."
    icon = "nexcrate"
    docs_url = "https://github.com/DerKezorm/nexcrate"
    #: Out of beta on 22.09.2026: every card run against a real nexcrate.
    beta = False
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://nexcrate:8390"),
        Field("api_key", "API key", type="password", secret=True, required=True, helper="nexcrate-pairing",
              help="Press “Pair with nexcrate” and confirm the code in nexcrate; the key arrives here by itself. "
                   "A key made by hand in nexcrate's settings works too. Reading is enough for every card; the buttons on a stuck download need “operate”."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(kind="library", label="Library", description="Films, series and music: what is there, what is wanted, what is on its way and what is stuck.",
                   renderer="value", default_size=(3, 2), refresh_seconds=120, ring=True, metrics=("available", "wanted"),
                   options=(Field("kind", "Show", type="select", default="", options=KIND_CHOICES),)),
        WidgetType(kind="queue", label="Downloads", description="What is loading, with progress and the time left.",
                   renderer="list", default_size=(4, 3), refresh_seconds=15, metrics=("queued",),
                   options=(Field("kind", "Show", type="select", default="", options=KIND_CHOICES), Field("limit", "Entries", type="number", default=8))),
        WidgetType(kind="problems", label="Stuck", description="Downloads that hang, those that need you first, with the buttons nexcrate offers for each.",
                   renderer="list", default_size=(4, 3), refresh_seconds=60, metrics=("problems",),
                   options=(Field("limit", "Entries", type="number", default=8),)),
        WidgetType(kind="calendar", label="Coming up", description="What is released in the next days, and whether it is already there.",
                   renderer="calendar", default_size=(3, 3), refresh_seconds=1800,
                   options=(Field("days", "Days ahead", type="number", default=14), Field("kind", "Show", type="select", default="", options=KIND_CHOICES),
                            Field("missing", "Only what is still missing", type="bool", default=False))),
        WidgetType(kind="arrivals", label="Just arrived", description="The latest imports, as posters and covers.",
                   renderer="posters", default_size=(4, 3), refresh_seconds=300,
                   options=(Field("limit", "Entries", type="number", default=12),)),
        WidgetType(kind="why", label="Why is it missing?", description="Wanted titles and the reason nexcrate gives for each, without asking any indexer: not released yet, only refused releases, the next search.",
                   renderer="list", default_size=(4, 3), refresh_seconds=900,
                   options=(Field("kind", "Show", type="select", default="", options=KIND_CHOICES), Field("limit", "Entries", type="number", default=8))),
        WidgetType(kind="storage", label="Storage", description="Free space on every volume nexcrate files into.",
                   renderer="list", bars=True, default_size=(3, 2), refresh_seconds=600),
        WidgetType(kind="findings", label="Findings", description="What nexcrate itself reports: indexers, download programs, TMDB, folders, disks.",
                   renderer="list", default_size=(3, 2), refresh_seconds=300, metrics=("findings",)),
    )

    def default_link(self, config: dict[str, Any]) -> str:
        return base_url(config)

    # -- asking nexcrate --------------------------------------------------------

    async def _call(self, config: dict[str, Any], ctx: Context, method: str, path: str, *,
                    params: dict[str, Any] | None = None, body: Any = None, cache: float = 0, timeout: float = 20) -> Any:
        response = await ctx.request(
            method, f"{base_url(config)}{API}{path}", params=params, json_body=body,
            headers={"Authorization": f"Bearer {str(config.get('api_key') or '').strip()}"},
            verify=not config.get("insecure"), cache_seconds=cache, auth_errors=False, timeout=timeout,
        )
        try:
            payload = response.json() if response.content else None
        except ValueError as failure:
            raise AdapterError("This address answers, but not the way nexcrate does.", code="not_nexcrate",
                               hint="The URL is nexcrate's own address, without /api.") from failure
        if response.status_code == 401:
            code = str((payload or {}).get("code") or "")
            raise AuthFailed(REFUSALS.get(code, "nexcrate refused the key."))
        if response.status_code == 403 and isinstance(payload, dict) and payload.get("code") == "scope_missing":
            scope = str((payload.get("params") or {}).get("scope") or "")
            raise AdapterError(f"This key may not {scope or 'do that'}. Pair the connection again and allow “{scope}”.",
                               code="nexcrate_scope", hint="Reading needs “read”, the buttons on a stuck download “operate”.")
        if response.status_code >= 400:
            message = (payload or {}).get("message") if isinstance(payload, dict) else None
            code = (payload or {}).get("code") if isinstance(payload, dict) else None
            raise AdapterError(str(message or f"nexcrate answered with HTTP {response.status_code}."), code=str(code or "http_error"))
        return payload

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        system = await self._call(config, ctx, "GET", "/system") or {}
        scopes = ", ".join(system.get("scopes") or []) or "?"
        update = system.get("update") or {}
        later = f" nexcrate {update['latest']} is out." if update.get("available") and update.get("latest") else ""
        return f"nexcrate {system.get('version', '?')} answers; this key may {scopes}.{later}"

    async def _titles(self, config: dict[str, Any], ctx: Context) -> dict[str, dict[str, Any]]:
        """The whole library, read once and then only what changed since."""
        # One reading at a time per connection: the library card and the "why"
        # card start together, and the first reading of a large library is
        # the expensive one. The second waits and finds it done.
        async with ctx.cache.setdefault("nexcrate:titles_lock", asyncio.Lock()):
            return await self._read_titles(config, ctx)

    async def _read_titles(self, config: dict[str, Any], ctx: Context) -> dict[str, dict[str, Any]]:
        kept = ctx.cache.get(TITLES) or {"after": 0, "items": {}}
        items: dict[str, dict[str, Any]] = kept["items"]
        after = kept["after"]
        for _page in range(200):
            try:
                answer = await self._call(config, ctx, "GET", "/titles", params={"after": after, "limit": 2000}, timeout=45) or {}
            except AdapterError as failure:
                if after and failure.code == "marker_too_old":
                    # Older than nexcrate keeps its changes: read it all again.
                    items, after = {}, 0
                    continue
                raise
            for title in answer.get("items") or []:
                items[f"{title.get('kind')}:{title.get('ref')}"] = title
            for gone in answer.get("removed") or []:
                items.pop(f"{gone.get('kind')}:{gone.get('ref')}", None)
            after = answer.get("next_after") or after
            # Kept after every page: a first read of a large library may take
            # longer than one round is allowed, and the next one goes on from here.
            ctx.cache[TITLES] = {"after": after, "items": items}
            if not answer.get("more"):
                break
        return items

    # -- the cards ----------------------------------------------------------------

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        kind = str(options.get("kind") or "")
        limit = max(1, min(30, int(options.get("limit") or 8)))
        if widget_kind == "library":
            titles = await self._titles(config, ctx)
            health = await self._call(config, ctx, "GET", "/health", cache=30) or {}
            return self._library(list(titles.values()), kind, health.get("items") or [])
        if widget_kind == "queue":
            answer = await self._call(config, ctx, "GET", "/queue", params={"kind": kind} if kind else None, cache=5) or {}
            return self._queue(answer.get("items") or [], limit)
        if widget_kind == "problems":
            answer = await self._call(config, ctx, "GET", "/problems", cache=5) or {}
            return self._problems(answer.get("items") or [], limit)
        if widget_kind == "calendar":
            days = max(1, min(100, int(options.get("days") or 14)))
            today = datetime.now(UTC).date()
            params: dict[str, Any] = {"from": today.isoformat(), "to": (today + timedelta(days=days)).isoformat()}
            if kind:
                params["kind"] = kind
            if options.get("missing"):
                params["missing"] = "true"
            # ⚠️ 45 s, not 20. Measured on 22.09.2026 against a library of several thousand
            # titles: 18 s for the first answer while the library card read
            # alongside, 2 s for the next. Twenty cut the first one off.
            answer = await self._call(config, ctx, "GET", "/calendar", params=params, cache=300, timeout=45) or {}
            return self._calendar(answer.get("items") or [])
        if widget_kind == "arrivals":
            return await self._arrivals(config, ctx, limit)
        if widget_kind == "why":
            titles = await self._titles(config, ctx)
            missing = [t for t in titles.values() if _state(t) == "wanted" and (not kind or t.get("kind") == kind)]
            wanted = sorted(missing, key=lambda t: -int(t.get("seq") or 0))[:limit]
            if not wanted:
                return WidgetData(items=[], meta={"empty": "Nothing is missing."})
            answer = await self._call(config, ctx, "POST", "/titles/why",
                                      body={"items": [{"kind": t["kind"], "ref": t["ref"]} for t in wanted]}) or {}
            return self._why(wanted, answer.get("items") or [], len(missing))
        if widget_kind == "storage":
            answer = await self._call(config, ctx, "GET", "/storage", cache=60) or {}
            return self._storage(answer.get("items") or [])
        if widget_kind == "findings":
            answer = await self._call(config, ctx, "GET", "/health", cache=30) or {}
            return self._findings(answer.get("items") or [])
        raise KeyError(widget_kind)

    @staticmethod
    def _library(titles: list[dict[str, Any]], kind: str, findings: list[dict[str, Any]]) -> WidgetData:
        shown = [t for t in titles if t.get("kind") != "artist" and (not kind or t.get("kind") == kind)]
        count = {state: 0 for state in PRECEDENCE}
        by_kind: dict[str, int] = {}
        for title in shown:
            state = _state(title)
            count[state] += 1
            # By kind only what is there, so the chips add up to the number
            # above them: a discography holds thousands of albums nobody wants.
            if state in ("available", "upgrade"):
                by_kind[str(title.get("kind"))] = by_kind.get(str(title.get("kind")), 0) + 1
        there = count["available"] + count["upgrade"]
        on_the_way = count["downloading"] + count["incomplete"]
        worst = "bad" if any(f.get("level") == "error" for f in findings) or count["problem"] else ("warn" if any(f.get("level") == "warning" for f in findings) else "ok")
        rows = [{"label": KINDS[k], "value": by_kind[k]} for k in ("movie", "series", "album") if by_kind.get(k)] if not kind else []
        rows += [{"label": "Wanted", "value": count["wanted"]}, {"label": "On its way", "value": on_the_way}, {"label": "Stuck", "value": count["problem"]}]
        return WidgetData(
            status=worst,
            primary={"label": "In the library", "value": there},
            secondary=rows,
            metrics={"available": float(there), "wanted": float(count["wanted"])},
            meta={"ring": ring_of(("There", there), ("Wanted", count["wanted"]), ("On its way", on_the_way), ("Stuck", count["problem"])),
                  "status_reason": str((findings[0] or {}).get("message") or "") if findings and worst != "ok" else ""},
        )

    @staticmethod
    def _queue(items: list[dict[str, Any]], limit: int) -> WidgetData:
        rows = []
        for item in items:
            if not isinstance(item, dict) or item.get("state") in ("failed",) or item.get("problem"):
                continue
            title = item.get("title") or {}
            episodes = (item.get("series") or {}).get("episodes") or []
            place = f" S{episodes[0]['season']:02d}E{episodes[0]['episode']:02d}" if episodes and isinstance(episodes[0], dict) else ""
            state = str(item.get("state") or "")
            progress = item.get("progress") if isinstance(item.get("progress"), (int, float)) else None
            words = {"queued": "Queued", "paused": "Paused", "completed": "Done", "importing": "Importing"}.get(state, "")
            left = _eta(item.get("remaining_seconds"))
            rows.append({
                "title": f"{title.get('name') or item.get('release') or '?'}{place}",
                "subtitle": " · ".join(part for part in (words, str(item.get("quality") or ""), left) if part),
                "progress": progress,
                "value": f"{progress:.0f}%" if progress is not None else "",
                "status": "ok" if state in ("downloading", "completed", "importing") else "warn",
            })
        return WidgetData(status="ok", items=rows[:limit], secondary=[{"label": "In the queue", "value": len(rows)}],
                          metrics={"queued": float(len(rows))}, meta={"empty": "Nothing is loading."})

    @staticmethod
    def _problems(items: list[dict[str, Any]], limit: int) -> WidgetData:
        rows = []
        for item in items:
            problem = item.get("problem") if isinstance(item, dict) else None
            if not isinstance(problem, dict):
                continue
            title = item.get("title") or {}
            offered = [DOWNLOAD_ACTIONS[name].model_copy(update={"params": {"download_id": item.get("download_id")}})
                       for name in problem.get("actions") or [] if name in DOWNLOAD_ACTIONS]
            rows.append({
                "title": str(title.get("name") or item.get("release") or "?"),
                "subtitle": str(problem.get("message") or problem.get("code") or ""),
                "status": "bad" if problem.get("needs_owner") else "warn",
                "value": "Needs you" if problem.get("needs_owner") else "",
                "actions": offered,
            })
        # What needs the owner first; that is what this card is for.
        rows.sort(key=lambda row: row["status"] != "bad")
        needs = sum(1 for row in rows if row["status"] == "bad")
        return WidgetData(status="bad" if needs else ("warn" if rows else "ok"), items=rows[:limit],
                          secondary=[{"label": "Stuck", "value": len(rows)}, {"label": "Needs you", "value": needs}],
                          metrics={"problems": float(len(rows))}, meta={"empty": "Nothing is stuck."})

    @staticmethod
    def _calendar(items: list[dict[str, Any]]) -> WidgetData:
        words = {"theatrical": "In cinemas", "digital": "Digital release", "physical": "Disc release", "air": "Airs", "release": "Released"}
        rows = []
        for item in items:
            if not isinstance(item, dict) or not item.get("date"):
                continue
            there = any(v.get("state") in ("available", "upgrade") for v in item.get("versions") or [] if isinstance(v, dict))
            name = str(item.get("name") or "?")
            episode = item.get("series") or {}
            if episode.get("season") is not None and episode.get("episode") is not None:
                name = f"{name} S{int(episode['season']):02d}E{int(episode['episode']):02d}"
            artists = ", ".join(a.get("name", "") for a in (item.get("album") or {}).get("artists") or [] if isinstance(a, dict))
            rows.append({
                "date": str(item["date"])[:10],
                "title": f"{artists} · {name}" if artists else name,
                "subtitle": words.get(str(item.get("date_kind") or ""), ""),
                "status": "ok" if there else "warn",
            })
        rows.sort(key=lambda row: row["date"])
        return WidgetData(items=rows, secondary=[{"label": "Coming up", "value": len(rows)}])

    async def _arrivals(self, config: dict[str, Any], ctx: Context, limit: int) -> WidgetData:
        first = await self._call(config, ctx, "GET", "/events", params={"after": 0, "limit": 1}, cache=30) or {}
        latest = int(first.get("latest") or 0)
        answer = await self._call(config, ctx, "GET", "/events", params={"after": max(0, latest - 1000), "limit": 1000}, cache=30) or {}
        seen: dict[str, dict[str, Any]] = {}
        for event in reversed(answer.get("items") or []):
            if not isinstance(event, dict) or event.get("type") != "download.imported" or not isinstance(event.get("title"), dict):
                continue
            key = f"{event['title'].get('kind')}:{event['title'].get('ref')}"
            seen.setdefault(key, event)
            if len(seen) >= limit:
                break
        if not seen:
            return WidgetData(items=[], meta={"empty": "Nothing arrived lately."})
        looked = await self._call(config, ctx, "POST", "/titles/lookup",
                                  body={"items": [{"kind": e["title"]["kind"], "ref": e["title"]["ref"]} for e in seen.values()]}) or {}
        pictures = {}
        for entry in looked.get("items") or []:
            title = entry.get("title") if isinstance(entry.get("title"), dict) else entry
            if isinstance(title, dict):
                pictures[f"{title.get('kind')}:{title.get('ref')}"] = self._art(title)
        items = [{
            "title": str(event["title"].get("name") or "?"),
            "subtitle": ago(_stamp(event.get("at"))),
            "art": pictures.get(key, ""),
            "kind": {"movie": "movie", "series": "show", "album": "album"}.get(str(event["title"].get("kind")), ""),
        } for key, event in seen.items()]
        return WidgetData(items=items, meta={"style": "posters"})

    @staticmethod
    def _art(title: dict[str, Any]) -> str:
        poster = str(title.get("poster_path") or "")
        if poster.startswith("/"):
            return f"proxy:/tmdb/w342{poster}"
        cover = str((title.get("album") or {}).get("cover_url") or "")
        prefix = "https://coverartarchive.org/"
        return f"proxy:/caa/{cover[len(prefix):]}" if cover.startswith(prefix) else ""

    @staticmethod
    def _why(wanted: list[dict[str, Any]], answers: list[dict[str, Any]], total: int) -> WidgetData:
        rows = []
        for title, answer in zip(wanted, answers, strict=False):
            why = (answer or {}).get("why") or {}
            versions = why.get("versions") or []
            because = (versions[0].get("because") if versions and isinstance(versions[0], dict) else None) or {}
            code = str(because.get("code") or "")
            params = because.get("params") or {}
            value = ""
            if code == "not_released":
                value = str(params.get("date") or "")
            elif code in ("searching_soon", "search_limit"):
                value = _until(params.get("next_at"))
            elif code == "waiting_delay":
                value = _until(params.get("until"))
            elif code == "not_found":
                value = ago(_stamp(params.get("at")))
            elif code == "no_fitting_release":
                value = f"{params.get('releases', 0)} found"
            rows.append({
                "title": _name(title),
                "subtitle": BECAUSE.get(code, code.replace("_", " ").capitalize() or "Unknown"),
                "value": value,
                "status": "warn" if code in ("no_fitting_release", "not_found", "version_not_ready", "problem") else "ok",
            })
        return WidgetData(status="ok", items=rows, secondary=[{"label": "Wanted", "value": total}], meta={"empty": "Nothing is missing."})

    @staticmethod
    def _storage(items: list[dict[str, Any]]) -> WidgetData:
        volumes: dict[str, dict[str, Any]] = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            volume = str(item.get("volume") or item.get("version_id") or "?")
            entry = volumes.setdefault(volume, {"kinds": set(), **item})
            entry["kinds"].add(KINDS.get(str(item.get("kind")), str(item.get("kind") or "")))
        rows = []
        worst = "ok"
        for item in volumes.values():
            total, free = item.get("total_bytes"), item.get("free_bytes")
            if item.get("problem"):
                rows.append({"title": " · ".join(sorted(item["kinds"])), "worded": True, "subtitle": str(item["problem"]).replace("_", " "), "status": "bad", "value": ""})
                worst = "bad"
                continue
            if not isinstance(total, (int, float)) or not isinstance(free, (int, float)) or total <= 0:
                continue
            used = round(100 * (total - free) / total, 1)
            status = "bad" if free < 1024 ** 3 else ("warn" if used >= 90 else "ok")
            worst = status if status == "bad" or (status == "warn" and worst == "ok") else worst
            rows.append({
                "title": " · ".join(sorted(item["kinds"])),
                "worded": True,
                "subtitle": f"{human_bytes(free)} free of {human_bytes(total)}",
                "value": used,
                "unit": "%",
                "progress": used,
                "status": status,
            })
        return WidgetData(status=worst, items=rows, meta={"empty": "No folder is set up."})

    @staticmethod
    def _findings(items: list[dict[str, Any]]) -> WidgetData:
        # Built from the code, not taken from nexcrate's sentence: that one is
        # English and carries names, and no table translates it. The name goes
        # beneath, as it stands.
        rows = []
        for item in items:
            if not isinstance(item, dict):
                continue
            code, params = str(item.get("code") or ""), item.get("params") or {}
            title = FINDINGS.get(code) or (AUTOMATIC_OFF.get(str(params.get("kind")), "") if code == "automatic_off" else "")
            detail = str(params.get("name") or "")
            if code in ("indexer_failing", "download_client_failing") and params.get("error"):
                detail = f"{detail}: {params['error']}" if detail else str(params["error"])
            if code == "disk_full" and isinstance(params.get("free_bytes"), (int, float)):
                detail = f"{detail} · {human_bytes(params['free_bytes'])} free".strip(" ·")
            rows.append({"title": title or str(item.get("message") or code or "?"), "worded": bool(title), "subtitle": detail,
                         "status": LEVEL.get(str(item.get("level")), "warn")})
        worst = "bad" if any(r["status"] == "bad" for r in rows) else ("warn" if any(r["status"] == "warn" for r in rows) else "ok")
        return WidgetData(status=worst, items=rows, secondary=[{"label": "Findings", "value": len(rows)}],
                          metrics={"findings": float(len(rows))}, meta={"empty": "nexcrate reports nothing."})

    async def action(self, widget_kind: str, action_id: str, params: dict[str, Any], config: dict[str, Any],
                     options: dict[str, Any], ctx: Context) -> str:
        if widget_kind != "problems" or action_id not in DOWNLOAD_ACTIONS:
            return await super().action(widget_kind, action_id, params, config, options, ctx)
        download = str(params.get("download_id") or "").strip()
        if not download:
            raise AdapterError("This button names no download.", code="missing_download")
        body = {"search_again": True} if action_id == "remove" else None
        await self._call(config, ctx, "POST", f"/downloads/{download}/{action_id}", body=body)
        ctx.forget_answers()
        return {"retry": "Tried again.", "search": "Searching again.", "remove": "Removed; searching again.", "clear": "Cleared."}[action_id]

    async def image_source(self, config: dict[str, Any], path: str, ctx: Context) -> MediaSource:
        """Posters from TMDB and covers from the Cover Art Archive; nexcrate hands out none to a key."""
        if path.startswith("/tmdb/"):
            return MediaSource(url=f"https://image.tmdb.org/t/p/{path[len('/tmdb/'):]}", cache_seconds=86400)
        if path.startswith("/caa/"):
            return MediaSource(url=f"https://coverartarchive.org/{path[len('/caa/'):]}", cache_seconds=86400)
        raise AdapterError("nexcrate hands out no pictures of its own.", code="no_image")

    # -- demo ----------------------------------------------------------------------------

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        now = time.time()
        iso = lambda seconds: datetime.fromtimestamp(now + seconds, UTC).isoformat()  # noqa: E731
        if widget_kind == "library":
            titles = ([{"kind": "movie", "versions": [{"state": "available"}]}] * 412 + [{"kind": "movie", "versions": [{"state": "wanted"}]}] * 23
                      + [{"kind": "series", "versions": [{"state": "available"}]}] * 87 + [{"kind": "series", "versions": [{"state": "downloading"}]}] * 3
                      + [{"kind": "album", "versions": [{"state": "available"}]}] * 640 + [{"kind": "album", "versions": [{"state": "problem"}]}] * (1 + (tick // 600) % 2))
            return self._library(titles, str(options.get("kind") or ""), [])
        if widget_kind == "queue":
            step = tick % 100
            return self._queue([
                {"title": {"name": "Dune: Part Two"}, "state": "downloading", "progress": min(99, 35 + step / 2), "quality": "Bluray-2160p", "remaining_seconds": 1500 - step * 10},
                {"title": {"name": "Severance"}, "series": {"episodes": [{"season": 2, "episode": 7}]}, "state": "downloading", "progress": min(99, 71 + step / 4), "quality": "WEBDL-1080p", "remaining_seconds": 240},
                {"title": {"name": "Big Thief · Double Infinity"}, "state": "queued", "progress": 0, "quality": "FLAC"},
            ], int(options.get("limit") or 8))
        if widget_kind == "problems":
            return self._problems([
                {"download_id": "d_1", "title": {"name": "The Bear"}, "problem": {"code": "import_mapping", "needs_owner": True, "message": "Which episode is this file? The name fits two.", "actions": ["search", "remove"]}},
                {"download_id": "d_2", "title": {"name": "Arrival"}, "problem": {"code": "stalled", "needs_owner": False, "message": "No progress for 40 minutes.", "actions": ["retry", "remove"]}},
            ], int(options.get("limit") or 8))
        if widget_kind == "calendar":
            day = lambda n: (datetime.now(UTC).date() + timedelta(days=n)).isoformat()  # noqa: E731
            return self._calendar([
                {"name": "Andor", "date": day(1), "date_kind": "air", "series": {"season": 2, "episode": 9}, "versions": [{"state": "wanted"}]},
                {"name": "Mickey 17", "date": day(3), "date_kind": "digital", "versions": [{"state": "wanted"}]},
                {"name": "Double Infinity", "date": day(6), "date_kind": "release", "album": {"artists": [{"name": "Big Thief"}]}, "versions": [{"state": "wanted"}]},
                {"name": "Conclave", "date": day(9), "date_kind": "physical", "versions": [{"state": "available"}]},
            ])
        if widget_kind == "arrivals":
            names = ["Anora", "Flow", "The Brutalist", "Shōgun", "Nosferatu", "Conclave"]
            return WidgetData(items=[{"title": name, "subtitle": ago(now - 3600 * (index + 1) * 5), "art": "", "kind": "movie"} for index, name in enumerate(names)],
                              meta={"style": "posters"})
        if widget_kind == "why":
            wanted = [{"kind": "movie", "name": name, "year": year} for name, year in (("Mickey 17", 2025), ("Sinners", 2025), ("Eddington", 2025), ("The Running Man", 2025))]
            answers = [{"why": {"versions": [{"because": because}]}} for because in (
                {"code": "not_released", "params": {"date": (datetime.now(UTC).date() + timedelta(days=3)).isoformat()}},
                {"code": "no_fitting_release", "params": {"releases": 14}},
                {"code": "searching_soon", "params": {"next_at": iso(2400)}},
                {"code": "waiting_delay", "params": {"until": iso(5400)}},
            )]
            return self._why(wanted, answers, 23)
        if widget_kind == "storage":
            free = 1.9e12 - (tick % 3600) * 1e7
            return self._storage([
                {"volume": "volume-1", "kind": "movie", "free_bytes": free, "total_bytes": 16e12},
                {"volume": "volume-1", "kind": "series", "free_bytes": free, "total_bytes": 16e12},
                {"volume": "volume-2", "kind": "album", "free_bytes": 3.1e12, "total_bytes": 4e12},
            ])
        if widget_kind == "findings":
            return self._findings([
                {"code": "indexer_failing", "level": "warning", "params": {"name": "Indexer A", "error": "timeout"}},
                {"code": "automatic_off", "level": "notice", "params": {"kind": "album"}},
            ])
        raise KeyError(widget_kind)


ADAPTER = NexcrateAdapter()
