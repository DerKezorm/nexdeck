"""nextasks' ``/api/v1`` as its ``docs/api.md`` (07.11.2026) describes it: ``/me``, ``/dashboard``, ``/lists`` and
``/tasks``, with the walls the whole family shares. Titles, names and days are made up."""

from __future__ import annotations

from datetime import date

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters import nextasks as module
from app.adapters.base import AdapterError, AuthFailed, Context, outbound_client

CONFIG = {"url": "http://nextasks:8510", "api_key": "ntk_example"}
BASE = "http://nextasks:8510/api/v1"
#: nexdeck's own day, which the cards must not use while the answer names the account's zone.
NEXDECK_DAY = date(2026, 11, 7)
#: 23:30 UTC on the 7th is already the 8th in Berlin: the account's today.
AS_OF = "2026-11-07T23:30:00.000Z"


def task(number: int, title: str, due: str | None, *, time: str | None = None, flagged: bool = False,
         people: tuple[str, ...] = (), list_id: str = "l-house", link: bool = True) -> dict:
    return {
        "id": f"t-{number}", "list_id": list_id, "title": title, "notes": "secret notes", "notes_text": "secret notes",
        "due_date": due, "due_time": time, "flagged": flagged, "priority": 0, "tags": ["x"],
        "assignees": [{"id": index, "name": name.lower(), "display_name": name} for index, name in enumerate(people, 1)],
        "completed": False, "trashed": False, "subtasks": {"open": 0, "total": 0},
        "link": f"https://tasks.example.com/lists/{list_id}?task=t-{number}" if link else None,
    }


DASHBOARD = {
    "counts": {"overdue": 2, "today": 3, "upcoming": 5, "assigned_to_me": 4, "flagged": 1, "open": 14},
    "overdue": [task(1, "Return the books", "2026-11-05", people=("Alex",)), task(2, "Pay the bill", "2026-11-07")],
    "today": [task(3, "Water the plants", "2026-11-08", time="18:00", flagged=True), task(4, "Call the plumber", "2026-11-08", time="09:00")],
    "upcoming": [task(5, "Paper bin", "2026-11-09", link=False), task(6, "Present for Grandma", "2026-11-12", people=("Alex", "Sam"))],
    "link": "https://tasks.example.com/today", "time_zone": "Europe/Berlin", "as_of": AS_OF,
}
LISTS = {"lists": [
    {"id": "l-shop", "space_id": "s1", "space_name": "Family", "name": "Shopping", "hidden": False, "open": 3},
    {"id": "l-house", "space_id": "s1", "space_name": "Family", "name": "House", "hidden": False, "open": 9},
    {"id": "l-club", "space_id": "s2", "space_name": "Club", "name": "Party", "hidden": True, "open": 2},
]}
ME = {"name": "robin", "display_name": "Robin", "level": "read", "time_zone": "Europe/Berlin",
      "spaces": [{"id": "s1", "name": "Family"}, {"id": "s2", "name": "Club"}], "version": "0.1.0",
      "features": ["tasks", "dashboard", "external_ref"]}


def fresh() -> Context:
    return Context(outbound_client(guard=False), integration_id=1, widget_id=1, cache={})


@pytest.fixture
def ctx() -> Context:
    return fresh()


