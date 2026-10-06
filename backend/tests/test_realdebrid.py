"""Real-Debrid's REST API 1.0, from its documentation (https://api.real-debrid.com/): no account was at hand to
measure against, so the shapes are the documented ones; the reporter of #29 confirmed the first three cards on
a real account (06.10.2026), the traffic cards are from the documentation only. Names and numbers made up."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context, outbound_client

API = "https://api.real-debrid.com/rest/1.0"
CONFIG = {"api_key": "made-up-real-debrid-token"}


def user(days: float, kind: str = "premium") -> dict:
    ends = datetime.now(UTC) + timedelta(days=days)
    return {"id": 1, "username": "example", "email": "example@example.com", "points": 1240, "locale": "en",
            "avatar": "https://example.com/avatar.png", "type": kind,
            "premium": int(days * 86_400) if kind == "premium" else 0,
            "expiration": ends.strftime("%Y-%m-%dT%H:%M:%S.000Z")}


TORRENTS = [
    {"id": "T1", "filename": "Example.Linux.Distro.iso", "hash": "0" * 40, "bytes": 4_400_000_000, "host": "real-debrid.com",
     "split": 2000, "progress": 42, "status": "downloading", "added": "2026-10-04T15:00:00.000Z", "links": [],
     "speed": 38_000_000, "seeders": 12},
    {"id": "T2", "filename": "Open.Movie.Project", "hash": "1" * 40, "bytes": 21_000_000_000, "host": "real-debrid.com",
     "split": 2000, "progress": 0, "status": "waiting_files_selection", "added": "2026-10-04T14:00:00.000Z", "links": []},
    {"id": "T3", "filename": "Broken.Upload", "hash": "2" * 40, "bytes": 0, "host": "real-debrid.com",
     "split": 2000, "progress": 0, "status": "magnet_error", "added": "2026-10-04T13:00:00.000Z", "links": []},
]


@pytest.fixture
def ctx() -> Context:
    return Context(outbound_client(guard=False), integration_id=1, widget_id=1, cache={})


@respx.mock
async def test_the_account_counts_the_days_of_premium_and_the_running_torrents(ctx: Context) -> None:
    me = respx.get(f"{API}/user").mock(return_value=httpx.Response(200, json=user(41.5)))
    respx.get(f"{API}/torrents/activeCount").mock(return_value=httpx.Response(200, json={"nb": 2, "limit": 50}))
    data = await get_adapter("realdebrid").fetch("account", CONFIG, {}, ctx)
    assert data.primary == {"label": "Premium days", "value": 41}
    secondary = {row["label"]: row["value"] for row in data.secondary}
    assert secondary["Points"] == 1240 and secondary["Active torrents"] == "2 / 50"
    assert secondary["Ends"] == (datetime.now(UTC) + timedelta(days=41.5)).date().isoformat()
    assert data.status == "ok"
    request = me.calls.last.request
    assert request.headers["Authorization"] == "Bearer made-up-real-debrid-token"
    assert "made-up" not in str(request.url)


@respx.mock
async def test_premium_running_out_is_amber_and_none_at_all_is_red(ctx: Context) -> None:
    respx.get(f"{API}/torrents/activeCount").mock(return_value=httpx.Response(200, json={"nb": 0, "limit": 50}))
    respx.get(f"{API}/user").mock(return_value=httpx.Response(200, json=user(3.2)))
    soon = await get_adapter("realdebrid").fetch("account", CONFIG, {}, ctx)
    assert soon.status == "warn" and soon.meta["status_reason"] == "Premium ends in 3 day(s)."

    respx.get(f"{API}/user").mock(return_value=httpx.Response(200, json=user(0, kind="free")))
    fresh = Context(outbound_client(guard=False), integration_id=1, widget_id=1, cache={})
    free = await get_adapter("realdebrid").fetch("account", CONFIG, {}, fresh)
    assert free.status == "bad" and free.primary["value"] == 0
    assert {row["label"]: row["value"] for row in free.secondary}["Ends"] == "?"


@respx.mock
async def test_torrents_show_their_progress_and_what_holds_them_up(ctx: Context) -> None:
    route = respx.get(f"{API}/torrents").mock(return_value=httpx.Response(200, json=TORRENTS))
    data = await get_adapter("realdebrid").fetch("torrents", CONFIG, {"limit": 5}, ctx)
    params = route.calls.last.request.url.params
    assert params["filter"] == "active" and params["limit"] == "5"
    assert [(row["title"], row["status"], row["value"]) for row in data.items] == [
        ("Example.Linux.Distro.iso", "ok", "42%"),
        ("Open.Movie.Project", "warn", "0%"),
        ("Broken.Upload", "bad", "0%"),
    ]
    assert data.items[0]["subtitle"] == "4.1 GB · downloading · 36.2 MB/s"
    assert data.items[1]["subtitle"] == "19.6 GB · waiting for a file selection"
    assert data.status == "bad" and data.meta["status_reason"] == "1 torrent(s) failed"


@respx.mock
async def test_all_torrents_ask_without_the_filter(ctx: Context) -> None:
    route = respx.get(f"{API}/torrents").mock(return_value=httpx.Response(200, json=[]))
    data = await get_adapter("realdebrid").fetch("torrents", CONFIG, {"show": "all"}, ctx)
    assert "filter" not in route.calls.last.request.url.params
    assert data.items == [] and data.meta["empty"] == "No torrents on the account."


@respx.mock
async def test_an_empty_list_may_come_as_no_content(ctx: Context) -> None:
    respx.get(f"{API}/downloads").mock(return_value=httpx.Response(204))
    data = await get_adapter("realdebrid").fetch("downloads", CONFIG, {}, ctx)
    assert data.items == [] and data.meta["empty"] == "Nothing unrestricted yet."


@respx.mock
async def test_the_latest_downloads_name_hoster_and_size(ctx: Context) -> None:
    generated = (datetime.now(UTC) - timedelta(minutes=20)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    respx.get(f"{API}/downloads").mock(return_value=httpx.Response(200, json=[
        {"id": "L1", "filename": "talk.mp4", "mimeType": "video/mp4", "filesize": 640_000_000, "link": "https://example.com/f/1",
         "host": "example.com", "chunks": 16, "download": "https://example.com/d/1", "streamable": 1, "generated": generated}]))
    data = await get_adapter("realdebrid").fetch("downloads", CONFIG, {}, ctx)
    assert [(row["title"], row["subtitle"], row["value"]) for row in data.items] == [("talk.mp4", "example.com · 610.4 MB", "20 min")]


@respx.mock
async def test_refusals_say_what_they_mean(ctx: Context) -> None:
    adapter = get_adapter("realdebrid")
    respx.get(f"{API}/user").mock(return_value=httpx.Response(401, json={"error": "bad_token", "error_code": 8}))
    with pytest.raises(AuthFailed):
        await adapter.test(CONFIG, ctx)
    respx.get(f"{API}/user").mock(return_value=httpx.Response(403, json={"error": "ip_not_allowed", "error_code": 22}))
    with pytest.raises(AdapterError) as caught:
        await adapter.test(CONFIG, ctx)
    assert caught.value.code == "ip_refused" and "VPN" in (caught.value.hint or "")
    respx.get(f"{API}/user").mock(return_value=httpx.Response(403, json={"error": "account_locked", "error_code": 14}))
    with pytest.raises(AdapterError, match="locked"):
        await adapter.test(CONFIG, ctx)
    respx.get(f"{API}/user").mock(return_value=httpx.Response(429, json={"error": "too_many_requests", "error_code": 34}))
    with pytest.raises(AdapterError) as caught:
        await adapter.test(CONFIG, ctx)
    assert caught.value.code == "rate_limited"


@respx.mock
async def test_the_connection_test_names_the_account(ctx: Context) -> None:
    respx.get(f"{API}/user").mock(return_value=httpx.Response(200, json=user(41.5)))
    assert await get_adapter("realdebrid").test(CONFIG, ctx) == "Real-Debrid answers for example, premium for 41 more day(s)."


def test_the_demo_fills_every_card() -> None:
    adapter = get_adapter("realdebrid")
    assert adapter.demo("account", {}, 1).primary["label"] == "Premium days"
    assert adapter.demo("torrents", {}, 1).items
    assert adapter.demo("downloads", {}, 1).items
    assert len(adapter.demo("traffic", {}, 1).items) == 7
    assert adapter.demo("limits", {}, 1).items


GIB = 1024 ** 3


@respx.mock
async def test_data_used_draws_a_bar_for_each_day_and_counts_a_missing_one_as_nothing(ctx: Context) -> None:
    from app.adapters import realdebrid

    today = realdebrid._today()
    yesterday = (today - timedelta(days=1)).isoformat()
    route = respx.get(f"{API}/traffic/details").mock(return_value=httpx.Response(200, json={
        today.isoformat(): {"host": {"real-debrid.com": 3 * GIB, "1fichier.com": GIB // 2}, "bytes": 3 * GIB + GIB // 2},
        yesterday: {"host": {"1fichier.com": 12 * GIB}, "bytes": 12 * GIB},
    }))
    data = await get_adapter("realdebrid").fetch("traffic", CONFIG, {"days": "7"}, ctx)
    params = route.calls.last.request.url.params
    assert params["end"] == today.isoformat() and params["start"] == (today - timedelta(days=6)).isoformat()
    assert [row["title"] for row in data.items] == [(today - timedelta(days=back)).isoformat() for back in range(7)]
    assert [row["value"] for row in data.items] == [3.5, 12.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    assert {row["unit"] for row in data.items} == {" GB"}
    assert data.primary == {"label": "Today", "value": "3.5 GB"}
    assert {row["label"]: row["value"] for row in data.secondary} == {"7 days": "15.5 GB", "Most from": "1fichier.com"}


@respx.mock
async def test_data_used_takes_no_more_days_than_offered(ctx: Context) -> None:
    route = respx.get(f"{API}/traffic/details").mock(return_value=httpx.Response(200, json={}))
    data = await get_adapter("realdebrid").fetch("traffic", CONFIG, {"days": "365"}, ctx)
    params = route.calls.last.request.url.params
    assert len(data.items) == 7
    assert (datetime.fromisoformat(params["end"]) - datetime.fromisoformat(params["start"])).days == 6
    assert data.primary["value"] == "0 B" and [row["label"] for row in data.secondary] == ["7 days"]


TRAFFIC = {
    "1fichier.com": {"left": 12 * GIB, "bytes": 88 * GIB, "links": 14, "limit": 100, "type": "gigabytes", "extra": 0, "reset": "daily"},
    "rapidgator.net": {"left": 40 * GIB, "bytes": 10 * GIB, "links": 2, "limit": 50, "type": "gigabytes", "extra": 0, "reset": "daily"},
    "example-hoster.com": {"left": 0, "bytes": 0, "links": 20, "limit": 20, "type": "links", "extra": 0, "reset": "weekly"},
    "quiet-hoster.com": {"left": 50 * GIB, "bytes": 0, "links": 0, "limit": 50, "type": "gigabytes", "extra": 0, "reset": "monthly"},
}


@respx.mock
async def test_hoster_limits_show_what_is_used_against_what_is_left(ctx: Context) -> None:
    respx.get(f"{API}/traffic").mock(return_value=httpx.Response(200, json=TRAFFIC))
    data = await get_adapter("realdebrid").fetch("limits", CONFIG, {}, ctx)
    assert [(row["title"], row["value"], row["status"]) for row in data.items] == [
        ("example-hoster.com", "100%", "bad"),
        ("1fichier.com", "88%", "warn"),
        ("rapidgator.net", "20%", "ok"),
    ]
    assert data.items[0]["subtitle"] == "20 of 20 links · resets weekly"
    assert data.items[1]["subtitle"] == "88.0 GB of 100.0 GB · resets daily"
    assert data.items[1]["progress"] == 88.0
    assert data.status == "bad" and data.meta["status_reason"] == "A hoster has reached its limit."


@respx.mock
async def test_hoster_limits_can_show_the_unused_ones_too(ctx: Context) -> None:
    respx.get(f"{API}/traffic").mock(return_value=httpx.Response(200, json={"quiet-hoster.com": TRAFFIC["quiet-hoster.com"]}))
    adapter = get_adapter("realdebrid")
    used = await adapter.fetch("limits", CONFIG, {}, ctx)
    assert used.items == [] and used.meta["empty"] == "No hoster with a limit was used in its current period."
    every = await adapter.fetch("limits", CONFIG, {"show": "all"}, Context(outbound_client(guard=False), integration_id=1, widget_id=1, cache={}))
    assert [(row["title"], row["value"], row["subtitle"]) for row in every.items] == [("quiet-hoster.com", "0%", "0 B of 50.0 GB · resets monthly")]
    assert every.status == "ok"
