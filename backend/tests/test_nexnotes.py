"""nexnotes' card routes as its ``docs/api.md`` (22.11.2026) describes them, played by a small nexnotes of our own:
``/me``, ``/dashboard``, ``/notes``, ``/notes/{id}`` and ``POST /notes/{id}/items/{index}``, with the family's walls.
Titles, names and items are made up."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.adapters import get_adapter
from app.adapters import nexnotes as module
from app.adapters.base import AdapterError, AuthFailed, Context, WidgetData, outbound_client
from app.services import collector as collector_module
from app.services.collector import collector
from app.services.state import live

from .conftest import CSRF, setup_admin

URL = "http://nexnotes:8570"
CONFIG = {"url": URL, "api_key": "nn_api_example"}
AS_OF = "2026-11-22T09:15:00+00:00"


class FakeNexnotes:
    """What nexnotes answers on the card's five routes, with a state the tests change and a log of what it was asked."""

    def __init__(self) -> None:
        self.level = "write"
        self.api_on = True
        self.token = "nn_api_example"
        self.stamp_turn = 0
        self.down = False
        self.seen: list[httpx.Request] = []
        self.notes: dict[str, dict[str, Any]] = {
            "n-shop": {"title": "Shopping", "access": "owner", "pinned": True, "locked": False, "trashed": False,
                       "items": [["Milk", False, 0], ["Bread", True, 0], ["Apples", False, 0], ["Coffee", False, 0],
                                 ["The dark roast", False, 1], ["Washing-up liquid", True, 0]], "lines": []},
            "n-trip": {"title": "Packing", "access": "read", "pinned": True, "owner": "Sam", "locked": False, "trashed": False,
                       "items": [["Passports", True, 0], ["Chargers", False, 0]], "lines": []},
            "n-wifi": {"title": "", "access": "owner", "pinned": True, "locked": False, "trashed": False, "items": [],
                       "lines": ["The password is on the fridge.", "Guests: the second network."]},
            "n-safe": {"title": "Bank", "access": "owner", "pinned": True, "locked": True, "trashed": False,
                       "items": [["PIN", False, 0]], "lines": []},
        }

    # -- what it answers ---------------------------------------------------------------------------------------------

    @staticmethod
    def refuse(status: int, code: str, headers: dict[str, str] | None = None) -> httpx.Response:
        return httpx.Response(status, json={"detail": {"code": code, "message": code}}, headers=headers)

    def stamp(self, note_id: str) -> str:
        note = self.notes[note_id]
        return f"{note_id}:{self.stamp_turn}:{json.dumps(note['items'])}:{note['title']}"

    def card(self, note_id: str) -> dict[str, Any]:
        note = self.notes[note_id]
        items = note["items"]
        done = sum(1 for _text, checked, _depth in items if checked)
        return {
            "id": note_id, "title": note["title"], "link": f"{URL}/notes/{note_id}", "updated_at": AS_OF,
            "can_check": self.level == "write" and note["access"] in ("owner", "write"),
            "tasks": {"done": done, "total": len(items)} if items else None,
            "items": [{"index": index, "text": text, "checked": checked, "depth": depth}
                      for index, (text, checked, depth) in enumerate(items)],
            "more_items": 0, "lines": note["lines"] if not items else [],
            "stamp": self.stamp(note_id), "as_of": AS_OF, "etag": "e1",
        }

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.seen.append(request)
        if self.down:
            raise httpx.ConnectError("nexnotes is down")
        if request.headers.get("origin"):
            return self.refuse(403, "origin_refused")
        if not self.api_on:
            return self.refuse(403, "api_off")
        if request.headers.get("authorization") != f"Bearer {self.token}":
            return self.refuse(401, "token_invalid")
        path = request.url.path.removeprefix("/api/v1")
        if request.method == "GET" and path == "/me":
            return httpx.Response(200, json={
                "app": "nexnotes", "name": "robin", "display_name": "Robin", "level": self.level, "version": "0.9.0",
                "features": ["pinned", "notes", "check", "read"], "token": {"id": 3, "name": "Kitchen"},
                "access": ["api"], "folders": None, "expires_at": None})
        if request.method == "GET" and path == "/dashboard":
            limit = int(request.url.params.get("limit", "12"))
            pinned = [one for one, note in self.notes.items() if note["pinned"] and not note["locked"] and not note["trashed"]]
            rows = []
            for note_id in pinned[:limit]:
                card = self.card(note_id)
                row = {"id": note_id, "title": card["title"], "first_line": (card["items"][0]["text"] if card["items"] else card["lines"][0]),
                       "tasks": card["tasks"], "updated_at": AS_OF, "link": card["link"]}
                if self.notes[note_id].get("owner"):
                    row["owner"] = self.notes[note_id]["owner"]
                rows.append(row)
            return httpx.Response(200, json={"pinned": rows, "more": max(0, len(pinned) - limit), "link": URL,
                                             "stamp": "~".join(self.stamp(one) for one in pinned[:limit]), "as_of": AS_OF})
        if request.method == "GET" and path == "/notes":
            return httpx.Response(200, json={"notes": [
                {"id": one, "title": note["title"], "tasks": self.card(one)["tasks"], "locked": False, **({"owner": note["owner"]} if note.get("owner") else {})}
                for one, note in self.notes.items() if not note["locked"] and not note["trashed"]], "next_cursor": None})
        parts = path.strip("/").split("/")
        if len(parts) >= 2 and parts[0] == "notes":
            note = self.notes.get(parts[1])
            if note is None:
                return self.refuse(404, "not_found")
            if note["locked"]:
                return self.refuse(409, "note_locked")
            if note["trashed"]:
                return self.refuse(410, "note_trashed")
            if request.method == "GET" and len(parts) == 2:
                return httpx.Response(200, json=self.card(parts[1]))
            if request.method == "POST" and len(parts) == 4 and parts[2] == "items":
                if self.level != "write":
                    return self.refuse(403, "token_reads_only")
                if note["access"] not in ("owner", "write"):
                    return self.refuse(403, "not_allowed")
                body = json.loads(request.content or b"{}")
                if "text" not in body:
                    return self.refuse(422, "invalid_input")
                index = int(parts[3])
                if index >= len(note["items"]) or note["items"][index][0] != body["text"]:
                    return self.refuse(409, "item_changed")
                note["items"][index][1] = bool(body.get("checked", True))
                return httpx.Response(200, json=self.card(parts[1]))
        return self.refuse(404, "not_found")


