"""MeTube, whose answers do not mean what their status code says.

Every expectation here comes from a live MeTube 2026.08.28 with yt-dlp
2026.08.19 (08.09.2026), not from its README.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, Context

METUBE = "http://metube.example.com"
CONFIG = {"url": METUBE}

#: Nanoseconds, which is what MeTube writes.
NEWER = 1_788_898_037_170_208_067
OLDER = 1_788_800_000_000_000_000


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


def _history(**lists: object) -> None:
    respx.get(f"{METUBE}/history").mock(return_value=httpx.Response(200, json={
        "queue": [], "pending": [], "done": [], **lists,
    }))


#: ⚠️ Every row carries an ``id`` **and** a differing ``url``, because that is
#: what a real MeTube hands over, and the difference is the whole point of
#: ``_key``: its lists are kept under the address while ``id`` is the video's
#: own identifier. These fixtures used to carry only the ``id``, so the
#: adapter's fallback made every test here pass while the buttons pressed
#: nothing at all on a live instance.
DOWNLOADING = {"id": "aBc", "url": "https://videos.example.com/watch?v=aBc",
               "title": "How a lock works", "status": "downloading",
               "percent": 42.0, "speed": 2_400_000, "eta": 40}
#: ⚠️ Measured: an entry sits here with no percentage at all before it starts.
PREPARING = {"id": "dEf", "url": "https://videos.example.com/watch?v=dEf",
             "title": "A workbench", "status": "preparing"}
FINISHED = {"id": "gHi", "url": "https://videos.example.com/watch?v=gHi",
            "title": "Soldering", "status": "finished", "filename": "Soldering.webm",
            "size": 184_000_000, "timestamp": NEWER}
FAILED = {"id": "jKl", "url": "https://videos.example.com/watch?v=jKl",
          "title": "Not a video", "status": "error", "timestamp": OLDER,
          "filename": "Not a video.webm",
          "msg": "ERROR: [generic] not-a-video: Unable to download webpage: HTTP Error 404\nsecond line"}


@respx.mock
async def test_the_count_card_separates_failed_from_done(ctx: Context) -> None:
    """⚠️ ``done`` is not "finished": a failure lands there and stays."""
    _history(queue=[DOWNLOADING], pending=[PREPARING], done=[FINISHED, FAILED])
    data = await get_adapter("metube").fetch("counts", CONFIG, {}, ctx)
    assert data.primary == {"label": "Running", "value": 2}
    assert data.secondary == [{"label": "Done", "value": 1}, {"label": "Failed", "value": 1}]
    assert data.metrics == {"running": 2.0, "failed": 1.0}
    assert data.status == "bad"


@respx.mock
async def test_a_quiet_metube_is_calm(ctx: Context) -> None:
    _history(done=[FINISHED])
    data = await get_adapter("metube").fetch("counts", CONFIG, {}, ctx)
    assert (data.status, data.primary["value"]) == ("ok", 0)


@respx.mock
async def test_the_list_shows_progress_waiting_and_what_went_wrong(ctx: Context) -> None:
    _history(queue=[DOWNLOADING], pending=[PREPARING], done=[FAILED, FINISHED])
    data = await get_adapter("metube").fetch("downloads", CONFIG, {"limit": 8, "show": "all"}, ctx)
    assert [(row["title"], row["subtitle"], row["status"]) for row in data.items] == [
        ("How a lock works", "42% · 2.3 MB/s · 40s left", "warn"),
        ("A workbench", "Preparing", "warn"),
        # Newest first, and only the first line of yt-dlp's several.
        ("Soldering", "175.5 MB", "ok"),
        ("Not a video", "ERROR: [generic] not-a-video: Unable to download webpage: HTTP Error 404", "bad"),
    ]
    assert [row["progress"] for row in data.items] == [42.0, 0.0, None, None]


@respx.mock
async def test_a_row_with_nothing_to_show_yet_is_named_in_our_own_words(ctx: Context) -> None:
    """⚠️ Not MeTube's word with a capital letter on it. Cards translate what an
    adapter writes by looking the English up, so a word taken straight from the
    service is a word no translation file has: "Preparing" stood in English on
    a German board while every row around it was translated."""
    _history(pending=[{"id": "mNo", "title": "Later", "status": "pending"},
                      {"id": "pQr", "title": "Odd", "status": "something-new"}])
    data = await get_adapter("metube").fetch("downloads", CONFIG, {"limit": 8, "show": "busy"}, ctx)
    assert [row["subtitle"] for row in data.items] == ["Waiting", "Waiting"]


@respx.mock
async def test_only_a_failed_row_offers_to_try_again(ctx: Context) -> None:
    _history(queue=[DOWNLOADING], done=[FAILED, FINISHED])
    data = await get_adapter("metube").fetch("downloads", CONFIG, {"limit": 8, "show": "all"}, ctx)
    offered = {row["title"]: [one["id"] for one in row["actions"]] for row in data.items}
    assert offered == {
        "How a lock works": ["remove"],
        "Soldering": ["remove"],
        "Not a video": ["retry", "remove"],
    }
    assert [one["params"] for one in data.items[0]["actions"]] == [
        {"where": "queue", "id": "https://videos.example.com/watch?v=aBc"}]


@respx.mock
async def test_a_button_names_the_row_the_way_metube_files_it(ctx: Context) -> None:
    """⚠️ The address, not the ``id`` MeTube prints beside it.

    Measured on 09.09.2026 against a live instance: ``POST /delete`` with the
    ``id`` answers ``{"status": "ok"}`` and removes nothing. The card reported
    a removal on every press and the row stayed. It survived the first round of
    these tests because the fixtures carried no ``url`` at all, so the
    adapter's fallback quietly made the wrong thing look right.
    """
    _history(queue=[DOWNLOADING], done=[FAILED])
    data = await get_adapter("metube").fetch("downloads", CONFIG, {"limit": 8, "show": "all"}, ctx)
    named = [(row["title"], one["id"], one["params"]["id"]) for row in data.items for one in row["actions"]]
    assert named == [
        ("How a lock works", "remove", "https://videos.example.com/watch?v=aBc"),
        ("Not a video", "retry", "https://videos.example.com/watch?v=jKl"),
        ("Not a video", "remove", "https://videos.example.com/watch?v=jKl"),
    ]


@respx.mock
async def test_the_list_can_be_narrowed_to_what_is_running(ctx: Context) -> None:
    _history(queue=[DOWNLOADING], pending=[PREPARING], done=[FINISHED, FAILED])
    metube = get_adapter("metube")
    busy = await metube.fetch("downloads", CONFIG, {"limit": 8, "show": "busy"}, ctx)
    over = await metube.fetch("downloads", CONFIG, {"limit": 8, "show": "done"}, ctx)
    assert [row["title"] for row in busy.items] == ["How a lock works", "A workbench"]
    assert [row["title"] for row in over.items] == ["Soldering", "Not a video"]


@respx.mock
async def test_the_field_card_offers_the_button_and_what_it_started(ctx: Context) -> None:
    _history(queue=[DOWNLOADING], done=[FINISHED])
    data = await get_adapter("metube").fetch(
        "fetch", CONFIG, {"what": "video", "quality": "720", "format": "mp4", "show_running": True}, ctx)
    assert [one.id for one in data.actions] == ["add"]
    action = data.actions[0]
    assert action.params == {"download_type": "video", "quality": "720", "format": "mp4"}
    assert action.ask is not None and action.ask.name == "url" and action.ask.kind == "url"
    # Only what is running: the history belongs on the other card.
    assert [row["title"] for row in data.items] == ["How a lock works"]


@respx.mock
async def test_audio_only_asks_for_no_resolution(ctx: Context) -> None:
    """⚠️ A quality of "720" with download_type "audio" is a setting that
    cannot mean anything, and the field for it is hidden in the sheet."""
    _history()
    data = await get_adapter("metube").fetch(
        "fetch", CONFIG, {"what": "audio", "quality": "720", "format": "mp3"}, ctx)
    assert data.actions[0].params == {"download_type": "audio", "quality": "best", "format": "mp3"}


@respx.mock
async def test_the_field_card_can_be_told_to_show_nothing_but_the_field(ctx: Context) -> None:
    _history(queue=[DOWNLOADING])
    data = await get_adapter("metube").fetch("fetch", CONFIG, {"show_running": False}, ctx)
    assert data.items == [] and [one.id for one in data.actions] == ["add"]


# -- the actions -------------------------------------------------------------


@respx.mock
async def test_a_failed_download_is_a_failure_however_the_status_code_reads(ctx: Context) -> None:
    """⚠️ The measurement this adapter exists around. MeTube answers HTTP 200
    and ``status: "error"`` in the same breath; a card that counts the status
    code tells somebody their download started when nothing did."""
    respx.post(f"{METUBE}/add").mock(return_value=httpx.Response(200, json={
        "status": "error",
        "msg": "ERROR: [generic] not-a-video: Unable to download webpage: HTTP Error 404\nsecond line",
    }))
    with pytest.raises(AdapterError) as refused:
        await get_adapter("metube").action(
            "fetch", "add", {"url": "https://videos.example.com/x"}, CONFIG, {}, ctx)
    assert refused.value.code == "rejected"
    assert "\n" not in refused.value.message


@respx.mock
async def test_an_address_that_was_already_queued_says_so(ctx: Context) -> None:
    """⚠️ Also HTTP 200, also ``status: "ok"``, and nothing was started. The
    button must not take credit for work it did not cause."""
    respx.post(f"{METUBE}/add").mock(return_value=httpx.Response(200, json={
        "status": "ok", "msg": "Already in queue: How a lock works"}))
    message = await get_adapter("metube").action(
        "fetch", "add", {"url": "https://videos.example.com/x"}, CONFIG, {}, ctx)
    assert message == "Already in queue: How a lock works"


@respx.mock
async def test_a_started_download_says_it_plainly(ctx: Context) -> None:
    route = respx.post(f"{METUBE}/add").mock(return_value=httpx.Response(200, json={"status": "ok"}))
    message = await get_adapter("metube").action(
        "fetch", "add",
        {"url": "https://videos.example.com/x", "download_type": "audio", "quality": "best", "format": "mp3"},
        CONFIG, {}, ctx)
    assert message == "MeTube is fetching it."
    assert json.loads(route.calls.last.request.read()) == {
        "url": "https://videos.example.com/x", "download_type": "audio",
        "quality": "best", "format": "mp3", "auto_start": True,
    }


@respx.mock
async def test_a_refusal_that_is_not_json_is_still_readable(ctx: Context) -> None:
    """Measured: an empty address comes back as plain text, not as JSON."""
    respx.post(f"{METUBE}/add").mock(return_value=httpx.Response(
        400, text="400: missing 'url', 'download_type', or 'quality'"))
    with pytest.raises(AdapterError) as refused:
        await get_adapter("metube").action("fetch", "add", {"url": "https://x.example.com"}, CONFIG, {}, ctx)
    assert refused.value.code == "http_error"
    assert "missing 'url'" in refused.value.message


@respx.mock
async def test_removing_and_retrying_use_the_shapes_metube_wants(ctx: Context) -> None:
    """⚠️ ``/delete`` takes a list under ``ids``; ``/retry`` takes one ``id``.
    Sending the list to ``/retry`` was refused with HTTP 400."""
    delete = respx.post(f"{METUBE}/delete").mock(return_value=httpx.Response(200, json={"status": "ok"}))
    retry = respx.post(f"{METUBE}/retry").mock(return_value=httpx.Response(200, json={"status": "ok"}))
    metube = get_adapter("metube")
    assert await metube.action("downloads", "remove", {"where": "queue", "id": "aBc"}, CONFIG, {}, ctx) == "Removed."
    assert await metube.action("downloads", "retry", {"id": "jKl"}, CONFIG, {}, ctx) == "Trying again."
    assert json.loads(delete.calls.last.request.read()) == {"where": "queue", "ids": ["aBc"]}
    assert json.loads(retry.calls.last.request.read()) == {"id": "jKl"}


@respx.mock
async def test_a_list_metube_does_not_have_is_refused(ctx: Context) -> None:
    with pytest.raises(AdapterError) as refused:
        await get_adapter("metube").action(
            "downloads", "remove", {"where": "../config", "id": "aBc"}, CONFIG, {}, ctx)
    assert refused.value.code == "no_such_action"


@respx.mock
async def test_the_connection_test_names_both_versions(ctx: Context) -> None:
    respx.get(f"{METUBE}/version").mock(return_value=httpx.Response(
        200, json={"yt-dlp": "2026.08.19", "version": "2026.08.28"}))
    _history(queue=[DOWNLOADING], done=[FINISHED])
    message = await get_adapter("metube").test(CONFIG, ctx)
    assert message == "MeTube 2026.08.28 with yt-dlp 2026.08.19 answers: 1 running, 1 in the history."
