"""Pocket ID, against the answers of a live Pocket ID 2.14.0 (11.09.2026)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context, Unreachable
from app.adapters.pocketid import PocketIdAdapter

FIXTURES = Path(__file__).parent / "fixtures"
PI = "http://pocket-id.example.com:1411"
CONFIG = {"url": PI, "api_key": "made-up-key"}
#: Ten minutes after the two measured sign-ins.
NOW = datetime(2026, 9, 11, 21, 56, 34, tzinfo=UTC).timestamp()


def fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


SIGNINS = fixture("pocketid_signins.json")
USERS = fixture("pocketid_users.json")


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


def _rows(data: Any) -> list[tuple[Any, ...]]:
    return [(row["title"], row["subtitle"], row["value"]) for row in data.items]


def test_recent_sign_ins_with_how_and_where() -> None:
    data = PocketIdAdapter._signins(SIGNINS, NOW)
    # ⚠️ Measured: "python-httpx on  " is what Pocket ID makes of a client without an operating system.
    assert _rows(data) == [("alice", "Login code · Internal network · python-httpx", "10 min"),
                           ("bob", "Login code · Internal network · python-httpx", "10 min")]
    assert data.secondary == [{"label": "Sign-ins", "value": 2}] and data.status == "ok"


def test_the_newest_first_and_only_sign_ins() -> None:
    remote = {**SIGNINS["data"][0], "event": "REMOTE_SIGN_IN", "username": "dana", "country": "Germany", "city": "Berlin",
              "device": "Safari on iOS", "createdAt": "2026-09-11T21:55:34Z"}
    passkey = {**SIGNINS["data"][1], "event": "SIGN_IN", "username": "erin", "country": "unknown", "city": "unknown",
               "device": "Firefox on Linux", "createdAt": "2026-09-11T20:56:34Z"}
    added = {**SIGNINS["data"][1], "event": "PASSKEY_ADDED", "username": "frank", "createdAt": "2026-09-11T21:56:00Z"}
    data = PocketIdAdapter._signins({"data": [*SIGNINS["data"], passkey, added, remote], "pagination": {"totalItems": 4}}, NOW)
    assert _rows(data) == [
        ("dana", "Other device · Berlin, Germany · Safari on iOS", "1 min"),
        ("alice", "Login code · Internal network · python-httpx", "10 min"),
        ("bob", "Login code · Internal network · python-httpx", "10 min"),
        ("erin", "Passkey · Firefox on Linux", "1 h"),
    ]
    assert PocketIdAdapter._signins({"data": []}, NOW).meta["empty"] == "Nobody has signed in yet."


def test_the_overview_leaves_the_static_api_user_out() -> None:
    """⚠️ Measured: STATIC_API_KEY adds an administrator called Static API User to the list."""
    data = PocketIdAdapter._summary(USERS["data"])
    assert data.primary == {"label": "Users", "value": 3}
    assert data.secondary == [{"label": "Administrators", "value": 1}, {"label": "Disabled", "value": 1}]
    assert data.metrics == {"users": 3.0}


@respx.mock
async def test_the_sign_in_card_asks_for_sign_in_events_newest_first(ctx: Context) -> None:
    route = respx.get(f"{PI}/api/audit-logs/all").mock(return_value=httpx.Response(200, json=SIGNINS))
    data = await get_adapter("pocketid").fetch("signins", CONFIG, {"limit": 500}, ctx)
    params = dict(route.calls.last.request.url.params)
    assert params == {"sort[column]": "createdAt", "sort[direction]": "desc", "pagination[limit]": "100",
                      "filters[event][0]": "SIGN_IN", "filters[event][1]": "TOKEN_SIGN_IN", "filters[event][2]": "REMOTE_SIGN_IN"}
    assert route.calls.last.request.headers["X-API-KEY"] == "made-up-key"
    assert [row["title"] for row in data.items] == ["alice", "bob"]


@respx.mock
async def test_the_overview_asks_for_the_users(ctx: Context) -> None:
    route = respx.get(f"{PI}/api/users").mock(return_value=httpx.Response(200, json=USERS))
    data = await get_adapter("pocketid").fetch("summary", CONFIG, {}, ctx)
    assert route.calls.last.request.url.params["pagination[limit]"] == "100"
    assert data.primary["value"] == 3


@respx.mock
async def test_a_rejected_key_and_a_key_that_is_not_an_administrators(ctx: Context) -> None:
    respx.get(f"{PI}/api/users").mock(return_value=httpx.Response(401, json={"error": "You are not signed in", "code": "not_signed_in"}))
    with pytest.raises(AuthFailed) as rejected:
        await get_adapter("pocketid").fetch("summary", CONFIG, {}, ctx)
    assert "rejected" in rejected.value.message
    respx.get(f"{PI}/api/users").mock(return_value=httpx.Response(403, json={"error": "You don't have permission to perform this action", "code": "forbidden"}))
    # A context of its own: the first answer is kept for the card's five minutes, refusal or not.
    fresh = Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})
    with pytest.raises(AuthFailed) as not_admin:
        await get_adapter("pocketid").fetch("summary", CONFIG, {}, fresh)
    assert "administrator" in not_admin.value.message


@respx.mock
async def test_the_web_interface_instead_of_the_api(ctx: Context) -> None:
    """⚠️ Measured: an address that is not the API answers 200 with the web page."""
    respx.get(f"{PI}/api/users").mock(return_value=httpx.Response(200, text="<!doctype html><html></html>"))
    with pytest.raises(AdapterError) as page:
        await get_adapter("pocketid").fetch("summary", CONFIG, {}, ctx)
    assert page.value.code == "not_json"
    respx.get(f"{PI}/api/audit-logs/all").mock(return_value=httpx.Response(200, json={"status": "ok"}))
    with pytest.raises(AdapterError) as wrong:
        await get_adapter("pocketid").fetch("signins", CONFIG, {}, ctx)
    assert wrong.value.code == "not_pocketid"
    respx.get(f"{PI}/api/audit-logs/all").mock(return_value=httpx.Response(404, json={"error": "API endpoint not found"}))
    fresh = Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})
    with pytest.raises(AdapterError) as missing:
        await get_adapter("pocketid").fetch("signins", CONFIG, {}, fresh)
    assert missing.value.code == "http_error"


@respx.mock
async def test_a_pocket_id_that_does_not_answer(ctx: Context) -> None:
    respx.get(f"{PI}/api/users").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(Unreachable):
        await get_adapter("pocketid").fetch("summary", CONFIG, {}, ctx)


@respx.mock
async def test_the_connection_test(ctx: Context) -> None:
    respx.get(f"{PI}/api/version/current").mock(return_value=httpx.Response(200, json={"currentVersion": "2.14.0"}))
    respx.get(f"{PI}/api/users").mock(return_value=httpx.Response(200, json=USERS))
    assert await get_adapter("pocketid").test(CONFIG, ctx) == "Pocket ID 2.14.0 answers with 3 users."