@pytest.fixture
def server() -> FakeNexnotes:
    return FakeNexnotes()


@pytest.fixture
def ctx() -> Context:
    return fresh()


def fresh() -> Context:
    return Context(outbound_client(guard=False), integration_id=1, widget_id=1, cache={})


def serve(fake: FakeNexnotes) -> None:
    respx.route(host="nexnotes").mock(side_effect=fake)


adapter = get_adapter("nexnotes")


# -- the connection ----------------------------------------------------------------------------------------------------


@respx.mock
async def test_the_test_names_the_account_its_level_and_what_it_sees(server: FakeNexnotes, ctx: Context) -> None:
    serve(server)
    said = await adapter.test(CONFIG, ctx)
    assert said == "nexnotes 0.9.0 answers; the token of Robin reads and ticks off and sees all notes."
    server.level = "read"
    assert "Robin reads and sees" in await adapter.test(CONFIG, fresh())
    request = server.seen[-1]
    assert request.headers["authorization"] == "Bearer nn_api_example" and "nn_api_" not in str(request.url)
    assert "origin" not in request.headers, "nexnotes refuses any request with an Origin header"


@respx.mock
async def test_another_app_of_the_family_at_the_address_is_said(ctx: Context) -> None:
    # nextasks answers /me with features too, but names no app.
    respx.get(f"{URL}/api/v1/me").mock(return_value=httpx.Response(200, json={
        "name": "robin", "level": "read", "features": ["tasks", "dashboard"], "spaces": []}))
    with pytest.raises(AdapterError) as failure:
        await adapter.test(CONFIG, ctx)
    assert failure.value.code == "wrong_app"
    respx.get(f"{URL}/api/v1/me").mock(return_value=httpx.Response(200, json={"app": "nexlore", "features": []}))
    with pytest.raises(AdapterError) as other:
        await adapter.test(CONFIG, fresh())
    assert other.value.code == "wrong_app", "an app field that names another app is not nexnotes"


