"""nexcanvas 0.4.1, from its ``docs/api.md`` and ``routers/v1.py``: the shapes are the documented ones, the names and
counts made up. The adapter was also run against a fresh
instance on 11.10.2026; these tests keep what that showed."""

from __future__ import annotations

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.adapters import get_adapter
from app.adapters import nexcanvas as module
from app.adapters.base import AdapterError, AuthFailed, Context, outbound_client

from .conftest import CSRF, setup_admin
from .test_boards import _board, _widget

CONFIG = {"url": "http://nexcanvas:8500", "api_key": "nxa_example"}
BASE = "http://nexcanvas:8500/api/v1"
ID = "Ab3_dEf-9xQ"
OTHER = "Zz9_yXw-1pL"


def board(board_id: str, title: str, updated_at: str, *, space: str = "Home", by: str = "alex") -> dict:
    return {"id": board_id, "title": title, "space_id": 1, "space": space, "created_at": "2026-09-01T08:00:00",
            "updated_at": updated_at, "updated_by": by, "items": 14, "url": f"https://canvas.example.com/b/{board_id}",
            "picture": f"/api/v1/boards/{board_id}/picture.svg"}


DASHBOARD = {
    "spaces": 2, "boards": 14, "changed_today": 3, "changed_week": 6,
    "recent": [board(ID, "Garden shed plan", "2026-10-11T08:30:00"), board(OTHER, "Network map", "2026-10-10T19:00:00", space="Homelab", by="sam")],
}
PICTURE = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 160 100"><rect width="160" height="100" fill="#111117"/></svg>'


@pytest.fixture
def ctx() -> Context:
    return Context(outbound_client(guard=False), integration_id=1, widget_id=1, cache={})


@respx.mock
async def test_the_boards_card_counts_and_lists_the_boards_changed_last_with_their_pictures(ctx: Context) -> None:
    route = respx.get(f"{BASE}/dashboard").mock(return_value=httpx.Response(200, json=DASHBOARD))
    data = await get_adapter("nexcanvas").fetch("boards", CONFIG, {}, ctx)
    assert data.primary == {"label": "Boards", "value": 14} and data.meta["headline"] is True
    assert {row["label"]: row["value"] for row in data.secondary} == {"Changed today": 3, "This week": 6, "Spaces": 2}
    first, second = data.items
    assert (first["title"], first["subtitle"], first["url"]) == ("Garden shed plan", "Home · alex", f"https://canvas.example.com/b/{ID}")
    assert second["subtitle"] == "Homelab · sam"
    assert first["when"] == 1_791_707_400.0  # 2026-10-11 08:30 UTC
    # The version in the address is the second the board changed: a changed board is a new address, never a stale picture.
    assert first["art"] == f"proxy:/board/{ID}/dark/320/1791707400" and first["art_shape"] == "wide"
    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer nxa_example" and "nxa_" not in str(request.url)
    assert "origin" not in request.headers

    light = await get_adapter("nexcanvas").fetch("boards", CONFIG, {"look": "light"}, ctx)
    assert light.items[0]["art"].startswith(f"proxy:/board/{ID}/light/320/")


@respx.mock
async def test_one_board_is_a_picture_that_is_never_kept(ctx: Context) -> None:
    respx.get(f"{BASE}/boards/{ID}").mock(return_value=httpx.Response(200, json=board(ID, "Garden shed plan", "2026-10-11T08:30:00")))
    data = await get_adapter("nexcanvas").fetch("board", CONFIG, {"board": ID, "look": "light", "interval": 2}, ctx)
    item = data.items[0]
    assert (item["title"], item["subtitle"]) == ("Garden shed plan", "Home")
    assert item["art"] == f"proxy:/board/{ID}/light/1200/live"
    assert data.link == f"https://canvas.example.com/b/{ID}"
    assert data.meta["interval"] == 5, "a picture is asked for no more often than every five seconds"


