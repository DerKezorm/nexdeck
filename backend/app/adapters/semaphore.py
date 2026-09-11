"""Semaphore UI: whether the playbooks and scripts that run on a schedule went through.

Measured against Semaphore UI 2.19.14 on 11.09.2026, with a project whose two
Ansible templates ran once each: one green, one red.

The template list carries each template's last run (``last_task``), so one
request per project says how every job last ended; no task list has to be
read and grouped.

⚠️ A missing and a wrong token both get 401 with an empty body.

⚠️ The version comes as ``v2.19.14-7d1872e-1788945498``: version, commit and
build time in one string.
"""

from __future__ import annotations

import time
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
    ago,
    base_url,
)

#: A run's state as a colour and a word; plain success needs no word.
RUN = {
    "success": ("ok", ""), "error": ("bad", "Failed"), "running": ("warn", "Running"), "starting": ("warn", "Starting"),
    "waiting": ("unknown", "Waiting"), "stopping": ("unknown", "Stopping"), "stopped": ("unknown", "Stopped"),
}


class SemaphoreAdapter(Adapter):
    kind = "semaphore"
    label = "Semaphore UI"
    category = "hosts"
    description = "Whether the playbooks and scripts that run on a schedule went through."
    icon = "semaphore"
    beta = False
    docs_url = "https://docs.semaphoreui.com/administration-guide/api/"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://semaphore:3000"),
        Field("token", "API token", type="password", secret=True, required=True,
              help="An API token of your Semaphore user. It sees the projects that user sees."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(kind="runs", label="Last runs", description="How every template last ended, red ones first.",
                   renderer="list", default_size=(3, 3), refresh_seconds=120, metrics=("failed",),
                   options=(Field("project", "Project", help="The name of one project. Empty shows all."),
                            Field("limit", "Entries", type="number", default=10))),
        WidgetType(kind="summary", label="Automation", description="How many templates last failed and how many are running.",
                   renderer="value", default_size=(3, 2), refresh_seconds=120, metrics=("failed",)),
    )

    async def _json(self, config: dict[str, Any], ctx: Context, path: str, cache: float = 10) -> Any:
        response = await ctx.request(
            "GET", f"{base_url(config)}/api{path}", headers={"Authorization": f"Bearer {config.get('token') or ''}"},
            verify=not config.get("insecure"), cache_seconds=cache, auth_errors=False,
        )
        if response.status_code in (401, 403):
            raise AuthFailed("Semaphore rejected the API token.")
        if response.status_code >= 400:
            raise AdapterError(f"Semaphore answered with HTTP {response.status_code}.", code="http_error",
                               hint="Check the URL; it is the address of Semaphore itself, without /api.")
        try:
            return response.json()
        except ValueError as error:
            raise AdapterError("Semaphore did not answer with JSON.", code="not_json",
                               hint="The URL probably points at a login page or a reverse proxy.") from error

    async def _templates(self, config: dict[str, Any], ctx: Context, project: str = "") -> list[tuple[str, dict[str, Any]]]:
        projects = await self._json(config, ctx, "/projects")
        if not isinstance(projects, list):
            raise AdapterError("This address answers, but not the way Semaphore does.", code="not_semaphore")
        wanted = project.strip().lower()
        chosen = [one for one in projects if isinstance(one, dict) and (not wanted or str(one.get("name", "")).lower() == wanted)]
        if wanted and not chosen:
            raise AdapterError(f"Semaphore has no project named {project.strip()!r} for this token.", code="no_such_project")
        found: list[tuple[str, dict[str, Any]]] = []
        for one in chosen:
            templates = await self._json(config, ctx, f"/project/{one.get('id')}/templates")
            found += [(str(one.get("name") or "?"), template) for template in templates or [] if isinstance(template, dict)]
        return found

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        info = await self._json(config, ctx, "/info", cache=0)
        projects = await self._json(config, ctx, "/projects", cache=0)
        if not isinstance(info, dict) or not isinstance(projects, list):
            raise AdapterError("This address answers, but not the way Semaphore does.", code="not_semaphore")
        version = str(info.get("version") or "?").split("-", 1)[0]
        return f"Semaphore {version} answers with {len(projects)} project{'' if len(projects) == 1 else 's'}."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "summary":
            return self._summary(await self._templates(config, ctx))
        return self._runs(await self._templates(config, ctx, str(options.get("project") or "")), options)

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def _last(template: dict[str, Any]) -> dict[str, Any]:
        return template.get("last_task") if isinstance(template.get("last_task"), dict) else {}

    @classmethod
    def _summary(cls, templates: list[tuple[str, dict[str, Any]]]) -> WidgetData:
        states = [str(cls._last(template).get("status") or "") for _project, template in templates]
        failed = states.count("error")
        running = sum(1 for state in states if state in ("running", "starting"))
        secondary: list[dict[str, Any]] = [{"label": "Templates", "value": len(templates)}]
        if running:
            secondary.append({"label": "Running", "value": running})
        return WidgetData(
            status="bad" if failed else "ok",
            primary={"label": "Failed", "value": failed},
            secondary=secondary,
            metrics={"failed": float(failed)},
        )

    @classmethod
    def _runs(cls, templates: list[tuple[str, dict[str, Any]]], options: dict[str, Any]) -> WidgetData:
        rows: list[tuple[int, str, dict[str, Any]]] = []
        for project, template in templates:
            last = cls._last(template)
            state = str(last.get("status") or "")
            if last:
                colour, word = RUN.get(state, ("unknown", state.capitalize()))
            else:
                colour, word = "unknown", "Never run"
            moment = last.get("end") or last.get("start") or last.get("created")
            rank = 0 if state == "error" else 1 if state in ("running", "starting") else 2
            rows.append((rank, str(moment or ""), {
                "title": str(template.get("name") or "?"),
                "subtitle": " · ".join(part for part in (word, project) if part),
                "status": colour,
                "value": ago(moment),
            }))
        # Red first, then what is running; within that the latest first, and never-run templates last.
        rows.sort(key=lambda entry: (entry[0], -_order(entry[1])))
        failed = sum(1 for _project, template in templates if cls._last(template).get("status") == "error")
        return WidgetData(
            status="bad" if failed else "ok",
            items=[row for _red, _moment, row in rows][: int(options.get("limit") or 10)],
            secondary=[{"label": "Failed", "value": failed}],
            meta={"empty": "No templates yet."},
            metrics={"failed": float(failed)},
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        red = fake.flicker("sem-deploy", tick, 0.6)

        def ran(status: str, minutes: int) -> dict[str, Any]:
            return {"status": status, "end": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - minutes * 60))}

        templates = [
            ("Homelab", {"name": "Update all hosts", "last_task": ran("success", 380)}),
            ("Homelab", {"name": "Renew certificates", "last_task": ran("error" if red else "success", 95)}),
            ("Backups", {"name": "Offsite sync", "last_task": ran("running", 2)}),
            ("Backups", {"name": "Restore test", "last_task": None}),
        ]
        if widget_kind == "summary":
            return self._summary(templates)
        return self._runs(templates, options)


def _order(moment: str) -> float:
    """An ISO moment as a number to sort by; an empty one sorts last."""
    if not moment:
        return float("-inf")
    try:
        return time.mktime(time.strptime(moment[:19], "%Y-%m-%dT%H:%M:%S"))
    except ValueError:
        return float("-inf")


ADAPTER = SemaphoreAdapter()