@respx.mock
async def test_the_walls_of_the_family_are_said(server: FakeNexnotes) -> None:
    serve(server)
    server.token = "nn_api_other"
    with pytest.raises(AuthFailed):
        await adapter.test(CONFIG, fresh())
    server.token = CONFIG["api_key"]
    server.api_on = False
    with pytest.raises(AdapterError) as off:
        await adapter.fetch("pinned", CONFIG, {}, fresh())
    assert off.value.code == "api_off" and "General > API for members" in off.value.hint


@respx.mock
@pytest.mark.parametrize(("status", "code", "ours"), [
    (403, "origin_refused", "origin_refused"),
    (429, "slow_down", "rate_limited"),
    (429, "too_many_attempts", "rate_limited"),
    (403, "token_card_only", "wrong_kind"),
    (502, "", "unreachable"),
    (503, "", "unreachable"),
])
async def test_every_refusal_of_the_card_routes_has_its_sentence(status: int, code: str, ours: str) -> None:
    body = {"detail": {"code": code, "message": code}} if code else {}
    respx.get(f"{URL}/api/v1/dashboard").mock(return_value=httpx.Response(status, json=body, headers={"Retry-After": "60"}))
    with pytest.raises(AdapterError) as failure:
        await adapter.fetch("pinned", CONFIG, {}, fresh())
    assert failure.value.code == ours and failure.value.message


# -- the pinned notes --------------------------------------------------------------------------------------------------


@respx.mock
async def test_pinned_shows_title_first_line_progress_and_owner_and_never_a_locked_note(server: FakeNexnotes, ctx: Context) -> None:
    serve(server)
    data = await adapter.fetch("pinned", CONFIG, {}, ctx)
    assert [(row["title"], row["subtitle"], row.get("done"), row.get("total"), row.get("owner")) for row in data.items] == [
        ("Shopping", "Milk", 2, 6, None),
        ("Packing", "Passports", 1, 2, "Sam"),
        ("", "The password is on the fridge.", None, None, None),
    ]
    assert all("Bank" not in str(row) and "PIN" not in str(row) for row in data.items)
    assert data.items[0]["url"] == f"{URL}/notes/n-shop" and data.link == URL
    assert data.meta["mode"] == "pinned" and data.meta["more"] == 0 and data.meta["offline_note"] is True
    assert data.meta["stamp"] and isinstance(data.meta["as_of"], float)
    assert server.seen[-1].url.params["limit"] == "8"


@respx.mock
async def test_pinned_keeps_to_its_entries_and_says_how_many_more(server: FakeNexnotes, ctx: Context) -> None:
    serve(server)
    data = await adapter.fetch("pinned", CONFIG, {"limit": 2}, ctx)
    assert len(data.items) == 2 and data.meta["more"] == 1
    assert server.seen[-1].url.params["limit"] == "2"
    many = await adapter.fetch("pinned", CONFIG, {"limit": 500}, fresh())
    assert server.seen[-1].url.params["limit"] == "50", "nexnotes takes at most 50"
    assert len(many.items) == 3


@respx.mock
async def test_pinned_without_a_pinned_note_says_so(server: FakeNexnotes, ctx: Context) -> None:
    serve(server)
    for note in server.notes.values():
        note["pinned"] = False
    data = await adapter.fetch("pinned", CONFIG, {}, ctx)
    assert data.items == [] and data.meta["empty"] == "No note is pinned."


# -- one note ----------------------------------------------------------------------------------------------------------


@respx.mock
async def test_a_checklist_shows_the_open_items_first_with_their_progress(server: FakeNexnotes, ctx: Context) -> None:
    serve(server)
    data = await adapter.fetch("note", CONFIG, {"note": "n-shop"}, ctx)
    assert [(row["title"], row["checked"], row["depth"]) for row in data.items] == [
        ("Milk", False, 0), ("Apples", False, 0), ("Coffee", False, 0), ("The dark roast", False, 1),
        ("Bread", True, 0), ("Washing-up liquid", True, 0),
    ]
    assert (data.meta["title"], data.meta["done"], data.meta["total"], data.meta["more"]) == ("Shopping", 2, 6, 0)
    assert data.primary == {"label": "Open", "value": 4}
    assert data.link == f"{URL}/notes/n-shop" and "check_note" not in data.meta
    read = next(request for request in server.seen if request.url.path == "/api/v1/notes/n-shop")
    assert read.url.params["markdown"] == "false", "the card never asks for the note's whole text"
    tick = data.items[0]["actions"][0]
    assert tick.id == "check" and tick.params == {"note": "n-shop", "index": 0, "text": "Milk", "checked": True}
    reopen = data.items[4]["actions"][0]
    assert reopen.label == "Open again" and reopen.params == {"note": "n-shop", "index": 1, "text": "Bread", "checked": False}


