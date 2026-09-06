"""Wake-on-LAN and the content feeds.

The feeds all talk to somebody else's service, so every parser here is held
against a recorded answer. What bites in this corner is not the shape but the
refusals: GitHub counts requests
per address, and a project without a release is not a failure.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context
from app.adapters.wol import mac_bytes, magic_packet


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


# -- wake-on-lan ---------------------------------------------------------------


def test_the_magic_packet_is_six_ones_and_the_address_sixteen_times() -> None:
    packet = magic_packet(mac_bytes("00:1A:2B:3C:4D:5E"))
    assert len(packet) == 102
    assert packet[:6] == b"\xff" * 6
    assert packet[6:12] == b"\x00\x1a\x2b\x3c\x4d\x5e"
    assert packet[6:] == b"\x00\x1a\x2b\x3c\x4d\x5e" * 16


@pytest.mark.parametrize("text", ["", "00:1A:2B:3C:4D", "hello", "00-1A-2B-3C-4D-5G", "001A2B3C4D5E"])
def test_a_wrong_mac_address_is_refused_before_anything_is_sent(text: str) -> None:
    with pytest.raises(AdapterError) as refused:
        mac_bytes(text)
    assert refused.value.code == "bad_mac"


def test_a_mac_with_dashes_is_read_too() -> None:
    assert mac_bytes("00-1A-2B-3C-4D-5E") == b"\x00\x1a\x2b\x3c\x4d\x5e"


async def test_wake_sends_one_packet_to_the_broadcast(ctx: Context, monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[tuple[bytes, str, int]] = []
    monkeypatch.setattr("app.adapters.wol._send", lambda packet, broadcast, port: sent.append((packet, broadcast, port)))
    config = {"mac": "00:1A:2B:3C:4D:5E", "broadcast": "192.0.2.255", "port": 9}
    message = await get_adapter("wol").action("wake", "wake", {}, config, {}, ctx)
    assert len(sent) == 1
    packet, broadcast, port = sent[0]
    assert broadcast == "192.0.2.255" and port == 9
    assert packet == magic_packet(mac_bytes("00:1A:2B:3C:4D:5E"))
    assert "192.0.2.255:9" in message


async def test_the_card_says_whether_the_machine_answers(ctx: Context, monkeypatch: pytest.MonkeyPatch) -> None:
    async def awake(host: str, port: int, timeout: float = 2.0) -> bool:
        return host == "workstation" and port == 22

    monkeypatch.setattr("app.adapters.wol.reachable", awake)
    wol = get_adapter("wol")
    up = await wol.fetch("wake", {"mac": "00:1A:2B:3C:4D:5E", "host": "workstation", "check_port": 22}, {}, ctx)
    assert up.status == "ok" and up.primary["label"] == "Awake" and up.metrics == {"awake": 1.0}
    down = await wol.fetch("wake", {"mac": "00:1A:2B:3C:4D:5E", "host": "workstation", "check_port": 3389}, {}, ctx)
    assert down.status == "warn" and down.meta["status_reason"] == "The machine is asleep."
    # Without an address there is nothing to check, and that is not a fault.
    blind = await wol.fetch("wake", {"mac": "00:1A:2B:3C:4D:5E"}, {}, ctx)
    assert blind.status == "unknown" and blind.meta["status_reason"] == ""
    assert [action.id for action in blind.actions] == ["wake"]


# -- hacker news ---------------------------------------------------------------

HN = {"hits": [
    {"objectID": "1", "title": "A story with a link", "url": "https://example.com/a", "points": 240, "num_comments": 61, "created_at_i": 1788600000},
    {"objectID": "2", "title": "Ask HN: a story without one", "points": 12, "num_comments": 4, "created_at_i": 1788590000},
]}


@respx.mock
async def test_hacker_news_takes_the_whole_page_in_one_request(ctx: Context) -> None:
    respx.get("https://hn.algolia.com/api/v1/search").mock(return_value=httpx.Response(200, json=HN))
    data = await get_adapter("hackernews").fetch("stories", {}, {"limit": 5}, ctx)
    assert len(respx.calls) == 1, "one request for the whole card"
    assert data.items[0]["url"] == "https://example.com/a"
    assert data.items[0]["source"] == "240 points · 61 comments"
    # A story without a link is a text post; the discussion is the story.
    assert data.items[1]["url"] == "https://news.ycombinator.com/item?id=2"


@respx.mock
async def test_hacker_news_can_be_told_to_leave_the_quiet_ones_out(ctx: Context) -> None:
    respx.get("https://hn.algolia.com/api/v1/search").mock(return_value=httpx.Response(200, json=HN))
    data = await get_adapter("hackernews").fetch("stories", {}, {"limit": 5, "min_points": 100}, ctx)
    assert [item["title"] for item in data.items] == ["A story with a link"]


@respx.mock
async def test_hacker_news_asks_the_right_list(ctx: Context) -> None:
    respx.get("https://hn.algolia.com/api/v1/search_by_date").mock(return_value=httpx.Response(200, json={"hits": []}))
    await get_adapter("hackernews").fetch("stories", {}, {"source": "new"}, ctx)
    assert dict(respx.calls.last.request.url.params)["tags"] == "story"


# -- youtube -------------------------------------------------------------------

ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:media="http://search.yahoo.com/mrss/" xmlns="http://www.w3.org/2005/Atom">
  <title>Homelab Diary</title>
  <entry>
    <title>One small box</title>
    <link rel="alternate" href="https://www.youtube.com/watch?v=aaa"/>
    <published>2026-09-04T10:00:00+00:00</published>
    <media:group><media:thumbnail url="https://i.ytimg.com/vi/aaa/hq.jpg"/></media:group>
  </entry>
</feed>"""


