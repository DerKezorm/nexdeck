"""Hacker News: the front page, without a key and in one request.

Two ways lead to the same stories. The official Firebase API hands out a list
of ids and then wants one request per story, twenty for a card. Algolia, which
runs the site's own search, answers the whole page at once. That is the one
used here.
"""

from __future__ import annotations

from typing import Any

from .base import Adapter, Context, Field, WidgetData, WidgetType

API = "https://hn.algolia.com/api/v1"
#: What the four lists are called at Algolia, and how they are asked for.
LISTS = {
    "front_page": ("search", "front_page"),
    "new": ("search_by_date", "story"),
    "ask": ("search", "ask_hn"),
    "show": ("search", "show_hn"),
}
SOURCES = (("front_page", "Front page"), ("new", "Newest"), ("ask", "Ask HN"), ("show", "Show HN"))


class HackerNewsAdapter(Adapter):
    kind = "hackernews"
    label = "Hacker News"
    category = "feeds"
    description = "The front page, newest, Ask HN or Show HN."
    icon = "hacker-news"
    docs_url = "https://hn.algolia.com/api"
    needs_integration = False
    widgets = (
        WidgetType(
            kind="stories",
            label="Stories",
            description="One line per story with points and comments.",
            renderer="feed",
            default_size=(4, 4),
            refresh_seconds=900,
            options=(
                Field("source", "List", type="select", default="front_page", options=SOURCES),
                Field("limit", "Entries", type="number", default=10),
                Field("min_points", "From this many points", type="number", default=0),
            ),
        ),
    )

    def default_link(self, config: dict[str, Any]) -> str:
        return "https://news.ycombinator.com/"

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        payload = await ctx.get_json(f"{API}/search", params={"tags": "front_page", "hitsPerPage": 1}, cache_seconds=0)
        return f"Hacker News answers with {int((payload or {}).get('nbHits') or 0)} stories on the front page."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        limit = max(1, min(30, int(options.get("limit") or 10)))
        floor = int(options.get("min_points") or 0)
        path, tag = LISTS.get(str(options.get("source") or "front_page"), LISTS["front_page"])
        payload = await ctx.get_json(
            f"{API}/{path}",
            params={"tags": tag, "hitsPerPage": limit * 2 if floor else limit},
            cache_seconds=600,
        )
        items = []
        for hit in (payload or {}).get("hits") or []:
            points = int(hit.get("points") or 0)
            if points < floor:
                continue
            identifier = str(hit.get("objectID") or "")
            comments = int(hit.get("num_comments") or 0)
            items.append({
                "title": hit.get("title") or hit.get("story_title") or "(untitled)",
                # A story without a link is a text post; then the discussion is the story.
                "url": hit.get("url") or f"https://news.ycombinator.com/item?id={identifier}",
                "source": f"{points} points · {comments} comments",
                "published": int(hit.get("created_at_i") or 0) or None,
                "summary": "",
                "image": "",
            })
            if len(items) >= limit:
                break
        return WidgetData(items=items, meta={"style": "list", "failures": []})

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        stories = [
            ("Show HN: I put my whole homelab on one page", 412, 96),
            ("The case against microservices for two people", 388, 214),
            ("SQLite is all most dashboards need", 301, 88),
            ("Writing a DNS server in 400 lines", 265, 41),
            ("Why your backups are not backups", 233, 130),
            ("A field guide to home network segmentation", 190, 37),
            ("Ask HN: what runs on your always-on machine?", 154, 302),
            ("The forgotten art of the status page", 121, 24),
        ]
        start = tick // 90
        items = []
        # Stop at the end of the list: wrapping put the same story on the
        # card twice, which reads like a bug in the service.
        for index in range(min(len(stories), max(1, min(30, int(options.get("limit") or 10))))):
            title, points, comments = stories[(start + index) % len(stories)]
            items.append({
                "title": title,
                "url": "https://news.ycombinator.com/item?id=1",
                "source": f"{points} points · {comments} comments",
                "published": 1788600000 - index * 3600 - tick,
                "summary": "",
                "image": "",
            })
        return WidgetData(items=items, meta={"style": "list", "failures": []})


ADAPTER = HackerNewsAdapter()
