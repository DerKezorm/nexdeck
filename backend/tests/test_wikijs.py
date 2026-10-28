"""Wiki.js, against the answers of a live Wiki.js 2.5.317 (28.10.2026).

Three invented pages, an administrator and a second user, an API key with
full access. Addresses and keys are made up; the shapes are the measured ones,
the HTTP 200 on every error included. The comments were measured the same day
on the same version: comments by two users, keys whose group may read the
comments of some pages only or of none.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
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


# -- comments, against the answers of the same Wiki.js (28.10.2026) ----------

#: Comments as Wiki.js hands them over: ``render`` is HTML, what the author
#: typed as HTML arrives escaped.
COMMENTS = {
    "homelab/backups": [{"id": 1, "authorName": "Administrator", "createdAt": "2026-10-28T19:48:17.985Z",
                         "render": "<p>The second disk is <strong>full</strong> again, see &lt;b&gt;log&lt;/b&gt; &amp; check.</p>\n<p>Next line here.</p>\n"}],
    "recipes/soup": [{"id": 2, "authorName": "Sam Example", "createdAt": "2026-10-28T19:50:07.456Z",
                      "render": "<p>Less salt next time.</p>\n"}],
    "homelab/rack": [{"id": 3, "authorName": "Sam Example", "createdAt": "2026-10-28T19:52:40.101Z",
                      "render": "<p>Shelf three is free now.</p>\n"}],
}
#: A page whose comments the key may not read, and a key without the right at all.
NOT_THIS_PAGE = {"message": "You are not authorized to view comments for this page.",
                 "extensions": {"code": "INTERNAL_SERVER_ERROR", "exception": {"code": 8006}}}
NO_COMMENTS = {"message": "Forbidden", "extensions": {"code": "INTERNAL_SERVER_ERROR", "exception": {}}}


def wiki_pages(count: int) -> list[dict[str, Any]]:
    """``count`` pages, the first changed last, as ``pages.list`` answers them."""
    start = datetime(2026, 10, 28, 20, 0, tzinfo=UTC)
    return [{"id": number, "path": f"notes/page-{number}", "locale": "en", "title": f"Page {number}",
             "updatedAt": (start - timedelta(minutes=number)).strftime("%Y-%m-%dT%H:%M:%S.000Z")}
            for number in range(1, count + 1)]


def comment_server(pages: list[dict[str, Any]], comments: dict[str, list[dict[str, Any]]], *,
                   refused: tuple[str, ...] = (), no_right: bool = False) -> list[dict[str, Any]]:
    """A fake Wiki.js for the comments card; notes every request body."""
    asked: list[dict[str, Any]] = []

    def answer(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        asked.append(body)
        query, variables = body["query"], body.get("variables") or {}
        # A wrong key is the guest, who may read comments; only the profile tells.
        guest = request.headers.get("Authorization") != f"Bearer {KEY}"
        data: dict[str, Any] = {}
        errors: list[dict[str, Any]] = []
        if "profile" in query:
            data["users"] = {"profile": None if guest else {"id": 1}}
            errors += [AUTH_REQUIRED["errors"][0]] if guest else []
        if "pages { list" in query:
            data["pages"] = {"list": pages}
            return httpx.Response(200, json={"data": data, **({"errors": errors} if errors else {})})
        for name in sorted(key for key in variables if key.startswith("p")):
            alias, path = f"c{name[1:]}", variables[name]
            # ⚠️ Measured: a refused page nulls its own `comments`, the others stand.
            if no_right or path in refused:
                data[alias] = None
                errors.append({**(NO_COMMENTS if no_right else NOT_THIS_PAGE), "path": [alias, "list"]})
            else:
                data[alias] = {"list": comments.get(path, [])}
        return httpx.Response(200, json={"data": data, **({"errors": errors} if errors else {})})

    respx.post(f"{WIKI}/graphql").mock(side_effect=answer)
    return asked


RACK = {"id": 5, "path": "homelab/rack", "locale": "en", "title": "Rack layout", "updatedAt": "2026-10-28T19:51:00.000Z"}


@respx.mock
async def test_the_newest_comments_come_first_with_their_page_author_and_a_link_to_the_discussion(ctx: Context) -> None:
    asked = comment_server([RACK, *PAGES], COMMENTS)
    card = await ADAPTER.fetch("comments", CONFIG, {"limit": 2}, ctx)
    assert [row["id"] for row in card.items] == [3, 2]
    assert card.items[0]["title"] == "Shelf three is free now."
    assert card.items[0]["subtitle"] == "Sam Example · Rack layout"
    # ⚠️ Measured: #comment-post-id-3 does nothing on a fresh page, #discussion scrolls there.
    assert card.items[0]["url"] == f"{WIKI}/en/homelab/rack#discussion"
    assert card.items[0]["value"] != ""
    assert "notice" not in card.meta
    # The page list, then one request for the comments of all four pages, paths as variables.
    assert len(asked) == 2
    assert sorted(value for key, value in asked[1]["variables"].items() if key.startswith("p")) == sorted(
        page["path"] for page in [RACK, *PAGES])
    assert "profile" in asked[1]["query"]


@respx.mock
async def test_a_comment_is_one_line_of_plain_text_cut_short(ctx: Context) -> None:
    long = {"id": 9, "authorName": "Sam Example", "createdAt": "2026-10-28T19:59:00.000Z",
            "render": "<p>" + "word " * 60 + "</p>"}
    comment_server(PAGES, {**COMMENTS, "recipes/soup": [long]})
    card = await ADAPTER.fetch("comments", CONFIG, {}, ctx)
    rows = {row["id"]: row for row in card.items}
    # Tags gone, what the author typed as HTML stays as written, entities read.
    assert rows[1]["title"] == "The second disk is full again, see <b>log</b> & check. Next line here."
    assert len(rows[9]["title"]) == 160 and rows[9]["title"].endswith("…")


@respx.mock
async def test_one_page_with_comments_the_key_may_not_read_leaves_the_others(ctx: Context) -> None:
    asked = comment_server(PAGES, COMMENTS, refused=("homelab/backups",))
    card = await ADAPTER.fetch("comments", CONFIG, {}, ctx)
    assert [row["id"] for row in card.items] == [2]
    # ⚠️ Every page under a `comments` of its own, or one refusal nulls them all.
    assert asked[1]["query"].count("comments {") == len(PAGES)


@respx.mock
async def test_a_key_that_may_not_read_comments_is_told_so(ctx: Context) -> None:
    comment_server(PAGES, COMMENTS, no_right=True)
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.fetch("comments", CONFIG, {}, ctx)
    assert caught.value.code == "forbidden"
    assert "comments" in str(caught.value)


@respx.mock
async def test_a_wrong_key_is_refused_although_the_guest_may_read_comments(ctx: Context) -> None:
    comment_server(PAGES, COMMENTS)
    with pytest.raises(AuthFailed):
        await ADAPTER.fetch("comments", {**CONFIG, "api_key": "abc"}, {}, ctx)


@respx.mock
async def test_a_second_comment_card_within_the_round_asks_nothing(ctx: Context) -> None:
    asked = comment_server(PAGES, COMMENTS)
    await ADAPTER.fetch("comments", CONFIG, {"limit": 8}, ctx)
    count = len(asked)
    card = await ADAPTER.fetch("comments", CONFIG, {"limit": 1}, ctx)
    assert len(asked) == count
    assert [row["id"] for row in card.items] == [2]


@respx.mock
async def test_a_large_wiki_is_read_in_capped_rounds_until_every_page_had_its_turn(ctx: Context) -> None:
    pages = wiki_pages(230)
    oldest = pages[-1]["path"]
    asked = comment_server(pages, {
        "notes/page-1": [{"id": 1, "authorName": "Sam Example", "createdAt": "2026-10-28T10:00:00.000Z", "render": "<p>New page.</p>"}],
        oldest: [{"id": 2, "authorName": "Robin Sample", "createdAt": "2026-10-28T12:00:00.000Z", "render": "<p>Old page.</p>"}],
    })
    seen: list[set[str]] = []
    for _round in range(4):
        asked.clear()
        card = await ADAPTER.fetch("comments", CONFIG, {}, ctx)
        # The page list and two requests of at most fifty pages, never more.
        assert len(asked) == 3
        paths = [{value for key, value in body["variables"].items() if key.startswith("p")} for body in asked[1:]]
        assert all(len(batch) <= 50 for batch in paths)
        seen.append(set().union(*paths))
        ctx.cache["wikijs.comments"]["at"] = None
        if _round < 3:
            assert card.meta.get("notice"), _round
            assert [row["id"] for row in card.items] == [1]
    # The fifty pages changed last every round, the others in turn, all of them by the fourth.
    newest = {page["path"] for page in pages[:50]}
    assert all(newest <= one for one in seen)
    assert set().union(*seen) == {page["path"] for page in pages}
    assert [row["id"] for row in card.items] == [2, 1]
    assert "notice" not in card.meta


@respx.mock
async def test_a_page_that_is_gone_takes_its_comments_with_it(ctx: Context) -> None:
    pages = list(PAGES)
    comment_server(pages, COMMENTS)
    assert [row["id"] for row in (await ADAPTER.fetch("comments", CONFIG, {}, ctx)).items] == [2, 1]
    ctx.cache["wikijs.comments"]["at"] = None
    pages.remove(PAGES[2])
    card = await ADAPTER.fetch("comments", CONFIG, {}, ctx)
    assert [row["id"] for row in card.items] == [2]


def test_the_demo_has_a_card_for_every_widget() -> None:
    for widget in ADAPTER.widgets:
        data: Any = ADAPTER.demo(widget.kind, {}, 3)
        assert data.primary or data.items
