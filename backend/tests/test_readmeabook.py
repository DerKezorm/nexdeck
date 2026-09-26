"""Issue #19: the ReadMeABook cards against the answers of its admin endpoints.

The answers are shaped after ReadMeABook 1.2.3's own route handlers
(src/app/api/admin/...), the refusals after its auth middleware.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, Context, WidgetData

URL = "https://books.example.com"
CONFIG = {"url": URL, "api_key": "rmab_test-token-for-the-cards"}
RMAB = get_adapter("readmeabook")


def _ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


def _request(number: int, status: str, **extra: object) -> dict:
    return {
        "requestId": f"req-{number}", "title": f"Book {number}", "author": "Mara Ellis", "status": status,
        "type": "audiobook", "user": "alex", "createdAt": "2026-09-26T08:00:00.000Z", "completedAt": None,
        "errorMessage": None, "torrentUrl": None, **extra,
    }


# ---------------------------------------------------------------------------
# The cards
# ---------------------------------------------------------------------------


@respx.mock
async def test_the_overview_counts_and_carries_the_token_in_the_header() -> None:
    route = respx.get(f"{URL}/api/admin/metrics").mock(return_value=httpx.Response(200, json={
        "totalRequests": 184, "activeDownloads": 2, "completedLast30Days": 23, "failedLast30Days": 1, "totalUsers": 6,
        "systemHealth": {"status": "healthy", "issues": []}}))
    card = await RMAB.fetch("overview", CONFIG, {}, _ctx())
    assert route.calls.last.request.headers["Authorization"] == "Bearer rmab_test-token-for-the-cards"
    assert "rmab_" not in str(route.calls.last.request.url), "the token stays out of the address"
    assert card.primary == {"label": "Downloads", "value": 2} and card.status == "ok"
    assert {chip["label"]: chip["value"] for chip in card.secondary} == {
        "Requests": 184, "Done in 30 days": 23, "Failed in 30 days": 1, "Users": 6}
    assert card.metrics == {"downloading": 2.0}


@respx.mock
@pytest.mark.parametrize(("health", "status"), [("degraded", "warn"), ("unhealthy", "bad"), ("something new", "unknown")])
async def test_the_overview_takes_readmeabooks_own_health_and_its_reasons(health: str, status: str) -> None:
    respx.get(f"{URL}/api/admin/metrics").mock(return_value=httpx.Response(200, json={
        "totalRequests": 5, "activeDownloads": 3, "completedLast30Days": 0, "failedLast30Days": 0, "totalUsers": 1,
        "systemHealth": {"status": health, "issues": ["3 stale downloads (>24h)"]}}))
    card = await RMAB.fetch("overview", CONFIG, {}, _ctx())
    assert card.status == status
    assert card.meta["status_reason"] == "3 stale downloads (>24h)"


@respx.mock
async def test_downloads_show_progress_speed_and_time_left() -> None:
    respx.get(f"{URL}/api/admin/downloads/active").mock(return_value=httpx.Response(200, json={"downloads": [
        {"requestId": "a", "title": "The Long Way Home", "author": "Mara Ellis", "status": "downloading", "type": "audiobook",
         "progress": 42, "speed": 2_097_152, "eta": 330, "torrentName": "x", "downloadStatus": "downloading", "user": "alex",
         "startedAt": "2026-09-26T08:00:00.000Z"},
        # The download client did not answer: speed 0 and no time.
        {"requestId": "b", "title": "Copper Sky", "author": "Jon Park", "status": "downloading", "type": "ebook",
         "progress": 0, "speed": 0, "eta": None, "user": "sam", "startedAt": "2026-09-26T08:00:00.000Z"},
    ]}))
    card = await RMAB.fetch("downloads", CONFIG, {}, _ctx())
    assert [(row["title"], row["subtitle"], row["progress"], row["value"]) for row in card.items] == [
        ("The Long Way Home", "Mara Ellis · alex", 42.0, "2.0 MB/s · 5m 30s"),
        ("Copper Sky", "Jon Park · sam · ebook", 0.0, ""),
    ]
    assert card.metrics == {"downloading": 2.0}


@respx.mock
async def test_nothing_downloading_says_so() -> None:
    respx.get(f"{URL}/api/admin/downloads/active").mock(return_value=httpx.Response(200, json={"downloads": []}))
    card = await RMAB.fetch("downloads", CONFIG, {}, _ctx())
    assert card.items == [] and card.meta["empty"] == "Nothing is downloading."


@respx.mock
async def test_requests_say_where_they_stand_and_a_failed_one_shows_why() -> None:
    respx.get(f"{URL}/api/admin/requests/recent").mock(return_value=httpx.Response(200, json={"requests": [
        _request(1, "awaiting_approval"),
        _request(2, "failed", errorMessage="No release matched the book."),
        _request(3, "available"),
        _request(4, "some_state_from_tomorrow"),
    ]}))
    card = await RMAB.fetch("requests", CONFIG, {}, _ctx())
    assert [(row["title"], row["value"], row["status"]) for row in card.items] == [
        ("Book 1", "Awaiting approval", "warn"), ("Book 2", "Failed", "bad"),
        ("Book 3", "Available", "ok"), ("Book 4", "Some state from tomorrow", "unknown")]
    assert card.items[1]["subtitle"] == "No release matched the book."
    assert card.items[0]["subtitle"].startswith("Mara Ellis · alex")
    assert card.status == "ok", "a red row, not a card that stays red until somebody retries"


@respx.mock
async def test_only_open_requests_and_the_limit() -> None:
    respx.get(f"{URL}/api/admin/requests/recent").mock(return_value=httpx.Response(200, json={"requests": [
        _request(1, "available"), _request(2, "downloading"), _request(3, "denied"),
        _request(4, "searching"), _request(5, "cancelled"), _request(6, "awaiting_import"), _request(7, "downloaded")]}))
    open_ones = await RMAB.fetch("requests", CONFIG, {"open_only": True}, _ctx())
    assert [row["title"] for row in open_ones.items] == ["Book 2", "Book 4", "Book 6"]
    assert open_ones.meta["empty"] == "No open request."
    two = await RMAB.fetch("requests", CONFIG, {"limit": 2}, _ctx())
    assert [row["title"] for row in two.items] == ["Book 1", "Book 2"]
    everything = await RMAB.fetch("requests", CONFIG, {"limit": 500}, _ctx())
    assert len(everything.items) == 7


# ---------------------------------------------------------------------------
# Refusals and the test
# ---------------------------------------------------------------------------


@respx.mock
async def test_an_unknown_token_is_a_rejected_credential() -> None:
    respx.get(f"{URL}/api/admin/metrics").mock(return_value=httpx.Response(
        401, json={"error": "Unauthorized", "message": "Invalid or expired API token"}))
    with pytest.raises(AdapterError) as refused:
        await RMAB.fetch("overview", CONFIG, {}, _ctx())
    # The code the collector turns into "the service rejected its credentials".
    assert refused.value.code == "auth_failed"


@respx.mock
async def test_a_users_token_is_told_apart_from_an_old_readmeabook() -> None:
    respx.get(f"{URL}/api/admin/metrics").mock(return_value=httpx.Response(
        403, json={"error": "Forbidden", "message": "Admin access required"}))
    with pytest.raises(AdapterError) as refused:
        await RMAB.fetch("overview", CONFIG, {}, _ctx())
    assert refused.value.code == "readmeabook_not_admin"

    respx.get(f"{URL}/api/admin/metrics").mock(return_value=httpx.Response(
        403, json={"error": "Forbidden", "message": "This endpoint is not available via API token authentication"}))
    with pytest.raises(AdapterError) as refused:
        await RMAB.fetch("overview", CONFIG, {}, _ctx())
    assert refused.value.code == "readmeabook_too_old"


@respx.mock
async def test_a_sign_in_page_instead_of_json_is_named() -> None:
    respx.get(f"{URL}/api/admin/metrics").mock(return_value=httpx.Response(200, text="<html>sign in</html>"))
    with pytest.raises(AdapterError) as refused:
        await RMAB.fetch("overview", CONFIG, {}, _ctx())
    assert refused.value.code == "bad_answer"


@respx.mock
async def test_the_test_names_the_administrator_and_refuses_a_user() -> None:
    respx.get(f"{URL}/api/auth/me").mock(return_value=httpx.Response(200, json={
        "user": {"id": "u1", "plexId": "p1", "username": "robin", "role": "admin"}}))
    respx.get(f"{URL}/api/admin/metrics").mock(return_value=httpx.Response(200, json={"totalRequests": 184}))
    assert await RMAB.test(CONFIG, _ctx()) == "ReadMeABook answers to robin; 184 requests."

    respx.get(f"{URL}/api/auth/me").mock(return_value=httpx.Response(200, json={
        "user": {"id": "u2", "username": "sam", "role": "user"}}))
    with pytest.raises(AdapterError) as refused:
        await RMAB.test(CONFIG, _ctx())
    assert refused.value.code == "readmeabook_not_admin" and "sam" in refused.value.message


# ---------------------------------------------------------------------------
# What it tells about
# ---------------------------------------------------------------------------


def _rows(*states: tuple[int, str]) -> WidgetData:
    return RMAB._requests({"requests": [_request(number, state) for number, state in states]}, 50, False)


def test_a_request_that_was_not_there_is_new_with_who_asked() -> None:
    found = RMAB.detect("requests", _rows((1, "downloading")), _rows((2, "pending"), (1, "downloading")), {})
    assert [(one.event, one.title, one.body) for one in found] == [
        ("request_new", "Book 2 was requested", "Asked for by alex in ReadMeABook.")]


def test_a_request_reaching_its_end_finished_once() -> None:
    before = _rows((1, "processing"), (2, "downloaded"))
    after = _rows((1, "available"), (2, "available"))
    found = RMAB.detect("requests", before, after, {})
    assert [(one.event, one.title) for one in found] == [("download_done", "Book 1 finished")], \
        "an ebook going from downloaded to available is not finishing twice"


def test_a_first_look_and_a_broken_look_stay_quiet() -> None:
    full = _rows((1, "pending"), (2, "available"))
    assert RMAB.detect("requests", None, full, {}) == []
    assert RMAB.detect("requests", WidgetData(error="timeout"), full, {}) == []
    assert RMAB.detect("requests", WidgetData(), full, {}) == []
    assert RMAB.detect("downloads", full, full, {}) == []


def test_a_request_leaving_the_list_is_not_called_finished() -> None:
    assert RMAB.detect("requests", _rows((1, "downloading"), (2, "pending")), _rows((2, "pending")), {}) == []


def test_every_state_readmeabook_has_is_worded() -> None:
    """The states from ReadMeABook's schema comment, 1.2.3."""
    from app.adapters.readmeabook import STATES

    schema = {"pending", "awaiting_approval", "denied", "searching", "downloading", "processing", "downloaded",
              "available", "failed", "cancelled", "awaiting_search", "awaiting_import", "awaiting_release", "warn"}
    assert schema <= set(STATES)


def test_the_demo_draws_every_card() -> None:
    for widget in RMAB.widgets:
        card = RMAB.demo(widget.kind, {}, 7)
        assert card.primary or card.items, widget.kind
