"""nexpaper's ``GET /api/v1/dashboard`` as agreed with it (nexpaper 1.1.0), and ``routers/v1.py`` for the walls around
it: the answer is the agreed one, the titles and counts made up. Not measured against a running instance."""

from __future__ import annotations

from datetime import date

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters import nexpaper as module
from app.adapters.base import AdapterError, AuthFailed, Context, outbound_client

CONFIG = {"url": "http://nexpaper:8560", "api_key": "npk_example"}
BASE = "http://nexpaper:8560/api/v1"
TODAY = date(2026, 10, 11)
NOW = 1_791_706_800.0  # 2026-10-11 08:20 UTC


def waiting(number: int, title: str, added: str) -> dict:
    return {"id": number, "title": title, "added_at": added, "url": f"https://paper.example.com/d/{number}"}


DASHBOARD = {
    "version": "1.1.0", "inbox": 7,
    "inbox_oldest": [waiting(12, "Scan from the printer", "2026-10-01T08:12:00+00:00"), waiting(15, "Phone bill", "2026-10-09T18:00:00+00:00")],
    "inbox_oldest_at": "2026-10-01T08:12:00+00:00", "filed": 412, "total": 419, "added_week": 9, "processing": 1,
    "deadlines": [
        {"id": 41, "title": "Tax return", "date": "2026-10-20", "kind": "due", "url": "https://paper.example.com/d/41"},
        {"id": 40, "title": "Car insurance", "date": "2026-10-13", "kind": "due", "url": "https://paper.example.com/d/40"},
        {"id": 42, "title": "Gym membership", "date": "2026-11-30", "kind": "due", "url": "https://paper.example.com/d/42"},
        {"id": 39, "title": "Electricity bill", "date": "2026-10-10", "kind": "due", "url": "https://paper.example.com/d/39"},
    ],
}


@pytest.fixture
def ctx() -> Context:
    return Context(outbound_client(guard=False), integration_id=1, widget_id=1, cache={})