@respx.mock
async def test_a_board_that_is_not_an_id_never_reaches_nexcanvas(ctx: Context) -> None:
    anything = respx.route().mock(return_value=httpx.Response(200, json={}))
    for wanted, why in (("", "Pick a board"), ("../me", "not the id"), ("a" * 41, "not the id"), ("abc", "not the id"), ("ok/../../me", "not the id")):
        with pytest.raises(AdapterError) as refused:
            await get_adapter("nexcanvas").fetch("board", CONFIG, {"board": wanted}, ctx)
        assert why in str(refused.value) and refused.value.code == "bad_param"
    assert not anything.called


@respx.mock
async def test_a_board_the_token_may_not_read_is_said_plainly(ctx: Context) -> None:
    respx.get(f"{BASE}/boards/{ID}").mock(return_value=httpx.Response(404, json={"detail": {"code": "not_found", "message": "Not found."}}))
    with pytest.raises(AdapterError) as gone:
        await get_adapter("nexcanvas").fetch("board", CONFIG, {"board": ID}, ctx)
    assert gone.value.code == "no_board" and "no such board" in str(gone.value)


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
        await get_adapter("nexcanvas").fetch("boards", CONFIG, {}, ctx)
    assert refused.value.code == ours and words in str(refused.value)
    # A token that is withdrawn is a wrong credential, a switch that is off is not: the card tells them apart.
    assert isinstance(refused.value, AuthFailed) is (code == "token_invalid")
    if code == "api_off":
        assert "Settings > Server > API" in refused.value.hint


@respx.mock
async def test_an_answer_that_is_not_json_names_the_address(ctx: Context) -> None:
    respx.get(f"{BASE}/dashboard").mock(return_value=httpx.Response(200, text="<html>login</html>"))
    with pytest.raises(AdapterError) as refused:
        await get_adapter("nexcanvas").fetch("boards", CONFIG, {}, ctx)
    assert refused.value.code == "bad_answer" and "address of nexcanvas" in str(refused.value)


@respx.mock
async def test_missing_fields_do_not_bring_the_card_down(ctx: Context) -> None:
    respx.get(f"{BASE}/dashboard").mock(return_value=httpx.Response(200, json={"boards": "many", "recent": [{"title": "No id"}, "junk", None, {"id": "../x", "title": "Bad id"}]}))
    data = await get_adapter("nexcanvas").fetch("boards", CONFIG, {}, ctx)
    assert data.primary == {"label": "Boards", "value": 0}
    assert [item["title"] for item in data.items] == ["No id", "Bad id"]
    assert all(item["art"] == "" for item in data.items), "a board without a usable id has no picture to ask for"
    respx.get(f"{BASE}/dashboard").mock(return_value=httpx.Response(200, json=["not", "an", "object"]))
    fresh = Context(outbound_client(guard=False), integration_id=1, widget_id=1, cache={})
    with pytest.raises(AdapterError) as refused:
        await get_adapter("nexcanvas").fetch("boards", CONFIG, {}, fresh)
    assert refused.value.code == "wrong_app", "an answer that is no dashboard of nexcanvas says so instead of drawing noughts"


@respx.mock
async def test_the_connection_test_names_version_and_reach(ctx: Context) -> None:
    respx.get(f"{BASE}/me").mock(return_value=httpx.Response(200, json={"name": "alex", "display_name": "Alex", "level": "read", "spaces": ["Home", "Homelab"], "version": "0.4.1"}))
    assert await get_adapter("nexcanvas").test(CONFIG, ctx) == "nexcanvas 0.4.1 answers; the token of alex reads 2 space(s)."


@respx.mock
async def test_the_board_list_is_by_title_with_the_space_and_skips_what_is_no_board(ctx: Context) -> None:
    route = respx.get(f"{BASE}/boards").mock(return_value=httpx.Response(200, json=[
        board(ID, "Garden shed plan", "2026-10-11T08:30:00"), {"id": "../x", "title": "Bad"}, "junk", board(OTHER, "Network map", "2026-10-10T19:00:00", space="")]))
    choices = await get_adapter("nexcanvas").choices("board", CONFIG, ctx)
    assert choices == [(ID, "Garden shed plan · Home"), (OTHER, "Network map")]
    assert dict(route.calls.last.request.url.params) == {"order": "title", "limit": "200"}


