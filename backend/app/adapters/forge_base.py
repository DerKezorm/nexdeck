"""Gitea and Forgejo: open issues, pull requests and the latest Actions jobs.

Measured on 11.09.2026 against Gitea 1.27.3 and Forgejo 13.0.5, each with a
runner that ran a green and a red workflow.

⚠️ The two forks no longer agree on ``/actions/runs``. Gitea answers the way
GitHub does (``display_title``, ``status: completed`` plus ``conclusion``,
``run_number``, newest first); Forgejo has ``title``, one ``status`` such as
``success``, ``workflow_id``, ``prettyref``, and lists the oldest first. The
cards use ``/actions/tasks`` instead, which both answered field for field the
same: one row per job with a single ``status``.

⚠️ Forgejo names itself ``13.0.5+gitea-1.22.0``. The part after the plus is
the Gitea version it forked from, not its own.
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

#: A job's state, as a colour and, where it is not plain success, a word.
JOB = {
    "success": ("ok", ""), "failure": ("bad", "Failed"), "cancelled": ("unknown", "Cancelled"),
    "skipped": ("unknown", "Skipped"), "running": ("warn", "Running"), "waiting": ("unknown", "Waiting"),
    "blocked": ("warn", "Blocked"),
}
#: How many repositories the Actions card looks into when none is named.
REPOSITORIES_TO_WATCH = 5


class ForgeAdapter(Adapter):
    """What Gitea and Forgejo share. The subclasses only name themselves."""

    category = "hosts"
    beta = False
    product = ""

    def __init__(self) -> None:
        self.fields = (
            Field("url", "URL", type="url", required=True, placeholder=f"http://{self.kind}:3000"),
            Field("token", "Access token", type="password", secret=True, required=True,
                  help="Settings > Applications > Generate new token, with read access to repositories, issues and the user."),
            Field("insecure", "Ignore TLS errors", type="bool", default=False),
        )
        self.widgets = (
            WidgetType(kind="issues", label="Open issues", description="Open issues or pull requests across your repositories, the latest first.",
                       renderer="list", default_size=(3, 3), refresh_seconds=300,
                       options=(Field("what", "Show", type="select", default="issues", options=(("issues", "Issues"), ("pulls", "Pull requests"))),
                                Field("limit", "Entries", type="number", default=8))),
            WidgetType(kind="actions", label="Actions", description="The latest jobs, red ones marked, from one repository or the most recently changed ones.",
                       renderer="list", default_size=(3, 3), refresh_seconds=120, metrics=("failing",),
                       options=(Field("repository", "Repository", placeholder="owner/name",
                                      help=f"Empty looks at the {REPOSITORIES_TO_WATCH} repositories that changed last."),
                                Field("limit", "Entries", type="number", default=8))),
            WidgetType(kind="summary", label="Repositories", description="Open issues, pull requests and how many repositories there are.",
                       renderer="value", default_size=(3, 2), refresh_seconds=300, metrics=("issues",)),
        )

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, params: dict[str, Any] | None = None,
                   cache: float = 10) -> Any:
        response = await ctx.request(
            "GET", f"{base_url(config)}/api/v1{path}", headers={"Authorization": f"token {config.get('token') or ''}"},
            params=params, verify=not config.get("insecure"), cache_seconds=cache, auth_errors=False,
        )
        # Measured: a wrong token gets 401 with a JSON message on both.
        if response.status_code == 401:
            raise AuthFailed(f"{self.product} rejected the access token.")
        return response

    async def _json(self, config: dict[str, Any], ctx: Context, path: str, params: dict[str, Any] | None = None,
                    cache: float = 10) -> tuple[Any, int | None]:
        response = await self._get(config, ctx, path, params, cache)
        if response.status_code >= 400:
            raise AdapterError(f"{self.product} answered with HTTP {response.status_code}.", code="http_error",
                               hint=f"Check the URL; it is the address of {self.product} itself, without /api.")
        try:
            answer = response.json()
        except ValueError as error:
            raise AdapterError(f"{self.product} did not answer with JSON.", code="not_json",
                               hint="The URL probably points at a login page or a reverse proxy.") from error
        total = response.headers.get("x-total-count")
        return answer, int(total) if total and total.isdigit() else None

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        version, _ = await self._json(config, ctx, "/version", cache=0)
        user, _ = await self._json(config, ctx, "/user", cache=0)
        if not isinstance(version, dict) or not isinstance(user, dict) or "login" not in user:
            raise AdapterError(f"This address answers, but not the way {self.product} does.", code="not_forge")
        number = str(version.get("version") or "?").split("+", 1)[0]
        return f"{self.product} {number} answers for {user['login']}."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "summary":
            _, issues = await self._json(config, ctx, "/repos/issues/search", {"state": "open", "type": "issues", "limit": 1})
            _, pulls = await self._json(config, ctx, "/repos/issues/search", {"state": "open", "type": "pulls", "limit": 1})
            repos, total = await self._json(config, ctx, "/user/repos", {"limit": 50})
            return self._summary(issues or 0, pulls or 0, total if total is not None else len(repos or []))
        if widget_kind == "actions":
            return await self._actions(config, options, ctx)
        what = "pulls" if options.get("what") == "pulls" else "issues"
        found, total = await self._json(config, ctx, "/repos/issues/search",
                                        {"state": "open", "type": what, "limit": int(options.get("limit") or 8)})
        if not isinstance(found, list):
            raise AdapterError(f"This address answers, but not the way {self.product} does.", code="not_forge")
        return self._issues(found, total, what)

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def _summary(issues: int, pulls: int, repositories: int) -> WidgetData:
        return WidgetData(
            status="ok",
            primary={"label": "Open issues", "value": issues},
            secondary=[{"label": "Pull requests", "value": pulls}, {"label": "Repositories", "value": repositories}],
            metrics={"issues": float(issues)},
        )

    @staticmethod
    def _issues(found: list[dict[str, Any]], total: int | None, what: str) -> WidgetData:
        items = []
        for issue in found:
            if not isinstance(issue, dict):
                continue
            repository = issue.get("repository") if isinstance(issue.get("repository"), dict) else {}
            draft = bool((issue.get("pull_request") or {}).get("draft")) if isinstance(issue.get("pull_request"), dict) else False
            place = f"{repository.get('full_name') or '?'}#{issue.get('number')}"
            items.append({
                "title": str(issue.get("title") or "?"),
                "subtitle": f"Draft · {place}" if draft else place,
                "value": ago(issue.get("updated_at")),
                "url": str(issue.get("html_url") or ""),
            })
        label = "Pull requests" if what == "pulls" else "Open issues"
        return WidgetData(
            status="ok",
            items=items,
            secondary=[{"label": label, "value": total if total is not None else len(items)}],
            meta={"empty": "No open pull requests." if what == "pulls" else "No open issues."},
        )

    async def _actions(self, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        limit = int(options.get("limit") or 8)
        named = str(options.get("repository") or "").strip().strip("/")
        if named:
            if named.count("/") != 1:
                raise AdapterError("A repository is named as owner/name.", code="bad_repository")
            watched = [named]
        else:
            repos, _ = await self._json(config, ctx, "/user/repos", {"limit": 50})
            usable = [repo for repo in repos or [] if isinstance(repo, dict) and repo.get("has_actions")
                      and not repo.get("archived") and not repo.get("empty")]
            usable.sort(key=lambda repo: str(repo.get("updated_at") or ""), reverse=True)
            watched = [str(repo.get("full_name")) for repo in usable[:REPOSITORIES_TO_WATCH]]
        jobs: list[tuple[str, dict[str, Any]]] = []
        for full_name in watched:
            response = await self._get(config, ctx, f"/repos/{full_name}/actions/tasks", {"limit": limit})
            # A repository with Actions switched off answers 404; a named one that does not exist too.
            if response.status_code == 404 and not named:
                continue
            if response.status_code >= 400:
                raise AdapterError(f"{self.product} answered with HTTP {response.status_code} for {full_name}.", code="http_error")
            try:
                answer = response.json()
            except ValueError:
                continue
            for job in (answer.get("workflow_runs") if isinstance(answer, dict) else None) or []:
                if isinstance(job, dict):
                    jobs.append((full_name, job))
        return self._jobs(jobs, limit)

    @staticmethod
    def _jobs(jobs: list[tuple[str, dict[str, Any]]], limit: int) -> WidgetData:
        jobs.sort(key=lambda entry: str(entry[1].get("created_at") or ""), reverse=True)
        latest: dict[tuple[str, str, str], str] = {}
        items = []
        for full_name, job in jobs:
            state = str(job.get("status") or "")
            latest.setdefault((full_name, str(job.get("workflow_id") or ""), str(job.get("name") or "")), state)
            colour, word = JOB.get(state, ("unknown", state.capitalize()))
            parts = (word, full_name.rsplit("/", 1)[-1], str(job.get("name") or ""))
            items.append({
                "title": str(job.get("display_title") or job.get("name") or "?"),
                "subtitle": " · ".join(part for part in parts if part),
                "status": colour,
                "value": ago(job.get("updated_at") or job.get("created_at")),
                "url": str(job.get("url") or ""),
            })
        failing = sum(1 for state in latest.values() if state == "failure")
        return WidgetData(
            status="bad" if failing else "ok",
            items=items[:limit],
            secondary=[{"label": "Failing jobs", "value": failing}],
            meta={"empty": "No Actions jobs yet."},
            metrics={"failing": float(failing)},
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        base = f"https://{self.kind}.example.com"
        red = fake.flicker(f"{self.kind}-ci", tick, 0.6)
        if widget_kind == "summary":
            return self._summary(7, 2, 23)
        if widget_kind == "actions":
            jobs = [
                ("home/compose", {"display_title": "Bump Jellyfin to 10.11.12", "name": "validate", "status": "failure" if red else "success",
                                  "workflow_id": "ci.yml", "created_at": "2026-09-11T08:40:00Z", "updated_at": fake_stamp(tick, 600), "url": f"{base}/home/compose/actions/runs/41"}),
                ("home/dotfiles", {"display_title": "Sort the shell aliases", "name": "lint", "status": "success",
                                   "workflow_id": "lint.yml", "created_at": "2026-09-11T07:10:00Z", "updated_at": fake_stamp(tick, 5400), "url": f"{base}/home/dotfiles/actions/runs/12"}),
                ("home/website", {"display_title": "New post about backups", "name": "deploy", "status": "success",
                                  "workflow_id": "deploy.yml", "created_at": "2026-09-10T21:00:00Z", "updated_at": fake_stamp(tick, 43200), "url": f"{base}/home/website/actions/runs/88"}),
            ]
            return self._jobs(jobs, int(options.get("limit") or 8))
        issues = [
            {"title": "Renew the certificate before it runs out", "number": 14, "repository": {"full_name": "home/compose"}, "updated_at": fake_stamp(tick, 3600), "html_url": f"{base}/home/compose/issues/14"},
            {"title": "Move backups to the new NAS", "number": 9, "repository": {"full_name": "home/compose"}, "updated_at": fake_stamp(tick, 86400), "html_url": f"{base}/home/compose/issues/9"},
            {"title": "Sort the shell aliases", "number": 3, "repository": {"full_name": "home/dotfiles"}, "updated_at": fake_stamp(tick, 3 * 86400), "html_url": f"{base}/home/dotfiles/issues/3"},
        ]
        return self._issues(issues, 7, str(options.get("what") or "issues"))


def fake_stamp(tick: int, seconds_ago: int) -> str:
    """An ISO moment for the demo."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - seconds_ago - tick % 60))
