"""YouTube: the newest videos of a few channels, without a key.

Every channel has an Atom feed at ``/feeds/videos.xml?channel_id=UC...``, and
that needs neither an account nor a quota. The catch is the handle: a card
should take ``@handle`` too, and the feed does not. The channel page carries
the id, so it is fetched once and remembered.

The Subscriptions card is the one place a key comes in. YouTube serves no
home feed to any API; what is left, and what most people mean by it, is the
channels an account follows. That list comes from the Data API with a key,
once a day, and the videos from the same free feeds as above.
"""

from __future__ import annotations

import asyncio
import calendar
import re
from typing import Any

import feedparser

from .base import Adapter, AdapterError, AuthFailed, Context, Field, WidgetData, WidgetType

FEED = "https://www.youtube.com/feeds/videos.xml"
API = "https://www.googleapis.com/youtube/v3"

#: One page of the Data API, and the most channels the card reads.
MOST_CHANNELS = 50
#: Feeds asked at the same time. Fifty one after another took long enough to
#: run into the collector's minute.
AT_ONCE = 6

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
    optional_integration = True
    fields = (
        Field("api_key", "API key", type="password", secret=True,
              help="Only for the Subscriptions card: a key for the YouTube Data API v3 from the Google Cloud console. The Videos card needs none."),
    )
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
        WidgetType(
            kind="subscriptions",
            label="Subscriptions",
            description="Newest videos of the channels an account follows. Needs a connection with an API key, and the account's subscriptions have to be public.",
            renderer="feed",
            default_size=(4, 4),
            refresh_seconds=1800,
            options=(
                Field("account", "Account", placeholder="@handle or UC...",
                      help="The channel whose subscriptions are read, as a handle with @ or the ID starting with UC."),
                Field("channels_read", "Channels read", type="number", default=25,
                      help="The most active first, at most 50. The list is read once a day; each channel is one free feed."),
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
        if str(config.get("api_key") or "").strip():
            # One unit of the daily quota, and it says whether the key is good.
            await self._api(config, ctx, "channels", {"part": "id", "id": "UCBJycsmduvYEL83R_U4JriQ"}, cache=0)
            return "YouTube accepts the API key."
        response = await ctx.request("GET", FEED, params={"channel_id": "UCBJycsmduvYEL83R_U4JriQ"}, cache_seconds=0, timeout=20)
        if response.status_code >= 400:
            raise AdapterError(f"YouTube answered with HTTP {response.status_code}.", code="http_error")
        return "YouTube hands out its channel feeds."

    async def _api(self, config: dict[str, Any], ctx: Context, path: str, params: dict[str, Any], cache: float = 86400) -> dict[str, Any]:
        """One call to the Data API.

        ⚠️ The key travels in the X-Goog-Api-Key header, not as ``key=`` in the
        address: every request's address goes into the log, and nexdeck's log
        can be downloaded from System.
        """
        key = str(config.get("api_key") or "").strip()
        if not key:
            raise AdapterError(
                "This card needs a YouTube connection with an API key.", code="missing_key",
                hint="Add YouTube under Connections with a key for the YouTube Data API v3, then pick it on this card.",
            )
        response = await ctx.request("GET", f"{API}/{path}", params=params, headers={"X-Goog-Api-Key": key},
                                     cache_seconds=cache, timeout=20, auth_errors=False)
        if response.status_code >= 400:
            raise refusal(response)
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if not isinstance(payload, dict):
            raise AdapterError("YouTube answered with something that is not JSON.", code="bad_answer")
        return payload

    async def _followed(self, config: dict[str, Any], ctx: Context, account: str, wanted: int) -> list[tuple[str, str]]:
        """The channels an account follows, the most active first: (id, name)."""
        channel = await self._channel_id(ctx, account)
        page = await self._api(config, ctx, "subscriptions",
                               {"part": "snippet", "channelId": channel, "maxResults": wanted, "order": "unread"})
        followed = []
        for item in page.get("items") or []:
            snippet = item.get("snippet") if isinstance(item, dict) else None
            target = (snippet or {}).get("resourceId") or {}
            if isinstance(target, dict) and target.get("channelId"):
                followed.append((str(target["channelId"]), str((snippet or {}).get("title") or target["channelId"])))
        return followed[:wanted]

    async def _videos(self, ctx: Context, channels: list[tuple[str, str]], failures: list[str]) -> list[dict[str, Any]]:
        """The newest videos of each channel from its feed, a few feeds at a time."""
        gate = asyncio.Semaphore(AT_ONCE)

        async def one(channel: str, name: str) -> list[dict[str, Any]]:
            async with gate:
                response = await ctx.request("GET", FEED, params={"channel_id": channel}, cache_seconds=1800, timeout=20)
                if response.status_code >= 400:
                    raise AdapterError(f"HTTP {response.status_code}", code="http_error")
                parsed = await asyncio.to_thread(feedparser.parse, response.content)
            source = parsed.feed.get("title", name)
            found = []
            for entry in parsed.entries:
                published = entry.get("published_parsed") or entry.get("updated_parsed")
                thumbnail = ""
                for media in entry.get("media_thumbnail", []) or []:
                    if media.get("url"):
                        thumbnail = media["url"]
                        break
                found.append({
                    "title": entry.get("title", "(untitled)"),
                    "url": entry.get("link", ""),
                    "source": source,
                    "published": calendar.timegm(published) if published else None,
                    "summary": "",
                    "image": thumbnail,
                })
            return found

        entries: list[dict[str, Any]] = []
        answers = await asyncio.gather(*(one(channel, name) for channel, name in channels), return_exceptions=True)
        for (_channel, name), answer in zip(channels, answers, strict=True):
            if isinstance(answer, AdapterError):
                failures.append(f"{name}: {answer.message}")
            elif isinstance(answer, BaseException):
                raise answer
            else:
                entries.extend(answer)
        return entries

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        limit = max(1, min(30, int(options.get("limit") or 8)))
        failures: list[str] = []
        if widget_kind == "subscriptions":
            account = str(options.get("account") or "").strip()
            if not account:
                raise AdapterError("No account is set.", code="missing_account", hint="Enter the channel whose subscriptions the card reads.")
            try:
                wanted = max(1, min(MOST_CHANNELS, int(options.get("channels_read") or 25)))
            except (TypeError, ValueError):
                wanted = 25
            channels = await self._followed(config, ctx, account, wanted)
        else:
            names = self._channels(options)
            if not names:
                raise AdapterError("No channel is set.", code="missing_channel")
            channels = []
            for name in names:
                try:
                    channels.append((await self._channel_id(ctx, name), name))
                except AdapterError as error:
                    failures.append(f"{name}: {error.message}")
        entries = await self._videos(ctx, channels, failures)
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


def refusal(response: Any) -> AdapterError:
    """What a refusal of the Data API means, in words somebody can act on."""
    try:
        error = response.json().get("error") or {}
    except (ValueError, AttributeError):
        error = {}
    reasons = {str(one.get("reason")) for one in error.get("errors") or [] if isinstance(one, dict)}
    reasons |= {str(one.get("reason")) for one in error.get("details") or [] if isinstance(one, dict)}
    if "subscriptionForbidden" in reasons:
        return AdapterError("YouTube keeps this account's subscriptions private.", code="subscriptions_private",
                            hint='On YouTube: Settings, Privacy, and switch off "Keep all my subscriptions private". Or name the channels on a Videos card.')
    if reasons & {"quotaExceeded", "dailyLimitExceeded", "RATE_LIMIT_EXCEEDED"}:
        return AdapterError("The API key has used up its daily quota.", code="quota",
                            hint="The card reads the list once a day; the quota comes back at midnight Pacific time.")
    if reasons & {"accessNotConfigured", "SERVICE_DISABLED"}:
        return AdapterError("The YouTube Data API is not switched on for this key's project.", code="api_disabled",
                            hint="In the Google Cloud console: APIs and services, enable YouTube Data API v3.")
    if reasons & {"keyInvalid", "API_KEY_INVALID", "keyExpired", "API_KEY_EXPIRED"}:
        return AuthFailed("YouTube refused the API key.")
    if reasons & {"subscriberNotFound", "channelNotFound"} or response.status_code == 404:
        return AdapterError("YouTube does not know this channel.", code="not_found")
    message = str(error.get("message") or "").strip()
    return AdapterError(f"YouTube answered with HTTP {response.status_code}" + (f": {message}" if message else "."), code="http_error")


ADAPTER = YoutubeAdapter()
