"""Readeck, against the answers of a live Readeck 0.23.5 (28.10.2026).

Three bookmarks of reserved example addresses, one archived, one favourite,
one read. Addresses and tokens are made up; the shapes are the measured
ones, the count in the header included.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context, Unreachable

RD = "http://readeck.example.com:8000"
TOKEN = "token-for-the-cards"
CONFIG = {"url": RD, "token": TOKEN}
ADAPTER = get_adapter("readeck")


def bookmark(identifier: str, title: str, site: str, created: str, **fields: Any) -> dict[str, Any]:
    entry = {"id": identifier, "href": f"{RD}/api/bookmarks/{identifier}", "created": created, "updated": created, "state": 0,
             "loaded": True, "url": f"https://{site}", "title": title, "site_name": site, "site": site, "authors": [], "lang": "en",
             "document_type": "article", "type": "article", "has_article": True, "description": "", "note": "", "is_deleted": False,
             "is_marked": False, "is_archived": False, "labels": [], "read_progress": 0, "word_count": 25}
    entry.update(fields)
    return entry


GUIDE = bookmark("S1GgbmmD5sEi5xmPNRhzBR", "IANA-managed Reserved Domains", "www.iana.org", "2026-10-28T01:45:24.032356011Z",
                 is_marked=True, reading_time=1)
EXAMPLE = bookmark("6rJg1issxNmUoeamPp5ReD", "Example Domain", "example.org", "2026-10-28T01:45:23.000000000Z", read_progress=100)
ARCHIVED = bookmark("P7psEFu9fCPZK8ZuUoyRsz", "Archived page", "example.com", "2026-10-28T01:45:22.000000000Z", is_archived=True)
ALL = [GUIDE, EXAMPLE, ARCHIVED]


def server() -> list[dict[str, str]]:
    """A fake Readeck that filters like the live one, and notes what it was asked."""
    asked: list[dict[str, str]] = []

    def answer(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/info":
            return httpx.Response(200, json={"version": {"canonical": "0.23.5", "release": "0.23.5", "build": ""}, "features": ["oauth"]})
        # ⚠️ Without Accept: application/json the live one redirected to the login page.
        if request.headers.get("Accept") != "application/json":
            return httpx.Response(303, headers={"Location": f"{RD}/login"})
        if request.headers.get("Authorization") != f"Bearer {TOKEN}":
            return httpx.Response(401, json={"status": 401, "message": "Unauthorized"})
        if path == "/api/bookmarks":
            params = dict(request.url.params)
            asked.append(params)
            rows = list(ALL)
            if params.get("read_status") == "unread":
                rows = [one for one in rows if one["read_progress"] == 0]
            if params.get("is_marked") == "true":
                rows = [one for one in rows if one["is_marked"]]
            if params.get("is_archived") in ("true", "false"):
                rows = [one for one in rows if one["is_archived"] == (params["is_archived"] == "true")]
            return httpx.Response(200, json=rows[: int(params.get("limit", 50))], headers={"Total-Count": str(len(rows))})
        return httpx.Response(404, json={"status": 404, "message": "Not Found"})

    respx.get(url__startswith=RD).mock(side_effect=answer)
    return asked


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


@respx.mock
async def test_the_connection_test_names_the_version_and_counts_the_bookmarks(ctx: Context) -> None:
    server()
    assert await ADAPTER.test(CONFIG, ctx) == "Readeck 0.23.5 answers with 3 bookmarks."


@respx.mock
async def test_the_overview_reads_the_count_from_the_header_with_one_entry_each(ctx: Context) -> None:
    asked = server()
    card = await ADAPTER.fetch("summary", CONFIG, {}, ctx)
    # ⚠️ The archive is in the total, and in the unread count too.
    assert card.primary == {"label": "Bookmarks", "value": 3}
    assert card.secondary == [
        {"label": "Unread", "value": 2, "part": "unread"},
        {"label": "Favourites", "value": 1, "part": "marked"},
        {"label": "Archived", "value": 1, "part": "archived"},
    ]
    assert card.metrics == {"bookmarks": 3.0, "unread": 2.0}
    assert card.link == f"{RD}/bookmarks"
    assert all(params["limit"] == "1" for params in asked)


@respx.mock
async def test_recent_bookmarks_leave_the_archive_out_and_name_site_and_time(ctx: Context) -> None:
    asked = server()
    card = await ADAPTER.fetch("recent", CONFIG, {"limit": 5}, ctx)
    assert [row["title"] for row in card.items] == ["IANA-managed Reserved Domains", "Example Domain"]
    assert card.items[0]["subtitle"] == "www.iana.org · 1 min"
    assert card.items[1]["subtitle"] == "example.org"
    assert card.items[0]["url"] == f"{RD}/bookmarks/S1GgbmmD5sEi5xmPNRhzBR"
    assert asked == [{"limit": "5", "sort": "-created", "is_archived": "false"}]


@respx.mock
async def test_the_reading_list_asks_for_unread_ones_only(ctx: Context) -> None:
    asked = server()
    card = await ADAPTER.fetch("recent", CONFIG, {"unread": True}, ctx)
    assert [row["title"] for row in card.items] == ["IANA-managed Reserved Domains"]
    assert asked[0]["read_status"] == "unread"
    assert card.meta["empty"] == "Nothing unread."


@respx.mock
async def test_a_wrong_token_is_an_authentication_failure(ctx: Context) -> None:
    server()
    for kind in ("summary", "recent"):
        with pytest.raises(AuthFailed):
            await ADAPTER.fetch(kind, {**CONFIG, "token": "wrong"}, {}, ctx)


@respx.mock
async def test_an_unreachable_service_is_reported_as_such(ctx: Context) -> None:
    respx.get(url__startswith=RD).mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(Unreachable):
        await ADAPTER.fetch("summary", CONFIG, {}, ctx)


@respx.mock
async def test_another_service_behind_the_address_is_named(ctx: Context) -> None:
    respx.get(url__startswith=RD).mock(return_value=httpx.Response(200, json=[]))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.fetch("summary", CONFIG, {}, ctx)
    assert caught.value.code == "not_readeck"


def test_the_demo_has_a_card_for_every_widget() -> None:
    for widget in ADAPTER.widgets:
        data: Any = ADAPTER.demo(widget.kind, {}, 3)
        assert data.primary or data.items
