"""Wiki.js, against the answers of a live Wiki.js 2.5.317 (28.10.2026).

Three invented pages, an administrator and a second user, an API key with
full access. Addresses and keys are made up; the shapes are the measured ones,
the HTTP 200 on every error included.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context, Unreachable

WIKI = "http://wiki.example.com:3000"
KEY = "key-for-the-cards"
CONFIG = {"url": WIKI, "api_key": KEY}
ADAPTER = get_adapter("wikijs")

PAGES = [
    {"id": 3, "path": "recipes/soup", "locale": "en", "title": "Tomato soup", "description": "", "isPublished": True,
     "updatedAt": "2026-10-28T01:32:32.513Z"},
    {"id": 2, "path": "homelab/dns", "locale": "en", "title": "DNS notes", "description": "Two resolvers", "isPublished": True,
     "updatedAt": "2026-10-28T01:32:30.886Z"},
    {"id": 1, "path": "homelab/backups", "locale": "en", "title": "Backup plan", "description": "", "isPublished": True,
     "updatedAt": "2026-10-28T01:32:28.000Z"},
]
#: ⚠️ How a refusal looks: HTTP 200, the errors beside nulls.
AUTH_REQUIRED = {"errors": [{"message": "You must be authenticated to access this resource.", "path": ["users", "profile"],
                             "extensions": {"code": "INTERNAL_SERVER_ERROR", "exception": {"code": 1019}}}],
                 "data": {"users": {"profile": None}}}
FORBIDDEN = {"errors": [{"message": "Forbidden", "path": ["system", "info", "currentVersion"],
                         "extensions": {"code": "INTERNAL_SERVER_ERROR", "exception": {"stacktrace": ["Error: Forbidden"]}}}],
             "data": {"system": {"info": {"currentVersion": None}}}}


def server(*, admin: bool = True, latest: str = "2.5.317") -> list[str]:
    """A fake Wiki.js that answers the way the live one did, and notes the queries."""
    asked: list[str] = []

    def answer(request: httpx.Request) -> httpx.Response:
        query = json.loads(request.content)["query"]
        asked.append(query)
        # A wrong key is the guest to Wiki.js, who may read pages but is nobody.
        if "profile" in query and request.headers.get("Authorization") != f"Bearer {KEY}":
            return httpx.Response(200, json=AUTH_REQUIRED)
        if "system" in query:
            if not admin:
                return httpx.Response(200, json=FORBIDDEN)
            return httpx.Response(200, json={"data": {"system": {"info": {"currentVersion": "2.5.317", "latestVersion": latest}}}})
        if "users { list" in query:
            if not admin:
                return httpx.Response(200, json={**FORBIDDEN, "data": {"users": {"list": None}}})
            return httpx.Response(200, json={"data": {"users": {"list": [{"id": 1, "isActive": True}, {"id": 2, "isActive": True}, {"id": 3, "isActive": False}]}}})
        rows = PAGES[:2] if "limit: 2" in query else PAGES
        return httpx.Response(200, json={"data": {"users": {"profile": {"id": 1}}, "pages": {"list": rows}}})

    respx.post(f"{WIKI}/graphql").mock(side_effect=answer)
    return asked


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


@respx.mock
async def test_the_connection_test_names_the_version_and_counts_the_pages(ctx: Context) -> None:
    server()
    assert await ADAPTER.test(CONFIG, ctx) == "Wiki.js 2.5.317 answers with 3 pages."


@respx.mock
async def test_a_key_that_may_not_see_the_version_still_connects(ctx: Context) -> None:
    server(admin=False)
    assert await ADAPTER.test(CONFIG, ctx) == "Wiki.js ? answers with 3 pages."


@respx.mock
async def test_the_overview_counts_pages_and_active_users_and_names_the_version(ctx: Context) -> None:
    server()
    card = await ADAPTER.fetch("summary", CONFIG, {}, ctx)
    assert card.primary == {"label": "Pages", "value": 3}
    assert card.secondary == [
        {"label": "Users", "value": 2, "part": "users"},
        {"label": "Version", "value": "2.5.317", "part": "version"},
    ]
    assert card.status == "ok" and card.metrics == {"pages": 3.0}
    assert card.link == WIKI


@respx.mock
async def test_a_newer_version_turns_the_card_yellow(ctx: Context) -> None:
    server(latest="2.5.400")
    card = await ADAPTER.fetch("summary", CONFIG, {}, ctx)
    assert card.status == "warn"
    assert {"label": "Newer version", "value": "2.5.400", "part": "version"} in card.secondary


@respx.mock
async def test_a_key_without_administrator_rights_leaves_those_rows_out(ctx: Context) -> None:
    # ⚠️ "Forbidden" arrives as HTTP 200 too.
    server(admin=False)
    card = await ADAPTER.fetch("summary", CONFIG, {}, ctx)
    assert card.primary == {"label": "Pages", "value": 3}
    assert card.secondary == []


@respx.mock
async def test_recent_pages_are_asked_newest_first_and_link_with_their_locale(ctx: Context) -> None:
    asked = server()
    card = await ADAPTER.fetch("recent", CONFIG, {"limit": 2}, ctx)
    assert [row["title"] for row in card.items] == ["Tomato soup", "DNS notes"]
    assert card.items[0]["subtitle"] == "recipes/soup"
    assert card.items[0]["url"] == f"{WIKI}/en/recipes/soup"
    assert "orderBy: UPDATED, orderByDirection: DESC, limit: 2" in asked[0]


@respx.mock
async def test_a_wrong_key_is_refused_although_the_guest_may_read_pages(ctx: Context) -> None:
    # ⚠️ Without the profile in the query a wrong key would have shown the pages.
    asked = server()
    with pytest.raises(AuthFailed):
        await ADAPTER.fetch("summary", {**CONFIG, "api_key": "abc"}, {}, ctx)
    assert all("profile" in query for query in asked)
    with pytest.raises(AuthFailed):
        await ADAPTER.fetch("recent", {**CONFIG, "api_key": "abc"}, {}, ctx)


@respx.mock
async def test_a_refusal_with_status_200_is_not_taken_for_an_answer(ctx: Context) -> None:
    respx.post(f"{WIKI}/graphql").mock(return_value=httpx.Response(200, json=FORBIDDEN))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.fetch("recent", CONFIG, {}, ctx)
    assert caught.value.code == "forbidden"


@respx.mock
async def test_an_unreachable_service_is_reported_as_such(ctx: Context) -> None:
    respx.post(f"{WIKI}/graphql").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(Unreachable):
        await ADAPTER.fetch("summary", CONFIG, {}, ctx)


@respx.mock
async def test_another_service_behind_the_address_is_named(ctx: Context) -> None:
    respx.post(f"{WIKI}/graphql").mock(return_value=httpx.Response(200, json={"hello": "world"}))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.fetch("summary", CONFIG, {}, ctx)
    assert caught.value.code == "not_wikijs"


def test_the_demo_has_a_card_for_every_widget() -> None:
    for widget in ADAPTER.widgets:
        data: Any = ADAPTER.demo(widget.kind, {}, 3)
        assert data.primary or data.items
