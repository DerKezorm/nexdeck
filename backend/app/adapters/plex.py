"""Plex Media Server."""

from __future__ import annotations

from typing import Any

from .base import Context, Field, WidgetData, WidgetType, base_url
from .media_base import MediaAdapter, Stream

#: Which Plex library types a "recently added" widget draws from.
KINDS = {"all": ("movie", "show", "artist"), "movies": ("movie",), "series": ("show",), "music": ("artist",)}


class PlexAdapter(MediaAdapter):
    kind = "plex"
    label = "Plex"
    description = "Active streams, library size and what was added last, with covers."
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
    )
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

    def _headers(self, config: dict[str, Any]) -> dict[str, str]:
        return {"Accept": "application/json", "X-Plex-Token": str(config.get("token") or ""), "X-Plex-Client-Identifier": "nexdeck"}

    def image_headers(self, config: dict[str, Any]) -> dict[str, str]:
        return {"X-Plex-Token": str(config.get("token") or ""), "X-Plex-Client-Identifier": "nexdeck"}

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "recent":
            return await self._recent(config, options, ctx)
        return await super().fetch(widget_kind, config, options, ctx)

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        if widget_kind == "recent":
            titles = [("The Quiet Harbour", "2026", "movie"), ("Harbour Lights", "Season 3", "season"), ("Orbital", "2025", "movie"), ("Aurora Fields", "Northern Sky", "album"), ("Tide Lines", "Season 1", "season"), ("Glass Bridge", "2026", "movie")]
            wanted = KINDS.get(str(options.get("kind") or "all"), KINDS["all"])
            allowed = {"movie": "movie", "season": "show", "album": "artist"}
            items = [{"title": title, "subtitle": subtitle, "art": "", "kind": kind} for title, subtitle, kind in titles if allowed[kind] in wanted]
            return WidgetData(items=items[: int(options.get("limit") or 8)], meta={"empty": "Nothing new"})
        return super().demo(widget_kind, options, tick)

    async def _recent(self, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        """The newest items of the chosen library types, one poster each."""
        wanted = KINDS.get(str(options.get("kind") or "all"), KINDS["all"])
        limit = max(1, min(40, int(options.get("limit") or 8)))
        sections = await self._get(config, ctx, "/library/sections", cache=600)
        items: list[dict[str, Any]] = []
        for section in (sections.get("MediaContainer") or {}).get("Directory") or []:
            if section.get("type") not in wanted or not section.get("key"):
                continue
            payload = await ctx.get_json(
                f"{base_url(config)}/library/sections/{section['key']}/recentlyAdded",
                headers={**self._headers(config), "X-Plex-Container-Start": "0", "X-Plex-Container-Size": str(limit)},
                params={"X-Plex-Container-Start": 0, "X-Plex-Container-Size": limit},
                verify=not config.get("insecure"), cache_seconds=120,
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

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, cache: float = 5) -> Any:
        return await ctx.get_json(f"{base_url(config)}{path}", headers=self._headers(config), verify=not config.get("insecure"), cache_seconds=cache)

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        identity = await self._get(config, ctx, "/", cache=0)
        container = identity.get("MediaContainer", {})
        return f"Plex {container.get('version', '?')} on {container.get('friendlyName', '?')}."

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
            payload = await ctx.get_json(
                f"{base_url(config)}/library/sections/{key}/all",
                headers={**self._headers(config), "X-Plex-Container-Size": "0", "X-Plex-Container-Start": "0"},
                params={"X-Plex-Container-Size": 0}, verify=not config.get("insecure"), cache_seconds=600,
            )
            total = int((payload.get("MediaContainer") or {}).get("totalSize") or 0)
            label = {"movie": "Movies", "show": "Series", "artist": "Artists", "photo": "Photos"}.get(section.get("type"), section.get("title", "Items"))
            counts[label] = counts.get(label, 0) + total
        return counts


ADAPTER = PlexAdapter()
