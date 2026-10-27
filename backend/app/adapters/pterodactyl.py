"""Pterodactyl: the game servers of an account, whether they run, and what they use.

The panel's **client API** (``/api/client``) takes an account's API key (made
under Account > API Credentials, starting with ``ptlc_``) as a bearer token
and lists the servers that account owns or may use. ``/servers/{id}/resources``
gives the state and the usage of one, and ``/servers/{id}/power`` starts and
stops it. The application API (``ptla_``, every server of the panel) is not
used: it cannot say whether a server runs.

Not measured. A panel needs a database, Redis and a Wings daemon on a node
before it can run a server, and none of that was started; everything follows
Pterodactyl's documentation (dashflo.net/docs/api/pterodactyl/v1/) and is
untested against a panel. Two places worth a look when it meets one:

* ``current_state`` is ``running``, ``starting``, ``stopping`` or ``offline``.
* The server's ``limits`` are in megabytes (memory, disk) and percent (cpu, where
  0 means unlimited), while the resources are in bytes.
"""

from __future__ import annotations

import asyncio
from typing import Any

from . import demo as fake
from .base import (
    Action,
    Adapter,
    AdapterError,
    Context,
    Field,
    WidgetData,
    WidgetType,
    base_url,
    duration_short,
    human_bytes,
    path_segment,
    percent,
    status_from_percent,
)

#: How many servers are asked for their resources one by one, and how many at once.
MAX_SERVERS = 40
PARALLEL = 6
HEADERS = {"Accept": "Application/vnd.pterodactyl.v1+json", "Content-Type": "application/json"}
STATES = {"running": "Running", "starting": "Starting", "stopping": "Stopping", "offline": "Offline"}


