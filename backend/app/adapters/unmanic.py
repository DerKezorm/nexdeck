"""Unmanic: the library optimiser and its workers."""

from __future__ import annotations

from typing import Any

from . import demo as fake
from .base import Adapter, AdapterError, Context, Field, WidgetData, WidgetType, base_url


class UnmanicAdapter(Adapter):
    kind = "unmanic"
    label = "Unmanic"
    category = "media"
    description = "Pending tasks and what each worker is converting."
    #: Neither dashboard-icons nor selfh.st has a logo for it; a drawn symbol
    #: is honest, a grey box is not.
    icon = "lucide:rotate-cw"
    docs_url = "https://docs.unmanic.app/docs/api/"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://unmanic:8888"),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(
            kind="workers",
            label="Workers",
            description="One line per worker with the file it is on.",
            renderer="list",
            default_size=(4, 3),
            refresh_seconds=30,
            metrics=("busy",),
        ),
        WidgetType(
            kind="queue",
            label="Queue",
            description="How much is waiting, and how many workers are running.",
            renderer="value",
            default_size=(2, 2),
            min_size=(1, 1),
            refresh_seconds=60,
            metrics=("queued", "busy"),
        ),
    )

    async def _post(self, config: dict[str, Any], ctx: Context, path: str, body: Any) -> Any:
        response = await ctx.request(
            "POST",
            f"{base_url(config)}/unmanic/api/v2{path}",
            json_body=body,
            verify=not config.get("insecure"),
        )
        if response.status_code >= 400:
            raise AdapterError(f"Unmanic answered with HTTP {response.status_code}.", code="http_error")
        try:
            return response.json()
        except ValueError:
            return {}

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, cache: float = 15) -> Any:
        return await ctx.get_json(
            f"{base_url(config)}/unmanic/api/v2{path}",
            verify=not config.get("insecure"),
            cache_seconds=cache,
        )

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        workers = await self._get(config, ctx, "/workers/status", cache=0)
        return f"Unmanic answers with {len(workers.get('workers_status') or [])} workers."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        status = await self._get(config, ctx, "/workers/status")
        workers = status.get("workers_status") or [] if isinstance(status, dict) else []
        busy = sum(1 for worker in workers if not worker.get("idle"))

        if widget_kind == "workers":
            items = []
            for worker in workers:
                idle = bool(worker.get("idle"))
                current = worker.get("current_file") or ""
                items.append({
                    "title": worker.get("name") or worker.get("id") or "?",
                    "subtitle": current if not idle else "idle",
                    "progress": float(worker.get("progress", {}).get("percent") or 0) if isinstance(worker.get("progress"), dict) else 0.0,
                    "value": "" if idle else f"{int(float(worker.get('progress', {}).get('percent') or 0))}%",
                    "status": "unknown" if idle else "ok",
                })
            return WidgetData(items=items, secondary=[{"label": "Busy", "value": busy}], metrics={"busy": float(busy)})

        pending = await self._post(config, ctx, "/pending/tasks", {"start": 0, "length": 1, "search_value": "", "order_by": "priority", "order_direction": "desc"})
        queued = int((pending or {}).get("recordsTotal") or 0)
        return WidgetData(
            status="warn" if queued else "ok",
            primary={"label": "Queued", "value": queued},
            secondary=[{"label": "Workers", "value": len(workers)}, {"label": "Busy", "value": busy}],
            metrics={"queued": float(queued), "busy": float(busy)},
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        queued = int(fake.walk("unmanic-queue", tick, 0, 24))
        if widget_kind == "workers":
            rows = [("Worker 1", "Harbour.Lights.S03E04.mkv", 41.0, False), ("Worker 2", "", 0.0, True)]
            return WidgetData(
                items=[
                    {
                        "title": name,
                        "subtitle": current or "idle",
                        "progress": round((share + tick * 0.4) % 100, 1) if not idle else 0.0,
                        "value": "" if idle else f"{int((share + tick * 0.4) % 100)}%",
                        "status": "unknown" if idle else "ok",
                    }
                    for name, current, share, idle in rows
                ],
                secondary=[{"label": "Busy", "value": 1}],
                metrics={"busy": 1.0},
            )
        return WidgetData(
            status="warn" if queued else "ok",
            primary={"label": "Queued", "value": queued},
            secondary=[{"label": "Workers", "value": 2}, {"label": "Busy", "value": 1}],
            metrics={"queued": float(queued), "busy": 1.0},
        )


ADAPTER = UnmanicAdapter()
