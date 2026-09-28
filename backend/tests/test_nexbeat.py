"""nexbeat: requests, library and approvals through nexbeat's /api/v1.

The shapes here are nexbeat's own answers, read out of its ``routers/v1.py``
and ``services/requests_service.py``. On 2026-09-28 all three cards, both
buttons, a read-only token, a user's token and a wrong one ran against the
released nexbeat 1.2.0 image, on a fresh database without Lidarr.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, Context, WidgetData
from app.services.collector import collector
from app.services.state import live

NEXBEAT = "http://nexbeat.example.com"
CONFIG = {"url": NEXBEAT, "api_key": "nxb_test"}

ALBUM = {"id": 21, "kind": "album", "title": "Northern Lights", "artist_name": "The Quiet Harbour",
         "album_type": "Album", "status": "pending_approval",
         "cover_url": "https://coverartarchive.org/release-group/99999999-9999-4999-8999-999999999999/front-500",
         "user": {"id": 2, "username": "anna", "display_name": "Anna"}}
ARTIST = {"id": 22, "kind": "artist", "title": "Copper Sky", "artist_name": "Copper Sky", "album_type": "",
          "status": "pending_approval",
          "cover_url": "/api/images/artist/88888888-8888-4888-8888-888888888888?name=Copper%20Sky",
          "user": {"id": 3, "username": "ben", "display_name": ""}}

TILE = {"version": "1.2.0", "scope": "all", "target": "lidarr", "requests_enabled": True,
        "requests": {"waiting": 3, "running": 2, "failed": 0, "done_last_7_days": 9},
        "library": {"artists": 412, "artists_with_music": 388, "albums": 2961}}


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


def _me(may: list[str], role: str = "admin") -> respx.Route:
    return respx.get(f"{NEXBEAT}/api/v1/me").mock(return_value=httpx.Response(200, json={
        "version": "1.2.0", "account": {"id": 1, "username": "admin", "display_name": "", "role": role},
        "key": {"name": "nexdeck", "read_only": "decide" not in may}, "may": may,
    }))


def _tile(**changes) -> respx.Route:
    return respx.get(f"{NEXBEAT}/api/v1/dashboard").mock(return_value=httpx.Response(200, json={**TILE, **changes}))


def _waiting(*rows: dict) -> respx.Route:
    return respx.get(f"{NEXBEAT}/api/v1/admin/requests").mock(return_value=httpx.Response(200, json=list(rows)))


def _fetch(ctx: Context, kind: str = "approvals", limit: int = 8):
    return get_adapter("nexbeat").fetch(kind, CONFIG, {"limit": limit}, ctx)


# -- the number cards ----------------------------------------------------------


@respx.mock
async def test_the_requests_card_counts_and_sends_the_token(ctx: Context) -> None:
    route = _tile()
    data = await _fetch(ctx, "requests")
    assert route.calls.last.request.headers["Authorization"] == "Bearer nxb_test"
    assert data.status == "ok"
    assert data.primary == {"label": "Waiting", "value": 3}
    assert data.secondary == [{"label": "Running", "value": 2}, {"label": "Failed", "value": 0},
                              {"label": "This week", "value": 9}]
    assert data.metrics == {"waiting": 3.0, "running": 2.0}
    assert "notice" not in data.meta


@respx.mock
async def test_failed_requests_turn_the_card_yellow_and_say_why(ctx: Context) -> None:
    _tile(requests={"waiting": 0, "running": 0, "failed": 2, "done_last_7_days": 0})
    data = await _fetch(ctx, "requests")
    assert (data.status, data.meta["status_reason"]) == ("warn", "2 request(s) failed")


@respx.mock
async def test_without_a_target_the_requests_only_wait_and_the_card_says_so(ctx: Context) -> None:
    _tile(requests_enabled=False, target=None)
    requests = await _fetch(ctx, "requests")
    assert (requests.status, requests.meta["status_reason"]) == ("warn", "nexbeat has no target for requests")
    library = await _fetch(ctx, "library")
    assert library.status == "warn"
    assert [one["label"] for one in library.secondary] == ["Albums", "With music"]


@respx.mock
async def test_a_users_token_says_it_counts_only_its_own_requests(ctx: Context) -> None:
    _tile(scope="mine")
    data = await _fetch(ctx, "requests")
    assert "only its own requests" in data.meta["notice"]


@respx.mock
async def test_the_library_card_names_where_the_music_is(ctx: Context) -> None:
    _tile(target="nexcrate")
    data = await _fetch(ctx, "library")
    assert data.primary == {"label": "Artists", "value": 412}
    assert data.secondary == [{"label": "Albums", "value": 2961}, {"label": "With music", "value": 388},
                              {"label": "Source", "value": "nexcrate"}]


# -- the approval card ---------------------------------------------------------


@respx.mock
async def test_a_token_that_may_decide_gets_both_buttons_on_every_row(ctx: Context) -> None:
    _me(["request", "see_all", "decide"])
    listed = _waiting(ALBUM, ARTIST)
    data = await _fetch(ctx)
    assert listed.calls.last.request.url.params["status"] == "pending_approval"
    album, artist = data.items
    assert (album["title"], album["subtitle"], album["value"]) == ("Northern Lights", "The Quiet Harbour · Anna", "Album")
    assert album["art"] == ALBUM["cover_url"]
    # A whole artist's picture lives on nexbeat itself and is made whole here.
    assert (artist["title"], artist["subtitle"], artist["value"]) == ("Copper Sky", "ben", "Whole artist")
    assert artist["art"] == NEXBEAT + ARTIST["cover_url"]
    assert all(row["art_shape"] == "square" for row in data.items)
    assert [one["id"] for one in album["actions"]] == ["approve", "reject"]
    assert album["actions"][1]["confirm"] is True
    assert data.metrics == {"waiting": 2.0}
    assert data.meta.get("actions_visible") is True
    assert "notice" not in data.meta


@respx.mock
async def test_a_read_only_token_lists_without_buttons_and_says_why(ctx: Context) -> None:
    _me(["see_all"])
    _waiting(ALBUM)
    data = await _fetch(ctx)
    assert "actions" not in data.items[0]
    assert data.meta["notice"].startswith("This token may only read.")


@respx.mock
async def test_a_users_token_lists_nothing_and_asks_nothing(ctx: Context) -> None:
    _me(["request"], role="user")
    listed = _waiting(ALBUM)
    data = await _fetch(ctx)
    assert data.items == [] and data.status == "unknown"
    assert "not an administrator" in data.meta["notice"]
    assert not listed.called


@respx.mock
async def test_the_list_is_cut_to_the_card_but_the_count_is_not(ctx: Context) -> None:
    _me(["see_all", "decide"])
    _waiting(*[{**ALBUM, "id": number} for number in range(1, 13)])
    data = await _fetch(ctx, limit=5)
    assert len(data.items) == 5
    assert data.secondary == [{"label": "Waiting", "value": 12}]


@respx.mock
async def test_a_cover_that_is_no_address_is_left_out(ctx: Context) -> None:
    _me(["see_all", "decide"])
    _waiting({**ALBUM, "cover_url": "javascript:alert(1)"}, {**ALBUM, "id": 23, "cover_url": "//elsewhere.example.com/x.jpg"})
    data = await _fetch(ctx)
    assert [row["art"] for row in data.items] == ["", ""]


@respx.mock
async def test_a_refused_list_gives_nexbeats_reason(ctx: Context) -> None:
    _me(["see_all", "decide"])
    respx.get(f"{NEXBEAT}/api/v1/admin/requests").mock(return_value=httpx.Response(403, json={
        "detail": {"code": "admins_only", "message": "This action is reserved for administrators."}}))
    with pytest.raises(AdapterError) as refused:
        await _fetch(ctx)
    assert (refused.value.code, refused.value.message) == (
        "http_error", "This token belongs to an account that is not an administrator.")


# -- the buttons ---------------------------------------------------------------


@respx.mock
async def test_approving_posts_to_nexbeats_address(ctx: Context) -> None:
    route = respx.post(f"{NEXBEAT}/api/v1/admin/requests/21/approve").mock(
        return_value=httpx.Response(200, json={**ALBUM, "status": "searching"}))
    assert await get_adapter("nexbeat").action("approvals", "approve", {"id": 21}, CONFIG, {}, ctx) == "Approved."
    assert json.loads(route.calls.last.request.read()) == {}
    assert route.calls.last.request.headers["Authorization"] == "Bearer nxb_test"


@respx.mock
async def test_an_approval_nexbeat_could_not_hand_on_says_so(ctx: Context) -> None:
    respx.post(f"{NEXBEAT}/api/v1/admin/requests/21/approve").mock(
        return_value=httpx.Response(200, json={**ALBUM, "status": "failed", "error_code": "lidarr_unreachable"}))
    said = await get_adapter("nexbeat").action("approvals", "approve", {"id": 21}, CONFIG, {}, ctx)
    assert said.startswith("Approved, but nexbeat could not hand it on.")


@respx.mock
async def test_turning_down_goes_to_its_own_address_with_a_body(ctx: Context) -> None:
    route = respx.post(f"{NEXBEAT}/api/v1/admin/requests/21/reject").mock(return_value=httpx.Response(200, json={}))
    assert await get_adapter("nexbeat").action("approvals", "reject", {"id": 21}, CONFIG, {}, ctx) == "Turned down."
    # nexbeat's handler takes a body with an optional reason; without one it answers 422.
    assert json.loads(route.calls.last.request.read()) == {}


@respx.mock
@pytest.mark.parametrize(("code", "said"), [
    ("api_key_read_only", "This token may only read."),
    ("request_not_pending", "This request is no longer waiting for approval."),
])
async def test_a_refusal_says_what_nexbeat_meant(ctx: Context, code: str, said: str) -> None:
    respx.post(f"{NEXBEAT}/api/v1/admin/requests/21/approve").mock(return_value=httpx.Response(
        403 if code == "api_key_read_only" else 409, json={"detail": {"code": code, "message": "whatever"}}))
    with pytest.raises(AdapterError) as refused:
        await get_adapter("nexbeat").action("approvals", "approve", {"id": 21}, CONFIG, {}, ctx)
    assert (refused.value.code, refused.value.message) == ("rejected", said)


@respx.mock
async def test_an_unknown_refusal_passes_nexbeats_words_through(ctx: Context) -> None:
    respx.post(f"{NEXBEAT}/api/v1/admin/requests/21/approve").mock(return_value=httpx.Response(409, json={
        "detail": {"code": "something_new", "message": "A reason nexdeck has no words for."}}))
    with pytest.raises(AdapterError) as refused:
        await get_adapter("nexbeat").action("approvals", "approve", {"id": 21}, CONFIG, {}, ctx)
    assert refused.value.message == "A reason nexdeck has no words for."


@respx.mock
@pytest.mark.parametrize("request_id", ["../settings", "21", 0, -3, True, None])
async def test_a_request_id_that_is_not_a_positive_number_goes_nowhere(ctx: Context, request_id) -> None:
    anything = respx.route(host="nexbeat.example.com").mock(return_value=httpx.Response(200, json={}))
    with pytest.raises(AdapterError) as refused:
        await get_adapter("nexbeat").action("approvals", "approve", {"id": request_id}, CONFIG, {}, ctx)
    assert refused.value.code == "bad_param"
    assert not anything.called


@respx.mock
async def test_the_guard_takes_only_a_request_the_card_offered(ctx: Context) -> None:
    """The card's real output fed to the real guard, so the two cannot drift apart."""
    _me(["see_all", "decide"])
    _waiting(ALBUM)
    data = await _fetch(ctx)
    live.set(7_778, WidgetData(items=data.items))
    try:
        assert collector._refuse_unless_offered(7_778, "approve", {"id": 21}) == {"id": 21}
        with pytest.raises(AdapterError):
            collector._refuse_unless_offered(7_778, "approve", {"id": 99})
    finally:
        live.forget(7_778)


