"""Memos, against the answers of a live Memos 0.31.0 (28.10.2026).

Four invented memos, two of them with task lists. Addresses and tokens are
made up; the shapes are the measured ones.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context, Unreachable

ME = "http://memos.example.com:5230"
TOKEN = "memos_pat_for_the_cards"
CONFIG = {"url": ME, "token": TOKEN}
ADAPTER = get_adapter("memos")


def memo(identifier: str, content: str, tags: list[str], *, incomplete: bool = False, stamp: str = "2026-10-28T01:40:33Z") -> dict[str, Any]:
    return {"name": f"memos/{identifier}", "state": "NORMAL", "creator": "users/admin", "createTime": stamp, "updateTime": stamp,
            "content": content, "visibility": "PRIVATE", "tags": tags, "pinned": False, "attachments": [], "relations": [], "reactions": [],
            "property": {"hasLink": False, "hasTaskList": incomplete, "hasCode": False, "hasIncompleteTasks": incomplete, "title": ""},
            "snippet": content.replace("\n", "")}


DENTIST = memo("C97x8yh3QmWmzozcYY7NgT", "Call the dentist #todo\n\n- [ ] book a slot\n- [x] find the number", ["todo"], incomplete=True)
BACKUP = memo("4u5LUoggD7eM7gux8VgxsL", "# Backup plan\n\nNightly to the NAS #lab", ["lab"])
SHOPPING = memo("H3s8SThVZVD3ADLcAgisXp", "Shopping\n\n- [ ] milk\n- [ ] bread\n- [ ] eggs", [], incomplete=True)
MEMOS = [SHOPPING, BACKUP, DENTIST]
#: The two differ on purpose, so a card that read the wrong one fails (the live answers had both at 2).
STATS = {"name": "users/admin/stats", "memoTypeStats": {"linkCount": 0, "codeCount": 0, "todoCount": 3, "undoCount": 2},
         "tagCount": {"food": 1, "lab": 1, "todo": 1}, "totalMemoCount": 3, "attachmentStorageBytes": "0"}


def server() -> list[dict[str, str]]:
    """A fake Memos that filters like the live one, and notes what it was asked."""
    asked: list[dict[str, str]] = []

    def answer(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/v1/instance/profile":
            return httpx.Response(200, json={"version": "0.31.0", "needsSetup": False})
        if request.headers.get("Authorization") != f"Bearer {TOKEN}":
            return httpx.Response(401, json={"code": 16, "message": "authentication required"})
        if path == "/api/v1/auth/me":
            return httpx.Response(200, json={"user": {"name": "users/admin", "username": "admin"}})
        if path == "/api/v1/users/admin:getStats":
            return httpx.Response(200, json=STATS)
        if path == "/api/v1/memos":
            params = dict(request.url.params)
            asked.append(params)
            rows = [one for one in MEMOS if one["property"]["hasIncompleteTasks"]] if params.get("filter") == "has_incomplete_tasks" else MEMOS
            return httpx.Response(200, json={"memos": rows[: int(params.get("pageSize", 50))], "nextPageToken": ""})
        return httpx.Response(404, json={"code": 5, "message": "Not Found", "details": []})

    respx.get(url__startswith=ME).mock(side_effect=answer)
    return asked


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


@respx.mock
async def test_the_connection_test_names_the_version_and_counts_the_memos(ctx: Context) -> None:
    server()
    assert await ADAPTER.test(CONFIG, ctx) == "Memos 0.31.0 answers with 3 memos."


@respx.mock
async def test_the_overview_reads_the_statistics_of_the_signed_in_user(ctx: Context) -> None:
    server()
    card = await ADAPTER.fetch("summary", CONFIG, {}, ctx)
    assert card.primary == {"label": "Memos", "value": 3}
    # ⚠️ undoCount counts memos with an open task, not tasks.
    assert card.secondary == [
        {"label": "Memos with open tasks", "value": 2, "part": "open"},
        {"label": "Tags", "value": 3, "part": "tags"},
    ]
    assert card.metrics == {"memos": 3.0}
    assert card.link == ME


@respx.mock
async def test_recent_memos_take_the_title_from_the_first_line_and_link_by_name(ctx: Context) -> None:
    asked = server()
    card = await ADAPTER.fetch("recent", CONFIG, {"limit": 3}, ctx)
    assert [row["title"] for row in card.items] == ["Shopping", "Backup plan", "Call the dentist #todo"]
    assert card.items[2]["subtitle"] == "#todo"
    assert card.items[1]["url"] == f"{ME}/memos/4u5LUoggD7eM7gux8VgxsL"
    assert asked == [{"pageSize": "3"}]


@respx.mock
async def test_the_open_tasks_are_the_unticked_boxes_with_their_memo(ctx: Context) -> None:
    asked = server()
    card = await ADAPTER.fetch("tasks", CONFIG, {"limit": 4}, ctx)
    assert [(row["title"], row["subtitle"]) for row in card.items] == [
        ("milk", "Shopping"), ("bread", "Shopping"), ("eggs", "Shopping"), ("book a slot", "Call the dentist #todo")]
    # The ticked box ("find the number") is not open; the count is of all open ones.
    assert card.secondary == [{"label": "Open", "value": 4}]
    assert card.metrics == {"open_tasks": 4.0}
    assert asked[0]["filter"] == "has_incomplete_tasks"


@respx.mock
async def test_a_wrong_token_is_an_authentication_failure(ctx: Context) -> None:
    server()
    for kind in ("summary", "recent", "tasks"):
        with pytest.raises(AuthFailed):
            await ADAPTER.fetch(kind, {**CONFIG, "token": "wrong"}, {}, ctx)


@respx.mock
async def test_an_unreachable_service_is_reported_as_such(ctx: Context) -> None:
    respx.get(url__startswith=ME).mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(Unreachable):
        await ADAPTER.fetch("recent", CONFIG, {}, ctx)


@respx.mock
async def test_another_service_behind_the_address_is_named(ctx: Context) -> None:
    respx.get(url__startswith=ME).mock(return_value=httpx.Response(200, json={"hello": "world"}))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.fetch("recent", CONFIG, {}, ctx)
    assert caught.value.code == "not_memos"


def test_the_demo_has_a_card_for_every_widget() -> None:
    for widget in ADAPTER.widgets:
        data: Any = ADAPTER.demo(widget.kind, {}, 3)
        assert data.primary or data.items
