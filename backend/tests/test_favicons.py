"""A card's logo from the service itself: only from its own host, only a picture, never too large."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.services import favicons, icons

from .conftest import CSRF, create_user, login, setup_admin

SITE = "http://192.0.2.10:8080"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
ICO = b"\x00\x00\x01\x00" + b"\x00" * 64
CLEAN_SVG = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 8 8"><title>Online = yes</title><rect width="8" height="8"/></svg>'


def page(*links: str) -> httpx.Response:
    return httpx.Response(200, html=f"<html><head><title>Service</title>{''.join(links)}</head><body><link rel=icon href=/late.png></body></html>")


@pytest.fixture(autouse=True)
def fresh(data_dir: Path) -> None:
    """A client and a list of misses of their own for every test: each runs in a loop of its own."""
    favicons._client = None
    icons._negative.clear()


@respx.mock
async def test_the_touch_icon_comes_first_and_is_kept() -> None:
    respx.get(f"{SITE}/").mock(return_value=page('<link rel="icon" href="/small.ico" sizes="16x16">', '<link rel="apple-touch-icon" href="/touch.png">'))
    touch = respx.get(f"{SITE}/touch.png").mock(return_value=httpx.Response(200, content=PNG, headers={"content-type": "image/png"}))
    assert await favicons.favicon(f"{SITE}/some/where?x=1") == (PNG, "image/png")
    assert await favicons.favicon(SITE) == (PNG, "image/png")
    assert touch.call_count == 1, "the second time from the cache"


@respx.mock
async def test_a_logo_on_another_host_is_never_fetched() -> None:
    respx.get(f"{SITE}/").mock(return_value=page('<link rel="icon" href="https://cdn.example.com/logo.png">', '<link rel="icon" href="//198.51.100.7/x.png">'))
    elsewhere = respx.get(host="cdn.example.com").mock(return_value=httpx.Response(200, content=PNG))
    other = respx.get(host="198.51.100.7").mock(return_value=httpx.Response(200, content=PNG))
    respx.get(f"{SITE}/favicon.ico").mock(return_value=httpx.Response(200, content=ICO))
    assert await favicons.favicon(SITE) == (ICO, "image/x-icon")
    assert not elsewhere.called and not other.called


@respx.mock
async def test_a_redirect_is_followed_only_on_the_same_place() -> None:
    respx.get(f"{SITE}/").mock(return_value=httpx.Response(302, headers={"location": "/login"}))
    respx.get(f"{SITE}/login").mock(return_value=page('<link rel="icon" href="/brand.png" sizes="192x192">'))
    respx.get(f"{SITE}/brand.png").mock(return_value=httpx.Response(301, headers={"location": "https://example.com/brand.png"}))
    away = respx.get("https://example.com/brand.png").mock(return_value=httpx.Response(200, content=PNG))
    respx.get(f"{SITE}/favicon.ico").mock(return_value=httpx.Response(200, content=ICO))
    assert await favicons.favicon(SITE) == (ICO, "image/x-icon"), "the logo that leaves the host is skipped"
    assert not away.called


@respx.mock
async def test_a_redirect_to_loopback_is_refused_on_the_hop() -> None:
    respx.get(f"{SITE}/").mock(return_value=page())
    respx.get(f"{SITE}/favicon.ico").mock(return_value=httpx.Response(302, headers={"location": "http://127.0.0.1:8080/favicon.ico"}))
    inside = respx.get("http://127.0.0.1:8080/favicon.ico").mock(return_value=httpx.Response(200, content=ICO))
    assert await favicons.favicon(SITE) is None
    assert not inside.called


@respx.mock
async def test_nothing_is_asked_of_loopback_or_link_local() -> None:
    route = respx.get(url__regex=r".*").mock(return_value=httpx.Response(200, content=ICO))
    for address in ("http://127.0.0.1:8080", "http://localhost:3000", "http://169.254.169.254", "file:///etc/passwd", "ftp://192.0.2.10/"):
        assert await favicons.favicon(address) is None, address
    assert not route.called
    assert favicons._client is None, "refused before a connection is even made ready"


@respx.mock
async def test_every_hop_is_held_to_the_member_rule() -> None:
    """The guard on the client, not only on the first address: loopback is refused on any request it makes."""
    inside = respx.get(url__regex=r".*").mock(return_value=httpx.Response(200, content=ICO))
    assert await favicons._get("http://127.0.0.1:8080/favicon.ico", favicons.ICON_LIMIT, "http://127.0.0.1:8080") is None
    assert not inside.called


@respx.mock
async def test_what_is_not_a_picture_or_too_large_is_left_alone() -> None:
    respx.get(f"{SITE}/").mock(return_value=page('<link rel="icon" href="/big.png">', '<link rel="icon" href="/streamed.png">', '<link rel="icon" href="/page.png">'))
    respx.get(f"{SITE}/big.png").mock(return_value=httpx.Response(200, content=PNG, headers={"content-length": str(favicons.ICON_LIMIT + 1)}))
    respx.get(f"{SITE}/streamed.png").mock(return_value=httpx.Response(200, stream=httpx.ByteStream(PNG * (favicons.ICON_LIMIT // len(PNG) + 2))))
    respx.get(f"{SITE}/page.png").mock(return_value=httpx.Response(200, html="<html>not a picture</html>", headers={"content-type": "image/png"}))
    favicon = respx.get(f"{SITE}/favicon.ico").mock(return_value=httpx.Response(404))
    assert await favicons.favicon(SITE) is None
    assert favicon.called
    # A miss is remembered: the next card on the same service asks nobody for an hour.
    again = respx.get(f"{SITE}/").mock(return_value=page())
    again.reset()
    assert await favicons.favicon(SITE) is None
    assert not again.called


@respx.mock
async def test_an_svg_is_taken_only_without_anything_that_runs() -> None:
    respx.get(f"{SITE}/").mock(return_value=page('<link rel="icon" type="image/svg+xml" href="/bad.svg">', '<link rel="icon" href="/good.svg">'))
    respx.get(f"{SITE}/bad.svg").mock(return_value=httpx.Response(200, content=b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"/>', headers={"content-type": "image/svg+xml"}))
    respx.get(f"{SITE}/good.svg").mock(return_value=httpx.Response(200, content=CLEAN_SVG, headers={"content-type": "image/svg+xml"}))
    assert await favicons.favicon(SITE) == (CLEAN_SVG, "image/svg+xml")


def test_the_card_serves_its_service_logo_to_who_may_see_it(client: TestClient) -> None:
    setup_admin(client)
    board = client.post("/api/v1/boards", json={"name": "Apps"}, headers=CSRF).json()
    page_id = board["pages"][0]["id"]
    tile = client.post(f"/api/v1/pages/{page_id}/widgets", json={"kind": "core.app", "title": "Wiki", "link": f"{SITE}/wiki", "options": {"check": False}}, headers=CSRF).json()
    tile_id = tile.get("id") or tile["widget"]["id"]
    bare = client.post(f"/api/v1/pages/{page_id}/widgets", json={"kind": "core.clock"}, headers=CSRF).json()
    bare_id = bare.get("id") or bare["widget"]["id"]
    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{SITE}/").mock(return_value=page('<link rel="icon" href="/logo.svg">'))
        mock.get(f"{SITE}/logo.svg").mock(return_value=httpx.Response(200, content=CLEAN_SVG, headers={"content-type": "image/svg+xml"}))
        served = client.get(f"/api/v1/widgets/{tile_id}/favicon")
        assert served.status_code == 200, served.text
        assert served.headers["content-type"] == "image/svg+xml"
        assert "sandbox" in served.headers["content-security-policy"], "an SVG of somebody else's making runs nothing"
        assert client.get(f"/api/v1/widgets/{bare_id}/favicon").status_code == 404, "a card without an address has none"

        create_user(client, "member")
        stranger = TestClient(client.app)
        login(stranger, "member", "another-long-password")
        assert stranger.get(f"/api/v1/widgets/{tile_id}/favicon").status_code in (403, 404)
        assert TestClient(client.app).get(f"/api/v1/widgets/{tile_id}/favicon").status_code in (401, 403, 404)


def test_a_connection_in_the_list_gets_its_service_logo_and_a_locked_one_only_for_admins(client: TestClient) -> None:
    setup_admin(client)
    made = client.post("/api/v1/integrations", json={"kind": "radarr", "name": "Movies", "config": {"url": f"{SITE}/radarr", "api_key": "made-up-key"}, "admin_only": True}, headers=CSRF)
    assert made.status_code in (200, 201), made.text
    number = made.json()["id"]
    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{SITE}/").mock(return_value=page('<link rel="icon" href="/logo.png" sizes="64x64">'))
        mock.get(f"{SITE}/logo.png").mock(return_value=httpx.Response(200, content=PNG))
        served = client.get(f"/api/v1/integrations/{number}/favicon")
        assert served.status_code == 200, served.text
        assert served.content == PNG and served.headers["content-type"] == "image/png"
        create_user(client, "member")
        member = TestClient(client.app)
        login(member, "member", "another-long-password")
        assert member.get(f"/api/v1/integrations/{number}/favicon").status_code in (403, 404)
