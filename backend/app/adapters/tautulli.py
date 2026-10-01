"""Tautulli: what is playing on Plex, and what was watched most.

nexdeck reads Plex itself and goes deeper, but Tautulli is what most people
have running, and they want its numbers on the board. Its API is one address
with a ``cmd`` parameter and an API key in the query string.
"""

from __future__ import annotations

from typing import Any

from . import demo as fake
from .base import (
    Adapter,
    AdapterError,
    Context,
    Field,
    WidgetData,
    WidgetType,
    base_url,
    human_bytes,
)

#: What the "Most watched" card shows, and the group of ``get_home_stats``
#: that holds it. Tautulli answers every group in one reply.
_TOP_STAT = {"titles": "top_movies", "shows": "top_tv", "music": "top_music", "users": "top_users"}


def _days(options: dict[str, Any]) -> int:
    try:
        return max(7, min(366, int(options.get("days") or 91)))
    except (TypeError, ValueError):
        return 91


def heat_of(graph: Any, hours: bool) -> WidgetData:
    """One square per day from Tautulli's graph by date: the series (TV,
    Movies, Music, Live TV) are added up, since a day is one square.

    ``duration`` comes in seconds and is shown in hours.
    """
    graph = graph if isinstance(graph, dict) else {}
    categories = [str(one) for one in graph.get("categories") or []]
    totals = [0.0] * len(categories)
    for series in graph.get("series") or []:
        for index, value in enumerate((series or {}).get("data") or []):
            if index < len(totals) and isinstance(value, (int, float)):
                totals[index] += float(value)
    if hours:
        totals = [round(value / 3600, 1) for value in totals]
    days = [[day, int(value) if not hours else value] for day, value in zip(categories, totals, strict=True)]
    total = sum(value for _day, value in days)
    busiest = max(days, key=lambda pair: pair[1], default=None)
    secondary: list[dict[str, Any]] = [{"label": "Busiest day", "value": busiest[0]}] if busiest and busiest[1] else []
    return WidgetData(
        primary={"label": "Hours watched" if hours else "Plays", "value": round(total, 1) if hours else int(total)},
        secondary=secondary,
        meta={"heatmap": {"days": days, "unit": "h" if hours else ""}, "empty": "Nothing was played in these days."},
    )


