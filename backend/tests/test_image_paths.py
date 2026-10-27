"""Pictures through the image route: only the shapes an adapter names, checked before anything is fetched.

The route fetches with the connection's credentials, and some services act on
a plain GET (Plex marks a film as watched on ``/:/scrobble``). Every adapter
that hands out ``proxy:`` paths names their shapes in ``image_paths``; this
file finds those adapters by themselves, checks the paths they really write
against their list, and a row of dangerous ones against it too.
"""

from __future__ import annotations

import inspect
import json
import re
import time
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.adapters import all_adapters, get_adapter
from app.adapters import nexcanvas as nexcanvas_module
from app.adapters.base import Adapter, AdapterError, Context, ImagePath, WidgetData, image_path
from app.routers import widgets as widgets_router

from .conftest import CSRF, setup_admin
from .test_boards import _board, _widget

FIXTURES = Path(__file__).parent / "fixtures"
#: A ``proxy:`` path written in an adapter's code, as a string and not in a comment's backticks.
PROXY_LITERAL = re.compile(r"""\bf?["']proxy:""")
UUID = "9b3f2c1e-4d5a-4e6b-8c7d-0a1b2c3d4e5f"
BOARD = "Ab3_dEf-9xQ"


def _proxied(value: Any) -> list[str]:
    """Every ``proxy:`` path anywhere in a card's data, without the prefix."""
    if isinstance(value, str):
        return [value[len("proxy:"):]] if value.startswith("proxy:") else []
    if isinstance(value, dict):
        return [found for item in value.values() for found in _proxied(item)]
    if isinstance(value, (list, tuple)):
        return [found for item in value for found in _proxied(item)]
    return []


def _demo_paths(adapter: Adapter) -> list[str]:
    found: list[str] = []
    for widget in adapter.widgets:
        options = {f.name: f.default for f in widget.options}
        for tick in (0, 42, 900):
            try:
                data = adapter.demo(widget.kind, options, tick)
            except AdapterError:
                continue
            if isinstance(data, WidgetData):
                found += _proxied(data.model_dump())
    return found


def _offers_pictures(adapter: Adapter) -> bool:
    """Through its own ``image_source``, headers for pictures, a ``proxy:`` path in its code, or one in its demo data."""
    kind = type(adapter)
    if kind.image_source is not Adapter.image_source or kind.image_headers is not Adapter.image_headers:
        return True
    for klass in kind.__mro__:
        module = inspect.getmodule(klass)
        name = getattr(module, "__name__", "")
        if name.startswith("app.adapters.") and name != "app.adapters.base" and PROXY_LITERAL.search(inspect.getsource(module)):
            return True
    return bool(_demo_paths(adapter))


async def _plex_paths() -> list[str]:
    plex = get_adapter("plex")
    entries = [
        {"type": "movie", "title": "Harbour", "thumb": "/library/metadata/10/thumb/1791700000"},
        {"type": "episode", "title": "Pilot", "grandparentTitle": "Harbour Lights", "grandparentThumb": "/library/metadata/20/thumb/1791700001"},
        {"type": "season", "title": "Season 1", "parentTitle": "Harbour Lights", "thumb": "/library/metadata/21/thumb/1791700002"},
        {"type": "track", "title": "Low Tide", "parentThumb": "/library/metadata/31/thumb/1791700003"},
        {"type": "album", "title": "Northern Sky", "thumb": "/library/metadata/30/thumb"},
    ]
    found = [plex._poster(entry)["art"][len("proxy:"):] for entry in entries]
    for thumb in ("/library/metadata/5/thumb/17", "/playlists/7/composite/1791700004"):
        found += [cover[len("proxy:"):] for cover in plex._cover(thumb)]
    with respx.mock:
        respx.get("http://plex:32400/status/sessions").mock(return_value=httpx.Response(200, json={"MediaContainer": {"Metadata": [{
            "type": "episode", "title": "Pilot", "grandparentTitle": "Harbour Lights", "duration": 1000, "viewOffset": 500,
            "thumb": "/library/metadata/22/thumb/1791700005", "grandparentArt": "/library/metadata/20/art/1791700006",
        }]}}))
        async with httpx.AsyncClient() as client:
            streams = await plex.sessions({"url": "http://plex:32400", "token": "tok"}, Context(client, integration_id=1, cache={}))
    return found + [path for stream in streams for path in _proxied([stream.art, stream.backdrop])]


