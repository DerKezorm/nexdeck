"""Linkding, against the answers of a live Linkding 1.47.0 (27.09.2026).

A superuser with five invented bookmarks (two unread, two shared, one
archived, one saved without a title) and a second account with one of its
own. Addresses and tokens are made up; the shapes are the measured ones.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context, Unreachable

LD = "http://linkding.example.com:9090"
TOKEN = "ld-test-token-for-the-cards"
CONFIG = {"url": LD, "token": TOKEN}
ADAPTER = get_adapter("linkding")


def bookmark(identifier: int, url: str, title: str, tags: list[str], **fields: Any) -> dict[str, Any]:
    entry = {"id": identifier, "url": url, "title": title, "description": "", "notes": "",
             "web_archive_snapshot_url": f"https://web.archive.org/web/20260927083815/{url}", "favicon_url": None,
             "preview_image_url": None, "is_archived": False, "unread": False, "shared": False, "tag_names": tags,
             "date_added": "2026-09-27T08:38:15.714213Z", "date_modified": "2026-09-27T08:38:15.714221Z",
             "website_title": None, "website_description": None}
    entry.update(fields)
    return entry


DNS = bookmark(4, "https://wiki.example.org/dns", "DNS cheat sheet", ["dns", "network", "reference"], date_added="2026-09-25T08:40:00Z")
#: ⚠️ Saved without scraping: the title is an empty string.
UNTITLED = bookmark(3, "https://news.example.com/proxy-notes", "", [], unread=True, shared=True)
ZFS = bookmark(2, "https://blog.example.com/zfs-small-machine", "ZFS on a small machine", ["storage"], shared=True)
BACKUP = bookmark(1, "https://docs.example.com/backup-guide", "Backup guide", ["backup", "homelab"], unread=True)
ARCHIVED = bookmark(5, "https://old.example.net/archived-page", "An old page", ["old"], is_archived=True)
ACTIVE = [DNS, UNTITLED, ZFS, BACKUP]
PROFILE = {"theme": "auto", "bookmark_date_display": "relative", "bookmark_link_target": "_blank", "web_archive_integration": "disabled",
           "tag_search": "strict", "enable_sharing": False, "enable_public_sharing": False, "enable_favicons": False, "display_url": False,
           "permanent_notes": False, "search_preferences": {}, "version": "1.47.0"}


def page(results: list[dict[str, Any]], limit: int) -> dict[str, Any]:
    return {"count": len(results), "next": None, "previous": None, "results": results[:limit]}


def server(*, sharing: bool = False) -> dict[str, list[dict[str, str]]]:
    """A fake Linkding that filters the way the live one did, and notes what it was asked."""
    asked: dict[str, list[dict[str, str]]] = {}

    def answer(request: httpx.Request) -> httpx.Response:
        if request.headers.get("Authorization") != f"Token {TOKEN}":
            return httpx.Response(401, json={"detail": "Invalid token."})
        path = request.url.path
        params = dict(request.url.params)
        asked.setdefault(path, []).append(params)
        limit = int(params.get("limit", 100))
        if path == "/api/user/profile/":
            return httpx.Response(200, json={**PROFILE, "enable_sharing": sharing})
        if path == "/api/tags/":
            return httpx.Response(200, json=page([{"id": n, "name": f"tag{n}", "date_added": "2026-09-27T08:38:15Z"} for n in range(7)], limit))
        if path == "/api/bookmarks/archived/":
            return httpx.Response(200, json=page([ARCHIVED], limit))
        if path == "/api/bookmarks/":
            chosen = ACTIVE
            if params.get("q") == "!unread":
                chosen = [one for one in chosen if one["unread"]]
            if params.get("shared") == "yes":
                chosen = [one for one in chosen if one["shared"]]
            return httpx.Response(200, json=page(chosen, limit))
        return httpx.Response(404, text="<h1>Not Found</h1>")

    respx.get(url__startswith=LD).mock(side_effect=answer)
    return asked


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


@respx.mock
async def test_the_connection_test_names_the_version_and_counts_the_archive_too(ctx: Context) -> None:
    asked = server()
    assert await ADAPTER.test(CONFIG, ctx) == "Linkding 1.47.0 answers with 5 bookmarks."
    assert asked["/api/bookmarks/"] == [{"limit": "1"}]


@respx.mock
async def test_the_overview_adds_the_archive_and_asks_for_one_entry_each(ctx: Context) -> None:
    asked = server()
    card = await ADAPTER.fetch("summary", CONFIG, {}, ctx)
    # ⚠️ /api/bookmarks/ leaves the archived one out: four plus one.
    assert card.primary == {"label": "Bookmarks", "value": 5}
    assert card.secondary == [
        {"label": "Unread", "value": 2, "part": "unread"},
        {"label": "Archived", "value": 1, "part": "archived"},
        {"label": "Tags", "value": 7, "part": "tags"},
    ]
    assert card.metrics == {"bookmarks": 5.0}
    assert card.link == f"{LD}/bookmarks"
    # ⚠️ Unread by the search that older versions know too.
    assert {"limit": "1", "q": "!unread"} in asked["/api/bookmarks/"]
    assert all(params.get("limit") == "1" for params in asked["/api/bookmarks/"])


@respx.mock
async def test_shared_is_counted_only_while_sharing_is_on(ctx: Context) -> None:
    # ⚠️ The flag is set on two, but with sharing off nobody sees them.
    asked = server(sharing=False)
    card = await ADAPTER.fetch("summary", CONFIG, {}, ctx)
    assert "shared" not in {row["part"] for row in card.secondary}
    assert not any(params.get("shared") for params in asked["/api/bookmarks/"])
    ctx.cache.clear()
    server(sharing=True)
    card = await ADAPTER.fetch("summary", CONFIG, {}, ctx)
    assert {row["part"]: row["value"] for row in card.secondary} == {"unread": 2, "archived": 1, "shared": 2, "tags": 7}


@respx.mock
async def test_recent_bookmarks_with_host_tags_and_age(ctx: Context) -> None:
    server()
    card = await ADAPTER.fetch("recent", CONFIG, {"limit": 3}, ctx)
    assert [(row["title"], row["subtitle"], row["url"]) for row in card.items] == [
        ("DNS cheat sheet", "wiki.example.org · dns, network, reference", "https://wiki.example.org/dns"),
        # ⚠️ No title: the host stands in, and is not repeated under it.
        ("news.example.com", "", "https://news.example.com/proxy-notes"),
        ("ZFS on a small machine", "blog.example.com · storage", "https://blog.example.com/zfs-small-machine"),
    ]
    assert card.items[0]["value"].endswith(" d")
    assert card.meta["empty"] == "No bookmarks saved yet."


@respx.mock
async def test_only_unread_asks_linkding_to_filter(ctx: Context) -> None:
    asked = server()
    card = await ADAPTER.fetch("recent", CONFIG, {"unread": True, "limit": 5}, ctx)
    assert asked["/api/bookmarks/"] == [{"limit": "5", "q": "!unread"}]
    assert [row["title"] for row in card.items] == ["news.example.com", "Backup guide"]
    assert card.meta["empty"] == "Nothing unread."


def test_a_title_from_the_scraper_is_the_next_best() -> None:
    card = ADAPTER._recent([bookmark(9, "https://example.com/", "", ["test"], website_title="Example Domain")], False, LD)
    assert card.items[0]["title"] == "Example Domain"
    assert card.items[0]["subtitle"] == "example.com · test"


@respx.mock
async def test_a_wrong_token_is_a_refusal(ctx: Context) -> None:
    server()
    with pytest.raises(AuthFailed, match="rejected the API token"):
        await ADAPTER.test({**CONFIG, "token": "ld-wrong-token-for-the-cards"}, ctx)


@respx.mock
async def test_the_api_path_typed_into_the_address_is_named(ctx: Context) -> None:
    server()
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.fetch("recent", {**CONFIG, "url": f"{LD}/api"}, {}, ctx)
    assert caught.value.code == "http_error" and "without /api" in caught.value.hint


@respx.mock
async def test_a_login_page_is_not_linkding(ctx: Context) -> None:
    respx.get(url__startswith=LD).mock(return_value=httpx.Response(200, text="<html>sign in</html>"))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.fetch("summary", CONFIG, {}, ctx)
    assert caught.value.code == "not_json"
    respx.get(url__startswith=LD).mock(return_value=httpx.Response(200, json={"status": "healthy"}))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.fetch("recent", CONFIG, {}, ctx)
    assert caught.value.code == "not_linkding"


@respx.mock
async def test_linkding_out_of_reach(ctx: Context) -> None:
    respx.get(url__startswith=LD).mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(Unreachable):
        await ADAPTER.fetch("summary", CONFIG, {}, ctx)


@pytest.mark.parametrize("kind", [widget.kind for widget in ADAPTER.widgets])
def test_demo_has_every_card(kind: str) -> None:
    for tick in range(4):
        card = ADAPTER.demo(kind, {}, tick)
        assert card.items or card.primary
