"""Your Spotify, built from the code of the official server image (27.10.2026), never run against an instance with data.

What the tests rely on is what the server's source settles: ``GET /spotify/listened_to`` answers ``{"count": n}``,
the public token goes in ``?token=``, no valid one is HTTP 401, the history takes ``number`` and ``offset``. The rows of
the history are a guess at the likely field names, and one test holds that a row of another shape does not break the card.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context, Unreachable, outbound_client

BASE = "http://your-spotify-server.example.com:8080"
CONFIG = {"url": BASE, "token": "a-made-up-public-token"}
ADAPTER = get_adapter("yourspotify")


def fresh() -> Context:
    return Context(outbound_client(guard=False), integration_id=1, widget_id=1, cache={})


@pytest.fixture
def ctx() -> Context:
    return fresh()


@respx.mock
async def test_the_statistics_ask_for_today_the_week_and_the_month_with_the_token(ctx: Context) -> None:
    counts = iter([18, 130, 612])
    route = respx.get(f"{BASE}/spotify/listened_to").mock(side_effect=lambda _r: httpx.Response(200, json={"count": next(counts)}))
    data = await ADAPTER.fetch("stats", CONFIG, {}, ctx)
    assert data.primary == {"label": "Today", "value": 18}
    assert data.secondary == [{"label": "This week", "value": 130}, {"label": "This month", "value": 612}]
    assert data.metrics == {"week": 130.0}
    assert [call.request.url.params["token"] for call in route.calls] == ["a-made-up-public-token"] * 3
    spans = [call.request.url.params for call in route.calls]
    assert all("start" in one and "end" in one for one in spans)
    assert spans[0]["start"] > spans[1]["start"] > spans[2]["start"]


@respx.mock
async def test_the_history_names_title_artist_album_and_how_long_ago(ctx: Context) -> None:
    route = respx.get(f"{BASE}/spotify/gethistory").mock(return_value=httpx.Response(200, json=[
        {"_id": "a1", "played_at": "2026-10-27T10:00:00.000Z", "track": {"name": "Departure"}, "artist": {"name": "Harbour Lights"}, "album": {"name": "Tide"}},
        {"id": "a2", "played_at": "2026-10-26T10:00:00.000Z", "track": {"name": "Signal", "artists": [{"name": "Orbital Tide"}]}}]))
    data = await ADAPTER.fetch("recent", CONFIG, {"limit": 2}, ctx)
    assert [(item["title"], item["subtitle"]) for item in data.items] == [("Departure", "Harbour Lights · Tide"), ("Signal", "Orbital Tide")]
    assert data.items[0]["value"].endswith(("min", "h", "d"))
    query = route.calls.last.request.url.params
    assert (query["number"], query["offset"], query["token"]) == ("2", "0", "a-made-up-public-token")


@respx.mock
async def test_a_row_of_another_shape_is_shown_as_far_as_it_goes_and_an_empty_history_says_so(ctx: Context) -> None:
    respx.get(f"{BASE}/spotify/gethistory").mock(return_value=httpx.Response(200, json=[{"surprise": True}, "junk"]))
    data = await ADAPTER.fetch("recent", CONFIG, {}, ctx)
    assert [item["title"] for item in data.items] == ["?"]
    respx.get(f"{BASE}/spotify/gethistory").mock(return_value=httpx.Response(200, json=[]))
    empty = await ADAPTER.fetch("recent", CONFIG, {}, fresh())
    assert (empty.items, empty.meta["empty"]) == ([], "Nothing was played yet.")


@respx.mock
async def test_the_test_counts_the_last_thirty_days_and_a_wrong_token_is_refused(ctx: Context) -> None:
    respx.get(f"{BASE}/spotify/listened_to").mock(return_value=httpx.Response(200, json={"count": 612}))
    assert await ADAPTER.test(CONFIG, ctx) == "Your Spotify answers, 612 tracks in the last 30 days."
    respx.get(f"{BASE}/spotify/listened_to").mock(return_value=httpx.Response(401, json={"code": "NOT_LOGGED"}))
    with pytest.raises(AuthFailed):
        await ADAPTER.test(CONFIG, fresh())


@respx.mock
async def test_the_web_interface_or_something_else_at_the_address_is_not_taken_for_the_server(ctx: Context) -> None:
    respx.get(f"{BASE}/spotify/listened_to").mock(return_value=httpx.Response(404, text="nothing"))
    with pytest.raises(AdapterError) as failure:
        await ADAPTER.test(CONFIG, ctx)
    assert failure.value.code == "not_yourspotify"
    respx.get(f"{BASE}/spotify/listened_to").mock(return_value=httpx.Response(200, text="<html></html>"))
    with pytest.raises(AdapterError) as failure:
        await ADAPTER.test(CONFIG, fresh())
    assert failure.value.code == "not_json"
    respx.get(f"{BASE}/spotify/listened_to").mock(return_value=httpx.Response(200, json={"hello": "world"}))
    with pytest.raises(AdapterError) as failure:
        await ADAPTER.test(CONFIG, fresh())
    assert failure.value.code == "not_yourspotify"


@respx.mock
async def test_an_unreachable_server(ctx: Context) -> None:
    respx.get(f"{BASE}/spotify/listened_to").mock(side_effect=httpx.ConnectError("connection refused"))
    with pytest.raises(Unreachable):
        await ADAPTER.fetch("stats", CONFIG, {}, ctx)


def test_the_demo_fills_every_card() -> None:
    for tick in range(0, 300, 30):
        assert ADAPTER.demo("stats", {}, tick).primary
        assert ADAPTER.demo("recent", {}, tick).items
