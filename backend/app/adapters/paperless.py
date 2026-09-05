"""Paperless-ngx: how much is filed, and what came in last.

The token is made in Paperless under the user profile and rides as
``Authorization: Token ...``, not as a bearer token; that one letter is the
usual reason the connection test fails.
"""

from __future__ import annotations

from typing import Any

from . import demo as fake
from .base import Adapter, Context, Field, WidgetData, WidgetType, base_url


class PaperlessAdapter(Adapter):
    kind = "paperless"
    label = "Paperless-ngx"
    category = "other"
    description = "Documents, the inbox and what was filed last."
    icon = "paperless-ngx"
    docs_url = "https://docs.paperless-ngx.com/api/"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://paperless:8000"),
        Field("token", "API token", type="password", secret=True, required=True, help="In Paperless under the user profile, not the password."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(
            kind="library",
            label="Archive",
            description="How many documents there are, and how many are still in the inbox.",
            renderer="value",
            default_size=(2, 2),
            min_size=(1, 1),
            refresh_seconds=300,
            metrics=("documents", "inbox"),
        ),
        WidgetType(
            kind="recent",
            label="Latest documents",
            description="What was filed last, newest first.",
            renderer="list",
            default_size=(4, 3),
            refresh_seconds=300,
            options=(Field("limit", "Entries", type="number", default=6),),
        ),
    )

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, params: dict[str, Any] | None = None, cache: float = 120) -> Any:
        return await ctx.get_json(
            f"{base_url(config)}/api{path}",
            headers={"Authorization": f"Token {config.get('token') or ''}", "Accept": "application/json"},
            params=params,
            verify=not config.get("insecure"),
            cache_seconds=cache,
        )

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        statistics = await self._get(config, ctx, "/statistics/", cache=0)
        return f"Paperless answers with {int(statistics.get('documents_total') or 0)} documents."

    async def _correspondents(self, config: dict[str, Any], ctx: Context) -> dict[int, str]:
        """A document names its correspondent by number, so the names have to
        be looked up once; they change about never."""
        payload = await self._get(config, ctx, "/correspondents/", {"page_size": 500}, cache=3600)
        return {int(entry.get("id")): str(entry.get("name") or "") for entry in (payload or {}).get("results") or [] if entry.get("id") is not None}

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "recent":
            limit = int(options.get("limit") or 6)
            payload = await self._get(config, ctx, "/documents/", {"ordering": "-added", "page_size": limit}, cache=300)
            names = await self._correspondents(config, ctx)
            items = []
            for document in (payload or {}).get("results") or []:
                # A document names its correspondent by number; a few builds
                # send the name itself, and then there is nothing to look up.
                raw = document.get("correspondent")
                who = raw if isinstance(raw, str) else names.get(raw or -1, "")
                added = str(document.get("added") or "")[:10]
                items.append({
                    "title": str(document.get("title") or "?"),
                    "subtitle": f"{who} · {added}".strip(" ·"),
                })
            return WidgetData(items=items, secondary=[{"label": "Documents", "value": int((payload or {}).get("count") or 0)}])

        statistics = await self._get(config, ctx, "/statistics/", cache=300)
        total = int(statistics.get("documents_total") or 0)
        inbox = int(statistics.get("documents_inbox") or 0)
        return WidgetData(
            primary={"label": "Documents", "value": total},
            secondary=[
                {"label": "Inbox", "value": inbox},
                {"label": "Tags", "value": int(statistics.get("tag_count") or 0)},
                {"label": "Correspondents", "value": int(statistics.get("correspondent_count") or 0)},
            ],
            metrics={"documents": float(total), "inbox": float(inbox)},
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        if widget_kind == "recent":
            rows = [
                ("Electricity bill", "City works", "2026-09-04"),
                ("Insurance policy", "Northern Mutual", "2026-09-02"),
                ("Payslip", "Harbour Logistics", "2026-08-31"),
                ("Warranty dishwasher", "Elm Street Electrics", "2026-08-28"),
                ("Tax assessment", "Tax office", "2026-08-24"),
            ]
            return WidgetData(
                items=[{"title": title, "subtitle": f"{who} · {when}"} for title, who, when in rows[: int(options.get("limit") or 6)]],
                secondary=[{"label": "Documents", "value": fake.counter("paperless-total", tick, 3480, 0.05)}],
            )
        total = fake.counter("paperless-total", tick, 3480, 0.05)
        inbox = int(fake.walk("paperless-inbox", tick, 0, 7))
        return WidgetData(
            primary={"label": "Documents", "value": total},
            secondary=[
                {"label": "Inbox", "value": inbox},
                {"label": "Tags", "value": 38},
                {"label": "Correspondents", "value": 62},
            ],
            metrics={"documents": float(total), "inbox": float(inbox)},
        )


ADAPTER = PaperlessAdapter()
