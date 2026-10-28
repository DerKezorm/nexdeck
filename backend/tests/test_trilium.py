"""Trilium, against the answers of a live TriliumNext 0.106.1 (28.10.2026).

Three invented notes beside the root note. Addresses and tokens are made up;
the shapes are the measured ones, the space in the times included.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context, Unreachable

TR = "http://trilium.example.com:8080"
TOKEN = "etapi-token-for-the-cards"
CONFIG = {"url": TR, "token": TOKEN}
ADAPTER = get_adapter("trilium")


def stamp(delta: timedelta) -> str:
    return (datetime.now(UTC) - delta).strftime("%Y-%m-%d %H:%M:%S.000Z")


def note(identifier: str, title: str, modified: str) -> dict[str, Any]:
    return {"noteId": identifier, "isProtected": False, "title": title, "type": "text", "mime": "text/html",
            "blobId": "SxjX0BwlgF8uk97mPM31", "dateCreated": "2026-10-28 01:37:08.638+0000",
            "dateModified": "2026-10-28 02:37:08.639+0100", "utcDateCreated": "2026-10-28 01:37:08.638Z",
            "utcDateModified": modified, "parentNoteIds": ["root"], "childNoteIds": [], "parentBranchIds": [],
            "childBranchIds": [], "attributes": []}


def notes() -> list[dict[str, Any]]:
    return [
        note("root", "root", stamp(timedelta(minutes=1))),
        note("621eyzav4P5W", "Backup plan", stamp(timedelta(minutes=20))),
        note("6dHJkvKu1iB4", "DNS notes", stamp(timedelta(days=3))),
        note("SFTYaaBz8x5g", "Tomato soup", stamp(timedelta(days=40))),
    ]


def server() -> list[dict[str, str]]:
    """A fake ETAPI that wants the bare token and notes what it was asked."""
    asked: list[dict[str, str]] = []

    def answer(request: httpx.Request) -> httpx.Response:
        if request.headers.get("Authorization") != TOKEN:
            return httpx.Response(401, json={"status": 401, "code": "NOT_AUTHENTICATED", "message": "Not authenticated"})
        if request.url.path == "/etapi/app-info":
            return httpx.Response(200, json={"appVersion": "0.106.1", "dbVersion": 240, "syncVersion": 39})
        if request.url.path == "/etapi/notes":
            params = dict(request.url.params)
            asked.append(params)
            rows = notes()
            if params.get("orderBy") == "utcDateModified":
                rows.sort(key=lambda one: one["utcDateModified"], reverse=params.get("orderDirection") == "desc")
            return httpx.Response(200, json={"results": rows[: int(params.get("limit", 1000))]})
        return httpx.Response(404, json={"status": 404, "code": "NOT_FOUND"})

    respx.get(url__startswith=TR).mock(side_effect=answer)
    return asked


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


@respx.mock
async def test_the_connection_test_names_the_version_and_counts_the_notes_without_the_root(ctx: Context) -> None:
    server()
    assert await ADAPTER.test(CONFIG, ctx) == "Trilium 0.106.1 answers with 3 notes."


@respx.mock
async def test_the_overview_counts_every_note_once_and_those_changed_this_week(ctx: Context) -> None:
    asked = server()
    card = await ADAPTER.fetch("summary", CONFIG, {}, ctx)
    assert card.primary == {"label": "Notes", "value": 3}
    # ⚠️ The root changed a minute ago and does not count; two of the three are from this week.
    assert card.secondary == [{"label": "Changed this week", "value": 2, "part": "week"}]
    assert card.metrics == {"notes": 3.0}
    assert card.link == TR
    assert asked == [{"search": "note.noteId != ''"}]


@respx.mock
async def test_recent_notes_are_asked_newest_first_and_leave_the_root_out(ctx: Context) -> None:
    asked = server()
    card = await ADAPTER.fetch("recent", CONFIG, {"limit": 2}, ctx)
    assert [row["title"] for row in card.items] == ["Backup plan", "DNS notes"]
    assert card.items[0]["url"] == f"{TR}/#621eyzav4P5W"
    assert card.items[0]["value"].endswith("min")
    assert asked[0]["orderBy"] == "utcDateModified" and asked[0]["orderDirection"] == "desc"
    assert asked[0]["limit"] == "3"


@respx.mock
async def test_a_wrong_token_is_an_authentication_failure(ctx: Context) -> None:
    server()
    with pytest.raises(AuthFailed):
        await ADAPTER.fetch("summary", {**CONFIG, "token": "wrong"}, {}, ctx)


@respx.mock
async def test_an_unreachable_service_is_reported_as_such(ctx: Context) -> None:
    respx.get(url__startswith=TR).mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(Unreachable):
        await ADAPTER.fetch("recent", CONFIG, {}, ctx)


@respx.mock
async def test_another_service_behind_the_address_is_named(ctx: Context) -> None:
    respx.get(url__startswith=TR).mock(return_value=httpx.Response(200, json={"hello": "world"}))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.test(CONFIG, ctx)
    assert caught.value.code == "not_trilium"


def test_the_demo_has_a_card_for_every_widget() -> None:
    for widget in ADAPTER.widgets:
        data: Any = ADAPTER.demo(widget.kind, {}, 3)
        assert data.primary or data.items
