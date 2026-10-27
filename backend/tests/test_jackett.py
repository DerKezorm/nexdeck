"""Jackett, against the answers of Jackett v0.24.2934 (lscr.io/linuxserver/jackett, 27.10.2026).

The sign-in is the measured one: ``POST /UI/Dashboard`` answers 302 to
``Dashboard`` either way and sets the ``Jackett`` cookie only when the
password (empty, if none is set) was right; ``/api/v2.0/...`` answers 302 to
``/UI/Login`` without it. The indexers are made up, the failure message is
the shape of the real one with the certificate details taken out.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context, Unreachable, outbound_client

BASE = "http://jackett.example.com:9117"
CONFIG = {"url": BASE}
ADAPTER = get_adapter("jackett")
COOKIE = "CfDJ8-made-up-ticket"
ADMIN = "made-up-word-for-the-form"
CERTIFICATE = (
    "Exception (old-mirror): certificate validation failed: [Subject]\n  CN=old-mirror.example.com\n\n[Issuer]\n  CN=Made Up CA\n\n"
    "[Thumbprint]\n  0000\n: The SSL connection could not be established, see inner exception."
)


def indexer(name: str, kind: str = "public", error: str = "") -> dict:
    identifier = name.lower().replace(" ", "-")
    return {"id": identifier, "name": name, "description": "A made up index", "type": kind, "configured": True,
            "site_link": f"https://{identifier}.example.com/", "alternativesitelinks": [], "language": "en-US", "tags": [],
            "last_error": error, "potatoenabled": True, "caps": [{"ID": "2000", "Name": "Movies"}, {"ID": "5000", "Name": "TV"}]}


INDEXERS = [indexer("Tracker One"), indexer("Old Mirror", error=CERTIFICATE), indexer("Members Only", "private"), indexer("Film Index", "semi-private")]
SERVER = {"notices": [], "port": 9117, "api_key": "not-read-by-the-adapter", "password": "", "app_version": "v0.24.2934"}


@pytest.fixture
def ctx() -> Context:
    return Context(outbound_client(guard=False), integration_id=1, widget_id=1, cache={})


def jackett(admin: str = "", indexers: list | None = None, seen: list[str] | None = None) -> None:
    """Jackett's two doors: the sign-in form and the API behind the cookie."""
    def sign_in(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(f"POST /UI/Dashboard {request.content.decode()}")
        headers = {"Location": "Dashboard"}
        if request.content.decode() == f"password={admin}":
            headers["Set-Cookie"] = f"Jackett={COOKIE}; path=/; httponly"
        return httpx.Response(302, headers=headers)

    def behind_the_cookie(answer):  # noqa: ANN001, ANN202
        def reply(request: httpx.Request) -> httpx.Response:
            if seen is not None:
                seen.append(f"{request.method} {request.url.path}")
            if f"Jackett={COOKIE}" not in request.headers.get("cookie", ""):
                return httpx.Response(302, headers={"Location": f"{BASE}/UI/Login?ReturnUrl=%2Fapi"})
            return answer(request)
        return reply

    respx.post(f"{BASE}/UI/Dashboard").mock(side_effect=sign_in)
    respx.get(f"{BASE}/api/v2.0/indexers").mock(side_effect=behind_the_cookie(lambda _r: httpx.Response(200, json=INDEXERS if indexers is None else indexers)))
    respx.get(f"{BASE}/api/v2.0/server/config").mock(side_effect=behind_the_cookie(lambda _r: httpx.Response(200, json=SERVER)))


@respx.mock
async def test_the_overview_counts_the_failing_ones_and_turns_yellow(ctx: Context) -> None:
    jackett()
    data = await ADAPTER.fetch("overview", CONFIG, {}, ctx)
    assert data.status == "warn"
    assert data.primary == {"label": "Indexers", "value": 4}
    assert data.secondary == [{"label": "Failing", "value": 1}, {"label": "Public", "value": 2}, {"label": "Private", "value": 2}]
    assert data.metrics == {"indexers": 4.0, "failing": 1.0}
    assert data.link == BASE


@respx.mock
async def test_the_indexer_list_puts_failures_first_with_the_first_line_of_the_reason_and_a_test_button(ctx: Context) -> None:
    jackett()
    data = await ADAPTER.fetch("indexers", CONFIG, {}, ctx)
    assert [item["title"] for item in data.items] == ["Old Mirror", "Film Index", "Members Only", "Tracker One"]
    assert data.items[0] == {
        "title": "Old Mirror", "subtitle": "Exception (old-mirror): certificate validation failed: [Subject]", "value": "Failing",
        "status": "bad", "actions": [{"id": "test", "label": "Test", "icon": "refresh-cw", "params": {"id": "old-mirror"}}]}
    assert [item["subtitle"] for item in data.items[1:]] == ["Semi-private", "Private", "Public"]
    assert data.metrics == {"failing": 1.0}
    only = await ADAPTER.fetch("indexers", CONFIG, {"only_failing": True}, ctx)
    assert [item["title"] for item in only.items] == ["Old Mirror"]


@respx.mock
async def test_all_quiet_says_so_and_so_does_an_empty_jackett(ctx: Context) -> None:
    jackett(indexers=[indexer("Tracker One")])
    data = await ADAPTER.fetch("indexers", CONFIG, {"only_failing": True}, ctx)
    assert (data.status, data.items, data.meta["empty"]) == ("ok", [], "No indexer fails.")
    jackett(indexers=[])
    empty = await ADAPTER.fetch("indexers", CONFIG, {}, ctx)
    assert empty.meta["empty"] == "No indexer is set up."


@respx.mock
async def test_the_session_is_made_once_and_kept(ctx: Context) -> None:
    seen: list[str] = []
    jackett(seen=seen)
    await ADAPTER.fetch("overview", CONFIG, {}, ctx)
    await ADAPTER.fetch("indexers", CONFIG, {}, ctx)
    assert seen == ["GET /api/v2.0/indexers", "POST /UI/Dashboard password=", "GET /api/v2.0/indexers", "GET /api/v2.0/indexers"]


@respx.mock
async def test_the_admin_password_goes_into_the_form_and_a_wrong_one_is_refused_by_the_missing_cookie(ctx: Context) -> None:
    seen: list[str] = []
    jackett(admin=ADMIN, seen=seen)
    await ADAPTER.fetch("overview", {**CONFIG, "password": ADMIN}, {}, ctx)
    assert f"POST /UI/Dashboard password={ADMIN}" in seen

    other = Context(outbound_client(guard=False), integration_id=2, widget_id=1, cache={})
    with pytest.raises(AuthFailed) as failure:
        await ADAPTER.fetch("overview", {**CONFIG, "password": "wrong"}, {}, other)
    assert "rejected the admin password" in str(failure.value)
    third = Context(outbound_client(guard=False), integration_id=3, widget_id=1, cache={})
    with pytest.raises(AuthFailed) as failure:
        await ADAPTER.fetch("overview", CONFIG, {}, third)
    assert "wants its admin password" in str(failure.value)


@respx.mock
async def test_a_cookie_that_ran_out_is_made_again(ctx: Context) -> None:
    seen: list[str] = []
    jackett(seen=seen)
    await ADAPTER.fetch("overview", CONFIG, {}, ctx)
    ctx.cache["jackett_client"].cookies.clear()
    await ADAPTER.fetch("overview", CONFIG, {}, ctx)
    assert seen.count("POST /UI/Dashboard password=") == 2


@respx.mock
async def test_the_test_names_the_version_and_reads_nothing_else_of_the_server_config(ctx: Context) -> None:
    jackett()
    assert await ADAPTER.test(CONFIG, ctx) == "Jackett 0.24.2934 answers, 4 indexers set up."
    assert await ADAPTER.running_version(CONFIG, ctx) == "0.24.2934"


@respx.mock
async def test_testing_an_indexer_says_works_or_gives_the_reason(ctx: Context) -> None:
    jackett()
    respx.post(f"{BASE}/api/v2.0/indexers/tracker-one/test").mock(return_value=httpx.Response(204))
    respx.post(f"{BASE}/api/v2.0/indexers/old-mirror/test").mock(return_value=httpx.Response(
        500, json={"result": "error", "error": CERTIFICATE, "stacktrace": "   at Jackett.Common"}))
    assert await ADAPTER.action("indexers", "test", {"id": "tracker-one"}, CONFIG, {}, ctx) == "tracker-one answers."
    with pytest.raises(AdapterError) as failure:
        await ADAPTER.action("indexers", "test", {"id": "old-mirror"}, CONFIG, {}, ctx)
    assert failure.value.code == "indexer_failed"
    assert str(failure.value) == "Exception (old-mirror): certificate validation failed: [Subject]"


async def test_an_indexer_name_cannot_climb_out_of_its_path(ctx: Context) -> None:
    with pytest.raises(AdapterError) as failure:
        await ADAPTER.action("indexers", "test", {"id": "../server/config"}, CONFIG, {}, ctx)
    assert failure.value.code == "bad_param"
    with pytest.raises(AdapterError):
        await ADAPTER.action("indexers", "delete", {"id": "tracker-one"}, CONFIG, {}, ctx)


@respx.mock
async def test_something_else_at_the_address_is_not_taken_for_jackett(ctx: Context) -> None:
    jackett()
    respx.get(f"{BASE}/api/v2.0/indexers").mock(return_value=httpx.Response(404, text="not found"))
    with pytest.raises(AdapterError) as failure:
        await ADAPTER.fetch("overview", CONFIG, {}, ctx)
    assert failure.value.code == "not_jackett"
    respx.get(f"{BASE}/api/v2.0/indexers").mock(return_value=httpx.Response(200, text="<html></html>"))
    with pytest.raises(AdapterError) as failure:
        await ADAPTER.fetch("overview", CONFIG, {}, ctx)
    assert failure.value.code == "not_json"
    respx.get(f"{BASE}/api/v2.0/indexers").mock(return_value=httpx.Response(200, json={"hello": "world"}))
    with pytest.raises(AdapterError) as failure:
        await ADAPTER.fetch("overview", CONFIG, {}, ctx)
    assert failure.value.code == "not_jackett"


@respx.mock
async def test_an_unreachable_jackett(ctx: Context) -> None:
    respx.get(f"{BASE}/api/v2.0/indexers").mock(side_effect=httpx.ConnectError("connection refused"))
    with pytest.raises(Unreachable):
        await ADAPTER.fetch("overview", CONFIG, {}, ctx)


def test_the_demo_fills_every_card() -> None:
    for tick in range(8):
        assert ADAPTER.demo("overview", {}, tick).primary
        assert ADAPTER.demo("indexers", {}, tick).items


@respx.mock
async def test_a_sign_in_that_is_taken_and_still_not_let_through_ends_instead_of_going_round(ctx: Context) -> None:
    jackett()
    respx.get(f"{BASE}/api/v2.0/indexers").mock(return_value=httpx.Response(302, headers={"Location": f"{BASE}/UI/Login"}))
    with pytest.raises(AuthFailed) as failure:
        await ADAPTER.fetch("overview", CONFIG, {}, ctx)
    assert "did not accept the sign-in" in str(failure.value)
