"""GitHub: releases, open issues and pull requests, and the latest workflow runs.

Public repositories are readable without a key, sixty requests an hour per
address. A connection with a personal access token raises that to five
thousand and reaches the private repositories the token may read; the cards
work with or without one.

Every answer is kept with its ETag and asked for again with If-None-Match.
An unchanged answer comes back as 304 without a body, and with a token it
does not count against the limit at all. Measured on 22.09.2026: without a
token it does count, one request like any other, so there the ETag saves the
download and not the request. What the limit says is read from
every answer: when only a few requests are left, the cards show what they
have and wait for the reset instead of spending the last ones, and when the
limit is used up they say until when, with the last answer still on show.

Three cards read more than the list of a project's issues:

- The repository card needs the repository (stars, forks, ``open_issues_count``
  with the pull requests in it), the newest release and, for the pull requests
  alone, one search request: ``/search/issues`` with ``is:pr is:open`` and
  ``per_page=1`` gives ``total_count``, and the issues are the difference.
- The pull request card asks, for each pull request shown, ``check-runs`` of
  its head commit. Measured on 28.10.2026 against two public projects: a
  project with no CI on a pull request answers ``total_count: 0``, and the
  combined ``/status`` of such a commit then says ``"state": "pending"`` with
  ``total_count: 0``. That is *no checks*, not *running*, so a card has to read
  the count and not the word.
- The milestone card reads ``/milestones?state=open&sort=due_on``: ``open_issues``,
  ``closed_issues`` and ``due_on``, which is often null.

What GitHub documents and this relies on: it sends ``x-ratelimit-remaining``,
``-limit`` and ``-reset`` (epoch seconds) on every answer, including 304 and
403, and answers a used-up limit with 403 or 429.
"""

from __future__ import annotations

import json
import math
import re
import time
from datetime import datetime
from typing import Any

from .base import Adapter, AdapterError, AuthFailed, Context, Field, WidgetData, WidgetType, ago

API = "https://api.github.com"

#: Ready-made sets of the projects a home server usually runs.
PRESETS = {
    "media": "jellyfin/jellyfin\nRadarr/Radarr\nSonarr/Sonarr\nsabnzbd/sabnzbd",
    "infrastructure": "home-assistant/core\nNginxProxyManager/nginx-proxy-manager\npi-hole/pi-hole\nAdguardTeam/AdGuardHome",
    "nexapps": "DerKezorm/nexdeck\nDerKezorm/nexview\nDerKezorm/nexmail",
    "": "",
}
PRESET_OPTIONS = (
    ("media", "Media and downloads"),
    ("infrastructure", "Infrastructure"),
    ("nexapps", "nexapps"),
    ("", "Own list only"),
)

#: Where the answers and the limit are kept, in the connection's memory.
ETAGS = "github:etags"
LIMIT = "github:limit"
#: The search has a limit of its own, ten a minute without a token and thirty with.
SEARCH_LIMIT = "github:limit:search"
#: How many answers are kept; enough for ten projects on every card.
KEPT = 300
#: Requests held back for when they matter: below this the cards live on
#: what they have until the limit resets.
RESERVE = 5

#: A run's state, as a colour and, where it is not plain success, a word.
RUN = {
    "success": ("ok", ""), "failure": ("bad", "Failed"), "timed_out": ("bad", "Timed out"), "cancelled": ("unknown", "Cancelled"),
    "skipped": ("unknown", "Skipped"), "action_required": ("warn", "Needs approval"), "neutral": ("ok", ""),
    "in_progress": ("warn", "Running"), "queued": ("unknown", "Queued"), "waiting": ("unknown", "Waiting"), "pending": ("unknown", "Waiting"),
}

REPOS_FIELD = Field("repos", "Projects", type="textarea", required=True, placeholder="owner/name",
                    help="One per line, as owner/name. At most ten.")


class RateLimited(AdapterError):
    pass


