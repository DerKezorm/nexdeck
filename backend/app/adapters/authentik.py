"""authentik: who signed in, and who tried.

nexdeck already signs people in through it; reading the other direction is the
second half. The token comes from an account in authentik and rides as a
bearer token; a read-only service account is enough.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from . import demo as fake
from .base import Adapter, Context, Field, WidgetData, WidgetType, base_url


class AuthentikAdapter(Adapter):
    kind = "authentik"
    label = "authentik"
    category = "network"
    description = "Sign-ins, failed attempts, users and whether the version is behind."
    icon = "authentik"
    docs_url = "https://docs.goauthentik.io/docs/developer-docs/api/"
    #: Seen against a live authentik 2026.8.0 (05.09.2026).
    beta = False
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="https://auth.example.com"),
        Field("token", "API token", type="password", secret=True, required=True, help="Directory > Tokens and App passwords; a service account with read access is enough."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(
            kind="status",
            label="Status",
            description="Users, sign-ins and failed attempts of the last day.",
            renderer="value",
            default_size=(2, 2),
            min_size=(1, 1),
            refresh_seconds=300,
            metrics=("failed", "logins"),
        ),
        WidgetType(
            kind="failed",
            label="Failed sign-ins",
            description="Who tried and did not get in, newest first.",
            renderer="list",
            default_size=(4, 3),
            refresh_seconds=300,
            metrics=("failed",),
            options=(Field("limit", "Entries", type="number", default=8),),
        ),
    )

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, params: dict[str, Any] | None = None, cache: float = 120) -> Any:
        return await ctx.get_json(
            f"{base_url(config)}/api/v3{path}",
            headers={"Authorization": f"Bearer {config.get('token') or ''}", "Accept": "application/json"},
            params=params,
            verify=not config.get("insecure"),
            cache_seconds=cache,
        )

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        version = await self._get(config, ctx, "/admin/version/", cache=0)
        return f"authentik {version.get('version_current', '?')} answers."

    @staticmethod
    def _recent(events: list[dict[str, Any]], hours: int = 24) -> list[dict[str, Any]]:
        since = datetime.now(UTC) - timedelta(hours=hours)
        recent = []
        for event in events:
            raw = str(event.get("created") or "")
            try:
                moment = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except ValueError:
                continue
            if moment >= since:
                recent.append(event)
        return recent

    @staticmethod
    def _who(event: dict[str, Any]) -> str:
        context = event.get("context") or {}
        user = event.get("user") or {}
        return str(context.get("username") or user.get("username") or "?")

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        limit = int(options.get("limit") or 8)
        failures = await self._get(config, ctx, "/events/events/", {"action": "login_failed", "ordering": "-created", "page_size": max(limit, 50)}, cache=120)
        failed_events = (failures or {}).get("results") or []
        failed_today = self._recent(failed_events)

        if widget_kind == "failed":
            items = []
            for event in failed_events[:limit]:
                raw = str(event.get("created") or "")
                when = raw[11:16] if len(raw) > 16 else raw
                items.append({
                    "title": self._who(event),
                    "subtitle": f"{(event.get('client_ip') or '')} · {when}".strip(" ·"),
                    "status": "warn",
                })
            return WidgetData(
                status="warn" if failed_today else "ok",
                items=items,
                secondary=[{"label": "Last day", "value": len(failed_today)}],
                metrics={"failed": float(len(failed_today))},
            )

        logins = await self._get(config, ctx, "/events/events/", {"action": "login", "ordering": "-created", "page_size": 50}, cache=120)
        users = await self._get(config, ctx, "/core/users/", {"page_size": 1}, cache=600)
        version = await self._get(config, ctx, "/admin/version/", cache=3600)
        logins_today = self._recent((logins or {}).get("results") or [])
        outdated = bool(version.get("outdated"))
        return WidgetData(
            status="warn" if failed_today or outdated else "ok",
            primary={"label": "Sign-ins", "value": len(logins_today)},
            secondary=[
                {"label": "Failed", "value": len(failed_today)},
                {"label": "Users", "value": int(((users or {}).get("pagination") or {}).get("count") or 0)},
                {"label": "Version", "value": f"{version.get('version_current', '?')}{' !' if outdated else ''}"},
            ],
            metrics={"failed": float(len(failed_today)), "logins": float(len(logins_today))},
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        failed = int(fake.walk("authentik-failed", tick, 0, 5))
        if widget_kind == "failed":
            rows = [("kim", "203.0.113.24", "07:14"), ("admin", "198.51.100.9", "03:02"), ("kim", "203.0.113.24", "07:13")]
            return WidgetData(
                status="warn" if failed else "ok",
                items=[{"title": who, "subtitle": f"{address} · {when}", "status": "warn"} for who, address, when in rows[:failed or 1]],
                secondary=[{"label": "Last day", "value": failed}],
                metrics={"failed": float(failed)},
            )
        outdated = fake.flicker("authentik-version", tick, 0.15)
        return WidgetData(
            status="warn" if failed or outdated else "ok",
            primary={"label": "Sign-ins", "value": int(fake.walk("authentik-logins", tick, 6, 34))},
            secondary=[
                {"label": "Failed", "value": failed},
                {"label": "Users", "value": 14},
                {"label": "Version", "value": "2026.6.2 !" if outdated else "2026.6.2"},
            ],
            metrics={"failed": float(failed), "logins": fake.walk("authentik-logins", tick, 6, 34)},
        )


ADAPTER = AuthentikAdapter()
