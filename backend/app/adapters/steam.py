"""Steam: which friends are online and in which game, and what was played in the last two weeks.

⚠️ NOT MEASURED. Steam's Web API needs a key tied to a Steam account (made at
steamcommunity.com/dev/apikey) and an account with friends and games, and
nothing here could be run against it. Everything below is taken from Valve's
documentation of the Web API (partner.steamgames.com/doc/webapi) and is
unchecked until somebody runs it against their own account.

What the documentation says, and what the card relies on:

* ``ISteamUser/GetFriendList/v1`` (``key``, ``steamid``, ``relationship=friend``)
  answers ``{"friendslist": {"friends": [{"steamid": ..., "relationship":
  "friend", "friend_since": ...}]}}``. For a profile whose friends list is
  private it is HTTP 401, which is not a wrong key: the card says so.
* ``ISteamUser/GetPlayerSummaries/v2`` (``key``, ``steamids`` comma separated,
  at most 100) answers ``{"response": {"players": [...]}}`` with
  ``personaname``, ``personastate`` (0 offline, 1 online, 2 busy, 3 away,
  4 snooze, 5 looking to trade, 6 looking to play), ``gameextrainfo`` (the
  name of the game being played, absent otherwise) and ``lastlogoff``.
  A private profile shows ``personastate`` 0 whatever it is doing.
* ``IPlayerService/GetRecentlyPlayedGames/v1`` (``key``, ``steamid``,
  ``count``) answers ``{"response": {"total_count": n, "games": [...]}}``,
  each game with ``name``, ``playtime_2weeks`` and ``playtime_forever`` in
  minutes. With the game details of the account set to private the answer is
  an empty ``response`` without ``total_count``.
* A wrong key is HTTP 403 with an HTML page.

The key can only travel as the query parameter ``key``; nexdeck takes it out
of the logs (``services/journal.py``). It is sent to api.steampowered.com
only, over HTTPS.
"""

from __future__ import annotations

from typing import Any

from . import demo as fake
from .base import (
    Adapter,
    AdapterError,
    AuthFailed,
    Context,
    Field,
    WidgetData,
    WidgetType,
)

API = "https://api.steampowered.com"
STATES = {1: "Online", 2: "Busy", 3: "Away", 4: "Snooze", 5: "Looking to trade", 6: "Looking to play"}
KEY_HINT = "Make a key at steamcommunity.com/dev/apikey and paste it here."


def _hours(minutes: Any) -> float:
    try:
        return round(float(minutes) / 60, 1)
    except (TypeError, ValueError):
        return 0.0


