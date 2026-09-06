"""Deluge web JSON API."""

from __future__ import annotations

from typing import Any

import httpx

from .base import AdapterError, AuthFailed, Context, Field, Unreachable, base_url
from .downloads_base import DownloadAdapter, QueueItem, Snapshot

TORRENT_FIELDS = ["name", "progress", "download_payload_rate", "eta", "state", "total_size", "total_remaining"]


class DelugeAdapter(DownloadAdapter):
    kind = "deluge"
    label = "Deluge"
    description = "Torrents, speed and pause or resume through the web UI API."
    icon = "deluge"
    #: Seen against a live Deluge 2.1 (06.09.2026).
    beta = False
    docs_url = "https://deluge.readthedocs.io/en/latest/reference/api.html"
    has_upload = True
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://deluge:8112"),
        Field("password", "Web UI password", type="password", secret=True, required=True),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )

    def _client(self, config: dict[str, Any], ctx: Context) -> httpx.AsyncClient:
        client = ctx.cache.get("deluge_client")
        if client is None or client.is_closed:
            client = httpx.AsyncClient(base_url=base_url(config), verify=not config.get("insecure"), timeout=15)
            ctx.cache["deluge_client"] = client
        return client

    async def _call(self, config: dict[str, Any], ctx: Context, method: str, params: list[Any] | None = None, retry: bool = True) -> Any:
        client = self._client(config, ctx)
        try:
            response = await client.post("/json", json={"method": method, "params": params or [], "id": 1})
        except httpx.HTTPError as error:
            raise Unreachable(f"Deluge could not be reached: {error.__class__.__name__}.") from error
        if response.status_code >= 400:
            raise AdapterError(f"Deluge answered with HTTP {response.status_code}.", code="http_error")
        payload = response.json()
        error = payload.get("error")
        if error and retry and int(error.get("code", 0)) == 1:
            login = await client.post("/json", json={"method": "auth.login", "params": [config.get("password") or ""], "id": 2})
            if not login.json().get("result"):
                raise AuthFailed("Deluge rejected the password.")
            return await self._call(config, ctx, method, params, retry=False)
        if error:
            raise AdapterError(str(error.get("message") or "Deluge refused the request."), code="rpc_error")
        return payload.get("result")

    async def snapshot(self, config: dict[str, Any], ctx: Context) -> Snapshot:
        result = await self._call(config, ctx, "web.update_ui", [TORRENT_FIELDS, {}])
        torrents = (result or {}).get("torrents") or {}
        stats = (result or {}).get("stats") or {}
        items = []
        remaining = 0.0
        for hash_id, torrent in torrents.items():
            state = str(torrent.get("state", "")).lower()
            if state == "seeding":
                continue
            remaining += float(torrent.get("total_remaining") or 0)
            items.append(QueueItem(
                name=torrent.get("name", "?"), progress=float(torrent.get("progress") or 0),
                size_bytes=float(torrent.get("total_size") or 0),
                eta_seconds=float(torrent["eta"]) if torrent.get("eta") else None,
                state="paused" if state == "paused" else ("queued" if state == "queued" else ("error" if state == "error" else "downloading")),
                identifier=hash_id,
            ))
        paused = bool(items) and all(i.state == "paused" for i in items)
        # Deluge answers -1 when it cannot read the free space; passed on as it
        # comes, the card reads "-1 B". Seen against 2.1 in a container.
        free = float(stats.get("free_space") or 0)
        return Snapshot(
            download_bps=float(stats.get("download_rate") or 0),
            upload_bps=float(stats.get("upload_rate") or 0),
            paused=paused,
            remaining_bytes=remaining,
            items=items,
            total=len(items),
            free_bytes=free if free > 0 else None,
        )

    async def pause(self, config: dict[str, Any], ctx: Context) -> None:
        await self._call(config, ctx, "core.pause_session")

    async def resume(self, config: dict[str, Any], ctx: Context) -> None:
        await self._call(config, ctx, "core.resume_session")


ADAPTER = DelugeAdapter()
