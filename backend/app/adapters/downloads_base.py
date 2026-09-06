"""Shared shape for download clients: SABnzbd, NZBGet, qBittorrent, Transmission, Deluge.

Every client answers the same three questions: how fast, what is in the
queue, is it paused. The concrete adapters translate their API into a
``Snapshot``; the widgets are built here once.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import demo as fake
from .base import (
    Action,
    Adapter,
    AdapterError,
    Context,
    Detected,
    Field,
    WidgetData,
    WidgetType,
    as_gauge,
    duration_short,
    gauge_fields,
    human_bytes,
    human_rate,
)


@dataclass
class QueueItem:
    name: str
    progress: float
    size_bytes: float | None = None
    eta_seconds: float | None = None
    state: str = "downloading"
    identifier: str = ""


@dataclass
class Snapshot:
    download_bps: float = 0.0
    upload_bps: float | None = None
    paused: bool = False
    remaining_bytes: float | None = None
    items: list[QueueItem] = field(default_factory=list)
    total: int = 0
    free_bytes: float | None = None


class DownloadAdapter(Adapter):
    category = "downloads"
    has_upload = False
    widgets = (
        WidgetType(
            kind="queue",
            label="Queue",
            description="Active downloads with progress, speed and time left.",
            renderer="list",
            default_size=(4, 3),
            refresh_seconds=10,
            metrics=("download",),
            options=(Field("limit", "Entries", type="number", default=8),),
        ),
        WidgetType(
            kind="speed",
            label="Speed",
            description="Current download speed, queue size and remaining data.",
            renderer="value",
            default_size=(2, 2),
            refresh_seconds=10,
            metrics=("download",),
            options=gauge_fields("What your line can take, in MB/s.", "12.5"),
        ),
    )

    async def snapshot(self, config: dict[str, Any], ctx: Context) -> Snapshot:
        raise NotImplementedError

    async def pause(self, config: dict[str, Any], ctx: Context) -> None:
        raise NotImplementedError

    async def resume(self, config: dict[str, Any], ctx: Context) -> None:
        raise NotImplementedError

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        snapshot = await self.snapshot(config, ctx)
        return f"{self.label} answers, {snapshot.total} items in the queue."

    def _actions(self, paused: bool) -> list[Action]:
        if paused:
            return [Action(id="resume", label="Resume", icon="play")]
        return [Action(id="pause", label="Pause", icon="pause")]

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        snapshot = await self.snapshot(config, ctx)
        return self._widget(widget_kind, options, snapshot)

    def _widget(self, widget_kind: str, options: dict[str, Any], snapshot: Snapshot) -> WidgetData:
        metrics = {"download": round(snapshot.download_bps / 1024 / 1024, 2)}
        if snapshot.upload_bps is not None:
            metrics["upload"] = round(snapshot.upload_bps / 1024 / 1024, 2)
        status = "warn" if snapshot.paused else "ok"
        if widget_kind == "speed":  # noqa: RET505
            secondary = [{"label": "Queue", "value": snapshot.total}]
            if snapshot.remaining_bytes is not None:
                secondary.append({"label": "Left", "value": human_bytes(snapshot.remaining_bytes)})
            if snapshot.upload_bps is not None:
                secondary.append({"label": "Up", "value": human_rate(snapshot.upload_bps)})
            if snapshot.free_bytes is not None:
                secondary.append({"label": "Free", "value": human_bytes(snapshot.free_bytes)})
            card = WidgetData(
                status=status,
                primary={"label": "Paused" if snapshot.paused else "Download", "value": round(snapshot.download_bps / 1024 / 1024, 1), "unit": "MB/s"},
                secondary=secondary,
                metrics=metrics,
                actions=self._actions(snapshot.paused),
            )
            return as_gauge(card, options)
        limit = int(options.get("limit") or 8)
        items = []
        for item in snapshot.items[:limit]:
            subtitle_parts = []
            if item.size_bytes:
                subtitle_parts.append(human_bytes(item.size_bytes))
            if item.eta_seconds:
                subtitle_parts.append(f"{duration_short(item.eta_seconds)} left")
            if item.state and item.state != "downloading":
                subtitle_parts.append(item.state)
            items.append({
                "id": item.identifier or item.name,
                "title": item.name,
                "subtitle": " · ".join(subtitle_parts),
                "progress": round(item.progress, 1),
                "value": f"{item.progress:.0f}%",
                "status": "warn" if item.state in ("paused", "stalled", "queued") else ("bad" if item.state in ("error", "failed") else "ok"),
            })
        return WidgetData(
            status=status,
            items=items,
            secondary=[{"label": "Speed", "value": human_rate(snapshot.download_bps)}, {"label": "Queue", "value": snapshot.total}],
            metrics=metrics,
            actions=self._actions(snapshot.paused),
        )

    #: How far along an item has to have been for its disappearance to mean
    #: "finished" rather than "removed".
    NEARLY_DONE = 95.0

    def detect(self, widget_kind: str, before: WidgetData | None, after: WidgetData,
               options: dict[str, Any]) -> list[Detected]:
        """An item that was nearly done and is gone finished.

        ⚠️ Only nearly done. The same disappearance at ten per cent means
        somebody removed it, and reporting that as "finished" is worse than
        reporting nothing: it is a claim about a file that is not there.

        ⚠️ And only when the queue was read both times. A card that was broken
        a minute ago has an empty "before", and calling every running download
        finished on the first successful fetch would be a burst of lies.
        """
        if widget_kind != "queue" or before is None or before.error or not before.items:
            return []
        gone_but_done = []
        still_here = {str(item.get("id") or item.get("title")) for item in after.items}
        for item in before.items:
            key = str(item.get("id") or item.get("title"))
            if key in still_here:
                continue
            try:
                progress = float(item.get("progress") or 0)
            except (TypeError, ValueError):
                continue
            if progress >= self.NEARLY_DONE:
                gone_but_done.append(str(item.get("title") or key))
        return [
            Detected(
                event="download_done",
                title=f"{name} finished",
                body=f"{self.label} has nothing left to do on it.",
                # The name is the key: two different files finishing a minute
                # apart are two messages, the same one is not two.
                key=f"download_done:{name}",
            )
            for name in gone_but_done[:5]
        ]

    async def action(self, widget_kind: str, action_id: str, params: dict[str, Any], config: dict[str, Any],
                     options: dict[str, Any], ctx: Context) -> str:
        if action_id == "pause":
            await self.pause(config, ctx)
            return "Downloads paused."
        if action_id == "resume":
            await self.resume(config, ctx)
            return "Downloads resumed."
        raise AdapterError("Unknown action.", code="no_such_action")

    demo_names = ("Copper.Sky.2025.2160p", "Nightshift.2026.1080p", "Harbour.Lights.S03E04", "Orbital.2025.REMUX")

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        paused = fake.flicker(f"{self.kind}-paused", tick, 0.1)
        speed = 0.0 if paused else fake.walk(f"{self.kind}-speed", tick, 8, 62) * 1024 * 1024
        items = []
        for index, name in enumerate(self.demo_names):
            progress = (fake.walk(f"{self.kind}-p{index}", tick, 0, 100, period=300) + tick * 0.2 + index * 27) % 100
            items.append(QueueItem(name=name, progress=progress, size_bytes=(4 + index * 3) * 1024 ** 3,
                                   eta_seconds=(100 - progress) * 30, state="paused" if paused else "downloading"))
        snapshot = Snapshot(download_bps=speed, upload_bps=fake.walk(f"{self.kind}-up", tick, 0.5, 6) * 1024 * 1024 if self.has_upload else None,
                            paused=paused, remaining_bytes=sum((i.size_bytes or 0) * (1 - i.progress / 100) for i in items),
                            items=items, total=len(items), free_bytes=1.8 * 1024 ** 4)
        return self._widget(widget_kind, options, snapshot)