#: Shaped like the real page: the misleading ``channelId`` of a recommended
#: video comes first, the canonical link further down is this channel.
CHANNEL_PAGE = (
    '<!DOCTYPE html><html><head><link rel="canonical" href="https://www.youtube.com/channel/UCaaaaaaaaaaaaaaaaaaaaaa">'
    '</head><body><script>var ytInitialData = {"contents":{"videoRenderer":'
    '{"channelId":"UCwrongwrongwrongwrongw","title":"a recommended video"}},'
    '"metadata":{"channelMetadataRenderer":{"externalId":"UCaaaaaaaaaaaaaaaaaaaaaa"}}};</script></body></html>'
)

#: What an EU address gets without the consent cookie.
CONSENT_WALL = "<!DOCTYPE html><html><head><title>Before you continue to YouTube</title></head><body>x</body></html>"

@respx.mock
async def test_youtube_turns_a_handle_into_the_id_the_feed_wants(ctx: Context) -> None:
    """The feed only knows channel ids. A card that refused handles would send
    people hunting through the channel's page source."""
    respx.get("https://www.youtube.com/@HomelabDiary").mock(return_value=httpx.Response(200, text=CHANNEL_PAGE))
    respx.get("https://www.youtube.com/feeds/videos.xml").mock(return_value=httpx.Response(200, text=ATOM))
    data = await get_adapter("youtube").fetch("videos", {}, {"channels": "@HomelabDiary"}, ctx)
    assert data.items[0]["title"] == "One small box"
    assert data.items[0]["source"] == "Homelab Diary"
    assert data.items[0]["image"] == "https://i.ytimg.com/vi/aaa/hq.jpg"
    assert dict(respx.calls.last.request.url.params)["channel_id"] == "UCaaaaaaaaaaaaaaaaaaaaaa"


@respx.mock
async def test_youtube_looks_a_handle_up_only_once(ctx: Context) -> None:
    page = respx.get("https://www.youtube.com/@HomelabDiary").mock(return_value=httpx.Response(200, text=CHANNEL_PAGE))
    respx.get("https://www.youtube.com/feeds/videos.xml").mock(return_value=httpx.Response(200, text=ATOM))
    youtube = get_adapter("youtube")
    await youtube.fetch("videos", {}, {"channels": "@HomelabDiary"}, ctx)
    await youtube.fetch("videos", {}, {"channels": "@HomelabDiary"}, ctx)
    assert page.call_count == 1
    # The response cache would hide a missing note, so look at the note itself.
    assert ctx.cache["yt:@HomelabDiary"] == "UCaaaaaaaaaaaaaaaaaaaaaa"


@respx.mock
async def test_youtube_reads_the_channel_and_not_a_recommended_video(ctx: Context) -> None:
    """⚠️ ``"channelId"`` appears several times and the first one is somebody
    else. Reading it gave a valid feed of the wrong person, which looks like
    the card working."""
    respx.get("https://www.youtube.com/@HomelabDiary").mock(return_value=httpx.Response(200, text=CHANNEL_PAGE))
    respx.get("https://www.youtube.com/feeds/videos.xml").mock(return_value=httpx.Response(200, text=ATOM))
    await get_adapter("youtube").fetch("videos", {}, {"channels": "@HomelabDiary"}, ctx)
    asked = dict(respx.calls.last.request.url.params)["channel_id"]
    assert asked == "UCaaaaaaaaaaaaaaaaaaaaaa"
    assert asked != "UCwrongwrongwrongwrongw", "that id belongs to a recommended video"