class TautulliAdapter(Adapter):
    kind = "tautulli"
    #: Confirmed against a live instance on 2026-09-07.
    beta = False
    label = "Tautulli"
    category = "media"
    description = "Streams with who is watching, library counts and the most watched titles."
    icon = "tautulli"
    docs_url = "https://github.com/Tautulli/Tautulli/wiki/Tautulli-API-Reference"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://tautulli:8181"),
        Field("api_key", "API key", type="password", secret=True, required=True, help="Settings > Web interface > API key"),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(
            kind="activity",
            label="Now playing",
            description="Who is watching what, with the bandwidth it costs.",
            renderer="list",
            default_size=(4, 3),
            refresh_seconds=20,
            metrics=("streams", "bandwidth"),
        ),
        WidgetType(
            kind="counts",
            label="Streams",
            description="Streams, transcodes and bandwidth in one number.",
            renderer="value",
            default_size=(2, 2),
            min_size=(1, 1),
            refresh_seconds=20,
            metrics=("streams", "bandwidth"),
        ),
        WidgetType(
            kind="top",
            bars=True,
            label="Most watched",
            description="The titles and users of the last days.",
            renderer="list",
            default_size=(3, 3),
            refresh_seconds=900,
            options=(
                Field("days", "Days", type="number", default=7),
                # ``titles`` stays the key for movies: boards saved before TV shows
                # and music were offered carry it.
                Field("show", "Show", type="select", default="titles", options=(("titles", "Movies"), ("shows", "TV shows"), ("music", "Music"), ("users", "Users"))),
                Field("limit", "Entries", type="number", default=6),
            ),
        ),
        WidgetType(
            kind="days",
            label="Plays per day",
            description="Every day of the last weeks as a square, darker the more was played, the way GitHub draws contributions.",
            renderer="heatmap",
            default_size=(4, 2),
            refresh_seconds=1800,
            options=(
                Field("days", "Days", type="select", default="91",
                      options=(("35", "Five weeks"), ("91", "Thirteen weeks"), ("182", "Half a year"), ("364", "A year"))),
                Field("measure", "Count", type="select", default="plays",
                      options=(("plays", "Plays"), ("duration", "Hours watched"))),
            ),
        ),
    )

    async def _cmd(self, config: dict[str, Any], ctx: Context, command: str, params: dict[str, Any] | None = None, cache: float = 15) -> Any:
        query = {"apikey": str(config.get("api_key") or ""), "cmd": command, **(params or {})}
        payload = await ctx.get_json(
            f"{base_url(config)}/api/v2",
            params=query,
            verify=not config.get("insecure"),
            cache_seconds=cache,
        )
        response = (payload or {}).get("response") or {}
        if response.get("result") != "success":
            raise AdapterError(str(response.get("message") or "Tautulli refused the request."), code="http_error")
        return response.get("data")

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        version = await self._cmd(config, ctx, "get_server_info", cache=0)
        name = (version or {}).get("pms_name") or "Plex"
        return f"Tautulli answers and watches {name}."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "days":
            days = _days(options)
            hours = options.get("measure") == "duration"
            graph = await self._cmd(config, ctx, "get_plays_by_date",
                                    {"time_range": days, "y_axis": "duration" if hours else "plays"}, cache=1800)
            return heat_of(graph, hours)
        if widget_kind == "top":
            days = int(options.get("days") or 7)
            limit = int(options.get("limit") or 6)
            wanted = _TOP_STAT.get(str(options.get("show")), "top_movies")
            stats = await self._cmd(config, ctx, "get_home_stats", {"time_range": days, "stats_count": limit}, cache=600)
            rows: list[dict[str, Any]] = []
            for group in stats or []:
                if group.get("stat_id") != wanted:
                    continue
                for row in group.get("rows") or []:
                    plays = int(row.get("total_plays") or 0)
                    rows.append({
                        "title": row.get("friendly_name") or row.get("title") or "?",
                        "subtitle": row.get("year") and str(row.get("year")) or "",
                        "value": plays,
                        "status": "ok",
                    })
            return WidgetData(items=rows[:limit], secondary=[{"label": "Days", "value": days}])

        activity = await self._cmd(config, ctx, "get_activity", cache=10) or {}
        streams = int(activity.get("stream_count") or 0)
        transcodes = int(activity.get("stream_count_transcode") or 0)
        bandwidth = float(activity.get("total_bandwidth") or 0) * 1000  # Tautulli counts kbit/s
        if widget_kind == "counts":
            return WidgetData(
                status="warn" if transcodes >= 3 else "ok",
                primary={"label": "Streams", "value": streams},
                secondary=[
                    {"label": "Transcodes", "value": transcodes},
                    {"label": "Bandwidth", "value": human_bytes(bandwidth / 8) + "/s"},
                    {"label": "Direct play", "value": int(activity.get("stream_count_direct_play") or 0)},
                ],
                metrics={"streams": float(streams), "bandwidth": bandwidth},
            )

        items = []
        for session in activity.get("sessions") or []:
            decision = str(session.get("transcode_decision") or "")
            items.append({
                "title": session.get("full_title") or session.get("title") or "?",
                "subtitle": f"{session.get('friendly_name', '?')} · {session.get('player', '?')} · {decision}",
                # Who it is, apart from the line: showcase mode replaces the person and the player.
                "user": str(session.get("friendly_name") or ""),
                "progress": float(session.get("progress_percent") or 0),
                "value": f"{int(float(session.get('progress_percent') or 0))}%",
                "status": "warn" if decision == "transcode" else "ok",
            })
        return WidgetData(
            status="ok",
            items=items,
            secondary=[{"label": "Streams", "value": streams}, {"label": "Bandwidth", "value": human_bytes(bandwidth / 8) + "/s"}],
            metrics={"streams": float(streams), "bandwidth": bandwidth},
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        if widget_kind == "days":
            import math
            from datetime import date, timedelta

            days = _days(options)
            today = date.today()
            categories = [(today - timedelta(days=days - 1 - index)).isoformat() for index in range(days)]
            # Weekends and the evenings of a holiday stretch play more; a few days nothing at all.
            plays = []
            for index, day in enumerate(categories):
                weekday = date.fromisoformat(day).weekday()
                wave = 0.5 + 0.5 * math.sin(index / 9.0)
                plays.append(0 if (index * 7) % 23 == 0 else round((2 + 6 * wave) * (1.8 if weekday >= 4 else 1.0)))
            return heat_of({"categories": categories, "series": [{"name": "TV", "data": plays}]}, False)
        streams = int(fake.walk("tautulli-streams", tick, 0, 4))
        transcodes = 1 if streams >= 2 else 0
        bandwidth = streams * 12_000_000.0
        if widget_kind == "counts":
            return WidgetData(
                status="warn" if transcodes >= 3 else "ok",
                primary={"label": "Streams", "value": streams},
                secondary=[
                    {"label": "Transcodes", "value": transcodes},
                    {"label": "Bandwidth", "value": human_bytes(bandwidth / 8) + "/s"},
                    {"label": "Direct play", "value": max(0, streams - transcodes)},
                ],
                metrics={"streams": float(streams), "bandwidth": bandwidth},
            )
        if widget_kind == "top":
            rows = [("The Quiet Harbour", 14), ("Harbour Lights", 11), ("Northern Shore", 9), ("Copper Sky", 6), ("Signal Lost", 4)]
            if str(options.get("show")) == "users":
                rows = [("Alex", 42), ("Sam", 31), ("Kim", 18), ("Robin", 7)]
            elif str(options.get("show")) == "shows":
                rows = [("Harbour Lights", 23), ("Northern Shore", 17), ("The Long Watch", 9), ("Tidewater", 5)]
            elif str(options.get("show")) == "music":
                rows = [("The Copper Bells", 38), ("Low Tide", 21), ("Signal Lost", 12), ("Northern Choir", 6)]
            return WidgetData(
                items=[{"title": title, "subtitle": "", "value": plays, "status": "ok"} for title, plays in rows],
                secondary=[{"label": "Days", "value": int(options.get("days") or 7)}],
            )
        watchers = [("The Quiet Harbour", "Alex", "Living room", "direct play"), ("Harbour Lights S03E04", "Sam", "Bedroom TV", "transcode")]
        items = []
        for index, (title, who, player, decision) in enumerate(watchers[:max(1, streams)]):
            progress = (fake.walk(f"tautulli-p{index}", tick, 5, 95, period=300) + tick * 0.2) % 100
            items.append({
                "title": title,
                "subtitle": f"{who} · {player} · {decision}",
                "user": who,
                "progress": round(progress, 1),
                "value": f"{progress:.0f}%",
                "status": "warn" if decision == "transcode" else "ok",
            })
        return WidgetData(
            items=items if streams else [],
            secondary=[{"label": "Streams", "value": streams}, {"label": "Bandwidth", "value": human_bytes(bandwidth / 8) + "/s"}],
            metrics={"streams": float(streams), "bandwidth": bandwidth},
        )


ADAPTER = TautulliAdapter()
