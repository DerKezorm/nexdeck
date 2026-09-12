"""Calibre-Web keeps the session its sign-in hands out, not the one of the page after it.

⚠️ Calibre-Web answers ``POST /login`` with a redirect, and the session cookie
stands in that redirect. The adapter read the cookie of the last answer in the
chain. That only ever worked because the shared client kept cookies and carried
the session to the page after the redirect. Since 12.09.2026 the shared client
keeps none, so the page after the redirect answers a stranger, and the adapter
would have kept an anonymous session and read the login page instead of books.
Found by reading every adapter for this on 12.09.2026.
"""

from __future__ import annotations

import asyncio

import httpx

from app.adapters import get_adapter
from app.adapters.base import Context, outbound_client

CONFIG = {"url": "http://calibre.example.com:8083", "username": "reader", "password": "made-up"}


def _calibre_web(seen: list[str]) -> httpx.MockTransport:
    async def handler(request: httpx.Request) -> httpx.Response:
        cookie = request.headers.get("cookie", "")
        seen.append(f"{request.method} {request.url.path} {cookie}")
        if request.url.path == "/login":
            return httpx.Response(302, headers={"Location": "/", "Set-Cookie": "session=signed-in; Path=/"})
        if request.url.path == "/":
            # The page after the sign-in hands a stranger an anonymous session.
            if "session=signed-in" in cookie:
                return httpx.Response(200, text="<html>shelf</html>")
            return httpx.Response(200, text="<html>login</html>", headers={"Set-Cookie": "session=anonymous; Path=/"})
        if request.url.path == "/ajax/listbooks":
            if "session=signed-in" in cookie:
                return httpx.Response(200, json={"totalNotFiltered": 2480, "rows": []})
            return httpx.Response(200, text="<html>login</html>")
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def test_the_session_comes_from_the_sign_in_not_from_the_page_after_it() -> None:
    seen: list[str] = []

    async def fetch() -> object:
        # The shape of the collector's shared client: follows redirects, keeps no cookies.
        client = outbound_client(transport=_calibre_web(seen), follow_redirects=True)
        try:
            return await get_adapter("calibreweb").fetch("library", CONFIG, {}, Context(client, integration_id=1, widget_id=1, cache={}))
        finally:
            await client.aclose()

    data = asyncio.run(fetch())
    assert data.primary == {"label": "Books", "value": 2480}, seen
    assert any(line.startswith("GET /ajax/listbooks session=signed-in") for line in seen), seen
