"""xTeVe, against the answers of xTeVe 2.2.0 (alturismo/xteve, 27.10.2026): the status of a fresh install, the update commands,
an unknown command, the 423 of a switched-off API. The counts are not measured (a fresh install has no playlist); a test says so."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, Context, Unreachable, outbound_client

BASE = "http://xteve.example.com:34400"
API = f"{BASE}/api/"
CONFIG = {"url": BASE}
ADAPTER = get_adapter("xteve")
STATUS = {"epg.source": "PMS", "status": True, "url.dvr": "192.0.2.5:34400", "url.m3u": "http://192.0.2.5:34400/m3u/xteve.m3u",
          "url.xepg": "http://192.0.2.5:34400/xmltv/xteve.xml", "version.api": "1.1.0", "version.xteve": "2.2.0"}


def fresh() -> Context:
    return Context(outbound_client(guard=False), integration_id=1, widget_id=1, cache={})


@pytest.fixture
def ctx() -> Context:
    return fresh()


@respx.mock
async def test_a_fresh_xteve_shows_its_version_and_guide_source_and_the_three_update_buttons(ctx: Context) -> None:
    route = respx.post(API).mock(return_value=httpx.Response(200, json=STATUS))
    data = await ADAPTER.fetch("status", CONFIG, {}, ctx)
    assert data.primary == {"label": "xTeVe", "value": "Running"}
    assert data.secondary == [{"label": "Version", "value": "2.2.0"}, {"label": "Guide source", "value": "PMS"}]
    assert [(a.id, a.confirm) for a in data.actions] == [("playlists", True), ("guide", True), ("mapping", True)]
    assert json.loads(route.calls.last.request.content) == {"cmd": "status"} and data.metrics == {}


def test_counts_are_shown_when_xteve_gives_them() -> None:
    card = ADAPTER.status_card({**STATUS, "streams.active": 2, "streams.all": 3120, "streams.xepg": 164})
    assert {"label": "Active streams", "value": 2} in card.secondary and {"label": "Channels", "value": 164} in card.secondary
    assert card.metrics == {"streams": 2.0}


@respx.mock
async def test_each_button_sends_its_command_and_the_body_decides_whether_it_worked(ctx: Context) -> None:
    route = respx.post(API).mock(return_value=httpx.Response(200, json={"status": True}))
    for action, command in (("playlists", "update.m3u"), ("guide", "update.xmltv"), ("mapping", "update.xepg")):
        await ADAPTER.action("status", action, {}, CONFIG, {}, ctx)
        assert json.loads(route.calls.last.request.content) == {"cmd": command}
    route.mock(return_value=httpx.Response(200, json={"err": "Invalid API command", "status": False}))
    with pytest.raises(AdapterError) as failure:
        await ADAPTER.action("status", "guide", {}, CONFIG, {}, ctx)
    assert failure.value.code == "xteve_refused" and "Invalid API command" in str(failure.value)
    with pytest.raises(AdapterError) as failure:
        await ADAPTER.action("status", "wipe", {}, CONFIG, {}, ctx)
    assert failure.value.code == "no_such_action"


@respx.mock
async def test_the_test_names_the_version_and_a_switched_off_api_says_how_to_switch_it_on(ctx: Context) -> None:
    respx.post(API).mock(return_value=httpx.Response(200, json=STATUS))
    assert await ADAPTER.test(CONFIG, ctx) == "xTeVe 2.2.0 answers."
    assert await ADAPTER.running_version(CONFIG, fresh()) == "2.2.0"
    respx.post(API).mock(return_value=httpx.Response(423, text="Locked\n"))
    with pytest.raises(AdapterError) as failure:
        await ADAPTER.test(CONFIG, fresh())
    assert failure.value.code == "api_off" and "Settings" in failure.value.hint


@respx.mock
async def test_something_else_at_the_address_is_not_taken_for_xteve(ctx: Context) -> None:
    for answer, code in ((httpx.Response(404, text="Not Found"), "not_xteve"), (httpx.Response(200, json={"hello": "world"}), "not_xteve"),
                         (httpx.Response(200, text="<html></html>"), "not_json")):
        respx.post(API).mock(return_value=answer)
        with pytest.raises(AdapterError) as failure:
            await ADAPTER.test(CONFIG, fresh())
        assert failure.value.code == code


@respx.mock
async def test_an_unreachable_xteve(ctx: Context) -> None:
    respx.post(API).mock(side_effect=httpx.ConnectError("connection refused"))
    with pytest.raises(Unreachable):
        await ADAPTER.fetch("status", CONFIG, {}, ctx)


def test_the_demo_fills_the_card() -> None:
    for tick in range(0, 200, 20):
        assert ADAPTER.demo("status", {}, tick).primary
