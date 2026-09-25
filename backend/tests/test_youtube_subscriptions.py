"""The YouTube Subscriptions card: the list once a day through the Data API, the videos from the free feeds."""

from __future__ import annotations

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, Context

KEY = "test-youtube-data-api-key"
ACCOUNT = "UCaccountaccountaccount0"
SUBSCRIPTIONS = "https://www.googleapis.com/youtube/v3/subscriptions"
FEED = "https://www.youtube.com/feeds/videos.xml"


def atom(title: str, video: str, published: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:media="http://search.yahoo.com/mrss/" xmlns="http://www.w3.org/2005/Atom">
  <title>{title}</title>
  <entry>
    <title>{video}</title>
    <link rel="alternate" href="https://www.youtube.com/watch?v={video[:3]}"/>
    <published>{published}</published>
  </entry>
</feed>"""


def page(*channels: tuple[str, str]) -> dict:
    return {"items": [{"snippet": {"title": name, "resourceId": {"kind": "youtube#channel", "channelId": channel}}} for channel, name in channels]}


def _ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=3, widget_id=1, cache={})


def _feeds() -> respx.Route:
    def answer(request: httpx.Request) -> httpx.Response:
        channel = request.url.params["channel_id"]
        if channel == "UCrackrackrackrackrackr0":
            return httpx.Response(200, text=atom("Rack Notes", "Silent switch", "2026-09-20T10:00:00+00:00"))
        if channel == "UCdiarydiarydiarydiaryd0":
            return httpx.Response(200, text=atom("Homelab Diary", "One small box", "2026-09-22T10:00:00+00:00"))
        return httpx.Response(404)

    return respx.get(FEED).mock(side_effect=answer)


@respx.mock
async def test_the_followed_channels_come_from_the_api_and_their_videos_from_the_feeds() -> None:
    listing = respx.get(SUBSCRIPTIONS).mock(return_value=httpx.Response(200, json=page(
        ("UCrackrackrackrackrackr0", "Rack Notes"), ("UCdiarydiarydiarydiaryd0", "Homelab Diary"))))
    feeds = _feeds()
    youtube = get_adapter("youtube")
    ctx = _ctx()
    card = await youtube.fetch("subscriptions", {"api_key": KEY}, {"account": ACCOUNT, "channels_read": 10}, ctx)
    assert [(entry["title"], entry["source"]) for entry in card.items] == [("One small box", "Homelab Diary"), ("Silent switch", "Rack Notes")]
    asked = listing.calls.last.request
    assert asked.headers["X-Goog-Api-Key"] == KEY
    assert KEY not in str(asked.url), "the key stays out of the address, which goes into the log"
    assert dict(asked.url.params) == {"part": "snippet", "channelId": ACCOUNT, "maxResults": "10", "order": "unread"}
    # A second refresh asks the list no more today, and the feeds not within half an hour.
    await youtube.fetch("subscriptions", {"api_key": KEY}, {"account": ACCOUNT, "channels_read": 10}, ctx)
    assert listing.call_count == 1 and feeds.call_count == 2


@respx.mock
async def test_a_handle_is_looked_up_on_the_channel_page_not_through_the_quota() -> None:
    respx.get("https://www.youtube.com/@HomelabDiary").mock(return_value=httpx.Response(
        200, text='<link rel="canonical" href="https://www.youtube.com/channel/UCaccountaccountaccount0">'))
    api = respx.get(url__startswith="https://www.googleapis.com/youtube/v3/").mock(return_value=httpx.Response(200, json=page()))
    card = await get_adapter("youtube").fetch("subscriptions", {"api_key": KEY}, {"account": "@HomelabDiary"}, _ctx())
    assert card.items == []
    assert [call.request.url.path for call in api.calls] == ["/youtube/v3/subscriptions"]
    assert api.calls.last.request.url.params["channelId"] == ACCOUNT


@respx.mock
async def test_a_feed_that_fails_is_a_line_and_the_rest_still_shows() -> None:
    respx.get(SUBSCRIPTIONS).mock(return_value=httpx.Response(200, json=page(
        ("UCrackrackrackrackrackr0", "Rack Notes"), ("UCgonegonegonegonegone00", "Gone Channel"))))
    _feeds()
    card = await get_adapter("youtube").fetch("subscriptions", {"api_key": KEY}, {"account": ACCOUNT}, _ctx())
    assert [entry["title"] for entry in card.items] == ["Silent switch"]
    assert card.meta["failures"] == ["Gone Channel: HTTP 404"] and card.status == "ok"


@pytest.mark.parametrize(("status", "reason", "code"), [
    (403, "subscriptionForbidden", "subscriptions_private"),
    (403, "quotaExceeded", "quota"),
    (403, "accessNotConfigured", "api_disabled"),
    (404, "subscriberNotFound", "not_found"),
])
@respx.mock
async def test_each_refusal_says_what_to_do(status: int, reason: str, code: str) -> None:
    respx.get(SUBSCRIPTIONS).mock(return_value=httpx.Response(status, json={
        "error": {"code": status, "message": "The request cannot be completed.", "errors": [{"domain": "youtube", "reason": reason}]}}))
    with pytest.raises(AdapterError) as refused:
        await get_adapter("youtube").fetch("subscriptions", {"api_key": KEY}, {"account": ACCOUNT}, _ctx())
    assert refused.value.code == code
    if code == "subscriptions_private":
        assert "Keep all my subscriptions private" in (refused.value.hint or "")


@respx.mock
async def test_a_key_youtube_does_not_take_is_a_refused_key() -> None:
    from app.adapters.base import AuthFailed

    respx.get(SUBSCRIPTIONS).mock(return_value=httpx.Response(400, json={"error": {
        "code": 400, "message": "API key not valid. Please pass a valid API key.", "errors": [{"reason": "badRequest"}],
        "status": "INVALID_ARGUMENT", "details": [{"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": "API_KEY_INVALID"}]}}))
    with pytest.raises(AuthFailed):
        await get_adapter("youtube").fetch("subscriptions", {"api_key": KEY}, {"account": ACCOUNT}, _ctx())


@respx.mock
async def test_without_key_or_account_nothing_goes_out() -> None:
    youtube = get_adapter("youtube")
    with pytest.raises(AdapterError) as no_key:
        await youtube.fetch("subscriptions", {}, {"account": ACCOUNT}, _ctx())
    assert no_key.value.code == "missing_key"
    with pytest.raises(AdapterError) as no_account:
        await youtube.fetch("subscriptions", {"api_key": KEY}, {}, _ctx())
    assert no_account.value.code == "missing_account"
    assert respx.calls.call_count == 0


@respx.mock
async def test_the_connection_test_asks_the_api_with_a_key_and_the_feed_without() -> None:
    channels = respx.get("https://www.googleapis.com/youtube/v3/channels").mock(return_value=httpx.Response(200, json={"items": [{"id": "x"}]}))
    feed = respx.get(FEED).mock(return_value=httpx.Response(200, text=atom("x", "y", "2026-09-22T10:00:00+00:00")))
    youtube = get_adapter("youtube")
    assert await youtube.test({"api_key": KEY}, _ctx()) == "YouTube accepts the API key."
    assert channels.calls.last.request.headers["X-Goog-Api-Key"] == KEY
    assert await youtube.test({}, _ctx()) == "YouTube hands out its channel feeds." and feed.call_count == 1
