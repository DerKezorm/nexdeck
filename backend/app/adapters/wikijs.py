"""Wiki.js 2: how many pages there are, the pages changed last, and whether Wiki.js is behind.

Measured on 28.10.2026 against Wiki.js 2.5.317 (SQLite), an API key with
full access, three invented pages and a second user. Wiki.js 3 is not
released and speaks a different schema; this is version 2.

⚠️ Every answer is HTTP 200, errors included: a refusal arrives as
``{"errors": [...], "data": {...: null}}``. Reading the status code would call
every failure a success.

⚠️ A wrong or missing key is not refused. Wiki.js treats the request as the
guest, and the guest of a default installation may read pages, so ``pages.list``
answered the same three pages with the key ``abc`` and with no key at all.
That is why every query asks ``users.profile`` beside the pages: it is the one
read that needs a real user and answers error 1019 "You must be
authenticated to access this resource." for the guest.

⚠️ ``system.info`` and ``users.list`` are for administrators and answer the
message "Forbidden" otherwise (also as HTTP 200). They are asked on their own,
so a key with fewer rights still fills the pages.

``pages.list`` takes ``orderBy: UPDATED``, ``orderByDirection: DESC`` and
``limit``; without a limit it answers every page the key may read, which is
how the pages are counted. A page lives at ``/<locale>/<path>``.
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

URL_HINT = "Check the URL; it is the address of Wiki.js itself, without /graphql."


class WikiJsAdapter(Adapter):
    kind = "wikijs"
    label = "Wiki.js"
    category = "other"
    description = "How many pages Wiki.js holds, the pages changed last, and whether a newer version is out."
    icon = "wikijs"
    beta = True
    docs_url = "https://docs.requarks.io/dev/api"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://wiki:3000"),
        Field("api_key", "API key", type="password", secret=True, required=True,
              help="Administration > API Access, after switching the API on. Wiki.js 2; the key needs the rights to read pages, and administrator rights for the version and the users."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(kind="summary", label="Wiki", description="How many pages there are, with the users and the version.",
                   renderer="value", default_size=(3, 2), refresh_seconds=600, metrics=("pages",),
                   parts=(("users", "Users"), ("version", "Version"))),
        WidgetType(kind="recent", label="Recently changed pages", description="The pages changed last, with their path.",
                   renderer="list", default_size=(3, 3), refresh_seconds=300,
                   options=(Field("limit", "Entries", type="number", default=8),)),
    )

    # -- talking to Wiki.js --------------------------------------------------

    async def _query(self, config: dict[str, Any], ctx: Context, query: str) -> dict[str, Any]:
        response = await ctx.request(
            "POST", f"{base_url(config)}/graphql", headers={"Authorization": f"Bearer {config.get('api_key') or ''}"},
            json_body={"query": query}, verify=not config.get("insecure"), auth_errors=False,
        )
        if response.status_code in (401, 403):
            raise AuthFailed("Wiki.js rejected the API key.")
        if response.status_code >= 400:
            raise AdapterError(f"Wiki.js answered with HTTP {response.status_code}.", code="http_error", hint=URL_HINT)
        try:
            answer = response.json()
        except ValueError as error:
            raise AdapterError("Wiki.js did not answer with JSON.", code="not_json",
                               hint="The URL probably points at a login page or a reverse proxy.") from error
        if not isinstance(answer, dict) or not ("data" in answer or "errors" in answer):
            raise AdapterError("This address answers, but not the way Wiki.js does.", code="not_wikijs", hint=URL_HINT)
        # ⚠️ HTTP 200 with the errors beside the data; see the top of the file.
        errors = [one for one in (answer.get("errors") or []) if isinstance(one, dict)]
        if errors:
            message = str(errors[0].get("message") or "")
            code = ((errors[0].get("extensions") or {}).get("exception") or {}).get("code")
            if code == 1019 or "must be authenticated" in message:
                raise AuthFailed("Wiki.js does not know this API key. Is the API switched on, and has the key not expired?")
            if message == "Forbidden":
                raise AdapterError("The API key may not read this.", code="forbidden",
                                   hint="Give the key's group the rights to read pages, or use the full access key.")
            raise AdapterError(f"Wiki.js refused the request: {message or 'unknown error'}.", code="graphql_error")
        data = answer.get("data")
        if not isinstance(data, dict):
            raise AdapterError("This address answers, but not the way Wiki.js does.", code="not_wikijs", hint=URL_HINT)
        return data

    async def _maybe(self, config: dict[str, Any], ctx: Context, query: str) -> dict[str, Any] | None:
        """What only an administrator may read; None for a key with fewer rights."""
        try:
            return await self._query(config, ctx, query)
        except AdapterError as error:
            if error.code == "forbidden":
                return None
            raise

    # -- the hooks -----------------------------------------------------------

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        data = await self._query(config, ctx, "{ users { profile { id } } pages { list { id } } }")
        info = await self._maybe(config, ctx, "{ system { info { currentVersion } } }")
        version = ((info or {}).get("system") or {}).get("info", {}).get("currentVersion")
        return f"Wiki.js {version or '?'} answers with {len((data.get('pages') or {}).get('list') or [])} pages."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        base = base_url(config)
        if widget_kind == "recent":
            limit = max(1, min(50, int(options.get("limit") or 8)))
            data = await self._query(
                config, ctx,
                f"{{ users {{ profile {{ id }} }} pages {{ list(orderBy: UPDATED, orderByDirection: DESC, limit: {limit}) "
                "{ id path locale title description isPublished updatedAt } } }")
            return self._recent((data.get("pages") or {}).get("list") or [], base)
        data = await self._query(config, ctx, "{ users { profile { id } } pages { list { id } } }")
        users = await self._maybe(config, ctx, "{ users { list { id isActive } } }")
        info = await self._maybe(config, ctx, "{ system { info { currentVersion latestVersion } } }")
        return self._summary(
            len((data.get("pages") or {}).get("list") or []),
            (users or {}).get("users", {}).get("list") if users else None,
            ((info or {}).get("system") or {}).get("info") if info else None,
            base,
        )

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def _summary(pages: int, users: list[Any] | None, info: dict[str, Any] | None, base: str) -> WidgetData:
        secondary: list[dict[str, Any]] = []
        if users is not None:
            secondary.append({"label": "Users", "value": sum(1 for one in users if isinstance(one, dict) and one.get("isActive")),
                              "part": "users"})
        status = "ok"
        if info and info.get("currentVersion"):
            current, latest = str(info["currentVersion"]), str(info.get("latestVersion") or "")
            behind = bool(latest) and latest != current
            secondary.append({"label": "Version", "value": current, "part": "version"})
            if behind:
                secondary.append({"label": "Newer version", "value": latest, "part": "version"})
                status = "warn"
        return WidgetData(
            status=status,
            primary={"label": "Pages", "value": pages},
            secondary=secondary,
            link=base,
            metrics={"pages": float(pages)},
        )

    @staticmethod
    def _recent(pages: list[Any], base: str) -> WidgetData:
        items = []
        for page in pages:
            if not isinstance(page, dict):
                continue
            path = str(page.get("path") or "")
            row: dict[str, Any] = {
                "title": str(page.get("title") or path or "?"),
                "subtitle": path,
                "value": ago(page.get("updatedAt")),
            }
            if path:
                row["url"] = f"{base}/{page.get('locale') or 'en'}/{path}"
            items.append(row)
        return WidgetData(status="ok", items=items, link=base, meta={"empty": "No pages yet."})

    # -- demo ----------------------------------------------------------------

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        base = "https://wiki.example.com"
        if widget_kind == "summary":
            fresh = 1 if fake.flicker("wikijs-new", tick, 0.3) else 0
            return self._summary(96 + tick % 3 + fresh, [{"isActive": True}] * 5, {"currentVersion": "2.5.317", "latestVersion": "2.5.317"}, base)
        now = time.time()
        stamp = lambda seconds: time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(now - seconds))  # noqa: E731
        pages = [
            {"title": "Backup plan", "path": "homelab/backups", "locale": "en", "updatedAt": stamp(1500)},
            {"title": "DNS notes", "path": "homelab/dns", "locale": "en", "updatedAt": stamp(5 * 3600)},
            {"title": "Tomato soup", "path": "recipes/soup", "locale": "en", "updatedAt": stamp(3 * 86400)},
        ]
        return self._recent(pages, base)


ADAPTER = WikiJsAdapter()