async def test_the_picture_is_fetched_with_the_token_and_only_this_path(ctx: Context) -> None:
    adapter = get_adapter("nexcanvas")
    source = await adapter.image_source(CONFIG, f"/board/{ID}/light/1200/live", ctx)
    assert source.url == f"{BASE}/boards/{ID}/picture.svg" and source.params == {"look": "light", "width": 1200}
    assert source.headers["Authorization"] == "Bearer nxa_example" and "nxa_" not in source.url
    assert source.svg is True and source.cache_seconds == 0, "the live picture is never kept"
    kept = await adapter.image_source(CONFIG, f"/board/{ID}/dark/320/1791707400", ctx)
    assert kept.cache_seconds == 3600, "a versioned picture is kept: a changed board has a new address"
    for path in ("/api/v1/me", f"/board/{ID}/dark/320", f"/board/{ID}/sepia/320/live", f"/board/{ID}/dark/50/live",
                 f"/board/{ID}/dark/9999/live", "/board/../me/dark/320/live", f"/board/{ID}/dark/320/live?x=1", f"/board/{ID}/dark/320/12345678901234"):
        with pytest.raises(AdapterError) as refused:
            await adapter.image_source(CONFIG, path, ctx)
        assert refused.value.code == "bad_path", path


def test_every_demo_draws() -> None:
    adapter = get_adapter("nexcanvas")
    for widget in adapter.widgets:
        for tick in (0, 40, 800):
            data = adapter.demo(widget.kind, {field.name: field.default for field in widget.options}, tick)
            assert data.items and data.status == "ok", widget.kind
            assert all(item["art"] == "" for item in data.items), "a demo points nowhere, so it has no picture to fetch"
    assert module.board_choices([]) == [] and adapter.demo_choices("board") and adapter.demo_choices("other") == []


# -- the route that hands the picture on ---------------------------------------


def _widget_of_nexcanvas(client: TestClient) -> dict:
    setup_admin(client)
    page = _board(client)["pages"][0]["id"]
    made = client.post("/api/v1/integrations", json={"kind": "nexcanvas", "name": "Canvas", "config": CONFIG}, headers=CSRF)
    assert made.status_code == 201, made.text
    return _widget(client, page, kind="nexcanvas.board", integration_id=made.json()["id"], options={"board": ID})


def test_a_board_picture_comes_through_the_server_in_a_sandbox(client: TestClient) -> None:
    widget = _widget_of_nexcanvas(client)
    with respx.mock:
        picture = respx.get(f"{BASE}/boards/{ID}/picture.svg").mock(return_value=httpx.Response(200, content=PICTURE, headers={"content-type": "image/svg+xml"}))
        answer = client.get(f"/api/v1/widgets/{widget['id']}/image", params={"path": f"/board/{ID}/dark/1200/live"})
        assert answer.status_code == 200 and answer.headers["content-type"] == "image/svg+xml" and answer.content == PICTURE
        assert "sandbox" in answer.headers["content-security-policy"], "an SVG is a document: it is served in a sandbox of its own"
        assert answer.headers["x-content-type-options"] == "nosniff" and answer.headers["cache-control"] == "no-store"
        sent = picture.calls.last.request
        assert sent.headers["Authorization"] == "Bearer nxa_example", "the token stays between server and nexcanvas"
        assert dict(sent.url.params) == {"look": "dark", "width": "1200"}
        # A versioned picture is kept for the next request, and the browser may keep it too.
        kept = client.get(f"/api/v1/widgets/{widget['id']}/image", params={"path": f"/board/{ID}/dark/320/1791707400"})
        again = client.get(f"/api/v1/widgets/{widget['id']}/image", params={"path": f"/board/{ID}/dark/320/1791707400"})
        assert kept.status_code == again.status_code == 200 and picture.call_count == 2
        assert again.headers["cache-control"].startswith("private") and "sandbox" in again.headers["content-security-policy"]
        assert client.get(f"/api/v1/widgets/{widget['id']}/image", params={"path": "/api/v1/me"}).status_code == 400, "only pictures of boards"


