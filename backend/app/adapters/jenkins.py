"""Jenkins: jobs and their last build, the queue and the executors, and a button to build a job.

Measured on 27.10.2026 against jenkins/jenkins:lts-jdk21 (2.580.1) with the
Folder plugin, a user with an API token and nine jobs: passing, failing,
running, never built, disabled, parameterised, and two inside a folder.

- ``GET /api/json?tree=...`` answers only what the ``tree`` names, and only
  descends into a folder when the tree says ``jobs[...]`` again, so the tree
  is written out to the depth read here (three folders deep).
- ``color`` is the last *finished* build (``blue`` passed, ``red`` failed,
  ``yellow`` unstable, ``aborted``, ``notbuilt``, ``disabled``); a running
  build adds ``_anime`` (``notbuilt_anime`` for a job that never finished one).
  A folder has no ``color``.
- A user name with an API token (Security page of the user) needs no CSRF
  crumb, for ``GET`` and for ``POST``. The password does for ``POST``.
- ``X-Jenkins`` carries the version on every answer that got past the login.
  A wrong token is **401**, no credentials at all **403** (with the header).
- ``POST /job/<a>/job/<b>/build`` answers **201** and queues the build; a
  job with parameters answers **400** there and **201** on
  ``buildWithParameters`` (their defaults); a disabled job **409**; a job
  that does not exist **404**.
"""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import quote

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
    duration_short,
)

#: A job's colour: how it stands as a colour and, where it is not plain success, a word.
COLOURS = {
    "blue": ("ok", ""), "red": ("bad", "Failed"), "yellow": ("warn", "Unstable"), "aborted": ("unknown", "Aborted"),
    "grey": ("unknown", "Never built"), "notbuilt": ("unknown", "Never built"), "disabled": ("unknown", "Disabled"),
}

BUILD = "result,building,timestamp,duration,estimatedDuration,number,url"


def _tree(depth: int) -> str:
    """The jobs of one level, and the jobs of the folders in it, down to ``depth`` levels."""
    inner = f",jobs[{_tree(depth - 1)}]" if depth > 1 else ""
    return f"name,fullName,url,color,lastBuild[{BUILD}]{inner}"


JOBS = f"jobs[{_tree(3)}]"


def _flatten(jobs: Any) -> list[dict[str, Any]]:
    """Every job, folders walked into and left out themselves."""
    found: list[dict[str, Any]] = []
    for job in jobs or []:
        if not isinstance(job, dict):
            continue
        if isinstance(job.get("jobs"), list):
            found += _flatten(job["jobs"])
        elif job.get("color"):
            found.append(job)
    return found


def _job_path(full_name: Any) -> str:
    """``/job/a/job/b`` out of ``a/b``, each name a single quoted segment."""
    names = str(full_name or "").split("/")
    if not full_name or any(name in ("", ".", "..") or any(ord(char) < 32 or char in "?#\\" for char in name) for name in names):
        raise AdapterError("That is not the name of a job.", code="bad_param")
    return "".join(f"/job/{quote(name, safe='')}" for name in names)


