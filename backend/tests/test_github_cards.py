"""GitHub: the repository, pull request and milestone cards, against the real API.

``fixtures/github_cards.json`` was recorded on 28.10.2026 from two public
projects without a token: ``/repos/<project>``, ``releases/latest``, the
search count of open pull requests, the open pull requests with the
``check-runs`` of their head commits, the combined ``status`` of a commit with
no statuses (``"state": "pending"`` and ``total_count: 0``, which is no checks
and not running checks), the status of a commit that has one (recorded for a commit that also
had check runs, and used here for a commit that has none: the path for a project that reports
statuses only), and the open milestones. People are taken out, the
projects are renamed to example/project and example/web, and a commit id is
written ``@sha0`` in the file and made here (forty hex characters in a row are
what the commit hook takes for a key).
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, Context, outbound_client

API = "https://api.github.com"
GITHUB = get_adapter("github")


def sha(name: str) -> str:
    return hashlib.sha1(name.encode()).hexdigest()


CARDS = json.loads(re.sub(r"@sha(\d+)", lambda found: sha(found.group(1)), (Path(__file__).parent / "fixtures" / "github_cards.json").read_text(encoding="utf-8")))
FIRST, SECOND, THIRD = (sha(str(n)) for n in range(3))


@pytest.fixture
def ctx() -> Context:
    return Context(outbound_client(guard=False), integration_id=None, widget_id=1, cache={})


def fresh() -> Context:
    return Context(outbound_client(guard=False), integration_id=None, widget_id=2, cache={})


def limit(remaining: int = 50) -> dict[str, str]:
    return {"x-ratelimit-remaining": str(remaining), "x-ratelimit-limit": "60", "x-ratelimit-reset": str(int(time.time() + 1800))}


def project() -> None:
    respx.get(f"{API}/repos/example/project").mock(return_value=httpx.Response(200, json=CARDS["repo"], headers=limit()))
    respx.get(f"{API}/repos/example/project/releases/latest").mock(return_value=httpx.Response(200, json=CARDS["release"], headers=limit()))
    respx.get(f"{API}/search/issues").mock(return_value=httpx.Response(200, json=CARDS["search_prs"], headers=limit(8)))


def pulls(check_runs: dict[str, dict] | None = None, status: dict[str, dict] | None = None) -> None:
    respx.get(f"{API}/repos/example/web/pulls").mock(return_value=httpx.Response(200, json=CARDS["pulls"], headers=limit()))
    runs = check_runs or {FIRST: CARDS["checks"]["5918"]["check_runs"], SECOND: {"total_count": 0, "check_runs": []}, THIRD: {"total_count": 0, "check_runs": []}}
    for head, answer in runs.items():
        respx.get(f"{API}/repos/example/web/commits/{head}/check-runs").mock(return_value=httpx.Response(200, json=answer, headers=limit()))
    statuses = status or {SECOND: CARDS["status_none"], THIRD: CARDS["status_success"]}
    for head, answer in statuses.items():
        respx.get(f"{API}/repos/example/web/commits/{head}/status").mock(return_value=httpx.Response(200, json=answer, headers=limit()))


@respx.mock
async def test_the_repository_card_gives_stars_forks_issues_pull_requests_release_and_push(ctx: Context) -> None:
    project()
    data = await GITHUB.fetch("repository", {}, {"repo": "example/project"}, ctx)
    assert data.primary == {"label": "Stars", "value": 54589}
    rows = {row["label"]: row["value"] for row in data.secondary}
    assert rows["Project"] == "example/project" and rows["Forks"] == 12106
    assert rows["Open pull requests"] == 87 and rows["Open issues"] == 244 - 87, "the count of the repository holds both; the search says which are pull requests"
    assert rows["Latest release"] == "v2.34.2" and rows["Released"].endswith(" d") and rows["Last push"]
    assert data.metrics == {"stars": 54589.0, "issues": 157.0, "pulls": 87.0}
    assert data.status == "ok" and data.link == CARDS["repo"]["html_url"]
    search = next(call.request for call in respx.calls if call.request.url.path == "/search/issues")
    assert search.url.params["q"] == "repo:example/project is:pr is:open" and search.url.params["per_page"] == "1"


@respx.mock
async def test_without_the_search_the_card_says_issues_and_pull_requests_together(ctx: Context) -> None:
    respx.get(f"{API}/repos/example/project").mock(return_value=httpx.Response(200, json=CARDS["repo"], headers=limit()))
    respx.get(f"{API}/repos/example/project/releases/latest").mock(return_value=httpx.Response(404, json={"message": "Not Found"}, headers=limit()))
    respx.get(f"{API}/search/issues").mock(return_value=httpx.Response(403, json={"message": "API rate limit exceeded"}, headers={**limit(0), "x-ratelimit-remaining": "0"}))
    data = await GITHUB.fetch("repository", {}, {"repo": "example/project"}, ctx)
    rows = {row["label"]: row["value"] for row in data.secondary}
    assert rows["Open issues and pull requests"] == 244 and "Open pull requests" not in rows
    assert rows["Latest release"] == "None" and "Released" not in rows, "a project without a release is not a fault"


def test_an_archived_project_turns_the_card_yellow_and_one_without_issues_asks_nothing_more() -> None:
    quiet = {**CARDS["repo"], "archived": True, "open_issues_count": 0}
    data = GITHUB.repository_card(quiet, None, 0)
    assert data.status == "warn" and {"label": "Archived", "value": "Yes"} in data.secondary
    assert data.metrics["issues"] == 0.0


@respx.mock
async def test_a_project_that_is_not_there_or_not_named_properly(ctx: Context) -> None:
    respx.get(f"{API}/repos/example/gone").mock(return_value=httpx.Response(404, json={"message": "Not Found"}, headers=limit()))
    with pytest.raises(AdapterError) as gone:
        await GITHUB.fetch("repository", {}, {"repo": "example/gone"}, ctx)
    assert gone.value.code == "not_found"
    for bad in ("", "nope", "a/b/c", "../x", "a/b?c"):
        with pytest.raises(AdapterError) as refused:
            await GITHUB.fetch("repository", {}, {"repo": bad}, fresh())
        assert refused.value.code == "bad_repository", bad


@respx.mock
async def test_pull_requests_carry_the_state_of_their_checks(ctx: Context) -> None:
    pulls()
    data = await GITHUB.fetch("pulls", {}, {"repos": "example/web"}, ctx)
    by_title = {row["title"]: row for row in data.items}
    passed = by_title["automatic options as separate route"]
    assert passed["status"] == "ok" and passed["subtitle"] == "Checks passed · web#5918"
    nothing = by_title["Move parts of the session code to sansio"]
    assert nothing["status"] == "unknown" and nothing["subtitle"] == "No checks · web#5660", "a commit with no statuses says pending, and it is not running"
    legacy = by_title["Workflow"]
    assert legacy["status"] == "ok" and legacy["subtitle"] == "Checks passed · web#5665", "a project that reports statuses and no check runs"
    assert data.status == "ok" and data.secondary == [{"label": "Failing checks", "value": 0}, {"label": "Open pull requests", "value": 3}]
    status_calls = [call.request.url.path for call in respx.calls if call.request.url.path.endswith("/status")]
    assert len(status_calls) == 2, "the status is asked only where there were no check runs"


@respx.mock
async def test_a_failed_check_puts_the_pull_request_first_and_a_running_one_is_yellow(ctx: Context) -> None:
    failed = {"total_count": 2, "check_runs": [{"name": "tests", "status": "completed", "conclusion": "success"}, {"name": "lint", "status": "completed", "conclusion": "failure"}]}
    running = {"total_count": 1, "check_runs": [{"name": "tests", "status": "in_progress", "conclusion": None}]}
    approval = {"total_count": 1, "check_runs": [{"name": "tests", "status": "completed", "conclusion": "action_required"}]}
    pulls({FIRST: failed, SECOND: running, THIRD: approval}, {})
    data = await GITHUB.fetch("pulls", {}, {"repos": "example/web"}, ctx)
    assert [(row["status"], row["subtitle"]) for row in data.items] == [
        ("bad", "Checks failed · web#5918"), ("warn", "Checks running · web#5660"), ("warn", "Needs approval · web#5665")]
    assert data.status == "bad" and data.metrics == {"failing": 1.0}
    assert data.secondary[0] == {"label": "Failing checks", "value": 1}


@respx.mock
async def test_drafts_can_be_left_out_and_a_review_request_is_said(ctx: Context) -> None:
    pulls()
    draft = json.loads(json.dumps(CARDS["pulls"]))
    draft[1]["draft"] = True
    draft[2]["requested_reviewers"] = [{"login": "someone"}]
    respx.get(f"{API}/repos/example/web/pulls").mock(return_value=httpx.Response(200, json=draft, headers=limit()))
    shown = await GITHUB.fetch("pulls", {}, {"repos": "example/web"}, ctx)
    assert {row["title"]: row["subtitle"] for row in shown.items}["Move parts of the session code to sansio"] == "No checks · Draft · web#5660"
    assert {row["title"]: row["subtitle"] for row in shown.items}["Workflow"] == "Checks passed · Review requested · web#5665"
    without = await GITHUB.fetch("pulls", {}, {"repos": "example/web", "drafts": False}, fresh())
    assert [row["title"] for row in without.items if "sansio" in row["title"]] == []


@respx.mock
async def test_when_the_limit_runs_out_between_the_checks_the_card_keeps_what_it_has(ctx: Context) -> None:
    pulls()
    respx.get(f"{API}/repos/example/web/commits/{SECOND}/check-runs").mock(return_value=httpx.Response(
        403, json={"message": "API rate limit exceeded"}, headers={**limit(0), "x-ratelimit-remaining": "0"}))
    data = await GITHUB.fetch("pulls", {}, {"repos": "example/web"}, ctx)
    assert len(data.items) == 3 and data.meta["checks_limited"] is True
    assert [row["status"] for row in data.items].count("ok") == 1 and [row["status"] for row in data.items].count("unknown") == 2


@respx.mock
async def test_a_project_that_does_not_exist_is_a_line_not_a_failure_of_the_card(ctx: Context) -> None:
    pulls()
    respx.get(f"{API}/repos/example/gone/pulls").mock(return_value=httpx.Response(404, json={"message": "Not Found"}, headers=limit()))
    data = await GITHUB.fetch("pulls", {}, {"repos": "example/web\nexample/gone"}, ctx)
    assert len(data.items) == 3 and data.meta["failures"] == ["example/gone: not found, or not visible to this token"]
    alone = await GITHUB.fetch("pulls", {}, {"repos": "example/gone"}, fresh())
    assert alone.status == "bad" and "example/gone" in (alone.error or "")


@respx.mock
async def test_milestones_say_how_much_is_done_and_when_it_is_due(ctx: Context) -> None:
    route = respx.get(f"{API}/repos/example/project/milestones").mock(return_value=httpx.Response(200, json=CARDS["milestones"], headers=limit()))
    data = await GITHUB.fetch("milestones", {}, {"repos": "example/project"}, ctx)
    assert [(row["title"], row["value"], row["progress"]) for row in data.items] == [
        ("project 3.0.0", "71%", 70.7), ("project 2.34.0", "100%", 100.0), ("project Soon™", "0%", 0.0)]
    assert [row["subtitle"] for row in data.items] == ["29 of 41 done", "5 of 5 done", "No issues yet"]
    assert data.secondary == [{"label": "Overdue", "value": 0}, {"label": "Open milestones", "value": 3}] and data.status == "ok"
    params = route.calls.last.request.url.params
    assert (params["state"], params["sort"], params["direction"]) == ("open", "due_on", "asc")


def test_an_overdue_milestone_is_red_and_first_one_due_soon_is_yellow_and_a_finished_one_is_never_late() -> None:
    now = 1_793_000_000.0
    day = 86400

    def due(days: float) -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now + days * day))

    found = [("o/p", [
        {"title": "later", "closed_issues": 1, "open_issues": 3, "due_on": due(20)},
        {"title": "soon", "closed_issues": 3, "open_issues": 1, "due_on": due(2.5)},
        {"title": "late", "closed_issues": 2, "open_issues": 2, "due_on": due(-3)},
        {"title": "done but past", "closed_issues": 4, "open_issues": 0, "due_on": due(-30)},
        {"title": "today", "closed_issues": 1, "open_issues": 1, "due_on": due(0.2)},
    ])]
    data = GITHUB.milestone_rows(found, 10, now)
    assert [(row["title"], row["status"]) for row in data.items] == [
        ("p late", "bad"), ("p today", "warn"), ("p soon", "warn"), ("p done but past", "ok"), ("p later", "ok")]
    assert data.items[0]["subtitle"] == "2 of 4 done · overdue by 3 d" and data.items[1]["subtitle"] == "1 of 2 done · due today"
    assert data.items[2]["subtitle"] == "3 of 4 done · due in 2 d"
    assert data.status == "bad" and data.metrics == {"overdue": 1.0}
    assert len(GITHUB.milestone_rows(found, 2, now).items) == 2


@respx.mock
async def test_the_new_cards_need_a_project(ctx: Context) -> None:
    for kind in ("pulls", "milestones"):
        with pytest.raises(AdapterError) as dots:
            await GITHUB.fetch(kind, {}, {"repos": "../x"}, ctx)
        assert dots.value.code == "bad_repository", "a path is not a project"
        with pytest.raises(AdapterError) as missing:
            await GITHUB.fetch(kind, {}, {}, ctx)
        assert missing.value.code == "missing_repo"
        with pytest.raises(AdapterError) as bad:
            await GITHUB.fetch(kind, {}, {"repos": "just-a-name"}, ctx)
        assert bad.value.code == "bad_repository"
