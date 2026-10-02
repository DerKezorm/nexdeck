"""nexsift: the notification inbox of the nexapps family, read through its API keys.

Written against nexsift 0.5.0, whose read API (``routers/api_v1.py``) is
built for this card, and measured against it on 02.10.2026: a fresh
installation with a webhook source and four messages, keys switched off
and on, with a right, a wrong and no key. The message text sent along
came back in no answer.

- A key is sent as ``Authorization: Bearer nxs_…``, never as a cookie and
  never in the address. It may read the numbers of the inbox and the titles
  of its newest lines, nothing else: no message text, no sender address, no
  token. A dashboard is often seen by guests.
- Keys are switched off out of the box. nexsift then answers 403
  ``api_keys_off`` for every key, a wrong one included, since the switch is
  asked first. Switched on, a wrong key gets 401 ``api_key_invalid``; none
  at all is always 401 ``api_key_missing``. The card tells off from wrong.
- ``/api/v1/status`` counts lines that are neither archived nor deleted:
  unread, critical and not resolved, warnings unread, all lines, messages
  since midnight UTC, sources, targets whose last delivery failed.
- ``/api/v1/threads?view=inbox|unread|crit&limit=1..50``, newest first.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
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
    base_url,
)

#: nexsift's priorities, as a row shows them. A critical line turns green once resolved.
PRIORITY = {"crit": "bad", "warn": "warn", "info": "unknown"}
VIEWS = (("inbox", "Inbox"), ("unread", "Unread"), ("crit", "Critical and open"))


class NexsiftAdapter(Adapter):
    kind = "nexsift"
    label = "nexsift"
    category = "monitoring"
    description = "The notification inbox of the homelab: what is unread, what is critical and open, and the newest lines."
    icon = "nexsift"
    beta = True
    docs_url = "https://github.com/DerKezorm/nexsift"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://nexsift:8490"),
        Field("api_key", "API key", type="password", secret=True, required=True,
              help="Settings > API keys in nexsift: switch on Allow API keys, then make one. It starts with nxs_ and may only read."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(
            kind="inbox",
            label="nexsift inbox",
            description="Unread lines, what is critical and still open, warnings, the messages of today and targets that failed.",
            renderer="value",
            default_size=(3, 2),
            refresh_seconds=30,
            metrics=("unread", "critical"),
        ),
        WidgetType(
            kind="threads",
            label="Newest lines",
            description="The newest lines of the inbox with where they came from and when, red while critical and open. Titles only, never the text.",
            renderer="list",
            default_size=(4, 3),
            refresh_seconds=30,
            options=(
                Field("view", "Show", type="select", default="inbox", options=VIEWS),
                Field("limit", "Entries", type="number", default=8),
            ),
        ),
    )

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, params: dict[str, Any] | None = None) -> Any:
        response = await ctx.request(
            "GET", f"{base_url(config)}/api/v1{path}", params=params, cache_seconds=10, auth_errors=False,
            headers={"Authorization": f"Bearer {config.get('api_key') or ''}", "Accept": "application/json"},
            verify=not config.get("insecure"),
        )
        code = _code_of(response)
        if response.status_code == 403 and code == "api_keys_off":
            raise AdapterError(
                "API keys are switched off in nexsift.", code="auth_failed",
                hint="Switch on Allow API keys under Settings > API keys in nexsift; the key itself stays valid.",
            )
        if response.status_code in (401, 403):
            raise AuthFailed("nexsift does not know this API key; it may have been withdrawn.")
        if response.status_code >= 400:
            raise AdapterError(f"nexsift answered with HTTP {response.status_code}.", code="http_error")
        try:
            return response.json()
        except ValueError:
            raise AdapterError("nexsift did not answer with JSON; is this the address of nexsift?", code="bad_answer") from None

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        status = await self._get(config, ctx, "/status")
        status = status if isinstance(status, dict) else {}
        return f"nexsift {status.get('version') or '?'} answers with {int(status.get('sources') or 0)} source(s) and {int(status.get('unread') or 0)} unread line(s)."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "threads":
            view = str(options.get("view") or "inbox")
            limit = max(1, min(50, int(options.get("limit") or 8)))
            rows = await self._get(config, ctx, "/threads", {"view": view if view in dict(VIEWS) else "inbox", "limit": limit})
            return threads_of(rows if isinstance(rows, list) else [])
        status = await self._get(config, ctx, "/status")
        return inbox_of(status if isinstance(status, dict) else {})

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        backup_failed = fake.flicker("nexsift-backup", tick, 0.35)
        now = time.time()
        if widget_kind == "threads":
            rows = [
                {"id": 31, "title": "Backup job failed: nas-weekly", "source": "Duplicati", "priority": "crit", "state": "unread",
                 "count": 2, "last_at": now - 600, "resolved": not backup_failed},
                {"id": 30, "title": "Disk temperature above 50 °C", "source": "Scrutiny", "priority": "warn", "state": "unread",
                 "count": 5, "last_at": now - 2400, "resolved": False},
                {"id": 29, "title": "Container updated: jellyfin", "source": "Watchtower", "priority": "info", "state": "read",
                 "count": 1, "last_at": now - 5400, "resolved": False},
                {"id": 28, "title": "New login from a new device", "source": "authentik", "priority": "warn", "state": "read",
                 "count": 1, "last_at": now - 9000, "resolved": False},
            ]
            view = str(options.get("view") or "inbox")
            if view == "unread":
                rows = [row for row in rows if row["state"] == "unread"]
            elif view == "crit":
                rows = [row for row in rows if row["priority"] == "crit" and not row["resolved"]]
            return threads_of(rows[: int(options.get("limit") or 8)])
        unread = int(fake.walk("nexsift-unread", tick, 3, 12))
        return inbox_of({
            "version": "0.5.0", "unread": unread, "critical_open": 1 if backup_failed else 0, "warnings_unread": 2,
            "lines": 64, "messages_today": 37, "sources": 11, "targets_failing": 0, "last_message_at": None,
        })


def _code_of(response: Any) -> str:
    """nexsift's own code of a refusal, from ``{"detail": {"code": …}}``."""
    try:
        detail = response.json().get("detail")
    except (ValueError, AttributeError):
        return ""
    return str(detail.get("code") or "") if isinstance(detail, dict) else ""


