"""The kept answers of ``Context.request``: told apart by who asked, and never an error.

Found while building connections: ``auth=`` was not in the key, so two accounts at one address could share an answer,
and a 401 was held for the seconds of the cache, so the second try after signing in again got the old refusal.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from app.adapters.base import CACHE_PREFIX, Context

URL = "http://service.example.com/me"


def _ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, cache={})


def _answer_by_account(request: httpx.Request) -> httpx.Response:
    # A digest sends nothing until challenged; the count tells the answers apart all the same.
    _answered.append(request.headers.get("authorization", ""))
    return httpx.Response(200, json={"n": len(_answered)})


_answered: list[str] = []


@pytest.mark.parametrize("make", [
    lambda user: (user, "secret"),
    lambda user: httpx.BasicAuth(user, "secret"),
    lambda user: httpx.DigestAuth(user, "secret"),
])
@respx.mock
async def test_two_accounts_at_one_address_each_get_their_own_answer(make) -> None:
    _answered.clear()
    respx.get(URL).mock(side_effect=_answer_by_account)
    ctx = _ctx()
    first = await ctx.request("GET", URL, auth=make("alice"), cache_seconds=60)
    second = await ctx.request("GET", URL, auth=make("bob"), cache_seconds=60)
    assert first.json() != second.json()
    assert respx.calls.call_count == 2


@respx.mock
async def test_the_same_account_is_answered_from_memory() -> None:
    _answered.clear()
    respx.get(URL).mock(side_effect=_answer_by_account)
    ctx = _ctx()
    await ctx.request("GET", URL, auth=("alice", "secret"), cache_seconds=60)
    await ctx.request("GET", URL, auth=("alice", "secret"), cache_seconds=60)
    assert respx.calls.call_count == 1


@respx.mock
async def test_the_secret_is_not_in_the_key() -> None:
    respx.get(URL).mock(return_value=httpx.Response(200, json={}))
    ctx = _ctx()
    await ctx.request("GET", URL, auth=("alice", "hunter2-example"), cache_seconds=60)
    keys = [key for key in ctx.cache if key.startswith(CACHE_PREFIX)]
    assert len(keys) == 1
    assert "hunter2" not in keys[0] and "alice" not in keys[0]


@pytest.mark.parametrize("code", [401, 403, 407, 429, 500, 503])
@respx.mock
async def test_an_error_is_not_kept(code: int) -> None:
    route = respx.get(URL).mock(side_effect=[httpx.Response(code), httpx.Response(200, json={"ok": True})])
    ctx = _ctx()
    refused = await ctx.request("GET", URL, cache_seconds=60, auth_errors=False)
    assert refused.status_code == code
    again = await ctx.request("GET", URL, cache_seconds=60, auth_errors=False)
    assert again.status_code == 200
    assert route.call_count == 2


@respx.mock
async def test_an_answer_that_worked_is_still_kept() -> None:
    route = respx.get(URL).mock(return_value=httpx.Response(200, json={"ok": True}))
    ctx = _ctx()
    await ctx.request("GET", URL, cache_seconds=60)
    await ctx.request("GET", URL, cache_seconds=60)
    assert route.call_count == 1
