"""Dockhand: every Docker environment Dockhand manages, its containers, compose stacks and the updates it found.

Measured against Dockhand 1.0.49 on 26.09.2026: two Docker engines of their
own, one reached directly over TCP and one through a Hawser agent, holding
only test containers. A compose stack that ran, one with a service that had
exited, a container failing its healthcheck, one that had finished, and an
image tagged older than its registry so that an update was waiting.

⚠️ Everything is under ``/api``. Without it the same address answers 200 with
the web interface. The adapter adds the prefix and takes one typed along.

⚠️ A token goes as ``Authorization: Bearer dh_…`` and carries every right of
the user who made it. There is no narrower token, and in Dockhand's free
edition every user may do everything. The cards only read.

⚠️ With sign-in switched off in Dockhand everything is open and a token is
not needed; one sent anyway is not looked at.

⚠️ Fifteen wrong tokens inside a minute lock the address for five minutes,
the right token included: 429 "Too many failed authentication attempts". The
lock was hit while measuring this, with the right token straight after.

⚠️ ``/dashboard/stats`` adds up every environment in one request: containers
with the unhealthy ones and pending updates, stacks, images, volumes,
networks, CPU and memory. The overview and the environment card read it and
nothing else. Asked for one environment it answers the object, not a list.

⚠️ An environment Dockhand cannot reach answers ``/containers``, ``/stacks``
and ``/containers/pending-updates`` with 200 and an empty list, the same as an
environment with nothing on it. Measured with the Hawser agent stopped and
with an address where no engine was: the agent's lists came back empty at
once, the dead address's after three seconds. Only ``/dashboard/stats`` says
``online: false``, and it said so straight away, so every list card asks it
first and leaves out what is not online instead of drawing it empty. An id
Dockhand does not know is a 404 "Environment not found".

⚠️ A container failing its healthcheck stays ``running``; ``health`` says
``unhealthy``, and so does the end of the status text.

⚠️ Updates are what Dockhand recorded when it last checked. Its scheduled
check is off by default, so an empty list after a fresh install means nobody
has checked, not that everything is current. The update card says which.
"""

from __future__ import annotations

import asyncio
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
    part_on,
)

TOKEN_HINT = "Make one in Dockhand under Profile > API tokens."

ENVIRONMENT = Field("environment", "Environment", type="choices", help="Empty for every environment.")

CONTAINER_WORD = {"running": "Running", "exited": "Exited", "created": "Created", "paused": "Paused",
                  "restarting": "Restarting", "removing": "Removing", "dead": "Dead"}
STACK_WORD = {"running": "Running", "partial": "Partially running", "stopped": "Stopped"}
ORDER = {"bad": 0, "warn": 1, "unknown": 2, "ok": 3}
PARTIAL = "Some environments did not answer; their rows are missing."


def _said(answer: Any) -> str:
    """What Dockhand wrote about a refusal."""
    if not isinstance(answer, dict):
        return ""
    for key in ("error", "message"):
        if answer.get(key):
            return " ".join(str(answer[key]).split())[:240]
    return ""


def _unhealthy(container: dict[str, Any]) -> bool:
    # ⚠️ The state stays "running".
    return container.get("health") == "unhealthy" or "(unhealthy)" in str(container.get("status") or "")


def _container_colour(container: dict[str, Any]) -> str:
    state = str(container.get("state") or "")
    if state == "running":
        return "bad" if _unhealthy(container) else "ok"
    if state in ("paused", "restarting", "created"):
        return "warn"
    return "bad"


def _stack_colour(status: str) -> str:
    return {"running": "ok", "partial": "warn", "stopped": "unknown"}.get(status, "unknown")


def _sorted(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda row: (ORDER.get(row["status"], 9), str(row["title"]).lower()))


def _percent(value: Any) -> str:
    try:
        share = float(value)
    except (TypeError, ValueError):
        return "?"
    # An idle engine sits well below one per cent; "0 %" would look broken.
    return f"{share:.1f} %" if share < 10 else f"{share:.0f} %"


