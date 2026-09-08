"""n8n: workflows, their runs and the ones that failed.

The public API lives under ``/api/v1`` and takes its key in an
``X-N8N-API-KEY`` header. The key is made in n8n under Settings > n8n API;
it is not the account password, and an instance can have the public API
switched off entirely, which is worth saying out loud when it answers 404.

⚠️ Publishing a workflow has two names. ``POST /workflows/{id}/activate`` and
``/deactivate`` are what every 1.x instance has and are marked deprecated
upstream in favour of ``/publish`` and ``/unpublish``. Neither name works
everywhere, so the action tries the newer one and falls back, rather than
picking one and failing on half the installations out there.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from . import demo as fake
from .base import (
    Action,
    Adapter,
    AdapterError,
    AuthFailed,
    Context,
    Field,
    WidgetData,
    WidgetType,
    base_url,
    path_segment,
    percent,
)

#: How many runs to read for the failure count. The API caps a page at 250.
RUNS = 100

#: What a run's status means for a card's colour. "new" and "waiting" are not
#: failures: a workflow that waits for a webhook is doing its job.
COLOURS = {
    "success": "ok",
    "running": "ok",
    "new": "unknown",
    "waiting": "unknown",
    "canceled": "warn",
    "error": "bad",
    "crashed": "bad",
    "unknown": "unknown",
}


def _when(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _took(run: dict[str, Any]) -> str:
    """How long a run took, or nothing when it is still going."""
    began, ended = _when(run.get("startedAt")), _when(run.get("stoppedAt"))
    if began is None or ended is None:
        return ""
    seconds = (ended - began).total_seconds()
    if seconds < 1:
        return f"{seconds * 1000:.0f} ms"
    if seconds < 90:
        return f"{seconds:.1f} s"
    return f"{seconds / 60:.0f} min"


class N8nAdapter(Adapter):
    kind = "n8n"
    #: Run against a live instance on 2026-09-08: the address, the key and both
    #: endpoints answered. ⚠️ That instance held no workflows, so the field
    #: names, the durations and the two names of the publish action rest on
    #: n8n's own OpenAPI spec rather than on something seen. If a card here
    #: ever comes out wrong, that is the first place to look.
    beta = False
    label = "n8n"
    category = "monitoring"
    description = "Workflows with their state, the last runs and how many of them failed."
    icon = "n8n"
    docs_url = "https://docs.n8n.io/api/"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://n8n:5678"),
        Field("api_key", "API key", type="password", secret=True, required=True,
              help="Made in n8n under Settings > n8n API. Not the account password."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(
            kind="workflows",
            label="Workflows",
            description="Every workflow with its state, and a button to publish or unpublish it.",
            renderer="list",
            default_size=(3, 3),
            refresh_seconds=60,
            metrics=("active",),
            options=(
                Field("only_active", "Only published workflows", type="bool", default=False),
                Field("limit", "Entries", type="number", default=15),
            ),
        ),
        WidgetType(
            kind="runs",
            label="Last runs",
            description="The most recent executions with their state and how long each took.",
            renderer="list",
            default_size=(3, 3),
            refresh_seconds=30,
            options=(
                Field("failed_only", "Only the failed ones", type="bool", default=False),
                Field("limit", "Entries", type="number", default=15),
            ),
        ),
        WidgetType(
            kind="summary",
            label="Summary",
            description="Published workflows, and how many of the last runs failed.",
            renderer="stats",
            default_size=(3, 2),
            min_size=(2, 2),
            refresh_seconds=60,
            metrics=("active", "failed"),
        ),
    )

    # -- talking to it -------------------------------------------------------

    def _headers(self, config: dict[str, Any]) -> dict[str, str]:
        return {"X-N8N-API-KEY": str(config.get("api_key") or ""), "Accept": "application/json"}

    async def _api(self, config: dict[str, Any], ctx: Context, path: str,
                   params: dict[str, Any] | None = None, cache: float = 20) -> dict[str, Any]:
        response = await ctx.request(
            "GET", f"{base_url(config)}/api/v1/{path}", params=params,
            headers=self._headers(config), verify=not config.get("insecure", False),
            cache_seconds=cache, auth_errors=False,
        )
        if response.status_code in (401, 403):
            raise AuthFailed("n8n refused the API key.")
        if response.status_code == 404:
            # ⚠️ The most common way this fails, and the least obvious. The
            # public API is a separate switch in n8n, and with it off every
            # address under /api/v1 is simply not there.
            raise AdapterError(
                "n8n answered 404. Is the public API switched on?", code="no_public_api",
                hint="N8N_PUBLIC_API_DISABLED must not be true, and the version has to be 1.x or newer.")
        if response.status_code >= 400:
            raise AdapterError(f"n8n answered with HTTP {response.status_code}.", code="http_error")
        try:
            return response.json()
        except ValueError as why:
            raise AdapterError("n8n answered with something that is not JSON.", code="bad_json") from why

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        found = await self._api(config, ctx, "workflows", {"limit": 1}, cache=0)
        published = await self._api(config, ctx, "workflows", {"active": "true", "limit": 250}, cache=0)
        total = found.get("data") or []
        return (f"n8n answers. {len(published.get('data') or [])} of the workflows are published."
                if total else "n8n answers. There are no workflows yet.")

    # -- the cards -----------------------------------------------------------

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "workflows":
            return await self._workflows(config, options, ctx)
        runs = (await self._api(config, ctx, "executions", {"limit": RUNS}, cache=15)).get("data") or []
        if widget_kind == "summary":
            return await self._summary(config, ctx, runs)
        return self._runs(options, runs, await self._names(config, ctx))

    async def _names(self, config: dict[str, Any], ctx: Context) -> dict[str, str]:
        """Workflow id to name, because a run only carries the id.

        One call for the whole card. A name per run would be one request per
        row, and a run list is fifteen rows.
        """
        found = await self._api(config, ctx, "workflows", {"limit": 250}, cache=60)
        return {str(one.get("id")): str(one.get("name") or one.get("id")) for one in found.get("data") or []}

    async def _workflows(self, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        params: dict[str, Any] = {"limit": 250}
        if options.get("only_active"):
            params["active"] = "true"
        found = (await self._api(config, ctx, "workflows", params, cache=30)).get("data") or []
        # An archived workflow is put away on purpose; listing it among the
        # live ones would be a row nobody can act on.
        alive = [one for one in found if not one.get("isArchived")]
        published = [one for one in alive if one.get("active")]
        items = []
        for one in sorted(alive, key=lambda w: (not w.get("active"), str(w.get("name") or "").lower()))[: int(options.get("limit") or 15)]:
            on = bool(one.get("active"))
            tags = ", ".join(str(tag.get("name") or "") for tag in (one.get("tags") or []) if tag.get("name"))
            items.append({
                "id": str(one.get("id") or ""),
                "title": str(one.get("name") or "?"),
                "subtitle": tags,
                "status": "ok" if on else "unknown",
                "value": "published" if on else "off",
                "actions": [Action(id="unpublish", label="Unpublish", icon="pause", confirm=True,
                                   params={"id": str(one.get("id") or "")})]
                if on else [Action(id="publish", label="Publish", icon="play", params={"id": str(one.get("id") or "")})],
            })
        return WidgetData(
            status="ok",
            items=items,
            secondary=[{"label": "Published", "value": len(published)},
                       {"label": "Workflows", "value": len(alive)}],
            metrics={"active": float(len(published))},
            meta={"empty": "No workflows"},
        )

    def _runs(self, options: dict[str, Any], runs: list[dict[str, Any]], names: dict[str, str]) -> WidgetData:
        wanted = [one for one in runs if COLOURS.get(str(one.get("status")), "unknown") == "bad"] \
            if options.get("failed_only") else runs
        items = []
        for one in wanted[: int(options.get("limit") or 15)]:
            state = str(one.get("status") or "unknown")
            took = _took(one)
            items.append({
                "title": names.get(str(one.get("workflowId")), str(one.get("workflowId") or "?")),
                "subtitle": " · ".join(part for part in (state, str(one.get("mode") or "")) if part),
                "status": COLOURS.get(state, "unknown"),
                "value": took,
            })
        failed = [one for one in runs if COLOURS.get(str(one.get("status")), "unknown") == "bad"]
        return WidgetData(
            status="bad" if failed else "ok",
            items=items,
            secondary=[{"label": "Failed", "value": len(failed)}, {"label": "Runs", "value": len(runs)}],
            meta={"empty": "No runs yet"},
        )

    async def _summary(self, config: dict[str, Any], ctx: Context, runs: list[dict[str, Any]]) -> WidgetData:
        found = (await self._api(config, ctx, "workflows", {"limit": 250}, cache=30)).get("data") or []
        alive = [one for one in found if not one.get("isArchived")]
        published = [one for one in alive if one.get("active")]
        failed = [one for one in runs if COLOURS.get(str(one.get("status")), "unknown") == "bad"]
        # ⚠️ A share of the runs that were read, not of all runs ever. Saying
        # "3% failed" about a window whose size is not on the card would be a
        # number nobody can check.
        share = percent(len(failed), len(runs))
        return WidgetData(
            status="bad" if failed else "ok",
            primary={"label": "Published", "value": len(published), "unit": f"/ {len(alive)}", "metric": "active"},
            secondary=[
                {"label": "Failed runs", "value": len(failed), "metric": "failed"},
                {"label": "Of the last", "value": len(runs)},
                *([{"label": "Failure rate", "value": share, "unit": "%"}] if share is not None else []),
            ],
            metrics={"active": float(len(published)), "failed": float(len(failed))},
        )

    # -- the buttons ---------------------------------------------------------

    async def action(self, widget_kind: str, action_id: str, params: dict[str, Any],
                     config: dict[str, Any], options: dict[str, Any], ctx: Context) -> str:
        if action_id not in ("publish", "unpublish"):
            raise AdapterError("Unknown workflow action.", code="no_such_action")
        workflow = path_segment(params.get("id"), "The workflow")
        # ⚠️ Two names for one thing. /publish and /unpublish are the current
        # ones; /activate and /deactivate are what a 1.x instance has and are
        # deprecated upstream. Trying the new name first and falling back on a
        # 404 covers both without asking anybody which version they run.
        older = {"publish": "activate", "unpublish": "deactivate"}[action_id]
        for name in (action_id, older):
            response = await ctx.request(
                "POST", f"{base_url(config)}/api/v1/workflows/{workflow}/{name}",
                headers=self._headers(config), verify=not config.get("insecure", False), auth_errors=False,
            )
            if response.status_code == 404:
                continue
            if response.status_code in (401, 403):
                raise AuthFailed("n8n refused the API key. Does it carry the workflow scope?")
            if response.status_code >= 400:
                raise AdapterError(f"n8n answered with HTTP {response.status_code}.", code="action_failed")
            return "Workflow published." if action_id == "publish" else "Workflow unpublished."
        raise AdapterError("n8n knows neither name for this action.", code="action_failed",
                           hint="Neither /publish nor /activate answered. Is the public API switched on?")

    # -- what it looks like with nothing connected ---------------------------

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        flows = [("Backup to the NAS", True), ("Invoices to Paperless", True), ("Weather to Telegram", True),
                 ("Certificate watch", True), ("Old files away", False), ("Test bench", False)]
        published = [one for one in flows if one[1]]
        runs = [{"name": name, "status": state} for name, state in (
            ("Backup to the NAS", "success"), ("Invoices to Paperless", "success"),
            ("Weather to Telegram", "error" if fake.flicker("n8n-fail", tick, 0.3) else "success"),
            ("Certificate watch", "success"), ("Backup to the NAS", "success"),
            ("Invoices to Paperless", "waiting"),
        )]
        failed = [one for one in runs if COLOURS.get(one["status"], "unknown") == "bad"]
        if widget_kind == "summary":
            share = percent(len(failed), len(runs))
            return WidgetData(
                status="bad" if failed else "ok",
                primary={"label": "Published", "value": len(published), "unit": f"/ {len(flows)}", "metric": "active"},
                secondary=[{"label": "Failed runs", "value": len(failed), "metric": "failed"},
                           {"label": "Of the last", "value": len(runs)},
                           *([{"label": "Failure rate", "value": share, "unit": "%"}] if share is not None else [])],
                metrics={"active": float(len(published)), "failed": float(len(failed))},
            )
        if widget_kind == "runs":
            items = [{"title": one["name"], "subtitle": f"{one['status']} · trigger",
                      "status": COLOURS.get(one["status"], "unknown"),
                      "value": f"{fake.walk(one['name'], tick, 0.4, 12):.1f} s"} for one in runs]
            return WidgetData(status="bad" if failed else "ok", items=items,
                              secondary=[{"label": "Failed", "value": len(failed)}, {"label": "Runs", "value": len(runs)}])
        items = [{"id": name, "title": name, "subtitle": "nightly" if on else "",
                  "status": "ok" if on else "unknown", "value": "published" if on else "off",
                  "actions": [Action(id="unpublish", label="Unpublish", icon="pause", confirm=True, params={"id": name})]
                  if on else [Action(id="publish", label="Publish", icon="play", params={"id": name})]}
                 for name, on in flows]
        return WidgetData(status="ok", items=items,
                          secondary=[{"label": "Published", "value": len(published)}, {"label": "Workflows", "value": len(flows)}],
                          metrics={"active": float(len(published))})


ADAPTER = N8nAdapter()
