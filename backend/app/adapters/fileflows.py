"""FileFlows: the processing queue and the runners on it."""

from __future__ import annotations

from typing import Any

from . import demo as fake
from .base import Adapter, Context, Field, WidgetData, WidgetType, base_url


class FileFlowsAdapter(Adapter):
    kind = "fileflows"
    label = "FileFlows"
    category = "media"
    description = "What is queued, what is running and what came out of it."
    icon = "fileflows"
    docs_url = "https://fileflows.com/docs/webhooks/api"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://fileflows:19200"),
        Field("api_token", "Access token", type="password", secret=True, help="Only if FileFlows was given one under Settings > Security."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(
            kind="status",
            label="Status",
            description="Queue, running files and what is done.",
            renderer="value",
            default_size=(2, 2),
            min_size=(1, 1),
            refresh_seconds=30,
            metrics=("queued", "processing"),
        ),
        WidgetType(
            kind="running",
            label="Running",
            description="One line per file being worked on, with progress.",
            renderer="list",
            default_size=(4, 3),
            refresh_seconds=20,
            metrics=("processing",),
        ),
    )

    def _headers(self, config: dict[str, Any]) -> dict[str, str]:
        token = str(config.get("api_token") or "")
        return {"x-token": token} if token else {}

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, cache: float = 15) -> Any:
        return await ctx.get_json(
            f"{base_url(config)}/api{path}",
            headers=self._headers(config),
            verify=not config.get("insecure"),
            cache_seconds=cache,
        )

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        status = await self._get(config, ctx, "/status", cache=0)
        return f"FileFlows answers; {int((status or {}).get('queue') or 0)} files are queued."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "running":
            workers = await self._get(config, ctx, "/worker", cache=10)
            items = []
            for worker in workers if isinstance(workers, list) else []:
                name = worker.get("relativeFile") or worker.get("libraryFile", {}).get("name") or "?"
                percent_done = float(worker.get("currentPartPercent") or 0)
                items.append({
                    "title": str(name).split("/")[-1],
                    "subtitle": worker.get("currentPartName") or worker.get("library", {}).get("name") or "",
                    "progress": round(percent_done, 1),
                    "value": f"{percent_done:.0f}%",
                    "status": "ok",
                })
            return WidgetData(items=items, secondary=[{"label": "Running", "value": len(items)}], metrics={"processing": float(len(items))})

        status = await self._get(config, ctx, "/status") or {}
        queued = int(status.get("queue") or 0)
        processing = int(status.get("processing") or 0)
        return WidgetData(
            status="warn" if queued else "ok",
            primary={"label": "Queued", "value": queued},
            secondary=[
                {"label": "Running", "value": processing},
                {"label": "Processed", "value": int(status.get("processed") or 0)},
                {"label": "Time saved", "value": str(status.get("time") or "?")},
            ],
            metrics={"queued": float(queued), "processing": float(processing)},
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        queued = int(fake.walk("fileflows-queue", tick, 0, 18))
        if widget_kind == "running":
            rows = [("Copper.Sky.2025.mkv", "Video Encode"), ("Northern.Shore.S01E02.mkv", "Audio Normalise")]
            return WidgetData(
                items=[
                    {
                        "title": name,
                        "subtitle": part,
                        "progress": round((fake.walk(f"ff-{index}", tick, 5, 95) + tick * 0.3) % 100, 1),
                        "value": f"{int((fake.walk(f'ff-{index}', tick, 5, 95) + tick * 0.3) % 100)}%",
                        "status": "ok",
                    }
                    for index, (name, part) in enumerate(rows)
                ],
                secondary=[{"label": "Running", "value": len(rows)}],
                metrics={"processing": float(len(rows))},
            )
        return WidgetData(
            status="warn" if queued else "ok",
            primary={"label": "Queued", "value": queued},
            secondary=[
                {"label": "Running", "value": 2},
                {"label": "Processed", "value": fake.counter("fileflows-done", tick, 1420, 0.02)},
                {"label": "Time saved", "value": "18d 4h"},
            ],
            metrics={"queued": float(queued), "processing": 2.0},
        )


ADAPTER = FileFlowsAdapter()
