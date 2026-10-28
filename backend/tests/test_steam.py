"""Steam, against the answers Valve's documentation describes.

⚠️ Not measured: Steam needs a key tied to an account, and there is none to
run it with. The fixtures follow the documented shapes of the Web API with
invented Steam IDs and names, so these tests hold the card to the
documentation and prove nothing about the live service.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context, Unreachable

KEY = "key-for-the-cards"
ME = "76561198000000001"
CONFIG = {"api_key": KEY, "steam_id": ME}
ADAPTER = get_adapter("steam")
API = "https://api.steampowered.com"

FRIENDS = {"friendslist": {"friends": [{"steamid": f"7656119800000000{n}", "relationship": "friend", "friend_since": 1700000000} for n in (2, 3, 4, 5)]}}
PLAYERS = [
    {"steamid": "76561198000000002", "personaname": "Robin", "personastate": 0, "profileurl": "https://steamcommunity.com/id/example-robin/"},
    {"steamid": "76561198000000003", "personaname": "Sam", "personastate": 3, "profileurl": "https://steamcommunity.com/id/example-sam/"},
    {"steamid": "76561198000000004", "personaname": "Kim", "personastate": 1, "gameextrainfo": "Space Trucker", "gameid": "1",
     "profileurl": "https://steamcommunity.com/id/example-kim/"},
    {"steamid": "76561198000000005", "personaname": "Alex", "personastate": 1, "profileurl": "https://steamcommunity.com/id/example-alex/"},
]
RECENT = {"response": {"total_count": 2, "games": [
    {"appid": 10, "name": "Card Garden", "playtime_2weeks": 90, "playtime_forever": 300},
    {"appid": 11, "name": "Factory Builder", "playtime_2weeks": 840, "playtime_forever": 12100},
]}}


def server(*, friends_status: int = 200, key_ok: bool = True, recent: dict[str, Any] | None = None) -> list[httpx.Request]:
    seen: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.params.get("key") != KEY or not key_ok:
            return httpx.Response(403, text="<html><head><title>Forbidden</title></head><body><h1>Forbidden</h1></body></html>")
        path = request.url.path
        if path.endswith("GetFriendList/v1"):
            return httpx.Response(friends_status, json=FRIENDS) if friends_status == 200 else httpx.Response(friends_status, text="Unauthorized")
        if path.endswith("GetPlayerSummaries/v2"):
            wanted = request.url.params["steamids"].split(",")
            return httpx.Response(200, json={"response": {"players": [one for one in PLAYERS + [{"steamid": ME, "personaname": "Me"}] if one["steamid"] in wanted]}})
        if path.endswith("GetRecentlyPlayedGames/v1"):
            return httpx.Response(200, json=RECENT if recent is None else recent)
        return httpx.Response(404, text="Not Found")

    respx.get(url__startswith=API).mock(side_effect=answer)
    return seen


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


@respx.mock
async def test_the_connection_test_names_the_profile_and_counts_the_friends(ctx: Context) -> None:
    server()
    assert await ADAPTER.test(CONFIG, ctx) == "Steam answers for Me with 4 friends."


@respx.mock
async def test_a_profile_name_instead_of_the_number_is_said_before_anything_is_asked(ctx: Context) -> None:
    seen = server()
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.test({**CONFIG, "steam_id": "gaben"}, ctx)
    assert caught.value.code == "bad_steam_id" and seen == []


@respx.mock
async def test_the_overview_counts_friends_online_in_a_game_and_the_hours_of_two_weeks(ctx: Context) -> None:
    server()
    card = await ADAPTER.fetch("summary", CONFIG, {}, ctx)
    # Sam is away, Kim plays and Alex is online; Robin is offline.
    assert card.primary == {"label": "Online", "value": 3}
    assert card.secondary == [
        {"label": "In a game", "value": 1, "part": "playing"},
        {"label": "Friends", "value": 4, "part": "friends"},
        {"label": "Played in two weeks", "value": "15.5 h", "part": "hours"},
    ]
    assert card.metrics == {"friends_online": 3.0}


@respx.mock
async def test_the_friends_card_puts_the_players_first_and_leaves_the_offline_out_unless_asked(ctx: Context) -> None:
    server()
    card = await ADAPTER.fetch("friends", CONFIG, {}, ctx)
    assert [(row["title"], row["subtitle"], row["value"]) for row in card.items] == [
        ("Kim", "Space Trucker", "Playing"), ("Alex", "", "Online"), ("Sam", "", "Away")]
    assert card.items[0]["url"] == "https://steamcommunity.com/id/example-kim/"
    ctx.cache.clear()
    everyone = await ADAPTER.fetch("friends", CONFIG, {"offline": True}, ctx)
    assert [row["title"] for row in everyone.items][-1] == "Robin" and everyone.items[-1]["status"] == "unknown"


@respx.mock
async def test_recently_played_games_come_with_the_hours_of_two_weeks_first(ctx: Context) -> None:
    seen = server()
    card = await ADAPTER.fetch("recent", CONFIG, {"limit": 5}, ctx)
    assert [(row["title"], row["value"], row["subtitle"]) for row in card.items] == [
        ("Factory Builder", "14.0 h", "201.7 h"), ("Card Garden", "1.5 h", "5.0 h")]
    assert seen[0].url.params["count"] == "5" and seen[0].url.params["steamid"] == ME


@respx.mock
async def test_a_private_friends_list_is_not_taken_for_a_wrong_key(ctx: Context) -> None:
    # ⚠️ Documented: 401 for a hidden list, 403 for a wrong key.
    server(friends_status=401)
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.fetch("friends", CONFIG, {}, ctx)
    assert caught.value.code == "private_profile" and not isinstance(caught.value, AuthFailed)


@respx.mock
async def test_a_wrong_key_is_an_authentication_failure(ctx: Context) -> None:
    server()
    with pytest.raises(AuthFailed):
        await ADAPTER.fetch("recent", {**CONFIG, "api_key": "wrong"}, {}, ctx)


@respx.mock
async def test_an_unreachable_service_is_reported_as_such(ctx: Context) -> None:
    respx.get(url__startswith=API).mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(Unreachable):
        await ADAPTER.fetch("summary", CONFIG, {}, ctx)


@respx.mock
async def test_hidden_game_details_give_an_empty_card_and_not_an_error(ctx: Context) -> None:
    # Documented: the answer is an empty response without total_count.
    server(recent={"response": {}})
    card = await ADAPTER.fetch("recent", CONFIG, {}, ctx)
    assert card.items == [] and card.meta["empty"]


def test_the_demo_has_a_card_for_every_widget() -> None:
    for widget in ADAPTER.widgets:
        data: Any = ADAPTER.demo(widget.kind, {}, 3)
        assert data.primary or data.items
