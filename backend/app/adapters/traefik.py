"""Traefik: routers, services and the ones that are not working.

Every homelab that is reachable from outside has a reverse proxy in front of
it, and nexdeck had none. Traefik answers on its API endpoint, which is off by
default and has to be switched on with ``--api.insecure=true`` or put behind
basic authentication.
"""

from __future__ import annotations

from typing import Any

from . import demo as fake
from .base import Adapter, Context, Field, WidgetData, WidgetType, base_url


class TraefikAdapter(Adapter):
    kind = "traefik"
    label = "Traefik"
    category = "network"
    description = "Routers, services and middlewares, and which of them Traefik marks as broken."
    icon = "traefik"
    docs_url = "https://doc.traefik.io/traefik/operations/api/"
    #: Seen against a live Traefik 3.3.7 (05.09.2026).
    beta = False
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://traefik:8080", help="The address of the API, not of a routed site."),
        Field("username", "User name", help="Only if the API sits behind basic authentication."),
        Field("password", "Password", type="password", secret=True),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(
            kind="overview",
            label="Overview",
            description="How many routers and services there are, and how many are broken.",
            renderer="value",
            default_size=(2, 2),
            min_size=(1, 1),
            refresh_seconds=60,
            metrics=("routers", "errors"),
        ),
        WidgetType(
            kind="routers",
            label="Routers",
            description="One line per router, broken ones first.",
            renderer="list",
            default_size=(4, 3),
            refresh_seconds=120,
            options=(
                Field("limit", "Entries", type="number", default=10),
                Field("only_problems", "Only problems", type="bool", default=False),
            ),
        ),
    )

    def _auth(self, config: dict[str, Any]) -> tuple[str, str] | None:
        user = str(config.get("username") or "")
        return (user, str(config.get("password") or "")) if user else None

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, cache: float = 30) -> Any:
        return await ctx.get_json(
            f"{base_url(config)}/api{path}",
            auth=self._auth(config),
            verify=not config.get("insecure"),
            cache_seconds=cache,
        )

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        version = await self._get(config, ctx, "/version", cache=0)
        return f"Traefik {version.get('Version', '?')} answers."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "routers":
            routers = await self._get(config, ctx, "/http/routers", cache=60)
            only_problems = bool(options.get("only_problems"))
            limit = int(options.get("limit") or 10)
            items = []
            for router in routers if isinstance(routers, list) else []:
                broken = str(router.get("status") or "enabled") != "enabled"
                if only_problems and not broken:
                    continue
                items.append({
                    "title": str(router.get("name") or "?").split("@")[0],
                    "subtitle": str(router.get("rule") or ""),
                    "status": "bad" if broken else "ok",
                    "value": router.get("service") or "",
                })
            items.sort(key=lambda entry: 0 if entry["status"] == "bad" else 1)
            return WidgetData(
                status="bad" if any(entry["status"] == "bad" for entry in items) else "ok",
                items=items[:limit],
                secondary=[{"label": "Routers", "value": len(items)}],
            )

        overview = await self._get(config, ctx, "/overview", cache=30)
        http = overview.get("http") or {}
        routers = http.get("routers") or {}
        services = http.get("services") or {}
        middlewares = http.get("middlewares") or {}
        errors = int(routers.get("errors") or 0) + int(services.get("errors") or 0) + int(middlewares.get("errors") or 0)
        return WidgetData(
            status="bad" if errors else "ok",
            primary={"label": "Routers", "value": int(routers.get("total") or 0)},
            secondary=[
                {"label": "Services", "value": int(services.get("total") or 0)},
                {"label": "Middlewares", "value": int(middlewares.get("total") or 0)},
                {"label": "Broken", "value": errors},
            ],
            metrics={"routers": float(routers.get("total") or 0), "errors": float(errors)},
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        broken = 1 if fake.flicker("traefik-error", tick, 0.12) else 0
        if widget_kind == "routers":
            rows = [
                ("nexdeck", "Host(`deck.example.com`)", "nexdeck@docker", False),
                ("plex", "Host(`plex.example.com`)", "plex@docker", False),
                ("photos", "Host(`photos.example.com`)", "immich@docker", bool(broken)),
                ("git", "Host(`git.example.com`)", "forgejo@docker", False),
            ]
            items = [
                {"title": name, "subtitle": rule, "status": "bad" if bad else "ok", "value": service}
                for name, rule, service, bad in rows
                if not options.get("only_problems") or bad
            ]
            return WidgetData(status="bad" if broken else "ok", items=items, secondary=[{"label": "Routers", "value": len(items)}])
        return WidgetData(
            status="bad" if broken else "ok",
            primary={"label": "Routers", "value": 18},
            secondary=[
                {"label": "Services", "value": 15},
                {"label": "Middlewares", "value": 7},
                {"label": "Broken", "value": broken},
            ],
            metrics={"routers": 18.0, "errors": float(broken)},
        )


ADAPTER = TraefikAdapter()
