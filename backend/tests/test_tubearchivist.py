"""Tube Archivist, against the answers of a live Tube Archivist v0.5.12 (11.09.2026)."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context
from app.adapters.tubearchivist import TubeArchivistAdapter

TA = "http://tubearchivist.example.com:8000"
CONFIG = {"url": TA, "token": "made-up-token"}
NOW = 1789162200.0


def paginate(total: int, params: str) -> dict[str, Any]:
    return {"page_size": 25, "page_from": 0, "prev_pages": None, "current_page": 0, "max_hits": False, "params": params,
            "last_page": 0, "next_pages": [], "total_hits": total}


#: ``/api/download/?filter=pending`` with the measured shape; title, channel and ids are made up.
QUEUE = {"data": [{"auto_start": False, "channel_id": "UC000000000000000000example", "channel_indexed": False, "channel_name": "Example Space Center",
                   "duration": "14s", "published": "2007-06-27T15:00:31+00:00", "status": "pending", "timestamp": 1789162127,
                   "title": "The Big Bang in fourteen seconds", "vid_thumb_url": "/cache/videos/e/example0001.jpg", "vid_type": "videos",
                   "youtube_id": "example0001", "_index": "ta_download", "_score": 0}],
         "paginate": paginate(1, "filter=pending")}
EMPTY_QUEUE = {"data": [], "paginate": paginate(0, "filter=pending")}
#: While the download runs, and once it is done: then no progress at all.
RUNNING = [{"id": "task-2", "title": "Downloading", "group": "download:run", "api_start": True, "api_stop": True, "level": "info",
            "messages": ["Processing Video: The Big Bang in fourteen seconds", "Validate download format"], "progress": 0.0, "command": None},
           {"id": "task-1", "title": "Add to download queue", "group": "download:add", "api_start": False, "api_stop": True, "level": "info",
            "messages": ["Adding new videos to the queue completed.", "Added 1 videos."], "progress": 0.0, "command": None}]
DONE = [{"id": "task-2", "title": "Downloading", "group": "download:run", "api_start": True, "api_stop": True, "level": "info",
         "messages": ["Task completed"], "command": None}]


def video(number: int, title: str, channel: str, downloaded: float) -> dict[str, Any]:
    return {"active": True, "category": ["Science & Technology"], "channel": {"channel_id": f"UC{number:022d}", "channel_active": True, "channel_name": channel,
            "channel_subs": 1000, "channel_subscribed": False}, "comment_count": None, "date_downloaded": int(downloaded), "description": None,
            "media_size": 770605, "media_url": f"/youtube/UC{number:022d}/example{number:04d}.mp4", "player": {"watched": False, "duration": 14, "duration_str": "14s"},
            "playlist": [], "published": "2007-06-27T15:00:31+00:00", "sponsorblock": None, "stats": {"view_count": 1, "like_count": 0, "dislike_count": 0, "average_rating": None},
            "streams": [], "subtitles": [], "tags": [], "title": title, "vid_last_refresh": "2026-09-11T21:29:06+00:00",
            "vid_thumb_url": f"/cache/videos/e/example{number:04d}.jpg", "vid_type": "videos", "youtube_id": f"example{number:04d}", "_index": "ta_video", "_score": 0}


VIDEOS = {"data": [video(1, "The Big Bang in fourteen seconds", "Example Space Center", NOW - 55),
                   video(2, "Sharpening a chisel", "Example Workshop", NOW - 3 * 3600)],
          "paginate": paginate(14, "sort=downloaded&order=desc")}


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


@respx.mock
async def test_the_queue_with_the_button_that_starts_the_downloads(ctx: Context) -> None:
    route = respx.get(f"{TA}/api/download/").mock(return_value=httpx.Response(200, json=QUEUE))
    respx.get(f"{TA}/api/notification/").mock(return_value=httpx.Response(200, json=[]))
    data = await get_adapter("tubearchivist").fetch("queue", CONFIG, {}, ctx)
    request = route.calls.last.request
    assert request.headers["Authorization"] == "Token made-up-token" and dict(request.url.params) == {"filter": "pending"}
    assert [(row["title"], row["subtitle"], row["value"]) for row in data.items] == [("The Big Bang in fourteen seconds", "Example Space Center", "14s")]
    assert data.secondary == [{"label": "Queue", "value": 1}] and data.metrics == {"queued": 1.0}
    assert [action.id for action in data.actions] == ["start_downloads"] and data.actions[0].confirm is True


def test_a_running_download_shows_how_far_it_is_and_hides_the_button() -> None:
    running = TubeArchivistAdapter._queue(QUEUE, RUNNING, {})
    assert running.secondary == [{"label": "Queue", "value": 1}, {"label": "Downloading", "value": "0%"}] and running.actions == []
    almost = TubeArchivistAdapter._queue(QUEUE, [{**RUNNING[0], "progress": 1.0}], {})
    assert almost.secondary[1] == {"label": "Downloading", "value": "100%"}
    # A finished entry stays for a while without progress; the one that adds to the queue is not a download.
    finished = TubeArchivistAdapter._queue(QUEUE, [*DONE, RUNNING[1]], {})
    assert finished.secondary == [{"label": "Queue", "value": 1}] and [action.id for action in finished.actions] == ["start_downloads"]
    empty = TubeArchivistAdapter._queue(EMPTY_QUEUE, [], {})
    assert empty.items == [] and empty.actions == [] and empty.meta["empty"] == "Nothing waits to be downloaded."


def test_the_latest_videos_with_their_channel() -> None:
    data = TubeArchivistAdapter._videos(VIDEOS, {"limit": 8}, NOW)
    assert [(row["title"], row["subtitle"], row["value"]) for row in data.items] == [
        ("The Big Bang in fourteen seconds", "Example Space Center", "0 min"),
        ("Sharpening a chisel", "Example Workshop", "3 h"),
    ]
    # All the archive holds, not the rows of this page.
    assert data.secondary == [{"label": "Videos", "value": 14}]
    assert len(TubeArchivistAdapter._videos(VIDEOS, {"limit": 1}, NOW).items) == 1


@respx.mock
async def test_the_videos_card_asks_for_the_newest_download_first(ctx: Context) -> None:
    route = respx.get(f"{TA}/api/video/").mock(return_value=httpx.Response(200, json=VIDEOS))
    await get_adapter("tubearchivist").fetch("videos", CONFIG, {}, ctx)
    assert dict(route.calls.last.request.url.params) == {"sort": "downloaded", "order": "desc"}


@respx.mock
async def test_the_summary_reads_null_as_nothing_waiting(ctx: Context) -> None:
    """⚠️ Measured: with an empty queue every download count is null."""
    # The shape as measured; the counts are made up so that no two of them are alike.
    respx.get(f"{TA}/api/stats/video/").mock(return_value=httpx.Response(200, json={
        "doc_count": 5, "media_size": 3853025, "duration": 70, "duration_str": "1m 10s", "type_videos": {"doc_count": 5}, "type_shorts": None,
        "type_streams": None, "active_true": {"doc_count": 5}, "active_false": None}))
    respx.get(f"{TA}/api/stats/channel/").mock(return_value=httpx.Response(200, json={
        "doc_count": 2, "active_true": 2, "active_false": None, "subscribed_true": None, "subscribed_false": 2}))
    downloads = respx.get(f"{TA}/api/stats/download/").mock(return_value=httpx.Response(200, json={
        "pending": None, "ignore": None, "pending_videos": None, "pending_shorts": None, "pending_streams": None}))
    data = await get_adapter("tubearchivist").fetch("summary", CONFIG, {}, ctx)
    assert data.primary == {"label": "Videos", "value": 5}
    assert data.secondary == [{"label": "Channels", "value": 2}, {"label": "Queue", "value": 0}]
    assert data.metrics == {"videos": 5.0, "queued": 0.0}
    downloads.mock(return_value=httpx.Response(200, json={"pending": 1, "ignore": None, "pending_videos": 1, "pending_shorts": None, "pending_streams": None}))
    ctx.cache.clear()
    assert (await get_adapter("tubearchivist").fetch("summary", CONFIG, {}, ctx)).secondary[1] == {"label": "Queue", "value": 1}


@respx.mock
async def test_starting_the_downloads(ctx: Context) -> None:
    adapter = get_adapter("tubearchivist")
    route = respx.post(f"{TA}/api/task/by-name/download_pending/").mock(return_value=httpx.Response(200, json={
        "task_id": "00000000-0000-4000-8000-000000000002", "status": "PENDING"}))
    ctx.cache["resp:stale"] = (1e18, httpx.Response(200, json=QUEUE))
    assert await adapter.action("queue", "start_downloads", {}, CONFIG, {}, ctx) == "Downloads started."
    assert route.calls.last.request.headers["Authorization"] == "Token made-up-token" and json.loads(route.calls.last.request.content) == {}
    assert "resp:stale" not in ctx.cache
    route.mock(return_value=httpx.Response(200, json={"message": "nothing"}))
    with pytest.raises(AdapterError) as nothing:
        await adapter.action("queue", "start_downloads", {}, CONFIG, {}, ctx)
    assert nothing.value.code == "action_failed"
    route.mock(return_value=httpx.Response(403, json={"detail": "Invalid token."}))
    with pytest.raises(AuthFailed):
        await adapter.action("queue", "start_downloads", {}, CONFIG, {}, ctx)
    with pytest.raises(AdapterError) as unknown:
        await adapter.action("queue", "delete_queue", {}, CONFIG, {}, ctx)
    assert unknown.value.code == "no_such_action"


@respx.mock
async def test_a_made_up_token_and_a_missing_one(ctx: Context) -> None:
    """⚠️ Measured: both get 403; a Bearer token counts as none."""
    adapter = get_adapter("tubearchivist")
    route = respx.get(f"{TA}/api/video/")
    for detail, words in (("Invalid token.", "rejected"), ("Authentication credentials were not provided.", "saw no")):
        route.mock(return_value=httpx.Response(403, json={"detail": detail}))
        ctx.cache.clear()
        with pytest.raises(AuthFailed) as refused:
            await adapter.fetch("videos", CONFIG, {}, ctx)
        assert words in refused.value.message


@respx.mock
async def test_an_unreachable_server(ctx: Context) -> None:
    respx.get(f"{TA}/api/download/").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(AdapterError) as failure:
        await get_adapter("tubearchivist").fetch("queue", CONFIG, {}, ctx)
    assert failure.value.code == "unreachable"


@respx.mock
async def test_another_service_on_the_address(ctx: Context) -> None:
    adapter = get_adapter("tubearchivist")
    respx.get(f"{TA}/api/ping/").mock(return_value=httpx.Response(200, json={"status": "ok"}))
    with pytest.raises(AdapterError) as other:
        await adapter.test(CONFIG, ctx)
    assert other.value.code == "not_tubearchivist"
    respx.get(f"{TA}/api/video/").mock(return_value=httpx.Response(200, json={"results": []}))
    with pytest.raises(AdapterError) as shape:
        await adapter.fetch("videos", CONFIG, {}, ctx)
    assert shape.value.code == "not_tubearchivist"


@respx.mock
async def test_the_connection_test(ctx: Context) -> None:
    respx.get(f"{TA}/api/ping/").mock(return_value=httpx.Response(200, json={"response": "pong", "user": 1, "version": "v0.5.12", "ta_update": None}))
    assert await get_adapter("tubearchivist").test(CONFIG, ctx) == "Tube Archivist v0.5.12 answers."
