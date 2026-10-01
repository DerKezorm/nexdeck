"""Qui, measured against 1.30.0 with one qBittorrent 5.2.3 behind it (01.10.2026).

The fixture is that instance's answers with the host, the public address of
the line and the wording of its error taken out."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AuthFailed, Context

ANSWERS = json.loads((Path(__file__).parent / "fixtures" / "qui.json").read_text(encoding="utf-8"))
CONFIG = {"url": "http://qui:7476", "api_key": "key"}


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


def _two_instances() -> tuple[list[dict], dict]:
    second = {**copy.deepcopy(ANSWERS["instances"][0]), "id": 2, "name": "Home"}
    busy = copy.deepcopy(ANSWERS["torrents"])
    busy["serverState"].update(dl_info_speed=2_000_000, up_info_speed=500_000)
    busy["stats"]["total"] = 9
    busy["counts"]["status"].update(active=3, seeding=5, errored=1)
    return [ANSWERS["instances"][0], second], busy


@respx.mock
async def test_the_overview_adds_up_every_instance(ctx: Context) -> None:
    instances, busy = _two_instances()
    respx.get("http://qui:7476/api/instances").mock(return_value=httpx.Response(200, json=instances))
    respx.get("http://qui:7476/api/instances/1/torrents").mock(return_value=httpx.Response(200, json=ANSWERS["torrents"]))
    respx.get("http://qui:7476/api/instances/2/torrents").mock(return_value=httpx.Response(200, json=busy))
    data = await get_adapter("qui").fetch("overview", CONFIG, {}, ctx)
    chips = {row["label"]: row["value"] for row in data.secondary}
    assert chips["Torrents"] == 10 and chips["Active"] == 3 and chips["Seeding"] == 5 and chips["Errored"] == 1
    assert data.metrics == {"download": 2_000_000.0, "upload": 500_000.0}
    assert data.status == "warn", "an errored torrent is worth a look"
    assert respx.calls.last.request.headers["X-API-Key"] == "key"
    assert respx.calls.last.request.url.params["limit"] == "1", "one row is enough for the totals"


@respx.mock
async def test_an_instance_that_does_not_answer_is_a_red_row_with_qui_s_reason(ctx: Context) -> None:
    instances, _busy = _two_instances()
    respx.get("http://qui:7476/api/instances").mock(return_value=httpx.Response(200, json=instances))
    respx.get("http://qui:7476/api/instances/1/torrents").mock(return_value=httpx.Response(200, json=ANSWERS["torrents"]))
    respx.get("http://qui:7476/api/instances/2/torrents").mock(return_value=httpx.Response(502, text="bad gateway"))
    data = await get_adapter("qui").fetch("instances", CONFIG, {}, ctx)
    rows = {row["title"]: row for row in data.items}
    assert rows["Seedbox"]["status"] == "ok" and rows["Seedbox"]["value"] == "1"
    assert rows["Home"]["status"] == "bad" and "authentication" in rows["Home"]["subtitle"]
    assert data.status == "warn"


@pytest.mark.parametrize("code", [401, 403])
@respx.mock
async def test_a_wrong_or_missing_key_is_said_in_words(code: int, ctx: Context) -> None:
    respx.get("http://qui:7476/api/instances").mock(return_value=httpx.Response(code, text="Unauthorized"))
    with pytest.raises(AuthFailed):
        await get_adapter("qui").fetch("overview", CONFIG, {}, ctx)


@respx.mock
async def test_the_connection_test_counts_what_answers(ctx: Context) -> None:
    respx.get("http://qui:7476/api/instances").mock(return_value=httpx.Response(200, json=ANSWERS["instances"]))
    respx.get("http://qui:7476/api/instances/1/torrents").mock(return_value=httpx.Response(200, json=ANSWERS["torrents"]))
    assert await get_adapter("qui").test(CONFIG, ctx) == "Qui answers with 1 instance(s), 1 of them reachable."


def test_the_public_address_of_the_line_is_never_in_a_card() -> None:
    state = {**ANSWERS["torrents"]["serverState"], "last_external_address_v4": "203.0.113.9"}
    from app.adapters.qui import shape

    data = shape("overview", [{"id": 1, "name": "A", "answered": True, "stats": {}, "status": {}, "state": state}])
    assert "203.0.113.9" not in json.dumps(data.model_dump())
