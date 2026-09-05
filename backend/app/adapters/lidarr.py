"""Lidarr: music."""

from __future__ import annotations

from typing import Any

from .arr_base import ArrAdapter


class LidarrAdapter(ArrAdapter):
    kind = "lidarr"
    #: Confirmed against a live instance on 2026-09-05.
    beta = False
    label = "Lidarr"
    category = "downloads"
    description = "Queue, upcoming albums and health."
    icon = "lidarr"
    api_version = "v1"
    noun = "artist"
    list_path = "artist"
    demo_titles = ("Tides - Low Water", "Northern Lights - EP", "Copper Sky - Live", "Orbital - Remixes")

    def has_file(self, entry: dict[str, Any]) -> bool:
        stats = entry.get("statistics") or {}
        return stats.get("percentOfTracks", 0) >= 100

    def queue_title(self, entry: dict[str, Any]) -> str:
        artist = (entry.get("artist") or {}).get("artistName")
        album = (entry.get("album") or {}).get("title")
        return f"{artist} - {album}" if artist and album else entry.get("title") or "?"

    def calendar_item(self, entry: dict[str, Any]) -> dict[str, Any] | None:
        date = entry.get("releaseDate")
        if not date:
            return None
        return {
            "date": str(date)[:10],
            "title": (entry.get("artist") or {}).get("artistName", "?"),
            "subtitle": entry.get("title", ""),
            "status": "ok" if (entry.get("statistics") or {}).get("percentOfTracks", 0) >= 100 else "warn",
        }

    def missing_command(self) -> str:
        return "MissingAlbumSearch"


ADAPTER = LidarrAdapter()
