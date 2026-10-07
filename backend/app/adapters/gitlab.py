"""GitLab: pipelines, merge requests, issues and releases, on GitLab.com or your own.

API v4, with a personal, group or project access token in ``PRIVATE-TOKEN``,
or with none at all for public projects. Measured against GitLab.com on
07.10.2026 with gitlab-org/cli, without a token:

- 500 requests a minute per address without a token, said in ``ratelimit-*``
  on every answer; ``/version`` wants a token (401).
- The pipeline list is mostly merge request and workload pipelines
  (``refs/merge-requests/…``, ``refs/workloads/…``): of the twenty newest,
  one ran on a branch. ``scope=branches`` hands out the latest pipeline of
  every branch, ``/pipelines/latest`` the latest of the default branch.
- Without a token the project carries no ``open_issues_count``; the issue
  statistics answer anyway. Lists say their size in ``x-total``, which GitLab
  leaves out above 10,000, so a missing one is read as "at least a page".
- A project that does not exist and one the token may not see both answer 404.
"""

from __future__ import annotations

import time
from datetime import datetime
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
)

#: A pipeline's state, as a colour and, where it is not plain success, a word.
PIPELINE = {
    "success": ("ok", ""), "failed": ("bad", "Failed"), "canceled": ("unknown", "Cancelled"), "canceling": ("unknown", "Cancelled"),
    "skipped": ("unknown", "Skipped"), "manual": ("warn", "Manual"), "scheduled": ("unknown", "Scheduled"),
    "running": ("warn", "Running"), "pending": ("unknown", "Waiting"), "preparing": ("unknown", "Waiting"),
    "waiting_for_resource": ("unknown", "Waiting"), "waiting_for_callback": ("unknown", "Waiting"), "created": ("unknown", "Waiting"),
}

#: Why a merge request cannot be merged yet, where GitLab says so in detailed_merge_status.
MERGE = {
    "draft_status": "Draft", "conflict": "Conflict", "need_rebase": "Needs a rebase", "not_approved": "Needs approval",
    "ci_must_pass": "Pipeline must pass", "ci_still_running": "Pipeline running", "discussions_not_resolved": "Open threads",
    "mergeable": "Ready to merge",
}

PROJECTS_FIELD = Field("projects", "Projects", type="textarea", required=True, placeholder="group/project",
                       help="One per line, as group/project or the project's address. At most ten.")


def _project(line: str, home: str) -> str:
    """group/project out of whatever was pasted: a path, a full address, or a number."""
    text = line.strip().rstrip("/")
    for prefix in (home + "/", "https://gitlab.com/"):
        if text.startswith(prefix):
            text = text[len(prefix):]
    return text.split("/-/", 1)[0].removesuffix(".git").strip("/")


def _stamp(text: Any) -> int | None:
    try:
        return int(datetime.fromisoformat(str(text).replace("Z", "+00:00")).timestamp())
    except ValueError:
        return None


