"""Shared code for the *arr family: Radarr, Sonarr, Lidarr, Readarr, Prowlarr.

They share the API shape (``/api/v3`` with ``X-Api-Key``), the queue, the
calendar and the health endpoint; what differs is the noun and the item
fields. Each concrete adapter fills in those differences.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from . import demo as fake
from .base import (
    Action,
    Adapter,
    AdapterError,
    Context,
    Field,
    WidgetData,
    WidgetType,
    base_url,
    human_bytes,
    percent,
)


class ArrAdapter(Adapter):
    api_version = "v3"
    #: The noun the service manages, e.g. "movie", and its list endpoint.
    noun = "item"
    list_path = "item"
    calendar_supported = True
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://radarr:7878"),
        Field("api_key", "API key", type="password", secret=True, required=True, help="Settings > General > API Key"),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )

    def _widgets(self) -> tuple[WidgetType, ...]:
        widgets = [
            WidgetType(
                kind="queue",
                label="Queue",
                description="What is downloading right now, with progress.",
                renderer="list",
                default_size=(4, 3),
                refresh_seconds=20,
                metrics=("queued",),
                options=(Field("limit", "Entries", type="number", default=8),),
            ),
            WidgetType(
                kind="status",
                label="Status",
                description="Library size, queue length, missing items and health warnings.",
                renderer="value",
                default_size=(2, 2),
                min_size=(1, 1),
                refresh_seconds=60,
                metrics=("queued", "missing"),
            ),
        ]
        if self.calendar_supported:
            widgets.append(
                WidgetType(
                    kind="calendar",
                    label="Upcoming",
                    description="Releases of the next days.",
                    renderer="calendar",
                    default_size=(3, 3),
                    refresh_seconds=600,
                    options=(Field("days", "Days ahead", type="number", default=7),),
                )
            )
        return tuple(widgets)

    def __init__(self) -> None:
        self.widgets = self._widgets()

    # -- HTTP ----------------------------------------------------------------

    def _headers(self, config: dict[str, Any]) -> dict[str, str]:
        return {"X-Api-Key": str(config.get("api_key") or "")}

    async def api(self, config: dict[str, Any], ctx: Context, path: str, params: dict[str, Any] | None = None,
                  cache_seconds: float = 5) -> Any:
        url = f"{base_url(config)}/api/{self.api_version}/{path.lstrip('/')}"
        return await ctx.get_json(url, headers=self._headers(config), params=params,
                                  verify=not config.get("insecure"), cache_seconds=cache_seconds)

    async def api_post(self, config: dict[str, Any], ctx: Context, path: str, body: Any) -> Any:
        url = f"{base_url(config)}/api/{self.api_version}/{path.lstrip('/')}"
        response = await ctx.request("POST", url, headers=self._headers(config), json_body=body, verify=not config.get("insecure"))
        if response.status_code >= 400:
            raise AdapterError(f"The service answered with HTTP {response.status_code}.", code="http_error")
        try:
            return response.json()
        except ValueError:
            return None

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        status = await self.api(config, ctx, "system/status", cache_seconds=0)
        return f"{status.get('appName', self.label)} {status.get('version', '?')} answers."

    # -- data ----------------------------------------------------------------

    def queue_item(self, entry: dict[str, Any]) -> dict[str, Any]:
        size = entry.get("size") or 0
        left = entry.get("sizeleft") or 0
        done = percent(size - left, size) if size else 0
        state = entry.get("status", "")
        status = "ok" if state in ("downloading", "completed") else ("bad" if state in ("failed", "warning") else "warn")
        return {
            "id": entry.get("id"),
            "title": self.queue_title(entry),
            "subtitle": entry.get("timeleft") or entry.get("trackedDownloadState") or state,
            "progress": done,
            "value": f"{done:.0f}%",
            "status": status,
            "size": human_bytes(size),
        }

    def queue_title(self, entry: dict[str, Any]) -> str:
        return entry.get("title") or "?"

    def calendar_item(self, entry: dict[str, Any]) -> dict[str, Any] | None:
        raise NotImplementedError

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "queue":
            queue = await self.api(config, ctx, "queue", params={"pageSize": 100, "includeUnknownMovieItems": "true"})
            records = queue.get("records", []) if isinstance(queue, dict) else queue
            limit = int(options.get("limit") or 8)
            items = [self.queue_item(e) for e in records[:limit]]
            return WidgetData(
                status="ok",
                items=items,
                secondary=[{"label": "In queue", "value": len(records)}],
                metrics={"queued": float(len(records))},
                actions=[Action(id="search_missing", label="Search missing", icon="search", confirm=True)],
            )
        if widget_kind == "status":
            return await self.status(config, ctx)
        if widget_kind == "calendar":
            days = int(options.get("days") or 7)
            items = await self.upcoming(config, ctx, days)
            return WidgetData(items=items, secondary=[{"label": "Next days", "value": len(items)}])
        raise KeyError(widget_kind)

    async def status(self, config: dict[str, Any], ctx: Context) -> WidgetData:
        health = await self.api(config, ctx, "health", cache_seconds=60)
        queue = await self.api(config, ctx, "queue/status", cache_seconds=20)
        library = await self.api(config, ctx, self.list_path, cache_seconds=300)
        count = len(library) if isinstance(library, list) else 0
        missing = 0
        if isinstance(library, list):
            missing = sum(1 for e in library if e.get("monitored") and not self.has_file(e))
        errors = [h for h in health if h.get("type") == "error"]
        warnings = [h for h in health if h.get("type") == "warning"]
        status = "bad" if errors else ("warn" if warnings else "ok")
        queued = int(queue.get("totalCount", 0)) if isinstance(queue, dict) else 0
        return WidgetData(
            status=status,
            primary={"label": self.noun_plural(), "value": count},
            secondary=[
                {"label": "Queue", "value": queued},
                {"label": "Missing", "value": missing},
                {"label": "Health", "value": (errors[0].get("message") if errors else (warnings[0].get("message") if warnings else "ok"))},
            ],
            metrics={"queued": float(queued), "missing": float(missing)},
            meta={"health": [h.get("message") for h in health]},
        )

    def has_file(self, entry: dict[str, Any]) -> bool:
        return bool(entry.get("hasFile"))

    def noun_plural(self) -> str:
        return self.noun + "s"

    async def upcoming(self, config: dict[str, Any], ctx: Context, days: int) -> list[dict[str, Any]]:
        start = datetime.now(UTC).date()
        end = start + timedelta(days=max(1, days))
        entries = await self.api(config, ctx, "calendar", params={"start": start.isoformat(), "end": end.isoformat(), "includeSeries": "true", "includeArtist": "true", "includeAuthor": "true"}, cache_seconds=300)
        items = []
        for entry in entries if isinstance(entries, list) else []:
            item = self.calendar_item(entry)
            if item:
                item["source"] = self.label
                items.append(item)
        items.sort(key=lambda i: i.get("date") or "")
        return items

    async def action(self, widget_kind: str, action_id: str, params: dict[str, Any], config: dict[str, Any],
                     options: dict[str, Any], ctx: Context) -> str:
        if action_id == "search_missing":
            await self.api_post(config, ctx, "command", {"name": self.missing_command()})
            return "Search for missing items started."
        raise AdapterError("Unknown action.", code="no_such_action")

    def missing_command(self) -> str:
        return "MissingMoviesSearch"

    # -- demo ----------------------------------------------------------------

    demo_titles: tuple[str, ...] = ("Example Title",)

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        titles = list(self.demo_titles)
        if widget_kind == "queue":
            items = []
            for index, title in enumerate(titles[:4]):
                progress = (fake.walk(f"{self.kind}-q{index}", tick, 0, 100, period=200) + tick * 0.3 + index * 23) % 100
                items.append({
                    "id": index, "title": title, "subtitle": f"{int((100 - progress) * 2.4)} min left",
                    "progress": round(progress, 1), "value": f"{progress:.0f}%", "status": "ok", "size": "4.2 GB",
                })
            return WidgetData(items=items, secondary=[{"label": "In queue", "value": len(items)}],
                              metrics={"queued": float(len(items))},
                              actions=[Action(id="search_missing", label="Search missing", icon="search", confirm=True)])
        if widget_kind == "status":
            return WidgetData(
                status="ok" if not fake.flicker(f"{self.kind}-health", tick, 0.2) else "warn",
                primary={"label": self.noun_plural(), "value": fake.counter(f"{self.kind}-count", tick, 640, 0.002)},
                secondary=[{"label": "Queue", "value": 4}, {"label": "Missing", "value": int(fake.walk(f"{self.kind}-missing", tick, 3, 19))}, {"label": "Health", "value": "ok"}],
                metrics={"queued": 4.0, "missing": fake.walk(f"{self.kind}-missing", tick, 3, 19)},
            )
        items = []
        today = datetime.now(UTC).date()
        for offset, title in enumerate(titles[:6]):
            items.append({"date": (today + timedelta(days=offset)).isoformat(), "title": title, "subtitle": "Digital release" if self.kind == "radarr" else "Episode 4", "source": self.label, "status": "ok"})
        return WidgetData(items=items, secondary=[{"label": "Next days", "value": len(items)}])
