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


def _tile(beschaffung: str | None = None) -> respx.Route:
    """Nexview's dashboard tile. Without ``beschaffung``, as every Nexview
    before nexcrate answers it; with nexcrate, ``nex`` (branch nex, 1.0.0)."""
    tile = {"version": "0.35.2", "befunde": {}, "anfragen": {}, "bibliothek": {}, "instanzen": [], "tickets_offen": 0}
    if beschaffung is not None:
        tile["beschaffung"] = beschaffung
    return respx.get(f"{NEXVIEW}/api/v1/dashboard").mock(return_value=httpx.Response(200, json=tile))


#: A request as Nexview lists it with nexcrate: no folder and no profile, ever;
#: the version it asks for is nexcrate's version id.
WITH_NEXCRATE = {"id": 14, "title": "Copper Sky", "display_name": "Ben", "media_type": "movie", "tier": "uhd",
                 "fassung": "v-films-4k", "root_folder_path": None, "quality_profile_id": None, "poster_path": None}
NEXCRATE_CONFIG = {"beschaffung": "nex", "fassungen": [
    {"kennung": "v-films-hd", "media_type": "movie", "name": "Films HD", "klasse": "hd", "quelle": "nex"},
    {"kennung": "v-films-4k", "media_type": "movie", "name": "Films 4K HDR", "klasse": "uhd", "quelle": "nex"},
]}


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
    # A wall with a touchscreen has no hover; these buttons have to be seen.
    assert data.meta.get("actions_visible") is True


@respx.mock
async def test_a_row_without_a_target_offers_the_lists_of_its_own_instance(ctx: Context) -> None:
    """⚠️ Of its own instance: a film in 4K goes to a different Radarr than the
    same film in 1080p, with different folders and different profiles."""
    _me(["lesen", "entscheiden"], role="approver")
    _waiting(NO_TARGET_4K)
    _tile()
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
    _tile()
    respx.get(f"{NEXVIEW}/api/arr/movie/options").mock(return_value=httpx.Response(200, json=FILMS_4K))
    data = await _fetch(ctx)
    assert [one["name"] for one in data.items[0]["actions"][0]["asks"]] == ["quality_profile_id"]


@respx.mock
async def test_no_list_from_nexview_means_no_button_rather_than_an_empty_choice(ctx: Context) -> None:
    _me(["lesen", "entscheiden"])
    _waiting(NO_TARGET_4K)
    _tile()
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
    _tile()
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


# -- with nexcrate behind Nexview (Nexview 1.0.0) ---------------------------


@respx.mock
async def test_with_nexcrate_a_row_is_approved_without_folder_or_profile(ctx: Context) -> None:
    """⚠️ With nexcrate, Nexview answers the lists with 409 not_in_this_mode,
    and the card took that for "no target" and dropped the approve button on
    every row. There is nothing to choose: folder and profile hang on the version."""
    _me(["lesen", "entscheiden"], role="approver")
    _waiting(WITH_NEXCRATE)
    _tile("nex")
    respx.get(f"{NEXVIEW}/api/config").mock(return_value=httpx.Response(200, json=NEXCRATE_CONFIG))
    options = respx.get(f"{NEXVIEW}/api/arr/movie/options").mock(return_value=httpx.Response(409, json={
        "detail": {"code": "not_in_this_mode", "message": "Nicht in dieser Betriebsart."}}))
    data = await _fetch(ctx)
    row = data.items[0]
    assert not options.called, "with nexcrate there are no lists to ask for"
    assert [one["id"] for one in row["actions"]] == ["approve", "reject"]
    assert "asks" not in row["actions"][0]
    assert row["subtitle"] == "Ben"
    # The version it asks for, by name, instead of folder and profile.
    assert row["value"] == "Films 4K HDR"


