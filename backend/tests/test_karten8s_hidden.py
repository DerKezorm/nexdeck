"""S1 (security review, stage 8): what a card gets from a service holds no credential of its connection.

A card reads any path under its connection. Sonarr names its own key at ``/api/v3/config/host``, and what a card reads
ends up with every viewer of the board. The answer is cleaned where it reaches the card (``rawread``): every text that
holds a credential of the connection, as a part, percent-encoded or in Base64, becomes ``[hidden]``.
"""

from __future__ import annotations

import asyncio
import base64
from typing import Any
from urllib.parse import quote

import httpx
import respx

from app.adapters import defined, get_adapter, rawread
from app.adapters.base import Context
from app.adapters.custom import present
from app.cards import load, pipeline, source
from app.cards.schema import Request

from .karten3_sample import MEMOS

BASE = "http://svc.example.com:8989"
KEY = "0123456789abcdef" * 2  # a Sonarr key has 32 hex digits
HIDDEN = "[hidden]"


def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


def read(adapter: Any, config: dict[str, Any], path: str = "/api/v3/config/host") -> Any:
    return asyncio.run(source.fetch_source(adapter, config, ctx(), Request(id="host", path=path)))


SONARR = {"url": BASE, "api_key": KEY}

CARD = """\
nexdeck-card: 1
slug: queue-size
name: {en: Queue size}
version: 1.0.0
requires: [sonarr]
requests:
  - id: host
    path: /api/v3/config/host
form: list
rows: {select: "[@]"}
item:
  title: {template: "Instance {instanceName}"}
  value: apiKey
demo:
  host: {instanceName: Sonarr, apiKey: aaaa}
"""


@respx.mock
def test_karten8s_s1_the_key_of_a_sonarr_never_reaches_the_data_of_a_card() -> None:
    """The probe of the review, the other way round: the key the service names is not in what a viewer gets."""
    respx.get(f"{BASE}/api/v3/config/host").mock(return_value=httpx.Response(200, json={"instanceName": "Sonarr", "apiKey": KEY}))
    definition = load.load_definition(CARD).definition
    answer = read(get_adapter("sonarr"), SONARR)
    assert answer == {"instanceName": "Sonarr", "apiKey": HIDDEN}
    dumped = present(definition, pipeline.run(definition, {"host": answer})).model_dump_json()
    assert KEY not in dumped and "Instance Sonarr" in dumped


@respx.mock
def test_karten8s_s1_a_text_that_holds_the_key_as_a_part_encoded_or_in_base64_is_hidden_whole() -> None:
    encoded = base64.b64encode(KEY.encode()).decode()
    answer = {
        "plain": KEY,
        "part": f"https://svc.example.com/feed?apikey={KEY}&x=1",
        "percent": "q=" + quote(KEY + "/", safe="").lower(),
        "basic": f"Basic {encoded}",
        "urlsafe": base64.urlsafe_b64encode(("x" + KEY).encode()).decode(),
        "nested": [{"deep": {"key": KEY}}, 7, None, True],
        KEY: "a name that is the key",
        "other": "nothing secret here",
        "number": 42,
    }
    respx.get(f"{BASE}/api/v3/config/host").mock(return_value=httpx.Response(200, json=answer))
    got = read(get_adapter("sonarr"), SONARR)
    assert got["plain"] == got["part"] == got["percent"] == got["basic"] == HIDDEN
    assert got["nested"] == [{"deep": {"key": HIDDEN}}, 7, None, True]
    assert got[HIDDEN] == "a name that is the key" and KEY not in got
    assert got["other"] == "nothing secret here" and got["number"] == 42
    # Base64 of a text that only begins with something else is not the Base64 of the key: it stays.
    assert got["urlsafe"] != HIDDEN


@respx.mock
def test_karten8s_s1_a_plain_text_answer_that_holds_the_key_is_hidden_and_a_short_key_is_not_looked_for() -> None:
    respx.get(f"{BASE}/api/v3/config/host").mock(return_value=httpx.Response(200, text=f"key is {KEY}"))
    assert read(get_adapter("sonarr"), SONARR) == HIDDEN
    respx.get(f"{BASE}/api/v3/status").mock(return_value=httpx.Response(200, json={"state": "k-12 running"}))
    assert read(get_adapter("sonarr"), {"url": BASE, "api_key": "k-12"}, "/api/v3/status") == {"state": "k-12 running"}


@respx.mock
def test_karten8s_s1_an_answer_without_a_credential_comes_back_as_it_was() -> None:
    route = respx.get(f"{BASE}/api/v3/config/host").mock(return_value=httpx.Response(200, json={"records": [{"title": "A"}]}))
    assert read(get_adapter("sonarr"), SONARR) == {"records": [{"title": "A"}]}
    assert route.calls.last.request.headers["x-api-key"] == KEY, "the key is still what signs the request"


PASSWORD = "pw-SuperSecret-9876543210"
TICKET = "ticket-0123456789"


@respx.mock
def test_karten8s_s1_the_password_and_the_ticket_of_an_own_connection_with_a_session_are_hidden() -> None:
    from app.cards.integration import load_integration

    adapter = defined.DefinedAdapter(load_integration(MEMOS).definition, MEMOS)
    respx.post(f"{BASE}/api/v1/auth/signin").mock(return_value=httpx.Response(200, json={"accessToken": TICKET}))
    route = respx.get(f"{BASE}/api/v1/me").mock(
        return_value=httpx.Response(200, json={"name": "ann", "session": f"Bearer {TICKET}", "pw": PASSWORD, "notes": 3})
    )
    got = read(adapter, {"url": BASE, "username": "ann", "password": PASSWORD}, "/api/v1/me")
    assert got == {"name": "ann", "session": HIDDEN, "pw": HIDDEN, "notes": 3}
    assert route.calls.last.request.headers["authorization"] == f"Bearer {TICKET}"


@respx.mock
def test_karten8s_s1_what_a_button_gets_back_holds_no_credential_either() -> None:
    respx.post(f"{BASE}/api/v3/command").mock(return_value=httpx.Response(201, json={"name": "RefreshSeries", "echo": KEY}))

    async def press() -> Any:
        return (await get_adapter("sonarr").raw_act("POST", "/api/v3/command", SONARR, ctx(), json_body={"name": "RefreshSeries"})).json()

    assert asyncio.run(press()) == {"name": "RefreshSeries", "echo": HIDDEN}


def test_karten8s_s1_the_credentials_come_from_the_secret_fields_the_signing_and_the_cookies_but_not_the_login_name() -> None:
    cookies = httpx.Cookies()
    cookies.set("SID", "cookie-0123456789", domain="svc.example.com")
    sent = rawread.Sent({"Authorization": "Bearer token-0123456789", "X-Client": "nexdeck-client"}, {"user": "someone-long", "sid": "sid-0123456789"}, ("someone-long", "pw-0123456789"))
    found = rawread.credentials_of(get_adapter("sonarr"), SONARR, [sent], cookies)
    assert {KEY, "token-0123456789", "sid-0123456789", "pw-0123456789", "cookie-0123456789"} <= found
    assert "someone-long" not in found and "nexdeck-client" not in found
