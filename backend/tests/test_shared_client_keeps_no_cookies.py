"""A client shared by all connections does not carry one answer's cookie into the next request.

⚠️ ``outbound_client`` built an ordinary ``httpx.AsyncClient``, and httpx keeps
every ``Set-Cookie``. The collector shares one such client across every
connection, so a session cookie that one connection's answer set went along
with the next request to the same host, whatever credentials that one carried.
Measured on What's Up Docker 9 on 11.09.2026: after one sign-in with the
administrator, a wrong password got in as well. Left open then as todo 28,
repaired on 12.09.2026.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx

from app.adapters.base import outbound_client


def _service(seen: list[str]) -> httpx.MockTransport:
    async def handler(request: httpx.Request) -> httpx.Response:
        cookie = request.headers.get("cookie", "")
        seen.append(cookie)
        if request.url.path == "/login":
            return httpx.Response(200, headers={"Set-Cookie": "connect.sid=signed-in; Path=/"})
        return httpx.Response(200 if "connect.sid" in cookie else 401)

    return httpx.MockTransport(handler)


def _sign_in_then_ask_with_a_wrong_password(**kwargs: object) -> tuple[int, list[str]]:
    seen: list[str] = []

    async def run() -> int:
        client = outbound_client(transport=_service(seen), **kwargs)
        try:
            await client.get("http://wud.example.com/login", auth=("admin", "the-right-one"))
            answer = await client.get("http://wud.example.com/api/containers", auth=("admin", "a-wrong-one"))
            return answer.status_code
        finally:
            await client.aclose()

    return asyncio.run(run()), seen


def test_a_shared_client_does_not_hand_one_answers_cookie_to_the_next_request() -> None:
    status, seen = _sign_in_then_ask_with_a_wrong_password()
    assert seen[1] == "", f"the second request carried {seen[1]!r}"
    assert status == 401


def test_a_client_built_for_one_connection_may_keep_its_session() -> None:
    """Deluge, qBittorrent and UniFi sign in once and build a client per connection for it."""
    status, seen = _sign_in_then_ask_with_a_wrong_password(keep_cookies=True)
    assert "connect.sid=signed-in" in seen[1]
    assert status == 200


def test_the_clients_that_sign_in_with_a_cookie_ask_to_keep_it() -> None:
    adapters = Path(__file__).resolve().parents[1] / "app" / "adapters"
    for name in ("deluge.py", "qbittorrent.py", "unifi.py"):
        assert "keep_cookies=True" in (adapters / name).read_text(encoding="utf-8"), name
