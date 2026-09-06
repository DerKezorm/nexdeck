"""Tdarr: the transcoding queue and the nodes that work it off.

Tdarr answers one address for almost everything: a POST to ``/api/v2/cruddb``
with the collection it should read.
"""

from __future__ import annotations

from typing import Any

from . import demo as fake
from .base import Adapter, AdapterError, Context, Field, WidgetData, WidgetType, base_url


class TdarrAdapter(Adapter):
    kind = "tdarr"
    label = "Tdarr"
    category = "media"
    description = "Queue, transcodes, errors and the nodes doing the work."
    #: Neither dashboard-icons nor selfh.st has a logo for it; a drawn symbol
    #: is honest, a grey box is not.
    icon = "lucide:film"
    #: Seen against a live Tdarr with its internal node (06.09.2026).
    beta = False
    docs_url = "https://docs.tdarr.io/docs/api/"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://tdarr:8265"),
        Field("api_key", "API key", type="password", secret=True, help="Only if the server was started with an API key."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(
            kind="queue",
            label="Queue",
            description="What is waiting, what is done and what failed.",
            renderer="value",
            default_size=(2, 2),
            min_size=(1, 1),
            refresh_seconds=60,
            metrics=("queued", "errors"),
        ),
        WidgetType(
            kind="nodes",
            label="Nodes",
            description="One line per node with what it is doing.",
            renderer="list",
            default_size=(3, 3),
            refresh_seconds=60,
            metrics=("nodes",),
        ),
    )

    def _headers(self, config: dict[str, Any]) -> dict[str, str]:
        key = str(config.get("api_key") or "")
        return {"x-api-key": key} if key else {}

    async def _post(self, config: dict[str, Any], ctx: Context, path: str, body: Any) -> Any:
        response = await ctx.request(
            "POST",
            f"{base_url(config)}/api/v2{path}",
            headers=self._headers(config),
            json_body=body,
            verify=not config.get("insecure"),
        )
        if response.status_code >= 400:
            raise AdapterError(f"Tdarr answered with HTTP {response.status_code}.", code="http_error")
        try:
            return response.json()
        except ValueError:
            return {}

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, cache: float = 30) -> Any:
        return await ctx.get_json(
            f"{base_url(config)}/api/v2{path}",
            headers=self._headers(config),
            verify=not config.get("insecure"),
            cache_seconds=cache,
        )

    async def _statistics(self, config: dict[str, Any], ctx: Context) -> dict[str, Any]:
        payload = await self._post(config, ctx, "/cruddb", {
            "data": {"collection": "StatisticsJSONDB", "mode": "getById", "docID": "statistics", "obj": {}},
        })
        return payload if isinstance(payload, dict) else {}

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        statistics = await self._statistics(config, ctx)
        return f"Tdarr answers with {int(statistics.get('totalFileCount') or 0)} files in its library."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "nodes":
            nodes = await self._get(config, ctx, "/get-nodes", cache=30)
            items = []
            for name, node in (nodes or {}).items() if isinstance(nodes, dict) else []:
                workers = node.get("workers") or {}
                busy = len(workers)
                items.append({
                    "title": node.get("nodeName") or name,
                    "subtitle": f"{node.get('nodeOS', '')} · {node.get('nodePaused') and 'paused' or 'running'}".strip(" ·"),
                    "value": busy,
                    "status": "unknown" if node.get("nodePaused") else "ok",
                })
            return WidgetData(
                items=items,
                secondary=[{"label": "Nodes", "value": len(items)}],
                metrics={"nodes": float(len(items))},
            )

        statistics = await self._statistics(config, ctx)
        queued = int(statistics.get("table1Count") or 0)
        errors = int(statistics.get("table3Count") or 0)
        done = int(statistics.get("table2Count") or 0)
        total = int(statistics.get("totalFileCount") or 0)
        return WidgetData(
            status="bad" if errors else ("warn" if queued else "ok"),
            primary={"label": "Queued", "value": queued},
            secondary=[
                {"label": "Transcoded", "value": done},
                {"label": "Errors", "value": errors},
                {"label": "Files", "value": total},
            ],
            metrics={"queued": float(queued), "errors": float(errors)},
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        queued = int(fake.walk("tdarr-queue", tick, 0, 42))
        errors = 1 if fake.flicker("tdarr-error", tick, 0.1) else 0
        if widget_kind == "nodes":
            rows = [("basement", "linux", 2, False), ("desktop", "windows", 0, True)]
            return WidgetData(
                items=[
                    {"title": name, "subtitle": f"{system} · {'paused' if paused else 'running'}", "value": workers, "status": "unknown" if paused else "ok"}
                    for name, system, workers, paused in rows
                ],
                secondary=[{"label": "Nodes", "value": len(rows)}],
                metrics={"nodes": float(len(rows))},
            )
        return WidgetData(
            status="bad" if errors else ("warn" if queued else "ok"),
            primary={"label": "Queued", "value": queued},
            secondary=[
                {"label": "Transcoded", "value": fake.counter("tdarr-done", tick, 4820, 0.05)},
                {"label": "Errors", "value": errors},
                {"label": "Files", "value": 18240},
            ],
            metrics={"queued": float(queued), "errors": float(errors)},
        )


ADAPTER = TdarrAdapter()
