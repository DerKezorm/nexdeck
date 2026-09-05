"""Coolify: the applications it runs and what is deploying right now.

The API has to be switched on in Coolify under Settings > Advanced before it
answers anything; the token comes from Keys & Tokens and needs read.

⚠️ Coolify composes an application's state as ``state:health``, for example
``running:healthy``. The API reference calls the field a string and says
nothing more, so this adapter reads the half it recognises and shows the rest
as it came instead of guessing.
"""

from __future__ import annotations

from typing import Any

from . import demo as fake
from .base import Adapter, Context, Field, WidgetData, WidgetType, base_url

#: What the first half of a status means for the dot on the row.
STATES = {
    "running": "ok",
    "starting": "warn",
    "restarting": "warn",
    "degraded": "warn",
    "exited": "bad",
    "stopped": "bad",
    "dead": "bad",
}
#: A deployment is a run, not a state; these are its ends.
DEPLOYMENTS = {"finished": "ok", "in_progress": "warn", "queued": "unknown", "failed": "bad", "cancelled-by-user": "unknown"}


class CoolifyAdapter(Adapter):
    kind = "coolify"
    label = "Coolify"
    category = "hosts"
    description = "Applications with their state, the servers behind them, and what is deploying."
    icon = "coolify"
    docs_url = "https://coolify.io/docs/api-reference/authorization"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="https://coolify.example.com"),
        Field("token", "API token", type="password", secret=True, required=True, help="Keys & Tokens > API tokens; read is enough. The API has to be on under Settings > Advanced."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(
            kind="applications",
            label="Applications",
            description="One line per application with its address and its state.",
            renderer="list",
            default_size=(4, 3),
            refresh_seconds=60,
            metrics=("applications", "running"),
            options=(Field("limit", "Entries", type="number", default=10), Field("only_trouble", "Only trouble", type="bool", default=False)),
        ),
        WidgetType(
            kind="deployments",
            label="Deployments",
            description="What is building or waiting right now.",
            renderer="list",
            default_size=(4, 2),
            refresh_seconds=30,
            metrics=("deployments",),
        ),
        WidgetType(
            kind="status",
            label="Status",
            description="How many applications run, how many servers answer, and the version.",
            renderer="value",
            default_size=(2, 2),
            min_size=(1, 1),
            refresh_seconds=120,
            metrics=("applications", "running"),
        ),
    )

    def _headers(self, config: dict[str, Any]) -> dict[str, str]:
        return {"Authorization": f"Bearer {config.get('token') or ''}", "Accept": "application/json"}

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, cache: float = 30) -> Any:
        return await ctx.get_json(
            f"{base_url(config)}/api/v1{path}",
            headers=self._headers(config),
            verify=not config.get("insecure"),
            cache_seconds=cache,
        )

    async def _version(self, config: dict[str, Any], ctx: Context) -> str:
        """The version comes back as bare text, not as JSON."""
        response = await ctx.request(
            "GET",
            f"{base_url(config)}/api/v1/version",
            headers=self._headers(config),
            verify=not config.get("insecure"),
            cache_seconds=3600,
        )
        return response.text.strip().strip('"') if response.status_code < 400 else "?"

    @staticmethod
    def _state(raw: Any) -> tuple[str, str]:
        """The state word and the dot that belongs to it."""
        text = str(raw or "").strip()
        state = text.split(":", 1)[0].lower()
        health = text.split(":", 1)[1].lower() if ":" in text else ""
        dot = STATES.get(state, "unknown")
        if dot == "ok" and health and health != "healthy":
            dot = "warn"
        return state, dot

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        applications = await self._get(config, ctx, "/applications", cache=0)
        count = len(applications) if isinstance(applications, list) else 0
        return f"Coolify answers with {count} applications."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "deployments":
            running = await self._get(config, ctx, "/deployments", cache=20)
            rows = running if isinstance(running, list) else []
            items = [
                {
                    "title": str(entry.get("application_name") or "?"),
                    "subtitle": str(entry.get("commit_message") or entry.get("server_name") or "")[:80],
                    "status": DEPLOYMENTS.get(str(entry.get("status") or "").lower(), "unknown"),
                }
                for entry in rows
            ]
            return WidgetData(
                items=items,
                secondary=[{"label": "Running", "value": len(items)}],
                metrics={"deployments": float(len(items))},
                meta={"empty": "Nothing is deploying."},
            )

        applications = await self._get(config, ctx, "/applications", cache=60)
        rows = applications if isinstance(applications, list) else []
        running = 0
        items = []
        for entry in rows:
            state, dot = self._state(entry.get("status"))
            running += 1 if dot == "ok" else 0
            items.append({
                "title": str(entry.get("name") or "?"),
                # The domain is what an operator recognises an application by.
                "subtitle": str(entry.get("fqdn") or entry.get("git_branch") or "").split(",")[0],
                "status": dot,
                "state": state,
            })

        if widget_kind == "status":
            servers = await self._get(config, ctx, "/servers", cache=300)
            reachable = sum(1 for server in servers if (server.get("settings") or {}).get("is_reachable")) if isinstance(servers, list) else 0
            version = await self._version(config, ctx)
            return WidgetData(
                status="bad" if running < len(rows) else "ok",
                primary={"label": "Running", "value": running},
                secondary=[
                    {"label": "Applications", "value": len(rows)},
                    {"label": "Servers", "value": f"{reachable}/{len(servers) if isinstance(servers, list) else 0}"},
                    {"label": "Version", "value": version},
                ],
                metrics={"applications": float(len(rows)), "running": float(running)},
            )

        if options.get("only_trouble"):
            items = [item for item in items if item["status"] != "ok"]
        items.sort(key=lambda item: (0 if item["status"] == "bad" else 1 if item["status"] != "ok" else 2, item["title"]))
        return WidgetData(
            status="bad" if running < len(rows) else "ok",
            items=[{key: value for key, value in item.items() if key != "state"} for item in items[: int(options.get("limit") or 10)]],
            secondary=[{"label": "Running", "value": running}, {"label": "Applications", "value": len(rows)}],
            metrics={"applications": float(len(rows)), "running": float(running)},
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        broken = fake.flicker("coolify-broken", tick, 0.25)
        applications = [
            ("shop", "shop.example.com", "running:healthy"),
            ("api", "api.example.com", "running:healthy"),
            ("staging", "staging.example.com", "exited:unhealthy" if broken else "running:healthy"),
            ("docs", "docs.example.com", "running:healthy"),
            ("worker", "", "running:unhealthy"),
        ]
        if widget_kind == "deployments":
            rows = [("api", "Bump the parser to 3.2"), ("shop", "Add the checkout banner")]
            take = 1 + (tick % 2)
            return WidgetData(
                items=[{"title": name, "subtitle": message, "status": "warn"} for name, message in rows[:take]],
                secondary=[{"label": "Running", "value": take}],
                metrics={"deployments": float(take)},
                meta={"empty": "Nothing is deploying."},
            )

        items = []
        running = 0
        for name, domain, status in applications:
            state, dot = self._state(status)
            running += 1 if dot == "ok" else 0
            items.append({"title": name, "subtitle": domain, "status": dot, "state": state})

        if widget_kind == "status":
            return WidgetData(
                status="bad" if running < len(applications) else "ok",
                primary={"label": "Running", "value": running},
                secondary=[
                    {"label": "Applications", "value": len(applications)},
                    {"label": "Servers", "value": "2/2"},
                    {"label": "Version", "value": "v4.0.0"},
                ],
                metrics={"applications": float(len(applications)), "running": float(running)},
            )

        if options.get("only_trouble"):
            items = [item for item in items if item["status"] != "ok"]
        items.sort(key=lambda item: (0 if item["status"] == "bad" else 1 if item["status"] != "ok" else 2, item["title"]))
        return WidgetData(
            status="bad" if running < len(applications) else "ok",
            items=[{key: value for key, value in item.items() if key != "state"} for item in items[: int(options.get("limit") or 10)]],
            secondary=[{"label": "Running", "value": running}, {"label": "Applications", "value": len(applications)}],
            metrics={"applications": float(len(applications)), "running": float(running)},
        )


ADAPTER = CoolifyAdapter()
