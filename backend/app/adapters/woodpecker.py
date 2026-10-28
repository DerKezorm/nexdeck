"""Woodpecker CI: the last pipeline of each repository, running and queued pipelines, and the agents.

Measured on 27.10.2026 against woodpeckerci/woodpecker-server v3 (3.19.0),
but only what needs no sign-in: Woodpecker signs in through a forge (Gitea,
GitHub, ...) and a server without one has no user to make a token for, so the
rest is built from the documentation and not run.

- ``GET /api/version`` answers without a token: ``{"source": ..., "version": "3.19.0"}``.
  ``/healthz`` answers 204.
- Every other address answers **401** with the plain text ``User not
  authorized`` (also for a token that is nonsense), no JSON.

From the documentation, not measured:

- ``Authorization: Bearer <personal access token>`` (the user's page in the
  web interface). ``GET /api/user/repos`` lists the repositories the user may
  see, each with ``id``, ``full_name`` and ``active``, and in v3 a
  ``last_pipeline``; where it is missing, ``GET /api/repos/<id>/pipelines``
  with ``perPage=1`` gives the newest.
- A pipeline has ``number``, ``status`` (``success``, ``failure``, ``error``,
  ``killed``, ``running``, ``pending``, ``blocked``, ``declined``, ``skipped``),
  ``event``, ``branch``, ``message``, and ``created``, ``started`` and
  ``finished`` in seconds since the epoch.
- ``GET /api/queue/info`` and ``GET /api/agents`` are for administrators: the
  queue has ``stats`` with ``pending_count`` and ``running_count``, an agent
  ``last_contact``. A user who is none gets 403, and the overview then leaves
  those figures out.
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

#: A pipeline's state, as a colour and, where it is not plain success, a word.
STATUS = {
    "success": ("ok", ""), "failure": ("bad", "Failed"), "error": ("bad", "Error"), "killed": ("unknown", "Cancelled"),
    "running": ("warn", "Running"), "started": ("warn", "Running"), "pending": ("unknown", "Waiting"), "blocked": ("warn", "Needs approval"),
    "declined": ("unknown", "Declined"), "skipped": ("unknown", "Skipped"),
}
#: Repositories whose newest pipeline is asked for one by one, where the list does not carry it.
ASKED = 20
#: An agent that has not been heard from for this long counts as gone.
SILENT = 300


class WoodpeckerAdapter(Adapter):
    kind = "woodpecker"
    label = "Woodpecker CI"
    category = "hosts"
    description = "The last pipeline of each repository in Woodpecker, pipelines running and waiting, and the agents."
    icon = "woodpecker-ci"
    docs_url = "https://woodpecker-ci.org/api"
    keywords = ("ci", "pipeline", "forgejo", "gitea")
    #: Built from the documentation. The version and the refusal were measured, a signed-in server was not.
    beta = True
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="https://ci.example.com"),
        Field("token", "Personal access token", type="password", secret=True, required=True,
              help="From the user's page in the web interface. An administrator's token also shows the queue and the agents."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(
            kind="overview",
            label="Woodpecker overview",
            description="Repositories whose last pipeline failed, pipelines running and waiting, and agents that are there.",
            renderer="value",
            default_size=(2, 2),
            min_size=(1, 1),
            refresh_seconds=60,
            metrics=("failing", "running", "pending"),
        ),
        WidgetType(
            kind="pipelines",
            label="Pipelines",
            description="The latest pipeline of every repository, failing ones first, with the branch, the event and the commit message.",
            renderer="list",
            default_size=(4, 3),
            min_size=(3, 2),
            refresh_seconds=120,
            metrics=("failing",),
            options=(Field("limit", "Entries", type="number", default=10), Field("only_failing", "Only the failing ones", type="bool", default=False)),
        ),
    )

    # -- asking Woodpecker ---------------------------------------------------------------

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, params: dict[str, Any] | None = None, cache: float = 20,
                   optional: bool = False) -> Any:
        """The JSON of an address; with ``optional`` a 403 or 404 is None, for what only an administrator may see."""
        response = await ctx.request(
            "GET", f"{base_url(config)}/api{path}", params=params, headers={"Authorization": f"Bearer {str(config.get('token') or '').strip()}"},
            verify=not config.get("insecure"), cache_seconds=cache, timeout=25, auth_errors=False)
        if response.status_code == 401:
            failure = AuthFailed("Woodpecker rejected the token.")
            failure.hint = "Copy the personal access token from the user's page in the web interface; it belongs to the user that made it."
            raise failure
        if optional and response.status_code in (403, 404):
            return None
        if response.status_code == 403:
            raise AuthFailed("This user may not read that.")
        if response.status_code >= 400:
            raise AdapterError(f"Woodpecker answered with HTTP {response.status_code}.", code="http_error",
                               hint="The URL is the address of Woodpecker's web interface.")
        try:
            return response.json()
        except ValueError as error:
            raise AdapterError("Woodpecker did not answer with JSON.", code="not_json", hint="The URL probably points at something else than Woodpecker.") from error

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        version = await self._get(config, ctx, "/version", cache=0)
        user = await self._get(config, ctx, "/user", cache=0)
        if not isinstance(version, dict) or not isinstance(user, dict):
            raise AdapterError("This address answers, but not the way Woodpecker does.", code="not_woodpecker")
        number = str(version.get("version") or "").strip()
        who = user.get("login") or "?"
        return f"Woodpecker {number} accepts the token of {who}." if number else f"Woodpecker accepts the token of {who}."

    # -- the cards ----------------------------------------------------------------------------

    async def _latest(self, config: dict[str, Any], ctx: Context) -> list[tuple[dict[str, Any], dict[str, Any] | None]]:
        repos = await self._get(config, ctx, "/user/repos")
        found: list[tuple[dict[str, Any], dict[str, Any] | None]] = []
        asked = 0
        for repo in repos if isinstance(repos, list) else []:
            if not isinstance(repo, dict) or repo.get("active") is False:
                continue
            pipeline = repo.get("last_pipeline") if isinstance(repo.get("last_pipeline"), dict) else None
            if pipeline is None and repo.get("id") is not None and asked < ASKED:
                asked += 1
                listed = await self._get(config, ctx, f"/repos/{int(repo['id'])}/pipelines", {"perPage": 1})
                pipeline = listed[0] if isinstance(listed, list) and listed and isinstance(listed[0], dict) else None
            found.append((repo, pipeline))
        return found

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        link = base_url(config)
        latest = await self._latest(config, ctx)
        if widget_kind == "pipelines":
            return self.pipelines_card(latest, options, link)
        queue = await self._get(config, ctx, "/queue/info", optional=True)
        agents = await self._get(config, ctx, "/agents", optional=True)
        return self.overview_card(latest, queue, agents, link)

    @staticmethod
    def _state(pipeline: dict[str, Any] | None) -> tuple[str, str]:
        if not pipeline:
            return "unknown", "No pipeline yet"
        return STATUS.get(str(pipeline.get("status") or ""), ("unknown", str(pipeline.get("status") or "").capitalize()))

    @classmethod
    def overview_card(cls, latest: list[tuple[dict[str, Any], dict[str, Any] | None]], queue: Any, agents: Any, link: str | None = None,
                      now: float | None = None) -> WidgetData:
        states = [cls._state(pipeline)[0] for _repo, pipeline in latest]
        failing = states.count("bad")
        stats = (queue or {}).get("stats") if isinstance(queue, dict) else None
        stats = stats if isinstance(stats, dict) else {}
        running = int(stats["running_count"]) if "running_count" in stats else sum(1 for _r, p in latest if p and p.get("status") in ("running", "started"))
        waiting = int(stats.get("pending_count") or 0)
        secondary = [{"label": "Repositories", "value": len(latest)}, {"label": "Running", "value": running}]
        if queue is not None:
            secondary.append({"label": "Waiting", "value": waiting})
        silent = 0
        if isinstance(agents, list):
            moment = now if now is not None else time.time()
            silent = sum(1 for one in agents if isinstance(one, dict) and moment - float(one.get("last_contact") or 0) > SILENT)
            secondary.append({"label": "Agents", "value": f"{len(agents) - silent} of {len(agents)}"})
        return WidgetData(
            status="bad" if failing else ("warn" if silent or (isinstance(agents, list) and not agents) else "ok"),
            primary={"label": "Failing", "value": failing},
            secondary=secondary,
            metrics={"failing": float(failing), "running": float(running), "pending": float(waiting)},
            link=link,
        )

    @classmethod
    def pipelines_card(cls, latest: list[tuple[dict[str, Any], dict[str, Any] | None]], options: dict[str, Any], link: str | None = None) -> WidgetData:
        rows = []
        for repo, pipeline in latest:
            status, word = cls._state(pipeline)
            if options.get("only_failing") and status != "bad":
                continue
            pipeline = pipeline or {}
            message = " ".join(str(pipeline.get("message") or "").split("\n")[0].split())[:80]
            stamp = pipeline.get("finished") or pipeline.get("started") or pipeline.get("created") or 0
            number = pipeline.get("number")
            row: dict[str, Any] = {
                "title": str(repo.get("full_name") or repo.get("name") or "?"),
                "subtitle": " · ".join(part for part in (word, str(pipeline.get("branch") or ""), str(pipeline.get("event") or "").replace("_", " "), message) if part),
                "status": status,
                "value": ago(stamp) if stamp else "",
            }
            if number is not None and repo.get("id") is not None:
                row["url"] = f"{link or ''}/repos/{int(repo['id'])}/pipeline/{int(number)}"
            rows.append((status != "bad", -float(stamp), row))
        rows.sort(key=lambda entry: entry[:2])
        failing = sum(1 for entry in rows if not entry[0])
        limit = max(1, min(100, int(options.get("limit") or 10)))
        return WidgetData(
            status="bad" if failing else "ok",
            items=[entry[2] for entry in rows[:limit]],
            secondary=[{"label": "Failing", "value": failing}, {"label": "Repositories", "value": len(rows)}],
            metrics={"failing": float(failing)},
            link=link,
            meta={"empty": "No pipeline fails." if options.get("only_failing") else "No repository is enabled."},
        )

    # -- demo ------------------------------------------------------------------------------------

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        now = time.time() - tick % 60
        broke = (tick // 300) % 3 == 0
        latest = [
            ({"id": 1, "full_name": "example/api"}, {"number": 212, "status": "failure" if broke else "success", "event": "push", "branch": "main", "message": "Cache the session lookups", "finished": now - 1500}),
            ({"id": 2, "full_name": "example/web"}, {"number": 97, "status": "running", "event": "pull_request", "branch": "feature/menu", "message": "Move the settings page", "started": now - 90}),
            ({"id": 3, "full_name": "example/infra"}, {"number": 31, "status": "success", "event": "cron", "branch": "main", "message": "Nightly scan", "finished": now - 28000}),
            ({"id": 4, "full_name": "example/docs"}, None),
        ]
        if widget_kind == "pipelines":
            return self.pipelines_card(latest, options)
        queue = {"stats": {"running_count": 1, "pending_count": int(fake.walk("woodpecker-queue", tick, 0, 3))}}
        agents = [{"name": "agent-1", "last_contact": now - 20}, {"name": "agent-2", "last_contact": now - (600 if fake.flicker("woodpecker-agent", tick, 0.2) else 30)}]
        return self.overview_card(latest, queue, agents, None, now)


ADAPTER = WoodpeckerAdapter()
