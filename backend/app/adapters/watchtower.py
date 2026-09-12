"""Watchtower: what its last update run did, with a button that starts the next one.

Measured against Watchtower 1.22.1 on 11.09.2026, the image
``nickfedor/watchtower`` of the maintained fork; ``containrrr/watchtower`` is
archived. Three test containers sat in a scope of their own and carried the
enable label: one on an older build of its tag, one up to date, one on an
image no registry has. Nothing else on the host was in reach.

⚠️ Everything under ``/v1`` wants ``Authorization: Bearer`` with
``WATCHTOWER_HTTP_API_TOKEN``. No header, a made-up token and the token as
``access_token`` in the address all got 401 "missing or invalid API Key" as
plain text.

⚠️ ``/v1/status`` answers 204 with no body until the first run, and again after
every restart: the status, the history and the metrics live in memory only.
A ``/v1/check`` is not a run and left all three as they were.

⚠️ Every endpoint has to be switched on. With ``WATCHTOWER_HTTP_API_ENDPOINTS``
naming only ``update``, ``/v1/status`` got 404; with only ``metrics``, a run
got 404. The older ``WATCHTOWER_HTTP_API_METRICS`` and
``WATCHTOWER_HTTP_API_UPDATE`` still switch on both.

⚠️ A run started with ``?async=true`` answered 202 "Accepted" at once; without
it the answer waited 8 seconds for the pull and the new container. A second
run while one was going got 429 with ``Retry-After: 30``. Switching on the
update endpoint turns off Watchtower's own schedule unless
``WATCHTOWER_HTTP_API_PERIODIC_POLLS`` is set, and its log says so at start.

⚠️ An image no registry has was counted neither as failed nor as skipped: its
digest lookup got 404, and the run reported 3 scanned, 1 updated, 0 failed.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
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
    ago,
    base_url,
)

RUN_NOW = Action(id="run", label="Run now", icon="play", confirm=True)


class WatchtowerAdapter(Adapter):
    kind = "watchtower"
    label = "Watchtower"
    category = "hosts"
    description = "What the last update run did, with a button that starts the next one."
    icon = "watchtower"
    #: Confirmed against a live instance on 2026-09-11.
    beta = False
    docs_url = "https://watchtower.nickfedor.com/"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://watchtower:8080"),
        Field("token", "API token", type="password", secret=True, required=True,
              help="WATCHTOWER_HTTP_API_TOKEN. The card needs metrics in WATCHTOWER_HTTP_API_ENDPOINTS, the button needs update."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(kind="summary", label="Last update run",
                   description="How many containers the last run updated, how many failed, and when it ran.",
                   renderer="value", default_size=(3, 2), refresh_seconds=120, metrics=("updated", "failed")),
    )

    def _headers(self, config: dict[str, Any]) -> dict[str, str]:
        return {"Authorization": f"Bearer {str(config.get('token') or '').strip()}"}

    async def _status(self, config: dict[str, Any], ctx: Context, cache: float = 10) -> dict[str, Any] | None:
        """The last run, or ``None`` when there has been none since Watchtower started."""
        response = await ctx.request("GET", f"{base_url(config)}/v1/status", headers=self._headers(config),
                                     verify=not config.get("insecure"), cache_seconds=cache, auth_errors=False)
        if response.status_code in (401, 403):
            raise AuthFailed("Watchtower rejected the API token.")
        if response.status_code == 204:
            return None
        if response.status_code == 404:
            raise AdapterError("Watchtower answers, but its status endpoint is switched off.", code="endpoint_off",
                               hint="Add metrics to WATCHTOWER_HTTP_API_ENDPOINTS. The status needs the maintained fork, nickfedor/watchtower.")
        if response.status_code >= 400:
            raise AdapterError(f"Watchtower answered with HTTP {response.status_code}.", code="http_error",
                               hint="Check the URL; it is the address of Watchtower's HTTP API, port 8080 inside the container.")
        try:
            answer = response.json()
        except ValueError as error:
            raise AdapterError("Watchtower did not answer with JSON.", code="not_json",
                               hint="The URL probably points at something else than Watchtower's HTTP API.") from error
        if not isinstance(answer, dict) or not isinstance(answer.get("summary"), dict):
            raise AdapterError("This address answers, but not the way Watchtower does.", code="not_watchtower")
        return answer

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        status = await self._status(config, ctx, cache=0)
        if status is None:
            return "Watchtower answers. It has not run since it started."
        summary = status["summary"]
        return (f"Watchtower answers. Its last run updated {int(summary.get('updated') or 0)} "
                f"of {int(summary.get('scanned') or 0)} containers.")

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        return self._summary(await self._status(config, ctx))

    async def action(self, widget_kind: str, action_id: str, params: dict[str, Any],
                     config: dict[str, Any], options: dict[str, Any], ctx: Context) -> str:
        if action_id != "run":
            raise AdapterError("Watchtower has no such action.", code="no_such_action")
        # ⚠️ Asynchronous: without it the answer waits for every pull and every new container.
        response = await ctx.request("POST", f"{base_url(config)}/v1/update", headers=self._headers(config),
                                     params={"async": "true"}, verify=not config.get("insecure"), auth_errors=False)
        if response.status_code in (401, 403):
            raise AuthFailed("Watchtower rejected the API token.")
        if response.status_code == 429:
            raise AdapterError("Watchtower did not start a run: one is still going, or too many requests came in.", code="action_failed",
                               hint=f"Try again in {response.headers.get('Retry-After') or 'a few'} seconds.")
        if response.status_code == 404:
            raise AdapterError("Watchtower answers, but its update endpoint is switched off.", code="endpoint_off",
                               hint="Add update to WATCHTOWER_HTTP_API_ENDPOINTS.")
        if response.status_code >= 400:
            raise AdapterError(f"Watchtower answered with HTTP {response.status_code}.", code="action_failed")
        ctx.forget_answers()
        return "Watchtower has started an update run."

    # -- the card ------------------------------------------------------------

    @staticmethod
    def _summary(status: dict[str, Any] | None, now: float | None = None) -> WidgetData:
        if status is None:
            return WidgetData(status="unknown", primary={"label": "Updated", "value": None}, actions=[RUN_NOW],
                              meta={"empty": "No run since Watchtower started."})
        summary = status["summary"]
        updated, failed, scanned = (int(summary.get(key) or 0) for key in ("updated", "failed", "scanned"))
        secondary: list[dict[str, Any]] = [{"label": "Failed", "value": failed}]
        last = ago(status.get("timestamp"), now=now)
        if last:
            secondary.append({"label": "Last run", "value": last})
        return WidgetData(
            status="bad" if failed else "ok",
            primary={"label": "Updated", "value": updated, "unit": f"/ {scanned}"},
            secondary=secondary,
            actions=[RUN_NOW],
            metrics={"updated": float(updated), "failed": float(failed)},
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        moment = datetime.fromtimestamp(time.time() - (35 + tick % 40) * 60, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        summary = {"scanned": 24, "updated": 2 if fake.flicker("watchtower-updated", tick, 0.5) else 1,
                   "failed": 1 if fake.flicker("watchtower-failed", tick, 0.2) else 0, "restarted": 0, "skipped": 0}
        return self._summary({"api_version": "v1", "summary": summary, "timestamp": moment})


ADAPTER = WatchtowerAdapter()