class PterodactylAdapter(Adapter):
    kind = "pterodactyl"
    label = "Pterodactyl"
    category = "hosts"
    description = "The game servers of a Pterodactyl account: which run, how much they use, and buttons to start and stop them."
    icon = "pterodactyl"
    docs_url = "https://dashflo.net/docs/api/pterodactyl/v1/"
    #: Built from the documentation and not run against a panel; it stays beta until somebody confirms it on one.
    beta = True
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="https://panel.example.com",
              help="The address of the panel."),
        Field("api_key", "API key", type="password", secret=True, required=True,
              help="A client key from Account > API Credentials, starting with ptlc_. It sees the servers of that account."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    guide = (
        "In the panel open your account's API Credentials and create a key. Pterodactyl shows it once.",
        "It must be a client key (ptlc_), not an application key (ptla_). It sees and may power the servers of the account it was made in.",
    )
    widgets = (
        WidgetType(
            kind="overview",
            label="Overview",
            description="How many servers run, how many are off or suspended.",
            renderer="value",
            default_size=(2, 2),
            min_size=(1, 1),
            refresh_seconds=60,
            metrics=("running", "offline"),
        ),
        WidgetType(
            kind="servers",
            label="Servers",
            description="Every server with its state, memory and processor use, and buttons to start or stop it.",
            renderer="list",
            default_size=(4, 3),
            refresh_seconds=60,
            options=(Field("limit", "Entries", type="number", default=12),),
        ),
    )

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, params: dict[str, Any] | None = None,
                   cache: float = 15) -> Any:
        response = await ctx.request(
            "GET", f"{base_url(config)}/api/client{path}", params=params,
            headers={**HEADERS, "Authorization": f"Bearer {config.get('api_key') or ''}"},
            verify=not config.get("insecure"), cache_seconds=cache,
        )
        if response.status_code >= 400:
            raise AdapterError(f"The panel answered with HTTP {response.status_code}.", code="http_error",
                               hint="Check the URL; it is the address of the panel, and the key has to be a client key (ptlc_).")
        try:
            return response.json()
        except ValueError as error:
            raise AdapterError("The panel did not answer with JSON.", code="not_json",
                               hint="The URL probably points at another service, or at a proxy that answers with a page.") from error

    async def _servers(self, config: dict[str, Any], ctx: Context) -> list[dict[str, Any]]:
        """Each server of the account with its resources; ``state`` is None where they could not be read."""
        listed = await self._get(config, ctx, "", {"per_page": 100})
        servers = [one.get("attributes") or {} for one in (listed or {}).get("data") or [] if isinstance(one, dict)][:MAX_SERVERS]
        gate = asyncio.Semaphore(PARALLEL)

        async def one(server: dict[str, Any]) -> dict[str, Any]:
            if server.get("is_suspended"):
                return {**server, "state": "suspended", "resources": {}}
            try:
                async with gate:
                    stats = await self._get(config, ctx, f"/servers/{path_segment(server.get('identifier'), 'The server')}/resources")
            except AdapterError as error:
                if error.code == "bad_param":
                    raise
                return {**server, "state": None, "resources": {}}
            attributes = (stats or {}).get("attributes") or {}
            return {**server, "state": str(attributes.get("current_state") or "") or None, "resources": attributes.get("resources") or {}}

        return list(await asyncio.gather(*(one(server) for server in servers)))

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        listed = await self._get(config, ctx, "", {"per_page": 1}, cache=0)
        total = (((listed or {}).get("meta") or {}).get("pagination") or {}).get("total")
        return f"Pterodactyl answers, {total if total is not None else len((listed or {}).get('data') or [])} server(s)."

    async def running_version(self, config: dict[str, Any], ctx: Context) -> str | None:
        return None

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        servers = await self._servers(config, ctx)
        if widget_kind == "servers":
            return self._list(servers, options)
        return self._overview(servers)

    def _overview(self, servers: list[dict[str, Any]]) -> WidgetData:
        running = sum(1 for one in servers if one["state"] in ("running", "starting"))
        suspended = sum(1 for one in servers if one["state"] == "suspended")
        unknown = sum(1 for one in servers if one["state"] is None)
        secondary = [{"label": "Servers", "value": len(servers)}, {"label": "Offline", "value": len(servers) - running - suspended - unknown}]
        if suspended:
            secondary.append({"label": "Suspended", "value": suspended})
        return WidgetData(
            status="warn" if suspended else "ok",
            primary={"label": "Running", "value": running},
            secondary=secondary,
            metrics={"running": float(running), "offline": float(len(servers) - running - suspended - unknown)},
        )

    def _list(self, servers: list[dict[str, Any]], options: dict[str, Any]) -> WidgetData:
        items = []
        for server in servers:
            state = server["state"]
            resources = server["resources"]
            limits = server.get("limits") or {}
            memory = resources.get("memory_bytes")
            memory_limit = int(limits.get("memory") or 0) * 1024 * 1024
            share = percent(memory, memory_limit) if memory is not None and memory_limit else None
            parts = []
            if state == "running":
                if memory is not None:
                    parts.append(f"{human_bytes(memory)} of {human_bytes(memory_limit)}" if memory_limit else human_bytes(memory))
                if resources.get("cpu_absolute") is not None:
                    parts.append(f"CPU {resources['cpu_absolute']:.0f} %")
                if resources.get("uptime"):
                    parts.append(f"up {duration_short(float(resources['uptime']) / 1000)}")
            identifier = str(server.get("identifier") or "")
            actions = []
            if identifier and state == "offline":
                actions = [Action(id="start", label="Start", icon="play", confirm=True, params={"id": identifier})]
            elif identifier and state in ("running", "starting"):
                actions = [Action(id="stop", label="Stop", icon="power", confirm=True, danger=True, params={"id": identifier})]
            items.append({
                "title": str(server.get("name") or identifier or "?"),
                "subtitle": " · ".join(parts),
                "status": "warn" if state in ("suspended", "starting", "stopping") else "unknown" if state is None else status_from_percent(share) if share is not None else "ok",
                "value": "Suspended" if state == "suspended" else STATES.get(str(state), "Unknown"),
                "actions": actions,
            })
        order = {"bad": 0, "warn": 1, "ok": 2, "unknown": 3}
        items.sort(key=lambda row: (order[row["status"]], row["value"] == "Offline", row["title"].casefold()))
        states = {row["status"] for row in items}
        return WidgetData(
            status="bad" if "bad" in states else "warn" if "warn" in states else "ok",
            items=items[: int(options.get("limit") or 12)],
            secondary=[{"label": "Servers", "value": len(items)}],
        )

    async def action(self, widget_kind: str, action_id: str, params: dict[str, Any], config: dict[str, Any],
                     options: dict[str, Any], ctx: Context) -> str:
        if action_id not in ("start", "stop"):
            raise AdapterError("Pterodactyl has no such action.", code="no_such_action")
        identifier = path_segment(params.get("id"), "The server")
        response = await ctx.request(
            "POST", f"{base_url(config)}/api/client/servers/{identifier}/power",
            headers={**HEADERS, "Authorization": f"Bearer {config.get('api_key') or ''}"},
            json_body={"signal": action_id}, verify=not config.get("insecure"), auth_errors=False,
        )
        if response.status_code in (401, 403):
            raise AdapterError("The panel refused the power signal.", code="not_allowed",
                               hint="The account may not control this server, or it is suspended.")
        if response.status_code >= 400:
            raise AdapterError(f"The panel answered with HTTP {response.status_code}.", code="http_error")
        ctx.forget_answers()
        return "The server is starting." if action_id == "start" else "The server is stopping."

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        down = fake.flicker("pterodactyl-down", tick, 0.2)
        servers = [
            {"identifier": "a1b2c3d4", "name": "Survival", "limits": {"memory": 4096}, "state": "running",
             "resources": {"memory_bytes": int(fake.walk("pterodactyl-m1", tick, 2.2, 3.8) * 1024 ** 3),
                           "cpu_absolute": fake.walk("pterodactyl-c1", tick, 8, 60), "uptime": 3_600_000 * 30}},
            {"identifier": "e5f6a7b8", "name": "Creative", "limits": {"memory": 2048}, "state": "offline" if down else "running",
             "resources": {} if down else {"memory_bytes": 900 * 1024 ** 2, "cpu_absolute": 12.0, "uptime": 3_600_000 * 5}},
            {"identifier": "c9d0e1f2", "name": "Modded", "limits": {"memory": 8192}, "state": "offline", "resources": {}},
            {"identifier": "03a4b5c6", "name": "Old test", "limits": {}, "state": "suspended", "resources": {}},
        ]
        if widget_kind == "servers":
            return self._list(servers, options)
        return self._overview(servers)


ADAPTER = PterodactylAdapter()
