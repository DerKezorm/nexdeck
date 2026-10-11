"""nexdiary's ``GET /api/v1/dashboard`` (nexdiary 0.8.0), and ``routers/v1.py`` for the walls around
it: the counts made up. The adapter was also run against a fresh
instance on 11.10.2026; these tests keep what that showed."""

from __future__ import annotations

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context, outbound_client

CONFIG = {"url": "http://nexdiary:8550", "api_key": "nxa_example"}
BASE = "http://nexdiary:8550/api/v1"
DASHBOARD = {"version": "0.8.0", "today_written": True, "streak": 12, "entries_month": 9, "notes_month": 31,
             "next_capsule": "2026-12-24", "next_capsule_days": 74}


@pytest.fixture
def ctx() -> Context:
    return Context(outbound_client(guard=False), integration_id=1, widget_id=1, cache={})


@respx.mock
async def test_the_diary_card_shows_the_streak_and_the_month(ctx: Context) -> None:
    route = respx.get(f"{BASE}/dashboard").mock(return_value=httpx.Response(200, json=DASHBOARD))
    data = await get_adapter("nexdiary").fetch("diary", CONFIG, {}, ctx)
    assert data.primary == {"label": "Streak", "value": 12, "unit": "days"}
    assert {row["label"]: row["value"] for row in data.secondary} == {"Written today": "Yes", "Entries this month": 9, "Notes this month": 31}
    assert data.metrics == {"streak": 12.0} and data.status == "ok"
    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer nxa_example" and "nxa_" not in str(request.url)
    assert "origin" not in request.headers


@pytest.mark.parametrize(("answer", "value", "unit"), [
    ({"streak": 12, "streak_unit": "days"}, 12, "days"),
    ({"streak": 12, "streak_unit": "weeks"}, 12, "weeks"),
    ({"streak": 1, "streak_unit": "weeks"}, 1, "week"),
    ({"streak": 1, "streak_unit": "days"}, 1, "day"),
    ({"streak": 5}, 5, "days"),
    ({"streak": 5, "streak_unit": "fortnights"}, 5, "days"),
])
@respx.mock
async def test_the_streak_is_counted_in_the_unit_nexdiary_names(answer: dict, value: int, unit: str, ctx: Context) -> None:
    respx.get(f"{BASE}/dashboard").mock(return_value=httpx.Response(200, json={**DASHBOARD, **answer}))
    data = await get_adapter("nexdiary").fetch("diary", CONFIG, {}, ctx)
    assert data.primary == {"label": "Streak", "value": value, "unit": unit}


@respx.mock
async def test_both_cards_share_one_answer_that_is_kept_and_asked_for_rarely(ctx: Context) -> None:
    route = respx.get(f"{BASE}/dashboard").mock(return_value=httpx.Response(200, json=DASHBOARD))
    for kind in ("diary", "capsule", "diary"):
        await get_adapter("nexdiary").fetch(kind, CONFIG, {}, ctx)
    assert route.call_count == 1, "every request makes nexdiary decrypt the whole history"
    assert all(widget.refresh_seconds >= 600 for widget in get_adapter("nexdiary").widgets)


@respx.mock
async def test_a_day_not_yet_written_says_no_and_a_missing_answer_says_nothing(ctx: Context) -> None:
    respx.get(f"{BASE}/dashboard").mock(return_value=httpx.Response(200, json={**DASHBOARD, "today_written": False}))
    data = await get_adapter("nexdiary").fetch("diary", CONFIG, {}, ctx)
    assert {row["label"]: row["value"] for row in data.secondary}["Written today"] == "No"
    respx.get(f"{BASE}/dashboard").mock(return_value=httpx.Response(200, json={"streak": 3}))
    fresh = Context(outbound_client(guard=False), integration_id=1, widget_id=1, cache={})
    bare = await get_adapter("nexdiary").fetch("diary", CONFIG, {}, fresh)
    assert "Written today" not in [row["label"] for row in bare.secondary], "an answer that does not say is not a no"


@respx.mock
async def test_the_capsule_card_counts_the_days_and_names_the_day(ctx: Context) -> None:
    respx.get(f"{BASE}/dashboard").mock(return_value=httpx.Response(200, json=DASHBOARD))
    data = await get_adapter("nexdiary").fetch("capsule", CONFIG, {}, ctx)
    assert data.primary == {"label": "Opens in", "value": 74, "unit": "days"}
    assert data.secondary == [{"label": "On", "value": "2026-12-24"}] and data.metrics == {"capsule_days": 74.0}