async def _jellyfin_paths(kind: str) -> list[str]:
    adapter = get_adapter(kind)
    with respx.mock:
        respx.get("http://jf:8096/Sessions").mock(return_value=httpx.Response(200, json=json.loads((FIXTURES / "jellyfin_sessions.json").read_text(encoding="utf-8"))))
        async with httpx.AsyncClient() as client:
            streams = await adapter.sessions({"url": "http://jf:8096", "api_key": "tok"}, Context(client, integration_id=1, cache={}))
    found = [path for stream in streams for path in _proxied([stream.art, stream.backdrop])]
    return found + _proxied([adapter._art("m1"), list(adapter._cover("m2"))])


async def real_paths(kind: str) -> list[str]:
    """The paths each adapter writes, made by its own code from fixtures and measured shapes."""
    if kind == "plex":
        return await _plex_paths()
    if kind in ("jellyfin", "emby"):
        return await _jellyfin_paths(kind)
    if kind == "frigate":
        frigate = get_adapter("frigate")
        camera = frigate._camera({"front_gate": {"camera_fps": 5}}, {"camera": "front_gate"})
        return _proxied([frigate._thumbnail({"id": "1726680000.5-ab12cd"}), camera.model_dump()])
    if kind == "reolink":
        # The camera card writes /snap/<channel>/<sub|main>; the bare channel is the older form still accepted.
        return ["/snap/0/sub", "/snap/1/main", "/snap/1"]
    if kind == "nexcanvas":
        return _proxied([nexcanvas_module._picture({"id": BOARD}, look, width, version)
                         for look, width, version in (("dark", 320, "1791707400"), ("light", 1200, "live"))])
    if kind == "nexcrate":
        nexcrate = get_adapter("nexcrate")
        return _proxied([nexcrate._art({"poster_path": "/8Gxv8gSFCU0XGDykEGv7zR1n2ua.jpg"}),
                         nexcrate._art({"album": {"cover_url": f"https://coverartarchive.org/release-group/{UUID}/front-500"}})])
    return []


#: The adapters that hand out pictures. A new one fails the guard below until it is named here with its real paths.
PICTURE_ADAPTERS = {"plex", "jellyfin", "emby", "frigate", "reolink", "nexcanvas", "nexcrate"}

#: Paths that act on a service or lead somewhere else, refused by every adapter.
DANGEROUS = [
    "", "/", "x.png", "//evil.example.com/x.png", "http://evil.example.com/x.png", "/login", "/api/v1/me",
    "/:/scrobble?key=10&identifier=com.plexapp.plugins.library", "/:/unscrobble?key=10&identifier=com.plexapp.plugins.library",
    "/library/sections/1/refresh", "/library/sections/all/refresh", "/library/metadata/10/refresh",
    "/cgi-bin/api.cgi?cmd=Reboot", "/System/Restart", "/Library/Refresh", "/api/restart",
]

