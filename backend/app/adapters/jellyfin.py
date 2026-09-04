"""Jellyfin, and by inheritance Emby."""

from __future__ import annotations

from typing import Any

from .base import Context, Field, base_url
from .media_base import MediaAdapter, Stream

TICKS_PER_SECOND = 10_000_000


class JellyfinAdapter(MediaAdapter):
    kind = "jellyfin"
    label = "Jellyfin"
    description = "Active streams and library counts."
    icon = "jellyfin"
    docs_url = "https://api.jellyfin.org/"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://jellyfin:8096"),
        Field("api_key", "API key", type="password", secret=True, required=True, help="Dashboard > API Keys"),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    token_header = "Authorization"

    def _headers(self, config: dict[str, Any]) -> dict[str, str]:
        token = str(config.get("api_key") or "")
        if self.token_header == "Authorization":
            return {"Authorization": f'MediaBrowser Token="{token}", Client="nexdeck", Device="nexdeck", DeviceId="nexdeck", Version="1"'}
        return {self.token_header: token}

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, params: dict[str, Any] | None = None, cache: float = 5) -> Any:
        return await ctx.get_json(f"{base_url(config)}{path}", headers=self._headers(config), params=params, verify=not config.get("insecure"), cache_seconds=cache)

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        info = await self._get(config, ctx, "/System/Info", cache=0)
        return f"{self.label} {info.get('Version', '?')} on {info.get('ServerName', '?')}."

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
            art = f"{base_url(config)}/Items/{item.get('SeriesId') or item.get('Id')}/Images/Primary?maxWidth=120" if item.get("Id") else ""
            streams.append(Stream(
                title=title, subtitle=subtitle, user=session.get("UserName", ""), progress=progress,
                remaining_seconds=(duration - position) if duration else None,
                paused=bool((session.get("PlayState") or {}).get("IsPaused")), transcoding=transcoding, art=art,
            ))
        return streams

    async def counts(self, config: dict[str, Any], ctx: Context) -> dict[str, int]:
        payload = await self._get(config, ctx, "/Items/Counts", cache=600)
        return {
            "Movies": int(payload.get("MovieCount") or 0),
            "Series": int(payload.get("SeriesCount") or 0),
            "Episodes": int(payload.get("EpisodeCount") or 0),
        }


ADAPTER = JellyfinAdapter()
