"""Bazarr: which subtitles are missing, and what it fetched lately.

The last link of the chain that Radarr, Sonarr, Lidarr, Readarr and Prowlarr
already form here. Bazarr speaks its own API (``/api`` with ``X-API-KEY``), not
the ``/api/v3`` of the others, so it does not inherit from ``ArrAdapter``.
"""

from __future__ import annotations

from typing import Any

from . import demo as fake
from .base import Adapter, Context, Field, WidgetData, WidgetType, base_url


class BazarrAdapter(Adapter):
    kind = "bazarr"
    label = "Bazarr"
    category = "media"
    description = "Missing subtitles for series and movies, and the ones it found lately."
    icon = "bazarr"
    docs_url = "https://wiki.bazarr.media/"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://bazarr:6767"),
        Field("api_key", "API key", type="password", secret=True, required=True, help="Settings > General > API Key"),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(
            kind="status",
            label="Status",
            description="How much is waiting for subtitles, and whether a provider is refusing.",
            renderer="value",
            default_size=(2, 2),
            min_size=(1, 1),
            refresh_seconds=120,
            metrics=("wanted",),
        ),
        WidgetType(
            kind="wanted",
            label="Missing subtitles",
            description="Episodes and movies still waiting, with the languages they need.",
            renderer="list",
            default_size=(4, 3),
            refresh_seconds=300,
            metrics=("wanted",),
            options=(
                Field("limit", "Entries", type="number", default=8),
                Field("show", "Show", type="select", default="all", options=(("all", "Episodes and movies"), ("episodes", "Episodes only"), ("movies", "Movies only"))),
            ),
        ),
        WidgetType(
            kind="history",
            label="Recently fetched",
            description="The subtitles Bazarr downloaded last.",
            renderer="list",
            default_size=(4, 3),
            refresh_seconds=300,
            options=(Field("limit", "Entries", type="number", default=8),),
        ),
    )

    def _headers(self, config: dict[str, Any]) -> dict[str, str]:
        return {"X-API-KEY": str(config.get("api_key") or "")}

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, params: dict[str, Any] | None = None, cache: float = 30) -> Any:
        return await ctx.get_json(
            f"{base_url(config)}/api{path}",
            headers=self._headers(config),
            params=params,
            verify=not config.get("insecure"),
            cache_seconds=cache,
        )

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        payload = await self._get(config, ctx, "/system/status", cache=0)
        data = payload.get("data") if isinstance(payload, dict) else {}
        return f"Bazarr {(data or {}).get('bazarr_version', '?')} answers."

    @staticmethod
    def _languages(entry: dict[str, Any]) -> str:
        names = [str(missing.get("name") or missing.get("code2") or "?") for missing in entry.get("missing_subtitles") or []]
        return ", ".join(names[:4]) if names else "?"

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "history":
            limit = int(options.get("limit") or 8)
            payload = await self._get(config, ctx, "/history", params={"start": 0, "length": limit}, cache=120)
            items = [
                {
                    "title": entry.get("seriesTitle") or entry.get("title") or "?",
                    "subtitle": entry.get("description") or entry.get("language", {}).get("name", ""),
                    "status": "ok",
                }
                for entry in (payload.get("data") or [])[:limit]
            ]
            return WidgetData(items=items, secondary=[{"label": "Entries", "value": len(items)}])

        badges = await self._get(config, ctx, "/badges", cache=60)
        episodes = int(badges.get("episodes") or 0)
        movies = int(badges.get("movies") or 0)
        providers = int(badges.get("providers") or 0)
        wanted = episodes + movies

        if widget_kind == "status":
            return WidgetData(
                status="bad" if providers else ("warn" if wanted else "ok"),
                primary={"label": "Missing subtitles", "value": wanted},
                secondary=[
                    {"label": "Episodes", "value": episodes},
                    {"label": "Movies", "value": movies},
                    # A throttled provider is the reason nothing arrives, and it
                    # is invisible in the counts above.
                    {"label": "Providers refusing", "value": providers},
                ],
                metrics={"wanted": float(wanted)},
            )

        limit = int(options.get("limit") or 8)
        show = str(options.get("show") or "all")
        items: list[dict[str, Any]] = []
        if show in ("all", "episodes"):
            payload = await self._get(config, ctx, "/episodes/wanted", params={"start": 0, "length": limit}, cache=120)
            for entry in (payload.get("data") or [])[:limit]:
                number = entry.get("episode_number") or ""
                items.append({
                    "title": f"{entry.get('seriesTitle', '?')} {number}".strip(),
                    "subtitle": self._languages(entry),
                    "status": "warn",
                })
        if show in ("all", "movies"):
            payload = await self._get(config, ctx, "/movies/wanted", params={"start": 0, "length": limit}, cache=120)
            for entry in (payload.get("data") or [])[:limit]:
                items.append({"title": entry.get("title") or "?", "subtitle": self._languages(entry), "status": "warn"})
        return WidgetData(
            status="warn" if items else "ok",
            items=items[:limit],
            secondary=[{"label": "Missing subtitles", "value": wanted}],
            metrics={"wanted": float(wanted)},
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        episodes = int(fake.walk("bazarr-eps", tick, 2, 14))
        movies = int(fake.walk("bazarr-movies", tick, 0, 5))
        if widget_kind == "status":
            throttled = 1 if fake.flicker("bazarr-providers", tick, 0.1) else 0
            return WidgetData(
                status="bad" if throttled else "warn",
                primary={"label": "Missing subtitles", "value": episodes + movies},
                secondary=[
                    {"label": "Episodes", "value": episodes},
                    {"label": "Movies", "value": movies},
                    {"label": "Providers refusing", "value": throttled},
                ],
                metrics={"wanted": float(episodes + movies)},
            )
        if widget_kind == "history":
            rows = [
                ("Harbour Lights S03E04", "German"),
                ("The Quiet Harbour", "English"),
                ("Northern Shore S01E02", "German, English"),
                ("Copper Sky", "Dutch"),
            ]
            return WidgetData(
                items=[{"title": title, "subtitle": language, "status": "ok"} for title, language in rows],
                secondary=[{"label": "Entries", "value": len(rows)}],
            )
        rows = [
            ("Harbour Lights S03E05", "German"),
            ("Signal Lost S02E01", "German, English"),
            ("Copper Sky", "English"),
            ("Northern Shore S01E07", "German"),
        ]
        return WidgetData(
            status="warn",
            items=[{"title": title, "subtitle": language, "status": "warn"} for title, language in rows],
            secondary=[{"label": "Missing subtitles", "value": episodes + movies}],
            metrics={"wanted": float(episodes + movies)},
        )


ADAPTER = BazarrAdapter()
