"""NZBGet over JSON-RPC."""

from __future__ import annotations

from typing import Any

from .base import AdapterError, Context, Field, base_url
from .downloads_base import DownloadAdapter, QueueItem, Snapshot


class NzbgetAdapter(DownloadAdapter):
    kind = "nzbget"
    label = "NZBGet"
    description = "Queue, speed and pause or resume over JSON-RPC."
    icon = "nzbget"
    docs_url = "https://nzbget.com/documentation/api/"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://nzbget:6789"),
        Field("username", "User name", default="nzbget"),
        Field("password", "Password", type="password", secret=True, required=True),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )

    async def _rpc(self, config: dict[str, Any], ctx: Context, method: str, params: list[Any] | None = None) -> Any:
        response = await ctx.request(
            "POST", f"{base_url(config)}/jsonrpc",
            json_body={"method": method, "params": params or [], "id": 1},
            auth=(str(config.get("username") or "nzbget"), str(config.get("password") or "")),
            verify=not config.get("insecure"),
        )
        if response.status_code >= 400:
            raise AdapterError(f"NZBGet answered with HTTP {response.status_code}.", code="http_error")
        payload = response.json()
        if payload.get("error"):
            raise AdapterError(str(payload["error"].get("message", "NZBGet refused the request.")), code="rpc_error")
        return payload.get("result")

    async def snapshot(self, config: dict[str, Any], ctx: Context) -> Snapshot:
        status = await self._rpc(config, ctx, "status")
        groups = await self._rpc(config, ctx, "listgroups", [0])
        items = []
        for group in groups or []:
            size = float(group.get("FileSizeMB") or 0) * 1024 * 1024
            remaining = float(group.get("RemainingSizeMB") or 0) * 1024 * 1024
            progress = 100.0 * (size - remaining) / size if size else 0.0
            rate = float(status.get("DownloadRate") or 0)
            items.append(QueueItem(
                name=group.get("NZBName", "?"), progress=progress, size_bytes=size,
                eta_seconds=(remaining / rate) if rate else None,
                state="paused" if status.get("DownloadPaused") else str(group.get("Status", "downloading")).lower(),
                identifier=str(group.get("NZBID", "")),
            ))
        return Snapshot(
            download_bps=float(status.get("DownloadRate") or 0),
            paused=bool(status.get("DownloadPaused")),
            remaining_bytes=float(status.get("RemainingSizeMB") or 0) * 1024 * 1024,
            items=items,
            total=len(items),
            free_bytes=float(status.get("FreeDiskSpaceMB") or 0) * 1024 * 1024 or None,
        )

    async def pause(self, config: dict[str, Any], ctx: Context) -> None:
        await self._rpc(config, ctx, "pausedownload")

    async def resume(self, config: dict[str, Any], ctx: Context) -> None:
        await self._rpc(config, ctx, "resumedownload")


ADAPTER = NzbgetAdapter()
