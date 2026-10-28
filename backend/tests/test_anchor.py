"""Anchor, against the answers of a live Anchor 0.17.2 (28.10.2026).

Five invented notes, one pinned, two with a reminder, one without a title,
and one archived. Addresses and tokens are made up; the shapes are the
measured ones.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context, Unreachable

AN = "http://anchor.example.com:3000"
TOKEN = "api-token-for-the-cards"
CONFIG = {"url": AN, "token": TOKEN}
ADAPTER = get_adapter("anchor")


def note(identifier: str, title: str, content: str, updated: str, **fields: Any) -> dict[str, Any]:
    entry = {"id": identifier, "title": title, "content": content, "background": None, "state": "active", "version": 1,
             "createdAt": updated, "updatedAt": updated, "userId": "u1", "isPinned": False, "isArchived": False, "tagIds": [],
             "permission": "owner", "attachmentCount": 0, "imagePreviewIds": [], "shareIds": [], "reminder": None}
    entry.update(fields)
    return entry


def reminder(at: str, recurrence: str = "none") -> dict[str, Any]:
    return {"remindAt": at, "recurrence": recurrence, "version": 1}


#: In the order the live server answered: newest change first, the pinned note not first.
NOTES = [
    note("n5", "Pay the invoice", "Every week", "2026-10-28T02:09:13.587Z", reminder=reminder("2026-10-27T09:30", "weekly")),
    note("n4", "Call the dentist", "Ask for a\nTuesday", "2026-10-28T02:09:13.566Z", reminder=reminder("2026-10-29T10:00")),
    # ⚠️ Saved without a title: the title is an empty string.
    note("n3", "", "\n  Milk, bread, eggs", "2026-10-28T02:08:50.000Z"),
    note("n2", "Tomato soup", "Simple", "2026-10-28T02:08:48.515Z", isPinned=True),
    note("n1", "Backup plan", "Nightly to the NAS", "2026-10-28T02:08:46.479Z"),
]
ARCHIVED = [note("n0", "Old idea", "x", "2026-10-28T02:00:00.000Z", isArchived=True)]


def server() -> list[str]:
    asked: list[str] = []

    def answer(request: httpx.Request) -> httpx.Response:
        asked.append(request.url.path)
        if request.url.path == "/api/health":
            return httpx.Response(200, json={"status": "ok", "app": "anchor", "version": "0.17.2", "protocols": [3, 4]})
        if request.headers.get("Authorization") is None:
            return httpx.Response(401, json={"message": "Missing authentication token", "error": "Unauthorized", "statusCode": 401})
        if request.headers["Authorization"] != f"Bearer {TOKEN}":
            return httpx.Response(401, json={"message": "Invalid authentication token", "error": "Unauthorized", "statusCode": 401})
        routes: dict[str, Any] = {"/api/notes": NOTES, "/api/notes/archive": ARCHIVED}
        if request.url.path in routes:
            return httpx.Response(200, json=routes[request.url.path])
        return httpx.Response(404, json={"message": "Cannot GET", "statusCode": 404})

    respx.get(url__startswith=AN).mock(side_effect=answer)
    return asked


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


@respx.mock
async def test_the_connection_test_names_the_version_and_counts_the_notes(ctx: Context) -> None:
    server()
    assert await ADAPTER.test(CONFIG, ctx) == "Anchor 0.17.2 answers with 5 notes."


@respx.mock
async def test_the_overview_counts_active_notes_and_reads_the_archive_from_its_own_route(ctx: Context) -> None:
    asked = server()
    card = await ADAPTER.fetch("summary", CONFIG, {}, ctx)
    assert card.primary == {"label": "Notes", "value": 5}
    assert card.secondary == [
        {"label": "Pinned", "value": 1, "part": "pinned"},
        {"label": "Reminders", "value": 2, "part": "reminders"},
        {"label": "Archived", "value": 1, "part": "archived"},
    ]
    assert card.metrics == {"notes": 5.0}
    assert "/api/notes/archive" in asked


@respx.mock
async def test_recent_notes_come_newest_first_with_the_first_line_and_a_name_for_a_blank_title(ctx: Context) -> None:
    server()
    card = await ADAPTER.fetch("recent", CONFIG, {"limit": 4}, ctx)
    assert [(row["title"], row["subtitle"]) for row in card.items] == [
        ("Pay the invoice", "Every week"), ("Call the dentist", "Ask for a"), ("Untitled", "Milk, bread, eggs"), ("Tomato soup", "Simple")]
    assert card.items[0]["value"].endswith(("min", "h", "d"))


@respx.mock
async def test_reminders_are_listed_by_the_clock_they_were_written_on_with_their_repeat(ctx: Context) -> None:
    server()
    card = await ADAPTER.fetch("reminders", CONFIG, {}, ctx)
    # ⚠️ remindAt has no zone, so it is shown as written and not turned into "in two hours".
    assert [(row["title"], row["subtitle"], row["value"]) for row in card.items] == [
        ("Pay the invoice", "Weekly", "2026-10-27 09:30"), ("Call the dentist", "", "2026-10-29 10:00")]


@respx.mock
async def test_a_wrong_token_and_a_missing_one_are_authentication_failures(ctx: Context) -> None:
    server()
    for token in ("wrong", ""):
        with pytest.raises(AuthFailed):
            await ADAPTER.fetch("recent", {**CONFIG, "token": token}, {}, ctx)


@respx.mock
async def test_an_unreachable_service_is_reported_as_such(ctx: Context) -> None:
    respx.get(url__startswith=AN).mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(Unreachable):
        await ADAPTER.fetch("summary", CONFIG, {}, ctx)


@respx.mock
async def test_another_service_behind_the_address_is_named(ctx: Context) -> None:
    respx.get(url__startswith=AN).mock(return_value=httpx.Response(200, json={"hello": "world"}))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.test(CONFIG, ctx)
    assert caught.value.code == "not_anchor"


def test_the_demo_has_a_card_for_every_widget() -> None:
    for widget in ADAPTER.widgets:
        data: Any = ADAPTER.demo(widget.kind, {}, 3)
        assert data.primary or data.items
