"""Shlink, against the answers of a live Shlink 5.1.6 (11.09.2026)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AuthFailed, Context
from app.adapters.shlink import dead_word

SH = "http://shlink.example.com"
CONFIG = {"url": SH, "api_key": "made-up-key"}


def short(code: str, long_url: str, visits: int, bots: int = 0, *, title: str | None = None, tags: list[str] | None = None,
          until: str | None = None, since: str | None = None, most: int | None = None) -> dict[str, Any]:
    return {"shortUrl": f"{SH}/{code}", "shortCode": code, "longUrl": long_url, "dateCreated": "2026-09-11T10:58:17+00:00", "tags": tags or [],
            "meta": {"validSince": since, "validUntil": until, "maxVisits": most}, "domain": None, "title": title, "crawlable": False,
            "forwardQuery": True, "visitsSummary": {"total": visits, "nonBots": visits - bots, "bots": bots}, "hasRedirectRules": False}


#: Most visited first, as asked for. "once" was visited twice; the second visit met a 404 and was not counted here.
URLS = [
    short("wiki", "https://example.org/wiki", 3, bots=1, tags=["homelab", "notes"]),
    short("once", "https://example.com/limited", 1, most=1),
    short("GJ7gK", "https://example.com/docs", 0, title="Docs", tags=["homelab"]),
    short("gone", "https://example.net/old", 0, until="2026-01-01T00:00:00+00:00"),
]
VISITS = {"visits": {"nonOrphanVisits": {"total": 4, "nonBots": 3, "bots": 1}, "orphanVisits": {"total": 3, "nonBots": 3, "bots": 0}}}


def page(urls: list[dict[str, Any]], total: int) -> dict[str, Any]:
    return {"shortUrls": {"data": urls, "pagination": {"currentPage": 1, "pagesCount": 1, "itemsPerPage": 10, "itemsInCurrentPage": len(urls), "totalItems": total}}}


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


def test_which_short_urls_no_longer_redirect() -> None:
    now = datetime.fromisoformat("2026-09-11T11:00:00+00:00").timestamp()
    assert [dead_word(one, now) for one in URLS] == ["", "Used up", "", "Expired"]
    assert dead_word(short("soon", "https://example.com/", 0, since="2026-12-24T18:00:00+00:00"), now) == "Not yet valid"
    # The limit is not reached yet, and a date that has not come does not end anything.
    assert dead_word(short("twice", "https://example.com/", 1, most=2, until="2026-12-31T00:00:00+00:00"), now) == ""


@respx.mock
async def test_the_list_with_visits_and_the_ones_that_lead_nowhere(ctx: Context) -> None:
    route = respx.get(f"{SH}/rest/v3/short-urls").mock(return_value=httpx.Response(200, json=page(URLS, 4)))
    data = await get_adapter("shlink").fetch("urls", CONFIG, {"order": "visits", "limit": 10}, ctx)
    assert route.calls.last.request.headers["X-Api-Key"] == "made-up-key"
    assert dict(route.calls.last.request.url.params) == {"itemsPerPage": "10", "orderBy": "visits-DESC"}
    assert [(row["title"], row["subtitle"], row["status"], row["value"]) for row in data.items] == [
        ("/wiki", "example.org · homelab, notes", "ok", "3"),
        ("/once", "Used up · example.com", "unknown", "1"),
        ("Docs", "example.com · homelab", "ok", "0"),
        ("/gone", "Expired · example.net", "unknown", "0"),
    ]
    assert data.items[0]["url"] == f"{SH}/wiki" and data.secondary == [{"label": "Short URLs", "value": 4}]
    await get_adapter("shlink").fetch("urls", CONFIG, {"order": "newest", "limit": 5}, Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={}))
    assert route.calls.last.request.url.params["orderBy"] == "dateCreated-DESC"


@respx.mock
async def test_the_summary(ctx: Context) -> None:
    urls = respx.get(f"{SH}/rest/v3/short-urls").mock(return_value=httpx.Response(200, json=page(URLS[:1], 4)))
    respx.get(f"{SH}/rest/v3/visits").mock(return_value=httpx.Response(200, json=VISITS))
    data = await get_adapter("shlink").fetch("summary", CONFIG, {}, ctx)
    assert urls.calls.last.request.url.params["itemsPerPage"] == "1"
    assert data.primary == {"label": "Visits", "value": 4}
    assert data.secondary == [{"label": "Short URLs", "value": 4}, {"label": "Bots", "value": 1}, {"label": "Led nowhere", "value": 3}]
    assert data.metrics == {"visits": 4.0}


@respx.mock
async def test_a_missing_and_a_wrong_key(ctx: Context) -> None:
    respx.get(f"{SH}/rest/v3/short-urls").mock(return_value=httpx.Response(401, json={
        "title": "Invalid API key", "type": "https://shlink.io/api/error/invalid-api-key", "status": 401}))
    with pytest.raises(AuthFailed):
        await get_adapter("shlink").test(CONFIG, ctx)


@respx.mock
async def test_the_connection_test(ctx: Context) -> None:
    respx.get(f"{SH}/rest/v3/short-urls").mock(return_value=httpx.Response(200, json=page(URLS[:1], 4)))
    assert await get_adapter("shlink").test(CONFIG, ctx) == "Shlink answers with 4 short URLs."