@respx.mock
async def test_youtube_asks_past_the_consent_wall(ctx: Context) -> None:
    """⚠️ From an EU address the channel page is the wall, not the channel.
    Without the cookie there is no id on the page at all and every handle on
    the card failed at once."""
    page = respx.get("https://www.youtube.com/@HomelabDiary").mock(return_value=httpx.Response(200, text=CHANNEL_PAGE))
    respx.get("https://www.youtube.com/feeds/videos.xml").mock(return_value=httpx.Response(200, text=ATOM))
    await get_adapter("youtube").fetch("videos", {}, {"channels": "@HomelabDiary"}, ctx)
    assert "SOCS=CAI" in page.calls.last.request.headers.get("cookie", "")


@respx.mock
async def test_youtube_says_what_to_do_when_the_page_gives_nothing(ctx: Context) -> None:
    """The wall, should the cookie ever stop being enough."""
    respx.get("https://www.youtube.com/@HomelabDiary").mock(return_value=httpx.Response(200, text=CONSENT_WALL))
    data = await get_adapter("youtube").fetch("videos", {}, {"channels": "@HomelabDiary"}, ctx)
    assert data.status == "bad"
    assert "channel ID" in (data.error or "")


@respx.mock
async def test_youtube_takes_an_id_straight_through(ctx: Context) -> None:
    respx.get("https://www.youtube.com/feeds/videos.xml").mock(return_value=httpx.Response(200, text=ATOM))
    await get_adapter("youtube").fetch("videos", {}, {"channels": "UCbbbbbbbbbbbbbbbbbbbbbb"}, ctx)
    assert len(respx.calls) == 1, "no page is fetched for an id"


# -- github --------------------------------------------------------------------


@respx.mock
async def test_github_reads_the_newest_release_of_every_project(ctx: Context) -> None:
    respx.get("https://api.github.com/repos/jellyfin/jellyfin/releases/latest").mock(return_value=httpx.Response(200, json={
        "tag_name": "10.11.12", "html_url": "https://github.com/jellyfin/jellyfin/releases/10.11.12",
        "published_at": "2026-09-01T12:00:00Z", "body": "Fixes trickplay.\nAnd more.", "prerelease": False,
    }))
    data = await get_adapter("github").fetch("releases", {}, {"repos": "jellyfin/jellyfin"}, ctx)
    assert data.items[0]["title"] == "jellyfin 10.11.12"
    assert data.items[0]["summary"] == "Fixes trickplay."
    assert data.items[0]["published"] == 1788264000


@respx.mock
async def test_github_does_not_call_a_project_without_a_release_a_failure(ctx: Context) -> None:
    respx.get("https://api.github.com/repos/owner/quiet/releases/latest").mock(return_value=httpx.Response(404, json={"message": "Not Found"}))
    respx.get("https://api.github.com/repos/owner/loud/releases/latest").mock(return_value=httpx.Response(200, json={
        "tag_name": "1.0", "published_at": "2026-09-01T12:00:00Z", "body": "",
    }))
    data = await get_adapter("github").fetch("releases", {}, {"repos": "owner/quiet\nowner/loud"}, ctx)
    assert [item["title"] for item in data.items] == ["loud 1.0"]
    assert data.status == "ok" and not data.error
    assert data.meta["failures"] == [], "a project with no release is quiet, not broken"


@respx.mock
async def test_github_says_when_the_hourly_limit_is_used_up(ctx: Context) -> None:
    respx.get("https://api.github.com/repos/owner/name/releases/latest").mock(
        return_value=httpx.Response(403, json={"message": "API rate limit exceeded for 203.0.113.1."}),
    )
    data = await get_adapter("github").fetch("releases", {}, {"repos": "owner/name"}, ctx)
    assert "limit" in (data.error or "").lower()


# -- share prices --------------------------------------------------------------


def _chart(price: float, before: float, name: str = "Apple Inc.") -> dict:
    return {"chart": {"result": [{"meta": {"regularMarketPrice": price, "chartPreviousClose": before, "currency": "USD", "shortName": name}}], "error": None}}


@respx.mock
async def test_share_prices_work_the_change_out_of_the_previous_close(ctx: Context) -> None:
    respx.get("https://query1.finance.yahoo.com/v8/finance/chart/AAPL").mock(return_value=httpx.Response(200, json=_chart(110.0, 100.0)))
    data = await get_adapter("stocks").fetch("quotes", {}, {"symbols": "AAPL"}, ctx)
    assert data.items[0]["title"] == "Apple Inc." and data.items[0]["subtitle"] == "AAPL"
    assert data.items[0]["change"] == "+10.00 %" and data.items[0]["status"] == "ok"
    assert data.items[0]["value"] == "110.00 USD"


