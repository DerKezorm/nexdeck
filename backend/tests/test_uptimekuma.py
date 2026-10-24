"""Uptime Kuma against answers recorded from throwaway instances of 1.23.17 and 2.x (24.10.2026).

Both had the same monitors: a group "Home lab" holding "Kuma itself" (up)
and "Nothing here" (down), and "Kuma again" and "Public site" outside it.
The status page "home" shows "Kuma itself" and "Nothing here".
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, Context

FIXTURES = Path(__file__).parent / "fixtures"
CONFIG = {"url": "http://kuma:3001", "api_key": "uk1_x"}


def text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


def serve(version: int) -> tuple[respx.Route, respx.Route]:
    """The metrics, the heartbeats and the page of status page "home", as that version answered."""
    respx.get("http://kuma:3001/metrics").mock(return_value=httpx.Response(200, text=text(f"uptimekuma{version}_metrics.txt")))
    beats = respx.get("http://kuma:3001/api/status-page/heartbeat/home").mock(
        return_value=httpx.Response(200, text=text(f"uptimekuma{version}_heartbeat.json"), headers={"content-type": "application/json"}))
    page = respx.get("http://kuma:3001/api/status-page/home").mock(
        return_value=httpx.Response(200, text=text(f"uptimekuma{version}_status_page.json"), headers={"content-type": "application/json"}))
    return beats, page


@respx.mock
@pytest.mark.parametrize("version", [1, 2])
async def test_a_status_page_keeps_the_card_to_its_monitors(ctx: Context, version: int) -> None:
    serve(version)
    kuma = get_adapter("uptimekuma")
    listed = await kuma.fetch("monitors", CONFIG, {"status_page": "home"}, ctx)
    assert [(row["title"], row["status"]) for row in listed.items] == [("Nothing here", "bad"), ("Kuma itself", "ok")]
    assert listed.secondary == [{"label": "Up", "value": 1}, {"label": "Down", "value": 1}]
    assert listed.link == "http://kuma:3001/status/home"
    summed = await kuma.fetch("summary", CONFIG, {"status_page": "home"}, ctx)
    assert summed.primary == {"label": "Monitors up", "value": 1, "unit": "/ 2"}
    assert summed.status == "bad"


@respx.mock
async def test_uptime_kuma_2_matches_by_number_and_never_asks_for_the_names(ctx: Context) -> None:
    """Its metrics carry monitor_id; the heartbeats say which numbers are on the page."""
    beats, page = serve(2)
    await get_adapter("uptimekuma").fetch("monitors", CONFIG, {"status_page": "home"}, ctx)
    assert beats.called
    assert not page.called


@respx.mock
async def test_uptime_kuma_1_matches_by_name(ctx: Context) -> None:
    """Its metrics have no number, so the page is read for the names of its monitors."""
    _beats, page = serve(1)
    await get_adapter("uptimekuma").fetch("monitors", CONFIG, {"status_page": "home"}, ctx)
    assert page.called


@respx.mock
async def test_an_unknown_status_page_is_said_and_its_page_never_asked(ctx: Context) -> None:
    """Uptime Kuma 1.23 does not answer /api/status-page/<slug> for a slug it does not know.

    Measured 24.10.2026: no answer in 15 seconds. The heartbeats answer at
    once with empty lists, and that is enough to know.
    """
    respx.get("http://kuma:3001/metrics").mock(return_value=httpx.Response(200, text=text("uptimekuma1_metrics.txt")))
    respx.get("http://kuma:3001/api/status-page/heartbeat/nope").mock(
        return_value=httpx.Response(200, json={"heartbeatList": {}, "uptimeList": {}}))
    page = respx.get("http://kuma:3001/api/status-page/nope").mock(side_effect=httpx.ReadTimeout("never answers"))
    with pytest.raises(AdapterError) as failure:
        await get_adapter("uptimekuma").fetch("summary", CONFIG, {"status_page": "nope"}, ctx)
    assert failure.value.code == "no_status_page"
    assert not page.called


@respx.mock
async def test_a_slug_is_written_the_way_uptime_kuma_writes_them(ctx: Context) -> None:
    respx.get("http://kuma:3001/metrics").mock(return_value=httpx.Response(200, text=text("uptimekuma2_metrics.txt")))
    with pytest.raises(AdapterError) as failure:
        await get_adapter("uptimekuma").fetch("summary", CONFIG, {"status_page": "../api/x"}, ctx)
    assert failure.value.code == "bad_status_page"
    # Pasted with its slash and in capitals, it is still the same page.
    serve(2)
    data = await get_adapter("uptimekuma").fetch("summary", CONFIG, {"status_page": "Home/"}, ctx)
    assert data.primary["unit"] == "/ 2"


@respx.mock
async def test_the_summary_names_what_is_down(ctx: Context) -> None:
    serve(2)
    data = await get_adapter("uptimekuma").fetch("summary", CONFIG, {}, ctx)
    assert data.primary == {"label": "Monitors up", "value": 3, "unit": "/ 5"}
    assert data.meta["status_reason"] == "Down: Home lab, Nothing here"
    assert data.link is None


@respx.mock
async def test_the_counts_and_the_colour_follow_the_name_filter(ctx: Context) -> None:
    """A filter for the two Kuma monitors leaves the one that is down out of it, colour and counts too."""
    serve(2)
    kuma = get_adapter("uptimekuma")
    listed = await kuma.fetch("monitors", CONFIG, {"filter": "kuma"}, ctx)
    assert listed.status == "ok"
    assert listed.secondary == [{"label": "Up", "value": 2}, {"label": "Down", "value": 0}]
    summed = await kuma.fetch("summary", CONFIG, {"filter": "kuma"}, ctx)
    assert summed.primary["unit"] == "/ 2" and summed.status == "ok"


def changed(name: str, monitor: str, state: int) -> str:
    """The recorded metrics with one monitor in another state."""
    lines = text(name).splitlines()
    return "\n".join(
        line.rsplit(" ", 1)[0] + f" {state}" if line.startswith(f'monitor_status{{monitor_name="{monitor}"') else line for line in lines)


@respx.mock
async def test_a_monitor_still_waiting_turns_the_card_yellow(ctx: Context) -> None:
    """Pending (2) is what a monitor is between a failed check and its retry."""
    respx.get("http://kuma:3001/metrics").mock(return_value=httpx.Response(200, text=changed("uptimekuma1_metrics.txt", "Kuma again", 2)))
    data = await get_adapter("uptimekuma").fetch("summary", CONFIG, {"filter": "kuma"}, ctx)
    assert data.status == "warn"


@respx.mock
async def test_no_response_time_is_no_number_and_node_is_no_monitor(ctx: Context) -> None:
    """A group, a push monitor or one that is down reports -1; node's own lines carry labels too.

    The group is up here: down, its row says "down" whatever the time was.
    """
    respx.get("http://kuma:3001/metrics").mock(return_value=httpx.Response(200, text=changed("uptimekuma1_metrics.txt", "Home lab", 1)))
    data = await get_adapter("uptimekuma").fetch("monitors", CONFIG, {}, ctx)
    titles = [row["title"] for row in data.items]
    assert sorted(titles) == ["Home lab", "Kuma again", "Kuma itself", "Nothing here", "Public site"]
    group = next(row for row in data.items if row["title"] == "Home lab")
    assert group["value"] == ""
    assert not any(str(row["value"]).startswith("-") for row in data.items)
