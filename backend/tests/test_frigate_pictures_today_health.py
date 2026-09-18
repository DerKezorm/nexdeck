"""Frigate's latest picture, detection thumbnails, today's counts and a quiet health card.

Asked for in issue #1 after the first cards turned out to be frame rates and a
text list. Written against Frigate's API documentation; the stats layout is
the current one, with the cameras under their own key.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, Context

FRIGATE = "http://frigate:5000"
CONFIG = {"url": FRIGATE}


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, cache={})


def _stats(**cameras: dict) -> dict:
    return {
        "cameras": cameras or {"front_gate": {"camera_fps": 5.0, "detection_fps": 0.4, "process_fps": 5.0}},
        "detectors": {"cpu": {"inference_speed": 40.0}},
        "service": {"storage": {"/media/frigate/recordings": {"used": 500_000, "total": 1_000_000}}},
    }


@respx.mock
async def test_the_camera_card_shows_the_latest_picture_through_the_server(ctx: Context) -> None:
    respx.get(f"{FRIGATE}/api/stats").mock(return_value=httpx.Response(200, json=_stats()))
    frigate = get_adapter("frigate")
    data = await frigate.fetch("camera", CONFIG, {"camera": "front_gate", "interval": 3}, ctx)
    assert data.items[0]["art"] == "proxy:/latest/front_gate"
    assert data.meta["mode"] == "snapshot"
    assert data.meta["interval"] == 5, "no faster than every five seconds"
    source = await frigate.image_source(CONFIG, "/latest/front_gate", ctx)
    assert source.url == f"{FRIGATE}/api/front_gate/latest.jpg"
    assert source.cache_seconds == 0


@respx.mock
async def test_a_camera_frigate_does_not_have_is_named(ctx: Context) -> None:
    respx.get(f"{FRIGATE}/api/stats").mock(return_value=httpx.Response(200, json=_stats()))
    with pytest.raises(AdapterError) as failure:
        await get_adapter("frigate").fetch("camera", CONFIG, {"camera": "garden"}, ctx)
    assert "front_gate" in failure.value.hint


@pytest.mark.parametrize("path", ["/api/config", "/latest/../config", "/thumb", "/latest/a/b", "/events/x/clip.mp4"])
async def test_only_the_two_picture_paths_are_fetched(ctx: Context, path: str) -> None:
    with pytest.raises(AdapterError) as failure:
        await get_adapter("frigate").image_source(CONFIG, path, ctx)
    assert failure.value.code in ("bad_path", "bad_param")


@respx.mock
async def test_detections_carry_their_thumbnail(ctx: Context) -> None:
    events = respx.get(f"{FRIGATE}/api/events").mock(return_value=httpx.Response(200, json=[
        {"id": "1726680000.5-ab12cd", "label": "car", "camera": "front_gate", "start_time": 1726680000.5, "top_score": 0.81},
    ]))
    data = await get_adapter("frigate").fetch("events", CONFIG, {"limit": 5}, ctx)
    assert data.items[0]["art"] == "proxy:/thumb/1726680000.5-ab12cd"
    assert data.items[0]["art_shape"] == "square"
    assert events.calls.last.request.url.params["include_thumbnails"] == "0"
    source = await get_adapter("frigate").image_source(CONFIG, "/thumb/1726680000.5-ab12cd", ctx)
    assert source.url == f"{FRIGATE}/api/events/1726680000.5-ab12cd/thumbnail.jpg"


@respx.mock
async def test_today_counts_detections_by_kind(ctx: Context) -> None:
    events = respx.get(f"{FRIGATE}/api/events").mock(return_value=httpx.Response(200, json=[
        {"label": "person"}, {"label": "car"}, {"label": "person"}, {"label": "person"},
    ]))
    data = await get_adapter("frigate").fetch("today", CONFIG, {"camera": "front_gate"}, ctx)
    assert data.primary == {"label": "Detections today", "value": 4}
    # The most frequent first, not the alphabet.
    assert data.secondary == [{"label": "Person", "value": 3}, {"label": "Car", "value": 1}]
    sent = events.calls.last.request.url.params
    assert sent["cameras"] == "front_gate"
    assert int(sent["after"]) > 0


@respx.mock
async def test_health_is_empty_while_everything_runs(ctx: Context) -> None:
    respx.get(f"{FRIGATE}/api/stats").mock(return_value=httpx.Response(200, json=_stats()))
    data = await get_adapter("frigate").fetch("health", CONFIG, {}, ctx)
    assert data.items == []
    assert data.status == "ok"


@respx.mock
async def test_health_names_what_is_wrong(ctx: Context) -> None:
    stats = _stats(
        front_gate={"camera_fps": 0.0},
        driveway={"camera_fps": 10.0, "skipped_fps": 3.0},
        garden={"camera_fps": 10.0, "skipped_fps": 0.2},
    )
    stats["detectors"] = {"cpu": {"inference_speed": 180.0}}
    stats["service"]["storage"]["/media/frigate/recordings"] = {"used": 950_000, "total": 1_000_000}
    respx.get(f"{FRIGATE}/api/stats").mock(return_value=httpx.Response(200, json=stats))
    data = await get_adapter("frigate").fetch("health", CONFIG, {}, ctx)
    assert [(item["title"], item["status"]) for item in data.items] == [
        ("front gate", "bad"), ("driveway", "warn"), ("Detector cpu", "warn"), ("Recordings", "warn"),
    ]
    assert data.status == "bad"


@respx.mock
async def test_the_score_comes_from_data_where_newer_frigate_keeps_it(ctx: Context) -> None:
    """The reporter's event (issue #1, trimmed): ``top_score`` null at the top,
    the number under ``data``. The card read 0%."""
    respx.get(f"{FRIGATE}/api/events").mock(return_value=httpx.Response(200, json=[
        {"id": "1789755429.995241-nxetgy", "camera": "front_gate", "label": "car", "start_time": 1789755429.995241,
         "has_clip": True, "top_score": None, "data": {"score": 0.8898783326148987, "top_score": 0.9173216223716736}},
        {"id": "1789755000.1-old", "camera": "front_gate", "label": "person", "start_time": 1789755000.1, "top_score": 0.76},
        {"id": "1789754000.1-none", "camera": "front_gate", "label": "dog", "start_time": 1789754000.1, "top_score": None},
    ]))
    data = await get_adapter("frigate").fetch("events", CONFIG, {}, ctx)
    assert [item["value"] for item in data.items] == ["92%", "76%", ""]