@pytest.fixture(autouse=True)
def on_the_measured_day(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(module, "_today", lambda: TODAY)
    monkeypatch.setattr(module, "_now", lambda: NOW)


@respx.mock
async def test_the_inbox_counts_and_lists_the_oldest_with_a_link(ctx: Context) -> None:
    route = respx.get(f"{BASE}/dashboard").mock(return_value=httpx.Response(200, json=DASHBOARD))
    data = await get_adapter("nexpaper").fetch("inbox", CONFIG, {}, ctx)
    assert data.primary == {"label": "In the inbox", "value": 7} and data.meta["headline"] is True
    first, second = data.items
    assert (first["title"], first["url"], first["status"]) == ("Scan from the printer", "https://paper.example.com/d/12", "ok")
    assert first["when"] == 1_790_842_320.0  # 2026-10-01 08:12 UTC
    assert data.secondary == [{"label": "Oldest", "value": "10 d"}]
    assert data.status == "ok", "seven documents of ten days is under both limits"
    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer npk_example" and "npk_" not in str(request.url)
    assert "origin" not in request.headers


@respx.mock
async def test_the_inbox_turns_yellow_by_count_or_by_age_as_the_card_was_told(ctx: Context) -> None:
    respx.get(f"{BASE}/dashboard").mock(return_value=httpx.Response(200, json=DASHBOARD))
    adapter = get_adapter("nexpaper")
    by_count = await adapter.fetch("inbox", CONFIG, {"warn_count": 7, "warn_days": 30}, ctx)
    assert by_count.status == "warn" and by_count.meta["status_reason"] == "7 in the inbox"
    by_age = await adapter.fetch("inbox", CONFIG, {"warn_count": 10, "warn_days": 9}, ctx)
    assert by_age.status == "warn" and by_age.meta["status_reason"] == "oldest 10 d old"
    assert [item["status"] for item in by_age.items] == ["warn", "ok"], "the row that has waited too long is the yellow one"
    edge = await adapter.fetch("inbox", CONFIG, {"warn_count": 10, "warn_days": 10}, ctx)
    assert edge.status == "ok" and edge.items[0]["status"] == "ok", "yellow is longer than the limit, not as long as it"
    both = await adapter.fetch("inbox", CONFIG, {"warn_count": 5, "warn_days": 5}, ctx)
    assert both.meta["status_reason"] == "7 in the inbox · oldest 10 d old"
    off = await adapter.fetch("inbox", CONFIG, {"warn_count": 0, "warn_days": 0}, ctx)
    assert off.status == "ok" and off.meta["status_reason"] == "", "0 switches a limit off"
    default = await adapter.fetch("inbox", CONFIG, {"warn_count": "", "warn_days": "x"}, ctx)
    assert default.status == "ok", "what is not a number is the default (10 documents, 14 days)"


@respx.mock
async def test_an_empty_inbox_is_calm_and_says_so(ctx: Context) -> None:
    respx.get(f"{BASE}/dashboard").mock(return_value=httpx.Response(200, json={"inbox": 0, "inbox_oldest": [], "inbox_oldest_at": None}))
    data = await get_adapter("nexpaper").fetch("inbox", CONFIG, {"warn_count": 1, "warn_days": 1}, ctx)
    assert data.status == "ok" and data.items == [] and data.secondary == [] and data.meta["empty"] == "The inbox is empty."


@respx.mock
async def test_deadlines_come_soonest_first_yellow_within_three_days_and_red_when_overdue(ctx: Context) -> None:
    respx.get(f"{BASE}/dashboard").mock(return_value=httpx.Response(200, json=DASHBOARD))
    data = await get_adapter("nexpaper").fetch("deadlines", CONFIG, {}, ctx)
    assert [(item["title"], item["subtitle"], item["value"], item["status"]) for item in data.items] == [
        ("Electricity bill", "2026-10-10", "1 d overdue", "bad"),
        ("Car insurance", "2026-10-13", "in 2 d", "warn"),
        ("Tax return", "2026-10-20", "in 9 d", "ok"),
    ]
    assert data.items[1]["url"] == "https://paper.example.com/d/40"
    assert data.status == "bad", "the 30th of November is beyond the 14 days and is left out"

    calm = {"deadlines": [DASHBOARD["deadlines"][0]]}
    respx.get(f"{BASE}/dashboard").mock(return_value=httpx.Response(200, json=calm))
    fresh = Context(outbound_client(guard=False), integration_id=1, widget_id=1, cache={})
    assert (await get_adapter("nexpaper").fetch("deadlines", CONFIG, {}, fresh)).status == "ok"


def test_the_day_is_named_and_the_edges_are_the_right_side() -> None:
    def rows(*days: str) -> list[tuple[str, str, str]]:
        data = module.deadlines_of({"deadlines": [{"id": number, "title": f"t{number}", "date": day} for number, day in enumerate(days)]}, TODAY, 10, "http://x")
        return [(item["value"], item["status"], item["subtitle"]) for item in data.items]

    assert rows("2026-10-11") == [("Today", "warn", "2026-10-11")]
    assert rows("2026-10-12") == [("Tomorrow", "warn", "2026-10-12")]
    assert rows("2026-10-14") == [("in 3 d", "warn", "2026-10-14")], "three days is still yellow"
    assert rows("2026-10-15") == [("in 4 d", "ok", "2026-10-15")]
    assert rows("2026-10-25") == [("in 14 d", "ok", "2026-10-25")], "the fourteenth day is in"
    assert rows("2026-10-26") == []
    assert rows("not a day", "", "2026-10-12T09:00:00") == [("Tomorrow", "warn", "2026-10-12")], "a time after the day is ignored, a non-day is skipped"


@respx.mock
async def test_the_filing_card_counts_and_records_the_total(ctx: Context) -> None:
    respx.get(f"{BASE}/dashboard").mock(return_value=httpx.Response(200, json=DASHBOARD))
    data = await get_adapter("nexpaper").fetch("library", CONFIG, {}, ctx)
    assert data.primary == {"label": "Documents", "value": 419}
    assert {row["label"]: row["value"] for row in data.secondary} == {"Filed": 412, "This week": 9, "Reading text": 1}
    assert data.metrics == {"documents": 419.0}


@respx.mock
async def test_the_three_cards_ask_nexpaper_once(ctx: Context) -> None:
    route = respx.get(f"{BASE}/dashboard").mock(return_value=httpx.Response(200, json=DASHBOARD))
    for kind in ("inbox", "deadlines", "library"):
        await get_adapter("nexpaper").fetch(kind, CONFIG, {}, ctx)
    assert route.call_count == 1, "the three cards of one connection share one answer"


@pytest.mark.parametrize(("status", "code", "ours", "words"), [
    (403, "origin_refused", "origin_refused", "Origin"),
    (401, "api_off", "api_off", "switched off"),
    (401, "key_invalid", "auth_failed", "does not know this key"),
    (401, "token_wrong_kind", "wrong_kind", "device token"),
    (403, "key_scope", "wrong_scope", "only upload"),
    (429, "slow_down", "rate_limited", "fewer requests"),
    (429, "too_many_attempts", "rate_limited", "rest for a while"),
    (500, "", "http_error", "HTTP 500"),
])
@respx.mock
async def test_each_refusal_says_what_to_do(status: int, code: str, ours: str, words: str, ctx: Context) -> None:
    body = {"detail": {"code": code, "message": "x"}} if code else {}
    respx.get(f"{BASE}/dashboard").mock(return_value=httpx.Response(status, json=body))
    with pytest.raises(AdapterError) as refused:
        await get_adapter("nexpaper").fetch("inbox", CONFIG, {}, ctx)
    assert refused.value.code == ours and words in str(refused.value)
    assert isinstance(refused.value, AuthFailed) is (code == "key_invalid")
    if code == "api_off":
        assert "Settings > API" in refused.value.hint


@respx.mock
async def test_a_nexpaper_without_the_route_says_it_needs_a_newer_version(ctx: Context) -> None:
    respx.get(f"{BASE}/dashboard").mock(return_value=httpx.Response(404, json={"detail": "Not Found"}))
    with pytest.raises(AdapterError) as old:
        await get_adapter("nexpaper").fetch("library", CONFIG, {}, ctx)
    assert old.value.code == "too_old" and "needs a newer version" in str(old.value)


@respx.mock
async def test_missing_fields_do_not_bring_the_card_down(ctx: Context) -> None:
    adapter = get_adapter("nexpaper")
    respx.get(f"{BASE}/dashboard").mock(return_value=httpx.Response(200, json={}))
    for kind in ("inbox", "deadlines", "library"):
        fresh = Context(outbound_client(guard=False), integration_id=1, widget_id=1, cache={})
        data = await adapter.fetch(kind, CONFIG, {}, fresh)
        assert data.status == "ok", kind
    odd = {"inbox": "many", "inbox_oldest": ["junk", None, {"title": "No date"}], "inbox_oldest_at": "yesterday",
           "deadlines": ["junk", {"title": "No date"}, {"date": "2026-10-12"}], "total": None, "added_week": "3"}
    respx.get(f"{BASE}/dashboard").mock(return_value=httpx.Response(200, json=odd))
    fresh = Context(outbound_client(guard=False), integration_id=1, widget_id=1, cache={})
    inbox = await adapter.fetch("inbox", CONFIG, {}, fresh)
    assert inbox.primary == {"label": "In the inbox", "value": 0} and [item["title"] for item in inbox.items] == ["No date"]
    assert (await adapter.fetch("deadlines", CONFIG, {}, fresh)).items[0]["title"] == "?"
    assert {row["label"]: row["value"] for row in (await adapter.fetch("library", CONFIG, {}, fresh)).secondary}["This week"] == 3
    respx.get(f"{BASE}/dashboard").mock(return_value=httpx.Response(200, json=["not", "an", "object"]))
    again = Context(outbound_client(guard=False), integration_id=1, widget_id=1, cache={})
    assert (await adapter.fetch("inbox", CONFIG, {}, again)).items == []


@respx.mock
async def test_the_connection_test_names_the_version_and_turns_down_an_upload_key(ctx: Context) -> None:
    respx.get(f"{BASE}/me").mock(return_value=httpx.Response(200, json={"name": "alex", "display_name": "Alex", "scope": "read", "version": "1.1.0"}))
    assert await get_adapter("nexpaper").test(CONFIG, ctx) == "nexpaper 1.1.0 answers; the key of alex reads."
    respx.get(f"{BASE}/me").mock(return_value=httpx.Response(200, json={"name": "alex", "scope": "upload", "version": "1.1.0"}))
    fresh = Context(outbound_client(guard=False), integration_id=1, widget_id=1, cache={})
    with pytest.raises(AdapterError) as upload:
        await get_adapter("nexpaper").test(CONFIG, fresh)
    assert upload.value.code == "wrong_scope"


def test_every_demo_draws() -> None:
    adapter = get_adapter("nexpaper")
    for widget in adapter.widgets:
        for tick in (0, 40, 800):
            options = {field.name: field.default for field in widget.options}
            data = adapter.demo(widget.kind, options, tick)
            assert data.items or data.primary, widget.kind