#: Per service: the GETs with a side effect or a secret behind them that we know of.
KNOWN_HARM = {
    "plex": [
        "/:/rate?key=10&identifier=com.plexapp.plugins.library&rating=2",
        "/:/prefs?FriendlyName=x",
        "/library/metadata/10/thumb/1?X-Plex-Token=other",
        "/library/metadata/10/thumb/1/../../../sections/1/refresh",
        "/photo/:/transcode?width=240&height=240&minSize=1&upscale=1&url=%2F%3A%2Fscrobble%3Fkey%3D10",
        "/photo/:/transcode?width=240&height=240&minSize=1&upscale=1&url=%2Flibrary%2Fsections%2F1%2Frefresh",
        "/photo/:/transcode?width=240&height=240&minSize=1&upscale=1&url=http%3A%2F%2Fevil.example.com%2Fx.png",
        "/photo/:/transcode?width=240&url=%2Flibrary%2Fmetadata%2F5%2Fthumb%2F17&url=%2F%3A%2Fscrobble",
        "/photo/:/transcode?width=240&url=%252F%253A%252Fscrobble",
        "/photo/:/transcode?width=240&url=%2Flibrary%2Fmetadata%2F5%2Fthumb%2F17%3Fx%3D1",
        "/photo/:/transcode?width=240&url=%2Flibrary%2Fmetadata%2F5%2Fthumb%2F..%2F..%2F..%2Fsections%2F1%2Frefresh",
        "/LIBRARY/metadata/10/thumb/1",
    ],
    "jellyfin": [
        "/Videos/e1/stream.mp4?static=true", "/Items/e1/Download", "/Items/e1/PlaybackInfo",
        "/Items/e1/Images/Primary?maxHeight=400&api_key=other", "/Items/e1/Images/Primary?maxHeight=4000000",
        "/Items/e1/Images/Primary?maxHeight=400&format=svg", "/Items/../System/Restart", "/items/e1/images/primary",
    ],
    "emby": ["/Videos/e1/stream.mp4?static=true", "/emby/System/Restart", "/Items/e1/Download", "/Items/e1/Images/Primary?api_key=other"],
    "frigate": [
        "/api/events/1726680000.5-ab12cd/retain", "/api/front_gate/latest.jpg", "/latest/front_gate/../../api/restart",
        "/latest/front_gate?h=99999", "/thumb/..", "/latest/.hidden", "/latest/front_gate/extra",
    ],
    "reolink": ["/snap/1/main?cmd=Reboot", "/snap/1/../../cgi-bin/api.cgi", "/snap/1234", "/snap/1/MAIN", "/snap/-1"],
    "nexcanvas": [
        f"/api/v1/boards/{BOARD}", f"/api/v1/boards/{BOARD}/picture.svg", f"/board/{BOARD}/dark/1200/live?look=x",
        f"/board/{BOARD}/../../api/v1/me", f"/board/{BOARD}/blue/1200/live",
    ],
    "nexcrate": [
        "/tmdb/w342/../../3/movie/1", "/tmdb/original/abc.jpg", "/tmdb/w342/abc.jpg?api_key=other", "/tmdb/w342/abc.svg",
        "/caa/release/../../x", "/caa/release-group/not-a-uuid/front-500", f"/caa/release-group/{UUID.upper()}/front-500",
        "/api/v1/titles",
    ],
}


def _bent(path: str) -> list[str]:
    """A real path with the tricks that slip a second request past a check that reads it differently than the service."""
    part, _, query = path.partition("?")
    joined = "&" if query else "?"
    bent = [
        path + "/../../library/sections/1/refresh",
        part + "/./" + (("?" + query) if query else ""),
        "/" + path, path + "/",
        part.replace("/", "%2F") + (("?" + query) if query else ""),
        part + "%2F..%2F..%2Flibrary%2Fsections%2F1%2Frefresh",
        part + "%252F..%252F..%252Flibrary%252Fsections%252F1%252Frefresh",
        part + "%2e%2e", "/%2e%2e" + part,
        part.replace("/", "\\"), path + "\\..\\..\\x",
        path + "\x00", path + "\r\nX-Injected: 1", path + "\t", path + "\x7f",
        path + joined + "url=http%3A%2F%2Fevil.example.com%2Fx.png",
        path + joined + "url=/:/scrobble",
        path + "?", path + "#fragment", part + ";jsessionid=1" + (("?" + query) if query else ""),
        path + joined + "a=%ff",
        part.upper() + (("?" + query) if query else ""),
    ]
    if query:
        first = query.split("&")[0]
        bent += [path + "&" + first, path + "&" + first.split("=")[0] + "=1", path + "?x=1", path + "&", path + "&=1", path + "&novalue"]
    return [one for one in bent if one != path]


# -- the guard ----------------------------------------------------------------------


async def test_every_adapter_that_hands_out_pictures_names_their_shapes_and_nothing_more() -> None:
    offering = {adapter.kind for adapter in all_adapters() if _offers_pictures(adapter)}
    assert offering == PICTURE_ADAPTERS, (
        "an adapter hands out pictures through the image route; give it image_paths and name it here with its real paths"
        if offering - PICTURE_ADAPTERS else "an adapter here no longer hands out pictures")
    for adapter in all_adapters():
        if adapter.kind not in offering:
            assert not adapter.image_paths, f"{adapter.kind} names picture shapes but hands out no pictures"
            continue
        assert adapter.image_paths and all(isinstance(shape, ImagePath) for shape in adapter.image_paths), f"{adapter.kind} has no image_paths"
        paths = await real_paths(adapter.kind) + _demo_paths(adapter)
        assert paths, f"no real paths of {adapter.kind} to check"
        for path in paths:
            assert image_path(adapter, path) == path, f"{adapter.kind} refuses or rewrites its own picture {path!r}"
        for path in DANGEROUS + KNOWN_HARM.get(adapter.kind, []) + [bent for real in paths for bent in _bent(real)]:
            with pytest.raises(AdapterError) as refused:
                image_path(adapter, path)
            assert refused.value.code == "bad_path", (adapter.kind, path)


