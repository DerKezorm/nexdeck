"""Piwigo, against answers in the form of Piwigo master's code (ws.php, include/ws_functions, 09.11.2026)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter, rawread
from app.adapters.base import AdapterError, AuthFailed, Context

PW = "http://piwigo.example.com"
CONFIG = {"url": PW, "key_id": "pkid-20260109-a1b2c3d4e5f6a7b8c9d0", "key_secret": "made-up-secret"}

ALBUMS = [
    {"id": 1, "name": "Holidays", "id_uppercat": None, "nb_images": 4, "total_nb_images": 30, "max_date_last": "2026-08-30 18:02:11"},
    {"id": 2, "name": "Holidays / Norway &amp; <b>Sweden</b>", "id_uppercat": "1", "nb_images": "26", "total_nb_images": "26",
     "max_date_last": "2026-08-30 18:02:11"},
    {"id": 3, "name": "Family", "id_uppercat": None, "nb_images": 12, "total_nb_images": 12, "max_date_last": "2026-11-08 10:14:00"},
    {"id": 4, "name": "Archive", "id_uppercat": None, "nb_images": 0, "total_nb_images": 0, "max_date_last": None},
]
INFOS = [{"name": "version", "value": "16.1.0"}, {"name": "nb_elements", "value": "41"}, {"name": "nb_categories", "value": "5"},
         {"name": "nb_users", "value": "3"}, {"name": "nb_tags", "value": "7"}, {"name": "nb_comments", "value": "2"}]
USERS = [
    {"id": 2, "username": "guest", "status": "guest", "last_visit": None},
    {"id": 1, "username": "alex", "status": "webmaster", "last_visit": "2026-11-07 19:45:31"},
    {"id": 3, "username": "sam", "status": "normal", "last_visit": "2026-11-09 08:12:00"},
    {"id": 4, "username": "kim", "status": "generic", "last_visit": None},
]
DENIED = httpx.Response(401, json={"stat": "fail", "err": 401, "message": "Access denied"})


def ok(result: Any) -> httpx.Response:
    return httpx.Response(200, json={"stat": "ok", "result": result})


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


def piwigo(answers: dict[str, httpx.Response]) -> respx.Route:
    """One stand-in for ws.php that answers by the method in the address."""
    return respx.get(f"{PW}/ws.php").mock(side_effect=lambda request: answers[request.url.params["method"]])


@respx.mock
async def test_the_gallery_of_an_administrator_counts_the_whole_gallery(ctx: Context) -> None:
    route = piwigo({"pwg.categories.getList": ok({"categories": ALBUMS}), "pwg.getInfos": ok({"infos": INFOS})})
    data = await get_adapter("piwigo").fetch("library", CONFIG, {}, ctx)
    asked = {call.request.url.params["method"]: call.request for call in route.calls}
    assert asked["pwg.getInfos"].headers["X-PIWIGO-API"] == "pkid-20260109-a1b2c3d4e5f6a7b8c9d0:made-up-secret"
    assert asked["pwg.getInfos"].url.params["format"] == "json"
    assert dict(asked["pwg.categories.getList"].url.params) == {
        "format": "json", "method": "pwg.categories.getList", "recursive": "true", "fullname": "true"}
    assert data.primary == {"label": "Photos", "value": 41}
    assert data.secondary == [{"label": "Albums", "value": 5}, {"label": "Users", "value": 3}, {"label": "Tags", "value": 7},
                              {"label": "Comments", "value": 2}]
    assert data.metrics == {"photos": 41.0, "albums": 5.0}


@respx.mock
async def test_without_an_administrator_the_gallery_counts_the_albums_it_may_see(ctx: Context) -> None:
    piwigo({"pwg.categories.getList": ok({"categories": ALBUMS}), "pwg.getInfos": DENIED})
    data = await get_adapter("piwigo").fetch("library", CONFIG, {}, ctx)
    assert data.primary == {"label": "Photos", "value": 42}
    assert data.secondary == [{"label": "Albums", "value": 4}]
    assert data.metrics == {"photos": 42.0, "albums": 4.0}


@respx.mock
async def test_without_a_key_nothing_signs_the_request(ctx: Context) -> None:
    route = piwigo({"pwg.categories.getList": ok({"categories": ALBUMS[:1]}), "pwg.getInfos": DENIED})
    await get_adapter("piwigo").fetch("library", {"url": PW, "key_id": "pkid-x"}, {}, ctx)
    assert all("X-PIWIGO-API" not in call.request.headers for call in route.calls)


@respx.mock
async def test_albums_at_the_top_by_how_many_photos_with_their_sub_albums(ctx: Context) -> None:
    piwigo({"pwg.categories.getList": ok({"categories": ALBUMS})})
    data = await get_adapter("piwigo").fetch("albums", CONFIG, {"limit": 2}, ctx)
    assert [(row["title"], row["subtitle"], row["value"]) for row in data.items] == [
        ("Holidays", "2026-08-30", 30), ("Family", "2026-11-08", 12)]
    assert data.secondary == [{"label": "Albums", "value": 3}]


def test_all_albums_by_name_carry_their_path_without_markup() -> None:
    data = get_adapter("piwigo")._album_list(ALBUMS, {"shown": "all", "order": "name"})
    assert [row["title"] for row in data.items] == ["Archive", "Family", "Holidays", "Holidays / Norway & Sweden"]
    assert data.items[0]["subtitle"] == "" and data.items[0]["value"] == 0


def test_albums_by_their_newest_photo() -> None:
    data = get_adapter("piwigo")._album_list(ALBUMS, {"order": "recent"})
    assert [row["title"] for row in data.items] == ["Family", "Holidays", "Archive"]


def test_no_albums_is_an_empty_card() -> None:
    data = get_adapter("piwigo")._album_list([], {})
    assert data.items == [] and data.meta["empty"] == "No albums."


@respx.mock
async def test_users_by_their_last_visit_without_the_visitor(ctx: Context) -> None:
    route = piwigo({"pwg.users.getList": ok({"paging": {"page": 0, "per_page": 100, "count": 4, "total_count": 4}, "users": USERS})})
    data = await get_adapter("piwigo").fetch("users", CONFIG, {"limit": 8}, ctx)
    params = route.calls.last.request.url.params
    assert params["display"] == "username,status,last_visit,total_count" and params["per_page"] == "100"
    assert [(row["title"], row["subtitle"], row["value"]) for row in data.items] == [
        ("sam", "User", "2026-11-09"), ("alex", "Webmaster", "2026-11-07"), ("kim", "Generic", "–")]
    assert data.secondary == [{"label": "Users", "value": 3}]
    assert data.metrics == {"users": 3.0}


def test_users_beyond_the_first_page_are_counted() -> None:
    data = get_adapter("piwigo")._users({"paging": {"total_count": 250}, "users": USERS}, 2)
    assert len(data.items) == 2 and data.secondary == [{"label": "Users", "value": 249}]


@respx.mock
async def test_users_need_an_administrator(ctx: Context) -> None:
    piwigo({"pwg.users.getList": DENIED})
    with pytest.raises(AuthFailed) as refused:
        await get_adapter("piwigo").fetch("users", CONFIG, {}, ctx)
    assert refused.value.message == "Piwigo refused: Access denied."
    assert "administrator" in refused.value.hint


@respx.mock
async def test_an_address_that_is_not_piwigo_says_so(ctx: Context) -> None:
    respx.get(f"{PW}/ws.php").mock(return_value=httpx.Response(200, text="<html>login</html>"))
    with pytest.raises(AdapterError) as wrong:
        await get_adapter("piwigo").fetch("albums", CONFIG, {}, ctx)
    assert wrong.value.code == "not_json"


@respx.mock
async def test_a_missing_ws_php_is_an_http_error(ctx: Context) -> None:
    respx.get(f"{PW}/ws.php").mock(return_value=httpx.Response(404, text="not found"))
    with pytest.raises(AdapterError) as wrong:
        await get_adapter("piwigo").fetch("albums", CONFIG, {}, ctx)
    assert wrong.value.code == "http_error"


@respx.mock
async def test_an_error_of_piwigo_is_named(ctx: Context) -> None:
    piwigo({"pwg.categories.getList": httpx.Response(501, json={"stat": "fail", "err": 501, "message": "Method name is not valid"})})
    with pytest.raises(AdapterError) as wrong:
        await get_adapter("piwigo").fetch("albums", CONFIG, {}, ctx)
    assert wrong.value.code == "piwigo_error" and "Method name is not valid" in wrong.value.message


@respx.mock
async def test_the_connection_test_names_version_and_user(ctx: Context) -> None:
    piwigo({"pwg.session.getStatus": ok({"username": "alex", "status": "webmaster", "version": "16.1.0", "pwg_token": "x"})})
    assert await get_adapter("piwigo").test(CONFIG, ctx) == "Piwigo 16.1.0 answers, as alex (Webmaster)."


@respx.mock
async def test_the_connection_test_says_when_piwigo_sees_a_visitor(ctx: Context) -> None:
    piwigo({"pwg.session.getStatus": ok({"username": "guest", "status": "guest", "version": "15.7.0"})})
    assert await get_adapter("piwigo").test({"url": PW}, ctx) == "Piwigo 15.7.0 answers to a visitor: only public albums are counted."


@pytest.mark.parametrize("path", [
    "/ws.php?format=json&method=pwg.session.getStatus",
    "/ws.php?format=json&method=pwg.users.getAuthKey&user_id=1",
    "/ws.php?format=json&method=pwg.images.delete&image_id=1",
    "/ws.php?format=xml&method=pwg.getInfos",
])
def test_a_custom_card_asks_nothing_but_the_reads(path: str) -> None:
    with pytest.raises(AdapterError):
        rawread.refuse_a_command(get_adapter("piwigo"), path)


def test_a_custom_card_may_read_the_albums() -> None:
    rawread.refuse_a_command(get_adapter("piwigo"), "/ws.php?format=json&method=pwg.categories.getList&recursive=true")


@pytest.mark.parametrize("kind", ["library", "albums", "users"])
def test_every_card_has_a_demo(kind: str) -> None:
    data = get_adapter("piwigo").demo(kind, {}, 3)
    assert data.primary or data.items
