"""Cup, against the answers of a live Cup 3.5.1 (11.09.2026).

The shapes below are copied from that instance, trimmed to the images that
matter: a major version step, a new build behind the same tag, one image the
registry refused to look up, and one that is up to date.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, Context

CUP = "http://cup.example.com"
CONFIG = {"url": CUP}

MAJOR = {
    "in_use": True,
    "parts": {"registry": "registry-1.docker.io", "repository": "library/postgres", "tag": "17-alpine"},
    "reference": "postgres:17-alpine",
    "result": {"error": None, "has_update": True, "info": {
        "current_version": "17", "new_tag": "18-alpine", "new_version": "18", "type": "version", "version_update_type": "major"}},
    "server": None, "time": 492, "url": None,
}
#: ⚠️ Measured: a new build behind the same tag has no versions at all, only digests.
NEW_BUILD = {
    "in_use": False,
    "parts": {"registry": "registry-1.docker.io", "repository": "traefik/whoami", "tag": "latest"},
    "reference": "traefik/whoami:latest",
    "result": {"error": None, "has_update": True, "info": {
        "local_digests": ["sha256:local-digest"],
        "remote_digest": "sha256:remote-digest", "type": "digest"}},
    "server": None, "time": 347, "url": "https://github.com/traefik/whoami",
}
MINOR = {
    "in_use": True,
    "parts": {"registry": "registry-1.docker.io", "repository": "traefik/whoami", "tag": "v1.10.1"},
    "reference": "traefik/whoami:v1.10.1",
    "result": {"error": None, "has_update": True, "info": {
        "current_version": "1.10.1", "new_tag": "v1.12.0", "new_version": "1.12.0", "type": "version", "version_update_type": "minor"}},
    "server": None, "time": 347, "url": "https://github.com/traefik/whoami",
}
#: ⚠️ Measured: ``has_update`` is null, not false, and the reason is led by the whole request.
REFUSED = {
    "in_use": False,
    "parts": {"registry": "registry-1.docker.io", "repository": "library/busybox", "tag": "no-such-tag"},
    "reference": "busybox:no-such-tag",
    "result": {"error": "HEAD https://registry-1.docker.io/v2/library/busybox/manifests/no-such-tag: Not found!", "has_update": None, "info": None},
    "server": None, "time": 314, "url": None,
}
CURRENT = {
    "in_use": True,
    "parts": {"registry": "ghcr.io", "repository": "sergi0g/cup", "tag": "latest"},
    "reference": "ghcr.io/sergi0g/cup:latest",
    "result": {"error": None, "has_update": False, "info": None},
    "server": None, "time": 218, "url": "https://github.com/sergi0g/cup",
}
METRICS = {"major_updates": 1, "minor_updates": 0, "monitored_images": 16, "other_updates": 1,
           "patch_updates": 0, "unknown": 1, "up_to_date": 13, "updates_available": 2}


def _hours_ago(hours: float) -> str:
    from datetime import UTC, datetime, timedelta

    return (datetime.now(UTC) - timedelta(hours=hours)).isoformat().replace("+00:00", "Z")


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


def _answer(*images: dict[str, Any], metrics: dict[str, Any] | None = None, last_updated: str = "2026-09-11T07:21:41Z") -> None:
    respx.get(f"{CUP}/api/v3/json").mock(return_value=httpx.Response(200, json={
        "images": list(images), "last_updated": last_updated, "metrics": metrics or METRICS,
    }))


@respx.mock
async def test_the_summary_counts_by_how_big_a_step_is(ctx: Context) -> None:
    # Two days without a check, which is what Cup without a refresh interval looks like.
    _answer(MAJOR, NEW_BUILD, REFUSED, CURRENT, last_updated=_hours_ago(48))
    data = await get_adapter("cup").fetch("summary", CONFIG, {}, ctx)
    assert data.primary == {"label": "Updates", "value": 2, "unit": "/ 16"}
    # A step nobody has to take is no chip: no Minor, no Patch at zero.
    assert [chip["label"] for chip in data.secondary] == ["Major", "New build", "Not checked", "Last check"]
    assert data.secondary[-1]["value"] == "2 d"
    assert [chip["value"] for chip in data.secondary][:3] == [1, 1, 1]
    assert data.status == "warn"
    assert data.metrics == {"updates": 2.0, "major": 1.0}
    assert [part["label"] for part in data.meta["ring"]] == ["Up to date", "Updates", "Not checked"]
    assert [action.id for action in data.actions] == ["refresh"]


@respx.mock
async def test_nothing_waiting_is_calm_and_says_so(ctx: Context) -> None:
    quiet = {**METRICS, "major_updates": 0, "other_updates": 0, "unknown": 0, "updates_available": 0, "up_to_date": 16}
    _answer(CURRENT, metrics=quiet)
    summary = await get_adapter("cup").fetch("summary", CONFIG, {}, ctx)
    assert summary.status == "ok"
    assert [chip["label"] for chip in summary.secondary if chip["label"] == "Not checked"] == []
    updates = await get_adapter("cup").fetch("updates", CONFIG, {"limit": 10}, ctx)
    assert updates.items == [] and updates.status == "ok"
    assert updates.meta["empty"] == "Every image is up to date."


@respx.mock
async def test_the_list_puts_the_biggest_step_first_and_the_refused_last(ctx: Context) -> None:
    _answer(NEW_BUILD, REFUSED, MINOR, CURRENT, MAJOR)
    data = await get_adapter("cup").fetch("updates", CONFIG, {"limit": 10}, ctx)
    assert [row["title"] for row in data.items] == ["postgres:17-alpine", "traefik/whoami:v1.10.1", "traefik/whoami:latest", "busybox:no-such-tag"]
    major, minor, build, refused = data.items
    # The words sit in the subtitle, which is translated; the value is drawn as it comes.
    assert (major["subtitle"], major["value"], major["status"]) == ("Major", "17 → 18", "warn")
    assert (minor["subtitle"], minor["status"], minor["url"]) == ("Minor", "ok", "https://github.com/traefik/whoami")
    assert build["subtitle"] == "New build" and "value" not in build
    assert refused == {"title": "busybox:no-such-tag", "subtitle": "Not checked · Not found!", "status": "unknown"}
    assert data.secondary[0] == {"label": "Not checked", "value": 1}
    assert data.metrics == {"updates": 3.0}


@respx.mock
async def test_the_list_can_leave_out_images_no_container_uses(ctx: Context) -> None:
    _answer(MAJOR, NEW_BUILD, REFUSED)
    data = await get_adapter("cup").fetch("updates", CONFIG, {"limit": 10, "in_use": True}, ctx)
    assert [row["title"] for row in data.items] == ["postgres:17-alpine"]


@respx.mock
async def test_the_limit_leaves_room_for_updates_before_refusals(ctx: Context) -> None:
    _answer(REFUSED, MAJOR, MINOR)
    data = await get_adapter("cup").fetch("updates", CONFIG, {"limit": 2}, ctx)
    assert [row["subtitle"] for row in data.items] == ["Major", "Minor"]


@respx.mock
async def test_the_connection_test_counts_images(ctx: Context) -> None:
    _answer(MAJOR, CURRENT)
    assert await get_adapter("cup").test(CONFIG, ctx) == "Cup answers: 16 images, 2 with an update."


@respx.mock
async def test_another_service_on_the_address_is_named_as_such(ctx: Context) -> None:
    """⚠️ Measured: a path Cup does not know answers 404 with plain text."""
    respx.get(f"{CUP}/api/v3/json").mock(return_value=httpx.Response(404, text="Not found"))
    with pytest.raises(AdapterError) as refused:
        await get_adapter("cup").test(CONFIG, ctx)
    assert refused.value.code == "not_cup"
    respx.get(f"{CUP}/api/v3/json").mock(return_value=httpx.Response(200, json={"status": "ok"}))
    with pytest.raises(AdapterError) as wrong:
        await get_adapter("cup").fetch("summary", CONFIG, {}, ctx)
    assert wrong.value.code == "not_cup"


@respx.mock
async def test_check_now_asks_cup_to_look_again(ctx: Context) -> None:
    refresh = respx.get(f"{CUP}/api/v3/refresh").mock(return_value=httpx.Response(200, text="OK"))
    message = await get_adapter("cup").action("summary", "refresh", {}, CONFIG, {}, ctx)
    assert refresh.called and message == "Cup has checked every image again."
    with pytest.raises(AdapterError):
        await get_adapter("cup").action("summary", "delete_everything", {}, CONFIG, {}, ctx)


@respx.mock
async def test_the_summary_names_the_last_check_only_once_it_is_old(ctx: Context) -> None:
    """⚠️ Cup without a refresh interval never looks again on its own."""
    fresh = _hours_ago(40 / 60)
    respx.get(f"{CUP}/api/v3/json").mock(return_value=httpx.Response(200, json={"images": [MAJOR], "last_updated": fresh, "metrics": METRICS}))
    recent = await get_adapter("cup").fetch("summary", CONFIG, {}, ctx)
    assert "Last check" not in [chip["label"] for chip in recent.secondary]
    listed = await get_adapter("cup").fetch("updates", CONFIG, {"limit": 10}, ctx)
    assert listed.secondary[-1] == {"label": "Last check", "value": "40 min"}
