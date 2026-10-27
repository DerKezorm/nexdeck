"""Stash, against the answers of Stash v0.31.1 (stashapp/stash, 27.10.2026).

The statistics, the job queue (null when idle, a running generate job with its
sub task and progress fraction, STOPPING after a stop), the 401 with no body and
the GraphQL error inside a 200 are the measured ones, from a Stash with three
generated test videos. The library is made up.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context, Unreachable, outbound_client

BASE = "http://stash.example.com:9999"
GRAPHQL = f"{BASE}/graphql"
CONFIG = {"url": BASE, "api_key": "a-made-up-key"}
OPEN = {"url": BASE}
ADAPTER = get_adapter("stash")


def fresh() -> Context:
    return Context(outbound_client(guard=False), integration_id=1, widget_id=1, cache={})


@pytest.fixture
def ctx() -> Context:
    return fresh()


STATS = {"scene_count": 1840, "scenes_size": 4.851177e+12, "scenes_duration": 912000, "image_count": 22610, "images_size": 103079215104, "gallery_count": 148,
         "performer_count": 410, "studio_count": 12, "tag_count": 95, "total_play_count": 3120, "total_play_duration": 250000, "scenes_played": 700}
RUNNING = [{"id": "3", "status": "RUNNING", "subTasks": ["Generating sprites for /data/sample-one.mp4"], "description": "Generating...", "progress": 0.1111111,
            "startTime": "2026-10-27T18:21:31.241Z", "error": None}]


def stash(data: dict, seen: list[httpx.Request] | None = None) -> respx.Route:
    def reply(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return httpx.Response(200, json={"data": data})
    return respx.post(GRAPHQL).mock(side_effect=reply)


@respx.mock
async def test_the_library_card_counts_scenes_and_images_and_says_how_much_space_and_time(ctx: Context) -> None:
    seen: list[httpx.Request] = []
    stash({"stats": STATS}, seen)
    data = await ADAPTER.fetch("library", CONFIG, {}, ctx)
    assert data.primary == {"label": "Scenes", "value": 1840}
    assert data.secondary == [{"label": "Images", "value": 22610}, {"label": "Galleries", "value": 148}, {"label": "Size", "value": "4.5 TB"},
                              {"label": "Length", "value": "10d 13h"}, {"label": "Plays", "value": 3120}, {"label": "Watched", "value": "2d 21h"}]
    assert data.metrics == {"scenes": 1840.0, "images": 22610.0}
    assert seen[0].headers["ApiKey"] == "a-made-up-key"
    assert "scene_count" in json.loads(seen[0].content)["query"]


@respx.mock
async def test_nothing_is_read_that_could_name_a_title_or_a_person(ctx: Context) -> None:
    seen: list[httpx.Request] = []
    stash({"stats": STATS, "jobQueue": None}, seen)
    await ADAPTER.fetch("library", CONFIG, {}, ctx)
    await ADAPTER.fetch("tasks", CONFIG, {}, fresh())
    for request in seen:
        query = json.loads(request.content)["query"]
        assert not any(word in query for word in ("findScenes", "findPerformers", "title", "name", "path", "performers"))


@respx.mock
async def test_an_empty_library_has_no_plays_row(ctx: Context) -> None:
    stash({"stats": {key: 0 for key in STATS}})
    data = await ADAPTER.fetch("library", CONFIG, {}, ctx)
    assert data.primary["value"] == 0 and not any(row["label"] in ("Plays", "Watched") for row in data.secondary)


@respx.mock
async def test_a_running_job_shows_its_file_and_progress_and_offers_stopping(ctx: Context) -> None:
    stash({"jobQueue": RUNNING})
    data = await ADAPTER.fetch("tasks", CONFIG, {}, ctx)
    assert data.items == [{"id": "3", "title": "Generating...", "subtitle": "Generating sprites for /data/sample-one.mp4", "progress": 11.1, "value": "11%", "status": "ok"}]
    assert data.metrics == {"running": 1.0} and data.secondary == [{"label": "Running", "value": 1}]
    assert [(action.id, action.confirm, action.danger) for action in data.actions] == [("scan", True, False), ("stop", True, False)]


@respx.mock
async def test_an_idle_stash_has_a_job_queue_of_null_and_still_offers_the_scan(ctx: Context) -> None:
    # Measured: jobQueue is null, not [], when nothing runs.
    stash({"jobQueue": None})
    data = await ADAPTER.fetch("tasks", CONFIG, {}, ctx)
    assert (data.items, data.status, data.meta["empty"], [a.id for a in data.actions]) == ([], "ok", "No task is running.", ["scan"])


def test_a_job_that_is_stopping_or_waiting_is_yellow_and_one_with_an_error_is_red() -> None:
    jobs = [{"id": "1", "status": "STOPPING", "description": "Scanning...", "progress": 0.5},
            {"id": "2", "status": "READY", "description": "Cleaning...", "progress": None},
            {"id": "3", "status": "RUNNING", "description": "Generating...", "progress": 2.0, "error": "ffmpeg failed"}]
    card = ADAPTER.tasks_card(jobs)
    assert [(item["status"], item["subtitle"], item["value"]) for item in card.items] == [("warn", "Stopping", "50%"), ("warn", "Waiting", "0%"), ("bad", "", "100%")]
    assert card.status == "bad"


@respx.mock
async def test_the_buttons_send_the_scan_and_the_stop_as_mutations(ctx: Context) -> None:
    seen: list[httpx.Request] = []
    stash({"metadataScan": "1", "stopAllJobs": True}, seen)
    assert await ADAPTER.action("tasks", "scan", {}, CONFIG, {}, ctx) == "Stash looks for new files."
    assert await ADAPTER.action("tasks", "stop", {}, CONFIG, {}, ctx) == "The tasks are stopping."
    assert [json.loads(request.content)["query"] for request in seen] == ["mutation { metadataScan(input: {}) }", "mutation { stopAllJobs }"]
    with pytest.raises(AdapterError) as failure:
        await ADAPTER.action("tasks", "wipe", {}, CONFIG, {}, ctx)
    assert failure.value.code == "no_such_action"


@respx.mock
async def test_the_test_names_the_version_and_the_number_of_scenes(ctx: Context) -> None:
    stash({"version": {"version": "v0.31.1"}, "stats": {"scene_count": 3}})
    assert await ADAPTER.test(CONFIG, ctx) == "Stash v0.31.1 answers, 3 scenes."
    assert await ADAPTER.running_version(CONFIG, fresh()) == "0.31.1"


@respx.mock
async def test_no_key_sends_no_header_and_a_401_says_what_is_missing(ctx: Context) -> None:
    seen: list[httpx.Request] = []
    stash({"stats": STATS}, seen)
    await ADAPTER.fetch("library", OPEN, {}, ctx)
    assert "apikey" not in seen[0].headers
    respx.post(GRAPHQL).mock(return_value=httpx.Response(401))
    with pytest.raises(AuthFailed) as failure:
        await ADAPTER.test(OPEN, fresh())
    assert "wants an API key" in str(failure.value)
    with pytest.raises(AuthFailed) as failure:
        await ADAPTER.test(CONFIG, fresh())
    assert "rejected the API key" in str(failure.value)


@respx.mock
async def test_an_error_inside_a_200_is_an_error_and_something_else_at_the_address_is_not_stash(ctx: Context) -> None:
    respx.post(GRAPHQL).mock(return_value=httpx.Response(200, json={"errors": [{"message": "Internal system error. Error <runtime error: invalid memory address>",
                                                                                "path": ["stats"]}], "data": None}))
    with pytest.raises(AdapterError) as failure:
        await ADAPTER.fetch("library", CONFIG, {}, ctx)
    assert failure.value.code == "graphql_error" and "invalid memory address" in str(failure.value)
    respx.post(GRAPHQL).mock(return_value=httpx.Response(404, text="nothing"))
    with pytest.raises(AdapterError) as failure:
        await ADAPTER.test(CONFIG, fresh())
    assert failure.value.code == "not_stash"
    respx.post(GRAPHQL).mock(return_value=httpx.Response(200, json={"hello": "world"}))
    with pytest.raises(AdapterError) as failure:
        await ADAPTER.test(CONFIG, fresh())
    assert failure.value.code == "not_stash"
    respx.post(GRAPHQL).mock(return_value=httpx.Response(200, text="<html></html>"))
    with pytest.raises(AdapterError) as failure:
        await ADAPTER.test(CONFIG, fresh())
    assert failure.value.code == "not_json"


@respx.mock
async def test_an_unreachable_stash(ctx: Context) -> None:
    respx.post(GRAPHQL).mock(side_effect=httpx.ConnectError("connection refused"))
    with pytest.raises(Unreachable):
        await ADAPTER.fetch("library", CONFIG, {}, ctx)


def test_the_demo_fills_every_card() -> None:
    for tick in range(0, 400, 15):
        assert ADAPTER.demo("library", {}, tick).primary
        assert ADAPTER.demo("tasks", {}, tick).actions
    assert any(ADAPTER.demo("tasks", {}, tick).items for tick in range(0, 400, 15))