def _epoch(moment: Any) -> float | None:
    """nexsift's ISO time as epoch seconds; one without a zone is UTC, as nexsift stores it."""
    try:
        when = datetime.fromisoformat(str(moment).replace("Z", "+00:00"))
    except ValueError:
        return None
    return (when if when.tzinfo else when.replace(tzinfo=UTC)).timestamp()


def inbox_of(status: dict[str, Any]) -> WidgetData:
    unread = int(status.get("unread") or 0)
    critical = int(status.get("critical_open") or 0)
    failing = int(status.get("targets_failing") or 0)
    reasons = [f"{critical} critical and open" if critical else "", f"{failing} target(s) failing" if failing else ""]
    return WidgetData(
        status="bad" if critical else "warn" if failing else "ok",
        primary={"label": "Unread", "value": unread},
        secondary=[
            {"label": "Critical", "value": critical},
            {"label": "Warnings", "value": int(status.get("warnings_unread") or 0)},
            {"label": "Today", "value": int(status.get("messages_today") or 0)},
            {"label": "Sources", "value": int(status.get("sources") or 0)},
        ],
        metrics={"unread": float(unread), "critical": float(critical)},
        meta={"status_reason": ", ".join(reason for reason in reasons if reason)},
    )


def threads_of(rows: list[Any]) -> WidgetData:
    """Each line: its title, where from and how many messages under it, how long ago on the right."""
    items: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        count = int(row.get("count") or 1)
        priority = str(row.get("priority") or "info")
        state = "ok" if priority == "crit" and row.get("resolved") else PRIORITY.get(priority, "unknown")
        when = row.get("last_at")
        items.append({
            "id": row.get("id"),
            "title": str(row.get("title") or "?"),
            "subtitle": " · ".join(part for part in (str(row.get("source") or ""), f"{count} messages" if count > 1 else "") if part),
            "status": state,
            "when": when if isinstance(when, (int, float)) else _epoch(when),
            "unread": row.get("state") == "unread",
        })
    return WidgetData(
        status="bad" if any(item["status"] == "bad" for item in items) else "ok",
        items=items,
        meta={"empty": "Nothing in the inbox."},
    )


ADAPTER = NexsiftAdapter()