def test_a_picture_that_could_run_is_refused(client: TestClient) -> None:
    widget = _widget_of_nexcanvas(client)
    with respx.mock:
        for hostile in (b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
                        b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"></svg>',
                        b'<svg xmlns="http://www.w3.org/2000/svg"><foreignObject><body/></foreignObject></svg>'):
            respx.get(f"{BASE}/boards/{ID}/picture.svg").mock(return_value=httpx.Response(200, content=hostile, headers={"content-type": "image/svg+xml"}))
            refused = client.get(f"/api/v1/widgets/{widget['id']}/image", params={"path": f"/board/{ID}/dark/1200/live"})
            assert refused.status_code == 404 and refused.json()["detail"]["code"] == "no_image"
        respx.get(f"{BASE}/boards/{ID}/picture.svg").mock(return_value=httpx.Response(401, content=PICTURE, headers={"content-type": "image/svg+xml"}))
        assert client.get(f"/api/v1/widgets/{widget['id']}/image", params={"path": f"/board/{ID}/dark/1200/live"}).status_code == 404


def test_a_service_that_did_not_ask_for_svg_still_gets_none(client: TestClient) -> None:
    setup_admin(client)
    page = _board(client)["pages"][0]["id"]
    made = client.post("/api/v1/integrations", json={"kind": "plex", "name": "P", "config": {"url": "http://plex:32400", "token": "tok"}}, headers=CSRF).json()
    widget = _widget(client, page, kind="plex.recent", integration_id=made["id"])
    with respx.mock:
        respx.get("http://plex:32400/library/metadata/10/thumb/1").mock(return_value=httpx.Response(200, content=PICTURE, headers={"content-type": "image/svg+xml"}))
        refused = client.get(f"/api/v1/widgets/{widget['id']}/image", params={"path": "/library/metadata/10/thumb/1"})
        assert refused.status_code == 404 and "SVG" in refused.json()["detail"]["message"]


def test_a_board_title_that_reads_like_code_does_not_cost_the_picture(client: TestClient) -> None:
    """"JavaScript: Basics" or "Online = yes" as a board's name read as an address or a handler (found
    against nexcanvas on 11.10.2026); the words of the title are no markup, the rest is checked as before."""
    widget = _widget_of_nexcanvas(client)
    with respx.mock:
        for title in (b"JavaScript: Basics", b"Online = yes", b"Plan: one = first", b"Tom &amp; Jerry"):
            fine = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 160 100"><title>' + title + b'</title><rect width="160" height="100"/></svg>'
            respx.get(f"{BASE}/boards/{ID}/picture.svg").mock(return_value=httpx.Response(200, content=fine, headers={"content-type": "image/svg+xml"}))
            answer = client.get(f"/api/v1/widgets/{widget['id']}/image", params={"path": f"/board/{ID}/dark/1200/live"})
            assert answer.status_code == 200 and answer.content == fine, title
        for hostile in (b'<svg xmlns="http://www.w3.org/2000/svg"><title>Plan</title><rect onload="alert(1)"/></svg>',
                        b'<svg xmlns="http://www.w3.org/2000/svg"><title>a<script>alert(1)</script></title></svg>',
                        b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"><title>Plan</title></svg>'):
            respx.get(f"{BASE}/boards/{ID}/picture.svg").mock(return_value=httpx.Response(200, content=hostile, headers={"content-type": "image/svg+xml"}))
            refused = client.get(f"/api/v1/widgets/{widget['id']}/image", params={"path": f"/board/{ID}/dark/1200/live"})
            assert refused.status_code == 404, hostile
