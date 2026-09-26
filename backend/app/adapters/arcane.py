"""Arcane: every Docker environment Arcane manages, its projects and containers, and the images with an update waiting.

Measured against Arcane 2.14.0 on 26.09.2026: the manager on a Docker engine
of its own and one agent as a second environment on another, so both held
only the test projects. Two compose projects that ran, one whose container
failed its healthcheck, one whose image no registry has, and an image tagged
older than its registry so that an update was waiting.

⚠️ Everything is under ``/api``. Without it the same address answers 200 with
the web interface, so a URL typed without the prefix would look like a
service that speaks HTML. The adapter adds the prefix and takes one that was
typed along.

⚠️ Lists stop at twenty entries unless asked otherwise, and ``limit=-1`` is
all of them. A card that asked without it would have lost the twenty-first
container quietly.

⚠️ An API key goes as ``X-API-Key``. A wrong one got 401 "Unauthorized:
invalid API key", twenty-five times in a row from one address, and the right
key was let in straight after: no lock like Komodo's.

⚠️ A scoped key is refused per permission, 403 "permission denied:
containers:list", and ``/environments`` lists only the environments the key
may see. The refusal names what is missing, so the card passes it on.

⚠️ An agent that stopped answering was still ``online`` in ``/environments``
for up to two minutes, until the next heartbeat. Every request for that
environment meanwhile got 502 with "Proxy request failed". The environment
card therefore asks each environment and believes the answer, not the flag.
A switched off environment answers 400 "Environment is disabled".

⚠️ A container failing its healthcheck stays ``running``. Only the status
text says "(unhealthy)", and the project it belongs to counts as running.

⚠️ Starting and redeploying a project answer 200 with a stream of JSON lines
(``application/x-json-stream``), and a failure is a line ``{"error": ...}``
inside that 200: a project whose image could not be pulled said nothing else.
Stopping a project and updating its services answer plain JSON, and a failed
update is a 400 with the reason.

⚠️ Updating a container answers 200 with ``success: true`` whatever happened.
Whether it was updated, skipped or failed is in ``items[].status``; a
container without anything newer came back ``skipped`` with "image digest
unchanged after pull".

⚠️ ``updateInfo`` is missing on a container Arcane has not checked yet, and
``hasUpdate`` false on one it has. The update card says which of the two it is.
It comes with ``containers:list`` alone.

⚠️ ``/image-updates/summary`` counts image records, not containers: after a
project was updated it still said one update was waiting, for the old image
nothing used any more, while every container said none. The overview counts
the containers, like the update card, so the two never disagree.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx

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
    part_on,
    path_segment,
)

#: Pulling images can take a while; the card waits this long for an action.
ACTION_SECONDS = 300.0

KEY_HINT = "Add it to the key in Arcane under Settings > API keys."

ENVIRONMENT = Field("environment", "Environment", type="choices", help="Empty for every environment.")

CONTAINER_WORD = {"running": "Running", "exited": "Exited", "created": "Created", "paused": "Paused",
                  "restarting": "Restarting", "removing": "Removing", "dead": "Dead"}
PROJECT_WORD = {"running": "Running", "partially running": "Partially running", "stopped": "Stopped"}
ORDER = {"bad": 0, "warn": 1, "unknown": 2, "ok": 3}

START = Action(id="start", label="Start", icon="play")
STOP = Action(id="stop", label="Stop", icon="square", confirm=True, danger=True)
RESTART = Action(id="restart", label="Restart", icon="rotate-cw", confirm=True)
UPDATE = Action(id="update", label="Update", icon="download", confirm=True)
PROJECT_UP = Action(id="up", label="Start", icon="play")
PROJECT_DOWN = Action(id="down", label="Stop", icon="square", confirm=True, danger=True)
PROJECT_REDEPLOY = Action(id="redeploy", label="Redeploy", icon="refresh-cw", confirm=True)
PROJECT_UPDATE = Action(id="update_project", label="Update", icon="download", confirm=True)

DONE = {
    "start": "Arcane has started the container.",
    "stop": "Arcane has stopped the container.",
    "restart": "Arcane has restarted the container.",
    "up": "Arcane has started the project.",
    "down": "Arcane has stopped the project.",
    "redeploy": "Arcane has redeployed the project.",
    "update_project": "Arcane has pulled the new images and recreated the project.",
}


def _said(answer: Any) -> str:
    """What Arcane wrote about a refusal, wherever in the answer it put it."""
    if not isinstance(answer, dict):
        return ""
    inner = answer.get("data") if isinstance(answer.get("data"), dict) else {}
    for source in (answer, inner):
        for key in ("detail", "error", "message"):
            if source.get(key):
                return " ".join(str(source[key]).split())[:240]
    return ""


def _stream_error(text: str) -> str:
    """The error line of a streamed answer, or nothing when it went through."""
    for line in text.splitlines():
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict) and entry.get("error"):
            return " ".join(str(entry["error"]).split())[:240]
    return ""


def _name(container: dict[str, Any]) -> str:
    names = container.get("names")
    if isinstance(names, list) and names:
        return str(names[0]).lstrip("/")
    return str(container.get("id") or "?")[:12]


def _unhealthy(container: dict[str, Any]) -> bool:
    # ⚠️ The state stays "running"; only the status text knows.
    return "(unhealthy)" in str(container.get("status") or "")


def _container_colour(container: dict[str, Any]) -> str:
    state = str(container.get("state") or "")
    if state == "running":
        return "bad" if _unhealthy(container) else "ok"
    if state in ("paused", "restarting", "created"):
        return "warn"
    return "bad"


def _project_colour(status: str) -> str:
    return {"running": "ok", "partially running": "warn", "stopped": "unknown"}.get(status, "unknown")


def _with(action: Action, **params: str) -> Action:
    return action.model_copy(update={"params": params})


def _sorted(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda row: (ORDER.get(row["status"], 9), str(row["title"]).lower()))


class ArcaneAdapter(Adapter):
    kind = "arcane"
    label = "Arcane"
    category = "hosts"
    description = "Every Docker environment Arcane manages: projects, containers and image updates, with start, stop, redeploy and update."
    icon = "arcane"
    #: Confirmed against a live instance on 2026-09-26.
    beta = False
    docs_url = "https://getarcane.app"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://arcane:3552"),
        Field("api_key", "API key", type="password", secret=True, required=True,
              help="A key from Settings > API keys. The cards read with environments:list, containers:list and projects:list, "
                   "the overview also with images:list, volumes:list and networks:list. The buttons need containers:start, "
                   "containers:stop, containers:restart, projects:deploy, projects:down, projects:update and image-updates:check."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(kind="summary", label="Arcane overview",
                   description="Running containers of every environment, with the unhealthy ones, projects, environments, image updates, images, volumes and networks.",
                   renderer="value", default_size=(3, 2), refresh_seconds=60,
                   metrics=("containers_running", "containers_unhealthy", "updates_waiting"),
                   parts=(("unhealthy", "Unhealthy"), ("projects", "Projects"), ("environments", "Environments"),
                          ("updates", "Image updates"), ("images", "Images"), ("volumes", "Volumes"), ("networks", "Networks")),
                   options=(ENVIRONMENT,)),
        WidgetType(kind="environments", label="Environments",
                   description="Every environment with whether it answers and how many of its containers run.",
                   renderer="list", default_size=(3, 3), refresh_seconds=60, metrics=("environments_offline",)),
        WidgetType(kind="projects", label="Projects",
                   description="Compose projects with their state, troubled ones first, with start, stop, redeploy and update.",
                   renderer="list", default_size=(3, 3), refresh_seconds=60,
                   options=(ENVIRONMENT,)),
        WidgetType(kind="containers", label="Containers",
                   description="Containers with their state and health, troubled ones first, with start, stop and restart.",
                   renderer="list", default_size=(4, 4), refresh_seconds=30, metrics=("containers_running",),
                   options=(ENVIRONMENT, Field("show_stopped", "Show stopped containers", type="bool", default=True))),
        WidgetType(kind="updates", label="Image updates",
                   description="Containers whose image has a newer version, as Arcane last checked, with a button to pull it and recreate the container.",
                   renderer="list", default_size=(3, 3), refresh_seconds=300, metrics=("updates_waiting",),
                   options=(ENVIRONMENT,)),
    )

    # -- talking to Arcane ---------------------------------------------------

    @staticmethod
    def _api(config: dict[str, Any]) -> str:
        root = base_url(config)
        # ⚠️ Taken along if typed; without it the web interface answers.
        if root.lower().endswith("/api"):
            root = root[:-4]
        return f"{root}/api"

    async def _send(self, config: dict[str, Any], ctx: Context, method: str, path: str, *, params: dict[str, Any] | None = None,
                    json_body: Any = None, timeout: float = 15.0, cache: float = 0) -> httpx.Response:
        response = await ctx.request(method, f"{self._api(config)}{path}", params=params, json_body=json_body,
                                     headers={"X-API-Key": str(config.get("api_key") or "").strip()},
                                     verify=not config.get("insecure"), timeout=timeout, cache_seconds=cache, auth_errors=False)
        if response.status_code < 400:
            return response
        try:
            answer: Any = response.json()
        except ValueError:
            answer = None
        said = _said(answer)
        if response.status_code == 401:
            raise AuthFailed("Arcane rejected the API key.")
        if response.status_code == 403:
            if said.startswith("permission denied:"):
                permission = said.removeprefix("permission denied:").strip()
                raise AdapterError(f"The API key lacks the permission {permission}.", code="forbidden", hint=KEY_HINT)
            raise AdapterError("The API key may not reach this environment.", code="forbidden", hint=KEY_HINT)
        if response.status_code == 502:
            raise AdapterError("Arcane cannot reach this environment.", code="environment_unreachable",
                               hint="Its agent may be down. Arcane marks it offline only at its next heartbeat, up to two minutes later.")
        if said == "Environment is disabled":
            raise AdapterError("This environment is switched off in Arcane.", code="environment_disabled")
        if answer is None:
            raise AdapterError(f"Arcane answered with HTTP {response.status_code}.", code="http_error",
                               hint="Check the URL; it is the address of Arcane itself, port 3552 by default.")
        raise AdapterError(f"Arcane refused: {said}" if said else f"Arcane answered with HTTP {response.status_code}.",
                           code="http_error")

    async def _data(self, config: dict[str, Any], ctx: Context, method: str, path: str, **kwargs: Any) -> Any:
        response = await self._send(config, ctx, method, path, **kwargs)
        try:
            answer = response.json()
        except ValueError as error:
            raise AdapterError("This address answers with something other than Arcane's API.", code="not_arcane",
                               hint="Enter the address of Arcane itself, port 3552 by default.") from error
        if not isinstance(answer, dict) or "data" not in answer:
            raise AdapterError("This address answers, but not the way Arcane does.", code="not_arcane")
        return answer["data"]

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, *, params: dict[str, Any] | None = None, cache: float = 5) -> Any:
        return await self._data(config, ctx, "GET", path, params=params, cache=cache)

    async def _environments(self, config: dict[str, Any], ctx: Context, cache: float = 30) -> list[dict[str, Any]]:
        found = await self._get(config, ctx, "/environments", params={"limit": -1}, cache=cache)
        if not isinstance(found, list):
            raise AdapterError("This address answers, but not the way Arcane does.", code="not_arcane")
        return [one for one in found if isinstance(one, dict) and str(one.get("id") or "") != ""]

    async def _chosen(self, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> list[dict[str, Any]]:
        """The environments a card covers: the one picked, or every one that is switched on."""
        known = await self._environments(config, ctx)
        wanted = str(options.get("environment") or "").strip()
        if not wanted:
            return [one for one in known if one.get("enabled", True)]
        picked = [one for one in known if str(one.get("id")) == wanted]
        if not picked:
            raise AdapterError("Arcane has no such environment, or this API key may not see it.", code="no_environment",
                               hint="Pick another environment in the card's settings.")
        return picked

    async def _each(self, environments: list[dict[str, Any]], ask: Any) -> tuple[list[tuple[dict[str, Any], Any]], list[AdapterError]]:
        """Ask every environment at once; one that does not answer must not take the others with it."""
        answers = await asyncio.gather(*(ask(one) for one in environments), return_exceptions=True)
        good: list[tuple[dict[str, Any], Any]] = []
        failed: list[AdapterError] = []
        for environment, answer in zip(environments, answers, strict=True):
            if isinstance(answer, AuthFailed):
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

    async def _list(self, config: dict[str, Any], ctx: Context, environment: dict[str, Any], what: str) -> list[dict[str, Any]]:
        # ⚠️ Twenty per page otherwise.
        env = path_segment(environment.get("id"), "The environment")
        found = await self._get(config, ctx, f"/environments/{env}/{what}", params={"limit": -1})
        if not isinstance(found, list):
            raise AdapterError("This address answers, but not the way Arcane does.", code="not_arcane")
        return [one for one in found if isinstance(one, dict)]

    async def _count(self, config: dict[str, Any], ctx: Context, environment: dict[str, Any], what: str) -> dict[str, Any]:
        env = path_segment(environment.get("id"), "The environment")
        found = await self._get(config, ctx, f"/environments/{env}/{what}")
        return found if isinstance(found, dict) else {}

    # -- the hooks -----------------------------------------------------------

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        environments = await self._environments(config, ctx, cache=0)
        # The one answer without the envelope around it, and without a key.
        try:
            version = (await self._send(config, ctx, "GET", "/app-version")).json()
        except (AdapterError, ValueError):
            version = {}
        number = str(version.get("displayVersion") or version.get("currentVersion") or "") if isinstance(version, dict) else ""
        return f"Arcane {number or '?'} answers; this key sees {len(environments)} environment(s)."

    async def choices(self, field: str, config: dict[str, Any], ctx: Context) -> list[tuple[str, str]]:
        if field != "environment":
            return await super().choices(field, config, ctx)
        return [(str(one["id"]), str(one.get("name") or one["id"])) for one in await self._environments(config, ctx)]

    def demo_choices(self, field: str) -> list[tuple[str, str]]:
        if field != "environment":
            return []
        return [(one["id"], one["name"]) for one in DEMO_ENVIRONMENTS]

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "environments":
            environments = await self._environments(config, ctx)

            async def counts(environment: dict[str, Any]) -> Any:
                if not environment.get("enabled", True):
                    return None
                try:
                    return await self._count(config, ctx, environment, "containers/counts")
                except AuthFailed:
                    raise
                except AdapterError as error:
                    return error

            answers = await asyncio.gather(*(counts(one) for one in environments))
            return self._environment_rows(list(zip(environments, answers, strict=True)))

        environments = await self._chosen(config, options, ctx)
        several = len(environments) > 1
        if widget_kind == "projects":
            good, failed = await self._each(environments, lambda one: self._list(config, ctx, one, "projects"))
            return self._project_rows(good, bool(failed), several)
        if widget_kind in ("containers", "updates"):
            good, failed = await self._each(environments, lambda one: self._list(config, ctx, one, "containers"))
            if widget_kind == "updates":
                return self._update_rows(good, bool(failed), several)
            return self._container_rows(good, bool(failed), several, show_stopped=options.get("show_stopped", True) is not False)

        async def overview(environment: dict[str, Any]) -> dict[str, Any]:
            asked = {"containers": self._list(config, ctx, environment, "containers"),
                     "projects": self._count(config, ctx, environment, "projects/counts")}
            # Only what is on the card is asked for, so a key without images:list still fills the rest.
            for part in ("images", "volumes", "networks"):
                if part_on(options, part):
                    asked[part] = self._count(config, ctx, environment, f"{part}/counts")
            values = await asyncio.gather(*asked.values())
            return dict(zip(asked, values, strict=True))

        good, failed = await self._each(environments, overview)
        return self._summary(good, len(failed), options)

    async def action(self, widget_kind: str, action_id: str, params: dict[str, Any],
                     config: dict[str, Any], options: dict[str, Any], ctx: Context) -> str:
        env = path_segment(params.get("environment"), "The environment")
        if action_id in ("start", "stop", "restart", "update"):
            container = path_segment(params.get("id"), "The container")
            path = f"/environments/{env}/containers/{container}/{action_id}"
            if action_id != "update":
                await self._data(config, ctx, "POST", path, timeout=60)
                ctx.forget_answers()
                return DONE[action_id]
            result = await self._data(config, ctx, "POST", path, timeout=ACTION_SECONDS)
            ctx.forget_answers()
            # ⚠️ success is true either way; the item says what happened.
            items = result.get("items") if isinstance(result, dict) else None
            item = items[0] if isinstance(items, list) and items and isinstance(items[0], dict) else {}
            status = str(item.get("status") or "")
            if status == "updated" or status == "restarted":
                return "Arcane has pulled the new image and recreated the container."
            if status == "skipped":
                return "Arcane found nothing newer to update to."
            reason = " ".join(str(item.get("error") or "").split())[:240]
            raise AdapterError(f"Arcane could not update the container: {reason}" if reason else "Arcane could not update the container.",
                               code="action_failed")
        if action_id not in ("up", "down", "redeploy", "update_project"):
            raise AdapterError("Arcane has no such action.", code="no_such_action")
        project = path_segment(params.get("project"), "The project")
        base = f"/environments/{env}/projects/{project}"
        if action_id in ("up", "redeploy"):
            # ⚠️ A stream, and a failure is a line in a 200.
            response = await self._send(config, ctx, "POST", f"{base}/{action_id}", timeout=ACTION_SECONDS)
            ctx.forget_answers()
            reason = _stream_error(response.text)
            if reason:
                what = "start" if action_id == "up" else "redeploy"
                raise AdapterError(f"Arcane could not {what} the project: {reason}", code="action_failed")
            return DONE[action_id]
        if action_id == "down":
            await self._data(config, ctx, "POST", f"{base}/down", timeout=120)
        else:
            await self._data(config, ctx, "POST", f"{base}/update-services", json_body={}, timeout=ACTION_SECONDS)
        ctx.forget_answers()
        return DONE[action_id]

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def _environment_rows(entries: list[tuple[dict[str, Any], Any]]) -> WidgetData:
        rows = []
        down = 0
        for environment, counts in entries:
            row: dict[str, Any] = {"title": str(environment.get("name") or environment.get("id"))}
            if not environment.get("enabled", True):
                row.update(subtitle="Switched off", status="unknown")
            elif isinstance(counts, AdapterError):
                forbidden = counts.code == "forbidden"
                row.update(subtitle="No access" if forbidden else "Not reachable", status="unknown" if forbidden else "bad")
                down += 0 if forbidden else 1
            else:
                # ⚠️ The answer, not the flag: "online" outlived a stopped agent by two minutes.
                running = int(counts.get("runningContainers") or 0)
                row.update(subtitle="Online", status="ok", value=f"{running} / {int(counts.get('totalContainers') or 0)}")
            rows.append(row)
        return WidgetData(
            status="bad" if down else "ok" if rows else "unknown",
            items=_sorted(rows),
            meta={"empty": "Arcane shows this API key no environment."},
            metrics={"environments_offline": float(down)},
        )

    @staticmethod
    def _project_rows(found: list[tuple[dict[str, Any], list[dict[str, Any]]]], partial: bool, several: bool) -> WidgetData:
        rows = []
        for environment, projects in found:
            env = str(environment.get("id"))
            for project in projects:
                status = str(project.get("status") or "")
                identifier = str(project.get("id") or "")
                update = bool((project.get("updateInfo") or {}).get("hasUpdate"))
                parts = [PROJECT_WORD.get(status, status.capitalize() or "Unknown"),
                         f"{int(project.get('runningCount') or 0)}/{int(project.get('serviceCount') or 0)}"]
                if several:
                    parts.append(str(environment.get("name") or env))
                if update:
                    parts.append("Update available")
                actions: list[Action] = []
                if identifier:
                    if status != "running":
                        actions.append(_with(PROJECT_UP, environment=env, project=identifier))
                    if status in ("running", "partially running"):
                        actions += [_with(PROJECT_DOWN, environment=env, project=identifier),
                                    _with(PROJECT_REDEPLOY, environment=env, project=identifier)]
                    if update:
                        actions.append(_with(PROJECT_UPDATE, environment=env, project=identifier))
                row: dict[str, Any] = {"title": str(project.get("name") or "?"), "subtitle": " · ".join(parts), "status": _project_colour(status)}
                if actions:
                    row["actions"] = actions
                rows.append(row)
        partly = sum(1 for row in rows if row["status"] == "warn")
        return WidgetData(
            status="warn" if partly or partial else "ok" if rows else "unknown",
            items=_sorted(rows),
            meta={"empty": "No projects, or none this API key may see.",
                  "notice": "Some environments did not answer; their rows are missing." if partial else ""},
        )

    @staticmethod
    def _container_rows(found: list[tuple[dict[str, Any], list[dict[str, Any]]]], partial: bool, several: bool,
                        *, show_stopped: bool = True) -> WidgetData:
        rows = []
        running = 0
        for environment, containers in found:
            env = str(environment.get("id"))
            for container in containers:
                state = str(container.get("state") or "")
                running += state == "running"
                if state != "running" and not show_stopped:
                    continue
                parts = [CONTAINER_WORD.get(state, state.capitalize() or "Unknown")]
                if _unhealthy(container):
                    parts.append("Unhealthy")
                parts.append(str(container.get("image") or ""))
                if several:
                    parts.append(str(environment.get("name") or env))
                identifier = str(container.get("id") or "")
                actions: list[Action] = []
                if identifier:
                    if state in ("running", "paused", "restarting"):
                        actions += [_with(STOP, environment=env, id=identifier), _with(RESTART, environment=env, id=identifier)]
                    else:
                        actions.append(_with(START, environment=env, id=identifier))
                rows.append({"title": _name(container), "subtitle": " · ".join(part for part in parts if part),
                             "status": _container_colour(container), "actions": actions})
        troubled = any(row["status"] == "bad" for row in rows)
        return WidgetData(
            status="bad" if troubled else "warn" if partial else "ok" if rows else "unknown",
            items=_sorted(rows),
            meta={"empty": "No containers, or none this API key may see.",
                  "notice": "Some environments did not answer; their rows are missing." if partial else ""},
            metrics={"containers_running": float(running)},
        )

    @staticmethod
    def _update_rows(found: list[tuple[dict[str, Any], list[dict[str, Any]]]], partial: bool, several: bool) -> WidgetData:
        rows = []
        checked = failed = 0
        for environment, containers in found:
            env = str(environment.get("id"))
            for container in containers:
                info = container.get("updateInfo")
                if not isinstance(info, dict) or not info.get("checkTime"):
                    continue
                checked += 1
                if info.get("error"):
                    failed += 1
                if not info.get("hasUpdate"):
                    continue
                parts = [str(container.get("image") or "")]
                if several:
                    parts.append(str(environment.get("name") or env))
                row: dict[str, Any] = {"title": _name(container), "subtitle": " · ".join(part for part in parts if part), "status": "warn"}
                if container.get("id"):
                    row["actions"] = [_with(UPDATE, environment=env, id=str(container["id"]))]
                rows.append(row)
        notice = ""
        if partial:
            notice = "Some environments did not answer; their rows are missing."
        elif failed:
            notice = "Arcane could not check some images."
        return WidgetData(
            status="warn" if rows or partial else "ok" if checked else "unknown",
            items=sorted(rows, key=lambda row: str(row["title"]).lower()),
            meta={"empty": "Everything is up to date." if checked else "Arcane has not checked these images for updates yet.",
                  "notice": notice},
            metrics={"updates_waiting": float(len(rows))},
        )

    @staticmethod
    def _summary(found: list[tuple[dict[str, Any], dict[str, Any]]], missing: int, options: dict[str, Any]) -> WidgetData:
        def total(what: str, key: str) -> int:
            return sum(int((answer.get(what) or {}).get(key) or 0) for _environment, answer in found)

        containers = [one for _environment, answer in found for one in answer["containers"]]
        running = sum(1 for one in containers if one.get("state") == "running")
        unhealthy = sum(1 for one in containers if _unhealthy(one))
        # ⚠️ Containers, not Arcane's summary of image records; see the top of the file.
        updates = sum(1 for one in containers if isinstance(one.get("updateInfo"), dict) and one["updateInfo"].get("hasUpdate"))
        secondary = [
            {"label": "Unhealthy", "value": unhealthy, "part": "unhealthy"},
            {"label": "Projects", "value": f"{total('projects', 'runningProjects')} / {total('projects', 'totalProjects')}", "part": "projects"},
            # Those that answered, of those switched on.
            {"label": "Environments", "value": f"{len(found)} / {len(found) + missing}", "part": "environments"},
            {"label": "Image updates", "value": updates, "part": "updates"},
        ]
        for part, label, key in (("images", "Images", "totalImages"), ("volumes", "Volumes", "total"), ("networks", "Networks", "total")):
            if part_on(options, part):
                secondary.append({"label": label, "value": total(part, key), "part": part})
        troubled = unhealthy or missing
        return WidgetData(
            status="bad" if troubled else "warn" if updates else "ok" if found else "unknown",
            primary={"label": "Containers running", "value": running, "unit": f"/ {len(containers)}"},
            secondary=secondary,
            metrics={"containers_running": float(running), "containers_unhealthy": float(unhealthy), "updates_waiting": float(updates)},
        )

    # -- demo ----------------------------------------------------------------

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        agent_down = fake.flicker("arcane-agent", tick, 0.15)
        sick = fake.flicker("arcane-sick", tick, 0.3)
        wanted = str(options.get("environment") or "")
        environments = [one for one in DEMO_ENVIRONMENTS if not wanted or one["id"] == wanted] or DEMO_ENVIRONMENTS[:1]
        containers = {env["id"]: _demo_containers(env["id"], sick) for env in environments}
        several = len(environments) > 1
        if widget_kind == "environments":
            entries: list[tuple[dict[str, Any], Any]] = []
            for env in DEMO_ENVIRONMENTS:
                listed = _demo_containers(env["id"], sick)
                if agent_down and env["id"] == "vps":
                    entries.append((env, AdapterError("Arcane cannot reach this environment.", code="environment_unreachable")))
                else:
                    entries.append((env, {"runningContainers": sum(one["state"] == "running" for one in listed), "totalContainers": len(listed)}))
            return self._environment_rows(entries)
        if widget_kind == "projects":
            return self._project_rows([(env, DEMO_PROJECTS[env["id"]]) for env in environments], False, several)
        if widget_kind == "containers":
            return self._container_rows([(env, containers[env["id"]]) for env in environments], False, several,
                                        show_stopped=options.get("show_stopped", True) is not False)
        if widget_kind == "updates":
            return self._update_rows([(env, containers[env["id"]]) for env in environments], False, several)
        found = []
        for env in environments:
            projects = DEMO_PROJECTS[env["id"]]
            found.append((env, {
                "containers": containers[env["id"]],
                "projects": {"runningProjects": sum(one["status"] == "running" for one in projects), "totalProjects": len(projects)},
                "images": {"totalImages": 14 if env["id"] == "0" else 6},
                "volumes": {"total": 9 if env["id"] == "0" else 3},
                "networks": {"total": 7 if env["id"] == "0" else 4},
            }))
        return self._summary(found, 0, options)


DEMO_ENVIRONMENTS = [
    {"id": "0", "name": "Local Docker", "status": "online", "enabled": True},
    {"id": "vps", "name": "vps", "status": "online", "enabled": True},
]

_CHECKED = "2026-09-26T09:00:00Z"

DEMO_PROJECTS: dict[str, list[dict[str, Any]]] = {
    "0": [
        {"id": "p-immich", "name": "immich", "status": "running", "runningCount": 4, "serviceCount": 4, "updateInfo": {"hasUpdate": True}},
        {"id": "p-paperless", "name": "paperless", "status": "running", "runningCount": 3, "serviceCount": 3, "updateInfo": {"hasUpdate": False}},
        {"id": "p-mealie", "name": "mealie", "status": "partially running", "runningCount": 1, "serviceCount": 2, "updateInfo": {"hasUpdate": False}},
        {"id": "p-lab", "name": "lab", "status": "stopped", "runningCount": 0, "serviceCount": 1, "updateInfo": {"hasUpdate": False}},
    ],
    "vps": [
        {"id": "p-traefik", "name": "traefik", "status": "running", "runningCount": 1, "serviceCount": 1, "updateInfo": {"hasUpdate": False}},
        {"id": "p-uptime", "name": "uptime-kuma", "status": "running", "runningCount": 1, "serviceCount": 1, "updateInfo": {"hasUpdate": False}},
    ],
}


def _demo_containers(env: str, sick: bool) -> list[dict[str, Any]]:
    def one(identifier: str, name: str, image: str, state: str = "running", status: str = "Up 3 days", update: bool = False) -> dict[str, Any]:
        return {"id": f"{identifier:0>12}", "names": [name], "image": image, "state": state, "status": status,
                "updateInfo": {"checkTime": _CHECKED, "hasUpdate": update, "error": ""}}

    if env == "vps":
        return [one("a1", "traefik", "traefik:v3.5"), one("a2", "uptime-kuma", "louislam/uptime-kuma:2")]
    return [
        one("b1", "immich-server", "ghcr.io/immich-app/immich-server:release", update=True),
        one("b2", "immich-postgres", "ghcr.io/immich-app/postgres:14"),
        one("b3", "paperless-webserver", "ghcr.io/paperless-ngx/paperless-ngx:2.18",
            status="Up 2 hours (unhealthy)" if sick else "Up 2 hours (healthy)"),
        one("b4", "mealie", "ghcr.io/mealie-recipes/mealie:v3"),
        one("b5", "mealie-worker", "ghcr.io/mealie-recipes/mealie:v3", state="exited", status="Exited (1) 12 minutes ago"),
    ]


ADAPTER = ArcaneAdapter()
