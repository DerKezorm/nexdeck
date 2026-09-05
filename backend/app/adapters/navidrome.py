"""Navidrome: the music library, and who is playing something.

Speaks the Subsonic API, which every music server of this family speaks: a
user name and a token derived from the password, salted per request. That is
why the password is stored, not a key.
"""

from __future__ import annotations

import hashlib
import secrets
from typing import Any

from . import demo as fake
from .base import Adapter, AdapterError, Context, Field, WidgetData, WidgetType, base_url


class NavidromeAdapter(Adapter):
    kind = "navidrome"
    label = "Navidrome"
    category = "media"
    description = "Albums, artists and what is playing right now."
    icon = "navidrome"
    docs_url = "https://www.navidrome.org/docs/developers/subsonic-api/"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://navidrome:4533"),
        Field("username", "User name", required=True),
        Field("password", "Password", type="password", secret=True, required=True, help="Navidrome answers the Subsonic API; nexdeck sends a salted token, never the password itself."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(
            kind="library",
            label="Library",
            description="Albums, artists and songs in one number.",
            renderer="value",
            default_size=(2, 2),
            min_size=(1, 1),
            refresh_seconds=600,
            metrics=("albums", "songs"),
        ),
        WidgetType(
            kind="playing",
            label="Playing now",
            description="Who is listening to what.",
            renderer="list",
            default_size=(4, 2),
            refresh_seconds=30,
            metrics=("players",),
        ),
    )

    def _params(self, config: dict[str, Any]) -> dict[str, str]:
        salt = secrets.token_hex(8)
        password = str(config.get("password") or "")
        token = hashlib.md5(f"{password}{salt}".encode()).hexdigest()  # noqa: S324 - the Subsonic API asks for exactly this
        return {"u": str(config.get("username") or ""), "t": token, "s": salt, "v": "1.16.1", "c": "nexdeck", "f": "json"}

    async def _get(self, config: dict[str, Any], ctx: Context, view: str, extra: dict[str, Any] | None = None, cache: float = 30) -> Any:
        payload = await ctx.get_json(
            f"{base_url(config)}/rest/{view}",
            params={**self._params(config), **(extra or {})},
            verify=not config.get("insecure"),
            # Every request carries a fresh salt, so the cache would never hit.
            cache_seconds=0 if cache else 0,
        )
        response = (payload or {}).get("subsonic-response") or {}
        if response.get("status") != "ok":
            message = (response.get("error") or {}).get("message") or "Navidrome refused the request."
            raise AdapterError(str(message), code="auth_failed" if (response.get("error") or {}).get("code") == 40 else "http_error")
        return response

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        response = await self._get(config, ctx, "ping")
        return f"Navidrome {response.get('serverVersion', '?')} answers."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "playing":
            response = await self._get(config, ctx, "getNowPlaying")
            entries = ((response.get("nowPlaying") or {}).get("entry")) or []
            items = [
                {
                    "title": f"{entry.get('artist', '?')} - {entry.get('title', '?')}",
                    "subtitle": f"{entry.get('username', '?')} · {entry.get('playerName', '')}".strip(" ·"),
                    "status": "ok",
                }
                for entry in entries
            ]
            return WidgetData(
                items=items,
                secondary=[{"label": "Playing", "value": len(items)}],
                metrics={"players": float(len(items))},
            )

        response = await self._get(config, ctx, "getScanStatus")
        scanning = bool(response.get("scanStatus", {}).get("scanning"))
        counts = await self._get(config, ctx, "getArtists")
        indexes = ((counts.get("artists") or {}).get("index")) or []
        artists = sum(len(entry.get("artist") or []) for entry in indexes)
        albums = int(response.get("scanStatus", {}).get("count") or 0)
        return WidgetData(
            status="warn" if scanning else "ok",
            primary={"label": "Artists", "value": artists},
            # No yes/no here: a value is not translated, and the colour of the
            # card already says that a scan is running.
            secondary=[{"label": "Songs", "value": albums}],
            metrics={"albums": float(albums), "songs": float(albums)},
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        if widget_kind == "playing":
            rows = [("Harbour Brass - Slow Tide", "Alex · Living room"), ("The Ferrymen - Northern Line", "Sam · phone")]
            # Never zero, same reason as everywhere else in demo mode.
            count = max(1, int(fake.walk("navidrome-players", tick, 1, 2)))
            return WidgetData(
                items=[{"title": title, "subtitle": who, "status": "ok"} for title, who in rows[:count]],
                secondary=[{"label": "Playing", "value": count}],
                metrics={"players": float(count)},
            )
        scanning = fake.flicker("navidrome-scan", tick, 0.08)
        return WidgetData(
            status="warn" if scanning else "ok",
            primary={"label": "Artists", "value": 1284},
            secondary=[{"label": "Songs", "value": fake.counter("navidrome-songs", tick, 21840, 0.02)}],
            metrics={"albums": 2140.0, "songs": 21840.0},
        )


ADAPTER = NavidromeAdapter()
