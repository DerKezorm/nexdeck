"""RSS and Atom feeds, fetched and cached by the server."""

from __future__ import annotations

import asyncio
import calendar
from typing import Any

import feedparser

from .base import Adapter, AdapterError, Context, Field, WidgetData, WidgetType, guard_member_target


class RssAdapter(Adapter):
    kind = "rss"
    label = "RSS feeds"
    category = "basics"
    description = "Headlines from one or more RSS or Atom feeds."
    icon = "lucide:rss"
    beta = False
    needs_integration = False
    widgets = (
        WidgetType(
            kind="headlines",
            label="Feed",
            description="Latest entries, newest first.",
            renderer="feed",
            default_size=(4, 3),
            refresh_seconds=900,
            options=(
                Field("urls", "Feed URLs", type="textarea", required=True, help="One per line.", placeholder="https://example.com/feed.xml"),
                Field("limit", "Entries", type="number", default=10),
                Field("images", "Show images", type="bool", default=True),
                Field("style", "Style", type="select", default="list", options=(("list", "List"), ("cards", "Cards with images"))),
            ),
        ),
    )

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        return "Nothing to test."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        urls = [u.strip() for u in str(options.get("urls") or "").splitlines() if u.strip()]
        if not urls:
            raise AdapterError("No feed URL is set.", code="missing_url")
        limit = max(1, min(50, int(options.get("limit") or 10)))
        entries: list[dict[str, Any]] = []
        failures: list[str] = []
        for url in urls:
            # ⚠️ The one adapter whose address lives in the widget options
            # instead of in a connection an administrator made, so the person
            # who may edit a board decides where the server goes.
            guard_member_target(url)
            try:
                # ``member`` puts the same rule on every hop of a redirect.
                response = await ctx.request("GET", url, cache_seconds=600, timeout=20, member=True)
                parsed = await asyncio.to_thread(feedparser.parse, response.content)
            except AdapterError as error:
                failures.append(f"{url}: {error.message}")
                continue
            source = parsed.feed.get("title", url)
            for entry in parsed.entries:
                published = entry.get("published_parsed") or entry.get("updated_parsed")
                image = ""
                for media in entry.get("media_content", []) or entry.get("media_thumbnail", []):
                    if media.get("url"):
                        image = media["url"]
                        break
                if not image:
                    for enclosure in entry.get("enclosures", []) or []:
                        if str(enclosure.get("type", "")).startswith("image/"):
                            image = enclosure.get("href", "")
                            break
                entries.append({
                    "title": entry.get("title", "(untitled)"),
                    "url": entry.get("link", ""),
                    "source": source,
                    "published": calendar.timegm(published) if published else None,
                    "summary": _strip(entry.get("summary", ""))[:280],
                    "image": image if options.get("images", True) else "",
                })
        entries.sort(key=lambda e: e["published"] or 0, reverse=True)
        status = "ok" if entries else ("bad" if failures else "warn")
        return WidgetData(
            status=status,
            items=entries[:limit],
            meta={"style": options.get("style") or "list", "failures": failures},
            error=("; ".join(failures) if failures and not entries else None),
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        headlines = [
            ("New release: nexdeck 0.1.0 brings live boards", "nexapps blog"),
            ("Why your NAS deserves a real dashboard", "Homelab Weekly"),
            ("Proxmox 9.1: what changed for LXC networking", "Virtualisation News"),
            ("A cheap 10G switch that does not sound like a jet", "Rack Notes"),
            ("Jellyfin adds trickplay by default", "Media Server Digest"),
            ("Backups: the 3-2-1 rule, revisited", "Storage Journal"),
            ("Home Assistant 2026.9 released", "Smart Home Today"),
            ("Pi-hole v6 API deep dive", "DNS Corner"),
        ]
        start = tick // 120
        items = []
        for index in range(int(options.get("limit") or 8)):
            title, source = headlines[(start + index) % len(headlines)]
            items.append({
                "title": title, "url": "https://example.com/post", "source": source,
                "published": 1788500000 - index * 5400 - tick, "summary": "A short summary of the article would appear here.",
                "image": "",
            })
        return WidgetData(items=items, meta={"style": options.get("style") or "list", "failures": []})


def _strip(html: str) -> str:
    import re

    return re.sub(r"<[^>]+>", "", html or "").strip()


ADAPTER = RssAdapter()
