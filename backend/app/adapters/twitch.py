"""Twitch: who of the channels you follow is live right now.

The only feed here that needs credentials. They are not an account but an
application: register one at dev.twitch.tv and the client id and secret are
enough for a token that reads public data.
"""

from __future__ import annotations

import time
from typing import Any

from .base import Adapter, AdapterError, AuthFailed, Context, Field, WidgetData, WidgetType

TOKEN_URL = "https://id.twitch.tv/oauth2/token"
API = "https://api.twitch.tv/helix"


class TwitchAdapter(Adapter):
    kind = "twitch"
    label = "Twitch"
    category = "feeds"
    description = "Which of the channels you follow is live, and what they play."
    icon = "twitch"
    docs_url = "https://dev.twitch.tv/docs/api/"
    fields = (
        Field("client_id", "Client ID", required=True, help="From an application at dev.twitch.tv; no account of the channels is needed."),
        Field("client_secret", "Client secret", type="password", secret=True, required=True),
    )
    widgets = (
        WidgetType(
            kind="live",
            label="Live",
            description="One line per channel, live ones first, with viewers and game.",
            renderer="list",
            default_size=(4, 3),
            refresh_seconds=180,
            metrics=("live", "viewers"),
            options=(
                Field("channels", "Channels", type="textarea", required=True, placeholder="channelname",
                      help="One login name per line, as it stands in the address after twitch.tv/."),
                Field("only_live", "Only live", type="bool", default=False),
            ),
        ),
    )

    def default_link(self, config: dict[str, Any]) -> str:
        return "https://www.twitch.tv/"

    async def _token(self, config: dict[str, Any], ctx: Context) -> str:
        """A token of the application itself, kept until shortly before it ends."""
        kept = ctx.cache.get("twitch_token")
        if kept and float(kept[1]) > time.time():
            return str(kept[0])
        response = await ctx.request(
            "POST", TOKEN_URL,
            data={
                "client_id": str(config.get("client_id") or ""),
                "client_secret": str(config.get("client_secret") or ""),
                "grant_type": "client_credentials",
            },
            timeout=20,
            # Read the refusal here, or the card says "the service rejected the
            # credentials" and never mentions which of the two is wrong.
            auth_errors=False,
        )
        if response.status_code in (400, 401, 403):
            raise AuthFailed("Twitch rejected the client ID or the secret.")
        if response.status_code >= 400:
            raise AdapterError(f"Twitch answered with HTTP {response.status_code}.", code="http_error")
        payload = response.json() or {}
        token = str(payload.get("access_token") or "")
        if not token:
            raise AuthFailed("Twitch handed out no token.")
        ctx.cache["twitch_token"] = (token, time.time() + max(60, int(payload.get("expires_in") or 3600) - 60))
        return token

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, params: list[tuple[str, str]], cache: float = 120) -> Any:
        token = await self._token(config, ctx)
        response = await ctx.request(
            "GET", f"{API}{path}",
            headers={"Client-Id": str(config.get("client_id") or ""), "Authorization": f"Bearer {token}"},
            params=params,
            cache_seconds=cache,
            timeout=20,
        )
        if response.status_code == 401:
            # The token went stale early; drop it so the next read fetches one.
            ctx.cache.pop("twitch_token", None)
            raise AuthFailed("Twitch refused the token.")
        if response.status_code >= 400:
            raise AdapterError(f"Twitch answered with HTTP {response.status_code}.", code="http_error")
        return response.json()

    @staticmethod
    def _names(options: dict[str, Any]) -> list[str]:
        raw = [line.strip().lstrip("@").lower() for line in str(options.get("channels") or "").splitlines()]
        return [name for name in raw if name][:20]

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        await self._token(config, ctx)
        return "Twitch accepted the application and handed out a token."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        names = self._names(options)
        if not names:
            raise AdapterError("No channel is set.", code="missing_channel")
        streams = await self._get(config, ctx, "/streams", [("user_login", name) for name in names], cache=120)
        live = {str(entry.get("user_login") or "").lower(): entry for entry in (streams or {}).get("data") or []}
        users = await self._get(config, ctx, "/users", [("login", name) for name in names], cache=3600)
        titles = {str(entry.get("login") or "").lower(): entry for entry in (users or {}).get("data") or []}

        items = []
        viewers = 0
        for name in names:
            stream = live.get(name)
            person = titles.get(name) or {}
            shown = str(person.get("display_name") or name)
            if stream:
                count = int(stream.get("viewer_count") or 0)
                viewers += count
                items.append({
                    "title": shown,
                    "subtitle": str(stream.get("game_name") or ""),
                    "value": f"{count:,}".replace(",", "."),
                    "status": "ok",
                    "icon": str(person.get("profile_image_url") or ""),
                })
            elif not options.get("only_live"):
                items.append({"title": shown, "subtitle": "Offline", "value": "", "status": "unknown",
                              "icon": str(person.get("profile_image_url") or "")})
        items.sort(key=lambda item: 0 if item["status"] == "ok" else 1)
        return WidgetData(
            items=items,
            secondary=[{"label": "Live", "value": len(live)}, {"label": "Viewers", "value": f"{viewers:,}".replace(",", ".")}],
            metrics={"live": float(len(live)), "viewers": float(viewers)},
            meta={"empty": "Nobody is live."},
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        from . import demo as fake

        rows = [("Harbourlight", "Factorio", True), ("Northshore", "Just Chatting", fake.flicker("twitch-two", tick, 0.4)), ("Elmstreet", "", False)]
        items = []
        viewers = 0
        for name, game, online in rows:
            if online:
                count = int(fake.walk(f"twitch-{name}", tick, 180, 4200, period=400))
                viewers += count
                items.append({"title": name, "subtitle": game, "value": f"{count:,}".replace(",", "."), "status": "ok", "icon": ""})
            elif not options.get("only_live"):
                items.append({"title": name, "subtitle": "Offline", "value": "", "status": "unknown", "icon": ""})
        items.sort(key=lambda item: 0 if item["status"] == "ok" else 1)
        count_live = sum(1 for _, _, online in rows if online)
        return WidgetData(
            items=items,
            secondary=[{"label": "Live", "value": count_live}, {"label": "Viewers", "value": f"{viewers:,}".replace(",", ".")}],
            metrics={"live": float(count_live), "viewers": float(viewers)},
            meta={"empty": "Nobody is live."},
        )


ADAPTER = TwitchAdapter()
