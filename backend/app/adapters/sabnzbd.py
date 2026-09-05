"""SABnzbd: the usenet downloader."""

from __future__ import annotations

from typing import Any

from .base import AdapterError, Context, Field, base_url
from .downloads_base import DownloadAdapter, QueueItem, Snapshot


def _mb(value: Any) -> float:
    try:
        return float(str(value).replace(",", "")) * 1024 * 1024
    except (TypeError, ValueError):
        return 0.0


def _seconds(text: Any) -> float | None:
    """``"0:12:34"`` -> seconds."""
    try:
        parts = [int(p) for p in str(text).split(":")]
    except ValueError:
        return None
    total = 0
    for part in parts:
        total = total * 60 + part
    return float(total) or None


class SabnzbdAdapter(DownloadAdapter):
    kind = "sabnzbd"
    #: Confirmed against a live instance on 2026-09-05.
    beta = False
    label = "SABnzbd"
    description = "Queue, speed, remaining data and pause or resume."
    icon = "sabnzbd"
    docs_url = "https://sabnzbd.org/wiki/advanced/api"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://sabnzbd:8080"),
        Field("api_key", "API key", type="password", secret=True, required=True, help="Config > General > API Key"),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )

    async def _call(self, config: dict[str, Any], ctx: Context, mode: str, extra: dict[str, Any] | None = None, cache: float = 0) -> Any:
        params = {"mode": mode, "output": "json", "apikey": config.get("api_key", "")}
        params.update(extra or {})
        payload = await ctx.get_json(f"{base_url(config)}/api", params=params, verify=not config.get("insecure"), cache_seconds=cache)
        if isinstance(payload, dict) and payload.get("status") is False:
            raise AdapterError(str(payload.get("error") or "SABnzbd refused the request."), code="sab_error")
        return payload

    async def snapshot(self, config: dict[str, Any], ctx: Context) -> Snapshot:
        payload = await self._call(config, ctx, "queue", cache=5)
        queue = payload.get("queue") or {}
        items = []
        for slot in queue.get("slots") or []:
            try:
                progress = float(slot.get("percentage") or 0)
            except ValueError:
                progress = 0.0
            items.append(QueueItem(
                name=slot.get("filename", "?"), progress=progress, size_bytes=_mb(slot.get("mb")),
                eta_seconds=_seconds(slot.get("timeleft")), state=str(slot.get("status", "downloading")).lower(),
                identifier=slot.get("nzo_id", ""),
            ))
        try:
            speed = float(queue.get("kbpersec") or 0) * 1024
        except ValueError:
            speed = 0.0
        return Snapshot(
            download_bps=speed,
            paused=bool(queue.get("paused")),
            remaining_bytes=_mb(queue.get("mbleft")),
            items=items,
            total=int(queue.get("noofslots") or len(items)),
            free_bytes=float(queue.get("diskspace1") or 0) * 1024 ** 3 or None,
        )

    async def pause(self, config: dict[str, Any], ctx: Context) -> None:
        await self._call(config, ctx, "pause")

    async def resume(self, config: dict[str, Any], ctx: Context) -> None:
        await self._call(config, ctx, "resume")


ADAPTER = SabnzbdAdapter()
