"""Audiobookshelf: audiobooks and podcasts, and who is listening.

Stands next to Plex in most households. The API key comes from the account
settings and rides as a bearer token.
"""

from __future__ import annotations

from typing import Any

from . import demo as fake
from .base import (
    Adapter,
    Context,
    Field,
    WidgetData,
    WidgetType,
    base_url,
    duration_short,
    human_bytes,
)


class AudiobookshelfAdapter(Adapter):
    kind = "audiobookshelf"
    label = "Audiobookshelf"
    category = "media"
    description = "Libraries, listeners and what is playing right now."
    icon = "audiobookshelf"
    docs_url = "https://api.audiobookshelf.org/"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://audiobookshelf:13378"),
        Field("api_key", "API key", type="password", secret=True, required=True, help="Settings > Users > your account > API token."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(
            kind="library",
            label="Library",
            description="Books, podcasts and what they occupy.",
            renderer="value",
            default_size=(2, 2),
            min_size=(1, 1),
            refresh_seconds=300,
            metrics=("items",),
        ),
        WidgetType(
            kind="listening",
            label="Listening now",
            description="Who is listening to what, with how far they are.",
            renderer="list",
            default_size=(4, 3),
            refresh_seconds=30,
            metrics=("sessions",),
        ),
    )

    def _headers(self, config: dict[str, Any]) -> dict[str, str]:
        return {"Authorization": f"Bearer {config.get('api_key') or ''}"}

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, cache: float = 60) -> Any:
        return await ctx.get_json(
            f"{base_url(config)}/api{path}",
            headers=self._headers(config),
            verify=not config.get("insecure"),
            cache_seconds=cache,
        )

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        libraries = await self._get(config, ctx, "/libraries", cache=0)
        count = len(libraries.get("libraries") or []) if isinstance(libraries, dict) else 0
        return f"Audiobookshelf answers with {count} libraries."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "listening":
            # The open sessions live under the administrator's online users.
            payload = await self._get(config, ctx, "/users/online", cache=15)
            sessions = payload.get("openSessions") or [] if isinstance(payload, dict) else []
            items = []
            for session in sessions:
                duration = float(session.get("duration") or 0)
                played = float(session.get("currentTime") or 0)
                items.append({
                    "title": session.get("displayTitle") or "?",
                    "subtitle": f"{session.get('userId') and (session.get('displayAuthor') or '') or ''} · {session.get('deviceInfo', {}).get('deviceType', '')}".strip(" ·"),
                    "progress": round(100.0 * played / duration, 1) if duration else 0.0,
                    "value": duration_short(max(0.0, duration - played)),
                    "status": "ok",
                })
            return WidgetData(
                items=items,
                secondary=[{"label": "Listening", "value": len(items)}],
                metrics={"sessions": float(len(items))},
            )

        libraries = await self._get(config, ctx, "/libraries", cache=300)
        entries = libraries.get("libraries") or [] if isinstance(libraries, dict) else []
        books = 0
        podcasts = 0
        size = 0.0
        for library in entries:
            stats = await self._get(config, ctx, f"/libraries/{library.get('id')}/stats", cache=600)
            total = int(stats.get("totalItems") or 0)
            size += float(stats.get("totalSize") or 0)
            if str(library.get("mediaType")) == "podcast":
                podcasts += total
            else:
                books += total
        return WidgetData(
            primary={"label": "Books", "value": books},
            secondary=[
                {"label": "Podcasts", "value": podcasts},
                {"label": "Libraries", "value": len(entries)},
                {"label": "Size", "value": human_bytes(size)},
            ],
            metrics={"items": float(books + podcasts)},
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        if widget_kind == "listening":
            listeners = [("The Long Way Home", "Alex · phone", 0.42), ("A History of Harbours", "Sam · tablet", 0.71)]
            # Never zero: the demo is there to show what the card looks like.
            count = max(1, int(fake.walk("abs-sessions", tick, 1, 2)))
            items = [
                {
                    "title": title,
                    "subtitle": who,
                    "progress": round(100 * ((share + tick / 900) % 1), 1),
                    "value": duration_short(3600 * (1 - share)),
                    "status": "ok",
                }
                for title, who, share in listeners[:count]
            ]
            return WidgetData(items=items, secondary=[{"label": "Listening", "value": count}], metrics={"sessions": float(count)})
        return WidgetData(
            primary={"label": "Books", "value": fake.counter("abs-books", tick, 412, 0.004)},
            secondary=[
                {"label": "Podcasts", "value": 38},
                {"label": "Libraries", "value": 2},
                {"label": "Size", "value": human_bytes(9.4e11)},
            ],
            metrics={"items": 450.0},
        )


ADAPTER = AudiobookshelfAdapter()