def test_the_list_of_known_harm_names_only_adapters_with_pictures() -> None:
    assert set(KNOWN_HARM) == PICTURE_ADAPTERS


def test_an_adapter_without_a_list_hands_out_no_pictures_at_all() -> None:
    class Quiet(Adapter):
        kind = "quiet"
        label = "Quiet"

    for path in ("/x.png", "/library/metadata/10/thumb/1", "/Items/m1/Images/Primary?maxHeight=400"):
        with pytest.raises(AdapterError) as refused:
            image_path(Quiet(), path)
        assert refused.value.code == "bad_path"
    for kind in ("radarr", "sonarr", "docker", "proxmox", "homeassistant"):
        with pytest.raises(AdapterError):
            image_path(get_adapter(kind), "/x.png")


def test_a_checked_path_is_put_together_again_from_what_was_checked() -> None:
    plex = get_adapter("plex")
    sent = "/photo/:/transcode?width=240&height=240&minSize=1&upscale=1&url=%2Flibrary%2Fmetadata%2F5%2Fthumb%2F17"
    assert image_path(plex, sent) == sent
    # Encoded where it need not be: the same picture, written the one way it goes out.
    assert image_path(plex, "/photo/:/transcode?w%69dth=240&url=%2Flibrary%2Fmetadata%2F5%2Fthumb%2F17") == (
        "/photo/:/transcode?width=240&url=%2Flibrary%2Fmetadata%2F5%2Fthumb%2F17")
    assert image_path(get_adapter("jellyfin"), "/Items/m1/Images/Primary?quality=9%30") == "/Items/m1/Images/Primary?quality=90"
    with pytest.raises(AdapterError):
        image_path(plex, "/photo/:/transcode?width=240&url=/library/metadata/5/thumb/17")


def test_the_normalisation_holds_even_for_a_shape_that_is_too_loose() -> None:
    """A shape written carelessly (anything under /x, any value) still cannot be used to walk out of it or to smuggle a second reading."""
    class Loose(Adapter):
        kind = "loose"
        label = "Loose"
        image_paths = (ImagePath(r"/x/.*", q=r".*"),)

    loose = Loose()
    assert image_path(loose, "/x/a/b.png?q=1") == "/x/a/b.png?q=1"
    for path in ("/x/../etc", "/x/a/../../etc", "/x/./a", "/x//a", "/x/a/", "/x/%2e%2e/a", "/x/a%2Fb", "/x/a\b", "/x/a;b", "/x/a b", "/x/a\x00",
                 "/x/a\n", "/x/a#frag", "/x/a?", "/x/a?q=1&q=2", "/x/a?q=%252F", "/x/a?q=..%2Fetc", "/x/a?q=%2F%2Fevil.example.com", "/x/a?q=a%2F..%2Fb", "/x/a?q=%ff", "/x/a?q=a?b=c", "/x/a?q",
                 "/x/a?q=1&other=1", "/x/a?q=http%3A%2F%2Fevil.example.com%2F", "/x/a?q=a b", "//x/a", "/x/a@evil.example.com"):
        with pytest.raises(AdapterError) as refused:
            image_path(loose, path)
        assert refused.value.code == "bad_path", path


# -- the route -----------------------------------------------------------------------


def _plex_card(client: TestClient) -> dict:
    setup_admin(client)
    page = _board(client)["pages"][0]["id"]
    made = client.post("/api/v1/integrations", json={"kind": "plex", "name": "P", "config": {"url": "http://plex:32400", "token": "tok"}}, headers=CSRF).json()
    return _widget(client, page, kind="plex.recent", integration_id=made["id"])


