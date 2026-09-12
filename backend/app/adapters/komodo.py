"""Komodo: stacks and deployments with their state, the servers behind them, and a restart for a stack.

Measured against Komodo 2.3.3, core and periphery, on 11.09.2026 with MongoDB
8.0. Periphery worked against a Docker daemon of its own inside the test stack,
so the server Komodo saw held only the test resources: a stack of two nginx
services, a stack whose image no registry has, and one deployment.

⚠️ The API is one address per request, ``POST /read/ListStacks``, with the
parameters as the body. An API key goes as ``X-Api-Key`` and ``X-Api-Secret``.
A wrong pair got 401 "Invalid user credentials | You have 4 attempts
remaining", no headers 401 "Invalid client credentials".

⚠️ Five wrong pairs from one address lock that address. The sixth request got
429 "Too many attempts | Try again in 15s", and so did the right key sent from
the same address, while the right key from another address still got in. A
card with a wrong secret spends those attempts for everything else nexdeck
sends to Komodo.

⚠️ A key sees what its user may see, and seeing nothing is an empty list, not a
refusal: a service user without permissions got ``[]`` and summaries of 0 from
a Komodo with two stacks. It needs Read on stacks, deployments and servers.

⚠️ An execute answers 200 at once with an Update that is ``InProgress`` and
says ``success: true``. A user with only Read on the stack got exactly that for
a restart, and the Update ended a moment later with ``success: false`` and
"User does not have required permissions on this Stack. Must have at least
Execute permissions". The restart button therefore follows the Update until it
is complete and reports what it says.

⚠️ With periphery stopped, every stack and deployment on that server read
``unknown``, not down, and only the servers summary counted the server as
unhealthy. A list of nothing but unknown states is not drawn as a calm one.

⚠️ A stack whose image could not be pulled is ``down``; its deploy ended at the
stage "Compose Pull" with "pull access denied".
"""

from __future__ import annotations

import asyncio
import re
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
)

#: How long the restart button follows the Update: a second apart, a minute at most.
POLL_SECONDS = 1.0
POLL_ATTEMPTS = 60

STACK_WORD = {"deploying": "Deploying", "running": "Running", "paused": "Paused", "stopped": "Stopped", "created": "Created",
              "restarting": "Restarting", "dead": "Dead", "removing": "Removing", "unhealthy": "Unhealthy", "down": "Down", "unknown": "Unknown"}
DEPLOYMENT_WORD = {"deploying": "Deploying", "running": "Running", "created": "Created", "restarting": "Restarting", "stopping": "Stopping",
                   "removing": "Removing", "paused": "Paused", "exited": "Exited", "dead": "Dead", "unhealthy": "Unhealthy",
                   "not_deployed": "Not deployed", "unknown": "Unknown"}
BAD = {"down", "dead", "unhealthy", "exited"}
QUIET = {"unknown", "not_deployed"}
#: A stack in one of these has containers a restart can reach.
RESTARTABLE = {"running", "unhealthy", "restarting", "paused", "stopped", "created", "dead"}
ORDER = {"bad": 0, "warn": 1, "unknown": 2, "ok": 3}


def _colour(state: str) -> str:
    if state == "running":
        return "ok"
    if state in BAD:
        return "bad"
    if state in QUIET:
        return "unknown"
    return "warn"


def _info(item: dict[str, Any]) -> dict[str, Any]:
    info = item.get("info")
    return info if isinstance(info, dict) else {}


def _reason(update: dict[str, Any]) -> str:
    """The error of the first failed step of an Update, without the markup Komodo writes into it."""
    for log in update.get("logs") or []:
        if isinstance(log, dict) and not log.get("success"):
            text = re.sub(r"<[^>]+>", "", str(log.get("stderr") or log.get("stdout") or ""))
            return " ".join(text.split()).removeprefix("ERROR: ")[:240]
    return ""