@respx.mock
async def test_what_does_not_fit_is_counted_and_ticked_items_can_be_left_out(server: FakeNexnotes) -> None:
    serve(server)
    cut = await adapter.fetch("note", CONFIG, {"note": "n-shop", "limit": 3}, fresh())
    assert [row["title"] for row in cut.items] == ["Milk", "Apples", "Coffee"] and cut.meta["more"] == 3
    hidden = await adapter.fetch("note", CONFIG, {"note": "n-shop", "checked": False}, fresh())
    assert [row["title"] for row in hidden.items] == ["Milk", "Apples", "Coffee", "The dark roast"] and hidden.meta["more"] == 0
    assert hidden.meta["done"] == 2, "the progress counts the whole list, shown or not"


def test_items_nexnotes_left_out_count_among_the_more() -> None:
    note = FakeNexnotes().card("n-shop")
    note["more_items"] = 120
    data = module.note_of(note, True, 12, True, URL)
    assert data.meta["more"] == 120


@respx.mock
async def test_a_read_token_or_a_note_shared_to_read_offers_no_ticking_and_says_why(server: FakeNexnotes) -> None:
    serve(server)
    server.level = "read"
    read = await adapter.fetch("note", CONFIG, {"note": "n-shop"}, fresh())
    assert all("actions" not in row for row in read.items)
    assert read.meta["check_note"] == "Read only: ticking off needs an API token with Read and write."
    server.level = "write"
    shared = await adapter.fetch("note", CONFIG, {"note": "n-trip"}, fresh())
    assert all("actions" not in row for row in shared.items)
    assert shared.meta["check_note"] == "This note is shared with you to read only."


@respx.mock
async def test_a_note_without_a_checklist_shows_its_first_lines(server: FakeNexnotes, ctx: Context) -> None:
    serve(server)
    data = await adapter.fetch("note", CONFIG, {"note": "n-wifi"}, ctx)
    assert data.items == [] and data.primary is None and "done" not in data.meta and "check_note" not in data.meta
    assert data.meta["lines"] == ["The password is on the fridge.", "Guests: the second network."]
    assert data.meta["title"] == "", "an untitled note is named on the screen, in the viewer's language"


@respx.mock
@pytest.mark.parametrize(("note", "code"), [("n-safe", "note_locked"), ("n-gone", "no_note")])
async def test_a_note_that_is_locked_or_gone_is_said_and_forgets_what_it_showed(server: FakeNexnotes, note: str, code: str) -> None:
    serve(server)
    with pytest.raises(AdapterError) as failure:
        await adapter.fetch("note", CONFIG, {"note": note}, fresh())
    assert failure.value.code == code and failure.value.forget is True


@respx.mock
async def test_a_note_in_the_trash_is_said(server: FakeNexnotes) -> None:
    serve(server)
    server.notes["n-shop"]["trashed"] = True
    with pytest.raises(AdapterError) as failure:
        await adapter.fetch("note", CONFIG, {"note": "n-shop"}, fresh())
    assert failure.value.code == "note_trashed" and failure.value.forget is True and failure.value.message == "This note is in the trash."


@pytest.mark.parametrize("wanted", ["", "../dashboard", "n-shop?x=1"])
async def test_a_card_without_a_sound_note_asks_for_one_and_sends_nothing(wanted: str) -> None:
    with respx.mock(assert_all_called=False) as router:
        route = router.route(host="nexnotes")
        with pytest.raises(AdapterError) as failure:
            await adapter.fetch("note", CONFIG, {"note": wanted}, fresh())
        assert failure.value.code == "bad_param" and not route.called


