"""Radarr: movies."""

from __future__ import annotations

from typing import Any

from .arr_base import ArrAdapter


class RadarrAdapter(ArrAdapter):
    kind = "radarr"
    #: Confirmed against a live instance on 2026-09-05.
    beta = False
    label = "Radarr"
    category = "downloads"
    description = "Queue, calendar, missing movies and health."
    icon = "radarr"
    docs_url = "https://radarr.video/docs/api/"
    noun = "movie"
    list_path = "movie"
    demo_titles = ("The Quiet Harbour (2026)", "Orbital (2025)", "Nightshift (2026)", "Copper Sky (2025)", "The Last Ferry (2026)", "Paper Towns of Mars (2026)")

    def queue_title(self, entry: dict[str, Any]) -> str:
        movie = entry.get("movie") or {}
        return movie.get("title") or entry.get("title") or "?"

    def calendar_item(self, entry: dict[str, Any]) -> dict[str, Any] | None:
        date = entry.get("digitalRelease") or entry.get("physicalRelease") or entry.get("inCinemas")
        if not date:
            return None
        return {
            "date": str(date)[:10],
            "title": entry.get("title", "?"),
            "subtitle": "Digital release" if entry.get("digitalRelease") else "Release",
            "status": "ok" if entry.get("hasFile") else "warn",
        }


ADAPTER = RadarrAdapter()
