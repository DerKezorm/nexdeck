"""PhotoPrism, against the answers of a live PhotoPrism 260728-bbde8f452 (11.09.2026)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context
from app.adapters.photoprism import PhotoPrismAdapter

PP = "http://photoprism.example.com:2342"
CONFIG = {"url": PP, "token": "aaaaaa-bbbbbb-cccccc-dddddd"}
#: Half a minute after the newest addition below.
NOW = datetime(2026, 9, 11, 22, 36, 40, tzinfo=UTC).timestamp()


def counts(**values: int) -> dict[str, int]:
    keys = ("all", "photos", "media", "animated", "live", "audio", "videos", "documents", "cameras", "lenses", "countries", "hidden", "archived",
            "favorites", "review", "stories", "private", "albums", "private_albums", "moments", "private_moments", "months", "private_months",
            "states", "private_states", "folders", "private_folders", "files", "people", "places", "labels", "labelMaxPhotos")
    return {key: values.get(key, 0) for key in keys}


#: Signed in: the counts after indexing the test files. Not signed in, or with a made-up password: the same 200, as a visitor.
USER = {"mode": "user", "name": "PhotoPrism", "edition": "plus", "version": "260728-bbde8f452-Linux-AMD64-Plus",
        "count": counts(all=1, photos=12, media=1, videos=1, review=12, folders=1, files=13)}
VISITOR = {"mode": "public", "name": "PhotoPrism", "edition": "plus", "version": "260728-bbde8f452-Linux-AMD64-Plus", "count": counts()}
REFUSED = {"code": 401, "error": "Please log in to your account", "messageId": "Please log in to your account"}


def photo(number: int, kind: str, title: str, added: str, taken: str = "2019-05-01T10:00:00Z") -> dict[str, Any]:
    """A row of ``/api/v1/photos?merged=true`` with the measured fields; ids and hashes are made up.

    A real photo was taken long before it came into the library, so the two times differ here.
    """
    return {"ID": f"{number}-{number + 1}", "UID": f"pt000000example{number:02d}", "Type": kind, "TypeSrc": "", "TakenAt": taken, "TakenAtLocal": taken,
            "TakenSrc": "", "TimeZone": "", "Path": "examples", "Name": f"file-{number}", "OriginalName": "", "Title": title, "Caption": "",
            "Year": -1, "Month": -1, "Day": -1, "Country": "zz", "Stack": 0, "Favorite": False, "Private": False, "Iso": 0, "FocalLength": 0,
            "FNumber": 0, "Exposure": "", "Quality": 1, "Resolution": 0, "Color": 9, "Scan": False, "Panorama": False, "CameraID": 1,
            "CameraModel": "Unknown", "LensID": 1, "LensModel": "Unknown", "Lat": 0, "Lng": 0, "CellID": "zz", "PlaceID": "zz", "PlaceSrc": "",
            "PlaceLabel": "Unknown", "PlaceCity": "Unknown", "PlaceState": "Unknown", "PlaceCountry": "zz", "FileUID": f"fs000000example{number:02d}",
            "FileRoot": "/", "FileName": f"examples/file-{number}.jpg", "Hash": f"{number:040d}", "Width": 640, "Height": 480, "Portrait": False,
            "Merged": True, "CreatedAt": added, "UpdatedAt": added, "EditedAt": "0001-01-01T00:00:00Z", "CheckedAt": added, "Files": []}


PHOTOS = [photo(13, "image", "Pattern", "2026-09-11T22:36:10Z"), photo(14, "video", "Clip", "2026-09-11T21:43:33Z"),
          photo(2, "live", "", "2026-09-10T08:00:00Z")]


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


@respx.mock
async def test_the_library_counts_with_the_index_button(ctx: Context) -> None:
    route = respx.get(f"{PP}/api/v1/config").mock(return_value=httpx.Response(200, json=USER))
    data = await get_adapter("photoprism").fetch("library", CONFIG, {}, ctx)
    assert route.calls.last.request.headers["Authorization"] == "Bearer aaaaaa-bbbbbb-cccccc-dddddd"
    assert data.primary == {"label": "Photos", "value": 12}
    assert data.secondary == [{"label": "Videos", "value": 1}, {"label": "In review", "value": 12}]
    assert data.metrics == {"photos": 12.0, "videos": 1.0}
    assert [(action.id, action.confirm) for action in data.actions] == [("index", True)]


@respx.mock
async def test_a_made_up_password_is_a_visitor_not_an_empty_library(ctx: Context) -> None:
    """⚠️ Measured: /api/v1/config answers 200 with every count at 0 for a password it does not know."""
    respx.get(f"{PP}/api/v1/config").mock(return_value=httpx.Response(200, json=VISITOR))
    with pytest.raises(AuthFailed) as refused:
        await get_adapter("photoprism").fetch("library", CONFIG, {}, ctx)
    assert "visitor" in refused.value.message


def test_recently_added_with_their_kind_and_age() -> None:
    data = PhotoPrismAdapter._recent([*PHOTOS, "not a photo"], NOW)
    assert [(row["title"], row["subtitle"], row["value"]) for row in data.items] == [
        ("Pattern", "Photo", "0 min"),
        ("Clip", "Video", "53 min"),
        ("file-2", "live", "1 d"),
    ]


@respx.mock
async def test_the_recent_card_asks_for_the_newest_additions(ctx: Context) -> None:
    route = respx.get(f"{PP}/api/v1/photos").mock(return_value=httpx.Response(200, json=PHOTOS[:2]))
    data = await get_adapter("photoprism").fetch("recent", CONFIG, {"limit": 2}, ctx)
    assert dict(route.calls.last.request.url.params) == {"count": "2", "offset": "0", "order": "added", "merged": "true"}
    assert len(data.items) == 2


@respx.mock
async def test_a_client_access_token_cannot_list_photos(ctx: Context) -> None:
    """⚠️ Measured: the counts work with such a token, every photo search answers 400."""
    respx.get(f"{PP}/api/v1/photos").mock(return_value=httpx.Response(400, json={"code": 400, "error": "Unable to do that", "messageId": "Unable to do that"}))
    with pytest.raises(AuthFailed) as refused:
        await get_adapter("photoprism").fetch("recent", CONFIG, {}, ctx)
    assert "app password" in refused.value.message


@respx.mock
async def test_indexing(ctx: Context) -> None:
    adapter = get_adapter("photoprism")
    route = respx.post(f"{PP}/api/v1/index").mock(return_value=httpx.Response(200, json={
        "code": 200, "message": "Indexing completed in 1 s", "messageId": "Indexing completed in %d s", "messageParams": [1]}))
    ctx.cache["resp:stale"] = (1e18, httpx.Response(200, json=USER))
    assert await adapter.action("library", "index", {}, CONFIG, {}, ctx) == "Indexing completed."
    assert json.loads(route.calls.last.request.content) == {"path": "/", "rescan": False, "cleanup": False}
    assert "resp:stale" not in ctx.cache
    route.mock(return_value=httpx.Response(500, json={"error": "Already running"}))
    with pytest.raises(AdapterError) as busy:
        await adapter.action("library", "index", {}, CONFIG, {}, ctx)
    assert busy.value.code == "action_failed" and "already" in busy.value.message
    route.mock(return_value=httpx.Response(200, json={"code": 200, "message": "Indexing canceled"}))
    with pytest.raises(AdapterError) as other:
        await adapter.action("library", "index", {}, CONFIG, {}, ctx)
    assert "did not say" in other.value.message
    route.mock(return_value=httpx.Response(401, json=REFUSED))
    with pytest.raises(AuthFailed):
        await adapter.action("library", "index", {}, CONFIG, {}, ctx)
    with pytest.raises(AdapterError) as unknown:
        await adapter.action("library", "rescan", {}, CONFIG, {}, ctx)
    assert unknown.value.code == "no_such_action"


@respx.mock
async def test_a_refused_password_on_the_photo_list(ctx: Context) -> None:
    respx.get(f"{PP}/api/v1/photos").mock(return_value=httpx.Response(401, json=REFUSED))
    with pytest.raises(AuthFailed) as refused:
        await get_adapter("photoprism").fetch("recent", CONFIG, {}, ctx)
    assert "rejected" in refused.value.message


@respx.mock
async def test_an_unreachable_server(ctx: Context) -> None:
    respx.get(f"{PP}/api/v1/config").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(AdapterError) as failure:
        await get_adapter("photoprism").fetch("library", CONFIG, {}, ctx)
    assert failure.value.code == "unreachable"


@respx.mock
async def test_another_service_on_the_address(ctx: Context) -> None:
    respx.get(f"{PP}/api/v1/config").mock(return_value=httpx.Response(200, json={"status": "ok"}))
    with pytest.raises(AdapterError) as other:
        await get_adapter("photoprism").fetch("library", CONFIG, {}, ctx)
    assert other.value.code == "not_photoprism"


@respx.mock
async def test_the_connection_test(ctx: Context) -> None:
    respx.get(f"{PP}/api/v1/config").mock(return_value=httpx.Response(200, json=USER))
    photos = respx.get(f"{PP}/api/v1/photos").mock(return_value=httpx.Response(200, json=PHOTOS[:1]))
    assert await get_adapter("photoprism").test(CONFIG, ctx) == "PhotoPrism 260728-bbde8f452-Linux-AMD64-Plus answers with 12 photos and 1 videos."
    # The photo list is asked too, so a client access token is caught at the test.
    assert photos.called
