"""Gotify as a source: show the messages, not only send them.

nexdeck already delivers to Gotify as a notification channel. Reading the
other half of the same connection costs one address, and it turns the push
service into the message log of the house.

⚠️ The token here is a **client** token, not the application token the channel
uses: application tokens may only write.
"""

from __future__ import annotations

from typing import Any

from . import demo as fake
from .base import Adapter, Context, Field, WidgetData, WidgetType, base_url


#: Gotify's priorities, in the three steps a card can show.
def _status(priority: int) -> str:
    if priority >= 8:
        return "bad"
    if priority >= 4:
        return "warn"
    return "ok"


class GotifyAdapter(Adapter):
    kind = "gotify"
    label = "Gotify"
    category = "monitoring"
    description = "The latest messages of a Gotify server, newest first."
    icon = "gotify"
    docs_url = "https://gotify.net/api-docs"
    #: Seen against a live Gotify 3.1.0 (05.09.2026).
    beta = False
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://gotify:80"),
        Field("client_token", "Client token", type="password", secret=True, required=True, help="Clients > Create client. An application token may only write."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(
            kind="messages",
            label="Messages",
            description="What arrived lately, with the application that sent it.",
            renderer="list",
            default_size=(4, 3),
            refresh_seconds=60,
            metrics=("messages",),
            options=(
                Field("limit", "Entries", type="number", default=8),
                Field("min_priority", "From priority", type="number", default=0, help="0 shows everything; 4 hides the chatter."),
            ),
        ),
        WidgetType(
            kind="counts",
            label="Message count",
            description="How much has arrived, and how much of it was loud.",
            renderer="value",
            default_size=(2, 2),
            min_size=(1, 1),
            refresh_seconds=120,
            metrics=("messages",),
        ),
    )

    def _headers(self, config: dict[str, Any]) -> dict[str, str]:
        return {"X-Gotify-Key": str(config.get("client_token") or "")}

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, params: dict[str, Any] | None = None, cache: float = 30) -> Any:
        return await ctx.get_json(
            f"{base_url(config)}{path}",
            headers=self._headers(config),
            params=params,
            verify=not config.get("insecure"),
            cache_seconds=cache,
        )

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        version = await self._get(config, ctx, "/version", cache=0)
        applications = await self._get(config, ctx, "/application", cache=0)
        count = len(applications) if isinstance(applications, list) else 0
        return f"Gotify {version.get('version', '?')} answers with {count} applications."

    async def _applications(self, config: dict[str, Any], ctx: Context) -> dict[int, str]:
        applications = await self._get(config, ctx, "/application", cache=600)
        return {int(entry.get("id")): str(entry.get("name") or "?") for entry in applications if isinstance(entry, dict) and entry.get("id") is not None}

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        limit = int(options.get("limit") or 8)
        minimum = int(options.get("min_priority") or 0)
        payload = await self._get(config, ctx, "/message", params={"limit": max(limit, 20)}, cache=30)
        messages = payload.get("messages") if isinstance(payload, dict) else []
        names = await self._applications(config, ctx)

        loud = sum(1 for message in messages if int(message.get("priority") or 0) >= 8)
        if widget_kind == "counts":
            return WidgetData(
                status="bad" if loud else "ok",
                primary={"label": "Messages", "value": len(messages)},
                secondary=[
                    {"label": "Loud", "value": loud},
                    {"label": "Applications", "value": len(names)},
                ],
                metrics={"messages": float(len(messages))},
            )

        items = []
        for message in messages:
            priority = int(message.get("priority") or 0)
            if priority < minimum:
                continue
            items.append({
                "title": message.get("title") or names.get(int(message.get("appid") or 0), "?"),
                "subtitle": str(message.get("message") or "")[:160],
                "value": names.get(int(message.get("appid") or 0), ""),
                "status": _status(priority),
            })
        return WidgetData(
            status="bad" if loud else "ok",
            items=items[:limit],
            secondary=[{"label": "Messages", "value": len(messages)}],
            metrics={"messages": float(len(messages))},
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        rows = [
            ("Backup finished", "42 GB in 18 minutes, no errors.", "Borg", 2),
            ("Disk warm", "sdc reached 52 °C.", "Scrutiny", 5),
            ("Update available", "Radarr 5.14 is out.", "Watchtower", 3),
            ("UPS on battery", "Mains gone, 18 minutes left.", "PeaNUT", 8),
        ]
        minimum = int(options.get("min_priority") or 0)
        count = fake.counter("gotify-count", tick, 128, 0.05)
        loud = 1 if fake.flicker("gotify-loud", tick, 0.15) else 0
        if widget_kind == "counts":
            return WidgetData(
                status="bad" if loud else "ok",
                primary={"label": "Messages", "value": count},
                secondary=[{"label": "Loud", "value": loud}, {"label": "Applications", "value": 6}],
                metrics={"messages": float(count)},
            )
        items = [
            {"title": title, "subtitle": body, "value": application, "status": _status(priority)}
            for title, body, application, priority in rows
            if priority >= minimum
        ]
        return WidgetData(
            status="bad" if loud else "ok",
            items=items[: int(options.get("limit") or 8)],
            secondary=[{"label": "Messages", "value": count}],
            metrics={"messages": float(count)},
        )


ADAPTER = GotifyAdapter()
