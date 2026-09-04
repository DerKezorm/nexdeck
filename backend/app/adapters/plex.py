"""Plex Media Server."""

from __future__ import annotations

from typing import Any

from .base import Context, Field, base_url
from .media_base import MediaAdapter, Stream


class PlexAdapter(MediaAdapter):
    kind = "plex"
    label = "Plex"
    description = "Active streams and library size."
    icon = "plex"
    docs_url = "https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://plex:32400"),
        Field("token", "Plex token", type="password", secret=True, required=True),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )

    def _headers(self, config: dict[str, Any]) -> dict[str, str]:
        return {"Accept": "application/json", "X-Plex-Token": str(config.get("token") or ""), "X-Plex-Client-Identifier": "nexdeck"}

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
                art=f"{base_url(config)}{art}?X-Plex-Token={config.get('token')}" if art else "",
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
