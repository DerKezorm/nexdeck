"""BookStack, against the answers of a live BookStack v26.09.2 (28.10.2026).

Two books, a chapter, two pages and a shelf, all invented. Addresses and
tokens are made up; the shapes are the measured ones.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context, Unreachable

BS = "http://bookstack.example.com:6875"
CONFIG = {"url": BS, "token_id": "id-for-the-cards", "token_secret": "secret-for-the-cards"}
ADAPTER = get_adapter("bookstack")

BOOKS = [
    {"id": 1, "slug": "homelab-guide", "name": "Homelab Guide", "description": "", "created_at": "2026-10-28T01:27:05.000000Z"},
    {"id": 2, "slug": "recipes", "name": "Recipes", "description": "", "created_at": "2026-10-28T01:27:05.000000Z"},
]
PAGES = [
    {"name": "DNS notes", "id": 4, "slug": "dns-notes", "book_id": 1, "chapter_id": None, "draft": False, "template": False,
     "created_at": "2026-10-28T01:27:06.000000Z", "updated_at": "2026-10-28T01:27:06.000000Z", "priority": 3, "owned_by": 1,
     "book_slug": "homelab-guide", "created_by": 1, "updated_by": 1, "revision_count": 1, "editor": "wysiwyg"},
    {"name": "Tomato soup", "id": 5, "slug": "tomato-soup", "book_id": 2, "chapter_id": None, "draft": False, "template": False,
     "created_at": "2026-10-27T01:27:06.000000Z", "updated_at": "2026-10-27T01:27:06.000000Z", "priority": 2, "owned_by": 1,
     "book_slug": "recipes", "created_by": 1, "updated_by": 1, "revision_count": 1, "editor": "markdown"},
]
CHAPTERS = [{"id": 3, "slug": "backups", "name": "Backups", "book_id": 1, "book_slug": "homelab-guide"}]
SHELVES = [{"id": 6, "slug": "everything", "name": "Everything"}]
LISTS = {"/api/pages": PAGES, "/api/books": BOOKS, "/api/chapters": CHAPTERS, "/api/shelves": SHELVES}


def server() -> dict[str, list[dict[str, str]]]:
    """A fake BookStack that pages the way the live one did, and notes what it was asked."""
    asked: dict[str, list[dict[str, str]]] = {}

    def answer(request: httpx.Request) -> httpx.Response:
        if request.headers.get("Authorization") != "Token id-for-the-cards:secret-for-the-cards":
            return httpx.Response(401, json={"error": {"message": "No matching API token was found for the provided authorization token", "code": 401}})
        path = request.url.path
        params = dict(request.url.params)
        asked.setdefault(path, []).append(params)
        if path == "/api/system":
            return httpx.Response(200, json={"version": "v26.09.2", "instance_id": "x", "app_name": "BookStack", "base_url": BS})
        if path in LISTS:
            rows = LISTS[path]
            return httpx.Response(200, json={"data": rows[: int(params.get("count", 100))], "total": len(rows)})
        return httpx.Response(404, json={"error": {"message": "The requested resource could not be found.", "code": 404}})

    respx.get(url__startswith=BS).mock(side_effect=answer)
    return asked


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


@respx.mock
async def test_the_connection_test_names_the_version_and_counts_the_pages(ctx: Context) -> None:
    server()
    assert await ADAPTER.test(CONFIG, ctx) == "BookStack v26.09.2 answers with 2 pages."


@respx.mock
async def test_the_overview_counts_by_asking_for_one_entry_each(ctx: Context) -> None:
    asked = server()
    card = await ADAPTER.fetch("summary", CONFIG, {}, ctx)
    assert card.primary == {"label": "Pages", "value": 2}
    assert card.secondary == [
        {"label": "Books", "value": 2, "part": "books"},
        {"label": "Chapters", "value": 1, "part": "chapters"},
        {"label": "Shelves", "value": 1, "part": "shelves"},
    ]
    assert card.metrics == {"pages": 2.0}
    assert card.link == BS
    # ⚠️ The total stands beside the page, so one entry is enough.
    assert all(params == {"count": "1"} for path, calls in asked.items() if path != "/api/system" for params in calls)


@respx.mock
async def test_recent_pages_name_their_book_and_link_to_the_page(ctx: Context) -> None:
    asked = server()
    card = await ADAPTER.fetch("recent", CONFIG, {"limit": 5}, ctx)
    assert [row["title"] for row in card.items] == ["DNS notes", "Tomato soup"]
    # ⚠️ The list carries only the id of the book.
    assert [row["subtitle"] for row in card.items] == ["Homelab Guide", "Recipes"]
    assert card.items[0]["url"] == f"{BS}/books/homelab-guide/page/dns-notes"
    assert card.items[0]["value"].endswith(("min", "h", "d"))
    assert asked["/api/pages"] == [{"count": "5", "sort": "-updated_at"}]


@respx.mock
async def test_a_wrong_token_is_an_authentication_failure(ctx: Context) -> None:
    server()
    with pytest.raises(AuthFailed):
        await ADAPTER.fetch("summary", {**CONFIG, "token_secret": "wrong"}, {}, ctx)


@respx.mock
async def test_an_unreachable_service_is_reported_as_such(ctx: Context) -> None:
    respx.get(url__startswith=BS).mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(Unreachable):
        await ADAPTER.fetch("summary", CONFIG, {}, ctx)


@respx.mock
async def test_another_service_behind_the_address_is_named(ctx: Context) -> None:
    respx.get(url__startswith=BS).mock(return_value=httpx.Response(200, json={"hello": "world"}))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.fetch("summary", CONFIG, {}, ctx)
    assert caught.value.code == "not_bookstack"


def test_the_demo_has_a_card_for_every_widget() -> None:
    for widget in ADAPTER.widgets:
        data: Any = ADAPTER.demo(widget.kind, {}, 3)
        assert data.primary or data.items
