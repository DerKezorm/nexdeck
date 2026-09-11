"""autobrr, against the answers of a live autobrr 1.86.0 (11.09.2026).

The releases below are the API's own serialisation of releases written into
that instance's database: one pushed, one the client rejected, one whose push
failed, and one no filter matched.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context

AB = "http://autobrr.example.com"
CONFIG = {"url": AB, "api_key": "not-a-real-key"}


def release(identifier: int, name: str, filter_status: str, filter_name: str, size: int, pushes: list[str]) -> dict[str, Any]:
    return {
        "id": identifier, "filter_status": filter_status, "rejections": [],
        "indexer": {"id": 0, "name": "Tracker One", "identifier": "trackerone", "identifier_external": ""},
        "filter": filter_name, "protocol": "torrent", "implementation": "", "timestamp": "2026-09-11T07:29:14Z",
        "announce_type": "NEW", "type": 6, "info_url": "", "download_url": "", "group_id": "", "torrent_id": "",
        "name": name, "normalized_hash": "", "size": size, "title": name.split(".")[0], "sub_title": "", "category": "TV",
        "season": 0, "episode": 0, "year": 0, "month": 0, "day": 0, "resolution": "1080p", "source": "WEB", "codec": ["H.264"],
        "container": "", "hdr": [""], "group": "GROUP", "proper": False, "repack": False, "website": "", "hybrid": False,
        "edition": [""], "cut": [""], "media_processing": "", "origin": "", "uploader": "", "record_label": "", "pre_time": "",
        "action_status": [{"id": index, "status": status, "action": "qBittorrent main", "action_id": 0, "type": "QBITTORRENT",
                           "client": "qbittorrent", "filter": filter_name, "filter_id": 0, "rejections": [], "release_id": identifier,
                           "timestamp": "2026-09-11T07:30:14Z"} for index, status in enumerate(pushes)],
    }


FAILED = release(4, "Broken.Upload.2026.1080p.WEB-DL-NOGRP", "FILTER_APPROVED", "TV 1080p", 2_147_483_648, ["PUSH_ERROR"])
NO_MATCH = release(3, "Some.Show.S02E04.720p.WEB.h264-GROUP", "FILTER_REJECTED", "", 734_003_200, [])
REJECTED = release(2, "Another.Film.2026.2160p.UHD.BluRay.x265-TEAM", "FILTER_APPROVED", "Films 4K", 48_318_382_080, ["PUSH_REJECTED"])
PUSHED = release(1, "Some.Show.S02E05.1080p.WEB.h264-GROUP", "FILTER_APPROVED", "TV 1080p", 1_610_612_736, ["PUSH_APPROVED"])
#: Measured field for field; ``/api/release/stats`` counts since the first start.
STATS = {"total_count": 4, "filtered_count": 3, "filter_rejected_count": 1, "push_approved_count": 1, "push_rejected_count": 1, "push_error_count": 1}
FILTERS = [{"id": 2, "name": "Films 4K", "enabled": True, "priority": 0, "actions_count": 0, "actions_enabled_count": 0, "is_auto_updated": False},
           {"id": 3, "name": "Old filter", "enabled": False, "priority": 0, "actions_count": 0, "actions_enabled_count": 0, "is_auto_updated": False},
           {"id": 1, "name": "TV 1080p", "enabled": True, "priority": 0, "actions_count": 0, "actions_enabled_count": 0, "is_auto_updated": False}]


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


@respx.mock
async def test_each_release_says_what_became_of_it(ctx: Context) -> None:
    route = respx.get(f"{AB}/api/release").mock(return_value=httpx.Response(200, json={"data": [FAILED, NO_MATCH, REJECTED, PUSHED], "count": 4, "next_cursor": 1}))
    data = await get_adapter("autobrr").fetch("releases", CONFIG, {"limit": 8}, ctx)
    sent = route.calls.last.request
    assert sent.headers["X-API-Token"] == "not-a-real-key" and dict(sent.url.params) == {"limit": "8"}
    # autobrr's order is kept: it hands them out newest first by arrival.
    assert [(row["status"], row["subtitle"]) for row in data.items] == [
        ("bad", "Push failed · TV 1080p · Tracker One · 2.0 GB"),
        ("unknown", "No match · Tracker One · 700.0 MB"),
        ("warn", "Rejected · Films 4K · Tracker One · 45.0 GB"),
        ("ok", "Pushed · TV 1080p · Tracker One · 1.5 GB"),
    ]
    assert data.items[0]["title"] == "Broken.Upload.2026.1080p.WEB-DL-NOGRP"
    assert data.items[0]["value"].endswith((" min", " h", " d"))
    assert data.secondary == [{"label": "Releases", "value": 4}]


@respx.mock
async def test_the_worst_push_speaks_for_a_release(ctx: Context) -> None:
    both = release(5, "Two.Actions.1080p", "FILTER_APPROVED", "TV 1080p", 1, ["PUSH_APPROVED", "PUSH_ERROR"])
    respx.get(f"{AB}/api/release").mock(return_value=httpx.Response(200, json={"data": [both], "count": 1, "next_cursor": 0}))
    data = await get_adapter("autobrr").fetch("releases", CONFIG, {"limit": 8}, ctx)
    assert data.items[0]["status"] == "bad" and data.items[0]["subtitle"].startswith("Push failed")


@respx.mock
async def test_only_pushed_releases_are_asked_of_autobrr(ctx: Context) -> None:
    route = respx.get(f"{AB}/api/release").mock(return_value=httpx.Response(200, json={"data": [PUSHED], "count": 1, "next_cursor": 0}))
    await get_adapter("autobrr").fetch("releases", CONFIG, {"limit": 5, "pushed_only": True}, ctx)
    assert route.calls.last.request.url.params["push_status"] == "PUSH_APPROVED"


@respx.mock
async def test_old_errors_do_not_colour_the_summary(ctx: Context) -> None:
    """⚠️ The counts never reset, so an error from weeks ago must not keep the card red."""
    respx.get(f"{AB}/api/release/stats").mock(return_value=httpx.Response(200, json=STATS))
    respx.get(f"{AB}/api/filters").mock(return_value=httpx.Response(200, json=FILTERS))
    data = await get_adapter("autobrr").fetch("summary", CONFIG, {}, ctx)
    assert data.primary == {"label": "Pushed", "value": 1}
    assert data.secondary == [{"label": "Filters on", "value": 2}, {"label": "Releases", "value": 4},
                              {"label": "Rejected", "value": 1}, {"label": "Errors", "value": 1}]
    assert data.status == "ok" and "notice" not in data.meta


@respx.mock
async def test_no_filter_switched_on_is_the_one_warning(ctx: Context) -> None:
    respx.get(f"{AB}/api/release/stats").mock(return_value=httpx.Response(200, json=STATS))
    respx.get(f"{AB}/api/filters").mock(return_value=httpx.Response(200, json=[{**one, "enabled": False} for one in FILTERS]))
    data = await get_adapter("autobrr").fetch("summary", CONFIG, {}, ctx)
    assert data.status == "warn"
    assert data.meta["notice"] == "No filter is switched on, so autobrr grabs nothing."


@respx.mock
async def test_the_connection_test_counts_filters(ctx: Context) -> None:
    respx.get(f"{AB}/api/config").mock(return_value=httpx.Response(200, json={"version": "v1.86.0", "database": "sqlite", "port": 7474}))
    respx.get(f"{AB}/api/filters").mock(return_value=httpx.Response(200, json=FILTERS))
    assert await get_adapter("autobrr").test(CONFIG, ctx) == "autobrr v1.86.0 answers with 3 filters, 2 switched on."


@respx.mock
@pytest.mark.parametrize(("code", "text"), [(401, "Unauthorized\n"), (403, "Forbidden\n")])
async def test_a_wrong_or_missing_key_is_refused(ctx: Context, code: int, text: str) -> None:
    """Measured: a wrong key gets 401, no key at all 403, both as plain text."""
    respx.get(f"{AB}/api/config").mock(return_value=httpx.Response(code, text=text))
    with pytest.raises(AuthFailed):
        await get_adapter("autobrr").test(CONFIG, ctx)


@respx.mock
async def test_another_service_on_the_address(ctx: Context) -> None:
    respx.get(f"{AB}/api/release").mock(return_value=httpx.Response(200, json=[]))
    with pytest.raises(AdapterError) as wrong:
        await get_adapter("autobrr").fetch("releases", CONFIG, {}, ctx)
    assert wrong.value.code == "not_autobrr"