@respx.mock
async def test_with_nexcrate_approving_sends_neither_folder_nor_profile(ctx: Context) -> None:
    _me(["lesen", "entscheiden"])
    _waiting(WITH_NEXCRATE)
    _tile("nex")
    respx.get(f"{NEXVIEW}/api/config").mock(return_value=httpx.Response(200, json=NEXCRATE_CONFIG))
    data = await _fetch(ctx)
    approve = data.items[0]["actions"][0]
    # The card's own button through the guard and on to Nexview, as a press would go.
    live.set(7_778, WidgetData(items=data.items))
    try:
        given = collector._refuse_unless_offered(7_778, "approve", dict(approve["params"]))
    finally:
        live.forget(7_778)
    route = respx.post(f"{NEXVIEW}/api/admin/requests/14/approve").mock(return_value=httpx.Response(200, json={}))
    await get_adapter("nexview").action("approvals", "approve", given, CONFIG, {}, ctx)
    assert json.loads(route.calls.last.request.content) == {}


@respx.mock
async def test_with_nexcrate_and_no_names_the_tier_shows_as_before(ctx: Context) -> None:
    _me(["lesen", "entscheiden"])
    _waiting(WITH_NEXCRATE)
    _tile("nex")
    respx.get(f"{NEXVIEW}/api/config").mock(return_value=httpx.Response(500))
    data = await _fetch(ctx)
    assert data.items[0]["value"] == "4K"
    assert [one["id"] for one in data.items[0]["actions"]] == ["approve", "reject"]


@respx.mock
async def test_with_radarr_and_sonarr_said_outright_the_lists_are_asked_as_before(ctx: Context) -> None:
    _me(["lesen", "entscheiden"])
    _waiting(NO_TARGET_4K)
    _tile("arr")
    config = respx.get(f"{NEXVIEW}/api/config")
    options = respx.get(f"{NEXVIEW}/api/arr/movie/options").mock(return_value=httpx.Response(200, json=FILMS_4K))
    data = await _fetch(ctx)
    assert options.called and not config.called
    assert [one["name"] for one in data.items[0]["actions"][0]["asks"]] == ["root_folder_path", "quality_profile_id"]
    assert data.items[0]["value"] == "4K"


@respx.mock
async def test_a_nexview_whose_tile_cannot_be_read_is_taken_for_radarr_and_sonarr(ctx: Context) -> None:
    _me(["lesen", "entscheiden"])
    _waiting(NO_TARGET_4K)
    respx.get(f"{NEXVIEW}/api/v1/dashboard").mock(return_value=httpx.Response(500))
    respx.get(f"{NEXVIEW}/api/arr/movie/options").mock(return_value=httpx.Response(200, json=FILMS_4K))
    data = await _fetch(ctx)
    assert [one["name"] for one in data.items[0]["actions"][0]["asks"]] == ["root_folder_path", "quality_profile_id"]


@respx.mock
async def test_rows_that_carry_their_target_do_not_ask_how_nexview_procures(ctx: Context) -> None:
    _me(["lesen", "entscheiden"])
    _waiting(READY)
    tile = _tile("arr")
    await _fetch(ctx)
    assert not tile.called, "nothing to choose, so nothing to find out"


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
    _tile()
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


@respx.mock
async def test_a_refused_list_gives_nexviews_reason_rather_than_blaming_the_credentials(ctx: Context) -> None:
    """⚠️ The same protection the buttons have, for the list itself. Nexview
    answers 403 for an account that may not decide, and "the service rejected
    the credentials" would send somebody hunting for a typo in a key that is
    perfectly valid."""
    _me(["lesen", "entscheiden"], role="approver")
    respx.get(f"{NEXVIEW}/api/admin/requests").mock(return_value=httpx.Response(403, json={
        "detail": {"code": "approvers_only", "message": "Diese Aktion ist Administratoren und Entscheidern vorbehalten."}}))
    with pytest.raises(AdapterError) as refused:
        await _fetch(ctx)
    assert (refused.value.code, refused.value.message) == (
        "http_error", "This key belongs to an account that approves nothing.")


@respx.mock
async def test_a_profile_that_is_not_a_number_goes_nowhere(ctx: Context) -> None:
    """The guard already refuses a value the row did not offer; this is the
    second lock, for the day a card offers something odd."""
    anything = respx.route(host="nexview.example.com").mock(return_value=httpx.Response(200, json={}))
    with pytest.raises(AdapterError) as refused:
        await get_adapter("nexview").action(
            "approvals", "approve", {"id": 13, "root_folder_path": "/media/films-4k", "quality_profile_id": "Ultra-HD"},
            CONFIG, {}, ctx)
    assert refused.value.code == "bad_param"
    assert not anything.called
