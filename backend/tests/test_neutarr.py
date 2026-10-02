"""NeutArr 1.11.1, measured on 02.10.2026 with one Sonarr behind it: the
answers are the measured ones, the counts raised where the measurement had
nothing hunted yet, the second app made up from the first."""

from __future__ import annotations

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AuthFailed, Context, outbound_client

CONFIG = {"url": "http://neutarr:9705", "api_key": "neutarr-key"}
BASE = "http://neutarr:9705/api"
CONFIGURED = {"eros": False, "general": False, "lidarr": False, "radarr": True, "readarr": False, "sonarr": True, "swaparr": False, "whisparr": False}
STATS = {"stats": {
    "eros": {"hunted": 0, "upgraded": 0}, "lidarr": {"hunted": 0, "upgraded": 0}, "radarr": {"hunted": 3, "upgraded": 1},
    "readarr": {"hunted": 0, "upgraded": 0}, "sonarr": {"hunted": 41, "upgraded": 7}, "swaparr": {"hunted": 0, "upgraded": 0},
    "whisparr": {"hunted": 0, "upgraded": 0},
}, "success": True}
CYCLES = {"cycles": {
    "sonarr": {"interval_seconds": 60, "next_cycle_at": 1790911290.87, "remaining_seconds": 45, "state": "waiting"},
    "radarr": {"interval_seconds": None, "next_cycle_at": None, "remaining_seconds": None, "state": "error", "reason": "Background worker failed to start"},
}, "server_time": 1790911246.71}
CAPS = {"caps": {"radarr": {"api_hits": 0}, "sonarr": {"api_hits": 4}}, "limits": {"radarr": 20, "sonarr": 20}, "success": True}


@pytest.fixture
def ctx() -> Context:
    return Context(outbound_client(guard=False), integration_id=1, widget_id=1, cache={})


def answers(radarr_connected: int = 1) -> None:
    respx.get(f"{BASE}/configured-apps").mock(return_value=httpx.Response(200, json=CONFIGURED))
    respx.get(f"{BASE}/stats").mock(return_value=httpx.Response(200, json=STATS))
    respx.get(f"{BASE}/cycles").mock(return_value=httpx.Response(200, json=CYCLES))
    respx.get(f"{BASE}/hourly-caps").mock(return_value=httpx.Response(200, json=CAPS))
    respx.get(f"{BASE}/status/sonarr").mock(return_value=httpx.Response(200, json={"connected_count": 1, "total_configured": 1}))
    respx.get(f"{BASE}/status/radarr").mock(return_value=httpx.Response(200, json={"connected_count": radarr_connected, "total_configured": 1}))


@respx.mock
async def test_the_overview_adds_up_every_app_and_sends_the_key_as_a_header(ctx: Context) -> None:
    answers()
    data = await get_adapter("neutarr").fetch("overview", CONFIG, {}, ctx)
    assert data.primary == {"label": "Hunted", "value": 44}
    assert {row["label"]: row["value"] for row in data.secondary} == {"Upgraded": 8, "Apps": "1 / 2"}
    # Radarr's worker broke, so it counts as not reached.
    assert data.status == "warn" and data.meta["status_reason"] == "Not reached: Radarr"
    request = respx.calls.last.request
    assert request.headers["X-Api-Key"] == "neutarr-key" and "neutarr-key" not in str(request.url)


@respx.mock
async def test_each_app_is_a_row_with_its_counts_and_its_next_cycle(ctx: Context) -> None:
    answers()
    data = await get_adapter("neutarr").fetch("apps", CONFIG, {}, ctx)
    sonarr, radarr = data.items
    assert (sonarr["title"], sonarr["value"], sonarr["status"]) == ("Sonarr", 41, "ok")
    assert sonarr["subtitle"] == "next in 1 min · 7 upgraded · 1 / 1 connected · 4 / 20 calls this hour"
    assert radarr["status"] == "bad"
    assert radarr["subtitle"].startswith("Background worker failed to start · 1 upgraded")
    assert data.status == "bad"


@respx.mock
async def test_an_app_no_instance_of_which_answers_is_red(ctx: Context) -> None:
    answers(radarr_connected=0)
    respx.get(f"{BASE}/cycles").mock(return_value=httpx.Response(200, json={"cycles": {"radarr": {"state": "running"}}}))
    data = await get_adapter("neutarr").fetch("apps", CONFIG, {}, ctx)
    rows = {row["title"]: row for row in data.items}
    assert rows["Radarr"]["status"] == "bad" and rows["Radarr"]["subtitle"].startswith("hunting now")
    assert rows["Sonarr"]["subtitle"].startswith("not started")


@respx.mock
async def test_nothing_set_up_asks_nothing_more(ctx: Context) -> None:
    respx.get(f"{BASE}/configured-apps").mock(return_value=httpx.Response(200, json={name: False for name in CONFIGURED}))
    respx.get(f"{BASE}/stats").mock(return_value=httpx.Response(200, json=STATS))
    data = await get_adapter("neutarr").fetch("apps", CONFIG, {}, ctx)
    assert data.items == [] and data.status == "unknown"
    assert len(respx.calls) == 2


@respx.mock
async def test_a_wrong_key_is_refused(ctx: Context) -> None:
    respx.get(f"{BASE}/configured-apps").mock(return_value=httpx.Response(401, json={"error": "Authentication required"}))
    with pytest.raises(AuthFailed):
        await get_adapter("neutarr").fetch("overview", CONFIG, {}, ctx)


@respx.mock
async def test_the_connection_test_names_the_version_and_the_apps(ctx: Context) -> None:
    respx.get(f"{BASE}/version").mock(return_value=httpx.Response(200, text="1.11.1\n"))
    respx.get(f"{BASE}/configured-apps").mock(return_value=httpx.Response(200, json=CONFIGURED))
    respx.get(f"{BASE}/stats").mock(return_value=httpx.Response(200, json=STATS))
    assert await get_adapter("neutarr").test(CONFIG, ctx) == "NeutArr 1.11.1 answers and hunts in 2 app(s)."
