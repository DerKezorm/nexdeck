"""BookOrbit, against the answers of a live BookOrbit v2.9.0 (11.09.2026)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context, Unreachable
from app.adapters.bookorbit import BookOrbitAdapter

BO = "http://bookorbit.example.com"
CONFIG = {"url": BO, "username": "reader", "password": "made-up-password"}
NOW = datetime(2026, 9, 11, 20, 30, tzinfo=UTC).timestamp()


def card(identifier: int, title: str, authors: list[str], progress: float | None, added: str) -> dict[str, Any]:
    """A book card as a shelf hands it out, trimmed of the fields nothing reads."""
    return {
        "id": identifier, "status": "present", "title": title, "seriesId": None, "seriesName": None, "authors": authors,
        "files": [{"id": identifier, "format": "epub", "role": "primary", "sizeBytes": 2122}],
        "language": "en", "rating": None, "readingProgress": progress,
        "readStatus": None if progress is None else {"status": "reading", "source": "auto", "startedAt": "2026-09-11T00:00:00.000Z",
                                                     "finishedAt": None, "updatedAt": "2026-09-11T20:28:01.250Z"},
        "addedAt": added, "updatedAt": added, "hasCover": False,
    }


#: The continue-reading shelf: the one read last first.
READING = [
    card(2, "Notes on Copper Wire", ["Ben Sample"], 73, "2026-09-11T20:26:53.527Z"),
    card(4, "The Quiet Harbour", ["Ada Example", "Cara Placeholder"], 42, "2026-09-11T20:26:53.597Z"),
]
#: The recently-added shelf: the newest first, no progress.
RECENT = [
    card(5, "Winter at the Lighthouse", ["Ada Example"], None, "2026-09-11T20:26:53.658Z"),
    card(3, "The Last Timetable", ["Dan Invented"], None, "2026-09-10T08:00:00.000Z"),
]
OVERVIEW = {"totalBooks": 5, "totalAuthors": 4, "totalSeries": 0, "totalStorageBytes": 10668, "booksAddedThisYear": 5}
UNAUTHORIZED = {"statusCode": 401, "message": "Unauthorized", "path": "/api/v1/auth/me", "timestamp": "2026-09-11T20:26:26.549Z", "requestId": "req-d"}


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


def _login(token: str = "made-up-jwt") -> respx.Route:
    return respx.post(f"{BO}/api/v1/auth/login").mock(return_value=httpx.Response(200, json={
        "accessToken": token, "user": {"id": 1, "username": "reader", "isSuperuser": False, "permissions": []}}))


def _shelf(name: str, books: list[dict[str, Any]]) -> respx.Route:
    return respx.get(f"{BO}/api/v1/dashboard/scrollers/{name}").mock(
        side_effect=lambda request: httpx.Response(200, json=books[: int(request.url.params["limit"])]))


@respx.mock
async def test_reading_now_with_the_share_read(ctx: Context) -> None:
    login = _login()
    shelf = _shelf("continue-reading", READING)
    data = await get_adapter("bookorbit").fetch("reading", CONFIG, {"limit": 5}, ctx)
    assert login.calls.last.request.content == b'{"username":"reader","password":"made-up-password"}'
    assert shelf.calls.last.request.headers["Authorization"] == "Bearer made-up-jwt"
    assert shelf.calls.last.request.url.params["limit"] == "5"
    assert [(row["title"], row["subtitle"], row["value"], row["progress"]) for row in data.items] == [
        ("Notes on Copper Wire", "Ben Sample", "73%", 73.0), ("The Quiet Harbour", "Ada Example, Cara Placeholder", "42%", 42.0)]
    assert data.metrics == {"reading": 2.0}


def test_nothing_being_read_is_an_empty_card() -> None:
    data = BookOrbitAdapter._reading([])
    assert data.items == [] and data.meta["empty"] == "Nothing is being read." and data.metrics == {"reading": 0.0}


def test_recently_added_with_how_long_ago() -> None:
    data = BookOrbitAdapter._recent(RECENT, NOW)
    assert [(row["title"], row["subtitle"], row["value"]) for row in data.items] == [
        ("Winter at the Lighthouse", "Ada Example", "3 min"), ("The Last Timetable", "Dan Invented", "1 d")]


@respx.mock
async def test_recently_added_asks_the_shelf_for_no_more_than_fifty(ctx: Context) -> None:
    _login()
    shelf = _shelf("recently-added", RECENT)
    data = await get_adapter("bookorbit").fetch("recent", CONFIG, {"limit": 500}, ctx)
    assert shelf.calls.last.request.url.params["limit"] == "50"
    assert [row["title"] for row in data.items] == ["Winter at the Lighthouse", "The Last Timetable"]


@respx.mock
async def test_the_library_in_numbers(ctx: Context) -> None:
    _login()
    respx.get(f"{BO}/api/v1/dashboard/widgets/library-overview").mock(return_value=httpx.Response(200, json=OVERVIEW))
    shelf = _shelf("continue-reading", READING)
    data = await get_adapter("bookorbit").fetch("summary", CONFIG, {}, ctx)
    assert shelf.calls.last.request.url.params["limit"] == "50"
    assert data.primary == {"label": "Books", "value": 5}
    assert data.secondary == [{"label": "Being read", "value": 2}, {"label": "Authors", "value": 4}]
    assert data.metrics == {"books": 5.0}


@respx.mock
async def test_the_token_is_kept_and_asked_for_again_when_refused(ctx: Context) -> None:
    """⚠️ Measured: signing in is limited to five times a minute, and a token lasts 15 minutes."""
    login = _login()
    answers = iter([httpx.Response(200, json=READING), httpx.Response(401, json=UNAUTHORIZED), httpx.Response(200, json=READING)])
    shelf = respx.get(f"{BO}/api/v1/dashboard/scrollers/continue-reading").mock(side_effect=lambda request: next(answers))
    adapter = get_adapter("bookorbit")
    await adapter.fetch("reading", CONFIG, {"limit": 3}, ctx)
    assert login.call_count == 1
    ctx.forget_answers()
    data = await adapter.fetch("reading", CONFIG, {"limit": 4}, ctx)
    assert login.call_count == 2 and shelf.call_count == 3 and len(data.items) == 2


@respx.mock
async def test_a_token_refused_twice_is_a_refusal(ctx: Context) -> None:
    _login()
    respx.get(f"{BO}/api/v1/dashboard/scrollers/continue-reading").mock(return_value=httpx.Response(401, json=UNAUTHORIZED))
    with pytest.raises(AuthFailed):
        await get_adapter("bookorbit").fetch("reading", CONFIG, {}, ctx)


@respx.mock
async def test_a_wrong_password(ctx: Context) -> None:
    respx.post(f"{BO}/api/v1/auth/login").mock(return_value=httpx.Response(401, json={
        "statusCode": 401, "message": "Invalid credentials", "path": "/api/v1/auth/login"}))
    with pytest.raises(AuthFailed):
        await get_adapter("bookorbit").fetch("recent", CONFIG, {}, ctx)


@respx.mock
async def test_too_many_sign_ins(ctx: Context) -> None:
    respx.post(f"{BO}/api/v1/auth/login").mock(return_value=httpx.Response(429, json={"statusCode": 429, "message": "ThrottlerException: Too Many Requests"}))
    with pytest.raises(AdapterError) as refused:
        await get_adapter("bookorbit").fetch("summary", CONFIG, {}, ctx)
    assert refused.value.code == "rate_limited"


@respx.mock
async def test_an_unreachable_server(ctx: Context) -> None:
    respx.post(f"{BO}/api/v1/auth/login").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(Unreachable):
        await get_adapter("bookorbit").fetch("reading", CONFIG, {}, ctx)


@respx.mock
async def test_the_connection_test(ctx: Context) -> None:
    _login()
    respx.get(f"{BO}/api/v1/app-info").mock(return_value=httpx.Response(200, json={"version": "v2.9.0", "updateAvailable": False, "latestVersion": "v2.9.0", "maxUploadSizeMb": 500}))
    respx.get(f"{BO}/api/v1/dashboard/widgets/library-overview").mock(return_value=httpx.Response(200, json=OVERVIEW))
    assert await get_adapter("bookorbit").test(CONFIG, ctx) == "BookOrbit v2.9.0 answers with 5 books."
