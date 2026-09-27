"""FreshRSS, against the answers of a live FreshRSS 1.30.0 (27.09.2026).

Google Reader API with two accounts; four invented feeds in two categories
next to the feed of FreshRSS releases every new account starts with, one
entry starred and read. Names, addresses and the token are made up; the
shapes, status codes and bodies are the measured ones.
"""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context, Unreachable

FR = "http://freshrss.example.com"
API = f"{FR}/api/greader.php"
PASSWORD = "fr-api-password-for-the-cards"
TOKEN = "curator/fr-test-token-for-the-cards"
CONFIG = {"url": FR, "username": "curator", "api_password": PASSWORD}
ADAPTER = get_adapter("freshrss")
NOW = 1790498700.0
READING_LIST = "user/-/state/com.google/reading-list"

UNREAD_COUNT = {"max": 15, "unreadcounts": [
    {"id": "feed/5", "count": 0, "newestItemTimestampUsec": "0"},
    {"id": "feed/4", "count": 1, "newestItemTimestampUsec": "1790498593412269"},
    {"id": "user/-/label/Hobby", "count": 1, "newestItemTimestampUsec": "1790498593412269"},
    {"id": "feed/2", "count": 2, "newestItemTimestampUsec": "1790498593412271"},
    {"id": "feed/3", "count": 2, "newestItemTimestampUsec": "1790498593412270"},
    {"id": "user/-/label/Tech", "count": 4, "newestItemTimestampUsec": "1790498593412271"},
    {"id": "feed/1", "count": 10, "newestItemTimestampUsec": "1790498569224352"},
    {"id": "user/-/label/Uncategorized", "count": 10, "newestItemTimestampUsec": "1790498569224352"},
    {"id": READING_LIST, "count": 15, "newestItemTimestampUsec": "1790498593412271"},
]}


def subscription(number: int, title: str, category: str) -> dict[str, Any]:
    return {"id": f"feed/{number}", "title": title, "categories": [{"id": f"user/-/label/{category}", "label": category}],
            "url": f"https://feeds.example.com/{number}.xml", "htmlUrl": f"https://site{number}.example.com/",
            "iconUrl": f"{FR}/f.php?h=feed{number}", "frss:priority": "main"}


SUBSCRIPTIONS = {"subscriptions": [
    subscription(1, "Project releases", "Uncategorized"),
    subscription(2, "Homelab Weekly", "Tech"),
    subscription(3, "Storage Corner", "Tech"),
    subscription(4, "Garden Log", "Hobby"),
    # ⚠️ Answers without a feed, and looks like any other subscription.
    subscription(5, "Broken Feed", "Hobby"),
]}


def item(title: str, feed: int, feed_title: str, published: int, *states: str) -> dict[str, Any]:
    link = f"https://site{feed}.example.com/{title.lower().replace(' ', '-')}"
    return {"id": f"tag:google.com,2005:reader/item/{feed:016x}", "crawlTimeMsec": "1790498593412", "timestampUsec": "1790498593412271",
            "published": published, "title": title, "canonical": [{"href": link}], "alternate": [{"href": link}],
            "categories": [READING_LIST, "user/-/label/Tech", "user/-/state/org.freshrss/main", *states],
            "origin": {"streamId": f"feed/{feed}", "htmlUrl": f"https://site{feed}.example.com/", "title": feed_title},
            "summary": {"content": f"Body of {title}"}}


#: Published an hour, two and three before the test runs, in seconds.
FRESH = int(time.time())
UNREAD_STREAM = {"id": READING_LIST, "updated": 1790498627, "continuation": "1790498593412269", "items": [
    item("Proxmox cluster notes", 2, "Homelab Weekly", FRESH - 3600 - 60),
    item("ZFS on a small machine", 3, "Storage Corner", FRESH - 7200 - 60),
    item("Tomatoes in September", 4, "Garden Log", FRESH - 10800 - 60),
]}
#: ⚠️ The stream of starred entries calls itself the reading list.
STARRED_STREAM = {"id": READING_LIST, "updated": 1790498628, "items": [
    item("A quieter fan curve", 2, "Homelab Weekly", 1790480396, "user/-/state/com.google/read", "user/-/state/com.google/starred"),
]}


