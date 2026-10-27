"""Stash: the size of the library, what it is doing, and a button to scan.

Measured on 27.10.2026 against stashapp/stash v0.31.1 after its setup through
the API, with a user and an API key, three generated test videos (colour
bars) scanned and a generate task running. Only numbers and task names are
read: no title, no picture and no name of a person comes out of this adapter.

⚠️ Stash is one GraphQL address, ``POST /graphql``. A refusal is **HTTP 401
with no body**, for no key, a wrong key and a key sent while Stash has no
sign-in set up. A query that fails inside Stash is HTTP 200 with
``{"errors": [...]}`` (a statistics query before the setup answered "invalid
memory address or nil pointer dereference").

⚠️ The key goes in the header ``ApiKey`` and is a JWT. It is made in the
settings under Security, "Generate API Key", and **that button only works once
a user name and password are set**: ``generateAPIKey`` answered an empty
string for a Stash without them. Stash signs a browser in by cookie
(``POST /login``, a form), not by basic authentication.

⚠️ ``jobQueue`` is **null, not an empty list**, when nothing runs. A running
job has ``status`` ``RUNNING`` (``STOPPING`` after a stop, then it is gone),
``description`` ("Generating...", "Scanning..."), ``subTasks`` (the file it is
at) and ``progress`` as a fraction from 0 to 1, which stayed 0 for a long
first file and then jumped.

⚠️ Sizes come as JSON numbers that may be written as floats
(``4.851177e+06``); they are read as numbers and rounded.

⚠️ ``stopJob`` answers true for a job number that does not exist.
"""

from __future__ import annotations

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
    duration_short,
    human_bytes,
)

STATS = ("scene_count scenes_size scenes_duration image_count images_size gallery_count performer_count studio_count tag_count "
         "total_play_count total_play_duration scenes_played")


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