class JenkinsAdapter(Adapter):
    kind = "jenkins"
    label = "Jenkins"
    category = "hosts"
    description = "Jobs and how their last build went, the queue and the executors of Jenkins, with a button to build a job."
    icon = "jenkins"
    docs_url = "https://www.jenkins.io/doc/book/using/remote-access-api/"
    #: Measured against Jenkins 2.580.1 (LTS) with the Folder plugin.
    beta = True
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://jenkins:8080", help="With the path it is served under, if any, such as /jenkins."),
        Field("user", "User name", help="Empty if Jenkins lets anonymous users read."),
        Field("token", "API token", type="password", secret=True,
              help="From the user's own page under Security > API Token, not the password: with the password the build button is refused for want of a CSRF crumb. The user needs Overall/Read and Job/Read, and Job/Build for the button."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(
            kind="overview",
            label="Jenkins overview",
            description="Jobs that fail, builds running, builds waiting in the queue and executors busy.",
            renderer="value",
            default_size=(2, 2),
            min_size=(1, 1),
            refresh_seconds=60,
            metrics=("failing", "queue", "busy"),
        ),
        WidgetType(
            kind="jobs",
            label="Jobs",
            description="Every job with its last build, failing ones first, running ones with how far they are, each with a button to build it.",
            renderer="list",
            default_size=(4, 3),
            min_size=(3, 2),
            refresh_seconds=60,
            metrics=("failing",),
            options=(
                Field("limit", "Entries", type="number", default=10),
                Field("only_failing", "Only the failing ones", type="bool", default=False),
                Field("disabled", "Show disabled jobs", type="bool", default=False),
                Field("folder", "Only in this folder", placeholder="team", help="The full name of a folder, such as team or team/api. Empty for every job."),
            ),
        ),
    )

    # -- asking Jenkins ------------------------------------------------------------

    @staticmethod
    def _credentials(config: dict[str, Any]) -> tuple[str, str] | None:
        user, token = str(config.get("user") or "").strip(), str(config.get("token") or "").strip()
        return (user, token) if user or token else None

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, tree: str, cache: float = 20) -> tuple[Any, str]:
        """The answer to a tree query and the version in ``X-Jenkins``."""
        response = await ctx.request("GET", f"{base_url(config)}{path}", params={"tree": tree}, auth=self._credentials(config),
                                     verify=not config.get("insecure"), cache_seconds=cache, timeout=25, auth_errors=False)
        if response.status_code in (401, 403):
            failure = AuthFailed("Jenkins rejected the user name or the API token." if self._credentials(config) else "Jenkins wants a user name and an API token.")
            failure.hint = "Make the token on the user's page under Security > API Token. The user needs Overall/Read and Job/Read."
            raise failure
        if response.status_code >= 400:
            raise AdapterError(f"Jenkins answered with HTTP {response.status_code}.", code="http_error",
                               hint="The URL is the address of Jenkins itself, with its path if it has one.")
        try:
            return response.json(), str(response.headers.get("x-jenkins") or "")
        except ValueError as error:
            raise AdapterError("Jenkins did not answer with JSON.", code="not_json",
                               hint="The URL probably points at a login page or a reverse proxy.") from error

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        answer, version = await self._get(config, ctx, "/api/json", "numExecutors,jobs[name]", cache=0)
        if not isinstance(answer, dict) or "jobs" not in answer:
            raise AdapterError("This address answers, but not the way Jenkins does.", code="not_jenkins")
        jobs = len(answer["jobs"])
        return f"Jenkins {version} answers, {jobs} jobs at the top." if version else f"Jenkins answers, {jobs} jobs at the top."

    # -- the cards -----------------------------------------------------------------

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        root, _version = await self._get(config, ctx, "/api/json", JOBS)
        jobs = _flatten((root or {}).get("jobs"))
        link = base_url(config)
        if widget_kind == "jobs":
            return self.jobs_card(jobs, options, link)
        queue, _ = await self._get(config, ctx, "/queue/api/json", "items[id]")
        computers, _ = await self._get(config, ctx, "/computer/api/json", "busyExecutors,totalExecutors,computer[displayName,offline,temporarilyOffline]")
        return self.overview_card(jobs, queue, computers, link)

    @staticmethod
    def _standing(job: dict[str, Any]) -> tuple[str, str, bool]:
        """The colour of the last finished build, a word for it and whether a build runs now."""
        colour = str(job.get("color") or "")
        running = colour.endswith("_anime")
        status, word = COLOURS.get(colour.removesuffix("_anime"), ("unknown", ""))
        return status, word, running

    @classmethod
    def overview_card(cls, jobs: list[dict[str, Any]], queue: Any, computers: Any, link: str | None = None) -> WidgetData:
        standing = [cls._standing(job) for job in jobs if not str(job.get("color")).startswith("disabled")]
        failing = sum(1 for status, _word, _running in standing if status == "bad")
        unstable = sum(1 for status, _word, _running in standing if status == "warn")
        running = sum(1 for _status, _word, going in standing if going)
        waiting = len((queue or {}).get("items") or []) if isinstance(queue, dict) else 0
        computers = computers if isinstance(computers, dict) else {}
        busy, total = int(computers.get("busyExecutors") or 0), int(computers.get("totalExecutors") or 0)
        offline = sum(1 for one in computers.get("computer") or [] if isinstance(one, dict) and one.get("offline"))
        secondary = [{"label": "Jobs", "value": len(standing)}, {"label": "Running", "value": running}, {"label": "Queued", "value": waiting},
                     {"label": "Executors busy", "value": f"{busy} of {total}"}]
        if unstable:
            secondary.insert(1, {"label": "Unstable", "value": unstable})
        if offline:
            secondary.append({"label": "Nodes offline", "value": offline})
        return WidgetData(
            status="bad" if failing else ("warn" if unstable or offline else "ok"),
            primary={"label": "Failing", "value": failing},
            secondary=secondary,
            metrics={"failing": float(failing), "queue": float(waiting), "busy": float(busy)},
            link=link,
        )

    @classmethod
    def jobs_card(cls, jobs: list[dict[str, Any]], options: dict[str, Any], link: str | None = None, now: float | None = None) -> WidgetData:
        moment = now if now is not None else time.time()
        folder = str(options.get("folder") or "").strip().strip("/")
        shown = [job for job in jobs if not folder or str(job.get("fullName") or "").startswith(folder + "/")]
        if not options.get("disabled"):
            shown = [job for job in shown if not str(job.get("color")).startswith("disabled")]
        rows = []
        for job in shown:
            status, word, running = cls._standing(job)
            if options.get("only_failing") and status != "bad":
                continue
            last = job.get("lastBuild") if isinstance(job.get("lastBuild"), dict) else {}
            stamp = (last.get("timestamp") or 0) / 1000
            number = f"#{last['number']}" if last.get("number") else ""
            took = duration_short((last.get("duration") or 0) / 1000) if last.get("duration") and not last.get("building") else ""
            parts = ("Running" if running else word, number, took)
            name = str(job.get("fullName") or job.get("name") or "?")
            row: dict[str, Any] = {
                "title": name,
                "subtitle": " · ".join(part for part in parts if part),
                "status": status,
                "value": ago(stamp, moment) if stamp else "",
                "url": str(job.get("url") or ""),
            }
            if running and last.get("building") and (last.get("estimatedDuration") or 0) > 0 and stamp:
                row["progress"] = round(min(99.0, 100 * (moment - stamp) * 1000 / last["estimatedDuration"]), 1)
            if not str(job.get("color")).startswith("disabled"):
                row["actions"] = [{"id": "build", "label": "Build now", "icon": "play", "confirm": True, "params": {"job": name}}]
            rows.append((status != "bad", not running, -stamp, row))
        rows.sort(key=lambda entry: entry[:3])
        failing = sum(1 for entry in rows if not entry[0])
        limit = max(1, min(100, int(options.get("limit") or 10)))
        return WidgetData(
            status="bad" if failing else "ok",
            items=[entry[3] for entry in rows[:limit]],
            secondary=[{"label": "Failing", "value": failing}, {"label": "Jobs", "value": len(rows)}],
            metrics={"failing": float(failing)},
            link=link,
            meta={"empty": "No job fails." if options.get("only_failing") else "Jenkins has no job to show."},
        )

    # -- the button ----------------------------------------------------------------

    async def action(self, widget_kind: str, action_id: str, params: dict[str, Any], config: dict[str, Any],
                     options: dict[str, Any], ctx: Context) -> str:
        if action_id != "build":
            raise AdapterError("Unknown action.", code="no_such_action")
        path = _job_path(params.get("job"))
        for step in ("build", "buildWithParameters"):
            response = await ctx.request("POST", f"{base_url(config)}{path}/{step}", auth=self._credentials(config),
                                         verify=not config.get("insecure"), timeout=25, auth_errors=False)
            # A job with parameters refuses plain "build" and starts from their defaults on the other.
            if response.status_code == 400 and step == "build":
                continue
            break
        ctx.forget_answers()
        if response.status_code in (401, 403):
            failure = AuthFailed("Jenkins refused to build this job.")
            failure.hint = "The user needs Job/Build, and an API token rather than the password, which would also need a CSRF crumb."
            raise failure
        if response.status_code == 404:
            raise AdapterError("Jenkins has no such job any more.", code="not_found")
        if response.status_code == 409:
            raise AdapterError("This job is disabled.", code="job_disabled", hint="Enable the job in Jenkins to build it.")
        if response.status_code >= 400:
            raise AdapterError(f"Jenkins answered with HTTP {response.status_code}.", code="http_error")
        return f"{params.get('job')} is queued."

    # -- demo ----------------------------------------------------------------------

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        now = time.time() - tick % 60
        red = (tick // 300) % 3 == 0
        stamp = lambda seconds: int((now - seconds) * 1000)  # noqa: E731
        base = "http://jenkins.example.com/job/"
        jobs = [
            {"name": "api-tests", "fullName": "team/api-tests", "url": base, "color": "red" if red else "blue",
             "lastBuild": {"number": 212, "timestamp": stamp(1500), "duration": 184000, "building": False}},
            {"name": "web-build", "fullName": "team/web-build", "url": base, "color": "blue_anime",
             "lastBuild": {"number": 97, "timestamp": stamp(60 + tick % 60), "duration": 0, "building": True, "estimatedDuration": 240000}},
            {"name": "nightly-backup", "fullName": "nightly-backup", "url": base, "color": "blue",
             "lastBuild": {"number": 331, "timestamp": stamp(28000), "duration": 912000, "building": False}},
            {"name": "image-scan", "fullName": "image-scan", "url": base, "color": "yellow",
             "lastBuild": {"number": 18, "timestamp": stamp(90000), "duration": 62000, "building": False}},
            {"name": "release", "fullName": "release", "url": base, "color": "notbuilt", "lastBuild": None},
            {"name": "old-mirror", "fullName": "old-mirror", "url": base, "color": "disabled", "lastBuild": None},
        ]
        if widget_kind == "jobs":
            return self.jobs_card(jobs, options, None, now)
        queue = {"items": [{"id": 1}] * int(fake.walk("jenkins-queue", tick, 0, 3))}
        return self.overview_card(jobs, queue, {"busyExecutors": int(fake.walk("jenkins-busy", tick, 0, 2)) + 1, "totalExecutors": 4,
                                                "computer": [{"displayName": "Built-In Node", "offline": False}]})


ADAPTER = JenkinsAdapter()
