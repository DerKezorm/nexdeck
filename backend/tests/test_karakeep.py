"""Karakeep, against the answers of a live Karakeep 0.33.2 (11.09.2026)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context

KK = "http://karakeep.example.com"
CONFIG = {"url": KK, "api_key": "made-up-key"}

#: Measured, trimmed of the lists by hour and by day of the week.
STATS = {"numBookmarks": 4, "numFavorites": 1, "numArchived": 1, "numTags": 1, "numLists": 1, "numHighlights": 0,
         "bookmarksByType": {"link": 3, "text": 1, "asset": 0},
         "topDomains": [{"domain": "www.debian.org", "count": 1}],
         "bookmarkingActivity": {"thisWeek": 4, "thisMonth": 4, "thisYear": 4}}


def bookmark(identifier: str, content: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {"id": identifier, "firstCreatedAt": "2026-09-11T08:52:34.000Z", "createdAt": "2026-09-11T08:52:34.000Z",
            "modifiedAt": "2026-09-11T08:52:34.000Z", "title": None, "archived": False, "favourited": False,
            "taggingStatus": "success", "summarizationStatus": None, "embeddingStatus": "pending", "note": None, "summary": None,
            "source": "api", "userId": "made-up-user", "tags": [], "content": content, "assets": [], **extra}


DEBIAN = bookmark("kmrxie", {"type": "link", "url": "https://www.debian.org/News/", "title": "Debian -- Latest News", "description": None,
                             "imageUrl": "https://www.debian.org/Pics/openlogo-50.png", "favicon": "https://www.debian.org/favicon.ico",
                             "crawledAt": "2026-09-11T08:52:36.000Z", "crawlStatus": "success"},
                  tags=[{"id": "tyyaou", "name": "homelab", "attachedBy": "human"}])
NOTE = bookmark("s733t7", {"type": "text", "text": "Remember to rotate\nthe backup disks.", "sourceUrl": None})
RENAMED = bookmark("k195ha", {"type": "link", "url": "https://example.org/", "title": "Example Domain", "crawlStatus": "success"}, title="My own title")


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


@respx.mock
async def test_recent_bookmarks_that_are_not_archived(ctx: Context) -> None:
    route = respx.get(f"{KK}/api/v1/bookmarks").mock(return_value=httpx.Response(200, json={"bookmarks": [DEBIAN, NOTE, RENAMED], "nextCursor": "k195ha_2026-09-11T08:52:34.000Z"}))
    data = await get_adapter("karakeep").fetch("recent", CONFIG, {"limit": 8}, ctx)
    sent = route.calls.last.request
    assert sent.headers["Authorization"] == "Bearer made-up-key" and dict(sent.url.params) == {"limit": "8", "archived": "false"}
    debian, note, renamed = data.items
    assert (debian["title"], debian["subtitle"], debian["url"]) == ("Debian -- Latest News", "www.debian.org · homelab", "https://www.debian.org/News/")
    # A note has no address of its own; it opens in Karakeep.
    assert (note["title"], note["subtitle"], note["url"]) == ("Remember to rotate the backup disks.", "Note", f"{KK}/dashboard/preview/s733t7")
    assert renamed["title"] == "My own title"
    assert debian["value"].endswith((" min", " h", " d"))


@respx.mock
async def test_favourites_are_asked_for_whether_archived_or_not(ctx: Context) -> None:
    route = respx.get(f"{KK}/api/v1/bookmarks").mock(return_value=httpx.Response(200, json={"bookmarks": [], "nextCursor": None}))
    data = await get_adapter("karakeep").fetch("recent", CONFIG, {"limit": 5, "favourites": True}, ctx)
    assert dict(route.calls.last.request.url.params) == {"limit": "5", "favourited": "true"}
    assert data.meta["empty"] == "No favourites yet."


@respx.mock
async def test_the_summary_counts_without_paging(ctx: Context) -> None:
    """⚠️ One call to the stats endpoint, no walk through the cursor pages."""
    stats = respx.get(f"{KK}/api/v1/users/me/stats").mock(return_value=httpx.Response(200, json=STATS))
    pages = respx.get(f"{KK}/api/v1/bookmarks").mock(return_value=httpx.Response(200, json={"bookmarks": [], "nextCursor": None}))
    data = await get_adapter("karakeep").fetch("summary", CONFIG, {}, ctx)
    assert stats.called and not pages.called
    assert data.primary == {"label": "To read", "value": 3}
    assert data.secondary == [{"label": "Bookmarks", "value": 4}, {"label": "This week", "value": 4}, {"label": "Favourites", "value": 1}]


@respx.mock
async def test_the_connection_test_a_wrong_key_and_another_service(ctx: Context) -> None:
    respx.get(f"{KK}/api/v1/users/me/stats").mock(return_value=httpx.Response(200, json=STATS))
    assert await get_adapter("karakeep").test(CONFIG, ctx) == "Karakeep answers with 4 bookmarks."
    respx.get(f"{KK}/api/v1/users/me/stats").mock(return_value=httpx.Response(401, text="Unauthorized"))
    with pytest.raises(AuthFailed):
        await get_adapter("karakeep").test(CONFIG, ctx)
    respx.get(f"{KK}/api/v1/bookmarks").mock(return_value=httpx.Response(200, json={"items": []}))
    with pytest.raises(AdapterError) as wrong:
        await get_adapter("karakeep").fetch("recent", CONFIG, {}, ctx)
    assert wrong.value.code == "not_karakeep"