class StashAdapter(Adapter):
    kind = "stash"
    label = "Stash"
    category = "media"
    description = "The size of the library, the tasks Stash is running and a button to scan for new files."
    icon = "stash"
    docs_url = "https://docs.stashapp.cc/in-app-manual/apikey"
    #: Measured against Stash v0.31.1 in a container with generated test videos; no real library.
    beta = True
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://stash:9999"),
        Field("api_key", "API key", type="password", secret=True,
              help="Settings > Security > Generate API Key; it needs a user name and password to be set first. Leave empty when Stash has no login."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(
            kind="library",
            label="Library",
            description="Scenes, images, galleries, how much space they take, and how much has been watched.",
            renderer="value",
            default_size=(3, 2),
            min_size=(1, 1),
            refresh_seconds=300,
            metrics=("scenes", "images"),
        ),
        WidgetType(
            kind="tasks",
            label="Tasks",
            description="What Stash is scanning, generating or cleaning right now, with progress, and buttons to scan or stop.",
            renderer="list",
            default_size=(4, 2),
            refresh_seconds=15,
            metrics=("running",),
        ),
    )

    async def _query(self, config: dict[str, Any], ctx: Context, query: str, cache: float = 0) -> dict[str, Any]:
        headers = {"ApiKey": str(config["api_key"])} if config.get("api_key") else {}
        response = await ctx.request("POST", f"{base_url(config)}/graphql", json_body={"query": query}, headers=headers,
                                     verify=not config.get("insecure"), auth_errors=False)
        if response.status_code in (401, 403):
            raise AuthFailed("Stash rejected the API key." if config.get("api_key") else "Stash wants an API key.")
        if response.status_code == 404:
            raise AdapterError("This address answers, but not the way Stash does.", code="not_stash",
                               hint="Use the address of Stash itself, usually port 9999.")
        try:
            answer = response.json()
        except ValueError as error:
            raise AdapterError("Stash did not answer with JSON.", code="not_json",
                               hint="The URL probably points at something else than Stash.") from error
        if not isinstance(answer, dict) or ("data" not in answer and "errors" not in answer):
            raise AdapterError("This address answers, but not the way Stash does.", code="not_stash")
        if answer.get("errors"):
            first = answer["errors"][0] if isinstance(answer["errors"][0], dict) else {}
            raise AdapterError(f"Stash refused the query: {first.get('message') or 'an error'}", code="graphql_error",
                               hint="Stash's own message; a Stash that is not set up yet answers this way.")
        return answer.get("data") or {}

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        data = await self._query(config, ctx, "{ version { version } stats { scene_count } }")
        version = str((data.get("version") or {}).get("version") or "")
        scenes = int(_number((data.get("stats") or {}).get("scene_count")))
        return f"Stash {version} answers, {scenes} scenes." if version else f"Stash answers, {scenes} scenes."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        link = base_url(config)
        if widget_kind == "tasks":
            data = await self._query(config, ctx, "{ jobQueue { id status subTasks description progress startTime error } }")
            return self.tasks_card(data.get("jobQueue"), link)
        data = await self._query(config, ctx, "{ stats { " + STATS + " } }")
        return self.library_card(data.get("stats") or {}, link)

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def library_card(stats: dict[str, Any], link: str | None = None) -> WidgetData:
        scenes, images = int(_number(stats.get("scene_count"))), int(_number(stats.get("image_count")))
        size = _number(stats.get("scenes_size")) + _number(stats.get("images_size"))
        secondary: list[dict[str, Any]] = [
            {"label": "Images", "value": images},
            {"label": "Galleries", "value": int(_number(stats.get("gallery_count")))},
            {"label": "Size", "value": human_bytes(size)},
            {"label": "Length", "value": duration_short(_number(stats.get("scenes_duration")))},
        ]
        if _number(stats.get("total_play_count")):
            secondary.append({"label": "Plays", "value": int(_number(stats["total_play_count"]))})
            secondary.append({"label": "Watched", "value": duration_short(_number(stats.get("total_play_duration")))})
        return WidgetData(
            primary={"label": "Scenes", "value": scenes},
            secondary=secondary,
            metrics={"scenes": float(scenes), "images": float(images)},
            link=link,
        )

    @staticmethod
    def tasks_card(jobs: Any, link: str | None = None) -> WidgetData:
        running = [job for job in jobs or [] if isinstance(job, dict)]
        items = []
        for job in running:
            state = str(job.get("status") or "")
            progress = max(0.0, min(1.0, _number(job.get("progress")))) * 100
            sub = [str(one) for one in job.get("subTasks") or [] if one]
            items.append({
                "id": str(job.get("id") or ""),
                "title": str(job.get("description") or "Task"),
                "subtitle": sub[0] if sub else {"STOPPING": "Stopping", "READY": "Waiting"}.get(state, ""),
                "progress": round(progress, 1),
                "value": f"{progress:.0f}%",
                "status": "bad" if job.get("error") else "warn" if state in ("STOPPING", "READY") else "ok",
            })
        actions = [Action(id="scan", label="Scan for new files", icon="refresh-cw", confirm=True)]
        if running:
            actions.append(Action(id="stop", label="Stop all tasks", icon="square", confirm=True))
        return WidgetData(
            status="bad" if any(item["status"] == "bad" for item in items) else "ok",
            items=items,
            secondary=[{"label": "Running", "value": len(running)}],
            metrics={"running": float(len(running))},
            actions=actions,
            link=link,
            meta={"empty": "No task is running."},
        )

    async def action(self, widget_kind: str, action_id: str, params: dict[str, Any], config: dict[str, Any],
                     options: dict[str, Any], ctx: Context) -> str:
        if action_id == "scan":
            await self._query(config, ctx, "mutation { metadataScan(input: {}) }")
            ctx.forget_answers()
            return "Stash looks for new files."
        if action_id == "stop":
            await self._query(config, ctx, "mutation { stopAllJobs }")
            ctx.forget_answers()
            return "The tasks are stopping."
        raise AdapterError("Unknown action.", code="no_such_action")

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        if widget_kind == "tasks":
            busy = fake.flicker("stash-busy", tick // 15, 0.45)
            jobs = [{"id": "12", "status": "RUNNING", "description": "Generating...", "subTasks": ["Generating sprites for /media/clips/harbour-lights-03.mp4"],
                     "progress": fake.walk("stash-progress", tick, 0.05, 0.95)}] if busy else None
            return self.tasks_card(jobs)
        return self.library_card({"scene_count": 1840 + tick // 60, "image_count": 22610, "gallery_count": 148, "scenes_size": 1.4 * 1024 ** 4,
                                  "images_size": 96 * 1024 ** 3, "scenes_duration": 912000, "total_play_count": 3120, "total_play_duration": 250000})


ADAPTER: Adapter = StashAdapter()
