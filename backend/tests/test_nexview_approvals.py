"""Nexview's waiting requests, approved or turned down from the board.

Every path and every shape here was read out of Nexview's own code
(``routers/admin_requests.py``, ``routers/discover.py``, ``routers/v1.py``) on
10.09.2026, not guessed from its documentation. None of it has been run
against a live Nexview yet.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, Context, WidgetData
from app.adapters.nexview import NO_TARGET
from app.services.collector import collector
from app.services.state import live

NEXVIEW = "http://nexview.example.com"
CONFIG = {"url": NEXVIEW, "api_key": "nv_test"}

READY = {"id": 12, "title": "The Quiet Harbour", "display_name": "Anna", "username": "anna",
         "media_type": "movie", "tier": "standard", "root_folder_path": "/media/films",
         "quality_profile_id": 4, "poster_path": "https://image.tmdb.org/t/p/w342/harbour.jpg"}
NO_TARGET_4K = {"id": 13, "title": "Copper Sky", "display_name": "Ben", "media_type": "movie", "tier": "uhd",
                "root_folder_path": None, "quality_profile_id": None, "poster_path": None}
FILMS_4K = {
    "root_folders": [{"path": "/media/films-4k", "free_space": 1}, {"path": "/media/kids-4k"}],
    "quality_profiles": [{"id": 7, "name": "Ultra-HD"}, {"id": 9, "name": "Remux"}],
}


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


def _me(darf: list[str], role: str = "admin") -> respx.Route:
    return respx.get(f"{NEXVIEW}/api/v1/me").mock(return_value=httpx.Response(200, json={
        "version": "0.31.1", "konto": {"id": 1, "username": "nexdeck", "role": role}, "schluessel": None, "darf": darf,
    }))


def _waiting(*rows: dict) -> respx.Route:
    return respx.get(f"{NEXVIEW}/api/admin/requests").mock(return_value=httpx.Response(200, json=list(rows)))


def _fetch(ctx: Context, limit: int = 8):
    return get_adapter("nexview").fetch("approvals", CONFIG, {"limit": limit}, ctx)


# -- what the card shows -----------------------------------------------------


@respx.mock
async def test_a_key_that_may_decide_gets_both_buttons(ctx: Context) -> None:
    _me(["lesen", "anfragen", "entscheiden", "verwalten", "einrichten"])
    listed = _waiting(READY)
    data = await _fetch(ctx)
    assert listed.calls.last.request.url.params["status"] == "pending_approval"
    row = data.items[0]
    assert (row["title"], row["subtitle"], row["art"]) == (
        "The Quiet Harbour", "Anna", "https://image.tmdb.org/t/p/w342/harbour.jpg")
    assert [one["id"] for one in row["actions"]] == ["approve", "reject"]
    # It carries its own target, so approving asks nothing.
    assert "asks" not in row["actions"][0]
    assert data.metrics == {"waiting": 1.0}


@respx.mock
async def test_a_row_without_a_target_offers_the_lists_of_its_own_instance(ctx: Context) -> None:
    """⚠️ Of its own instance: a film in 4K goes to a different Radarr than the
    same film in 1080p, with different folders and different profiles."""
    _me(["lesen", "entscheiden"], role="approver")
    _waiting(NO_TARGET_4K)
    options = respx.get(f"{NEXVIEW}/api/arr/movie/options").mock(return_value=httpx.Response(200, json=FILMS_4K))
    data = await _fetch(ctx)

    assert options.calls.last.request.url.params["tier"] == "uhd"
    asks = data.items[0]["actions"][0]["asks"]
    assert [(one["name"], one["kind"]) for one in asks] == [
        ("root_folder_path", "choice"), ("quality_profile_id", "choice")]
    assert [one["value"] for one in asks[0]["options"]] == ["/media/films-4k", "/media/kids-4k"]
    assert [(one["value"], one["label"]) for one in asks[1]["options"]] == [("7", "Ultra-HD"), ("9", "Remux")]
    assert data.items[0]["value"] == "4K"


@respx.mock
async def test_only_the_missing_half_is_asked(ctx: Context) -> None:
    """Nexview fills a missing half from the request itself, so asking for the
    half it already has would be asking to overwrite it."""
    _me(["lesen", "entscheiden"])
    _waiting({**NO_TARGET_4K, "root_folder_path": "/media/films-4k"})
    respx.get(f"{NEXVIEW}/api/arr/movie/options").mock(return_value=httpx.Response(200, json=FILMS_4K))
    data = await _fetch(ctx)
    assert [one["name"] for one in data.items[0]["actions"][0]["asks"]] == ["quality_profile_id"]


@respx.mock
async def test_no_list_from_nexview_means_no_button_rather_than_an_empty_choice(ctx: Context) -> None:
    _me(["lesen", "entscheiden"])
    _waiting(NO_TARGET_4K)
    respx.get(f"{NEXVIEW}/api/arr/movie/options").mock(return_value=httpx.Response(502))
    data = await _fetch(ctx)
    row = data.items[0]
    assert [one["id"] for one in row["actions"]] == ["reject"]
    assert row["subtitle"] == NO_TARGET


@respx.mock
async def test_a_read_only_key_lists_requests_without_buttons_and_says_why(ctx: Context) -> None:
    """⚠️ An administrator with a read-only key: ``role`` says admin, ``darf``
    says no. The card follows ``darf``."""
    _me(["lesen", "verwalten"], role="admin")
    _waiting(READY)
    data = await _fetch(ctx)
    assert "actions" not in data.items[0]
    assert "only read" in data.meta["notice"]


@respx.mock
async def test_an_account_that_decides_nothing_lists_nothing_and_asks_nothing(ctx: Context) -> None:
    _me(["lesen", "anfragen"], role="user")
    listed = _waiting(READY)
    data = await _fetch(ctx)
    assert data.items == [] and "approves nothing" in data.meta["notice"]
    assert not listed.called, "the card asked for a list its key may not read"


@respx.mock
async def test_ten_waiting_films_ask_for_their_folders_once(ctx: Context) -> None:
    _me(["lesen", "entscheiden"])
    _waiting(*[{**NO_TARGET_4K, "id": 20 + number} for number in range(5)])
    options = respx.get(f"{NEXVIEW}/api/arr/movie/options").mock(return_value=httpx.Response(200, json=FILMS_4K))
    data = await _fetch(ctx)
    assert len(data.items) == 5
    assert options.call_count == 1


@respx.mock
async def test_the_list_is_cut_to_the_card_but_the_count_is_not(ctx: Context) -> None:
    _me(["lesen", "entscheiden"])
    _waiting(*[{**READY, "id": 40 + number} for number in range(12)])
    data = await _fetch(ctx, limit=3)
    assert len(data.items) == 3
    assert data.metrics == {"waiting": 12.0}


# -- what pressing does ------------------------------------------------------


@respx.mock
async def test_approving_sends_the_choice_with_a_number_for_the_profile(ctx: Context) -> None:
    route = respx.post(f"{NEXVIEW}/api/admin/requests/13/approve").mock(return_value=httpx.Response(200, json={}))
    message = await get_adapter("nexview").action(
        "approvals", "approve", {"id": 13, "root_folder_path": "/media/films-4k", "quality_profile_id": "7"},
        CONFIG, {}, ctx)
    assert message == "Approved."
    assert json.loads(route.calls.last.request.read()) == {"root_folder_path": "/media/films-4k", "quality_profile_id": 7}


@respx.mock
async def test_approving_a_request_that_carries_its_target_sends_no_choice(ctx: Context) -> None:
    route = respx.post(f"{NEXVIEW}/api/admin/requests/12/approve").mock(return_value=httpx.Response(200, json={}))
    await get_adapter("nexview").action("approvals", "approve", {"id": 12}, CONFIG, {}, ctx)
    assert json.loads(route.calls.last.request.read()) == {}


@respx.mock
async def test_a_read_only_refusal_says_so_rather_than_blaming_the_credentials(ctx: Context) -> None:
    respx.post(f"{NEXVIEW}/api/admin/requests/12/approve").mock(return_value=httpx.Response(403, json={
        "detail": {"code": "apikey_read_only", "message": "Dieser Schluessel darf nur lesen."}}))
    with pytest.raises(AdapterError) as refused:
        await get_adapter("nexview").action("approvals", "approve", {"id": 12}, CONFIG, {}, ctx)
    assert (refused.value.code, refused.value.message) == ("rejected", "This key may only read.")


@respx.mock
async def test_nexviews_own_reason_passes_through_when_this_card_has_no_words_for_it(ctx: Context) -> None:
    respx.post(f"{NEXVIEW}/api/admin/requests/13/approve").mock(return_value=httpx.Response(422, json={
        "detail": {"code": "ziel_fehlt", "message": "Bitte einen Zielordner für diese Anfrage wählen."}}))
    with pytest.raises(AdapterError) as refused:
        await get_adapter("nexview").action("approvals", "approve", {"id": 13}, CONFIG, {}, ctx)
    assert refused.value.message == "Bitte einen Zielordner für diese Anfrage wählen."


@respx.mock
@pytest.mark.parametrize("request_id", ["../settings", "12", 0, -3, True, None])
async def test_a_request_id_that_is_not_a_positive_number_goes_nowhere(ctx: Context, request_id) -> None:
    anything = respx.route(host="nexview.example.com").mock(return_value=httpx.Response(200, json={}))
    with pytest.raises(AdapterError) as refused:
        await get_adapter("nexview").action("approvals", "approve", {"id": request_id}, CONFIG, {}, ctx)
    assert refused.value.code == "bad_param"
    assert not anything.called


@respx.mock
async def test_turning_down_goes_to_its_own_address(ctx: Context) -> None:
    route = respx.post(f"{NEXVIEW}/api/admin/requests/12/reject").mock(return_value=httpx.Response(200, json={}))
    assert await get_adapter("nexview").action("approvals", "reject", {"id": 12}, CONFIG, {}, ctx) == "Turned down."
    assert route.called


# -- the card and the guard together -----------------------------------------


@respx.mock
async def test_the_guard_takes_a_folder_this_row_offered_and_no_other(ctx: Context) -> None:
    """The card's real output fed to the real guard, so the two cannot drift
    apart: a folder from another instance's list is not a folder for this row."""
    _me(["lesen", "entscheiden"])
    _waiting(NO_TARGET_4K)
    respx.get(f"{NEXVIEW}/api/arr/movie/options").mock(return_value=httpx.Response(200, json=FILMS_4K))
    data = await _fetch(ctx)
    live.set(7_777, WidgetData(items=data.items))
    try:
        given = collector._refuse_unless_offered(
            7_777, "approve", {"id": 13, "root_folder_path": "/media/kids-4k", "quality_profile_id": "9"})
        assert given == {"id": 13, "root_folder_path": "/media/kids-4k", "quality_profile_id": "9"}
        with pytest.raises(AdapterError):
            collector._refuse_unless_offered(
                7_777, "approve", {"id": 13, "root_folder_path": "/media/films", "quality_profile_id": "9"})
    finally:
        live.forget(7_777)


# -- the connection test -----------------------------------------------------


@respx.mock
async def test_the_connection_test_says_whether_the_key_may_approve(ctx: Context) -> None:
    respx.get(f"{NEXVIEW}/api/v1/dashboard").mock(return_value=httpx.Response(200, json={"version": "0.31.1"}))
    route = _me(["lesen", "entscheiden"])
    nexview = get_adapter("nexview")
    assert "may approve" in await nexview.test(CONFIG, ctx)
    route.mock(return_value=httpx.Response(200, json={"konto": {"role": "admin"}, "darf": ["lesen", "verwalten"]}))
    assert "without buttons" in await nexview.test(CONFIG, Context(httpx.AsyncClient(), integration_id=2, cache={}))