@pytest.fixture(autouse=True)
def on_a_known_day(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(module, "_today", lambda: NEXDECK_DAY)


@respx.mock
async def test_today_counts_and_is_red_while_something_is_overdue(ctx: Context) -> None:
    route = respx.get(f"{BASE}/dashboard").mock(return_value=httpx.Response(200, json=DASHBOARD))
    data = await get_adapter("nextasks").fetch("today", CONFIG, {}, ctx)
    assert data.primary == {"label": "Due today", "value": 3}
    assert {row["label"]: row["value"] for row in data.secondary} == {"Overdue": 2, "Next 7 days": 5, "Flagged": 1, "Open": 14}
    assert data.status == "bad" and data.meta["status_reason"] == "Overdue"
    assert data.metrics == {"today": 3.0, "overdue": 2.0}
    assert data.link == "https://tasks.example.com/today"
    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer ntk_example" and "ntk_" not in str(request.url)
    assert "origin" not in request.headers
    assert request.url.params["limit"] == "20"


@respx.mock
async def test_today_turns_yellow_from_the_number_it_was_told_and_0_switches_it_off(ctx: Context) -> None:
    calm = {**DASHBOARD, "counts": {**DASHBOARD["counts"], "overdue": 0}}
    respx.get(f"{BASE}/dashboard").mock(return_value=httpx.Response(200, json=calm))
    adapter = get_adapter("nextasks")
    assert (await adapter.fetch("today", CONFIG, {}, fresh())).status == "ok", "three today is under five"
    at = await adapter.fetch("today", CONFIG, {"warn_today": 3}, fresh())
    assert at.status == "warn" and at.meta["status_reason"] == "Due today", "yellow at the number, not only above it"
    assert (await adapter.fetch("today", CONFIG, {"warn_today": 4}, fresh())).status == "ok"
    assert (await adapter.fetch("today", CONFIG, {"warn_today": 0}, fresh())).status == "ok", "0 switches it off"
    assert (await adapter.fetch("today", CONFIG, {"warn_today": "many"}, fresh())).status == "ok", "not a number is the default"


@respx.mock
async def test_due_lists_overdue_first_and_counts_days_in_the_accounts_zone(ctx: Context) -> None:
    respx.get(f"{BASE}/dashboard").mock(return_value=httpx.Response(200, json=DASHBOARD))
    data = await get_adapter("nextasks").fetch("due", CONFIG, {}, ctx)
    rows = [(item["title"], item.get("value"), item["status"]) for item in data.items]
    # Berlin's today is the 8th: the day of nexdeck's clock (the 7th) would make every value one day off.
    assert rows == [
        ("Return the books", "3 d overdue", "bad"),
        ("Pay the bill", "1 d overdue", "bad"),
        ("Call the plumber", "Today", "warn"),
        ("Water the plants", "Today", "warn"),
        ("Paper bin", "Tomorrow", "ok"),
        ("Present for Grandma", "in 4 d", "ok"),
    ]
    assert data.status == "bad" and data.link == "https://tasks.example.com/today"
    by_title = {item["title"]: item for item in data.items}
    assert by_title["Water the plants"]["subtitle"] == "2026-11-08 18:00 · Flagged"
    assert by_title["Present for Grandma"]["subtitle"] == "2026-11-12 · Alex, Sam"
    assert by_title["Return the books"]["url"] == "https://tasks.example.com/lists/l-house?task=t-1"
    assert by_title["Paper bin"]["url"] == "http://nextasks:8510", "a task without a link opens nextasks"
    assert all("secret" not in str(item) for item in data.items), "notes never reach a card"


@respx.mock
async def test_due_keeps_to_its_number_of_entries_and_is_calm_without_overdue(ctx: Context) -> None:
    calm = {**DASHBOARD, "overdue": []}
    respx.get(f"{BASE}/dashboard").mock(return_value=httpx.Response(200, json=calm))
    data = await get_adapter("nextasks").fetch("due", CONFIG, {"limit": 2}, ctx)
    assert [item["title"] for item in data.items] == ["Call the plumber", "Water the plants"]
    assert data.status == "ok", "due today is a yellow row, not a yellow card"


@respx.mock
async def test_without_a_zone_the_days_are_nexdecks(ctx: Context) -> None:
    respx.get(f"{BASE}/dashboard").mock(return_value=httpx.Response(200, json={**DASHBOARD, "time_zone": None}))
    data = await get_adapter("nextasks").fetch("due", CONFIG, {}, ctx)
    assert [item.get("value") for item in data.items][2:4] == ["Tomorrow", "Tomorrow"]
    respx.get(f"{BASE}/dashboard").mock(return_value=httpx.Response(200, json={**DASHBOARD, "time_zone": "Mars/Olympus"}))
    odd = await get_adapter("nextasks").fetch("due", CONFIG, {}, fresh())
    assert odd.items[2]["value"] == "Tomorrow", "a zone nobody knows is no reason to fail"


@respx.mock
async def test_assigned_counts_from_the_dashboard_and_lists_its_own_soonest_first(ctx: Context) -> None:
    respx.get(f"{BASE}/dashboard").mock(return_value=httpx.Response(200, json=DASHBOARD))
    respx.get(f"{BASE}/lists").mock(return_value=httpx.Response(200, json=LISTS))
    mine = respx.get(f"{BASE}/tasks").mock(return_value=httpx.Response(200, json={"tasks": [
        task(10, "No date", None, people=("Robin",)),
        task(11, "Later", "2026-11-20", people=("Robin",)),
        task(12, "In a hidden space", "2026-11-08", people=("Robin",), list_id="l-club"),
        task(13, "Soon", "2026-11-08", time="08:00", people=("Robin",)),
        {"id": "t-14", "gone": True},
    ], "next_cursor": None, "as_of": AS_OF}))
    data = await get_adapter("nextasks").fetch("assigned", CONFIG, {}, ctx)
    assert data.primary == {"label": "Assigned to me", "value": 4} and data.meta["headline"] is True
    assert data.metrics == {"assigned": 4.0}
    assert [(item["title"], item.get("value")) for item in data.items] == [("Soon", "Today"), ("Later", "in 12 d"), ("No date", None)]
    assert all("Robin" not in item["subtitle"] for item in data.items), "every row would name the same account"
    params = mine.calls.last.request.url.params
    assert (params["assigned"], params["state"]) == ("me", "open")


@respx.mock
async def test_the_dashboard_cards_ask_nextasks_once(ctx: Context) -> None:
    dashboard = respx.get(f"{BASE}/dashboard").mock(return_value=httpx.Response(200, json=DASHBOARD))
    respx.get(f"{BASE}/lists").mock(return_value=httpx.Response(200, json=LISTS))
    respx.get(f"{BASE}/tasks").mock(return_value=httpx.Response(200, json={"tasks": []}))
    for kind in ("today", "due", "assigned"):
        await get_adapter("nextasks").fetch(kind, CONFIG, {"limit": 3 if kind == "due" else 8}, ctx)
    assert dashboard.call_count == 1, "the three cards of one connection share one answer, whatever their entries"


@respx.mock
async def test_the_list_card_shows_one_list_in_nextasks_order(ctx: Context) -> None:
    respx.get(f"{BASE}/me").mock(return_value=httpx.Response(200, json=ME))
    route = respx.get(f"{BASE}/tasks").mock(return_value=httpx.Response(200, json={"tasks": [
        task(20, "Milk", None, list_id="l-shop"), task(21, "Bread", "2026-11-06", list_id="l-shop"),
        task(22, "Apples", None, list_id="l-shop"),
    ], "next_cursor": None, "as_of": AS_OF}))
    data = await get_adapter("nextasks").fetch("list", CONFIG, {"list": "l-shop", "limit": 2}, ctx)
    assert [item["title"] for item in data.items] == ["Milk", "Bread"], "nextasks' own order, not by date"
    assert data.primary == {"label": "Open", "value": 3}
    assert data.items[1]["value"] == "2 d overdue" and data.status == "bad", "Berlin's 8th: the zone of /me at the moment of the answer"
    params = route.calls.last.request.url.params
    assert (params["list_id"], params["state"]) == ("l-shop", "open")


@respx.mock
async def test_the_list_card_asks_for_a_list_and_says_when_it_is_gone(ctx: Context) -> None:
    adapter = get_adapter("nextasks")
    with pytest.raises(AdapterError) as unset:
        await adapter.fetch("list", CONFIG, {}, ctx)
    assert unset.value.code == "bad_param" and "Pick a list" in str(unset.value)
    respx.get(f"{BASE}/tasks").mock(return_value=httpx.Response(404, json={"detail": {"code": "not_found", "message": "x"}}))
    with pytest.raises(AdapterError) as gone:
        await adapter.fetch("list", CONFIG, {"list": "l-old"}, fresh())
    assert gone.value.code == "no_list" and "no such list" in str(gone.value)


@respx.mock
async def test_the_lists_are_offered_by_space_and_name(ctx: Context) -> None:
    respx.get(f"{BASE}/lists").mock(return_value=httpx.Response(200, json={"lists": [*LISTS["lists"], {"name": "No id"}, "junk"]}))
    assert await get_adapter("nextasks").choices("list", CONFIG, ctx) == [
        ("l-shop", "Family › Shopping"), ("l-house", "Family › House"), ("l-club", "Club › Party")]


@pytest.mark.parametrize(("status", "code", "ours", "words"), [
    (403, "origin_refused", "origin_refused", "Origin"),
    (401, "api_off", "api_off", "switched off"),
    (401, "token_invalid", "auth_failed", "does not know this token"),
    (429, "slow_down", "rate_limited", "fewer requests"),
    (500, "", "http_error", "HTTP 500"),
])
@respx.mock
async def test_each_refusal_says_what_to_do(status: int, code: str, ours: str, words: str, ctx: Context) -> None:
    body = {"detail": {"code": code, "message": "x"}} if code else {}
    respx.get(f"{BASE}/dashboard").mock(return_value=httpx.Response(status, json=body))
    with pytest.raises(AdapterError) as refused:
        await get_adapter("nextasks").fetch("today", CONFIG, {}, ctx)
    assert refused.value.code == ours and words in str(refused.value)
    assert isinstance(refused.value, AuthFailed) is (code == "token_invalid")
    if code == "api_off":
        assert "Settings > Server > API" in refused.value.hint


@respx.mock
async def test_a_nextasks_without_the_route_says_it_needs_a_newer_version(ctx: Context) -> None:
    respx.get(f"{BASE}/dashboard").mock(return_value=httpx.Response(404, json={"detail": "Not Found"}))
    with pytest.raises(AdapterError) as old:
        await get_adapter("nextasks").fetch("due", CONFIG, {}, ctx)
    assert old.value.code == "too_old" and "needs a newer version" in str(old.value)


@respx.mock
async def test_missing_fields_do_not_bring_the_cards_down(ctx: Context) -> None:
    adapter = get_adapter("nextasks")
    odd = {"counts": "many", "overdue": ["junk", None, {"title": "No date"}], "today": None, "upcoming": [{"due_date": "soon"}]}
    respx.get(f"{BASE}/dashboard").mock(return_value=httpx.Response(200, json=odd))
    today = await adapter.fetch("today", CONFIG, {}, ctx)
    assert today.primary == {"label": "Due today", "value": 0} and today.status == "ok"
    due = await adapter.fetch("due", CONFIG, {}, ctx)
    assert [(item["title"], item.get("value")) for item in due.items] == [("No date", None), ("?", None)]
    for answer in (["not", "an", "object"], {}, {"boards": 3}):
        respx.get(f"{BASE}/dashboard").mock(return_value=httpx.Response(200, json=answer))
        with pytest.raises(AdapterError) as refused:
            await adapter.fetch("today", CONFIG, {}, fresh())
        assert refused.value.code == "wrong_app", "an answer with nothing of nextasks' says so instead of drawing noughts"


@respx.mock
async def test_the_connection_test_names_the_level_and_the_spaces(ctx: Context) -> None:
    adapter = get_adapter("nextasks")
    respx.get(f"{BASE}/me").mock(return_value=httpx.Response(200, json=ME))
    assert await adapter.test(CONFIG, ctx) == "nextasks 0.1.0 answers; the token of Robin reads and sees 2 spaces: Family, Club."
    respx.get(f"{BASE}/me").mock(return_value=httpx.Response(200, json={**ME, "level": "write", "spaces": [{"id": "s1", "name": "Family"}]}))
    assert await adapter.test(CONFIG, fresh()) == (
        "nextasks 0.1.0 answers; the token of Robin reads and writes; the cards only read and sees 1 space: Family.")
    respx.get(f"{BASE}/me").mock(return_value=httpx.Response(200, json={**ME, "spaces": []}))
    assert (await adapter.test(CONFIG, fresh())).endswith("sees no space.")


@respx.mock
async def test_the_connection_test_turns_down_a_nextasks_without_the_dashboard(ctx: Context) -> None:
    respx.get(f"{BASE}/me").mock(return_value=httpx.Response(200, json={**ME, "features": ["tasks"]}))
    with pytest.raises(AdapterError) as old:
        await get_adapter("nextasks").test(CONFIG, ctx)
    assert old.value.code == "too_old"
    respx.get(f"{BASE}/me").mock(return_value=httpx.Response(200, json={**ME, "features": "dashboard"}))
    with pytest.raises(AdapterError) as odd:
        await get_adapter("nextasks").test(CONFIG, fresh())
    assert odd.value.code == "too_old", "a text that only contains the word is no list of features"


def test_every_demo_draws() -> None:
    adapter = get_adapter("nextasks")
    for widget in adapter.widgets:
        for tick in (0, 40, 800):
            options = {field.name: field.default for field in widget.options}
            data = adapter.demo(widget.kind, options, tick)
            assert data.items or data.primary, widget.kind
    assert [value for value, _label in adapter.demo_choices("list")] == ["demo-shopping", "demo-house", "demo-club"]
    assert adapter.demo("due", {}, 0).items == adapter.demo("due", {}, 0).items, "the demo is the same each time it is drawn"
