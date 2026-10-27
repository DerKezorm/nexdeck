"""A custom card signs in to the kinds that came with release 0.50.0 the way the kind does (JEDE-2, after the merge of ``main``).

The test over every kind (``test_cards_every_kind.py``) answers ``{}`` to everything and so cannot play a service that signs
in properly or asks who it talks to first. These kinds are listed there and played here, each with a stub that behaves.
"""

from __future__ import annotations

import time

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AuthFailed, Context

BASE = "http://svc.example.com:8080"
PASSWORD = "Zk-password-1"


def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


# -- slskd: a token from a POST, or an API key ------------------------------------------------


class Slskd:
    def __init__(self) -> None:
        self.logins = 0
        self.valid: str | None = None
        self.asked: list[httpx.Request] = []

    def login(self, request: httpx.Request) -> httpx.Response:
        assert PASSWORD.encode() in request.content
        self.logins += 1
        self.valid = f"tok-{self.logins}"
        return httpx.Response(200, json={"token": self.valid, "expires": time.time() + 3600})

    def read(self, request: httpx.Request) -> httpx.Response:
        self.asked.append(request)
        if request.headers.get("authorization") != f"Bearer {self.valid}":
            return httpx.Response(401)
        return httpx.Response(200, json={"version": {"current": "0.26.2"}})


@respx.mock
async def test_nach_merge_slskd_a_card_uses_the_token_of_the_sign_in_and_signs_in_again_when_it_was_turned_down() -> None:
    service = Slskd()
    respx.post(f"{BASE}/api/v0/session").mock(side_effect=service.login)
    respx.get(url__regex=rf"{BASE}/api/v0/.*").mock(side_effect=service.read)
    adapter, config, held = get_adapter("slskd"), {"url": BASE, "username": "ZkUser", "password": PASSWORD}, ctx()
    answer = await adapter.raw_request("GET", "/api/v0/application", config, held)
    assert answer.status_code == 200 and service.logins == 1
    sent = service.asked[-1]
    assert sent.headers["authorization"] == "Bearer tok-1" and PASSWORD not in str(sent.url) + str(sent.headers)
    await adapter.raw_request("GET", "/api/v0/transfers/downloads", config, held)
    assert service.logins == 1, "the token is kept, not asked for again with every card"
    service.valid = None  # revoked at the service
    answer = await adapter.raw_request("GET", "/api/v0/application", config, held)
    assert answer.status_code == 200 and service.logins == 2
    assert service.asked[-1].headers["authorization"] == "Bearer tok-2"


@respx.mock
async def test_nach_merge_slskd_a_path_the_service_keeps_turning_down_is_asked_once_more_and_then_the_card_fails() -> None:
    service = Slskd()
    respx.post(f"{BASE}/api/v0/session").mock(side_effect=service.login)
    respx.get(url__regex=rf"{BASE}/api/v0/.*").mock(return_value=httpx.Response(401))
    adapter, config = get_adapter("slskd"), {"url": BASE, "username": "ZkUser", "password": PASSWORD}
    with pytest.raises(AuthFailed):
        await adapter.raw_request("GET", "/api/v0/nothing", config, ctx())
    assert service.logins == 2, "one sign-in for the first ask and one renewal, never a third"


@respx.mock
async def test_nach_merge_slskd_an_api_key_travels_in_its_header_and_is_never_renewed() -> None:
    signed_in = respx.post(f"{BASE}/api/v0/session").mock(return_value=httpx.Response(200, json={}))
    read = respx.get(url__regex=rf"{BASE}/api/v0/.*").mock(return_value=httpx.Response(401))
    adapter, config = get_adapter("slskd"), {"url": BASE, "api_key": "ZkKey-1"}
    with pytest.raises(AuthFailed):
        await adapter.raw_request("GET", "/api/v0/application", config, ctx())
    assert read.calls.last.request.headers["x-api-key"] == "ZkKey-1" and not signed_in.called
