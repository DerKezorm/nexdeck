"""Maintainerr: what its rules have collected for deletion.

The card that says how much of the library is on its way out, which is the one
thing about a clean-up rule nobody wants to learn afterwards.
"""

from __future__ import annotations

from typing import Any

from . import demo as fake
from .base import Adapter, Context, Field, WidgetData, WidgetType, base_url


class MaintainerrAdapter(Adapter):
    kind = "maintainerr"
    label = "Maintainerr"
    category = "media"
    description = "Collections of a clean-up rule, with how much they hold and when it goes."
    icon = "maintainerr"
    docs_url = "https://docs.maintainerr.info/"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://maintainerr:6246"),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(
            kind="collections",
            label="Collections",
            description="One line per collection with what it holds and its deadline.",
            renderer="list",
            default_size=(4, 3),
            refresh_seconds=600,
            metrics=("media",),
        ),
        WidgetType(
            kind="status",
            label="Status",
            description="How much is collected for deletion, over how many collections.",
            renderer="value",
            default_size=(2, 2),
            min_size=(1, 1),
            refresh_seconds=600,
            metrics=("media", "collections"),
        ),
    )

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, cache: float = 300) -> Any:
        return await ctx.get_json(
            f"{base_url(config)}/api{path}",
            verify=not config.get("insecure"),
            cache_seconds=cache,
        )

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        collections = await self._get(config, ctx, "/collections", cache=0)
        return f"Maintainerr answers with {len(collections) if isinstance(collections, list) else 0} collections."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        collections = await self._get(config, ctx, "/collections")
        rows = collections if isinstance(collections, list) else []
        total = sum(len(entry.get("media") or []) for entry in rows)
        active = [entry for entry in rows if entry.get("isActive", True)]

        if widget_kind == "status":
            return WidgetData(
                status="warn" if total else "ok",
                primary={"label": "Media", "value": total},
                secondary=[
                    {"label": "Collections", "value": len(rows)},
                    {"label": "Active", "value": len(active)},
                ],
                metrics={"media": float(total), "collections": float(len(rows))},
            )

        items = []
        for entry in rows:
            count = len(entry.get("media") or [])
            days = entry.get("deleteAfterDays")
            items.append({
                "title": entry.get("title") or "?",
                "subtitle": entry.get("description") or "",
                "value": f"{count} · {days} d" if days else str(count),
                "status": "warn" if count else ("unknown" if not entry.get("isActive", True) else "ok"),
            })
        return WidgetData(
            status="warn" if total else "ok",
            items=items,
            secondary=[{"label": "Media", "value": total}],
            metrics={"media": float(total)},
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        rows = [("Watched over 90 days", "Movies nobody came back to", int(fake.walk("mtr-a", tick, 0, 24)), 14, True),
                ("Ended series, fully watched", "Series with no new season", int(fake.walk("mtr-b", tick, 0, 9)), 30, True),
                ("Never watched", "Sitting there for a year", 0, 60, False)]
        total = sum(count for _, _, count, _, _ in rows)
        if widget_kind == "status":
            return WidgetData(
                status="warn" if total else "ok",
                primary={"label": "Media", "value": total},
                secondary=[{"label": "Collections", "value": len(rows)}, {"label": "Active", "value": 2}],
                metrics={"media": float(total), "collections": float(len(rows))},
            )
        return WidgetData(
            status="warn" if total else "ok",
            items=[
                {"title": title, "subtitle": description, "value": f"{count} · {days} d", "status": "warn" if count else ("ok" if active else "unknown")}
                for title, description, count, days, active in rows
            ],
            secondary=[{"label": "Media", "value": total}],
            metrics={"media": float(total)},
        )


ADAPTER = MaintainerrAdapter()