class SteamAdapter(Adapter):
    kind = "steam"
    label = "Steam"
    category = "other"
    description = "Which of your Steam friends are online and what they play, and what you played in the last two weeks."
    icon = "steam"
    beta = True
    docs_url = "https://partner.steamgames.com/doc/webapi_overview"
    fields = (
        Field("api_key", "Web API key", type="password", secret=True, required=True,
              help="From steamcommunity.com/dev/apikey. Sent to api.steampowered.com only."),
        Field("steam_id", "Steam ID", required=True, placeholder="76561198000000000",
              help="Your 17-digit Steam ID (steamid.io finds it). The friends list and the game details of the profile have to be public."),
    )
    widgets = (
        WidgetType(kind="summary", label="Steam", description="How many friends are online, with those in a game and the hours played in two weeks.",
                   renderer="value", default_size=(3, 2), refresh_seconds=300, metrics=("friends_online",),
                   parts=(("playing", "In a game"), ("friends", "Friends"), ("hours", "Played in two weeks"))),
        WidgetType(kind="friends", label="Friends", description="Your friends who are online, the ones in a game first, with the game.",
                   renderer="list", default_size=(3, 3), refresh_seconds=120,
                   options=(Field("limit", "Entries", type="number", default=10),
                            Field("offline", "Show friends who are offline too", type="bool", default=False))),
        WidgetType(kind="recent", label="Recently played", description="The games you played in the last two weeks, with the hours then and in total.",
                   renderer="list", default_size=(3, 3), refresh_seconds=900,
                   options=(Field("limit", "Entries", type="number", default=8),)),
    )

    #: The Web API has one address of its own, and the key travels in the query of every request.
    raw_root = API

    def raw_params(self, config: dict[str, Any]) -> dict[str, Any]:
        return {"key": str(config.get("api_key") or "")}

    def default_link(self, config: dict[str, Any]) -> str:
        return "https://steamcommunity.com/"

    # -- talking to Steam ----------------------------------------------------

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, params: dict[str, Any], cache: float = 60) -> dict[str, Any]:
        response = await ctx.request(
            "GET", f"{API}/{path}", params={"key": str(config.get("api_key") or ""), "format": "json", **params},
            cache_seconds=cache, auth_errors=False,
        )
        if response.status_code == 403:
            raise AuthFailed("Steam rejected the Web API key.")
        if response.status_code == 401:
            # ⚠️ Not a wrong key: the profile hides this list. See the top of the file.
            raise AdapterError("Steam says this profile is private.", code="private_profile",
                               hint="Set the friends list and the game details of the profile to public, in Steam under Edit Profile > Privacy Settings.")
        if response.status_code >= 400:
            raise AdapterError(f"Steam answered with HTTP {response.status_code}.", code="http_error", hint=KEY_HINT)
        try:
            answer = response.json()
        except ValueError as error:
            raise AdapterError("Steam did not answer with JSON.", code="not_json", hint=KEY_HINT) from error
        if not isinstance(answer, dict):
            raise AdapterError("Steam answered in a way the card does not know.", code="not_steam")
        return answer

    async def _friends(self, config: dict[str, Any], ctx: Context) -> list[dict[str, Any]]:
        """Every friend with the summary of his or her profile."""
        listed = await self._get(config, ctx, "ISteamUser/GetFriendList/v1",
                                 {"steamid": str(config.get("steam_id") or "").strip(), "relationship": "friend"})
        ids = [str(one.get("steamid")) for one in (listed.get("friendslist") or {}).get("friends") or [] if isinstance(one, dict) and one.get("steamid")]
        players: list[dict[str, Any]] = []
        for start in range(0, len(ids), 100):
            answer = await self._get(config, ctx, "ISteamUser/GetPlayerSummaries/v2", {"steamids": ",".join(ids[start:start + 100])})
            players += [one for one in (answer.get("response") or {}).get("players") or [] if isinstance(one, dict)]
        return players

    async def _recent(self, config: dict[str, Any], ctx: Context, count: int = 0) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"steamid": str(config.get("steam_id") or "").strip()}
        if count:
            params["count"] = count
        answer = await self._get(config, ctx, "IPlayerService/GetRecentlyPlayedGames/v1", params)
        return [one for one in (answer.get("response") or {}).get("games") or [] if isinstance(one, dict)]

    # -- the hooks -----------------------------------------------------------

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        if not str(config.get("steam_id") or "").strip().isdigit():
            raise AdapterError("The Steam ID is the 17-digit number, not the profile name.", code="bad_steam_id",
                               hint="steamid.io turns a profile address into the number.")
        answer = await self._get(config, ctx, "ISteamUser/GetPlayerSummaries/v2", {"steamids": str(config["steam_id"]).strip()}, cache=0)
        players = (answer.get("response") or {}).get("players") or []
        if not players:
            raise AdapterError("Steam knows no profile with this Steam ID.", code="no_such_profile")
        friends = await self._friends(config, ctx)
        return f"Steam answers for {players[0].get('personaname') or '?'} with {len(friends)} friends."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "recent":
            return self._recent_card(await self._recent(config, ctx, max(1, min(30, int(options.get("limit") or 8)))))
        friends = await self._friends(config, ctx)
        if widget_kind == "friends":
            return self._friends_card(friends, options)
        return self._summary(friends, await self._recent(config, ctx))

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def _summary(friends: list[dict[str, Any]], recent: list[dict[str, Any]]) -> WidgetData:
        online = [one for one in friends if one.get("personastate") not in (0, None)]
        playing = sum(1 for one in online if one.get("gameextrainfo"))
        hours = round(sum(_hours(one.get("playtime_2weeks")) for one in recent), 1)
        return WidgetData(
            status="ok",
            primary={"label": "Online", "value": len(online)},
            secondary=[
                {"label": "In a game", "value": playing, "part": "playing"},
                {"label": "Friends", "value": len(friends), "part": "friends"},
                {"label": "Played in two weeks", "value": f"{hours} h", "part": "hours"},
            ],
            link="https://steamcommunity.com/",
            metrics={"friends_online": float(len(online))},
        )

    @staticmethod
    def _friends_card(friends: list[dict[str, Any]], options: dict[str, Any]) -> WidgetData:
        def order(player: dict[str, Any]) -> tuple[int, str]:
            state = player.get("personastate")
            return (0 if player.get("gameextrainfo") else 1 if state not in (0, None) else 2, str(player.get("personaname") or "").lower())

        shown = sorted(friends, key=order)
        if options.get("offline") is not True:
            shown = [one for one in shown if one.get("personastate") not in (0, None)]
        items = []
        for player in shown[: max(1, int(options.get("limit") or 10))]:
            game = str(player.get("gameextrainfo") or "")
            state = player.get("personastate")
            row: dict[str, Any] = {
                "title": str(player.get("personaname") or "?"),
                "subtitle": game,
                "value": "Playing" if game else STATES.get(state, "Offline") if isinstance(state, int) else "Offline",
                "status": "ok" if game else "unknown" if state in (0, None) else "ok",
            }
            if player.get("profileurl"):
                row["url"] = str(player["profileurl"])
            items.append(row)
        return WidgetData(status="ok", items=items, link="https://steamcommunity.com/", meta={"empty": "No friend is online."})

    @staticmethod
    def _recent_card(games: list[dict[str, Any]]) -> WidgetData:
        items = [{
            "title": str(game.get("name") or game.get("appid") or "?"),
            "subtitle": f"{_hours(game.get('playtime_forever'))} h",
            "value": f"{_hours(game.get('playtime_2weeks'))} h",
        } for game in sorted(games, key=lambda one: -(one.get("playtime_2weeks") or 0))]
        return WidgetData(status="ok", items=items, link="https://steamcommunity.com/", meta={"empty": "Nothing played in the last two weeks."})

    # -- demo ----------------------------------------------------------------

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        away = fake.flicker("steam-away", tick, 0.3)
        friends = [
            {"personaname": "Alex", "personastate": 1, "gameextrainfo": "Factory Builder" if not away else "", "profileurl": "https://steamcommunity.com/id/example-alex/"},
            {"personaname": "Sam", "personastate": 3},
            {"personaname": "Robin", "personastate": 0},
            {"personaname": "Kim", "personastate": 1, "gameextrainfo": "Space Trucker"},
        ]
        games = [
            {"name": "Factory Builder", "playtime_2weeks": 840 + tick % 5, "playtime_forever": 12100},
            {"name": "Space Trucker", "playtime_2weeks": 210, "playtime_forever": 960},
            {"name": "Card Garden", "playtime_2weeks": 45, "playtime_forever": 300},
        ]
        if widget_kind == "friends":
            return self._friends_card(friends, options)
        if widget_kind == "recent":
            return self._recent_card(games)
        return self._summary(friends, games)


ADAPTER = SteamAdapter()