def _is_repo(text: str) -> bool:
    """``owner/name`` in the characters GitHub allows, and neither part ``.`` or ``..``.

    ⚠️ httpx puts ``/repos/../x`` right before it sends it and the request goes to ``/x``.
    """
    return bool(re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", text)) and not any(part in (".", "..") for part in text.split("/"))


class GithubAdapter(Adapter):
    raw_root = API
    kind = "github"
    label = "GitHub"
    category = "feeds"
    description = "Releases, open issues and pull requests, and the latest workflow runs of the projects you follow."
    icon = "github"
    docs_url = "https://docs.github.com/en/rest"
    #: Out of beta on 22.09.2026: every card run against the real API.
    beta = False
    needs_integration = False
    optional_integration = True
    fields = (
        Field("token", "Personal access token", type="password", secret=True,
              help="This connection carries only the token; which projects are shown is set on each card. Optional: a fine-grained token with read access raises the limit from 60 to 5,000 requests an hour and reaches private repositories."),
    )
    widgets = (
        WidgetType(
            kind="releases",
            label="Releases",
            description="One line per project with its newest version and when it came.",
            renderer="feed",
            default_size=(4, 4),
            refresh_seconds=1800,
            options=(
                Field("preset", "Ready-made set", type="select", default="media", options=PRESET_OPTIONS),
                Field("repos", "Own projects", type="textarea", placeholder="owner/name",
                      help="One per line, as owner/name. Replaces the ready-made set."),
                Field("limit", "Entries", type="number", default=8),
                Field("prereleases", "Include pre-releases", type="bool", default=False),
            ),
        ),
        WidgetType(
            kind="issues",
            label="Issues and pull requests",
            description="What is open in the projects you follow, the latest changed first. Pull requests say whether they are drafts or wait for a review.",
            renderer="list",
            default_size=(4, 3),
            min_size=(3, 2),
            refresh_seconds=600,
            options=(
                REPOS_FIELD,
                Field("what", "Show", type="select", default="issues", options=(("issues", "Issues"), ("pulls", "Pull requests"))),
                Field("limit", "Entries", type="number", default=8),
            ),
        ),
        WidgetType(
            kind="repository",
            label="Repository",
            description="One project: stars, forks, open issues and open pull requests, the newest release and the last push.",
            renderer="stats",
            default_size=(3, 2),
            refresh_seconds=1800,
            metrics=("stars", "issues", "pulls"),
            options=(Field("repo", "Project", required=True, placeholder="owner/name"),),
        ),
        WidgetType(
            kind="pulls",
            label="Pull requests",
            description="Open pull requests of the projects you follow, with the state of their checks: failed, running or passed. Red ones first.",
            renderer="list",
            default_size=(4, 3),
            min_size=(3, 2),
            refresh_seconds=900,
            metrics=("failing",),
            options=(
                REPOS_FIELD,
                Field("limit", "Entries", type="number", default=6,
                      help="Each pull request shown costs one more request for its checks; without a token GitHub allows sixty an hour."),
                Field("drafts", "Show drafts", type="bool", default=True),
            ),
        ),
        WidgetType(
            kind="milestones",
            label="Milestones",
            description="Open milestones with how much of each is done and when it is due, overdue ones first.",
            renderer="list",
            default_size=(4, 3),
            min_size=(3, 2),
            refresh_seconds=1800,
            metrics=("overdue",),
            options=(REPOS_FIELD, Field("limit", "Entries", type="number", default=8)),
        ),
        WidgetType(
            kind="runs",
            label="Workflow runs",
            description="The latest run of every workflow, red ones first.",
            renderer="list",
            default_size=(4, 3),
            min_size=(3, 2),
            refresh_seconds=300,
            metrics=("failing",),
            options=(REPOS_FIELD, Field("limit", "Entries", type="number", default=8)),
        ),
    )

    def default_link(self, config: dict[str, Any]) -> str:
        return "https://github.com/"

    # -- asking GitHub --------------------------------------------------------

    @staticmethod
    def _limit_word(reset: float) -> str:
        minutes = max(1, round((reset - time.time()) / 60))
        return f"in {minutes} min" if minutes < 90 else f"in {round(minutes / 60)} h"

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, params: dict[str, Any] | None = None) -> tuple[Any, float | None]:
        """One answer, and the moment it was fetched when it is an old one shown for want of a new.

        None for a 404: a project without releases or without Actions is not a fault.
        """
        token = str(config.get("token") or "").strip()
        answers: dict[str, tuple[str, Any, float]] = ctx.cache.setdefault(ETAGS, {})
        key = json.dumps([path, params], sort_keys=True)
        held = answers.get(key)
        where = SEARCH_LIMIT if path.startswith("/search/") else LIMIT
        limit = ctx.cache.get(where)
        if limit and limit["remaining"] <= (1 if where == SEARCH_LIMIT else RESERVE) and time.time() < limit["reset"]:
            if held:
                return held[1], held[2]
            raise self._used_up(limit["reset"], bool(token))
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if held:
            headers["If-None-Match"] = held[0]
        response = await ctx.request("GET", f"{API}{path}", headers=headers, params=params, timeout=20, auth_errors=False)
        remaining, reset = response.headers.get("x-ratelimit-remaining"), response.headers.get("x-ratelimit-reset")
        if remaining is not None and remaining.isdigit() and reset is not None and reset.isdigit():
            ctx.cache[where] = {"remaining": int(remaining), "reset": float(reset), "limit": int(response.headers.get("x-ratelimit-limit") or 0)}
        if response.status_code == 304 and held:
            answers[key] = (held[0], held[1], time.time())
            return held[1], None
        if response.status_code in (403, 429) and (remaining == "0" or "rate limit" in response.text.lower()):
            if held:
                return held[1], held[2]
            raise self._used_up(float(reset) if reset and reset.isdigit() else time.time() + 3600, bool(token))
        if response.status_code == 401:
            failure = AuthFailed("GitHub rejected the token.")
            failure.hint = "A fine-grained token needs read access to the repositories; a classic one needs no scope for public ones."
            raise failure
        if response.status_code == 404:
            return None, None
        if response.status_code >= 400:
            raise AdapterError(f"GitHub answered with HTTP {response.status_code}.", code="http_error")
        payload = response.json()
        etag = response.headers.get("etag")
        if etag:
            if len(answers) >= KEPT:
                # The oldest goes; a dict keeps the order things came in.
                answers.pop(next(iter(answers)))
            answers[key] = (etag, payload, time.time())
        return payload, None

    def _used_up(self, reset: float, with_token: bool) -> RateLimited:
        return RateLimited(
            f"GitHub's hourly limit is used up; it resets {self._limit_word(reset)}.",
            code="rate_limited",
            hint="A connection with a personal access token raises the limit from 60 to 5,000 an hour." if not with_token
            else "Follow fewer projects or give the cards a longer interval.",
        )

    async def newest_release(self, config: dict[str, Any], ctx: Context, repo: str) -> dict[str, Any] | None:
        """The newest release of one project, for a card that gathers from several places.

        Through the same ETags and the same rate limit as the cards here, so a
        project asked for on two cards costs one request. None when the
        project has no release.
        """
        answer, _old = await self._get(config, ctx, f"/repos/{repo}/releases/latest")
        if not isinstance(answer, dict):
            return None
        return {
            "tag": str(answer.get("tag_name") or answer.get("name") or "?"),
            "url": str(answer.get("html_url") or f"https://github.com/{repo}/releases"),
            "published": self._stamp(answer.get("published_at") or answer.get("created_at") or ""),
            "prerelease": bool(answer.get("prerelease")),
        }

    @staticmethod
    def _repos(options: dict[str, Any], presets: bool) -> list[str]:
        own = [line.strip().strip("/") for line in str(options.get("repos") or "").splitlines() if line.strip()]
        if own or not presets:
            return own[:10]
        preset = PRESETS.get(str(options.get("preset") or "media"), "")
        return [line for line in preset.splitlines() if line][:10]

    @staticmethod
    def _stamp(text: str) -> int | None:
        try:
            return int(datetime.fromisoformat(str(text).replace("Z", "+00:00")).timestamp())
        except ValueError:
            return None

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        """What the connection is good for: the requests it has this hour.

        ⚠️ Asked of /rate_limit, which GitHub does not count. The test used to
        fetch nexdeck's own latest release, and "nexdeck is at v0.16.1" read as
        if something had been set up that nobody had set up. The projects are
        chosen on each card; the connection only carries the token.
        """
        token = str(config.get("token") or "").strip()
        answer, _ = await self._get(config, ctx, "/rate_limit")
        core = ((answer or {}).get("resources") or {}).get("core") or {}
        left, of = core.get("remaining", "?"), core.get("limit", "?")
        if token:
            user, _ = await self._get(config, ctx, "/user")
            return f"GitHub accepts the token of {(user or {}).get('login', '?')}: {left} of {of} requests left this hour."
        return f"GitHub answers without a token: {left} of {of} requests left this hour. The projects are chosen on each card."

    # -- the cards --------------------------------------------------------------

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "repository":
            return await self._repository(config, options, ctx)
        if widget_kind == "pulls":
            return await self._pulls(config, options, ctx)
        if widget_kind == "milestones":
            return await self._milestones(config, options, ctx)
        repos = self._repos(options, presets=widget_kind == "releases")
        if not repos:
            raise AdapterError("No project is set.", code="missing_repo")
        bad = [repo for repo in repos if repo.count("/") != 1]
        if bad:
            raise AdapterError(f"{bad[0]} is not owner/name.", code="bad_repository")
        limit = max(1, min(20, int(options.get("limit") or 8)))
        failures: list[str] = []
        stale: list[float] = []
        found: list[tuple[str, Any]] = []
        pulls = options.get("what") == "pulls"
        total: int | None = None
        if widget_kind == "issues":
            # ⚠️ Through the search, not the repository's issue list. That list
            # carries the pull requests too, the last changed first: measured on
            # seerr-team/seerr, the eight newest were all pull requests, so the
            # card said "no open issues" of 250. The search asks for issues
            # alone, for every project in one request, and says how many there are.
            query = " ".join(f"repo:{repo}" for repo in repos) + (" is:pr" if pulls else " is:issue") + " is:open"
            try:
                answer, old = await self._get(config, ctx, "/search/issues", {"q": query, "sort": "updated", "order": "desc", "per_page": limit})
                total = int((answer or {}).get("total_count") or 0)
                if old:
                    stale.append(old)
                if not pulls:
                    for item in (answer or {}).get("items") or []:
                        if isinstance(item, dict):
                            found.append((str(item.get("repository_url") or "").split("/repos/", 1)[-1], [item]))
            except RateLimited:
                if not pulls:
                    raise
        for repo in repos if widget_kind != "issues" or pulls else []:
            try:
                if widget_kind == "issues":
                    # Pull requests from their own list, which says whether a review is asked for.
                    answer, old = await self._get(config, ctx, f"/repos/{repo}/pulls",
                                                  {"state": "open", "sort": "updated", "direction": "desc", "per_page": limit})
                elif widget_kind == "runs":
                    # ⚠️ Without the runs of pull requests. Measured on jellyfin/jellyfin:
                    # a failed test on somebody's pull request branch made the whole
                    # card red, though the project itself was green.
                    answer, old = await self._get(config, ctx, f"/repos/{repo}/actions/runs", {"per_page": 20, "exclude_pull_requests": "true"})
                else:
                    prereleases = bool(options.get("prereleases"))
                    path = f"/repos/{repo}/releases" if prereleases else f"/repos/{repo}/releases/latest"
                    answer, old = await self._get(config, ctx, path, {"per_page": 1} if prereleases else None)
            except (RateLimited, AuthFailed):
                # Neither is about one project: every line would say the same.
                raise
            except AdapterError as error:
                failures.append(f"{repo}: {error.message}")
                continue
            if old:
                stale.append(old)
            found.append((repo, answer))
        if widget_kind == "issues":
            data = self._issues(found, pulls, limit, total)
        elif widget_kind == "runs":
            data = self._runs(found, limit)
        else:
            data = self._releases(found, limit)
        data.meta = {**(data.meta or {}), "failures": failures}
        if stale:
            # Shown with the card's own words for an old answer.
            data.meta["stale_since"] = int(min(stale))
        if failures and not data.items:
            data.error = "; ".join(failures)
            data.status = "bad"
        return data

    # -- repository, pull requests with their checks, milestones ---------------------------

    def _named(self, options: dict[str, Any]) -> list[str]:
        repos = self._repos(options, presets=False)
        if not repos:
            raise AdapterError("No project is set.", code="missing_repo")
        bad = [repo for repo in repos if not _is_repo(repo)]
        if bad:
            raise AdapterError(f"{bad[0]} is not owner/name.", code="bad_repository")
        return repos

    async def _repository(self, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        repo = str(options.get("repo") or "").strip().strip("/")
        if not _is_repo(repo):
            raise AdapterError(f"{repo or 'The project'} is not owner/name.", code="bad_repository")
        project, _old = await self._get(config, ctx, f"/repos/{repo}")
        if not isinstance(project, dict):
            raise AdapterError(f"{repo} was not found, or the token cannot see it.", code="not_found")
        release, _ = await self._get(config, ctx, f"/repos/{repo}/releases/latest")
        pulls: int | None = 0
        if int(project.get("open_issues_count") or 0) > 0:
            try:
                found, _ = await self._get(config, ctx, "/search/issues", {"q": f"repo:{repo} is:pr is:open", "per_page": 1})
                pulls = int((found or {}).get("total_count") or 0)
            except RateLimited:
                # The search has a limit of its own; the number of issues and pull requests together is still true.
                pulls = None
        return self.repository_card(project, release if isinstance(release, dict) else None, pulls)

    @staticmethod
    def repository_card(project: dict[str, Any], release: dict[str, Any] | None, pulls: int | None) -> WidgetData:
        both = int(project.get("open_issues_count") or 0)
        secondary: list[dict[str, Any]] = [{"label": "Project", "value": str(project.get("full_name") or "?")},
                                           {"label": "Forks", "value": int(project.get("forks_count") or 0)}]
        if pulls is None:
            secondary.append({"label": "Open issues and pull requests", "value": both})
        else:
            secondary += [{"label": "Open issues", "value": max(0, both - pulls)}, {"label": "Open pull requests", "value": pulls}]
        secondary.append({"label": "Latest release", "value": str(release.get("tag_name") or release.get("name") or "?") if release else "None"})
        if release and release.get("published_at"):
            secondary.append({"label": "Released", "value": ago(release.get("published_at"))})
        if project.get("pushed_at"):
            secondary.append({"label": "Last push", "value": ago(project.get("pushed_at"))})
        if project.get("archived"):
            secondary.append({"label": "Archived", "value": "Yes"})
        return WidgetData(
            status="warn" if project.get("archived") else "ok",
            primary={"label": "Stars", "value": int(project.get("stargazers_count") or 0)},
            secondary=secondary,
            metrics={"stars": float(project.get("stargazers_count") or 0), "issues": float(max(0, both - (pulls or 0))), "pulls": float(pulls or 0)},
            link=str(project.get("html_url") or "") or None,
        )

    async def _checks(self, config: dict[str, Any], ctx: Context, repo: str, sha: str) -> str:
        """``bad``, ``running``, ``approval``, ``ok`` or ``none`` for the head commit of a pull request."""
        if not re.fullmatch(r"[0-9a-f]{7,64}", sha):
            return "none"
        runs, _ = await self._get(config, ctx, f"/repos/{repo}/commits/{sha}/check-runs", {"per_page": 100})
        listed = [one for one in runs.get("check_runs") or [] if isinstance(one, dict)] if isinstance(runs, dict) else []
        if listed:
            if any(one.get("conclusion") in ("failure", "timed_out", "startup_failure") for one in listed):
                return "bad"
            if any(one.get("conclusion") == "action_required" for one in listed):
                return "approval"
            if any(one.get("status") != "completed" for one in listed):
                return "running"
            return "ok"
        status, _ = await self._get(config, ctx, f"/repos/{repo}/commits/{sha}/status")
        # ⚠️ A commit with no statuses at all answers state "pending": it is the count that says none.
        if not isinstance(status, dict) or not int(status.get("total_count") or 0):
            return "none"
        return {"success": "ok", "failure": "bad", "error": "bad"}.get(str(status.get("state")), "running")

    async def _pulls(self, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        repos = self._named(options)
        limit = max(1, min(15, int(options.get("limit") or 6)))
        failures: list[str] = []
        stale: list[float] = []
        every: list[tuple[str, dict[str, Any]]] = []
        full = False
        for repo in repos:
            try:
                answer, old = await self._get(config, ctx, f"/repos/{repo}/pulls", {"state": "open", "sort": "updated", "direction": "desc", "per_page": limit})
            except (RateLimited, AuthFailed):
                raise
            except AdapterError as error:
                failures.append(f"{repo}: {error.message}")
                continue
            if old:
                stale.append(old)
            if answer is None:
                failures.append(f"{repo}: not found, or not visible to this token")
                continue
            full = full or len(answer) >= limit
            every += [(repo, one) for one in answer if isinstance(one, dict) and (options.get("drafts", True) or not one.get("draft"))]
        every.sort(key=lambda entry: str(entry[1].get("updated_at") or ""), reverse=True)
        shown = every[:limit]
        checks: dict[tuple[str, int], str] = {}
        limited = False
        for repo, pull in shown:
            try:
                checks[(repo, int(pull.get("number") or 0))] = await self._checks(config, ctx, repo, str((pull.get("head") or {}).get("sha") or ""))
            except RateLimited:
                # What is known stays on the card; the rest waits for the reset.
                limited = True
                break
            except AuthFailed:
                raise
            except AdapterError:
                continue
        data = self.pull_rows(shown, checks, full or len(every) > len(shown))
        data.meta = {**(data.meta or {}), "failures": failures, **({"checks_limited": True} if limited else {})}
        if stale:
            data.meta["stale_since"] = int(min(stale))
        if failures and not data.items:
            data.error = "; ".join(failures)
            data.status = "bad"
        return data

    @staticmethod
    def pull_rows(shown: list[tuple[str, dict[str, Any]]], checks: dict[tuple[str, int], str], more: bool = False) -> WidgetData:
        words = {"bad": ("bad", "Checks failed"), "running": ("warn", "Checks running"), "approval": ("warn", "Needs approval"),
                 "ok": ("ok", "Checks passed"), "none": ("unknown", "No checks")}
        rows = []
        for repo, pull in shown:
            colour, word = words[checks.get((repo, int(pull.get("number") or 0)), "none")]
            review = "Draft" if pull.get("draft") else ("Review requested" if pull.get("requested_reviewers") or pull.get("requested_teams") else "")
            rows.append((colour != "bad", str(pull.get("updated_at") or ""), {
                "title": str(pull.get("title") or "?"),
                "subtitle": " · ".join(part for part in (word, review, f"{repo.rsplit('/', 1)[-1]}#{pull.get('number')}") if part),
                "status": colour,
                "value": ago(pull.get("updated_at")),
                "url": str(pull.get("html_url") or ""),
            }))
        # Red first, then the most recently changed.
        rows.sort(key=lambda row: row[1], reverse=True)
        rows.sort(key=lambda row: row[0])
        failing = sum(1 for entry in rows if not entry[0])
        return WidgetData(
            status="bad" if failing else "ok",
            items=[entry[2] for entry in rows],
            secondary=[{"label": "Failing checks", "value": failing}, {"label": "Open pull requests", "value": f"{len(rows)}+" if more else len(rows)}],
            metrics={"failing": float(failing)},
            meta={"empty": "No open pull requests."},
        )

    async def _milestones(self, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        repos = self._named(options)
        failures: list[str] = []
        stale: list[float] = []
        found: list[tuple[str, Any]] = []
        for repo in repos:
            try:
                answer, old = await self._get(config, ctx, f"/repos/{repo}/milestones", {"state": "open", "sort": "due_on", "direction": "asc", "per_page": 20})
            except (RateLimited, AuthFailed):
                raise
            except AdapterError as error:
                failures.append(f"{repo}: {error.message}")
                continue
            if old:
                stale.append(old)
            if answer is None:
                failures.append(f"{repo}: not found, or not visible to this token")
                continue
            found.append((repo, answer))
        data = self.milestone_rows(found, max(1, min(30, int(options.get("limit") or 8))))
        data.meta = {**(data.meta or {}), "failures": failures}
        if stale:
            data.meta["stale_since"] = int(min(stale))
        if failures and not data.items:
            data.error = "; ".join(failures)
            data.status = "bad"
        return data

    @classmethod
    def milestone_rows(cls, found: list[tuple[str, Any]], limit: int, now: float | None = None) -> WidgetData:
        moment = now if now is not None else time.time()
        rows = []
        for repo, milestones in found:
            for milestone in milestones if isinstance(milestones, list) else []:
                if not isinstance(milestone, dict):
                    continue
                done, left = int(milestone.get("closed_issues") or 0), int(milestone.get("open_issues") or 0)
                total = done + left
                share = 100 * done / total if total else 0.0
                due = cls._stamp(milestone.get("due_on") or "")
                days = None if due is None else math.floor((due - moment) / 86400)
                late = days is not None and days < 0 and left > 0
                soon = days is not None and 0 <= days <= 7 and left > 0
                parts = (f"{done} of {total} done" if total else "No issues yet",
                         "" if days is None else (f"overdue by {-days} d" if late else ("due today" if days == 0 else f"due in {days} d")))
                rows.append((not late, not soon, due if due is not None else float("inf"), {
                    "title": f"{repo.rsplit('/', 1)[-1]} {milestone.get('title') or '?'}",
                    "subtitle": " · ".join(part for part in parts if part),
                    "status": "bad" if late else ("warn" if soon else "ok"),
                    "value": f"{share:.0f}%",
                    "progress": round(share, 1),
                    "url": str(milestone.get("html_url") or ""),
                }))
        rows.sort(key=lambda entry: entry[:3])
        overdue = sum(1 for entry in rows if not entry[0])
        return WidgetData(
            status="bad" if overdue else "ok",
            items=[entry[3] for entry in rows[:limit]],
            secondary=[{"label": "Overdue", "value": overdue}, {"label": "Open milestones", "value": len(rows)}],
            metrics={"overdue": float(overdue)},
            meta={"empty": "No open milestones."},
        )

    def _releases(self, found: list[tuple[str, Any]], limit: int) -> WidgetData:
        entries = []
        for repo, payload in found:
            release = (payload[0] if payload else None) if isinstance(payload, list) else payload
            if not isinstance(release, dict):
                continue
            name = str(release.get("tag_name") or release.get("name") or "?")
            notes = str(release.get("body") or "").strip().splitlines()
            entries.append({
                "title": f"{repo.split('/')[-1]} {name}",
                "url": release.get("html_url") or f"https://github.com/{repo}/releases",
                "source": repo + (" · pre-release" if release.get("prerelease") else ""),
                "published": self._stamp(release.get("published_at") or release.get("created_at") or ""),
                "summary": (notes[0][:280] if notes else ""),
                "image": "",
            })
        entries.sort(key=lambda entry: entry["published"] or 0, reverse=True)
        return WidgetData(status="ok" if entries else "warn", items=entries[:limit], meta={"style": "list"})

    @staticmethod
    def _issues(found: list[tuple[str, Any]], pulls: bool, limit: int, total: int | None = None) -> WidgetData:
        rows = []
        # Without a count from the search, a full page means there may be more.
        more = False
        for repo, payload in found:
            more = more or (isinstance(payload, list) and len(payload) >= limit)
            for issue in payload or []:
                if not isinstance(issue, dict) or (not pulls and "pull_request" in issue):
                    continue
                place = f"{repo.rsplit('/', 1)[-1]}#{issue.get('number')}"
                state = ""
                if pulls:
                    state = "Draft" if issue.get("draft") else ("Review requested" if issue.get("requested_reviewers") or issue.get("requested_teams") else "")
                rows.append((str(issue.get("updated_at") or ""), {
                    "title": str(issue.get("title") or "?"),
                    "subtitle": " · ".join(part for part in (state, place) if part),
                    "value": ago(issue.get("updated_at")),
                    "url": str(issue.get("html_url") or ""),
                }))
        rows.sort(key=lambda row: row[0], reverse=True)
        return WidgetData(
            status="ok",
            items=[row for _updated, row in rows[:limit]],
            # ⚠️ Only what was fetched is counted. Measured on jellyfin/jellyfin:
            # the card said "2 open issues" of several hundred, because it
            # counted the one page it had asked for.
            secondary=[{"label": "Pull requests" if pulls else "Open issues",
                        "value": total if total is not None else (f"{len(rows)}+" if more else len(rows))}],
            meta={"empty": "No open pull requests." if pulls else "No open issues."},
        )

    @staticmethod
    def _runs(found: list[tuple[str, Any]], limit: int) -> WidgetData:
        latest = []
        for repo, payload in found:
            seen: set[Any] = set()
            # Newest first; the first run of each workflow is its latest.
            for run in (payload or {}).get("workflow_runs") or [] if isinstance(payload, dict) else []:
                if not isinstance(run, dict) or run.get("workflow_id") in seen:
                    continue
                seen.add(run.get("workflow_id"))
                latest.append((repo, run))
        rows = []
        for repo, run in latest:
            state = str(run.get("conclusion") or run.get("status") or "")
            colour, word = RUN.get(state, ("unknown", state.replace("_", " ").capitalize()))
            parts = (word, repo.rsplit("/", 1)[-1], str(run.get("name") or ""))
            rows.append((colour, str(run.get("updated_at") or ""), {
                "title": str(run.get("display_title") or run.get("name") or "?"),
                "subtitle": " · ".join(part for part in parts if part),
                "status": colour,
                "value": ago(run.get("updated_at") or run.get("created_at")),
                "url": str(run.get("html_url") or ""),
            }))
        # Red first, then by time.
        rows.sort(key=lambda row: row[1], reverse=True)
        rows.sort(key=lambda row: row[0] != "bad")
        failing = sum(1 for colour, _t, _r in rows if colour == "bad")
        return WidgetData(
            status="bad" if failing else "ok",
            items=[row for _c, _t, row in rows[:limit]],
            secondary=[{"label": "Failing workflows", "value": failing}],
            meta={"empty": "No workflow runs yet."},
            metrics={"failing": float(failing)},
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        now = time.time() - tick % 60
        stamp = lambda seconds: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - seconds))  # noqa: E731
        if widget_kind == "repository":
            return self.repository_card(
                {"full_name": "example/project", "stargazers_count": 1840 + tick // 120, "forks_count": 92, "open_issues_count": 31, "pushed_at": stamp(5400),
                 "html_url": "https://github.com/"}, {"tag_name": "v1.4.0", "published_at": stamp(86400 * 6)}, 9)
        if widget_kind == "pulls":
            red = (tick // 300) % 3 == 0
            pulls = [
                ("example/project", {"number": 412, "title": "Cards keep their size when moved", "updated_at": stamp(1800), "html_url": "https://github.com/",
                                     "requested_reviewers": [{"login": "someone"}]}),
                ("example/project", {"number": 398, "title": "Import from Homepage", "updated_at": stamp(7200), "html_url": "https://github.com/", "draft": True}),
                ("example/project", {"number": 377, "title": "Weather card shows the wrong unit", "updated_at": stamp(86400), "html_url": "https://github.com/"}),
                ("example/project", {"number": 371, "title": "Update the base image", "updated_at": stamp(172800), "html_url": "https://github.com/"}),
            ]
            checks = {("example/project", 412): "bad" if red else "ok", ("example/project", 398): "none", ("example/project", 377): "running",
                      ("example/project", 371): "approval"}
            return self.pull_rows(pulls, checks)
        if widget_kind == "milestones":
            return self.milestone_rows([("example/project", [
                {"title": "1.5.0", "closed_issues": 14, "open_issues": 6, "due_on": stamp(-3 * 86400), "html_url": "https://github.com/"},
                {"title": "1.4.1", "closed_issues": 5, "open_issues": 2, "due_on": stamp(2 * 86400), "html_url": "https://github.com/"},
                {"title": "2.0.0", "closed_issues": 3, "open_issues": 21, "due_on": None, "html_url": "https://github.com/"}])], 8, now)
        if widget_kind == "issues":
            pulls = options.get("what") == "pulls"
            items = [
                {"title": "Cards keep their size when moved", "number": 412, "updated_at": stamp(1800), "html_url": "https://github.com/",
                 "draft": False, "requested_reviewers": [{"login": "someone"}]},
                {"title": "Import from Homepage", "number": 398, "updated_at": stamp(7200), "html_url": "https://github.com/", "draft": True},
                {"title": "Weather card shows the wrong unit", "number": 377, "updated_at": stamp(86400), "html_url": "https://github.com/"},
            ]
            return self._issues([("example/project", items)], pulls, int(options.get("limit") or 8))
        if widget_kind == "runs":
            red = (tick // 300) % 3 == 0
            runs = {"workflow_runs": [
                {"workflow_id": 1, "name": "CI", "display_title": "Release 1.4.0", "status": "completed", "conclusion": "failure" if red else "success", "updated_at": stamp(900), "html_url": "https://github.com/"},
                {"workflow_id": 2, "name": "Docker image", "display_title": "Release 1.4.0", "status": "in_progress", "conclusion": None, "updated_at": stamp(120), "html_url": "https://github.com/"},
                {"workflow_id": 3, "name": "CodeQL", "display_title": "Weekly scan", "status": "completed", "conclusion": "success", "updated_at": stamp(86400), "html_url": "https://github.com/"},
            ]}
            return self._runs([("example/project", runs)], int(options.get("limit") or 8))
        releases = [
            ("jellyfin 10.11.12", "jellyfin/jellyfin", "Fixes trickplay on ARM devices."),
            ("Radarr 6.3.1", "Radarr/Radarr", "Improved import matching for collections."),
            ("core 2026.9.1", "home-assistant/core", "New energy dashboard cards."),
            ("Sonarr 4.0.20", "Sonarr/Sonarr", "Season pack handling reworked."),
            ("pi-hole 6.4.4", "pi-hole/pi-hole", "Faster gravity rebuilds."),
            ("nexdeck 0.1.0", "DerKezorm/nexdeck", "First release."),
        ]
        start = tick // 150
        items = []
        for index in range(min(len(releases), max(1, min(20, int(options.get("limit") or 8))))):
            title, repo, note = releases[(start + index) % len(releases)]
            items.append({"title": title, "url": "https://github.com/", "source": repo, "published": 1788600000 - index * 86400 - tick,
                          "summary": note, "image": ""})
        return WidgetData(items=items, meta={"style": "list", "failures": []})


ADAPTER = GithubAdapter()
