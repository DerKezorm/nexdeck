"""Miniflux, against the answers of a live Miniflux 2.3.3 (11.09.2026).

Three feeds were added there; one was pointed at an address without a feed
and refreshed, which is how a feed breaks in practice.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context

MF = "http://miniflux.example.com"
CONFIG = {"url": MF, "api_key": "not-a-real-token"}


def feed(identifier: int, title: str, **extra: Any) -> dict[str, Any]:
    return {"id": identifier, "user_id": 1, "feed_url": f"https://feeds.example.com/{identifier}.xml",
            "site_url": "https://feeds.example.com/", "title": title, "checked_at": "2026-09-11T07:39:51.615681Z",
            "next_check_at": "2026-09-11T08:39:51.615681Z", "parsing_error_count": 0, "parsing_error_message": "",
            "disabled": False, "category": {"id": 1, "title": "All", "user_id": 1, "hide_globally": False}, **extra}


BLOG = feed(1, "The GitHub Blog")
NEWS = feed(2, "Debian News")
#: ⚠️ Measured after pointing a feed at an address without one and refreshing it.
BROKEN = feed(3, "Archive: 2026 - GitHub Changelog", parsing_error_count=1,
              parsing_error_message="The requested resource is not found. Please, verify the URL.")
SWITCHED_OFF = feed(4, "Old forum", parsing_error_count=7, parsing_error_message="timeout", disabled=True)

ENTRY = {"id": 10, "user_id": 1, "feed_id": 1, "status": "unread", "hash": "x", "title": "Using the diff, terminal, and browser",
         "url": "https://github.blog/ai-and-ml/diff-terminal-browser/", "comments_url": "", "published_at": "2026-09-10T21:31:19Z",
         "created_at": "2026-09-11T07:39:51Z", "changed_at": "2026-09-11T07:39:51Z", "content": "<p>…</p>", "author": "",
         "share_code": "", "starred": False, "reading_time": 3, "enclosures": [], "tags": [], "feed": BLOG}


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


@respx.mock
async def test_the_unread_list_asks_for_the_newest_first(ctx: Context) -> None:
    route = respx.get(f"{MF}/v1/entries").mock(return_value=httpx.Response(200, json={"total": 20, "entries": [ENTRY]}))
    data = await get_adapter("miniflux").fetch("unread", CONFIG, {"limit": 3}, ctx)
    sent = route.calls.last.request
    assert sent.headers["X-Auth-Token"] == "not-a-real-token"
    assert dict(sent.url.params) == {"limit": "3", "order": "published_at", "direction": "desc", "status": "unread"}
    row = data.items[0]
    assert (row["title"], row["subtitle"], row["url"]) == ("Using the diff, terminal, and browser", "The GitHub Blog", ENTRY["url"])
    assert row["value"].endswith((" min", " h", " d"))
    assert data.secondary == [{"label": "Unread", "value": 20}]
    assert data.metrics == {"unread": 20.0}
    assert data.link == f"{MF}/unread"


@respx.mock
async def test_starred_entries_are_shown_read_or_not(ctx: Context) -> None:
    route = respx.get(f"{MF}/v1/entries").mock(return_value=httpx.Response(200, json={"total": 0, "entries": []}))
    data = await get_adapter("miniflux").fetch("unread", CONFIG, {"limit": 8, "starred": True}, ctx)
    params = dict(route.calls.last.request.url.params)
    assert params["starred"] == "true" and "status" not in params
    assert data.meta["empty"] == "Nothing starred." and data.metrics == {}


@respx.mock
async def test_the_summary_counts_unread_and_failing_feeds(ctx: Context) -> None:
    respx.get(f"{MF}/v1/entries").mock(return_value=httpx.Response(200, json={"total": 20, "entries": [ENTRY]}))
    respx.get(f"{MF}/v1/feeds").mock(return_value=httpx.Response(200, json=[BLOG, NEWS, BROKEN, SWITCHED_OFF]))
    data = await get_adapter("miniflux").fetch("summary", CONFIG, {}, ctx)
    assert data.primary == {"label": "Unread", "value": 20}
    # A feed somebody switched off is not failing, however many errors it once had.
    assert data.secondary == [{"label": "Feeds", "value": 4}, {"label": "Failing", "value": 1}]
    assert data.status == "warn"
    assert data.metrics == {"unread": 20.0, "failing": 1.0}


@respx.mock
async def test_failing_feeds_carry_the_reason(ctx: Context) -> None:
    respx.get(f"{MF}/v1/feeds").mock(return_value=httpx.Response(200, json=[BLOG, BROKEN, SWITCHED_OFF]))
    data = await get_adapter("miniflux").fetch("failing", CONFIG, {"limit": 6}, ctx)
    assert [row["title"] for row in data.items] == ["Archive: 2026 - GitHub Changelog"]
    row = data.items[0]
    assert (row["subtitle"], row["status"], row["url"]) == ("The requested resource is not found. Please, verify the URL.", "bad", f"{MF}/feed/3/entries")
    respx.get(f"{MF}/v1/feeds").mock(return_value=httpx.Response(200, json=[BLOG, NEWS]))
    fresh = Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})
    calm = await get_adapter("miniflux").fetch("failing", CONFIG, {"limit": 6}, fresh)
    assert calm.items == [] and calm.status == "ok" and calm.meta["empty"] == "Every feed fetches without errors."


@respx.mock
async def test_the_connection_test_names_the_account(ctx: Context) -> None:
    respx.get(f"{MF}/v1/me").mock(return_value=httpx.Response(200, json={"id": 1, "username": "reader", "is_admin": True}))
    respx.get(f"{MF}/v1/entries").mock(return_value=httpx.Response(200, json={"total": 20, "entries": [ENTRY]}))
    assert await get_adapter("miniflux").test(CONFIG, ctx) == "Miniflux answers for reader: 20 unread."


@respx.mock
async def test_a_wrong_key_and_another_service(ctx: Context) -> None:
    """Measured: a wrong and a missing token both get 401 "access unauthorized"."""
    respx.get(f"{MF}/v1/me").mock(return_value=httpx.Response(401, json={"error_message": "access unauthorized"}))
    with pytest.raises(AuthFailed):
        await get_adapter("miniflux").test(CONFIG, ctx)
    respx.get(f"{MF}/v1/feeds").mock(return_value=httpx.Response(200, json={"feeds": []}))
    with pytest.raises(AdapterError) as wrong:
        await get_adapter("miniflux").fetch("failing", CONFIG, {}, ctx)
    assert wrong.value.code == "not_miniflux"
