"""Umami: visitors, page views and live visitors of your websites, and what they read and where they came from.

Measured on 28.10.2026 against Umami 3.4.1 (``ghcr.io/umami-software/umami``
with PostgreSQL 15): the sign-in, the website list, the figures, the visitors
online and the five rankings all answer as described below, and the answers in
the tests are recorded from it. **Not run** against Umami 2, which is still
read after its documentation, nor against Umami Cloud (no account). That is why
the card stays a beta.

What the documentation says, and Umami 3.4.1 confirmed except where noted:

- Self-hosted: ``POST /api/auth/login`` with ``{"username", "password"}`` gives
  ``{"token": ..., "user": {...}}``, sent as ``Authorization: Bearer``; a wrong
  password is 401 (an empty field 400), a token it does not know 401 as well,
  and a path that is not Umami's a 404 page. Umami Cloud has no
  login but an API key in ``x-umami-api-key`` and its API under
  ``https://api.umami.is/v1``.
- ``GET /websites`` gives ``{"data": [{"id", "name", "domain", ...}], "count": n, "page", "pageSize"}``;
  ``pageSize=100`` is accepted.
- ``GET /websites/<id>/stats?startAt=<ms>&endAt=<ms>`` gives ``pageviews``,
  ``visitors``, ``visits``, ``bounces`` and ``totaltime`` (in seconds); without
  both bounds it is 400, an unknown website gives zeros. In
  Umami 2 each is ``{"value": n, "prev": m}``, in Umami 3 (measured) a plain
  number with a ``comparison`` beside them; both are read.
- ``GET /websites/<id>/active`` gives the visitors of the last five minutes:
  ``{"x": n}`` in Umami 2, ``{"visitors": n}`` in Umami 3.
- ``GET /websites/<id>/metrics?type=...&startAt&endAt&limit`` gives
  ``[{"x": name, "y": count}]``. The type for pages is ``url`` in Umami 2 and
  ``path`` in Umami 3; the card asks for ``path`` and tries ``url`` when that
  is refused with 400. Umami 3.4.1 refuses ``url`` and a wrong type with a bare
  400, leaves visits without a referrer out of ``referrer``, and names the
  devices ``laptop``, ``mobile`` and so on.
"""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import urlsplit

from . import demo as fake
from .base import (
    Adapter,
    AdapterError,
    AuthFailed,
    Context,
    Field,
    WidgetData,
    WidgetType,
    base_url,
    duration_short,
)

PERIODS = (("day", "The last 24 hours"), ("week", "The last 7 days"), ("month", "The last 30 days"))
SECONDS = {"day": 86400, "week": 7 * 86400, "month": 30 * 86400}
TOPS = (("pages", "Pages"), ("referrers", "Referrers"), ("countries", "Countries"), ("browsers", "Browsers"), ("devices", "Devices"))
#: What the card calls a kind of ranking, and the type Umami calls it.
METRIC = {"pages": "path", "referrers": "referrer", "countries": "country", "browsers": "browser", "devices": "device"}
PERIOD_FIELD = Field("period", "Period", type="select", default="day", options=PERIODS)
SITE_FIELD = Field("website", "Website", placeholder="example.com", help="Its name, its domain or its ID. Empty means the first one.")


def _count(value: Any) -> float:
    """A figure of the stats: ``{"value": n, "prev": m}`` in Umami 2, a number in Umami 3."""
    if isinstance(value, dict):
        value = value.get("value")
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else 0.0


def _live(answer: Any) -> int:
    if not isinstance(answer, dict):
        return 0
    for key in ("visitors", "x"):
        if isinstance(answer.get(key), int | float):
            return int(answer[key])
    return 0