def server(*, api_on: bool = True) -> dict[str, list[Any]]:
    """A fake FreshRSS: the sign-in, the three reads, and what it was sent."""
    seen: dict[str, list[Any]] = {"login": [], "auth": [], "paths": []}

    def answer(request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/api/greader.php")
        seen["paths"].append((path, dict(request.url.params)))
        if not api_on:
            return httpx.Response(503, text="Service Unavailable!")
        if path == "/accounts/ClientLogin":
            sent = {key: values[0] for key, values in parse_qs(request.content.decode()).items()}
            seen["login"].append(sent)
            if sent.get("Email") == "curator" and sent.get("Passwd") == PASSWORD:
                return httpx.Response(200, text=f"SID={TOKEN}\nLSID=null\nAuth={TOKEN}\n")
            return httpx.Response(401, text="Unauthorized!")
        seen["auth"].append(request.headers.get("Authorization"))
        if request.headers.get("Authorization") != f"GoogleLogin auth={TOKEN}":
            return httpx.Response(401, text="Unauthorized!")
        if path == "/reader/api/0/unread-count":
            return httpx.Response(200, json=UNREAD_COUNT)
        if path == "/reader/api/0/subscription/list":
            return httpx.Response(200, json=SUBSCRIPTIONS)
        if path == f"/reader/api/0/stream/contents/{READING_LIST}":
            return httpx.Response(200, json=UNREAD_STREAM)
        if path == "/reader/api/0/stream/contents/user/-/state/com.google/starred":
            return httpx.Response(200, json=STARRED_STREAM)
        return httpx.Response(400, text="Bad Request!")

    respx.route(url__startswith=API).mock(side_effect=answer)
    return seen


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


@respx.mock
async def test_sign_in_with_the_api_password_and_keep_the_token(ctx: Context) -> None:
    seen = server()
    assert await ADAPTER.test(CONFIG, ctx) == "FreshRSS answers for curator: 15 unread."
    await ADAPTER.fetch("summary", CONFIG, {}, ctx)
    await ADAPTER.fetch("feeds", CONFIG, {}, ctx)
    assert seen["login"] == [{"Email": "curator", "Passwd": PASSWORD}], "one sign-in for all of it"
    assert set(seen["auth"]) == {f"GoogleLogin auth={TOKEN}"}


@respx.mock
async def test_a_token_that_stopped_working_is_fetched_again(ctx: Context) -> None:
    seen = server()
    # ⚠️ The token lives as long as the API password; a changed one kills it.
    ctx.cache["freshrss_auth"] = ((FR, "curator", PASSWORD), "curator/an-old-token-from-before")
    card = await ADAPTER.fetch("summary", CONFIG, {}, ctx)
    assert card.primary == {"label": "Unread", "value": 15}
    assert len(seen["login"]) == 1


@respx.mock
async def test_the_sign_in_password_is_refused_like_a_wrong_one(ctx: Context) -> None:
    server()
    # ⚠️ Measured: the password to sign in with, a wrong one and an unknown user all get 401 "Unauthorized!".
    with pytest.raises(AuthFailed) as caught:
        await ADAPTER.test({**CONFIG, "api_password": "the-sign-in-password"}, ctx)
    assert "API password" in caught.value.message and "Settings > Profile" in caught.value.hint


@respx.mock
async def test_the_api_switched_off_is_named(ctx: Context) -> None:
    server(api_on=False)
    # ⚠️ 503 "Service Unavailable!" for everything below greader.php, the sign-in included.
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.test(CONFIG, ctx)
    assert caught.value.code == "api_disabled" and "Allow API access" in caught.value.hint


@respx.mock
async def test_the_overview_counts_feeds_categories_and_the_latest_arrival(ctx: Context) -> None:
    server()
    card = ADAPTER._summary(UNREAD_COUNT["unreadcounts"], SUBSCRIPTIONS["subscriptions"], FR, NOW)
    assert card.primary == {"label": "Unread", "value": 15}
    # ⚠️ The newest timestamp is when FreshRSS fetched it, in microseconds.
    assert card.secondary == [
        {"label": "Feeds", "value": 5, "part": "feeds"},
        {"label": "Categories", "value": 3, "part": "categories"},
        {"label": "Latest arrival", "value": "1 min", "part": "arrival"},
    ]
    assert card.metrics == {"unread": 15.0} and card.link == f"{FR}/i/"
    fetched = await ADAPTER.fetch("summary", CONFIG, {}, ctx)
    assert fetched.primary == card.primary


def test_the_total_is_the_reading_list_and_not_a_sum() -> None:
    # The feeds and the categories count the same entries twice over.
    assert ADAPTER._total(UNREAD_COUNT["unreadcounts"]) == 15
    card = ADAPTER._summary([{"id": READING_LIST, "count": 0, "newestItemTimestampUsec": "1790498593412271"}], [], FR, NOW)
    assert card.secondary[2]["value"] == "", "nothing unread has no latest arrival"


@respx.mock
async def test_unread_entries_newest_first_without_the_read_ones(ctx: Context) -> None:
    seen = server()
    card = await ADAPTER.fetch("unread", CONFIG, {"limit": 3}, ctx)
    stream = [params for path, params in seen["paths"] if "/stream/contents/" in path]
    assert stream == [{"n": "3", "xt": "user/-/state/com.google/read"}]
    assert [(row["title"], row["subtitle"], row["value"], row["url"]) for row in card.items] == [
        ("Proxmox cluster notes", "Homelab Weekly", "1 h", "https://site2.example.com/proxmox-cluster-notes"),
        ("ZFS on a small machine", "Storage Corner", "2 h", "https://site3.example.com/zfs-on-a-small-machine"),
        ("Tomatoes in September", "Garden Log", "3 h", "https://site4.example.com/tomatoes-in-september"),
    ]
    assert card.secondary == [{"label": "Unread", "value": 15}] and card.metrics == {"unread": 15.0}


@respx.mock
async def test_starred_entries_come_from_their_own_stream(ctx: Context) -> None:
    seen = server()
    card = await ADAPTER.fetch("unread", CONFIG, {"starred": True}, ctx)
    assert [path for path, _params in seen["paths"] if "/stream/" in path] == [
        "/reader/api/0/stream/contents/user/-/state/com.google/starred"]
    assert [row["title"] for row in card.items] == ["A quieter fan curve"]
    assert card.secondary == [] and card.metrics == {} and card.meta["empty"] == "Nothing starred."


@respx.mock
async def test_unread_by_feed_and_by_category(ctx: Context) -> None:
    server()
    by_feed = await ADAPTER.fetch("feeds", CONFIG, {}, ctx)
    assert [(row["title"], row["value"]) for row in by_feed.items] == [
        ("Project releases", 10), ("Homelab Weekly", 2), ("Storage Corner", 2), ("Garden Log", 1)]
    by_category = await ADAPTER.fetch("feeds", CONFIG, {"group": "category", "limit": 2}, ctx)
    assert [(row["title"], row["value"]) for row in by_category.items] == [("Uncategorized", 10), ("Tech", 4)]


@respx.mock
async def test_an_address_that_is_not_freshrss(ctx: Context) -> None:
    respx.route(url__startswith=FR).mock(return_value=httpx.Response(404, text="<h1>Not Found</h1>"))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.test(CONFIG, ctx)
    assert caught.value.code == "http_error" and "without /api" in caught.value.hint
    respx.route(url__startswith=FR).mock(return_value=httpx.Response(200, text="<html>welcome</html>"))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.test(CONFIG, Context(httpx.AsyncClient(), cache={}))
    assert caught.value.code == "not_freshrss"


@respx.mock
async def test_freshrss_out_of_reach(ctx: Context) -> None:
    respx.route(url__startswith=FR).mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(Unreachable):
        await ADAPTER.fetch("summary", CONFIG, {}, ctx)


@pytest.mark.parametrize("kind", [widget.kind for widget in ADAPTER.widgets])
def test_demo_has_every_card(kind: str) -> None:
    for tick in range(4):
        card = ADAPTER.demo(kind, {}, tick)
        assert card.items or card.primary

