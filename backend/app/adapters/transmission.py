"""Transmission RPC with its session-id handshake."""

from __future__ import annotations

from typing import Any

from .base import AdapterError, AuthFailed, Context, Field, base_url
from .downloads_base import DownloadAdapter, QueueItem, Snapshot

FIELDS = ["id", "name", "percentDone", "rateDownload", "eta", "status", "totalSize", "leftUntilDone"]


class TransmissionAdapter(DownloadAdapter):
    kind = "transmission"
    label = "Transmission"
    description = "Torrents, speed and pause or resume over RPC."
    icon = "transmission"
    docs_url = "https://github.com/transmission/transmission/blob/main/docs/rpc-spec.md"
    #: Seen against a live Transmission (linuxserver) (05.09.2026).
    beta = False
    has_upload = True
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://transmission:9091"),
        Field("username", "User name"),
        Field("password", "Password", type="password", secret=True),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )

    async def _rpc(self, config: dict[str, Any], ctx: Context, method: str, arguments: dict[str, Any] | None = None, retry: bool = True) -> Any:
        headers = {}
        session_id = ctx.cache.get("transmission_session")
        if session_id:
            headers["X-Transmission-Session-Id"] = session_id
        auth = None
        if config.get("username"):
            auth = (str(config["username"]), str(config.get("password") or ""))
        # ⚠️ Through ``ctx.request``, not the shared client. Posting straight
        # to the client walked past everything the context does around a call,
        # and the "Ignore TLS errors" box was one of those things: the field
        # was offered, saved and shown, and never read. A Transmission behind
        # a self-signed certificate was simply unreachable, with no hint that
        # the box the operator had ticked did nothing.
        response = await ctx.request(
            "POST",
            f"{base_url(config)}/transmission/rpc",
            json_body={"method": method, "arguments": arguments or {}},
            headers=headers, auth=auth, timeout=15,
            verify=not config.get("insecure"),
            auth_errors=False,
        )
        if response.status_code == 409 and retry:
            ctx.cache["transmission_session"] = response.headers.get("X-Transmission-Session-Id", "")
            return await self._rpc(config, ctx, method, arguments, retry=False)
        if response.status_code in (401, 403):
            raise AuthFailed("Transmission rejected the user name or password.")
        if response.status_code >= 400:
            raise AdapterError(f"Transmission answered with HTTP {response.status_code}.", code="http_error")
        payload = response.json()
        if payload.get("result") != "success":
            raise AdapterError(str(payload.get("result") or "Transmission refused the request."), code="rpc_error")
        return payload.get("arguments") or {}

    async def snapshot(self, config: dict[str, Any], ctx: Context) -> Snapshot:
        stats = await self._rpc(config, ctx, "session-stats")
        torrents = (await self._rpc(config, ctx, "torrent-get", {"fields": FIELDS})).get("torrents", [])
        items = []
        remaining = 0.0
        for torrent in torrents:
            status = int(torrent.get("status") or 0)
            if status == 6:  # seeding
                continue
            progress = float(torrent.get("percentDone") or 0) * 100
            remaining += float(torrent.get("leftUntilDone") or 0)
            items.append(QueueItem(
                name=torrent.get("name", "?"), progress=progress, size_bytes=float(torrent.get("totalSize") or 0),
                eta_seconds=float(torrent["eta"]) if torrent.get("eta", -1) and torrent.get("eta", -1) > 0 else None,
                state="paused" if status == 0 else ("queued" if status in (3, 5) else "downloading"),
                identifier=str(torrent.get("id", "")),
            ))
        paused = bool(items) and all(i.state == "paused" for i in items)
        return Snapshot(
            download_bps=float(stats.get("downloadSpeed") or 0),
            upload_bps=float(stats.get("uploadSpeed") or 0),
            paused=paused,
            remaining_bytes=remaining,
            items=items,
            total=len(items),
        )

    async def pause(self, config: dict[str, Any], ctx: Context) -> None:
        await self._rpc(config, ctx, "torrent-stop")

    async def resume(self, config: dict[str, Any], ctx: Context) -> None:
        await self._rpc(config, ctx, "torrent-start")


ADAPTER = TransmissionAdapter()