class UmamiAdapter(Adapter):
    kind = "umami"
    label = "Umami"
    category = "monitoring"
    description = "Visitors, page views and live visitors of your websites in Umami, and their top pages, referrers and countries."
    icon = "umami"
    docs_url = "https://umami.is/docs/api"
    #: Measured against Umami 3.4.1; Umami 2 and Umami Cloud are built from the documentation.
    beta = True
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="https://umami.example.com",
              help="Your Umami, or https://api.umami.is for Umami Cloud."),
        Field("username", "User name", help="Of your own Umami. Not for Umami Cloud."),
        Field("password", "Password", type="password", secret=True, help="Of that user. Not for Umami Cloud."),
        Field("api_key", "API key", type="password", secret=True, help="Umami Cloud only: Settings > API keys."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(
            kind="site",
            label="Website",
            description="Visitors, page views, visits, bounce rate and visit time of one website, and who is on it now.",
            renderer="stats",
            default_size=(3, 2),
            refresh_seconds=120,
            metrics=("visitors", "pageviews", "online"),
            options=(SITE_FIELD, PERIOD_FIELD),
        ),
        WidgetType(
            kind="websites",
            label="Websites",
            description="Every website with its visitors in a period and how many are on it now.",
            renderer="list",
            default_size=(4, 3),
            min_size=(3, 2),
            refresh_seconds=300,
            options=(PERIOD_FIELD, Field("limit", "Entries", type="number", default=8)),
        ),
        WidgetType(
            kind="top",
            label="Top of a website",
            description="The pages, referrers, countries, browsers or devices with the most visitors on one website.",
            renderer="list",
            default_size=(4, 3),
            min_size=(3, 2),
            refresh_seconds=600,
            options=(SITE_FIELD, Field("what", "Show", type="select", default="pages", options=TOPS), PERIOD_FIELD, Field("limit", "Entries", type="number", default=8)),
        ),
    )

    # -- asking Umami -----------------------------------------------------------------

    @staticmethod
    def _api(config: dict[str, Any]) -> str:
        base = base_url(config)
        return f"{base}/v1" if (urlsplit(base).hostname or "") == "api.umami.is" else f"{base}/api"

    async def _login(self, config: dict[str, Any], ctx: Context) -> str:
        user, password = str(config.get("username") or "").strip(), str(config.get("password") or "")
        if not user:
            raise AuthFailed("Umami wants a user name and a password, or an API key for Umami Cloud.")
        response = await ctx.request("POST", f"{self._api(config)}/auth/login", json_body={"username": user, "password": password},
                                     verify=not config.get("insecure"), timeout=20, auth_errors=False)
        if response.status_code == 404:
            raise AdapterError("This address answers, but not the way Umami does.", code="not_umami", hint="The URL is the address of Umami itself, without /api.")
        if response.status_code in (400, 401, 403):
            failure = AuthFailed("Umami rejected the user name or the password.")
            failure.hint = "Use the name and password you sign in to Umami with."
            raise failure
        if response.status_code >= 400:
            raise AdapterError(f"Umami answered with HTTP {response.status_code}.", code="http_error")
        try:
            token = str(response.json().get("token") or "")
        except (ValueError, AttributeError) as error:
            raise AdapterError("Umami did not answer with JSON.", code="not_json", hint="The URL is the address of Umami itself.") from error
        if not token:
            raise AdapterError("Umami gave no token.", code="no_token")
        ctx.cache["umami:token"] = token
        return token

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, params: dict[str, Any] | None = None, retry: bool = True,
                   cache: float = 20) -> Any:
        key = str(config.get("api_key") or "").strip()
        if key:
            headers = {"x-umami-api-key": key}
        else:
            headers = {"Authorization": f"Bearer {ctx.cache.get('umami:token') or await self._login(config, ctx)}"}
        response = await ctx.request("GET", f"{self._api(config)}{path}", params=params, headers=headers, verify=not config.get("insecure"),
                                     cache_seconds=cache, timeout=25, auth_errors=False)
        if response.status_code == 401:
            if key:
                raise AuthFailed("Umami Cloud rejected the API key.")
            ctx.cache.pop("umami:token", None)
            if retry:
                # A token that has run out: sign in once more, and say so if that is refused too.
                await self._login(config, ctx)
                # Not from memory: the 401 of the first try is kept for a few seconds under the same address.
                return await self._get(config, ctx, path, params, retry=False, cache=0)
            raise AuthFailed("Umami rejected the sign-in.")
        if response.status_code == 400 and path.endswith("/metrics"):
            return None
        if response.status_code == 404:
            raise AdapterError("This address answers, but not the way Umami does.", code="not_umami", hint="The URL is the address of Umami itself, without /api.")
        if response.status_code >= 400:
            raise AdapterError(f"Umami answered with HTTP {response.status_code}.", code="http_error")
        try:
            return response.json()
        except ValueError as error:
            raise AdapterError("Umami did not answer with JSON.", code="not_json", hint="The URL probably points at a login page or a reverse proxy.") from error

    async def _websites(self, config: dict[str, Any], ctx: Context) -> list[dict[str, Any]]:
        answer = await self._get(config, ctx, "/websites", {"pageSize": 100})
        rows = answer.get("data") if isinstance(answer, dict) else answer
        return [one for one in rows or [] if isinstance(one, dict) and one.get("id")]

    @staticmethod
    def _pick(sites: list[dict[str, Any]], wanted: str) -> dict[str, Any]:
        wanted = wanted.strip().casefold()
        if not sites:
            raise AdapterError("Umami has no website yet.", code="no_website")
        if not wanted:
            return sites[0]
        for site in sites:
            if wanted in (str(site.get("id")).casefold(), str(site.get("name") or "").casefold(), str(site.get("domain") or "").casefold()):
                return site
        raise AdapterError(f"No website is called {wanted}.", code="no_website", hint="Use its name, its domain or its ID as Umami shows them.")

    @staticmethod
    def _window(options: dict[str, Any], now: float | None = None) -> dict[str, int]:
        end = int((now if now is not None else time.time()) * 1000)
        return {"startAt": end - SECONDS.get(str(options.get("period") or "day"), 86400) * 1000, "endAt": end}

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        ctx.cache.pop("umami:token", None)
        sites = await self._websites(config, ctx)
        return f"Umami accepts the sign-in, {len(sites)} websites."

    # -- the cards -------------------------------------------------------------------------

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        sites = await self._websites(config, ctx)
        window = self._window(options)
        link = base_url(config)
        if widget_kind == "websites":
            limit = max(1, min(30, int(options.get("limit") or 8)))
            facts = []
            for site in sites[:limit]:
                stats = await self._get(config, ctx, f"/websites/{site['id']}/stats", window)
                live = await self._get(config, ctx, f"/websites/{site['id']}/active")
                facts.append((site, stats, _live(live)))
            return self.websites_card(facts, len(sites), link)
        site = self._pick(sites, str(options.get("website") or ""))
        if widget_kind == "top":
            kind = str(options.get("what") or "pages")
            limit = max(1, min(30, int(options.get("limit") or 8)))
            rows = await self._get(config, ctx, f"/websites/{site['id']}/metrics", {**window, "type": METRIC.get(kind, "path"), "limit": limit})
            if rows is None and kind == "pages":
                rows = await self._get(config, ctx, f"/websites/{site['id']}/metrics", {**window, "type": "url", "limit": limit})
            return self.top_card(rows or [], kind, limit, link)
        stats = await self._get(config, ctx, f"/websites/{site['id']}/stats", window)
        live = await self._get(config, ctx, f"/websites/{site['id']}/active")
        return self.site_card(stats, _live(live), link)

    @staticmethod
    def site_card(stats: Any, online: int, link: str | None = None) -> WidgetData:
        stats = stats if isinstance(stats, dict) else {}
        visitors, views, visits = _count(stats.get("visitors")), _count(stats.get("pageviews")), _count(stats.get("visits"))
        bounces, seconds = _count(stats.get("bounces")), _count(stats.get("totaltime"))
        secondary = [{"label": "Page views", "value": int(views)}, {"label": "Visits", "value": int(visits)}, {"label": "Online now", "value": online}]
        if visits:
            secondary.append({"label": "Bounce rate", "value": f"{round(100 * bounces / visits)}%"})
            secondary.append({"label": "Visit time", "value": duration_short(seconds / visits)})
        return WidgetData(
            status="ok",
            primary={"label": "Visitors", "value": int(visitors)},
            secondary=secondary,
            metrics={"visitors": visitors, "pageviews": views, "online": float(online)},
            link=link,
        )

    @staticmethod
    def websites_card(facts: list[tuple[dict[str, Any], Any, int]], total: int, link: str | None = None) -> WidgetData:
        top = max((_count((stats or {}).get("visitors")) for _site, stats, _live_now in facts), default=0.0)
        items = []
        for site, stats, online in facts:
            stats = stats if isinstance(stats, dict) else {}
            visitors = _count(stats.get("visitors"))
            items.append({
                "title": str(site.get("name") or site.get("domain") or "?"),
                "subtitle": " · ".join(part for part in (str(site.get("domain") or "") if site.get("name") != site.get("domain") else "",
                                                          f"{int(_count(stats.get('pageviews')))} views", f"{online} online" if online else "") if part),
                "value": str(int(visitors)),
                "progress": round(100 * visitors / top, 1) if top else 0.0,
                "status": "ok",
            })
        return WidgetData(status="ok", items=items, secondary=[{"label": "Websites", "value": total}], link=link, meta={"empty": "Umami has no website yet."})

    @staticmethod
    def top_card(rows: Any, kind: str, limit: int, link: str | None = None) -> WidgetData:
        entries = [one for one in rows if isinstance(one, dict)] if isinstance(rows, list) else []
        top = max((float(one.get("y") or 0) for one in entries), default=0.0)
        items = []
        for one in entries[:limit]:
            name = str(one.get("x") or "")
            items.append({
                "title": name or ("Direct" if kind == "referrers" else "Unknown"),
                "subtitle": "No referrer" if kind == "referrers" and not name else "",
                "value": str(int(one.get("y") or 0)),
                "progress": round(100 * float(one.get("y") or 0) / top, 1) if top else 0.0,
            })
        return WidgetData(status="ok", items=items, link=link, meta={"empty": "No visits in this period."})

    # -- demo ----------------------------------------------------------------------------------

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        scale = {"day": 1, "week": 6, "month": 24}.get(str(options.get("period") or "day"), 1)
        visitors = int((140 + fake.walk("umami-visitors", tick, 0, 40)) * scale)
        if widget_kind == "websites":
            sites = [({"name": "Blog", "domain": "blog.example.com"}, {"visitors": visitors, "pageviews": visitors * 3}, int(fake.walk("umami-live", tick, 0, 5))),
                     ({"name": "Docs", "domain": "docs.example.com"}, {"visitors": visitors // 3, "pageviews": visitors}, 1),
                     ({"name": "Status", "domain": "status.example.com"}, {"visitors": visitors // 10, "pageviews": visitors // 3}, 0)]
            return self.websites_card(sites, 3)
        if widget_kind == "top":
            what = str(options.get("what") or "pages")
            names = {"pages": ["/", "/blog/self-hosting", "/about", "/projects"], "referrers": ["", "news.example.org", "search.example.net"],
                     "countries": ["DE", "US", "NL", "FR"], "browsers": ["chrome", "firefox", "safari"], "devices": ["desktop", "mobile", "tablet"]}[what]
            return self.top_card([{"x": name, "y": int(visitors / (index + 1.5))} for index, name in enumerate(names)], what, int(options.get("limit") or 8))
        stats = {"visitors": {"value": visitors, "prev": visitors - 9}, "pageviews": {"value": visitors * 3, "prev": 0}, "visits": {"value": int(visitors * 1.2), "prev": 0},
                 "bounces": {"value": int(visitors * 0.5), "prev": 0}, "totaltime": {"value": int(visitors * 1.2) * 95, "prev": 0}}
        return self.site_card(stats, int(fake.walk("umami-live", tick, 0, 5)))


ADAPTER = UmamiAdapter()
