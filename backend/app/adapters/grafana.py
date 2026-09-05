"""Grafana: which alert rules are firing right now.

Grafana's own alerting API is read here, not the Alertmanager view: it names
the rule, tells a pending rule from a firing one, and answers even when
nothing is on fire, which is what makes an empty card mean "quiet" instead of
"not set up".

⚠️ Needs unified alerting, so Grafana 9.0 or newer. In 8.x it was opt-in and
the address may not exist.
"""

from __future__ import annotations

from typing import Any

from . import demo as fake
from .base import Adapter, Context, Field, WidgetData, WidgetType, base_url

RULES = "/api/prometheus/grafana/api/v1/rules"
#: What a rule's state means for the dot beside it.
STATES = {"firing": "bad", "pending": "warn", "inactive": "ok", "recovering": "warn"}


class GrafanaAdapter(Adapter):
    kind = "grafana"
    label = "Grafana"
    category = "monitoring"
    description = "Alert rules that are firing, and how many dashboards there are."
    icon = "grafana"
    docs_url = "https://grafana.com/docs/grafana/latest/developer-resources/api-reference/http-api/"
    #: Seen against a live Grafana 13.2.1 (05.09.2026).
    beta = False
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://grafana:3000"),
        Field("token", "API token", type="password", secret=True, required=True, help="A service account token; the viewer role is enough. Needs Grafana 9.0 or newer."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(
            kind="alerts",
            label="Alerts",
            description="Every rule that is firing or about to, newest state first.",
            renderer="list",
            default_size=(4, 3),
            refresh_seconds=60,
            metrics=("firing", "pending"),
            options=(Field("limit", "Entries", type="number", default=8), Field("only_firing", "Only firing", type="bool", default=False)),
        ),
        WidgetType(
            kind="status",
            label="Status",
            description="Firing rules, waiting rules, dashboards and the version.",
            renderer="value",
            default_size=(2, 2),
            min_size=(1, 1),
            refresh_seconds=300,
            metrics=("firing", "pending"),
        ),
    )

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, params: dict[str, Any] | None = None, cache: float = 60) -> Any:
        return await ctx.get_json(
            f"{base_url(config)}{path}",
            headers={"Authorization": f"Bearer {config.get('token') or ''}", "Accept": "application/json"},
            params=params,
            verify=not config.get("insecure"),
            cache_seconds=cache,
        )

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        health = await self._get(config, ctx, "/api/health", cache=0)
        return f"Grafana {health.get('version', '?')} answers; its database is {health.get('database', '?')}."

    @staticmethod
    def _rules(payload: Any) -> list[tuple[str, str, str]]:
        """Name, state and where it lives, for every alert rule."""
        rows = []
        for group in ((payload or {}).get("data") or {}).get("groups") or []:
            # "file" carries the folder's title, "folderUid" a random string.
            # Seen against Grafana 13.2.1: preferring the uid puts
            # "cfxd7vj7k5m9sd" on the card where a name belongs.
            folder = str(group.get("file") or group.get("folderUid") or "")
            name = str(group.get("name") or "")
            # Folder and group are the operator's own words. Joined with
            # a middle dot the interface would translate each half, so a
            # group called Storage would show up as Speicher.
            where = folder if folder == name or not name else f"{folder} / {name}".strip(" /")
            for rule in group.get("rules") or []:
                if str(rule.get("type") or "alerting") != "alerting":
                    continue
                rows.append((str(rule.get("name") or "?"), str(rule.get("state") or "").lower(), where))
        return rows

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        payload = await self._get(config, ctx, RULES, cache=60)
        rules = self._rules(payload)
        firing = sum(1 for _, state, _ in rules if state == "firing")
        pending = sum(1 for _, state, _ in rules if state == "pending")

        if widget_kind == "status":
            health = await self._get(config, ctx, "/api/health", cache=600)
            dashboards = await self._get(config, ctx, "/api/search", {"type": "dash-db", "limit": 5000}, cache=600)
            return WidgetData(
                status="bad" if firing else ("warn" if pending else "ok"),
                primary={"label": "Firing", "value": firing},
                secondary=[
                    {"label": "Pending", "value": pending},
                    {"label": "Rules", "value": len(rules)},
                    {"label": "Dashboards", "value": len(dashboards) if isinstance(dashboards, list) else 0},
                    {"label": "Version", "value": str(health.get("version") or "?")},
                ],
                metrics={"firing": float(firing), "pending": float(pending)},
            )

        wanted = {"firing"} if options.get("only_firing") else {"firing", "pending", "recovering"}
        items = [
            {"title": name, "subtitle": where, "status": STATES.get(state, "unknown")}
            for name, state, where in rules
            if state in wanted
        ]
        items.sort(key=lambda item: 0 if item["status"] == "bad" else 1)
        return WidgetData(
            status="bad" if firing else ("warn" if pending else "ok"),
            items=items[: int(options.get("limit") or 8)],
            secondary=[{"label": "Firing", "value": firing}, {"label": "Pending", "value": pending}],
            metrics={"firing": float(firing), "pending": float(pending)},
            meta={"empty": "Everything is quiet."},
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        loud = fake.flicker("grafana-firing", tick, 0.35)
        rules = [
            ("Disk almost full", "firing" if loud else "inactive", "Infrastructure / Storage"),
            ("Backup older than a day", "pending", "Infrastructure / Backups"),
            ("Certificate expires soon", "inactive", "Web / Certificates"),
            ("Load above 8", "inactive", "Infrastructure / Hosts"),
        ]
        firing = sum(1 for _, state, _ in rules if state == "firing")
        pending = sum(1 for _, state, _ in rules if state == "pending")

        if widget_kind == "status":
            return WidgetData(
                status="bad" if firing else ("warn" if pending else "ok"),
                primary={"label": "Firing", "value": firing},
                secondary=[
                    {"label": "Pending", "value": pending},
                    {"label": "Rules", "value": len(rules)},
                    {"label": "Dashboards", "value": 21},
                    {"label": "Version", "value": "11.6.0"},
                ],
                metrics={"firing": float(firing), "pending": float(pending)},
            )

        wanted = {"firing"} if options.get("only_firing") else {"firing", "pending", "recovering"}
        items = [
            {"title": name, "subtitle": where, "status": STATES.get(state, "unknown")}
            for name, state, where in rules
            if state in wanted
        ]
        items.sort(key=lambda item: 0 if item["status"] == "bad" else 1)
        return WidgetData(
            status="bad" if firing else ("warn" if pending else "ok"),
            items=items[: int(options.get("limit") or 8)],
            secondary=[{"label": "Firing", "value": firing}, {"label": "Pending", "value": pending}],
            metrics={"firing": float(firing), "pending": float(pending)},
            meta={"empty": "Everything is quiet."},
        )


ADAPTER = GrafanaAdapter()
