"""Sonarr: series and episodes."""

from __future__ import annotations

from typing import Any

from .arr_base import ArrAdapter
from .ical import at_moment


class SonarrAdapter(ArrAdapter):
    kind = "sonarr"
    #: Confirmed against a live instance on 2026-09-05.
    beta = False
    label = "Sonarr"
    category = "downloads"
    description = "Queue, upcoming episodes, missing episodes and health."
    icon = "sonarr"
    docs_url = "https://sonarr.tv/docs/api/"
    noun = "series"
    list_path = "series"
    demo_titles = ("Harbour Lights S03E04", "Orbital Decay S01E08", "The Archive S02E01", "Slow Horses S05E02", "Northern Shore S01E03", "Signal Lost S02E06")

    def noun_plural(self) -> str:
        return "series"

    def has_file(self, entry: dict[str, Any]) -> bool:
        stats = entry.get("statistics") or {}
        return stats.get("episodeFileCount", 0) >= stats.get("episodeCount", 0)

    def queue_title(self, entry: dict[str, Any]) -> str:
        series = (entry.get("series") or {}).get("title")
        episode = entry.get("episode") or {}
        code = ""
        if episode.get("seasonNumber") is not None:
            code = f" S{int(episode['seasonNumber']):02d}E{int(episode.get('episodeNumber', 0)):02d}"
        return f"{series}{code}" if series else entry.get("title") or "?"

    def calendar_item(self, entry: dict[str, Any]) -> dict[str, Any] | None:
        # The moment it airs, so the card can put it on the viewer's own day
        # (#56); airDate alone is the day where the network is, and has no time.
        when = at_moment(entry.get("airDateUtc"))
        if when is None and not entry.get("airDate"):
            return None
        series = (entry.get("series") or {}).get("title", "?")
        return {
            **(when or {"date": str(entry["airDate"])[:10]}),
            "title": series,
            "subtitle": f"S{int(entry.get('seasonNumber', 0)):02d}E{int(entry.get('episodeNumber', 0)):02d} {entry.get('title', '')}".strip(),
            "status": "ok" if entry.get("hasFile") else "warn",
        }

    def missing_command(self) -> str:
        return "MissingEpisodeSearch"


ADAPTER = SonarrAdapter()
