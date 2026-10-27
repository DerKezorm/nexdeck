"""Ombi, against the answers of Ombi 4.53.10 (lscr.io/linuxserver/ombi, 27.10.2026).

The shapes are the measured ones, including the user object each request
carries, with its e-mail address and access token (made up here), and the
200 with ``isError`` that Ombi gives for a refusal. Albums follow Ombi's
OpenAPI file; no Lidarr was there to ask for one.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context, Unreachable, outbound_client

BASE = "http://ombi.example.com:3579"
CONFIG = {"url": BASE, "api_key": "ombi-example-key"}
ADAPTER = get_adapter("ombi")


def fresh() -> Context:
    """Answers are remembered for a while per connection; a test that changes them asks with a new one."""
    return Context(outbound_client(guard=False), integration_id=1, widget_id=1, cache={})


@pytest.fixture
def ctx() -> Context:
    return fresh()



def person(alias: str) -> dict:
    return {"alias": alias, "userType": 1, "userAccessToken": "made-up-access-token", "id": "00000000-0000-0000-0000-000000000001",
            "userName": alias.lower(), "email": f"{alias.lower()}@example.com", "emailConfirmed": False}


def movie(identifier: int, title: str, released: str, when: str, who: str = "Alex") -> dict:
    return {"theMovieDbId": 600 + identifier, "title": title, "releaseDate": released, "requestedDate": when, "approved": False,
            "denied": None, "requestStatus": "Common.PendingApproval", "requestedUser": person(who), "requestedByAlias": None, "id": identifier}


MOVIES = {"collection": [movie(5, "Jurassic Park", "1993-06-11T00:00:00Z", "2026-10-27T16:23:18.4622643Z"),
                         movie(3, "Inception", "2010-07-15T00:00:00Z", "2026-10-27T16:23:17.1Z"),
                         movie(7, "Unreleased", "0001-01-01T00:00:00Z", "2026-10-26T09:00:00Z", "Sam")], "total": 3}
SHOWS = {"collection": [{"title": "Breaking Bad", "approved": False, "requestedDate": "2026-10-27T16:23:58.9954444Z",
                         "requestedUser": person("Kim"), "requestedByAlias": None, "parentRequestId": 1, "seasonRequests": [], "id": 1396}], "total": 1}
ALBUMS = {"collection": [{"title": "Copper Sky", "artistName": "Orbital Tide", "requestedDate": "2026-10-27T12:00:00Z",
                          "requestedUser": person("Robin"), "requestedByAlias": "Robin B.", "id": 2}], "total": 1}
COUNTS = {"pending": 5, "approved": 3, "available": 1, "denied": 2}


def ombi(movies: dict = MOVIES, shows: dict = SHOWS, albums: dict = ALBUMS, counts: dict = COUNTS) -> dict[str, respx.Route]:
    return {
        "count": respx.get(f"{BASE}/api/v1/Request/count").mock(return_value=httpx.Response(200, json=counts)),
        "movie": respx.get(url__regex=rf"{BASE}/api/v2/Requests/movie/pending/\d+/0/requestedDate/desc").mock(return_value=httpx.Response(200, json=movies)),
        "tv": respx.get(url__regex=rf"{BASE}/api/v2/Requests/tv/pending/\d+/0/requestedDate/desc").mock(return_value=httpx.Response(200, json=shows)),
        "album": respx.get(url__regex=rf"{BASE}/api/v2/Requests/album/pending/\d+/0/requestedDate/desc").mock(return_value=httpx.Response(200, json=albums)),
    }


@respx.mock
async def test_the_requests_of_three_lists_come_newest_first_with_who_asked(ctx: Context) -> None:
    routes = ombi()
    data = await ADAPTER.fetch("requests", CONFIG, {"limit": 4}, ctx)
    assert [(item["id"], item["title"], item["subtitle"]) for item in data.items] == [
        ("tv:1396", "Breaking Bad", "Kim · Show"),
        ("movie:5", "Jurassic Park (1993)", "Alex · Movie"),
        ("movie:3", "Inception (2010)", "Alex · Movie"),
        ("album:2", "Orbital Tide: Copper Sky", "Robin B. · Album"),
    ]
    assert data.status == "warn" and data.metrics == {"pending": 5.0}
    assert routes["movie"].calls.last.request.headers["ApiKey"] == CONFIG["api_key"]
    # What the user object holds beyond the name never reaches the card.
    assert "alex@example.com" not in data.model_dump_json() and "made-up-access-token" not in data.model_dump_json()



@respx.mock
async def test_a_movie_without_a_release_date_shows_no_year(ctx: Context) -> None:
    ombi()
    data = await ADAPTER.fetch("requests", CONFIG, {"limit": 8}, ctx)
    assert "Unreleased" in [item["title"] for item in data.items]


@respx.mock
async def test_each_row_offers_approve_and_a_confirmed_decline_with_its_kind_and_id(ctx: Context) -> None:
    ombi()
    data = await ADAPTER.fetch("requests", CONFIG, {"limit": 1}, ctx)
    assert data.items[0]["actions"] == [
        {"id": "approve", "label": "Approve", "icon": "check", "params": {"kind": "tv", "id": 1396}},
        {"id": "decline", "label": "Decline", "icon": "x", "confirm": True, "danger": True, "params": {"kind": "tv", "id": 1396}},
    ]


@respx.mock
async def test_nothing_waiting_is_green_and_says_so(ctx: Context) -> None:
    empty = {"collection": [], "total": 0}
    ombi(empty, empty, empty, {"pending": 0, "approved": 3, "available": 1, "denied": 0})
    data = await ADAPTER.fetch("requests", CONFIG, {}, ctx)
    assert (data.status, data.items, data.meta["empty"]) == ("ok", [], "No request waits.")


@respx.mock
async def test_the_counts_card(ctx: Context) -> None:
    ombi()
    data = await ADAPTER.fetch("counts", CONFIG, {}, ctx)
    assert data.primary == {"label": "Pending", "value": 5}
    assert data.status == "warn"
    assert ADAPTER.counts_card({**COUNTS, "pending": 0}).status == "ok"
    assert data.secondary == [{"label": "Approved"
, "value": 3}, {"label": "Available", "value": 1}, {"label": "Declined", "value": 2}]


@respx.mock
async def test_approving_posts_the_id_to_the_address_of_its_kind(ctx: Context) -> None:
    movie_route = respx.post(f"{BASE}/api/v1/Request/movie/approve").mock(return_value=httpx.Response(
        200, json={"result": True, "message": None, "isError": False, "errorMessage": None, "errorCode": None, "requestId": 0}))
    tv_route = respx.post(f"{BASE}/api/v1/Request/tv/approve").mock(return_value=httpx.Response(200, json={"result": True, "isError": False}))
    album_route = respx.post(f"{BASE}/api/v1/Request/music/approve").mock(return_value=httpx.Response(200, json={"result": True, "isError": False}))
    assert await ADAPTER.action("requests", "approve", {"kind": "movie", "id": 5}, CONFIG, {}, ctx) == "Request approved."
    await ADAPTER.action("requests", "approve", {"kind": "tv", "id": 1396}, CONFIG, {}, ctx)
    await ADAPTER.action("requests", "approve", {"kind": "album", "id": 2}, CONFIG, {}, ctx)
    assert json.loads(movie_route.calls.last.request.content) == {"id": 5, "is4K": False}
    assert json.loads(tv_route.calls.last.request.content) == {"id": 1396}
    assert json.loads(album_route.calls.last.request.content) == {"id": 2}
    assert movie_route.calls.last.request.headers["ApiKey"] == CONFIG["api_key"]


@respx.mock
async def test_declining_puts_to_deny(ctx: Context) -> None:
    route = respx.put(f"{BASE}/api/v1/Request/movie/deny").mock(return_value=httpx.Response(
        200, json={"result": True, "message": "Request successfully deleted", "isError": False}))
    assert await ADAPTER.action("requests", "decline", {"kind": "movie", "id": 4}, CONFIG, {}, ctx) == "Request declined."
    assert json.loads(route.calls.last.request.content) == {"id": 4, "is4K": False, "reason": ""}


@respx.mock
async def test_a_refusal_in_a_200_is_an_error_and_not_an_approval(ctx: Context) -> None:
    # Measured: approving a request that does not exist.
    respx.post(f"{BASE}/api/v1/Request/movie/approve").mock(return_value=httpx.Response(
        200, json={"result": False, "message": None, "isError": True, "errorMessage": "Request does not exist", "errorCode": None, "requestId": 0}))
    with pytest.raises(AdapterError) as failure:
        await ADAPTER.action("requests", "approve", {"kind": "movie", "id": 999}, CONFIG, {}, ctx)
    assert (failure.value.code, str(failure.value)) == ("ombi_refused", "Request does not exist")


async def test_an_action_needs_a_known_kind_and_a_number(ctx: Context) -> None:
    for params in ({"id": 5}, {"kind": "game", "id": 5}, {"kind": "movie"}, {"kind": "movie", "id": "../x"}):
        with pytest.raises(AdapterError) as failure:
            await ADAPTER.action("requests", "approve", params, CONFIG, {}, ctx)
        assert failure.value.code == "missing_param"
    with pytest.raises(AdapterError) as failure:
        await ADAPTER.action("requests", "delete", {"kind": "movie", "id": 5}, CONFIG, {}, ctx)
    assert failure.value.code == "no_such_action"


@respx.mock
async def test_the_test_asks_a_list_because_the_count_answers_anybody(ctx: Context) -> None:
    # Measured: /Request/count and /Status answer 200 to a wrong key, a request list answers 401 "Invalid API Key".
    respx.get(f"{BASE}/api/v1/Status/info").mock(return_value=httpx.Response(200, json="4.53.10"))
    respx.get(f"{BASE}/api/v1/Request/count").mock(return_value=httpx.Response(200, json=COUNTS))
    respx.get(url__regex=rf"{BASE}/api/v2/Requests/movie/pending/1/0/.*").mock(return_value=httpx.Response(401, text="Invalid API Key"))
    with pytest.raises(AuthFailed):
        await ADAPTER.test(CONFIG, ctx)
    respx.get(url__regex=rf"{BASE}/api/v2/Requests/movie/pending/1/0/.*").mock(return_value=httpx.Response(200, json=MOVIES))
    assert await ADAPTER.test(CONFIG, ctx) == "Ombi 4.53.10 answers."
    assert await ADAPTER.running_version(CONFIG, ctx) == "4.53.10"


@respx.mock
async def test_something_else_at_the_address_is_not_taken_for_ombi(ctx: Context) -> None:
    respx.get(f"{BASE}/api/v1/Request/count").mock(return_value=httpx.Response(404, text="nothing here"))
    with pytest.raises(AdapterError) as failure:
        await ADAPTER.fetch("counts", CONFIG, {}, ctx)
    assert failure.value.code == "not_ombi"
    respx.get(f"{BASE}/api/v1/Request/count").mock(return_value=httpx.Response(200, text="<html></html>"))
    with pytest.raises(AdapterError) as failure:
        await ADAPTER.fetch("counts", CONFIG, {}, fresh())
    assert failure.value.code == "not_json"


@respx.mock
async def test_an_unreachable_ombi(ctx: Context) -> None:
    respx.get(f"{BASE}/api/v1/Request/count").mock(side_effect=httpx.ConnectError("connection refused"))
    with pytest.raises(Unreachable):
        await ADAPTER.fetch("counts", CONFIG, {}, ctx)


@respx.mock
async def test_a_new_request_is_told_about_by_its_kind_and_number(ctx: Context) -> None:
    routes = ombi()
    before = await ADAPTER.fetch("requests", CONFIG, {"limit": 2}, ctx)
    routes["tv"].mock(return_value=httpx.Response(
        200, json={"collection": [{**SHOWS["collection"][0], "id": 1500, "title": "Harbour Lights"}], "total": 1}))

    after = await ADAPTER.fetch("requests", CONFIG, {"limit": 2}, fresh())
    found = ADAPTER.detect("requests", before, after, {})
    assert [(event.event, event.title, event.body) for event in found] == [("request_new", "Harbour Lights was requested", "Asked for by Kim.")]
    assert ADAPTER.detect("requests", None, after, {}) == []
    assert ADAPTER.detect("counts", before, after, {}) == []


def test_the_demo_fills_every_card() -> None:
    for tick in range(0, 400, 90):
        assert ADAPTER.demo("counts", {}, tick).primary
        assert ADAPTER.demo("requests", {}, tick).items
