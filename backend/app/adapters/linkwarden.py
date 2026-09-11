"""Linkwarden: the links saved lately, and how many there are.

Measured against Linkwarden 2.16.3 on 11.09.2026, with an account, an access
token, a collection with two tagged links (one of them pinned) and a link
saved without a collection.

⚠️ No endpoint answers with the number of links. ``/api/v1/collections``
carries ``_count.links`` for every collection, and the card adds those up;
``/api/v2/dashboard`` counts pinned links and tags.

⚠️ A link saved without a collection lands in one called "Unorganized",
which Linkwarden makes on the spot.

⚠️ A missing and a wrong token both get 401 "You must be logged in."
``/api/v1/config`` answers without one and carries the version.
"""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import urlsplit

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


class LinkwardenAdapter(Adapter):
    kind = "linkwarden"
    label = "Linkwarden"
    category = "feeds"
    description = "The links saved lately, and how many there are."
    icon = "linkwarden"
    beta = False
    docs_url = "https://docs.linkwarden.app/api/api-introduction"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://linkwarden:3000"),
        Field("token", "Access token", type="password", secret=True, required=True, help="Settings > Access Tokens > New Access Token."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(kind="recent", label="Recent links", description="The links saved last, with their collection and tags.",
                   renderer="list", default_size=(3, 3), refresh_seconds=300,
                   options=(Field("limit", "Entries", type="number", default=8),
                            Field("pinned", "Only pinned links", type="bool", default=False))),
        WidgetType(kind="summary", label="Links", description="How many links, collections, pinned links and tags there are.",
                   renderer="value", default_size=(3, 2), refresh_seconds=600, metrics=("links",)),
    )

    async def _json(self, config: dict[str, Any], ctx: Context, path: str, params: dict[str, Any] | None = None, cache: float = 10) -> Any:
        response = await ctx.request(
            "GET", f"{base_url(config)}/api{path}", headers={"Authorization": f"Bearer {config.get('token') or ''}"},
            params=params, verify=not config.get("insecure"), cache_seconds=cache, auth_errors=False,
        )
        if response.status_code in (401, 403):
            raise AuthFailed("Linkwarden rejected the access token.")
        if response.status_code >= 400:
            raise AdapterError(f"Linkwarden answered with HTTP {response.status_code}.", code="http_error",
                               hint="Check the URL; it is the address of Linkwarden itself, without /api.")
        try:
            answer = response.json()
        except ValueError as error:
            raise AdapterError("Linkwarden did not answer with JSON.", code="not_json",
                               hint="The URL probably points at a login page or a reverse proxy.") from error
        if not isinstance(answer, dict):
            raise AdapterError("This address answers, but not the way Linkwarden does.", code="not_linkwarden")
        return answer

    async def _collections(self, config: dict[str, Any], ctx: Context) -> list[dict[str, Any]]:
        answer = await self._json(config, ctx, "/v1/collections", cache=30)
        if not isinstance(answer.get("response"), list):
            raise AdapterError("This address answers, but not the way Linkwarden does.", code="not_linkwarden")
        return [one for one in answer["response"] if isinstance(one, dict)]

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        collections = await self._collections(config, ctx)
        about = await self._json(config, ctx, "/v1/config", cache=0)
        version = str((about.get("response") or {}).get("INSTANCE_VERSION") or "?").lstrip("v")
        return f"Linkwarden {version} answers with {sum(self._count(one) for one in collections)} links."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "summary":
            collections = await self._collections(config, ctx)
            dashboard = await self._json(config, ctx, "/v2/dashboard", cache=30)
            return self._summary(collections, dashboard.get("data") if isinstance(dashboard.get("data"), dict) else {})
        params: dict[str, Any] = {"sort": 0}
        if options.get("pinned"):
            params["pinnedOnly"] = "true"
        answer = await self._json(config, ctx, "/v1/links", params)
        if not isinstance(answer.get("response"), list):
            raise AdapterError("This address answers, but not the way Linkwarden does.", code="not_linkwarden")
        return self._recent(answer["response"], options)

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def _count(collection: dict[str, Any]) -> int:
        counted = collection.get("_count") if isinstance(collection.get("_count"), dict) else {}
        return int(counted.get("links") or 0)

    @staticmethod
    def _recent(links: list[Any], options: dict[str, Any]) -> WidgetData:
        items = []
        for link in links[: int(options.get("limit") or 8)]:
            if not isinstance(link, dict):
                continue
            address = str(link.get("url") or "")
            host = urlsplit(address).hostname or ""
            collection = link.get("collection") if isinstance(link.get("collection"), dict) else {}
            tags = ", ".join(str(tag.get("name")) for tag in (link.get("tags") or [])[:2] if isinstance(tag, dict) and tag.get("name"))
            row: dict[str, Any] = {
                "title": str(link.get("name") or host or address or "?"),
                "subtitle": " · ".join(part for part in (host, str(collection.get("name") or ""), tags) if part),
                "value": ago(link.get("createdAt")),
            }
            if address:
                row["url"] = address
            items.append(row)
        return WidgetData(
            status="ok",
            items=items,
            meta={"empty": "No pinned links yet." if options.get("pinned") else "No links saved yet."},
        )

    def _summary(self, collections: list[dict[str, Any]], dashboard: dict[str, Any]) -> WidgetData:
        links = sum(self._count(one) for one in collections)
        secondary: list[dict[str, Any]] = [{"label": "Collections", "value": len(collections)}]
        secondary += [{"label": label, "value": value} for label, value in
                      (("Pinned", int(dashboard.get("numberOfPinnedLinks") or 0)), ("Tags", int(dashboard.get("numberOfTags") or 0))) if value]
        return WidgetData(
            status="ok",
            primary={"label": "Links", "value": links},
            secondary=secondary,
            metrics={"links": float(links)},
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        if widget_kind == "summary":
            return self._summary([{"_count": {"links": 311 + tick % 4}}, {"_count": {"links": 96}}, {"_count": {"links": 12}}],
                                 {"numberOfPinnedLinks": 9, "numberOfTags": 41})

        def saved(hours: float) -> str:
            return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(time.time() - hours * 3600))

        links = [
            {"name": "Self-hosting a mail server in 2026", "url": "https://blog.example.com/mail", "createdAt": saved(2),
             "collection": {"name": "Homelab"}, "tags": [{"name": "mail"}]},
            {"name": "", "url": "https://docs.example.org/zfs/send", "createdAt": saved(9), "collection": {"name": "Unorganized"}, "tags": []},
            {"name": "Sourdough, the long way", "url": "https://kitchen.example.net/sourdough", "createdAt": saved(30),
             "collection": {"name": "Recipes"}, "tags": [{"name": "bread"}, {"name": "weekend"}]},
        ]
        return self._recent(links, options)


ADAPTER = LinkwardenAdapter()