class DockhandAdapter(Adapter):
    kind = "dockhand"
    label = "Dockhand"
    category = "hosts"
    description = "Every Docker environment Dockhand manages: containers with their health, compose stacks and the image updates it found."
    icon = "dockhand"
    beta = False
    docs_url = "https://dockhand.pro/manual/"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://dockhand:3000"),
        Field("api_token", "API token", type="password", secret=True,
              help="A token from Profile > API tokens, starting with dh_. Empty when sign-in is switched off in Dockhand. "
                   "A token may do everything its user may, and in Dockhand's free edition that is everything; the cards only read."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(kind="summary", label="Dockhand overview",
                   description="Running containers of every environment, with the unhealthy ones, stacks, environments, image updates, images, volumes and networks.",
                   renderer="value", default_size=(3, 2), refresh_seconds=60,
                   metrics=("containers_running", "containers_unhealthy", "updates_waiting"),
                   parts=(("unhealthy", "Unhealthy"), ("stacks", "Stacks"), ("environments", "Environments"),
                          ("updates", "Image updates"), ("images", "Images"), ("volumes", "Volumes"), ("networks", "Networks")),
                   options=(ENVIRONMENT,)),
        WidgetType(kind="environments", label="Environments",
                   description="Every environment with whether it answers, how many of its containers run, and its processor and memory.",
                   renderer="list", default_size=(3, 3), refresh_seconds=60, metrics=("environments_offline",),
                   parts=(("usage", "Processor and memory"),)),
        WidgetType(kind="stacks", label="Stacks",
                   description="Compose stacks with their state and how many of their containers run, troubled ones first.",
                   renderer="list", default_size=(3, 3), refresh_seconds=60,
                   options=(ENVIRONMENT,)),
        WidgetType(kind="containers", label="Containers",
                   description="Containers with their state and health, troubled ones first.",
                   renderer="list", default_size=(4, 4), refresh_seconds=30, metrics=("containers_running",),
                   options=(ENVIRONMENT, Field("show_stopped", "Show stopped containers", type="bool", default=True))),
        WidgetType(kind="updates", label="Image updates",
                   description="Containers whose image has a newer version, as Dockhand recorded when it last checked.",
                   renderer="list", default_size=(3, 3), refresh_seconds=300, metrics=("updates_waiting",),
                   options=(ENVIRONMENT,)),
    )

    # -- talking to Dockhand -------------------------------------------------

    @staticmethod
    def _api(config: dict[str, Any]) -> str:
        root = base_url(config)
        # ⚠️ Taken along if typed; without it the web interface answers.
        if root.lower().endswith("/api"):
            root = root[:-4]
        return f"{root}/api"

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, *, params: dict[str, Any] | None = None,
                   cache: float = 5) -> Any:
        token = str(config.get("api_token") or "").strip()
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        response = await ctx.request("GET", f"{self._api(config)}{path}", params=params, headers=headers,
                                     verify=not config.get("insecure"), timeout=20.0, cache_seconds=cache, auth_errors=False)
        try:
            answer: Any = response.json()
        except ValueError:
            answer = None
        if response.status_code >= 400:
            self._refused(response.status_code, answer, bool(token))
        if answer is None:
            raise AdapterError("This address answers with something other than Dockhand's API.", code="not_dockhand",
                               hint="Enter the address of Dockhand itself, port 3000 by default.")
        return answer

    @staticmethod
    def _refused(status: int, answer: Any, with_token: bool) -> None:
        said = _said(answer)
        if status == 401:
            if not with_token:
                raise AuthFailed("Dockhand asks for sign-in. Add an API token.")
            raise AuthFailed("Dockhand rejected the API token.")
        if status == 429:
            raise AdapterError("Dockhand has locked this address after too many wrong tokens.", code="locked",
                               hint="Fifteen wrong tokens inside a minute lock it for five minutes, the right token included. "
                                    "Check the token, then wait.")
        if status == 403:
            if "environment" in said.lower():
                raise AdapterError("The token's user may not reach this environment.", code="forbidden", hint=TOKEN_HINT)
            raise AdapterError("The token's user lacks a permission in Dockhand.", code="forbidden",
                               hint="Roles exist only in Dockhand's paid editions; give the user a role that may view.")
        if status == 404 and "environment" in said.lower():
            raise AdapterError("Dockhand has no such environment.", code="no_environment",
                               hint="Pick another environment in the card's settings.")
        if answer is None:
            raise AdapterError(f"Dockhand answered with HTTP {status}.", code="http_error",
                               hint="Check the URL; it is the address of Dockhand itself, port 3000 by default.")
        raise AdapterError(f"Dockhand refused: {said}" if said else f"Dockhand answered with HTTP {status}.", code="http_error")

    async def _environments(self, config: dict[str, Any], ctx: Context, cache: float = 30) -> list[dict[str, Any]]:
        found = await self._get(config, ctx, "/environments", cache=cache)
        if not isinstance(found, list):
            raise AdapterError("This address answers, but not the way Dockhand does.", code="not_dockhand")
        return sorted((one for one in found if isinstance(one, dict) and one.get("id") is not None),
                      key=lambda one: str(one.get("name") or "").lower())

    async def _stats(self, config: dict[str, Any], ctx: Context, environment: str = "") -> list[dict[str, Any]]:
        found = await self._get(config, ctx, "/dashboard/stats", params={"env": environment} if environment else None, cache=10)
        # One environment comes back as the object itself.
        entries = [found] if isinstance(found, dict) else found
        if not isinstance(entries, list):
            raise AdapterError("This address answers, but not the way Dockhand does.", code="not_dockhand")
        return sorted((one for one in entries if isinstance(one, dict)), key=lambda one: str(one.get("name") or "").lower())

    async def _chosen(self, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> tuple[list[dict[str, Any]], bool]:
        """The environments a card may ask, the one picked or every one, and whether some had to be left out.

        ⚠️ Taken from the stats, not from ``/environments``: an environment
        Dockhand cannot reach answers its lists with 200 and nothing in them,
        exactly like an empty one. Only the stats say ``online: false``.
        """
        wanted = str(options.get("environment") or "").strip()
        known = await self._stats(config, ctx, wanted)
        online = [one for one in known if one.get("online") and one.get("id") is not None]
        if known and not online:
            raise AdapterError("Dockhand cannot reach this environment." if wanted or len(known) == 1
                               else "Dockhand cannot reach any of its environments.", code="environment_unreachable",
                               hint="The Docker engine or the Hawser agent behind it does not answer.")
        return online, len(online) < len(known)

    async def _each(self, environments: list[dict[str, Any]], ask: Any) -> tuple[list[tuple[dict[str, Any], Any]], list[AdapterError]]:
        """Ask every environment at once; one that does not answer must not take the others with it."""
        answers = await asyncio.gather(*(ask(one) for one in environments), return_exceptions=True)
        good: list[tuple[dict[str, Any], Any]] = []
        failed: list[AdapterError] = []
        for environment, answer in zip(environments, answers, strict=True):
            if isinstance(answer, AuthFailed) or (isinstance(answer, AdapterError) and answer.code == "locked"):
                raise answer
            if isinstance(answer, AdapterError):
                failed.append(answer)
            elif isinstance(answer, BaseException):
                raise answer
            else:
                good.append((environment, answer))
        if failed and not good:
            raise failed[0]
        return good, failed

    async def _list(self, config: dict[str, Any], ctx: Context, environment: dict[str, Any], path: str) -> Any:
        return await self._get(config, ctx, path, params={"env": str(environment["id"])})

    # -- the hooks -----------------------------------------------------------

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        environments = await self._environments(config, ctx, cache=0)
        return f"Dockhand answers and manages {len(environments)} environment(s)."

    async def choices(self, field: str, config: dict[str, Any], ctx: Context) -> list[tuple[str, str]]:
        if field != "environment":
            return await super().choices(field, config, ctx)
        return [(str(one["id"]), str(one.get("name") or one["id"])) for one in await self._environments(config, ctx)]

    def demo_choices(self, field: str) -> list[tuple[str, str]]:
        if field != "environment":
            return []
        return [(str(one["id"]), one["name"]) for one in DEMO_STATS]

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "environments":
            return self._environment_rows(await self._stats(config, ctx), options)
        if widget_kind == "summary":
            return self._summary(await self._stats(config, ctx, str(options.get("environment") or "").strip()), options)

        environments, left_out = await self._chosen(config, options, ctx)
        several = len(environments) > 1 or left_out
        path = {"stacks": "/stacks", "containers": "/containers"}.get(widget_kind, "/containers/pending-updates")
        good, failed = await self._each(environments, lambda one: self._list(config, ctx, one, path))
        partial = left_out or bool(failed)
        if widget_kind == "stacks":
            return self._stack_rows(good, partial, several)
        if widget_kind == "containers":
            return self._container_rows(good, partial, several, show_stopped=options.get("show_stopped", True) is not False)
        return self._update_rows(good, partial, several)

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def _environment_rows(stats: list[dict[str, Any]], options: dict[str, Any]) -> WidgetData:
        rows = []
        down = 0
        for entry in stats:
            containers = entry.get("containers") or {}
            row: dict[str, Any] = {"title": str(entry.get("name") or entry.get("id"))}
            if not entry.get("online"):
                down += 1
                row.update(subtitle="Not reachable", status="bad")
            else:
                parts = ["Online"]
                metrics = entry.get("metrics") or {}
                if part_on(options, "usage") and metrics:
                    parts += [f"CPU {_percent(metrics.get('cpuPercent'))}", f"Memory {_percent(metrics.get('memoryPercent'))}"]
                unhealthy = int(containers.get("unhealthy") or 0)
                if unhealthy:
                    parts.append(f"{unhealthy} unhealthy")
                row.update(subtitle=" · ".join(parts), status="warn" if unhealthy else "ok",
                           value=f"{int(containers.get('running') or 0)} / {int(containers.get('total') or 0)}")
            rows.append(row)
        return WidgetData(
            status="bad" if down else "ok" if rows else "unknown",
            items=_sorted(rows),
            meta={"empty": "Dockhand manages no environment yet."},
            metrics={"environments_offline": float(down)},
        )

    @staticmethod
    def _stack_rows(found: list[tuple[dict[str, Any], Any]], partial: bool, several: bool) -> WidgetData:
        rows = []
        for environment, stacks in found:
            for stack in stacks if isinstance(stacks, list) else []:
                if not isinstance(stack, dict):
                    continue
                status = str(stack.get("status") or "")
                details = [one for one in stack.get("containerDetails") or [] if isinstance(one, dict)]
                parts = [STACK_WORD.get(status, status.capitalize() or "Unknown")]
                if details:
                    parts.append(f"{sum(one.get('state') == 'running' for one in details)}/{len(details)}")
                if several:
                    parts.append(str(environment.get("name") or environment["id"]))
                if stack.get("updatesAvailable"):
                    parts.append("Update available")
                rows.append({"title": str(stack.get("name") or "?"), "subtitle": " · ".join(parts), "status": _stack_colour(status)})
        partly = any(row["status"] == "warn" for row in rows)
        return WidgetData(
            status="warn" if partly or partial else "ok" if rows else "unknown",
            items=_sorted(rows),
            meta={"empty": "No compose stacks.", "notice": PARTIAL if partial else ""},
        )

    @staticmethod
    def _container_rows(found: list[tuple[dict[str, Any], Any]], partial: bool, several: bool,
                        *, show_stopped: bool = True) -> WidgetData:
        rows = []
        running = 0
        for environment, containers in found:
            for container in containers if isinstance(containers, list) else []:
                if not isinstance(container, dict):
                    continue
                state = str(container.get("state") or "")
                running += state == "running"
                if state != "running" and not show_stopped:
                    continue
                parts = [CONTAINER_WORD.get(state, state.capitalize() or "Unknown")]
                if _unhealthy(container):
                    parts.append("Unhealthy")
                parts.append(str(container.get("image") or ""))
                if several:
                    parts.append(str(environment.get("name") or environment["id"]))
                rows.append({"title": str(container.get("name") or str(container.get("id") or "?")[:12]),
                             "subtitle": " · ".join(part for part in parts if part), "status": _container_colour(container)})
        troubled = any(row["status"] == "bad" for row in rows)
        return WidgetData(
            status="bad" if troubled else "warn" if partial else "ok" if rows else "unknown",
            items=_sorted(rows),
            meta={"empty": "No containers.", "notice": PARTIAL if partial else ""},
            metrics={"containers_running": float(running)},
        )

    @staticmethod
    def _update_rows(found: list[tuple[dict[str, Any], Any]], partial: bool, several: bool) -> WidgetData:
        rows = []
        checking = False
        for environment, answer in found:
            checking = checking or bool(environment.get("updateCheckEnabled"))
            pending = answer.get("pendingUpdates") if isinstance(answer, dict) else None
            for update in pending if isinstance(pending, list) else []:
                if not isinstance(update, dict):
                    continue
                parts = [str(update.get("currentImage") or "")]
                if update.get("newerVersion"):
                    parts.append(f"{update['newerVersion']} available")
                if several:
                    parts.append(str(environment.get("name") or environment["id"]))
                rows.append({"title": str(update.get("containerName") or "?"),
                             "subtitle": " · ".join(part for part in parts if part), "status": "warn"})
        return WidgetData(
            status="warn" if rows or partial else "ok" if checking else "unknown",
            items=sorted(rows, key=lambda row: str(row["title"]).lower()),
            meta={"empty": "Everything is up to date, as Dockhand last checked." if checking
                  else "No update recorded. Dockhand's scheduled update check is off, so it records one only when somebody checks.",
                  "notice": PARTIAL if partial else ""},
            metrics={"updates_waiting": float(len(rows))},
        )

    @staticmethod
    def _summary(stats: list[dict[str, Any]], options: dict[str, Any]) -> WidgetData:
        online = [one for one in stats if one.get("online")]

        def total(what: str, key: str) -> int:
            return sum(int((one.get(what) or {}).get(key) or 0) for one in online)

        running = total("containers", "running")
        unhealthy = total("containers", "unhealthy")
        updates = total("containers", "pendingUpdates")
        missing = len(stats) - len(online)
        secondary = [
            {"label": "Unhealthy", "value": unhealthy, "part": "unhealthy"},
            {"label": "Stacks", "value": f"{total('stacks', 'running')} / {total('stacks', 'total')}", "part": "stacks"},
            {"label": "Environments", "value": f"{len(online)} / {len(stats)}", "part": "environments"},
            {"label": "Image updates", "value": updates, "part": "updates"},
            {"label": "Images", "value": total("images", "total"), "part": "images"},
            {"label": "Volumes", "value": total("volumes", "total"), "part": "volumes"},
            {"label": "Networks", "value": total("networks", "total"), "part": "networks"},
        ]
        return WidgetData(
            status="bad" if unhealthy or missing else "warn" if updates else "ok" if online else "unknown",
            primary={"label": "Containers running", "value": running, "unit": f"/ {total('containers', 'total')}"},
            secondary=secondary,
            metrics={"containers_running": float(running), "containers_unhealthy": float(unhealthy), "updates_waiting": float(updates)},
        )

    # -- demo ----------------------------------------------------------------

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        agent_down = fake.flicker("dockhand-agent", tick, 0.15)
        sick = fake.flicker("dockhand-sick", tick, 0.3)
        wanted = str(options.get("environment") or "")
        stats = [dict(one, online=not (agent_down and one["id"] == 2)) for one in DEMO_STATS]
        if widget_kind == "environments":
            return self._environment_rows(stats, options)
        chosen = [one for one in stats if not wanted or str(one["id"]) == wanted] or stats[:1]
        if widget_kind == "summary":
            return self._summary(chosen, options)
        several = len(chosen) > 1
        if widget_kind == "stacks":
            return self._stack_rows([(env, DEMO_STACKS[env["id"]]) for env in chosen], False, several)
        if widget_kind == "containers":
            return self._container_rows([(env, _demo_containers(env["id"], sick)) for env in chosen], False, several,
                                        show_stopped=options.get("show_stopped", True) is not False)
        return self._update_rows([(env, {"pendingUpdates": DEMO_UPDATES.get(env["id"], [])}) for env in chosen], False, several)


def _demo_stat(identifier: int, name: str, running: int, total: int, unhealthy: int, updates: int,
               stacks: tuple[int, int], images: int, volumes: int, networks: int, cpu: float, memory: float) -> dict[str, Any]:
    return {"id": identifier, "name": name, "online": True, "updateCheckEnabled": True,
            "containers": {"total": total, "running": running, "stopped": total - running, "unhealthy": unhealthy, "pendingUpdates": updates},
            "stacks": {"total": stacks[1], "running": stacks[0]}, "images": {"total": images}, "volumes": {"total": volumes},
            "networks": {"total": networks}, "metrics": {"cpuPercent": cpu, "memoryPercent": memory}}


DEMO_STATS = [
    _demo_stat(1, "homeserver", 5, 6, 0, 1, (2, 3), 16, 9, 7, 6.2, 41.0),
    _demo_stat(2, "vps", 2, 2, 0, 0, (1, 1), 5, 2, 4, 1.4, 22.5),
]

DEMO_STACKS: dict[int, list[dict[str, Any]]] = {
    1: [
        {"name": "immich", "status": "running", "updatesAvailable": True,
         "containerDetails": [{"state": "running"}] * 4},
        {"name": "paperless", "status": "running", "updatesAvailable": False,
         "containerDetails": [{"state": "running"}] * 2},
        {"name": "mealie", "status": "partial", "updatesAvailable": False,
         "containerDetails": [{"state": "running"}, {"state": "exited"}]},
    ],
    2: [{"name": "traefik", "status": "running", "updatesAvailable": False, "containerDetails": [{"state": "running"}]}],
}

DEMO_UPDATES: dict[int, list[dict[str, Any]]] = {
    1: [{"containerName": "immich-server", "currentImage": "ghcr.io/immich-app/immich-server:release", "newerVersion": None}],
}


def _demo_containers(env: int, sick: bool) -> list[dict[str, Any]]:
    def one(name: str, image: str, state: str = "running", status: str = "Up 3 days", health: str | None = None) -> dict[str, Any]:
        return {"name": name, "image": image, "state": state, "status": status, "health": health}

    if env == 2:
        return [one("traefik", "traefik:v3.5"), one("hawser", "ghcr.io/finsys/hawser:latest")]
    return [
        one("immich-server", "ghcr.io/immich-app/immich-server:release"),
        one("immich-postgres", "ghcr.io/immich-app/postgres:14"),
        one("paperless-webserver", "ghcr.io/paperless-ngx/paperless-ngx:2.18",
            status="Up 2 hours (unhealthy)" if sick else "Up 2 hours (healthy)", health="unhealthy" if sick else "healthy"),
        one("paperless-redis", "redis:7"),
        one("mealie", "ghcr.io/mealie-recipes/mealie:v3"),
        one("mealie-worker", "ghcr.io/mealie-recipes/mealie:v3", state="exited", status="Exited (1) 12 minutes ago"),
    ]


ADAPTER = DockhandAdapter()
