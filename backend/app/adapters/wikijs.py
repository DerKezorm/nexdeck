"""Wiki.js 2: how many pages there are, the pages changed last, the newest comments, and whether Wiki.js is behind.

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

Comments, measured on 28.10.2026 against the same version with the built-in
comment provider:

⚠️ There is no list of all comments. ``comments.list(locale, path)`` answers
the comments of one page, ``comments.single(id)`` one comment without its
page, and a new comment leaves the ``updatedAt`` of its page alone, so "the
pages changed last" does not find it either. The card therefore asks page by
page, many pages to a request through aliases, and caps a round:
``COMMENT_PAGES`` pages, ``COMMENT_BATCH`` to a request, so one round is the
page list and at most two more requests. The ``COMMENT_HOT`` pages changed
last are asked every round, the others take turns, and what was read stays in
the integration's memory. On a wiki with more pages than one round holds, a
new comment on an old page shows up once that page's turn comes, and the card
says so until every page has had one.

⚠️ ``list`` is non-null, so one refused page nulls its parent: with all pages
under one ``comments { ... }``, a single page whose comments the key may not
read emptied the whole answer. Each alias is a ``comments`` of its own. Such a
page answers 8006 "You are not authorized to view comments for this page.";
a key without ``read:comments`` at all answers "Forbidden" for every page.
The guest of a default installation may read comments, so the profile rides
along here as well.

``render`` is the comment as HTML, with whatever the author typed as HTML
escaped (``&lt;b&gt;``). A comment carries the anchor ``#comment-post-id-<id>``,
but the comments load only once their section is on screen, so that anchor
does nothing on a freshly opened page (measured in Chromium). ``#discussion``
is the section itself: the browser scrolls there and the comments load.
"""

from __future__ import annotations

import html
import re
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

#: At most this many pages are asked for their comments in one round ...
COMMENT_PAGES = 100
#: ... in requests of this many pages each ...
COMMENT_BATCH = 50
#: ... and the pages changed last are among them every round; the rest take turns.
COMMENT_HOT = 50
#: Two comment cards on one wiki share a round instead of making two.
ROUND_SECONDS = 240
#: Where the comments read so far stay, in the integration's memory.
MEMORY = "wikijs.comments"
#: How much of a comment a row shows.
EXCERPT = 160


