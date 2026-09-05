"""Prowlarr: indexers and their health."""

from __future__ import annotations

from typing import Any

from . import demo as fake
from .arr_base import ArrAdapter
from .base import Context, Field, WidgetData, WidgetType


class ProwlarrAdapter(ArrAdapter):
    kind = "prowlarr"
    label = "Prowlarr"
    category = "downloads"
    description = "Indexers, their health and today's grabs."
    icon = "prowlarr"
    #: Seen against a live Prowlarr 2.5.2 (05.09.2026).
    beta = False
    api_version = "v1"
    noun = "indexer"
    list_path = "indexer"
    calendar_supported = False

    def _widgets(self) -> tuple[WidgetType, ...]:
        return (
            WidgetType(
                kind="indexers",
                label="Indexers",
                description="Every indexer with its state and the grabs and queries of the day.",
                renderer="list",
                default_size=(3, 3),
                refresh_seconds=120,
                metrics=("grabs",),
                options=(Field("limit", "Entries", type="number", default=12),),
            ),
            WidgetType(
                kind="status",
                label="Status",
                description="Indexer count, disabled indexers and health warnings.",
                renderer="value",
                default_size=(2, 2),
                min_size=(1, 1),
                refresh_seconds=120,
                metrics=("grabs",),
            ),
        )

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        indexers = await self.api(config, ctx, "indexer", cache_seconds=60)
        stats = await self.api(config, ctx, "indexerstats", cache_seconds=120)
        per_indexer = {s.get("indexerId"): s for s in (stats.get("indexers") or [])} if isinstance(stats, dict) else {}
        health = await self.api(config, ctx, "health", cache_seconds=60)
        grabs = sum(int(s.get("numberOfGrabs", 0)) for s in per_indexer.values())
        disabled = [i for i in indexers if not i.get("enable", True)]
        if widget_kind == "status":
            errors = [h for h in health if h.get("type") == "error"]
            return WidgetData(
                status="bad" if errors else ("warn" if disabled or health else "ok"),
                primary={"label": "Indexers", "value": len(indexers)},
                secondary=[{"label": "Disabled", "value": len(disabled)}, {"label": "Grabs", "value": grabs}],
                metrics={"grabs": float(grabs)},
            )
        items = []
        for indexer in sorted(indexers, key=lambda i: i.get("name", ""))[: int(options.get("limit") or 12)]:
            stat = per_indexer.get(indexer.get("id"), {})
            items.append({
                "title": indexer.get("name", "?"),
                "subtitle": f"{stat.get('numberOfQueries', 0)} queries, {stat.get('numberOfGrabs', 0)} grabs",
                "status": "ok" if indexer.get("enable", True) else "bad",
                "value": f"{stat.get('averageResponseTime', 0)} ms",
            })
        return WidgetData(items=items, metrics={"grabs": float(grabs)}, status="warn" if disabled else "ok")

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        names = ["NZBgeek", "DrunkenSlug", "NZBFinder", "TorrentLeech", "IPTorrents", "AnimeBytes"]
        grabs = fake.counter("prowlarr-grabs", tick, 12, 0.01)
        if widget_kind == "status":
            return WidgetData(primary={"label": "Indexers", "value": len(names)},
                              secondary=[{"label": "Disabled", "value": 1}, {"label": "Grabs", "value": grabs}],
                              metrics={"grabs": float(grabs)}, status="warn")
        items = [{"title": n, "subtitle": f"{fake.counter(n, tick, 40, 0.02)} queries, {fake.counter(n + 'g', tick, 2, 0.003)} grabs",
                  "status": "bad" if n == "IPTorrents" else "ok", "value": f"{int(fake.walk(n + 'rt', tick, 180, 900))} ms"} for n in names]
        return WidgetData(items=items, metrics={"grabs": float(grabs)}, status="warn")


ADAPTER = ProwlarrAdapter()
