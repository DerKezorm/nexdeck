"""FreshRSS: how much is unread, where, and the newest entries.

Measured on 27.09.2026 against FreshRSS 1.30.0 (the project's own image),
installed from the command line with the API allowed, two accounts with an
API password each and a third without one. Four invented feeds in two
categories, one of them an address that answers with no feed at all, next
to the feed of FreshRSS releases every new account starts with.

The way in is the Google Reader API, ``/api/greader.php``, and not Fever.
Both are behind the same switch and the same API password, but the Google
Reader API answers the unread count per feed and per category in one call,
hands out the entries of a stream with their feed's name, newest first, and
signs in with the user name and the password as they are. Fever wants an
MD5 of both, knows neither categories by name nor any order, and answers a
wrong key with 200 and ``auth: 0``.

⚠️ The API password is its own password, set per user under Settings >
Profile. The password somebody signs in with is refused like a wrong one:
401 with the body ``Unauthorized!``, the same as an unknown user and a user
that has no API password at all. The user name is case sensitive.

⚠️ With the API switched off (Administration > Authentication), every
address below ``/api/greader.php`` answers 503 ``Service Unavailable!``,
the sign-in included, while ``/api/greader.php`` itself still answers 200
``OK``. The adapter says what to switch on instead of "the service is down".

⚠️ The token from ``accounts/ClientLogin`` is ``user/`` and forty hex
characters and it does not run out: two sign-ins handed out the same one.
It changes with the API password, so the adapter keeps it and signs in once
more on a 401 before it believes the refusal.

⚠️ FreshRSS 1.30 refuses to fetch feeds from private addresses (the log
says "URL is not allowed to be resolved") unless they are listed in
``INTERNAL_HOST_ALLOWLIST`` as ``address:port``. That is FreshRSS's own
business and nothing the API reports; a feed on the home network that never
updates is the symptom.

⚠️ A feed that answers without a feed is not reported through the API: its
subscription looks like any other, with an unread count of 0. The cards say
nothing about broken feeds for that reason.

⚠️ The total unread count is the entry ``user/-/state/com.google/reading-list``
in ``unread-count``; ``max`` beside the list carried the same number.
``user-info`` answers JSON with the content type ``text/html``. The stream
of starred entries names itself ``reading-list`` in its ``id``.

⚠️ ``newestItemTimestampUsec`` in ``unread-count`` is when FreshRSS fetched
the entry, in microseconds, not when it was published: an entry a day old
fetched four minutes ago read "4 min". The card calls it the latest
arrival for that reason; the entries themselves carry ``published`` in
seconds.
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

SESSION = "freshrss_auth"
API = "/api/greader.php"
READING_LIST = "user/-/state/com.google/reading-list"
READ = "user/-/state/com.google/read"
STARRED = "user/-/state/com.google/starred"
LABEL = "user/-/label/"
URL_HINT = "Check the URL; it is the address of FreshRSS itself, without /api or /i."
API_HINT = "An administrator allows it in FreshRSS under Administration > Authentication > Allow API access."
PASSWORD_HINT = "The API password is set under Settings > Profile; it is not the password you sign in with."


class FreshRssAdapter(Adapter):
    kind = "freshrss"
    label = "FreshRSS"
    category = "feeds"
    description = "What is unread in FreshRSS, per feed or category, and the newest entries."
    icon = "freshrss"
    beta = False
    docs_url = "https://freshrss.github.io/FreshRSS/en/developers/06_GoogleReader_API.html"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://freshrss:80"),
        Field("username", "Username", required=True),
        Field("api_password", "API password", type="password", secret=True, required=True,
              help="Settings > Profile > API password, not the sign-in password. "
                   "The API has to be allowed under Administration > Authentication."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(kind="summary", label="Feed reader", description="How much is unread, in how many feeds and categories, and when the latest entry arrived.",
                   renderer="value", default_size=(2, 2), refresh_seconds=300, metrics=("unread",),
                   parts=(("feeds", "Feeds"), ("categories", "Categories"), ("arrival", "Latest arrival"))),
        WidgetType(kind="unread", label="Unread", description="The newest unread entries with their feed.",
                   renderer="list", default_size=(3, 3), refresh_seconds=300, metrics=("unread",),
                   options=(Field("limit", "Entries", type="number", default=8),
                            Field("starred", "Only starred entries", type="bool", default=False))),
        WidgetType(kind="feeds", label="Unread by feed", description="How many entries are unread in each feed or category, the most first.",
                   renderer="list", default_size=(3, 3), refresh_seconds=300, bars=True,
                   options=(Field("limit", "Entries", type="number", default=8),
                            Field("group", "Count by", type="select", default="feed",
                                  options=(("feed", "Feed"), ("category", "Category"))))),
    )

    # -- talking to FreshRSS -------------------------------------------------

    async def _send(self, config: dict[str, Any], ctx: Context, method: str, path: str, *, token: str = "",
                    data: dict[str, Any] | None = None, params: dict[str, Any] | None = None, cache: float = 0) -> Any:
        headers = {"Authorization": f"GoogleLogin auth={token}"} if token else None
        response = await ctx.request(method, f"{base_url(config)}{API}{path}", headers=headers, data=data, params=params,
                                     verify=not config.get("insecure"), cache_seconds=cache, timeout=15.0, auth_errors=False)
        if response.status_code == 503:
            # ⚠️ The API switched off; see the top of the file.
            raise AdapterError("FreshRSS has its API switched off.", code="api_disabled", hint=API_HINT)
        return response

    async def _sign_in(self, config: dict[str, Any], ctx: Context) -> str:
        user = str(config.get("username") or "").strip()
        response = await self._send(config, ctx, "POST", "/accounts/ClientLogin",
                                    data={"Email": user, "Passwd": str(config.get("api_password") or "")})
        if response.status_code in (401, 403):
            refused = AuthFailed("FreshRSS rejected the user name or the API password.")
            refused.hint = PASSWORD_HINT
            raise refused
        if response.status_code >= 400:
            raise AdapterError(f"FreshRSS answered with HTTP {response.status_code}.", code="http_error", hint=URL_HINT)
        for line in response.text.splitlines():
            if line.startswith("Auth="):
                return line[len("Auth="):].strip()
        raise AdapterError("This address answers, but not the way FreshRSS does.", code="not_freshrss", hint=URL_HINT)

    async def _token(self, config: dict[str, Any], ctx: Context, *, fresh: bool = False) -> str:
        who = (base_url(config), str(config.get("username") or "").strip(), str(config.get("api_password") or ""))
        held = ctx.cache.get(SESSION)
        if not fresh and isinstance(held, tuple) and held[0] == who:
            return str(held[1])
        token = await self._sign_in(config, ctx)
        ctx.cache[SESSION] = (who, token)
        return token

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        response = await self._send(config, ctx, "GET", path, token=await self._token(config, ctx), params=params, cache=10)
        if response.status_code == 401:
            # ⚠️ A kept token dies with a changed API password: sign in once more.
            response = await self._send(config, ctx, "GET", path, token=await self._token(config, ctx, fresh=True), params=params, cache=10)
        if response.status_code in (401, 403):
            raise AuthFailed("FreshRSS rejected the user name or the API password.")
        if response.status_code >= 400:
            raise AdapterError(f"FreshRSS answered with HTTP {response.status_code}.", code="http_error", hint=URL_HINT)
        try:
            answer = response.json()
        except ValueError as error:
            raise AdapterError("FreshRSS did not answer with JSON.", code="not_json", hint=URL_HINT) from error
        if not isinstance(answer, dict):
            raise AdapterError("This address answers, but not the way FreshRSS does.", code="not_freshrss", hint=URL_HINT)
        return answer

    async def _counts(self, config: dict[str, Any], ctx: Context) -> list[dict[str, Any]]:
        answer = await self._get(config, ctx, "/reader/api/0/unread-count", {"output": "json"})
        if not isinstance(answer.get("unreadcounts"), list):
            raise AdapterError("This address answers, but not the way FreshRSS does.", code="not_freshrss", hint=URL_HINT)
        return [one for one in answer["unreadcounts"] if isinstance(one, dict)]

    async def _subscriptions(self, config: dict[str, Any], ctx: Context) -> list[dict[str, Any]]:
        answer = await self._get(config, ctx, "/reader/api/0/subscription/list", {"output": "json"})
        return [one for one in answer.get("subscriptions") or [] if isinstance(one, dict)]

    async def _stream(self, config: dict[str, Any], ctx: Context, limit: int, starred: bool) -> list[dict[str, Any]]:
        if starred:
            path, params = f"/reader/api/0/stream/contents/{STARRED}", {"n": max(1, limit)}
        else:
            path, params = f"/reader/api/0/stream/contents/{READING_LIST}", {"n": max(1, limit), "xt": READ}
        answer = await self._get(config, ctx, path, params)
        return [one for one in answer.get("items") or [] if isinstance(one, dict)]

    # -- the hooks -----------------------------------------------------------

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        counts = await self._counts(config, ctx)
        user = str(config.get("username") or "").strip()
        return f"FreshRSS answers for {user}: {self._total(counts)} unread."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        base = base_url(config)
        counts = await self._counts(config, ctx)
        if widget_kind == "unread":
            starred = options.get("starred") is True
            entries = await self._stream(config, ctx, int(options.get("limit") or 8), starred)
            return self._unread(entries, counts, starred, base)
        subscriptions = await self._subscriptions(config, ctx)
        if widget_kind == "feeds":
            return self._by_feed(counts, subscriptions, options, base)
        return self._summary(counts, subscriptions, base, time.time())

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def _total(counts: list[dict[str, Any]]) -> int:
        for one in counts:
            if one.get("id") == READING_LIST:
                return int(one.get("count") or 0)
        return 0

    @classmethod
    def _summary(cls, counts: list[dict[str, Any]], subscriptions: list[dict[str, Any]], base: str, now: float) -> WidgetData:
        total = cls._total(counts)
        categories = {str(category.get("label") or category.get("id"))
                      for one in subscriptions for category in one.get("categories") or [] if isinstance(category, dict)}
        newest = next((int(one.get("newestItemTimestampUsec") or 0) for one in counts if one.get("id") == READING_LIST), 0)
        return WidgetData(
            status="ok",
            primary={"label": "Unread", "value": total},
            secondary=[
                {"label": "Feeds", "value": len(subscriptions), "part": "feeds"},
                {"label": "Categories", "value": len(categories), "part": "categories"},
                # ⚠️ When FreshRSS fetched it, not when it was published; microseconds.
                {"label": "Latest arrival", "value": ago(newest / 1_000_000, now) if newest > 0 and total else "", "part": "arrival"},
            ],
            link=f"{base}/i/",
            metrics={"unread": float(total)},
        )

    @classmethod
    def _unread(cls, entries: list[dict[str, Any]], counts: list[dict[str, Any]], starred: bool, base: str) -> WidgetData:
        items = []
        for entry in entries:
            origin = entry.get("origin") if isinstance(entry.get("origin"), dict) else {}
            links = [one.get("href") for one in (entry.get("alternate") or entry.get("canonical") or []) if isinstance(one, dict)]
            row: dict[str, Any] = {
                "title": str(entry.get("title") or (links[0] if links else "") or "?"),
                "subtitle": str(origin.get("title") or ""),
                # Seconds since the epoch.
                "value": ago(entry.get("published")),
            }
            if links and links[0]:
                row["url"] = str(links[0])
            items.append(row)
        total = cls._total(counts)
        return WidgetData(
            status="ok",
            items=items,
            secondary=[] if starred else [{"label": "Unread", "value": total}],
            link=f"{base}/i/",
            meta={"empty": "Nothing starred." if starred else "Nothing unread."},
            metrics={} if starred else {"unread": float(total)},
        )

    @staticmethod
    def _by_feed(counts: list[dict[str, Any]], subscriptions: list[dict[str, Any]], options: dict[str, Any], base: str) -> WidgetData:
        by_category = options.get("group") == "category"
        names = {str(one.get("id")): str(one.get("title") or one.get("url") or "?") for one in subscriptions}
        rows = []
        for one in counts:
            key = str(one.get("id") or "")
            count = int(one.get("count") or 0)
            if count <= 0:
                continue
            if by_category and key.startswith(LABEL):
                title = key[len(LABEL):]
            elif not by_category and key.startswith("feed/"):
                title = names.get(key, key)
            else:
                continue
            rows.append({"title": title, "value": count, "status": "ok"})
        rows.sort(key=lambda row: (-row["value"], row["title"].lower()))
        return WidgetData(
            status="ok",
            items=rows[: int(options.get("limit") or 8)],
            link=f"{base}/i/",
            meta={"empty": "Nothing unread."},
        )

    # -- demo ----------------------------------------------------------------

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        now = time.time()
        fresh = fake.flicker("freshrss-new", tick, 0.4)
        homelab = 6 + tick % 4 + (2 if fresh else 0)
        counts = [
            {"id": "feed/1", "count": homelab, "newestItemTimestampUsec": str(int((now - 900) * 1_000_000))},
            {"id": "feed/2", "count": 3, "newestItemTimestampUsec": str(int((now - 7200) * 1_000_000))},
            {"id": "feed/3", "count": 12, "newestItemTimestampUsec": str(int((now - 3600) * 1_000_000))},
            {"id": "feed/4", "count": 0, "newestItemTimestampUsec": "0"},
            {"id": "user/-/label/Tech", "count": homelab + 3, "newestItemTimestampUsec": "0"},
            {"id": "user/-/label/News", "count": 12, "newestItemTimestampUsec": "0"},
            {"id": READING_LIST, "count": homelab + 15, "newestItemTimestampUsec": str(int((now - 900) * 1_000_000))},
        ]
        # Category names are the operator's own words and stay as they are.
        subscriptions = [
            {"id": f"feed/{number}", "title": title, "categories": [dict(id=f"{LABEL}{folder}", label=folder)]}
            for number, title, folder in ((1, "Homelab Weekly", "Tech"), (2, "Storage Corner", "Tech"),
                                          (3, "Morning Digest", "News"), (4, "Garden Log", "News"))
        ]
        base = "https://freshrss.example.com"
        if widget_kind == "unread":
            entries = [
                {"title": "Proxmox cluster notes", "published": now - 900, "alternate": [{"href": "https://homelab.example.com/cluster"}],
                 "origin": {"streamId": "feed/1", "title": "Homelab Weekly"}},
                {"title": "Five quiet fans compared", "published": now - 3600, "alternate": [{"href": "https://digest.example.com/fans"}],
                 "origin": {"streamId": "feed/3", "title": "Morning Digest"}},
                {"title": "ZFS on a small machine", "published": now - 7200, "alternate": [{"href": "https://storage.example.com/zfs"}],
                 "origin": {"streamId": "feed/2", "title": "Storage Corner"}},
                {"title": "A rack in the hallway", "published": now - 26 * 3600, "alternate": [{"href": "https://homelab.example.com/rack"}],
                 "origin": {"streamId": "feed/1", "title": "Homelab Weekly"}},
            ]
            return self._unread(entries, counts, options.get("starred") is True, base)
        if widget_kind == "feeds":
            return self._by_feed(counts, subscriptions, options, base)
        return self._summary(counts, subscriptions, base, now)


ADAPTER = FreshRssAdapter()