@pytest.mark.parametrize("path", [
    "/:/scrobble?key=10&identifier=com.plexapp.plugins.library",
    "/library/sections/1/refresh",
    "/library/sections/all/refresh",
    "/library/metadata/10/thumb/1/../../../sections/1/refresh",
    "/library/metadata/10/thumb/1%2F..%2F..%2F..%2Fsections%2F1%2Frefresh",
    "/photo/:/transcode?width=240&url=%2F%3A%2Fscrobble%3Fkey%3D10",
])
def test_plex_never_hears_of_a_path_that_marks_watched_or_scans(client: TestClient, path: str, monkeypatch: pytest.MonkeyPatch) -> None:
    widget = _plex_card(client)
    asked: list[str] = []
    real = type(get_adapter("plex")).image_source

    async def spy(self: Adapter, config: dict, wanted: str, ctx: Context) -> Any:
        asked.append(wanted)
        return await real(self, config, wanted, ctx)

    monkeypatch.setattr(type(get_adapter("plex")), "image_source", spy)
    with respx.mock(assert_all_called=False) as mock:
        anything = mock.route(host="plex").mock(return_value=httpx.Response(200, content=b"\x89PNG", headers={"content-type": "image/png"}))
        refused = client.get(f"/api/v1/widgets/{widget['id']}/image", params={"path": path})
    assert refused.status_code == 400 and refused.json()["detail"]["code"] == "bad_path"
    assert anything.call_count == 0 and asked == [], "nothing went to Plex, not even through the adapter"


def test_a_cached_answer_is_no_way_around_the_check(client: TestClient) -> None:
    widget = _plex_card(client)
    smuggled = "/:/scrobble?key=10&identifier=com.plexapp.plugins.library"
    widgets_router._images[(widget["id"], smuggled)] = (time.monotonic() + 3600, b"\x89PNG", "image/png")
    try:
        assert client.get(f"/api/v1/widgets/{widget['id']}/image", params={"path": smuggled}).status_code == 400
    finally:
        widgets_router._images.pop((widget["id"], smuggled), None)


def test_a_plex_cover_still_goes_through_the_scaler_with_its_thumb(client: TestClient) -> None:
    widget = _plex_card(client)
    art, _ = get_adapter("plex")._cover("/library/metadata/5/thumb/17")
    with respx.mock:
        scaler = respx.get("http://plex:32400/photo/:/transcode").mock(return_value=httpx.Response(200, content=b"\x89PNG", headers={"content-type": "image/png"}))
        answer = client.get(f"/api/v1/widgets/{widget['id']}/image", params={"path": art[len("proxy:"):]})
    assert answer.status_code == 200 and answer.content == b"\x89PNG"
    sent = scaler.calls.last.request
    assert sent.url.params["url"] == "/library/metadata/5/thumb/17" and sent.url.params["width"] == "800"
    assert sent.headers["X-Plex-Token"] == "tok"


def test_a_connection_whose_adapter_names_no_pictures_fetches_none(client: TestClient) -> None:
    setup_admin(client)
    page = _board(client)["pages"][0]["id"]
    made = client.post("/api/v1/integrations", json={"kind": "radarr", "name": "R", "config": {"url": "http://radarr:7878", "api_key": "key"}}, headers=CSRF).json()
    widget = _widget(client, page, kind="radarr.queue", integration_id=made["id"])
    with respx.mock(assert_all_called=False) as mock:
        anything = mock.route(host="radarr").mock(return_value=httpx.Response(200, content=b"\x89PNG", headers={"content-type": "image/png"}))
        refused = client.get(f"/api/v1/widgets/{widget['id']}/image", params={"path": "/api/v3/command"})
        poster = client.get(f"/api/v1/widgets/{widget['id']}/image", params={"path": "/MediaCover/1/poster.jpg"})
    assert refused.status_code == 400 and poster.status_code == 400 and anything.call_count == 0


@respx.mock
def test_a_reolink_reboot_never_reaches_the_device(client: TestClient) -> None:
    setup_admin(client)
    page = _board(client)["pages"][0]["id"]
    made = client.post("/api/v1/integrations", json={"kind": "reolink", "name": "Cams", "config": {"url": "http://cam", "username": "nexdeck", "password": "pw"}}, headers=CSRF).json()
    widget = _widget(client, page, kind="reolink.camera", integration_id=made["id"], options={"channel": 1})
    device = respx.route(host="cam").mock(return_value=httpx.Response(200, json=[]))
    for path in ("/cgi-bin/api.cgi?cmd=Reboot", "/snap/1/main?cmd=Reboot", "/snap/1/../../cgi-bin/api.cgi"):
        assert client.get(f"/api/v1/widgets/{widget['id']}/image", params={"path": path}).status_code == 400
    assert device.call_count == 0, "not even the login went out"