@respx.mock
async def test_without_a_sealed_capsule_the_card_says_so(ctx: Context) -> None:
    respx.get(f"{BASE}/dashboard").mock(return_value=httpx.Response(200, json={**DASHBOARD, "next_capsule": None, "next_capsule_days": None}))
    data = await get_adapter("nexdiary").fetch("capsule", CONFIG, {}, ctx)
    assert data.primary == {"label": "Next time capsule", "value": "None sealed"} and data.secondary == [] and data.metrics == {}


@respx.mock
async def test_a_capsule_that_opens_today_is_nought_days_and_a_past_one_is_not_negative(ctx: Context) -> None:
    respx.get(f"{BASE}/dashboard").mock(return_value=httpx.Response(200, json={**DASHBOARD, "next_capsule_days": -2, "next_capsule": "2026-10-09"}))
    data = await get_adapter("nexdiary").fetch("capsule", CONFIG, {}, ctx)
    assert data.primary["value"] == 0


@respx.mock
async def test_the_cards_carry_no_word_of_the_diary(ctx: Context) -> None:
    """Whatever else the answer holds, the cards show their own fields and nothing more."""
    sneaky = {**DASHBOARD, "title": "A secret title", "text": "Dear diary, today", "values": [7, 3], "people": ["Sam"]}
    respx.get(f"{BASE}/dashboard").mock(return_value=httpx.Response(200, json=sneaky))
    for kind in ("diary", "capsule"):
        shown = (await get_adapter("nexdiary").fetch(kind, CONFIG, {}, ctx)).model_dump_json()
        assert "secret" not in shown and "Dear diary" not in shown and "Sam" not in shown, kind


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
        await get_adapter("nexdiary").fetch("diary", CONFIG, {}, ctx)
    assert refused.value.code == ours and words in str(refused.value)
    assert isinstance(refused.value, AuthFailed) is (code == "token_invalid")
    if code == "api_off":
        assert "Settings > API" in refused.value.hint


@respx.mock
async def test_a_nexdiary_without_the_route_says_it_needs_a_newer_version(ctx: Context) -> None:
    respx.get(f"{BASE}/dashboard").mock(return_value=httpx.Response(404, json={"detail": "Not Found"}))
    with pytest.raises(AdapterError) as old:
        await get_adapter("nexdiary").fetch("capsule", CONFIG, {}, ctx)
    assert old.value.code == "too_old" and "needs a newer version" in str(old.value)


@respx.mock
async def test_an_answer_that_is_not_json_names_the_address(ctx: Context) -> None:
    respx.get(f"{BASE}/dashboard").mock(return_value=httpx.Response(200, text="<html>login</html>"))
    with pytest.raises(AdapterError) as refused:
        await get_adapter("nexdiary").fetch("diary", CONFIG, {}, ctx)
    assert refused.value.code == "bad_answer" and "address of nexdiary" in str(refused.value)


@respx.mock
async def test_missing_fields_do_not_bring_the_cards_down(ctx: Context) -> None:
    adapter = get_adapter("nexdiary")
    for answer in ({"streak": None}, {"streak": "many", "next_capsule_days": "soon", "next_capsule": 5}):
        respx.get(f"{BASE}/dashboard").mock(return_value=httpx.Response(200, json=answer))
        for kind in ("diary", "capsule"):
            fresh = Context(outbound_client(guard=False), integration_id=1, widget_id=1, cache={})
            assert (await adapter.fetch(kind, CONFIG, {}, fresh)).status == "ok", (answer, kind)
    for answer in ({}, ["not", "an", "object"]):
        respx.get(f"{BASE}/dashboard").mock(return_value=httpx.Response(200, json=answer))
        fresh = Context(outbound_client(guard=False), integration_id=1, widget_id=1, cache={})
        with pytest.raises(AdapterError) as refused:
            await adapter.fetch("diary", CONFIG, {}, fresh)
        assert refused.value.code == "wrong_app", "an answer with nothing of nexdiary's says so instead of drawing noughts"


@respx.mock
async def test_the_connection_test_names_the_version(ctx: Context) -> None:
    respx.get(f"{BASE}/me").mock(return_value=httpx.Response(200, json={"name": "alex", "display_name": "Alex", "level": "read", "version": "0.8.0"}))
    assert await get_adapter("nexdiary").test(CONFIG, ctx) == "nexdiary 0.8.0 answers; the token of alex reads."


def test_every_demo_draws() -> None:
    adapter = get_adapter("nexdiary")
    for widget in adapter.widgets:
        for tick in (0, 40, 800):
            data = adapter.demo(widget.kind, {}, tick)
            assert data.primary and data.status == "ok", widget.kind