@respx.mock
async def test_the_settings_offer_the_notes_the_token_sees(server: FakeNexnotes, ctx: Context) -> None:
    serve(server)
    offered = await adapter.choices("note", CONFIG, ctx)
    assert offered == [("n-shop", "Shopping · 2/6"), ("n-trip", "Packing · 1/2 · Sam"), ("n-wifi", "Untitled note")]
    assert server.seen[-1].url.params["limit"] == "200"


# -- ticking off -------------------------------------------------------------------------------------------------------


@respx.mock
async def test_a_tap_ticks_an_item_with_the_text_it_was_read_with(server: FakeNexnotes, ctx: Context) -> None:
    serve(server)
    ctx.cache["resp:old"] = object()
    said = await adapter.action("note", "check", {"note": "n-shop", "index": 0, "text": "Milk", "checked": True}, CONFIG, {}, ctx)
    assert said == "Ticked off." and server.notes["n-shop"]["items"][0][1] is True
    posted = server.seen[-1]
    assert posted.method == "POST" and posted.url.path == "/api/v1/notes/n-shop/items/0"
    assert json.loads(posted.content) == {"checked": True, "text": "Milk"}
    assert "origin" not in posted.headers and "resp:old" not in ctx.cache, "the note is read anew after a tick"
    again = await adapter.action("note", "check", {"note": "n-shop", "index": 0, "text": "Milk", "checked": False}, CONFIG, {}, fresh())
    assert again == "Opened again." and server.notes["n-shop"]["items"][0][1] is False


@respx.mock
@pytest.mark.parametrize(("setup", "params", "code"), [
    (lambda fake: None, {"note": "n-shop", "index": 0, "text": "Oat milk", "checked": True}, "item_changed"),
    (lambda fake: None, {"note": "n-shop", "index": 40, "text": "Milk", "checked": True}, "item_changed"),
    (lambda fake: setattr(fake, "level", "read"), {"note": "n-shop", "index": 0, "text": "Milk", "checked": True}, "read_only"),
    (lambda fake: None, {"note": "n-trip", "index": 1, "text": "Chargers", "checked": True}, "not_allowed"),
    (lambda fake: fake.notes["n-shop"].update(locked=True), {"note": "n-shop", "index": 0, "text": "Milk", "checked": True}, "note_locked"),
])
async def test_a_tick_that_cannot_go_through_says_why_and_changes_nothing(server: FakeNexnotes, setup: Any, params: dict[str, Any], code: str) -> None:
    serve(server)
    setup(server)
    before = json.dumps(server.notes)
    with pytest.raises(AdapterError) as failure:
        await adapter.action("note", "check", params, CONFIG, {}, fresh())
    assert failure.value.code == code and json.dumps(server.notes) == before


@pytest.mark.parametrize("params", [
    {"note": "../me", "index": 0, "text": "Milk", "checked": True},
    {"note": "n-shop", "index": "one", "text": "Milk", "checked": True},
    {"note": "n-shop", "index": -1, "text": "Milk", "checked": True},
])
async def test_a_tick_with_parameters_that_cannot_be_an_address_sends_nothing(params: dict[str, Any]) -> None:
    with respx.mock(assert_all_called=False) as router:
        route = router.route(host="nexnotes")
        with pytest.raises(AdapterError) as failure:
            await adapter.action("note", "check", params, CONFIG, {}, fresh())
        assert failure.value.code == "bad_param" and not route.called


# -- the demo ----------------------------------------------------------------------------------------------------------


def test_the_demo_draws_both_cards() -> None:
    note = adapter.demo("note", {}, 3)
    assert note.meta["mode"] == "note" and note.items and note.items[0]["actions"]
    assert [row["checked"] for row in note.items] == sorted(row["checked"] for row in note.items), "open items first"
    pinned = adapter.demo("pinned", {"limit": 2}, 3)
    assert len(pinned.items) == 2 and pinned.meta["more"] == 2
    assert adapter.demo_choices("note")[0] == ("demo-shopping", "Shopping · 2/6")


# -- on the board: the last state while nexnotes is away, nothing of a locked note ---------------------------------------


