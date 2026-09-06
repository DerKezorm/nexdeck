"""YouTube: the newest videos of a few channels, without a key.

Every channel has an Atom feed at ``/feeds/videos.xml?channel_id=UC...``, and
that needs neither an account nor a quota. The catch is the handle: a card
should take ``@handle`` too, and the feed does not. The channel page carries
the id, so it is fetched once and remembered.
"""

from __future__ import annotations

import asyncio
import calendar
import re
from typing import Any

import feedparser

from .base import Adapter, AdapterError, Context, Field, WidgetData, WidgetType

FEED = "https://www.youtube.com/feeds/videos.xml"

#: The canonical link is this channel and nothing else.
#:
#: ⚠️ ``"channelId"`` appears several times on a channel page and the first one
#: belongs to a recommended video, not to the channel. Reading it gave a
#: perfectly valid feed of the wrong person.
CANONICAL = re.compile(r'<link\s+rel="canonical"\s+href="https://www\.youtube\.com/channel/(UC[\w-]{20,})"')
EXTERNAL_ID = re.compile(r'"externalId"\s*:\s*"(UC[\w-]{20,})"')

#: ⚠️ From an EU address the channel page is the consent wall: 580 kB of
#: "Before you continue to YouTube" with no id in it. This cookie is what a
#: browser sets when someone clicks through, and it is enough. No account and
#: no key; the User-Agent makes no difference either way.
CONSENT = {"Cookie": "SOCS=CAI"}

#: Ready-made sets, so a card shows something before anything is typed.
PRESETS = {
    "selfhosted": "@TechnoTim\n@ChristianLempa\n@JeffGeerling",
    "networking": "@NetworkChuck\n@LawrenceSystems",
    "": "",
}
PRESET_OPTIONS = (
    ("selfhosted", "Self-hosting and homelab"),
    ("networking", "Network and infrastructure"),
    ("", "Own list only"),
)


class YoutubeAdapter(Adapter):
    kind = "youtube"
    label = "YouTube"
    category = "feeds"
    description = "The newest videos of the channels you follow."
    icon = "youtube"
    docs_url = "https://support.google.com/youtube/answer/6224202"
    needs_integration = False
    widgets = (
        WidgetType(
            kind="videos",
            label="Videos",
            description="Newest videos with their thumbnails, newest first.",
            renderer="feed",
            default_size=(4, 4),
            refresh_seconds=1800,
            options=(
                Field("preset", "Ready-made set", type="select", default="selfhosted", options=PRESET_OPTIONS),
                Field("channels", "Own channels", type="textarea", placeholder="@handle or UC...",
                      help="One per line. A handle with @, or the channel ID starting with UC. Replaces the ready-made set."),
                Field("limit", "Entries", type="number", default=8),
                Field("style", "Style", type="select", default="cards", options=(("cards", "Cards with images"), ("list", "List"))),
            ),
        ),
    )

    def default_link(self, config: dict[str, Any]) -> str:
        return "https://www.youtube.com/feed/subscriptions"

    @staticmethod
    def _channels(options: dict[str, Any]) -> list[str]:
        own = [line.strip() for line in str(options.get("channels") or "").splitlines() if line.strip()]
        if own:
            return own[:8]
        preset = PRESETS.get(str(options.get("preset") or "selfhosted"), "")
        return [line for line in preset.splitlines() if line][:8]

    async def _channel_id(self, ctx: Context, name: str) -> str:
        """A handle turned into the id the feed wants, looked up once."""
        if name.startswith("UC") and len(name) >= 22:
            return name
        cached = ctx.cache.get(f"yt:{name}")
        if cached:
            return str(cached)
        handle = name if name.startswith("@") else f"@{name}"
        response = await ctx.request("GET", f"https://www.youtube.com/{handle}", headers=CONSENT, cache_seconds=86400, timeout=20)
        if response.status_code >= 400:
            raise AdapterError(f"YouTube does not know {handle}.", code="not_found")
        found = CANONICAL.search(response.text) or EXTERNAL_ID.search(response.text)
        if not found:
            raise AdapterError(
                f"The channel ID of {handle} could not be read.",
                code="no_channel_id",
                hint="Enter the ID starting with UC instead. Open the channel, choose Share, and the address ends in it.",
            )
        ctx.cache[f"yt:{name}"] = found.group(1)
        return found.group(1)

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        response = await ctx.request("GET", FEED, params={"channel_id": "UCBJycsmduvYEL83R_U4JriQ"}, cache_seconds=0, timeout=20)
        if response.status_code >= 400:
            raise AdapterError(f"YouTube answered with HTTP {response.status_code}.", code="http_error")
        return "YouTube hands out its channel feeds."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        names = self._channels(options)
        if not names:
            raise AdapterError("No channel is set.", code="missing_channel")
        limit = max(1, min(30, int(options.get("limit") or 8)))
        entries: list[dict[str, Any]] = []
        failures: list[str] = []
        for name in names:
            try:
                channel = await self._channel_id(ctx, name)
                response = await ctx.request("GET", FEED, params={"channel_id": channel}, cache_seconds=1800, timeout=20)
                if response.status_code >= 400:
                    raise AdapterError(f"HTTP {response.status_code}", code="http_error")
                parsed = await asyncio.to_thread(feedparser.parse, response.content)
            except AdapterError as error:
                failures.append(f"{name}: {error.message}")
                continue
            source = parsed.feed.get("title", name)
            for entry in parsed.entries:
                published = entry.get("published_parsed") or entry.get("updated_parsed")
                thumbnail = ""
                for media in entry.get("media_thumbnail", []) or []:
                    if media.get("url"):
                        thumbnail = media["url"]
                        break
                entries.append({
                    "title": entry.get("title", "(untitled)"),
                    "url": entry.get("link", ""),
                    "source": source,
                    "published": calendar.timegm(published) if published else None,
                    "summary": "",
                    "image": thumbnail,
                })
        entries.sort(key=lambda entry: entry["published"] or 0, reverse=True)
        return WidgetData(
            status="ok" if entries else ("bad" if failures else "warn"),
            items=entries[:limit],
            meta={"style": options.get("style") or "cards", "failures": failures},
            error=("; ".join(failures) if failures and not entries else None),
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        videos = [
            ("I replaced my cloud with one small box", "Homelab Diary"),
            ("Ten containers every home server should run", "Self-hosted Weekly"),
            ("This switch is silent and I am shocked", "Rack Notes"),
            ("Proxmox backups done properly", "Virtualisation Corner"),
            ("Why I moved off the big media services", "Media at Home"),
            ("A dashboard that actually gets used", "Desk Setup"),
        ]
        start = tick // 120
        items = []
        for index in range(min(len(videos), max(1, min(30, int(options.get("limit") or 8))))):
            title, source = videos[(start + index) % len(videos)]
            items.append({
                "title": title,
                "url": "https://www.youtube.com/watch?v=lab",
                "source": source,
                "published": 1788600000 - index * 43200 - tick,
                "summary": "",
                "image": "",
            })
        return WidgetData(items=items, meta={"style": options.get("style") or "cards", "failures": []})


ADAPTER = YoutubeAdapter()