class KomodoAdapter(Adapter):
    kind = "komodo"
    label = "Komodo"
    category = "hosts"
    description = "Stacks and deployments with their state, the servers behind them, and a restart for a stack."
    icon = "komodo"
    #: Confirmed against a live instance on 2026-09-11.
    beta = False
    docs_url = "https://komo.do/docs"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://komodo:9120"),
        Field("api_key", "API key", type="password", secret=True, required=True,
              help="The key of a user, best a service user. It needs Read on stacks, deployments and servers, and Execute on a stack to restart it."),
        Field("api_secret", "API secret", type="password", secret=True, required=True),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(kind="stacks", label="Stacks", description="Every stack with its state and server, troubled ones first, with a restart button.",
                   renderer="list", default_size=(3, 3), refresh_seconds=60, metrics=("stacks_down",),
                   options=(Field("limit", "Entries", type="number", default=10),)),
        WidgetType(kind="deployments", label="Deployments", description="Every deployment with its state, image and server, troubled ones first.",
                   renderer="list", default_size=(3, 3), refresh_seconds=60,
                   options=(Field("limit", "Entries", type="number", default=10),)),
        WidgetType(kind="summary", label="Komodo overview", description="How many stacks run, and how many deployments run and servers answer.",
                   renderer="value", default_size=(3, 2), refresh_seconds=60, metrics=("stacks_running", "stacks_down")),
    )

    def _headers(self, config: dict[str, Any]) -> dict[str, str]:
        return {"X-Api-Key": str(config.get("api_key") or "").strip(), "X-Api-Secret": str(config.get("api_secret") or "").strip()}

    async def _post(self, config: dict[str, Any], ctx: Context, path: str, body: dict[str, Any], timeout: float = 15.0) -> Any:
        response = await ctx.request("POST", f"{base_url(config)}{path}", headers=self._headers(config), json_body=body,
                                     verify=not config.get("insecure"), timeout=timeout, auth_errors=False)
        if response.status_code in (401, 403):
            raise AuthFailed("Komodo rejected the API key or its secret. It counts failed attempts.")
        if response.status_code == 429:
            raise AdapterError("Komodo is turning nexdeck's address away after too many failed attempts.", code="rate_limited",
                               hint="Five wrong keys from one address lock it for 15 seconds, the right key included. Check the key and its secret.")
        try:
            answer = response.json()
        except ValueError as error:
            if response.status_code >= 400:
                raise AdapterError(f"Komodo answered with HTTP {response.status_code}.", code="http_error",
                                   hint="Check the URL; it is the address of Komodo Core, port 9120 by default.") from error
            raise AdapterError("Komodo did not answer with JSON.", code="not_json",
                               hint="The URL probably points at something else than Komodo Core.") from error
        if response.status_code >= 400:
            message = str(answer.get("error") or "") if isinstance(answer, dict) else ""
            raise AdapterError(f"Komodo refused: {message}" if message else f"Komodo answered with HTTP {response.status_code}.",
                               code="http_error")
        return answer

    async def _list(self, config: dict[str, Any], ctx: Context, request: str) -> list[dict[str, Any]]:
        # ⚠️ limit 0 is every entry; without it Komodo stops at its page size.
        answer = await self._post(config, ctx, f"/read/{request}", {"limit": 0})
        if not isinstance(answer, list):
            raise AdapterError("This address answers, but not the way Komodo does.", code="not_komodo")
        return [one for one in answer if isinstance(one, dict)]

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        version = await self._post(config, ctx, "/read/GetVersion", {})
        stacks = await self._list(config, ctx, "ListStacks")
        number = version.get("version") if isinstance(version, dict) else None
        return f"Komodo {number or '?'} answers; this key sees {len(stacks)} stacks."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "summary":
            stacks = await self._post(config, ctx, "/read/GetStacksSummary", {})
            deployments = await self._post(config, ctx, "/read/GetDeploymentsSummary", {})
            servers = await self._post(config, ctx, "/read/GetServersSummary", {})
            if not all(isinstance(one, dict) for one in (stacks, deployments, servers)):
                raise AdapterError("This address answers, but not the way Komodo does.", code="not_komodo")
            return self._summary(stacks, deployments, servers)
        limit = max(1, int(options.get("limit") or 10))
        if widget_kind == "deployments":
            return self._deployments(await self._list(config, ctx, "ListDeployments"), limit)
        return self._stacks(await self._list(config, ctx, "ListStacks"), limit)

    async def action(self, widget_kind: str, action_id: str, params: dict[str, Any],
                     config: dict[str, Any], options: dict[str, Any], ctx: Context) -> str:
        if action_id != "restart":
            raise AdapterError("Komodo has no such action.", code="no_such_action")
        stack = str(params.get("stack") or "").strip()
        if not stack or len(stack) > 128:
            raise AdapterError("That is not a stack this card offered.", code="bad_param")
        update = await self._post(config, ctx, "/execute/RestartStack", {"stack": stack}, timeout=30)
        identifier = str(((update.get("_id") or {}).get("$oid") if isinstance(update.get("_id"), dict) else update.get("id")) or "") \
            if isinstance(update, dict) else ""
        # ⚠️ The first answer says success before anything has run; only the finished Update knows.
        for _attempt in range(POLL_ATTEMPTS):
            if not isinstance(update, dict) or update.get("status") == "Complete" or not identifier:
                break
            await asyncio.sleep(POLL_SECONDS)
            update = await self._post(config, ctx, "/read/GetUpdate", {"id": identifier})
        if not isinstance(update, dict) or update.get("status") != "Complete":
            return "Komodo is restarting the stack; it had not finished when the card stopped waiting."
        ctx.forget_answers()
        if update.get("success"):
            return "Komodo has restarted the stack."
        reason = _reason(update)
        raise AdapterError(f"Komodo could not restart the stack: {reason}" if reason else "Komodo could not restart the stack.",
                           code="action_failed", hint="The API key's user needs Execute on this stack.")

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def _stacks(stacks: list[dict[str, Any]], limit: int) -> WidgetData:
        rows = []
        for stack in stacks:
            info = _info(stack)
            state = str(info.get("state") or "unknown")
            row: dict[str, Any] = {
                "title": str(stack.get("name") or "?"),
                "subtitle": " · ".join(part for part in (STACK_WORD.get(state, "Unknown"), str(info.get("server_name") or "")) if part),
                "status": _colour(state),
            }
            if state in RESTARTABLE and stack.get("id"):
                row["actions"] = [Action(id="restart", label="Restart", icon="rotate-cw", confirm=True, params={"stack": str(stack["id"])})]
            rows.append(row)
        rows.sort(key=lambda row: (ORDER.get(row["status"], 9), row["title"].lower()))
        down = sum(1 for stack in stacks if str(_info(stack).get("state") or "") in BAD)
        known = any(row["status"] != "unknown" for row in rows)
        return WidgetData(
            status="bad" if down else "ok" if known else "unknown",
            items=rows[:limit],
            meta={"empty": "No stacks, or none this API key may see."},
            metrics={"stacks_down": float(down)},
        )

    @staticmethod
    def _deployments(deployments: list[dict[str, Any]], limit: int) -> WidgetData:
        rows = []
        for deployment in deployments:
            info = _info(deployment)
            state = str(info.get("state") or "unknown")
            rows.append({
                "title": str(deployment.get("name") or "?"),
                "subtitle": " · ".join(part for part in (DEPLOYMENT_WORD.get(state, "Unknown"), str(info.get("image") or ""),
                                                         str(info.get("server_name") or "")) if part),
                "status": _colour(state),
            })
        rows.sort(key=lambda row: (ORDER.get(row["status"], 9), row["title"].lower()))
        troubled = sum(1 for row in rows if row["status"] == "bad")
        seen = any(row["status"] != "unknown" for row in rows)
        return WidgetData(
            status="bad" if troubled else "ok" if seen else "unknown",
            items=rows[:limit],
            meta={"empty": "No deployments, or none this API key may see."},
        )

    @staticmethod
    def _summary(stacks: dict[str, Any], deployments: dict[str, Any], servers: dict[str, Any]) -> WidgetData:
        def number(source: dict[str, Any], key: str) -> int:
            return int(source.get(key) or 0)

        troubled = number(stacks, "down") + number(stacks, "unhealthy") + number(deployments, "unhealthy") + number(servers, "unhealthy")
        seen = number(stacks, "total") + number(deployments, "total") + number(servers, "total")
        return WidgetData(
            status="bad" if troubled else "ok" if seen else "unknown",
            primary={"label": "Stacks running", "value": number(stacks, "running"), "unit": f"/ {number(stacks, 'total')}"},
            secondary=[
                {"label": "Deployments", "value": f"{number(deployments, 'running')} / {number(deployments, 'total')}"},
                {"label": "Servers", "value": f"{number(servers, 'healthy')} / {number(servers, 'total')}"},
            ],
            meta={} if seen else {"empty": "Komodo shows this API key nothing. Its user needs Read on stacks, deployments and servers."},
            metrics={"stacks_running": float(number(stacks, "running")), "stacks_down": float(number(stacks, "down"))},
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        restarting = fake.flicker("komodo-paperless", tick, 0.3)
        if widget_kind == "summary":
            return self._summary({"total": 14, "running": 12 if restarting else 13, "stopped": 0, "down": 1, "unhealthy": 1 if restarting else 0, "unknown": 0},
                                 {"total": 4, "running": 3, "stopped": 1, "not_deployed": 0, "unhealthy": 0, "unknown": 0},
                                 {"total": 2, "healthy": 2, "warning": 0, "unhealthy": 0, "disabled": 0})
        if widget_kind == "deployments":
            return self._deployments([
                {"id": "d1", "name": "whoami", "info": {"state": "running", "image": "traefik/whoami:v1.10", "server_name": "nas"}},
                {"id": "d2", "name": "backup-job", "info": {"state": "exited", "image": "example/backup:2.4", "server_name": "nas"}},
                {"id": "d3", "name": "speedtest", "info": {"state": "running", "image": "example/speedtest:1.2", "server_name": "vps"}},
            ], max(1, int(options.get("limit") or 10)))
        return self._stacks([
            {"id": "s1", "name": "immich", "info": {"state": "running", "server_name": "nas"}},
            {"id": "s2", "name": "paperless", "info": {"state": "restarting" if restarting else "running", "server_name": "nas"}},
            {"id": "s3", "name": "mealie", "info": {"state": "down", "server_name": "vps"}},
            {"id": "s4", "name": "traefik", "info": {"state": "running", "server_name": "vps"}},
        ], max(1, int(options.get("limit") or 10)))


ADAPTER = KomodoAdapter()