class WikiJsAdapter(Adapter):
    kind = "wikijs"
    label = "Wiki.js"
    category = "other"
    description = "How many pages Wiki.js holds, the pages changed last, the newest comments, and whether a newer version is out."
    icon = "wikijs"
    beta = True
    docs_url = "https://docs.requarks.io/dev/api"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://wiki:3000"),
        Field("api_key", "API key", type="password", secret=True, required=True,
              help="Administration > API Access, after switching the API on. Wiki.js 2; the key needs the rights to read pages, to read comments for the comments card, and administrator rights for the version and the users."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(kind="summary", label="Wiki", description="How many pages there are, with the users and the version.",
                   renderer="value", default_size=(3, 2), refresh_seconds=600, metrics=("pages",),
                   parts=(("users", "Users"), ("version", "Version"))),
        WidgetType(kind="recent", label="Recently changed pages", description="The pages changed last, with their path.",
                   renderer="list", default_size=(3, 3), refresh_seconds=300,
                   options=(Field("limit", "Entries", type="number", default=8),)),
        WidgetType(kind="comments", label="Recent comments", description="The newest comments, with their page, who wrote them and how long ago.",
                   renderer="list", default_size=(3, 3), refresh_seconds=300,
                   options=(Field("limit", "Entries", type="number", default=8),)),
    )

    # -- talking to Wiki.js --------------------------------------------------

    async def _answer(self, config: dict[str, Any], ctx: Context, query: str,
                      variables: dict[str, Any] | None = None) -> dict[str, Any]:
        """The whole answer, the errors and the data side by side."""
        body: dict[str, Any] = {"query": query}
        if variables:
            body["variables"] = variables
        response = await ctx.request(
            "POST", f"{base_url(config)}/graphql", headers={"Authorization": f"Bearer {config.get('api_key') or ''}"},
            json_body=body, verify=not config.get("insecure"), auth_errors=False,
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
        return answer

    async def _query(self, config: dict[str, Any], ctx: Context, query: str) -> dict[str, Any]:
        answer = await self._answer(config, ctx, query)
        # ⚠️ HTTP 200 with the errors beside the data; see the top of the file.
        errors = _errors(answer)
        if errors:
            raise _refusal(errors[0])
        return _data(answer)

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
        if widget_kind == "comments":
            memory = await self._comment_round(config, ctx)
            return self._comments(memory, base, max(1, min(50, int(options.get("limit") or 8))))
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

    async def _comment_round(self, config: dict[str, Any], ctx: Context) -> dict[str, Any]:
        """Read the comments of the pages whose turn it is; see the top of the file."""
        memory = ctx.cache.get(MEMORY)
        if memory is None:
            memory = ctx.cache[MEMORY] = {"pages": {}, "titles": {}, "asked": set(), "cursor": 0, "total": 0, "at": None}
        if memory["at"] is not None and time.monotonic() - memory["at"] < ROUND_SECONDS:
            return memory
        data = await self._query(config, ctx, "{ users { profile { id } } pages { list { id path locale title updatedAt } } }")
        pages = [page for page in ((data.get("pages") or {}).get("list") or [])
                 if isinstance(page, dict) and page.get("id") is not None and page.get("path")]
        pages.sort(key=lambda page: str(page.get("updatedAt") or ""), reverse=True)
        known = {page["id"] for page in pages}
        # A page that is gone takes its comments with it.
        memory["pages"] = {key: rows for key, rows in memory["pages"].items() if key in known}
        memory["asked"] &= known
        memory["titles"] = {page["id"]: (str(page.get("title") or page["path"]), str(page.get("locale") or "en"), str(page["path"]))
                            for page in pages}
        memory["total"] = len(pages)
        read, refusals = 0, []
        turn = self._turn(pages, memory)
        for start in range(0, len(turn), COMMENT_BATCH):
            batch = turn[start:start + COMMENT_BATCH]
            answer = await self._answer(config, ctx, *_comment_query(batch))
            errors = _errors(answer)
            for error in errors:
                if isinstance(_refusal(error), AuthFailed):
                    raise _refusal(error)
            refusals += errors
            data = _data(answer)
            for index, page in enumerate(batch):
                part = data.get(f"c{index}")
                rows = part.get("list") if isinstance(part, dict) else None
                memory["asked"].add(page["id"])
                if isinstance(rows, list):
                    read += 1
                    memory["pages"][page["id"]] = [row for row in rows if isinstance(row, dict)]
                else:
                    # Comments this key may not read are no comments to it.
                    memory["pages"].pop(page["id"], None)
        if refusals and not read:
            refusal = _refusal(refusals[0])
            if refusal.code == "forbidden":
                raise AdapterError("The API key may not read comments.", code="forbidden",
                                   hint="Give the key's group the right to read comments, or use the full access key.")
            raise refusal
        memory["at"] = time.monotonic()
        return memory

    @staticmethod
    def _turn(pages: list[dict[str, Any]], memory: dict[str, Any]) -> list[dict[str, Any]]:
        """The pages changed last, and as many of the others as the round still holds, in turn."""
        if len(pages) <= COMMENT_PAGES:
            return pages
        hot, rest = pages[:COMMENT_HOT], pages[COMMENT_HOT:]
        room = COMMENT_PAGES - COMMENT_HOT
        start = memory["cursor"] % len(rest)
        memory["cursor"] = (start + room) % len(rest)
        return hot + (rest[start:] + rest[:start])[:room]

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

    @staticmethod
    def _comments(memory: dict[str, Any], base: str, limit: int) -> WidgetData:
        found = [(str(row.get("createdAt") or ""), int(row.get("id") or 0), page, row)
                 for page, rows in memory["pages"].items() for row in rows]
        found.sort(key=lambda one: (one[0], one[1]), reverse=True)
        items = []
        for _created, number, page, row in found[:limit]:
            title, locale, path = memory["titles"].get(page, ("?", "en", ""))
            items.append({
                "id": number,
                "title": excerpt(row.get("render")) or "?",
                "subtitle": " · ".join((str(row.get("authorName") or "?"), title)),
                "value": ago(row.get("createdAt")),
                # ⚠️ Not #comment-post-id-<id>: see the top of the file.
                "url": f"{base}/{locale}/{path}#discussion",
            })
        meta: dict[str, Any] = {"empty": "No comments yet."}
        if memory["total"] > len(memory["asked"]):
            meta["notice"] = "This wiki has many pages; comments on older pages follow over the next rounds."
        return WidgetData(status="ok", items=items, link=base, meta=meta)

    # -- demo ----------------------------------------------------------------

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        base = "https://wiki.example.com"
        if widget_kind == "summary":
            fresh = 1 if fake.flicker("wikijs-new", tick, 0.3) else 0
            return self._summary(96 + tick % 3 + fresh, [{"isActive": True}] * 5, {"currentVersion": "2.5.317", "latestVersion": "2.5.317"}, base)
        now = time.time()
        stamp = lambda seconds: time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(now - seconds))  # noqa: E731
        if widget_kind == "comments":
            memory = {
                "titles": {1: ("Backup plan", "en", "homelab/backups"), 2: ("Tomato soup", "en", "recipes/soup"),
                           3: ("DNS notes", "en", "homelab/dns")},
                "pages": {
                    1: [{"id": 4, "authorName": "Sam Example", "createdAt": stamp(900),
                         "render": "<p>The second disk is <strong>full</strong> again, I moved the old snapshots.</p>"}],
                    2: [{"id": 2, "authorName": "Robin Sample", "createdAt": stamp(26 * 3600), "render": "<p>Less salt next time.</p>"},
                        {"id": 3, "authorName": "Alex Doe", "createdAt": stamp(7 * 3600), "render": "<p>And more basil.</p>"}],
                    3: [{"id": 1, "authorName": "Sam Example", "createdAt": stamp(4 * 86400),
                         "render": "<p>The second resolver answers again.</p>"}],
                },
                "asked": {1, 2, 3}, "total": 3,
            }
            return self._comments(memory, base, max(1, min(50, int(options.get("limit") or 8))))
        pages = [
            {"title": "Backup plan", "path": "homelab/backups", "locale": "en", "updatedAt": stamp(1500)},
            {"title": "DNS notes", "path": "homelab/dns", "locale": "en", "updatedAt": stamp(5 * 3600)},
            {"title": "Tomato soup", "path": "recipes/soup", "locale": "en", "updatedAt": stamp(3 * 86400)},
        ]
        return self._recent(pages, base)


