"""Shlink: which short URLs get visited, and which of them no longer lead anywhere.

Measured against Shlink 5.1.6 on 11.09.2026, with four short URLs: one tagged
and visited three times (once with a crawler's user agent), one limited to a
single visit and visited twice, one whose validity had ended, and one never
visited, plus a visit to a code that does not exist.

⚠️ A short URL that reached its maximum of visits, or whose validity ended,
answers 404 and stays in the list as if nothing happened. The visit that met
the 404 is not counted for it; it counts as an orphan visit of the type
``invalid_short_url``. The cards work out from ``meta`` which ones still lead
somewhere.

⚠️ A missing and a wrong key both get 401, told apart only by the error type.
"""

from __future__ import annotations

import time
from datetime import datetime
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
    base_url,
)

ORDER = {"visits": "visits-DESC", "newest": "dateCreated-DESC"}


def _moment(raw: Any) -> float | None:
    try:
        return datetime.fromisoformat(str(raw)).timestamp() if raw else None
    except ValueError:
        return None


def dead_word(short: dict[str, Any], now: float) -> str:
    """Why a short URL no longer redirects, or ``""`` while it does."""
    meta = short.get("meta") if isinstance(short.get("meta"), dict) else {}
    until, since = _moment(meta.get("validUntil")), _moment(meta.get("validSince"))
    visits = short.get("visitsSummary") if isinstance(short.get("visitsSummary"), dict) else {}
    most = meta.get("maxVisits")
    if until is not None and until < now:
        return "Expired"
    if since is not None and since > now:
        return "Not yet valid"
    if isinstance(most, int) and int(visits.get("total") or 0) >= most:
        return "Used up"
    return ""