def connection(client: TestClient) -> int:
    made = client.post("/api/v1/integrations", json={"kind": "nexnotes", "name": "Notes", "config": CONFIG}, headers=CSRF)
    assert made.status_code == 201, made.text
    return int(made.json()["id"])


@pytest.fixture
def board(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, int]:
    setup_admin(client)
    monkeypatch.setattr(collector, "running", False)
    page = int(client.post("/api/v1/boards", json={"name": "Kitchen"}, headers=CSRF).json()["pages"][0]["id"])
    body = {"kind": "nexnotes.note", "integration_id": connection(client), "options": {"note": "n-shop"}}
    made = client.post(f"/api/v1/pages/{page}/widgets", json=body, headers=CSRF)
    assert made.status_code == 201, made.text
    return client, int(made.json()["widget"]["id"])


async def read_card(widget: int) -> WidgetData:
    collector._caches.clear()
    await collector.refresh(widget)
    data = live.get(widget)
    assert data is not None
    return data


@respx.mock
async def test_while_nexnotes_cannot_be_reached_the_card_keeps_its_last_state_and_nothing_can_be_ticked(server: FakeNexnotes, board: tuple[TestClient, int]) -> None:
    serve(server)
    _client, widget = board
    good = await read_card(widget)
    assert good.items[0]["actions"] and not good.error
    server.down = True
    since: set[float] = set()
    for _ in range(3):
        held = await read_card(widget)
        since.add(held.meta["stale_since"])
        assert held.error and held.meta["code"] == "unreachable" and held.meta["offline"] is True
        assert [row["title"] for row in held.items] == [row["title"] for row in good.items], "kept from one failure to the next"
        assert all("actions" not in row for row in held.items)
        assert held.meta["as_of"] == good.meta["as_of"] and held.meta["done"] == 2 and held.meta["offline_note"] is True
    assert since == {good.updated_at}, "the card says since when it shows the last state, not since the last failure"
    with pytest.raises(AdapterError) as refused:
        await collector.run_action(widget, "check", {"note": "n-shop", "index": 0, "text": "Milk", "checked": True}, actor="test", user_id=None)
    assert refused.value.code == "no_such_action"
    server.down = False
    back = await read_card(widget)
    assert not back.error and "offline" not in back.meta and back.items[0]["actions"]


@respx.mock
async def test_a_note_that_is_locked_meanwhile_shows_nothing_of_what_it_showed(server: FakeNexnotes, board: tuple[TestClient, int]) -> None:
    serve(server)
    _client, widget = board
    assert (await read_card(widget)).items
    server.notes["n-shop"]["locked"] = True
    data = await read_card(widget)
    assert data.error and data.meta["code"] == "note_locked"
    assert data.items == [] and "Milk" not in json.dumps(data.model_dump()), "a locked note leaves nothing on the card"


@respx.mock
async def test_any_other_failure_still_greys_the_last_values_once(server: FakeNexnotes, board: tuple[TestClient, int]) -> None:
    serve(server)
    _client, widget = board
    await read_card(widget)
    server.token = "nn_api_other"
    refused = await read_card(widget)
    assert refused.meta["code"] == "auth_failed" and refused.items and "offline" not in refused.meta


@respx.mock
async def test_a_tick_on_an_item_that_changed_reads_the_card_anew_at_once(server: FakeNexnotes, board: tuple[TestClient, int], monkeypatch: pytest.MonkeyPatch) -> None:
    serve(server)
    _client, widget = board
    await read_card(widget)
    server.notes["n-shop"]["items"][0][0] = "Oat milk"
    spawned: list[str] = []
    monkeypatch.setattr(collector_module, "spawn", lambda make, name="": spawned.append(name))
    with pytest.raises(AdapterError) as failure:
        await collector.run_action(widget, "check", {"note": "n-shop", "index": 0, "text": "Milk", "checked": True}, actor="test", user_id=None)
    assert "changed in nexnotes" in failure.value.message
    assert spawned == [f"refresh-{widget}"]
    spawned.clear()
    await collector.run_action(widget, "check", {"note": "n-shop", "index": 2, "text": "Apples", "checked": True}, actor="test", user_id=None)
    assert spawned == [f"refresh-{widget}"] and server.notes["n-shop"]["items"][2][1] is True
