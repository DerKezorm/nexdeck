"""qBittorrent Web API v2."""

from __future__ import annotations

from typing import Any

import httpx

from .base import AdapterError, AuthFailed, Context, Field, Unreachable, base_url
from .downloads_base import DownloadAdapter, QueueItem, Snapshot

ACTIVE_STATES = {"downloading", "metaDL", "forcedDL", "stalledDL", "queuedDL", "checkingDL", "pausedDL", "stoppedDL"}


class QbittorrentAdapter(DownloadAdapter):
    kind = "qbittorrent"
    label = "qBittorrent"
    description = "Torrents, speed and pause or resume."
    icon = "qbittorrent"
    docs_url = "https://github.com/qbittorrent/qBittorrent/wiki/WebUI-API-(qBittorrent-4.1)"
    #: Seen against a live qBittorrent 5.1 (05.09.2026).
    beta = False
    has_upload = True
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://qbittorrent:8080"),
        Field("username", "User name", default="admin"),
        Field("password", "Password", type="password", secret=True, required=True),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )

    def _client(self, config: dict[str, Any], ctx: Context) -> httpx.AsyncClient:
        client = ctx.cache.get("qb_client")
        if client is None or client.is_closed:
            client = httpx.AsyncClient(base_url=base_url(config), verify=not config.get("insecure"), timeout=15)
            ctx.cache["qb_client"] = client
        return client

    async def _login(self, config: dict[str, Any], ctx: Context) -> None:
        """Sign in, and understand both answers qBittorrent gives.

        ⚠️ Version 5 changed the reply. Version 4 answers ``200`` with the body
        ``Ok.`` and ``200`` with ``Fails.``; version 5 answers ``204`` with no
        body at all, and ``401``. Measured against 5.1.2: reading the old
        answer only, the connection test fails while every card works, because
        the session cookie arrives with that 204 either way.
        """
        client = self._client(config, ctx)
        try:
            response = await client.post(
                "/api/v2/auth/login",
                data={"username": config.get("username") or "admin", "password": config.get("password") or ""},
                headers={"Referer": base_url(config)},
            )
        except httpx.HTTPError as error:
            raise Unreachable(f"qBittorrent could not be reached: {error.__class__.__name__}.") from error
        if response.status_code in (401, 403):
            raise AuthFailed("qBittorrent rejected the user name or password.")
        if response.status_code >= 400:
            raise AdapterError(f"qBittorrent answered with HTTP {response.status_code} on the sign-in.", code="http_error")
        body = response.text.strip()
        if body and body != "Ok.":
            raise AuthFailed("qBittorrent rejected the user name or password.")

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, params: dict[str, Any] | None = None, retry: bool = True) -> Any:
        client = self._client(config, ctx)
        try:
            response = await client.get(path, params=params)
        except httpx.HTTPError as error:
            raise Unreachable(f"qBittorrent could not be reached: {error.__class__.__name__}.") from error
        if response.status_code == 403 and retry:
            await self._login(config, ctx)
            return await self._get(config, ctx, path, params, retry=False)
        if response.status_code >= 400:
            raise AdapterError(f"qBittorrent answered with HTTP {response.status_code}.", code="http_error")
        return response.json()

    async def _post(self, config: dict[str, Any], ctx: Context, path: str, data: dict[str, Any]) -> None:
        client = self._client(config, ctx)
        response = await client.post(path, data=data)
        if response.status_code == 403:
            await self._login(config, ctx)
            response = await client.post(path, data=data)
        if response.status_code >= 400:
            raise AdapterError(f"qBittorrent answered with HTTP {response.status_code}.", code="http_error")

    async def snapshot(self, config: dict[str, Any], ctx: Context) -> Snapshot:
        info = await self._get(config, ctx, "/api/v2/transfer/info")
        torrents = await self._get(config, ctx, "/api/v2/torrents/info", params={"filter": "downloading"})
        items = []
        remaining = 0.0
        for torrent in torrents:
            size = float(torrent.get("size") or 0)
            progress = float(torrent.get("progress") or 0) * 100
            remaining += size * (1 - progress / 100)
            state = str(torrent.get("state", ""))
            items.append(QueueItem(
                name=torrent.get("name", "?"), progress=progress, size_bytes=size,
                eta_seconds=float(torrent["eta"]) if torrent.get("eta") not in (None, 8640000) else None,
                state="paused" if state in ("pausedDL", "stoppedDL") else ("stalled" if state == "stalledDL" else "downloading"),
                identifier=torrent.get("hash", ""),
            ))
        paused = bool(items) and all(i.state == "paused" for i in items)
        return Snapshot(
            download_bps=float(info.get("dl_info_speed") or 0),
            upload_bps=float(info.get("up_info_speed") or 0),
            paused=paused,
            remaining_bytes=remaining,
            items=items,
            total=len(items),
        )

    async def pause(self, config: dict[str, Any], ctx: Context) -> None:
        await self._post(config, ctx, "/api/v2/torrents/stop", {"hashes": "all"})

    async def resume(self, config: dict[str, Any], ctx: Context) -> None:
        await self._post(config, ctx, "/api/v2/torrents/start", {"hashes": "all"})


ADAPTER = QbittorrentAdapter()