@respx.mock
async def test_a_falling_price_is_red_and_a_flat_one_is_neither(ctx: Context) -> None:
    respx.get("https://query1.finance.yahoo.com/v8/finance/chart/DOWN").mock(return_value=httpx.Response(200, json=_chart(90.0, 100.0, "Down plc")))
    respx.get("https://query1.finance.yahoo.com/v8/finance/chart/FLAT").mock(return_value=httpx.Response(200, json=_chart(100.0, 100.0, "Flat plc")))
    data = await get_adapter("stocks").fetch("quotes", {}, {"symbols": "DOWN\nFLAT"}, ctx)
    assert [item["status"] for item in data.items] == ["bad", "unknown"]
    assert {entry["label"]: entry["value"] for entry in data.secondary} == {"Risen": "0/2"}


@respx.mock
async def test_one_dead_symbol_does_not_empty_the_card(ctx: Context) -> None:
    respx.get("https://query1.finance.yahoo.com/v8/finance/chart/GOOD").mock(return_value=httpx.Response(200, json=_chart(110.0, 100.0, "Good plc")))
    respx.get("https://query1.finance.yahoo.com/v8/finance/chart/NOPE").mock(return_value=httpx.Response(200, json={"chart": {"result": None, "error": {"description": "No data found, symbol may be delisted"}}}))
    data = await get_adapter("stocks").fetch("quotes", {}, {"symbols": "GOOD\nNOPE"}, ctx)
    assert [item["title"] for item in data.items] == ["Good plc"]
    assert data.status == "ok" and "NOPE" in str(data.meta["failures"])


# -- twitch --------------------------------------------------------------------

TWITCH_CONFIG = {"client_id": "cid", "client_secret": "secret"}


def _twitch_routes(streams: list[dict], users: list[dict]) -> None:
    respx.post("https://id.twitch.tv/oauth2/token").mock(return_value=httpx.Response(200, json={"access_token": "tok", "expires_in": 3600}))
    respx.get("https://api.twitch.tv/helix/streams").mock(return_value=httpx.Response(200, json={"data": streams}))
    respx.get("https://api.twitch.tv/helix/users").mock(return_value=httpx.Response(200, json={"data": users}))


@respx.mock
async def test_twitch_puts_the_live_channels_first(ctx: Context) -> None:
    _twitch_routes(
        [{"user_login": "northshore", "viewer_count": 1240, "game_name": "Factorio"}],
        [{"login": "northshore", "display_name": "Northshore"}, {"login": "elmstreet", "display_name": "Elmstreet"}],
    )
    data = await get_adapter("twitch").fetch("live", TWITCH_CONFIG, {"channels": "elmstreet\nnorthshore"}, ctx)
    assert [item["title"] for item in data.items] == ["Northshore", "Elmstreet"]
    assert data.items[0]["subtitle"] == "Factorio" and data.items[0]["value"] == "1.240"
    assert data.items[1]["subtitle"] == "Offline"
    assert {entry["label"]: entry["value"] for entry in data.secondary} == {"Live": 1, "Viewers": "1.240"}
    assert respx.calls[1].request.headers["Client-Id"] == "cid"


@respx.mock
async def test_twitch_asks_for_a_token_once_and_keeps_it(ctx: Context) -> None:
    token = respx.post("https://id.twitch.tv/oauth2/token").mock(return_value=httpx.Response(200, json={"access_token": "tok", "expires_in": 3600}))
    respx.get("https://api.twitch.tv/helix/streams").mock(return_value=httpx.Response(200, json={"data": []}))
    respx.get("https://api.twitch.tv/helix/users").mock(return_value=httpx.Response(200, json={"data": []}))
    twitch = get_adapter("twitch")
    await twitch.fetch("live", TWITCH_CONFIG, {"channels": "elmstreet"}, ctx)
    await twitch.fetch("live", TWITCH_CONFIG, {"channels": "elmstreet"}, ctx)
    assert token.call_count == 1, "the token is kept until it runs out"


@respx.mock
async def test_twitch_says_when_the_application_is_wrong(ctx: Context) -> None:
    respx.post("https://id.twitch.tv/oauth2/token").mock(return_value=httpx.Response(403, json={"message": "invalid client"}))
    with pytest.raises(AuthFailed):
        await get_adapter("twitch").fetch("live", TWITCH_CONFIG, {"channels": "elmstreet"}, ctx)


# -- every one of them ---------------------------------------------------------


@pytest.mark.parametrize("kind", ["wol", "hackernews", "youtube", "github", "stocks", "twitch"])
def test_every_feed_adapter_has_demo_data_for_every_widget(kind: str) -> None:
    adapter = get_adapter(kind)
    assert adapter.widgets, kind
    for widget in adapter.widgets:
        options = {field.name: field.default for field in widget.options if field.default is not None}
        for tick in (0, 7, 41):
            data = adapter.demo(widget.kind, options, tick)
            assert data.items or data.primary or data.secondary, f"{kind}/{widget.kind} at tick {tick} is empty"
