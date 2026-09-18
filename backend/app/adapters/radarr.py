"""Radarr: movies."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .arr_base import ArrAdapter

#: Radarr's three dates of a movie and what the card calls each.
RELEASES = (("inCinemas", "In cinemas"), ("digitalRelease", "Digital release"), ("physicalRelease", "Physical release"))


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
        # ⚠️ The next of the three dates, not the digital one first. Radarr puts
        # a movie in the calendar when any of its dates falls in the window,
        # and the card used to show the digital release whenever there was
        # one: Toy Story 5 read "18 August, digital release" on 18 September,
        # listed because its physical release was on the 22nd. Issue #8.
        dates = sorted(
            (str(entry[key])[:10], label) for key, label in RELEASES if entry.get(key)
        )
        if not dates:
            return None
        today = datetime.now(UTC).date().isoformat()
        # All of them past only happens outside the calendar's window; the
        # last one is then the nearest.
        date, label = next((one for one in dates if one[0] >= today), dates[-1])
        return {
            "date": date,
            "title": entry.get("title", "?"),
            "subtitle": label,
            "status": "ok" if entry.get("hasFile") else "warn",
        }


ADAPTER = RadarrAdapter()