# -- the connection test -------------------------------------------------------


@respx.mock
async def test_the_connection_test_says_what_the_token_may_do(ctx: Context) -> None:
    _tile()
    route = _me(["request", "see_all", "decide"])
    nexbeat = get_adapter("nexbeat")
    assert "may approve" in await nexbeat.test(CONFIG, ctx)
    route.mock(return_value=httpx.Response(200, json={"may": ["see_all"]}))
    assert "without buttons" in await nexbeat.test(CONFIG, Context(httpx.AsyncClient(), integration_id=2, cache={}))
    route.mock(return_value=httpx.Response(200, json={"may": ["request"]}))
    assert "own requests" in await nexbeat.test(CONFIG, Context(httpx.AsyncClient(), integration_id=3, cache={}))


@respx.mock
async def test_a_wrong_token_is_a_credentials_problem(ctx: Context) -> None:
    respx.get(f"{NEXBEAT}/api/v1/dashboard").mock(return_value=httpx.Response(401, json={
        "detail": {"code": "not_signed_in", "message": "Not signed in."}}))
    with pytest.raises(AdapterError) as refused:
        await get_adapter("nexbeat").test(CONFIG, ctx)
    assert refused.value.code == "auth_failed"


def test_every_demo_card_draws() -> None:
    nexbeat = get_adapter("nexbeat")
    for widget in nexbeat.widgets:
        data = nexbeat.demo(widget.kind, {"limit": 8}, 0)
        assert data.status in ("ok", "warn")
    rows = nexbeat.demo("approvals", {"limit": 8}, 0).items
    assert [row["value"] for row in rows] == ["Album", "Whole artist", "EP"]
