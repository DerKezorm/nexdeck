"""A custom card can read through every kind of connection that speaks HTTP, and signs in the way the kind does (JEDE-1, JEDE-2).

No kind is tried one by one for a card. The test goes over **all** adapters: each one is asked once through a stubbed
server with invented credentials (only example.com), and what its connection carries has to come along, whichever way
the kind proves who asks (header, login, key in the address). The kinds that open a session first are listed with the
pattern they follow and are tested by pattern in ``test_cards_sessions.py``.
"""

from __future__ import annotations

import base64
from typing import Any

import httpx
import pytest
import respx

from app.adapters import all_adapters, get_adapter
from app.adapters.base import NOT_READ_BY_CARDS, Context
from app.cards import source
from app.cards.schema import Request

BASE = "http://svc.example.com:8080"

#: Kinds that open a session before they ask (or fetch a token first): a stub that answers ``{}`` cannot sign them in.
#: Each stands for a pattern, and ``test_cards_sessions.py`` signs in through a stub that does it properly.
SIGNS_IN: dict[str, str] = {
    "qbittorrent": "cookie of a client of its own",
    "deluge": "cookie of a client of its own",
    "pihole": "session id in a header, from a POST",
    "synology": "session id in the address, from a GET",
    "npm": "token in a header, from a POST",
    "kavita": "token in a header, from a GET with the key",
    "twitch": "token from another host",
    "freshrss": "token in a header, from a POST",
    "urbackup": "session id in the address",
    "bookorbit": "token in a header, from a POST",
    "calibreweb": "cookie in a header, from a POST",
    "beszel": "token in a header, from a POST",
    "frigate": "token in a header, from a POST",
    "reolink": "token in the address, from a GET",
    "duplicati": "token in a header, from a POST",
    "openmediavault": "session id in a header, from a POST",
    "openwrt": "session id in the body, from a POST",
    "ghostfolio": "token in a header, from a POST",
    "zabbix": "asks without a token first",
}

#: Configurations the plain filling-in would make contradictory.
FIXES: dict[str, dict[str, Any]] = {"elasticsearch": {"username": ""}}


def invented(kind: str) -> dict[str, Any]:
    """A connection of this kind with every text field filled with a marker, so a test can see where it travels."""
    config: dict[str, Any] = {}
    for one in get_adapter(kind).fields:
        if one.type in ("integrations", "items", "choices", "board", "pictures", "cards", "date", "time", "timezone", "colour", "textarea"):
            if one.default is not None:
                config[one.name] = one.default
        elif one.name == "url" or one.type == "url":
            config[one.name] = BASE
        elif one.type == "bool":
            config[one.name] = bool(one.default)
        elif one.type == "select":
            config[one.name] = one.default if one.default is not None else (one.options[0][0] if one.options else "")
        elif one.type == "number":
            config[one.name] = one.default if one.default is not None else 8080
        else:
            config[one.name] = "Zk" + one.name.replace("_", "")
    return {**config, **FIXES.get(kind, {})}


def markers(config: dict[str, Any]) -> list[str]:
    return [value for value in config.values() if isinstance(value, str) and value.startswith("Zk")]


def what_travelled(sent: httpx.Request) -> str:
    """Everything of a request that could carry a credential, with a basic login opened up."""
    text = str(sent.url) + " " + " ".join(f"{name}={value}" for name, value in sent.headers.items())
    login = sent.headers.get("authorization", "")
    if login.lower().startswith("basic "):
        text += " " + base64.b64decode(login[6:]).decode()
    return text


def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


def readable() -> list[str]:
    return sorted(one.kind for one in all_adapters() if one.kind not in NOT_READ_BY_CARDS)


def test_jede2_the_kinds_that_sign_in_first_are_kinds_that_exist_and_can_be_read() -> None:
    assert set(SIGNS_IN) <= set(readable())
    assert len(SIGNS_IN) < 25, "the list is for the few that open a session, not a way out for kinds that do not work"


@pytest.mark.parametrize("kind", [one for one in readable() if one not in SIGNS_IN])
@respx.mock
async def test_jede2_every_kind_asks_a_card_s_path_with_the_credentials_of_its_connection(kind: str) -> None:
    adapter = get_adapter(kind)
    config = invented(kind)
    route = respx.route().mock(return_value=httpx.Response(200, json={}))
    try:
        await adapter.test(config, ctx())
    except Exception:  # noqa: BLE001, S110 - a stub that answers {} may fail a test; what it sent before is what counts
        pass
    # What proves who asks in the kind's own request (a secret field or the user name, in a header or the query, not in the path or a
    # body) has to come along with the card's, every marker of it and not only one.
    proof = {config[name] for name in (*adapter.secret_field_names(), "username", "user") if isinstance(config.get(name), str)}
    expected = [
        one for one in markers(config)
        if one in proof and any(one in what_travelled(call.request).replace(call.request.url.path, "") for call in route.calls)
    ]
    # A kind whose own requests are all POSTs and carry none of the markers keeps its credentials for the POST (FRITZ!Box: user
    # and password only go with a TR-064 call, answered to a digest challenge); a card reads with a GET, which asks for none of it.
    posts_only = bool(route.calls) and all(
        call.request.method == "POST" and not any(one in what_travelled(call.request) for one in markers(config)) for call in route.calls
    )
    await source.fetch_source(adapter, config, ctx(), Request(id="probe", path="/api/getprobe"))
    sent = route.calls.last.request
    assert sent.method == "GET"
    assert str(sent.url.path) == httpx.URL(adapter.raw_base(config)).path.rstrip("/") + "/api/getprobe"
    assert sent.url.host == httpx.URL(adapter.raw_base(config)).host, "the credentials stay with the address of the connection"
    carried = what_travelled(sent)
    given = markers(config)
    if posts_only:
        return
    assert not given or any(one in carried for one in given), f"{kind}: nothing of the connection came along ({given})"
    assert all(one in carried for one in expected), f"{kind}: the kind's own request carries {expected}, the card only {carried}"


@respx.mock
async def test_jede2_a_card_never_sends_the_fritzbox_user_and_password_with_its_get() -> None:
    adapter = get_adapter("fritzbox")
    config = {"url": BASE, "username": "ZkUser", "password": "ZkSecret"}
    route = respx.route().mock(return_value=httpx.Response(200, json={}))
    await source.fetch_source(adapter, config, ctx(), Request(id="probe", path="/api/getprobe"))
    sent = route.calls.last.request
    assert sent.method == "GET" and "authorization" not in sent.headers
    assert "ZkUser" not in what_travelled(sent) and "ZkSecret" not in what_travelled(sent)


def test_jede6_the_service_step_lists_the_kinds_people_have_on_their_board_such_as_wud_and_the_sign_in_kinds() -> None:
    listed = {row["kind"] for row in source.sources()}
    assert {"wud", "pihole", "qbittorrent", "synology", "unifi", "tautulli", "github", "cloudflare"} <= listed
    assert not listed & set(NOT_READ_BY_CARDS)
