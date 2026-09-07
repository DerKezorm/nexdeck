"""Sign in with Plex: the PIN dance against a recorded plex.tv, and the routes that carry it."""

from __future__ import annotations

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.services import plex_auth

from .conftest import CSRF, create_user, login, setup_admin

PLEX = "https://plex.tv/api/v2"


@respx.mock
async def test_pin_url_and_polling(data_dir) -> None:  # noqa: ANN001
    pins = respx.post(f"{PLEX}/pins").mock(return_value=httpx.Response(201, json={"id": 4711, "code": "ABCD"}))
    challenge = await plex_auth.begin_login()
    assert challenge["id"] == "4711" and challenge["code"] == "ABCD"
    assert challenge["url"].startswith("https://app.plex.tv/auth#?clientID=") and "code=ABCD" in challenge["url"] and "product%5D=nexdeck" in challenge["url"]
    sent = pins.calls.last.request
    assert sent.url.params["strong"] == "true"
    assert sent.headers["X-Plex-Product"] == "nexdeck" and len(sent.headers["X-Plex-Client-Identifier"]) == 32
    assert sent.headers["X-Plex-Client-Identifier"] == plex_auth.client_identifier(), "one identifier per installation"

    poll = respx.get(f"{PLEX}/pins/4711").mock(side_effect=[httpx.Response(200, json={"id": 4711, "authToken": None}), httpx.Response(200, json={"id": 4711, "authToken": "tok-1"})])
    assert await plex_auth.poll_login("4711", "ABCD") is None
    assert await plex_auth.poll_login("4711", "ABCD") == "tok-1"
    assert poll.calls.last.request.url.params["code"] == "ABCD"


@respx.mock
async def test_servers_are_sorted_owned_first_and_local_first(data_dir) -> None:  # noqa: ANN001
    respx.get(f"{PLEX}/resources").mock(return_value=httpx.Response(200, json=[
        {"name": "Friend", "provides": "server", "owned": False, "clientIdentifier": "m2", "accessToken": "shared-tok", "connections": [{"uri": "https://1-2-3-4.plex.direct:32400", "local": False}]},
        {"name": "Phone", "provides": "client", "owned": True, "clientIdentifier": "m9", "connections": []},
        {"name": "Home", "provides": "server", "owned": True, "clientIdentifier": "m1", "connections": [{"uri": "https://9-9-9-9.plex.direct:32400", "local": False}, {"uri": "http://192.168.1.10:32400", "local": True}]},
    ]))
    found = await plex_auth.servers("tok-1")
    assert [s["name"] for s in found] == ["Home", "Friend"], "own server first, clients dropped"
    assert found[0]["urls"] == ["http://192.168.1.10:32400", "https://9-9-9-9.plex.direct:32400"], "local address first"
    assert found[0]["access_token"] == "tok-1", "the owner uses the account token"
    assert found[1]["access_token"] == "shared-tok", "a shared server needs its own access token"


@respx.mock
async def test_plex_tv_failures_are_readable(data_dir) -> None:  # noqa: ANN001
    respx.post(f"{PLEX}/pins").mock(return_value=httpx.Response(200, json={}))
    with pytest.raises(plex_auth.PlexTvError) as no_pin:
        await plex_auth.begin_login()
    assert "PIN" in no_pin.value.message
    respx.get(f"{PLEX}/user").mock(return_value=httpx.Response(401))
    with pytest.raises(plex_auth.PlexTvError) as refused:
        await plex_auth.account_name("bad")
    assert refused.value.code == "plex_refused"


@respx.mock
def test_plex_routes_need_a_member_and_pass_plex_answers_through(client: TestClient) -> None:
    respx.post(f"{PLEX}/pins").mock(return_value=httpx.Response(201, json={"id": 1, "code": "ZZ"}))
    respx.get(f"{PLEX}/pins/1").mock(return_value=httpx.Response(200, json={"id": 1, "authToken": "tok-9"}))
    respx.get(f"{PLEX}/user").mock(return_value=httpx.Response(200, json={"username": "plex-user"}))
    respx.get(f"{PLEX}/resources").mock(return_value=httpx.Response(200, json=[]))
    setup_admin(client)
    started = client.post("/api/v1/plex/pin", headers=CSRF)
    assert started.status_code == 200 and started.json()["code"] == "ZZ"
    # ⚠️ POST with the code in the body, not GET with it in the address. The
    # browser polls this every two seconds while somebody agrees at plex.tv, so
    # as a query parameter the code stood in nexdeck's own log and in every
    # line of the reverse proxy in front of it.
    polled = client.post("/api/v1/plex/pin/1", json={"code": "ZZ"}, headers=CSRF)
    assert polled.json() == {"token": "tok-9", "username": "plex-user"}
    assert client.post("/api/v1/plex/servers", json={"token": "tok-9"}, headers=CSRF).json() == []
    create_user(client, "visitor", role="guest")
    guest = TestClient(client.app)
    login(guest, "visitor", "another-long-password")
    assert guest.post("/api/v1/plex/pin", headers=CSRF).status_code == 403
    respx.post(f"{PLEX}/pins").mock(return_value=httpx.Response(503))
    failed = client.post("/api/v1/plex/pin", headers=CSRF)
    assert failed.status_code == 502 and "HTTP 503" in failed.json()["detail"]["message"]