def _errors(answer: dict[str, Any]) -> list[dict[str, Any]]:
    return [one for one in (answer.get("errors") or []) if isinstance(one, dict)]


def _data(answer: dict[str, Any]) -> dict[str, Any]:
    data = answer.get("data")
    if not isinstance(data, dict):
        raise AdapterError("This address answers, but not the way Wiki.js does.", code="not_wikijs", hint=URL_HINT)
    return data


def _refusal(error: dict[str, Any]) -> AdapterError:
    """What one GraphQL error means, as the error to raise."""
    message = str(error.get("message") or "")
    code = ((error.get("extensions") or {}).get("exception") or {}).get("code")
    if code == 1019 or "must be authenticated" in message:
        return AuthFailed("Wiki.js does not know this API key. Is the API switched on, and has the key not expired?")
    if message == "Forbidden" or code == 8006:
        return AdapterError("The API key may not read this.", code="forbidden",
                            hint="Give the key's group the rights to read pages, or use the full access key.")
    return AdapterError(f"Wiki.js refused the request: {message or 'unknown error'}.", code="graphql_error")


def _comment_query(pages: list[dict[str, Any]]) -> tuple[str, dict[str, Any]]:
    """One request for the comments of these pages, the paths as variables."""
    variables: dict[str, Any] = {}
    for index, page in enumerate(pages):
        variables[f"l{index}"] = str(page.get("locale") or "en")
        variables[f"p{index}"] = str(page["path"])
    signature = ", ".join(f"$l{index}: String!, $p{index}: String!" for index in range(len(pages)))
    # ⚠️ Each page under a `comments` of its own: one refused page would null them all.
    asks = " ".join(f"c{index}: comments {{ list(locale: $l{index}, path: $p{index}) {{ id authorName createdAt render }} }}"
                    for index in range(len(pages)))
    return f"query({signature}) {{ users {{ profile {{ id }} }} {asks} }}", variables


def excerpt(rendered: Any) -> str:
    """A comment as one line of plain text, cut short: Wiki.js hands it over as HTML."""
    text = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", str(rendered or ""))).split())
    return text if len(text) <= EXCERPT else text[:EXCERPT - 1].rstrip() + "…"


ADAPTER = WikiJsAdapter()
