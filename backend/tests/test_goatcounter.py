"""GoatCounter, against the answers of the build of 2025-12-15 (arp242/goatcounter, 27.10.2026).

``fixtures/goatcounter_answers.json`` holds the real shapes of ``/stats/total``,
``/stats/hits``, ``/stats/toprefs``, ``/me`` and ``/status`` for one site with
four visits sent through the API (addresses and pages made up). The days are
moved to end today, since the cards count from the day they are asked.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context, Unreachable, outbound_client

BASE = "https://stats.example.com"
CONFIG = {"url": BASE, "token": "made-up-token"}
ADAPTER = get_adapter("goatcounter")
ANSWERS = json.loads((Path(__file__).parent / "fixtures" / "goatcounter_answers.json").read_text(encoding="utf-8"))


@pytest.fixture
def ctx() -> Context:
    return Context(outbound_client(guard=False), integration_id=1, widget_id=1, cache={})


def rebased() -> dict:
    """The recorded days, moved so that the 27th, the day with the visits, is today."""
    total = json.loads(json.dumps(ANSWERS["total"]))
    today = datetime.now(UTC).date()
    for index, entry in enumerate(total["stats"]):
        entry["day"] = (today - timedelta(days=7 - index)).isoformat()
    return total


def goat() -> None:
    respx.get(f"{BASE}/api/v0/stats/total").mock(return_value=httpx.Response(200, json=rebased()))
    respx.get(f"{BASE}/api/v0/stats/hits").mock(return_value=httpx.Response(200, json=ANSWERS["hits"]))
    respx.get(f"{BASE}/api/v0/stats/toprefs").mock(return_value=httpx.Response(200, json=ANSWERS["refs"]))


@respx.mock
async def test_the_visits_card_counts_today_yesterday_and_the_week(ctx: Context) -> None:
    goat()
    data = await ADAPTER.fetch("visits", CONFIG, {}, ctx)
    assert data.primary == {"label": "Today", "value": 4}
    assert data.secondary == [{"label": "Yesterday", "value": 0}, {"label": "Last 7 days", "value": 4}, {"label": "Last 30 days", "value": 4}]
    assert data.metrics == {"today": 4.0, "week": 4.0}
    assert data.link == BASE
    request = respx.calls.last.request
    assert request.headers["authorization"] == "Bearer made-up-token"
    assert request.url.params["start"].endswith("T00:00:00Z") and request.url.params["end"].endswith("T00:00:00Z")
    start = datetime.fromisoformat(request.url.params["start"].replace("Z", "+00:00"))
    end = datetime.fromisoformat(request.url.params["end"].replace("Z", "+00:00"))
    assert (end - start).days == 30, "thirty days, today included, ending at the coming midnight"


@respx.mock
async def test_the_pages_card_orders_by_visits_and_leaves_events_out(ctx: Context) -> None:
    goat()
    data = await ADAPTER.fetch("pages", CONFIG, {"period": "month", "limit": 8}, ctx)
    assert [(row["title"], row["value"], row["progress"]) for row in data.items] == [("/", "2", 100.0), ("/blog/post-1", "1", 50.0), ("/about", "1", 50.0)]
    assert data.items[0]["subtitle"] == "Home"
    assert data.secondary == [{"label": "Visits", "value": 4}], "the sum over every page, not the number of pages"
    request = respx.calls.last.request
    start = datetime.fromisoformat(request.url.params["start"].replace("Z", "+00:00"))
    end = datetime.fromisoformat(request.url.params["end"].replace("Z", "+00:00"))
    assert (end - start).days == 30 and request.url.params["limit"] == "8"

    events = {"hits": [{"path": "clicked-download", "event": True, "count": 9}, {"path": "/", "title": "/", "event": False, "count": 3}], "total": 2}
    shown = ADAPTER.pages_card(events, 8)
    assert [row["title"] for row in shown.items] == ["/"], "an event is not a page"
    assert shown.items[0]["subtitle"] == "", "a title that repeats the path is not said twice"


@respx.mock
async def test_the_referrers_card_names_visits_without_one(ctx: Context) -> None:
    goat()
    data = await ADAPTER.fetch("referrers", CONFIG, {"period": "today"}, ctx)
    assert [(row["title"], row["value"]) for row in data.items] == [
        ("Direct", "2"), ("https://news.example.org/post", "1"), ("https://search.example.net", "1")]
    assert data.items[0]["subtitle"] == "No referrer"
    request = respx.calls.last.request
    start = datetime.fromisoformat(request.url.params["start"].replace("Z", "+00:00"))
    end = datetime.fromisoformat(request.url.params["end"].replace("Z", "+00:00"))
    assert (end - start).days == 1, "today alone is asked for from the start of today to the coming midnight"


@respx.mock
async def test_the_test_reads_the_statistics_and_says_how_many_visits(ctx: Context) -> None:
    goat()
    assert await ADAPTER.test(CONFIG, ctx) == "GoatCounter accepts the token: 4 visits today."


@respx.mock
async def test_a_wrong_token_is_a_refusal_and_a_token_without_the_permission_says_which(ctx: Context) -> None:
    route = respx.get(f"{BASE}/api/v0/stats/total")
    route.mock(return_value=httpx.Response(401, text="<p>error 401: unknown token</p>"))
    with pytest.raises(AuthFailed) as wrong:
        await ADAPTER.fetch("visits", CONFIG, {}, ctx)
    assert "rejected the token" in wrong.value.message
    route.mock(return_value=httpx.Response(403, text="<p>error 403: requires &#39;stats&#39; permissions</p>"))
    ctx.cache.clear()
    with pytest.raises(AuthFailed) as limited:
        await ADAPTER.fetch("visits", CONFIG, {}, ctx)
    assert "may not read statistics" in limited.value.message and "Settings > API" in limited.value.hint


@respx.mock
async def test_the_rate_limit_and_a_wrong_address_are_told_apart(ctx: Context) -> None:
    respx.get(f"{BASE}/api/v0/stats/hits").mock(return_value=httpx.Response(429, headers={"Retry-After": "1"}, text="rate limited exceeded"))
    with pytest.raises(AdapterError) as busy:
        await ADAPTER.fetch("pages", CONFIG, {}, ctx)
    assert busy.value.code == "rate_limited"
    respx.get(f"{BASE}/api/v0/stats/toprefs").mock(return_value=httpx.Response(404, text="not found"))
    with pytest.raises(AdapterError) as elsewhere:
        await ADAPTER.fetch("referrers", CONFIG, {}, ctx)
    assert elsewhere.value.code == "not_goatcounter"


@respx.mock
async def test_an_unreachable_goatcounter_is_unreachable(ctx: Context) -> None:
    respx.get(f"{BASE}/api/v0/stats/total").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(Unreachable):
        await ADAPTER.fetch("visits", CONFIG, {}, ctx)
