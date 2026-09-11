"""Miniflux: what is unread, and which feeds fail to fetch.

Measured against Miniflux 2.3.3 on 11.09.2026.

The unread count comes with the entries: ``/v1/entries?status=unread``
answers with ``total`` beside the page, so one entry is enough to know how
many there are. ``/v1/feeds/counters`` would have to be added up per feed.

⚠️ Miniflux answers 500, not 400, when an address is not a feed. A 500 from
it is therefore not necessarily a broken server.
"""

from __future__ import annotations

import time
from typing import Any

from . import demo as fake
from .base import (
    Adapter,
    AdapterError,
    AuthFailed,
    Context,
    Field,
    WidgetData,
    WidgetType,
    ago,
    base_url,
)


class MinifluxAdapter(Adapter):
    kind = "miniflux"
    label = "Miniflux"
    category = "feeds"
    description = "What is unread in your feed reader, and which feeds fail to fetch."
    icon = "miniflux"
    beta = False
    docs_url = "https://miniflux.app/docs/api.html"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://miniflux:8080"),
        Field("api_key", "API key", type="password", secret=True, required=True,
              help="Settings > API Keys > Create a new API key."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(kind="unread", label="Unread", description="The newest unread entries with their feed.",
                   renderer="list", default_size=(3, 3), refresh_seconds=300, metrics=("unread",),
                   options=(Field("limit", "Entries", type="number", default=8),
                            Field("starred", "Only starred entries", type="bool", default=False))),
        WidgetType(kind="failing", label="Failing feeds", description="Feeds Miniflux could not fetch, with the reason.",
                   renderer="list", default_size=(3, 2), refresh_seconds=600, metrics=("failing",),
                   options=(Field("limit", "Entries", type="number", default=6),)),
        WidgetType(kind="summary", label="Feed reader", description="How much is unread, and how many feeds fail.",
                   renderer="value", default_size=(2, 2), refresh_seconds=300, metrics=("unread", "failing")),
    )

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, params: dict[str, Any] | None = None,
                   cache: float = 10) -> Any:
        response = await ctx.request(
            "GET", f"{base_url(config)}/v1{path}", headers={"X-Auth-Token": str(config.get("api_key") or "")},
            params=params, verify=not config.get("insecure"), cache_seconds=cache, auth_errors=False,
        )
        # Measured: a wrong and a missing key both get 401 "access unauthorized".
        if response.status_code in (401, 403):
            raise AuthFailed("Miniflux rejected the API key.")
        if response.status_code >= 400:
            raise AdapterError(f"Miniflux answered with HTTP {response.status_code}.", code="http_error",
                               hint="Check the URL; it is the address of Miniflux itself, without /v1.")
        try:
            return response.json()
        except ValueError as error:
            raise AdapterError("Miniflux did not answer with JSON.", code="not_json",
                               hint="The URL probably points at a login page or a reverse proxy.") from error

    async def _entries(self, config: dict[str, Any], ctx: Context, limit: int, starred: bool = False) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": max(1, limit), "order": "published_at", "direction": "desc"}
        # Starred entries are worth showing whether they have been read or not.
        params.update({"starred": "true"} if starred else {"status": "unread"})
        answer = await self._get(config, ctx, "/entries", params=params)
        if not isinstance(answer, dict) or not isinstance(answer.get("entries"), list):
            raise AdapterError("This address answers, but not the way Miniflux does.", code="not_miniflux")
        return answer

    async def _feeds(self, config: dict[str, Any], ctx: Context) -> list[dict[str, Any]]:
        answer = await self._get(config, ctx, "/feeds")
        if not isinstance(answer, list):
            raise AdapterError("This address answers, but not the way Miniflux does.", code="not_miniflux")
        return [feed for feed in answer if isinstance(feed, dict)]

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        me = await self._get(config, ctx, "/me", cache=0)
        if not isinstance(me, dict) or "username" not in me:
            raise AdapterError("This address answers, but not the way Miniflux does.", code="not_miniflux")
        unread = await self._entries(config, ctx, limit=1)
        return f"Miniflux answers for {me['username']}: {unread.get('total', 0)} unread."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "summary":
            return self._summary(await self._entries(config, ctx, limit=1), await self._feeds(config, ctx), base_url(config))
        if widget_kind == "failing":
            return self._failing(await self._feeds(config, ctx), options, base_url(config))
        starred = bool(options.get("starred"))
        answer = await self._entries(config, ctx, limit=int(options.get("limit") or 8), starred=starred)
        return self._unread(answer, starred, base_url(config))

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def _broken(feeds: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [feed for feed in feeds if int(feed.get("parsing_error_count") or 0) > 0 and not feed.get("disabled")]

    @classmethod
    def _summary(cls, unread: dict[str, Any], feeds: list[dict[str, Any]], base: str) -> WidgetData:
        total = int(unread.get("total") or 0)
        failing = len(cls._broken(feeds))
        return WidgetData(
            status="warn" if failing else "ok",
            primary={"label": "Unread", "value": total},
            secondary=[{"label": "Feeds", "value": len(feeds)}, {"label": "Failing", "value": failing}],
            link=f"{base}/unread",
            metrics={"unread": float(total), "failing": float(failing)},
        )

    @staticmethod
    def _unread(answer: dict[str, Any], starred: bool, base: str) -> WidgetData:
        items = []
        for entry in answer["entries"]:
            if not isinstance(entry, dict):
                continue
            feed = entry.get("feed") if isinstance(entry.get("feed"), dict) else {}
            row: dict[str, Any] = {
                "title": str(entry.get("title") or entry.get("url") or "?"),
                "subtitle": str(feed.get("title") or ""),
                "value": ago(entry.get("published_at")),
            }
            if entry.get("url"):
                row["url"] = str(entry["url"])
            items.append(row)
        total = int(answer.get("total") or 0)
        return WidgetData(
            status="ok",
            items=items,
            secondary=[{"label": "Starred" if starred else "Unread", "value": total}],
            link=f"{base}/starred" if starred else f"{base}/unread",
            meta={"empty": "Nothing starred." if starred else "Nothing unread."},
            metrics={} if starred else {"unread": float(total)},
        )

    @classmethod
    def _failing(cls, feeds: list[dict[str, Any]], options: dict[str, Any], base: str) -> WidgetData:
        broken = sorted(cls._broken(feeds), key=lambda feed: -int(feed.get("parsing_error_count") or 0))
        items = [{
            "title": str(feed.get("title") or feed.get("feed_url") or "?"),
            "subtitle": str(feed.get("parsing_error_message") or ""),
            "status": "bad",
            "value": ago(feed.get("checked_at")),
            "url": f"{base}/feed/{feed['id']}/entries" if feed.get("id") is not None else str(feed.get("site_url") or ""),
        } for feed in broken]
        return WidgetData(
            status="warn" if broken else "ok",
            items=items[: int(options.get("limit") or 6)],
            secondary=[{"label": "Feeds", "value": len(feeds)}, {"label": "Failing", "value": len(broken)}],
            meta={"empty": "Every feed fetches without errors."},
            metrics={"failing": float(len(broken))},
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        now = time.time()
        broken = fake.flicker("mf-feed", tick, 0.7)
        stamp = lambda seconds: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - seconds))  # noqa: E731
        entries = [
            {"title": "Proxmox VE 9.3 released", "url": "https://news.example.com/pve-93", "published_at": stamp(40 * 60), "feed": {"title": "Homelab Weekly"}},
            {"title": "A quieter way to run backups", "url": "https://blog.example.com/backups", "published_at": stamp(3 * 3600), "feed": {"title": "Self-hosted notes"}},
            {"title": "ZFS on a small machine", "url": "https://blog.example.com/zfs", "published_at": stamp(9 * 3600), "feed": {"title": "Storage corner"}},
            {"title": "Home Assistant release party", "url": "https://news.example.com/ha", "published_at": stamp(26 * 3600), "feed": {"title": "Smart home digest"}},
        ]
        feeds = [
            {"id": 1, "title": "Homelab Weekly", "parsing_error_count": 0, "disabled": False},
            {"id": 2, "title": "Self-hosted notes", "parsing_error_count": 0, "disabled": False},
            {"id": 3, "title": "Old forum", "parsing_error_count": 4 if broken else 0, "disabled": False,
             "parsing_error_message": "The requested resource is not found. Please, verify the URL.", "checked_at": stamp(1800)},
        ]
        base = "https://miniflux.example.com"
        unread = {"total": 42 + tick % 5, "entries": entries}
        if widget_kind == "summary":
            return self._summary(unread, feeds, base)
        if widget_kind == "failing":
            return self._failing(feeds, options, base)
        return self._unread(unread, bool(options.get("starred")), base)


ADAPTER = MinifluxAdapter()
