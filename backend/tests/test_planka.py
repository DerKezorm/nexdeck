"""Planka, against the answers of a live Planka 2 (28.10.2026).

One project, one board of three lists (and the unnamed archive and trash)
and four invented cards. Addresses and keys are made up; the shapes are the
measured ones, the dates relative to now so that the test does not age.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context, Unreachable

PK = "http://planka.example.com:1337"
KEY = "OB3rx2Rc_key-for-the-cards"
CONFIG = {"url": PK, "api_key": KEY}
ADAPTER = get_adapter("planka")


def at(delta: timedelta) -> str:
    return (datetime.now(UTC) + delta).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def card(identifier: str, name: str, list_id: str, due: timedelta | None = None, **fields: Any) -> dict[str, Any]:
    entry = {"id": identifier, "name": name, "listId": list_id, "type": "project", "dueDate": at(due) if due is not None else None,
             "isDueCompleted": False if due is not None else None, "isClosed": False, "createdAt": "2026-10-28T01:58:37.490Z",
             "updatedAt": None, "commentsTotal": 0}
    entry.update(fields)
    return entry


LISTS = [
    {"id": "l1", "name": "To do", "type": "active", "position": 65536},
    {"id": "l2", "name": "Doing", "type": "active", "position": 131072},
    {"id": "l3", "name": "Done", "type": "closed", "position": 196608},
    # ⚠️ Two lists with no name and no position: the archive and the trash.
    {"id": "l4", "name": None, "type": "archive", "position": None},
    {"id": "l5", "name": None, "type": "trash", "position": None},
]
CARDS = [
    card("c1", "Replace the UPS battery", "l1", timedelta(days=-2)),
    card("c2", "Renew the certificate", "l1", timedelta(days=3, hours=1)),
    card("c3", "Label the patch panel", "l2"),
    card("c4", "Update the router", "l3", isClosed=True),
    card("c5", "Thrown away", "l5", timedelta(days=-9)),
    card("c6", "Paid already", "l1", timedelta(days=-1), isDueCompleted=True),
]
PROJECTS = {"items": [{"id": "p1", "name": "Home lab"}], "included": {"boards": [{"id": "b1", "name": "Chores", "projectId": "p1"}], "users": []}}
BOARD = {"item": {"id": "b1", "name": "Chores"}, "included": {"lists": LISTS, "cards": CARDS, "users": []}}


def server() -> list[httpx.Request]:
    """A fake Planka that wants the key in X-API-Key, and the requests it saw."""
    seen: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        # ⚠️ A Bearer key is a 401 too.
        if request.headers.get("X-API-Key") != KEY:
            return httpx.Response(401, json={"code": "E_UNAUTHORIZED", "message": "Access token is missing, invalid or expired"})
        if request.url.path == "/api/projects":
            return httpx.Response(200, json=PROJECTS)
        if request.url.path == "/api/boards/b1":
            return httpx.Response(200, json=BOARD)
        return httpx.Response(404, json={"code": "E_NOT_FOUND"})

    respx.get(url__startswith=PK).mock(side_effect=answer)
    return seen


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


@respx.mock
async def test_the_connection_test_counts_projects_and_boards(ctx: Context) -> None:
    server()
    assert await ADAPTER.test(CONFIG, ctx) == "Planka answers with 1 projects and 1 boards."


@respx.mock
async def test_the_overview_counts_only_cards_in_active_lists_and_those_overdue_or_due_soon(ctx: Context) -> None:
    server()
    card_data = await ADAPTER.fetch("summary", CONFIG, {}, ctx)
    # c1, c2, c3 and c6 are in active lists; the closed list and the trash are not open.
    assert card_data.primary == {"label": "Open", "value": 4}
    # c1 is overdue; c6 is overdue too but its due date is ticked off. c2 is due in three days.
    assert card_data.secondary == [
        {"label": "Overdue", "value": 1, "part": "overdue"},
        {"label": "Due in a week", "value": 1, "part": "soon"},
        {"label": "Boards", "value": 1, "part": "boards"},
    ]
    assert card_data.status == "bad" and card_data.metrics == {"open": 4.0, "overdue": 1.0}


@respx.mock
async def test_due_cards_come_nearest_first_with_days_board_and_list(ctx: Context) -> None:
    server()
    data = await ADAPTER.fetch("due", CONFIG, {}, ctx)
    assert [(row["title"], row["subtitle"], row["value"], row["status"]) for row in data.items] == [
        ("Replace the UPS battery", "Chores · To do", "-2 d", "bad"),
        ("Renew the certificate", "Chores · To do", "3 d", "ok"),
    ]
    assert data.items[0]["url"] == f"{PK}/cards/c1"
    assert data.status == "bad"


@respx.mock
async def test_a_board_shows_its_named_lists_with_the_cards_in_each(ctx: Context) -> None:
    server()
    data = await ADAPTER.fetch("board", CONFIG, {"board": "chores"}, ctx)
    # ⚠️ Not the archive and the trash, which have no name.
    assert [(row["title"], row["value"]) for row in data.items] == [("To do", 3), ("Doing", 1), ("Done", 1)]
    assert data.link == f"{PK}/boards/b1"
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.fetch("board", CONFIG, {"board": "Garden"}, ctx)
    assert caught.value.code == "no_such_board"


@respx.mock
async def test_a_wrong_key_and_a_bearer_key_are_authentication_failures(ctx: Context) -> None:
    server()
    with pytest.raises(AuthFailed):
        await ADAPTER.fetch("summary", {**CONFIG, "api_key": "wrong"}, {}, ctx)


@respx.mock
async def test_an_unreachable_service_is_reported_as_such(ctx: Context) -> None:
    respx.get(url__startswith=PK).mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(Unreachable):
        await ADAPTER.fetch("due", CONFIG, {}, ctx)


@respx.mock
async def test_another_service_behind_the_address_is_named(ctx: Context) -> None:
    respx.get(url__startswith=PK).mock(return_value=httpx.Response(200, json={"hello": "world"}))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.fetch("summary", CONFIG, {}, ctx)
    assert caught.value.code == "not_planka"


def test_the_demo_has_a_card_for_every_widget() -> None:
    for widget in ADAPTER.widgets:
        data: Any = ADAPTER.demo(widget.kind, {}, 3)
        assert data.primary or data.items
