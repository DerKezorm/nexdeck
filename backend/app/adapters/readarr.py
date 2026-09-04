"""Readarr: books."""

from __future__ import annotations

from typing import Any

from .arr_base import ArrAdapter


class ReadarrAdapter(ArrAdapter):
    kind = "readarr"
    label = "Readarr"
    category = "downloads"
    description = "Queue, upcoming books and health."
    icon = "readarr"
    api_version = "v1"
    noun = "author"
    list_path = "author"
    demo_titles = ("The Quiet Harbour", "Orbital Decay", "A Field Guide to Nothing", "Copper Sky")

    def has_file(self, entry: dict[str, Any]) -> bool:
        stats = entry.get("statistics") or {}
        return stats.get("percentOfBooks", 0) >= 100

    def queue_title(self, entry: dict[str, Any]) -> str:
        author = (entry.get("author") or {}).get("authorName")
        book = (entry.get("book") or {}).get("title")
        return f"{author} - {book}" if author and book else entry.get("title") or "?"

    def calendar_item(self, entry: dict[str, Any]) -> dict[str, Any] | None:
        date = entry.get("releaseDate")
        if not date:
            return None
        return {
            "date": str(date)[:10],
            "title": entry.get("title", "?"),
            "subtitle": (entry.get("author") or {}).get("authorName", ""),
            "status": "ok" if (entry.get("statistics") or {}).get("bookFileCount", 0) else "warn",
        }

    def missing_command(self) -> str:
        return "MissingBookSearch"


ADAPTER = ReadarrAdapter()