class ShlinkAdapter(Adapter):
    kind = "shlink"
    label = "Shlink"
    category = "network"
    description = "Which short URLs get visited, and which of them no longer lead anywhere."
    icon = "shlink"
    beta = False
    docs_url = "https://api-spec.shlink.io/"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://shlink:8080"),
        Field("api_key", "API key", type="password", secret=True, required=True,
              help="Made with shlink api-key:generate inside the container, or given as INITIAL_API_KEY."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(kind="urls", label="Short URLs", description="Short URLs with their visits; the ones that no longer redirect say why.",
                   renderer="list", default_size=(3, 3), refresh_seconds=300,
                   options=(Field("order", "Order", type="select", default="visits", options=(("visits", "Most visited"), ("newest", "Newest"))),
                            Field("limit", "Entries", type="number", default=10))),
        WidgetType(kind="summary", label="Visits", description="Visits to all short URLs, how many there are, and visits that led nowhere.",
                   renderer="value", default_size=(3, 2), refresh_seconds=300, metrics=("visits",)),
    )

    async def _json(self, config: dict[str, Any], ctx: Context, path: str, params: dict[str, Any] | None = None, cache: float = 10) -> Any:
        response = await ctx.request(
            "GET", f"{base_url(config)}/rest/v3{path}", headers={"X-Api-Key": str(config.get("api_key") or "")},
            params=params, verify=not config.get("insecure"), cache_seconds=cache, auth_errors=False,
        )
        if response.status_code in (401, 403):
            raise AuthFailed("Shlink rejected the API key.")
        if response.status_code >= 400:
            raise AdapterError(f"Shlink answered with HTTP {response.status_code}.", code="http_error",
                               hint="Check the URL; it is the address of Shlink itself, without /rest.")
        try:
            answer = response.json()
        except ValueError as error:
            raise AdapterError("Shlink did not answer with JSON.", code="not_json",
                               hint="The URL probably points at something else than Shlink.") from error
        if not isinstance(answer, dict):
            raise AdapterError("This address answers, but not the way Shlink does.", code="not_shlink")
        return answer

    async def _short_urls(self, config: dict[str, Any], ctx: Context, per_page: int, order: str) -> dict[str, Any]:
        answer = await self._json(config, ctx, "/short-urls", {"itemsPerPage": per_page, "orderBy": ORDER.get(order, ORDER["visits"])})
        page = answer.get("shortUrls")
        if not isinstance(page, dict) or not isinstance(page.get("data"), list):
            raise AdapterError("This address answers, but not the way Shlink does.", code="not_shlink")
        return page

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        page = await self._short_urls(config, ctx, 1, "newest")
        total = int((page.get("pagination") or {}).get("totalItems") or 0)
        return f"Shlink answers with {total} short URLs."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "summary":
            page = await self._short_urls(config, ctx, 1, "newest")
            visits = await self._json(config, ctx, "/visits")
            return self._summary(page, visits)
        limit = max(1, int(options.get("limit") or 10))
        page = await self._short_urls(config, ctx, limit, str(options.get("order") or "visits"))
        return self._list(page, time.time())

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def _list(page: dict[str, Any], now: float) -> WidgetData:
        items = []
        for short in page["data"]:
            if not isinstance(short, dict):
                continue
            dead = dead_word(short, now)
            host = urlsplit(str(short.get("longUrl") or "")).hostname or ""
            tags = ", ".join(str(tag) for tag in (short.get("tags") or [])[:3])
            visits = short.get("visitsSummary") if isinstance(short.get("visitsSummary"), dict) else {}
            row: dict[str, Any] = {
                "title": str(short.get("title") or f"/{short.get('shortCode') or '?'}"),
                "subtitle": " · ".join(part for part in (dead, host, tags) if part),
                # Nothing is broken: the limit or the date was set on purpose.
                "status": "unknown" if dead else "ok",
                "value": str(int(visits.get("total") or 0)),
            }
            if short.get("shortUrl"):
                row["url"] = str(short["shortUrl"])
            items.append(row)
        total = int((page.get("pagination") or {}).get("totalItems") or len(items))
        return WidgetData(
            status="ok",
            items=items,
            secondary=[{"label": "Short URLs", "value": total}],
            meta={"empty": "No short URLs yet."},
        )

    @staticmethod
    def _summary(page: dict[str, Any], visits: dict[str, Any]) -> WidgetData:
        counts = visits.get("visits") if isinstance(visits.get("visits"), dict) else {}
        real = counts.get("nonOrphanVisits") if isinstance(counts.get("nonOrphanVisits"), dict) else {}
        orphan = counts.get("orphanVisits") if isinstance(counts.get("orphanVisits"), dict) else {}
        total = int(real.get("total") or 0)
        secondary: list[dict[str, Any]] = [{"label": "Short URLs", "value": int((page.get("pagination") or {}).get("totalItems") or 0)}]
        secondary += [{"label": label, "value": value} for label, value in
                      (("Bots", int(real.get("bots") or 0)), ("Led nowhere", int(orphan.get("total") or 0))) if value]
        return WidgetData(
            status="ok",
            primary={"label": "Visits", "value": total},
            secondary=secondary,
            metrics={"visits": float(total)},
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        now = time.time()
        page = {"pagination": {"totalItems": 38}, "data": [
            {"shortCode": "wiki", "longUrl": "https://wiki.example.com/start", "tags": ["homelab"], "meta": {}, "shortUrl": "https://s.example.com/wiki",
             "visitsSummary": {"total": 412 + tick % 5}},
            {"shortCode": "status", "title": "Status page", "longUrl": "https://status.example.com/", "tags": [], "meta": {}, "shortUrl": "https://s.example.com/status",
             "visitsSummary": {"total": 190}},
            {"shortCode": "party", "longUrl": "https://photos.example.com/album/summer", "tags": ["family"], "meta": {"validUntil": "2026-08-31T23:59:59+00:00"},
             "shortUrl": "https://s.example.com/party", "visitsSummary": {"total": 57}},
        ]}
        if widget_kind == "summary":
            return self._summary(page, {"visits": {"nonOrphanVisits": {"total": 2_918 + tick % 9, "bots": 211}, "orphanVisits": {"total": 64}}})
        return self._list(page, now)


ADAPTER = ShlinkAdapter()
