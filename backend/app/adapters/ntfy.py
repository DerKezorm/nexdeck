"""ntfy as a source: read a topic, not only write to it.

The other half of the connection nexdeck already has as a notification
channel. ntfy hands out a topic's history as newline-separated JSON, one
message per line, which is why this adapter parses the body itself instead of
asking for one JSON document.
"""

from __future__ import annotations

import json
from typing import Any

from . import demo as fake
from .base import Adapter, AdapterError, Context, Field, WidgetData, WidgetType, base_url


def _status(priority: int) -> str:
    if priority >= 5:
        return "bad"
    if priority >= 4:
        return "warn"
    return "ok"


class NtfyAdapter(Adapter):
    kind = "ntfy"
    label = "ntfy"
    category = "monitoring"
    description = "The messages of an ntfy topic, newest first."
    icon = "ntfy"
    docs_url = "https://docs.ntfy.sh/subscribe/api/"
    #: Seen against a live ntfy (05.09.2026).
    beta = False
    fields = (
        Field("url", "Server URL", type="url", required=True, default="https://ntfy.sh", placeholder="https://ntfy.sh"),
        Field("topic", "Topic", required=True, help="On a public server anybody who knows the name can read along."),
        Field("token", "Access token", type="password", secret=True, help="Only for a protected topic."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(
            kind="messages",
            label="Messages",
            description="What the topic received, with title and priority.",
            renderer="list",
            default_size=(4, 3),
            refresh_seconds=60,
            metrics=("messages",),
            options=(
                Field("limit", "Entries", type="number", default=8),
                Field("since", "Look back", type="select", default="12h", options=(("1h", "One hour"), ("12h", "Twelve hours"), ("24h", "One day"), ("7d", "Seven days"))),
            ),
        ),
    )

    def _headers(self, config: dict[str, Any]) -> dict[str, str]:
        token = str(config.get("token") or "")
        return {"Authorization": f"Bearer {token}"} if token else {}

    async def _messages(self, config: dict[str, Any], ctx: Context, since: str, cache: float = 30) -> list[dict[str, Any]]:
        topic = str(config.get("topic") or "").strip("/")
        if not topic:
            raise AdapterError("No topic was named.", code="missing_fields", hint="Fill in the topic of the ntfy server.")
        response = await ctx.request(
            "GET",
            f"{base_url(config)}/{topic}/json",
            params={"poll": "1", "since": since},
            headers=self._headers(config),
            verify=not config.get("insecure"),
            cache_seconds=cache,
        )
        if response.status_code >= 400:
            raise AdapterError(f"ntfy answered with HTTP {response.status_code}.", code="http_error")
        messages = []
        for line in response.text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            # Keep-alive and open events are not messages.
            if entry.get("event") == "message":
                messages.append(entry)
        messages.reverse()
        return messages

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        messages = await self._messages(config, ctx, "12h", cache=0)
        return f"ntfy answers; {len(messages)} messages in the last twelve hours."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        since = str(options.get("since") or "12h")
        limit = int(options.get("limit") or 8)
        messages = await self._messages(config, ctx, since)
        loud = sum(1 for message in messages if int(message.get("priority") or 3) >= 5)
        items = [
            {
                "title": message.get("title") or str(message.get("message") or "")[:60] or "?",
                "subtitle": str(message.get("message") or "")[:160] if message.get("title") else "",
                "value": ", ".join(message.get("tags") or [])[:24],
                "status": _status(int(message.get("priority") or 3)),
            }
            for message in messages[:limit]
        ]
        return WidgetData(
            status="bad" if loud else "ok",
            items=items,
            secondary=[{"label": "Messages", "value": len(messages)}],
            metrics={"messages": float(len(messages))},
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        rows = [
            ("Door opened", "Front door, 07:14", "door", 3),
            ("Backup finished", "Nightly run, 42 GB", "floppy_disk", 2),
            ("UPS on battery", "Mains gone", "warning", 5),
            ("Printer out of paper", "Office", "printer", 4),
        ]
        count = fake.counter("ntfy-count", tick, 26, 0.03)
        loud = 1 if fake.flicker("ntfy-loud", tick, 0.12) else 0
        items = [
            {"title": title, "subtitle": body, "value": tag, "status": _status(priority)}
            for title, body, tag, priority in rows[: int(options.get("limit") or 8)]
        ]
        return WidgetData(
            status="bad" if loud else "ok",
            items=items,
            secondary=[{"label": "Messages", "value": count}],
            metrics={"messages": float(count)},
        )


ADAPTER = NtfyAdapter()