class GitlabAdapter(Adapter):
    kind = "gitlab"
    label = "GitLab"
    category = "hosts"
    description = "Pipelines, merge requests, issues and releases of the projects you follow, on GitLab.com or your own GitLab."
    icon = "gitlab"
    docs_url = "https://docs.gitlab.com/api/rest/"
    fields = (
        Field("url", "URL", type="url", required=True, default="https://gitlab.com", placeholder="https://gitlab.com",
              help="GitLab.com, or the address of your own GitLab."),
        Field("token", "Access token", type="password", secret=True,
              help="Optional for public projects. A personal, group or project access token with the scope read_api reaches private ones and raises the limit."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(
            kind="projects",
            label="Projects",
            description="One row per project: the latest pipeline of its default branch, its open merge requests and issues, and when it last changed.",
            renderer="list",
            default_size=(4, 3),
            min_size=(3, 2),
            refresh_seconds=600,
            metrics=("failing",),
            options=(PROJECTS_FIELD,),
        ),
        WidgetType(
            kind="pipelines",
            label="Pipelines",
            description="The latest pipeline of every branch or tag, red ones first. Merge request pipelines are left out.",
            renderer="list",
            default_size=(4, 3),
            min_size=(3, 2),
            refresh_seconds=300,
            metrics=("failing",),
            options=(
                PROJECTS_FIELD,
                Field("scope", "Pipelines of", type="select", default="default",
                      options=(("default", "The default branch"), ("branches", "Every branch"), ("tags", "Release tags"))),
                Field("limit", "Entries", type="number", default=8),
            ),
        ),
        WidgetType(
            kind="merge_requests",
            label="Merge requests and issues",
            description="What is open in the projects you follow, the latest changed first. Merge requests say why they cannot be merged yet.",
            renderer="list",
            default_size=(4, 3),
            min_size=(3, 2),
            refresh_seconds=600,
            options=(
                PROJECTS_FIELD,
                Field("what", "Show", type="select", default="merge_requests", options=(("merge_requests", "Merge requests"), ("issues", "Issues"))),
                Field("limit", "Entries", type="number", default=8),
            ),
        ),
        WidgetType(
            kind="releases",
            label="Releases",
            description="One line per project with its newest release and when it came.",
            renderer="feed",
            default_size=(4, 4),
            refresh_seconds=1800,
            options=(PROJECTS_FIELD, Field("limit", "Entries", type="number", default=8)),
        ),
    )

    def default_link(self, config: dict[str, Any]) -> str:
        return base_url(config) or "https://gitlab.com"

    # -- asking GitLab ---------------------------------------------------------

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, params: dict[str, Any] | None = None,
                   cache: float = 30) -> tuple[Any, dict[str, str]]:
        """One answer and its headers. None for a 404, which is about one project, not the connection."""
        token = str(config.get("token") or "").strip()
        headers = {"PRIVATE-TOKEN": token} if token else None
        response = await ctx.request("GET", f"{base_url(config) or 'https://gitlab.com'}/api/v4{path}", headers=headers, params=params,
                                     verify=not config.get("insecure"), cache_seconds=cache, timeout=20, auth_errors=False)
        if response.status_code == 401:
            failure = AuthFailed("GitLab rejected the token." if token else "GitLab wants a token for this.")
            failure.hint = "A token needs the scope read_api; one that has expired or was revoked is refused the same way."
            raise failure
        if response.status_code == 429:
            wait = response.headers.get("retry-after") or "60"
            raise AdapterError(f"GitLab's rate limit is used up; try again in {wait} s.", code="rate_limited",
                               hint="Give the cards a longer interval, or a token, which raises the limit on GitLab.com.")
        if response.status_code in (403, 404):
            return None, dict(response.headers)
        if response.status_code >= 400:
            raise AdapterError(f"GitLab answered with HTTP {response.status_code}.", code="http_error")
        try:
            return response.json(), dict(response.headers)
        except ValueError as error:
            raise AdapterError("GitLab did not answer with JSON.", code="not_json",
                               hint="The URL is the address of GitLab itself, without /api/v4.") from error

    @staticmethod
    def _total(headers: dict[str, str], got: int, page: int) -> int | str:
        """The size of a list from x-total; above 10,000 GitLab leaves it out."""
        total = headers.get("x-total") or ""
        if total.isdigit():
            return int(total)
        return f"{got}+" if got >= page else got

    def _projects(self, config: dict[str, Any], options: dict[str, Any]) -> list[str]:
        home = base_url(config) or "https://gitlab.com"
        found = [_project(line, home) for line in str(options.get("projects") or "").splitlines() if line.strip()]
        found = [one for one in found if one][:10]
        if not found:
            raise AdapterError("No project is set.", code="missing_project")
        return found

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        if str(config.get("token") or "").strip():
            user, _ = await self._get(config, ctx, "/user", cache=0)
            version, _ = await self._get(config, ctx, "/version", cache=0)
            if not isinstance(user, dict):
                raise AuthFailed("GitLab rejected the token.")
            release = f" {version.get('version')}" if isinstance(version, dict) and version.get("version") else ""
            return f"GitLab{release} accepts the token of {user.get('username', '?')}."
        answer, headers = await self._get(config, ctx, "/projects", {"per_page": 1}, cache=0)
        if not isinstance(answer, list):
            raise AdapterError("This address answers, but not the way GitLab does.", code="not_gitlab")
        left = headers.get("ratelimit-remaining")
        return "GitLab answers without a token; public projects can be read" + (f", {left} requests left this minute." if left else ".")

    # -- the cards -------------------------------------------------------------

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        projects = self._projects(config, options)
        limit = max(1, min(20, int(options.get("limit") or 8)))
        failures: list[str] = []
        found: list[tuple[str, Any]] = []
        totals: list[int | str] = []
        what = str(options.get("what") or "merge_requests")
        for project in projects:
            where = f"/projects/{quote(project, safe='')}"
            try:
                if widget_kind == "projects":
                    answer = await self._project_row(config, ctx, where)
                elif widget_kind == "pipelines":
                    scope = str(options.get("scope") or "default")
                    if scope == "default":
                        latest, _ = await self._get(config, ctx, f"{where}/pipelines/latest")
                        answer = [latest] if isinstance(latest, dict) else None
                    else:
                        answer, _ = await self._get(config, ctx, f"{where}/pipelines", {"scope": scope, "per_page": limit})
                elif widget_kind == "merge_requests":
                    kind = "issues" if what == "issues" else "merge_requests"
                    answer, headers = await self._get(config, ctx, f"{where}/{kind}",
                                                      {"state": "opened", "order_by": "updated_at", "sort": "desc", "per_page": limit})
                    if isinstance(answer, list):
                        totals.append(self._total(headers, len(answer), limit))
                else:
                    answer, _ = await self._get(config, ctx, f"{where}/releases", {"per_page": 1})
            except (AuthFailed, AdapterError) as error:
                if isinstance(error, AuthFailed) or error.code in ("rate_limited", "unreachable"):
                    # None of these is about one project: every line would say the same.
                    raise
                failures.append(f"{project}: {error.message}")
                continue
            if answer is None:
                failures.append(f"{project}: not found, or not visible to this token")
                continue
            found.append((project, answer))
        if widget_kind == "projects":
            data = self.project_rows(found)
        elif widget_kind == "pipelines":
            data = self.pipeline_rows(found, limit, by_project=str(options.get("scope") or "default") == "default")
        elif widget_kind == "merge_requests":
            data = self.open_rows(found, what == "issues", limit, totals)
        else:
            data = self.release_rows(found, limit)
        data.meta = {**(data.meta or {}), "failures": failures}
        if failures and not data.items:
            data.error = "; ".join(failures)
            data.status = "bad"
        return data

    async def _project_row(self, config: dict[str, Any], ctx: Context, where: str) -> dict[str, Any] | None:
        project, _ = await self._get(config, ctx, where, cache=120)
        if not isinstance(project, dict):
            return None
        pipeline, _ = await self._get(config, ctx, f"{where}/pipelines/latest")
        merges, headers = await self._get(config, ctx, f"{where}/merge_requests", {"state": "opened", "per_page": 1}, cache=120)
        statistics, _ = await self._get(config, ctx, f"{where}/issues_statistics", cache=120)
        opened = ((statistics or {}).get("statistics") or {}).get("counts", {}).get("opened") if isinstance(statistics, dict) else None
        return {
            "project": project,
            "pipeline": pipeline if isinstance(pipeline, dict) else None,
            "merge_requests": self._total(headers, len(merges), 1) if isinstance(merges, list) else None,
            "issues": opened,
        }

    @staticmethod
    def project_rows(found: list[tuple[str, Any]]) -> WidgetData:
        rows = []
        for path, entry in found:
            project, pipeline = entry["project"], entry["pipeline"]
            colour, word = PIPELINE.get(str((pipeline or {}).get("status") or ""), ("unknown", "")) if pipeline else ("unknown", "No pipeline")
            counts = []
            if entry["merge_requests"] is not None:
                counts.append(f"{entry['merge_requests']} MRs")
            if entry["issues"] is not None:
                counts.append(f"{entry['issues']} issues")
            rows.append({
                "title": str(project.get("name") or path.rsplit("/", 1)[-1]),
                "subtitle": " · ".join(part for part in (word, *counts) if part),
                "status": colour,
                "value": ago(project.get("last_activity_at")),
                "url": str(project.get("web_url") or ""),
            })
        rows.sort(key=lambda row: row["status"] != "bad")
        failing = sum(1 for row in rows if row["status"] == "bad")
        return WidgetData(
            status="bad" if failing else "ok",
            items=rows,
            secondary=[{"label": "Failing pipelines", "value": failing}],
            meta={"empty": "No project could be read."},
            metrics={"failing": float(failing)},
        )

    @staticmethod
    def pipeline_rows(found: list[tuple[str, Any]], limit: int, by_project: bool = False) -> WidgetData:
        """Rows named by their branch or tag, or by their project where each project has one: the default branch."""
        rows = []
        for path, pipelines in found:
            for pipeline in pipelines or []:
                if not isinstance(pipeline, dict) or str(pipeline.get("ref") or "").startswith("refs/"):
                    continue
                colour, word = PIPELINE.get(str(pipeline.get("status") or ""), ("unknown", str(pipeline.get("status") or "").capitalize()))
                name, ref = path.rsplit("/", 1)[-1], str(pipeline.get("ref") or "?")
                parts = (word, ref if by_project else name, "Scheduled" if pipeline.get("source") == "schedule" else "")
                rows.append((colour, str(pipeline.get("updated_at") or ""), {
                    "title": name if by_project else ref,
                    "subtitle": " · ".join(part for part in parts if part),
                    "status": colour,
                    "value": ago(pipeline.get("updated_at") or pipeline.get("created_at")),
                    "url": str(pipeline.get("web_url") or ""),
                }))
        # Red first, then by time.
        rows.sort(key=lambda row: row[1], reverse=True)
        rows.sort(key=lambda row: row[0] != "bad")
        failing = sum(1 for colour, _t, _r in rows if colour == "bad")
        return WidgetData(
            status="bad" if failing else "ok",
            items=[row for _c, _t, row in rows[:limit]],
            secondary=[{"label": "Failing pipelines", "value": failing}],
            meta={"empty": "No pipelines yet."},
            metrics={"failing": float(failing)},
        )

    @staticmethod
    def open_rows(found: list[tuple[str, Any]], issues: bool, limit: int, totals: list[int | str]) -> WidgetData:
        rows = []
        for path, entries in found:
            for entry in entries or []:
                if not isinstance(entry, dict):
                    continue
                place = f"{path.rsplit('/', 1)[-1]}{(entry.get('references') or {}).get('short') or ''}"
                state = "" if issues else MERGE.get(str(entry.get("detailed_merge_status") or ""), "Draft" if entry.get("draft") else "")
                title = str(entry.get("title") or "?")
                rows.append((str(entry.get("updated_at") or ""), {
                    # The word is said once, in front, and not twice.
                    "title": title.removeprefix("Draft: ") if state == "Draft" else title,
                    "subtitle": " · ".join(part for part in (state, place) if part),
                    "value": ago(entry.get("updated_at")),
                    "url": str(entry.get("web_url") or ""),
                }))
        rows.sort(key=lambda row: row[0], reverse=True)
        exact = sum(total for total in totals if isinstance(total, int))
        total: int | str = exact if all(isinstance(one, int) for one in totals) else f"{exact + sum(int(str(one).rstrip('+')) for one in totals if not isinstance(one, int))}+"
        return WidgetData(
            status="ok",
            items=[row for _updated, row in rows[:limit]],
            secondary=[{"label": "Open issues" if issues else "Merge requests", "value": total}],
            meta={"empty": "No open issues." if issues else "No open merge requests."},
        )

    @staticmethod
    def release_rows(found: list[tuple[str, Any]], limit: int) -> WidgetData:
        entries = []
        for path, releases in found:
            release = releases[0] if isinstance(releases, list) and releases else None
            if not isinstance(release, dict):
                continue
            notes = [line for line in str(release.get("description") or "").strip().splitlines() if line.strip() and not line.startswith("#")]
            entries.append({
                "title": f"{path.rsplit('/', 1)[-1]} {release.get('tag_name') or release.get('name') or '?'}",
                "url": str(((release.get("_links") or {}).get("self")) or ""),
                "source": path,
                "published": _stamp(release.get("released_at") or release.get("created_at") or ""),
                "summary": notes[0].strip()[:280] if notes else "",
                "image": "",
            })
        entries.sort(key=lambda entry: entry["published"] or 0, reverse=True)
        return WidgetData(status="ok" if entries else "warn", items=entries[:limit], meta={"style": "list"})

    # -- demo ------------------------------------------------------------------

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        now = time.time() - tick % 60
        stamp = lambda seconds: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - seconds))  # noqa: E731
        red = (tick // 300) % 3 == 0
        web = "https://gitlab.com/"
        if widget_kind == "projects":
            return self.project_rows([
                ("example/api", {"project": {"name": "api", "last_activity_at": stamp(1800), "web_url": web},
                                 "pipeline": {"status": "failed" if red else "success"}, "merge_requests": 4, "issues": 17}),
                ("example/web", {"project": {"name": "web", "last_activity_at": stamp(7200), "web_url": web},
                                 "pipeline": {"status": "running"}, "merge_requests": 2, "issues": 9}),
                ("example/infra", {"project": {"name": "infra", "last_activity_at": stamp(86400 * 3), "web_url": web},
                                   "pipeline": {"status": "success"}, "merge_requests": 0, "issues": 3}),
            ])
        if widget_kind == "pipelines":
            return self.pipeline_rows([("example/api", [
                {"ref": "main", "status": "failed" if red else "success", "source": "push", "updated_at": stamp(900), "web_url": web},
                {"ref": "v2.4.0", "status": "success", "source": "push", "updated_at": stamp(5400), "web_url": web},
                {"ref": "feature/cache", "status": "running", "source": "push", "updated_at": stamp(120), "web_url": web},
                {"ref": "nightly", "status": "success", "source": "schedule", "updated_at": stamp(36000), "web_url": web},
            ])], int(options.get("limit") or 8))
        if widget_kind == "merge_requests":
            issues = options.get("what") == "issues"
            entries = [
                {"title": "Cache the session lookups", "references": {"short": "#58" if issues else "!58"}, "updated_at": stamp(1800),
                 "detailed_merge_status": "ci_still_running", "web_url": web},
                {"title": "Draft: Move the settings page", "draft": True, "references": {"short": "#55" if issues else "!55"}, "updated_at": stamp(7200),
                 "detailed_merge_status": "draft_status", "web_url": web},
                {"title": "Update the base image", "references": {"short": "#51" if issues else "!51"}, "updated_at": stamp(86400),
                 "detailed_merge_status": "mergeable", "web_url": web},
            ]
            return self.open_rows([("example/api", entries)], issues, int(options.get("limit") or 8), [int(fake.walk("gl-open", tick, 3, 9))])
        return self.release_rows([
            ("example/api", [{"tag_name": "v2.4.0", "released_at": stamp(86400), "description": "Faster sign-in and a new health page.", "_links": {"self": web}}]),
            ("example/web", [{"tag_name": "v1.9.2", "released_at": stamp(86400 * 4), "description": "Fixes the dark theme.", "_links": {"self": web}}]),
        ], int(options.get("limit") or 8))


ADAPTER = GitlabAdapter()
