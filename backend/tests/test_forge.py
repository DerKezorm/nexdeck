"""Gitea and Forgejo, against the answers of a live Gitea 1.27.3 and Forgejo 13.0.5 (11.09.2026).

Each had two repositories, three issues (one closed), a pull request and a
runner that ran a green and a red workflow. The shapes below are copied from
there; ``/actions/tasks`` answered the same on both, down to the field names.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context

FORGES = {"gitea": "http://gitea.example.com", "forgejo": "http://forgejo.example.com"}
VERSION = {"gitea": "1.27.3", "forgejo": "13.0.5+gitea-1.22.0"}


def task(identifier: int, name: str, status: str, workflow: str, title: str, created: str, base: str) -> dict[str, Any]:
    return {"id": identifier, "name": name, "head_branch": "main", "head_sha": "made-up-sha", "run_number": identifier, "event": "push",
            "display_title": title, "status": status, "workflow_id": workflow, "url": f"{base}/tester/homelab/actions/runs/{identifier}",
            "created_at": created, "updated_at": created, "run_started_at": created}


def issue(number: int, title: str, repository: str, base: str, pull: bool = False, draft: bool = False) -> dict[str, Any]:
    kind = "pulls" if pull else "issues"
    return {"id": number, "number": number, "title": title, "state": "open", "comments": 0,
            "created_at": "2026-09-11T08:38:15Z", "updated_at": "2026-09-11T08:38:15Z",
            "html_url": f"{base}/{repository}/{kind}/{number}",
            "repository": {"id": 1, "name": repository.split("/")[1], "owner": "tester", "full_name": repository},
            "pull_request": {"merged": False, "merged_at": None, "draft": draft, "html_url": f"{base}/{repository}/pulls/{number}"} if pull else None}


def repo(full_name: str, updated: str, base: str, *, actions: bool = True, archived: bool = False) -> dict[str, Any]:
    return {"id": 1, "full_name": full_name, "name": full_name.split("/")[1], "private": False, "empty": False, "archived": archived,
            "has_actions": actions, "open_issues_count": 1, "open_pr_counter": 0, "updated_at": updated, "html_url": f"{base}/{full_name}"}


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


@pytest.mark.parametrize("kind", FORGES)
@respx.mock
async def test_the_connection_test_names_the_version_without_what_it_forked_from(ctx: Context, kind: str) -> None:
    """⚠️ Forgejo calls itself 13.0.5+gitea-1.22.0; the second half is not its version."""
    base = FORGES[kind]
    respx.get(f"{base}/api/v1/version").mock(return_value=httpx.Response(200, json={"version": VERSION[kind]}))
    route = respx.get(f"{base}/api/v1/user").mock(return_value=httpx.Response(200, json={"login": "tester", "is_admin": True}))
    message = await get_adapter(kind).test({"url": base, "token": "made-up"}, ctx)
    assert message == {"gitea": "Gitea 1.27.3 answers for tester.", "forgejo": "Forgejo 13.0.5 answers for tester."}[kind]
    assert route.calls.last.request.headers["Authorization"] == "token made-up"


@pytest.mark.parametrize("kind", FORGES)
@respx.mock
async def test_a_wrong_token_is_rejected(ctx: Context, kind: str) -> None:
    base = FORGES[kind]
    respx.get(f"{base}/api/v1/version").mock(return_value=httpx.Response(401, json={"message": "invalid username, password or token"}))
    with pytest.raises(AuthFailed):
        await get_adapter(kind).test({"url": base, "token": "wrong"}, ctx)


@pytest.mark.parametrize("kind", FORGES)
@respx.mock
async def test_open_issues_and_pull_requests_with_their_total(ctx: Context, kind: str) -> None:
    base = FORGES[kind]
    route = respx.get(f"{base}/api/v1/repos/issues/search").mock(side_effect=lambda request: httpx.Response(
        200, headers={"X-Total-Count": "9" if request.url.params["type"] == "issues" else "1"},
        json=[issue(1, "Sort the shell aliases", "tester/dotfiles", base), issue(2, "Move backups to the new NAS", "tester/homelab", base)]
        if request.url.params["type"] == "issues" else [issue(3, "Add notes", "tester/homelab", base, pull=True, draft=True)]))
    issues = await get_adapter(kind).fetch("issues", {"url": base, "token": "t"}, {"what": "issues", "limit": 8}, ctx)
    assert dict(route.calls.last.request.url.params) == {"state": "open", "type": "issues", "limit": "8"}
    assert [(row["title"], row["subtitle"]) for row in issues.items] == [("Sort the shell aliases", "tester/dotfiles#1"), ("Move backups to the new NAS", "tester/homelab#2")]
    assert issues.items[0]["url"] == f"{base}/tester/dotfiles/issues/1"
    # The page holds eight at most; the header says how many there are.
    assert issues.secondary == [{"label": "Open issues", "value": 9}]
    pulls = await get_adapter(kind).fetch("issues", {"url": base, "token": "t"}, {"what": "pulls", "limit": 8}, ctx)
    assert pulls.items[0]["subtitle"] == "Draft · tester/homelab#3" and pulls.secondary == [{"label": "Pull requests", "value": 1}]


@pytest.mark.parametrize("kind", FORGES)
@respx.mock
async def test_actions_from_the_repositories_that_changed_last(ctx: Context, kind: str) -> None:
    base = FORGES[kind]
    respx.get(f"{base}/api/v1/user/repos").mock(return_value=httpx.Response(200, json=[
        repo("tester/dotfiles", "2026-09-11T08:38:15Z", base),
        repo("tester/homelab", "2026-09-11T08:42:30Z", base),
        repo("tester/old", "2026-09-12T00:00:00Z", base, archived=True),
        repo("tester/notes", "2026-09-12T00:00:00Z", base, actions=False),
    ]))
    homelab = respx.get(f"{base}/api/v1/repos/tester/homelab/actions/tasks").mock(return_value=httpx.Response(200, json={"total_count": 3, "workflow_runs": [
        task(6, "green", "success", "green.yml", "Add a green workflow", "2026-09-11T08:42:30Z", base),
        task(5, "check", "failure", "ci.yml", "Add a green workflow", "2026-09-11T08:42:29Z", base),
        task(4, "fails", "success", "broken.yml", "Fix the broken workflow", "2026-09-11T08:41:30Z", base),
        task(3, "check", "success", "ci.yml", "Add a broken workflow", "2026-09-11T08:41:04Z", base),
        # Red once, green since: an old failure must not count.
        task(2, "fails", "failure", "broken.yml", "Add a broken workflow", "2026-09-11T08:41:02Z", base),
    ]}))
    # Actions switched off there: 404, which is skipped rather than failing the card.
    respx.get(f"{base}/api/v1/repos/tester/dotfiles/actions/tasks").mock(return_value=httpx.Response(404, json={"message": "Not found"}))
    data = await get_adapter(kind).fetch("actions", {"url": base, "token": "t"}, {"limit": 8}, ctx)
    assert homelab.called
    assert [(row["subtitle"], row["status"]) for row in data.items] == [
        ("homelab · green", "ok"), ("Failed · homelab · check", "bad"), ("homelab · fails", "ok"),
        ("homelab · check", "ok"), ("Failed · homelab · fails", "bad")]
    # Only the latest job of a workflow counts: ci.yml is red now, whatever it was before.
    assert data.secondary == [{"label": "Failing jobs", "value": 1}] and data.status == "bad"
    assert data.items[0]["url"] == f"{base}/tester/homelab/actions/runs/6"


@pytest.mark.parametrize("kind", FORGES)
@respx.mock
async def test_a_named_repository_is_the_only_one_asked(ctx: Context, kind: str) -> None:
    base = FORGES[kind]
    listing = respx.get(f"{base}/api/v1/user/repos").mock(return_value=httpx.Response(200, json=[]))
    respx.get(f"{base}/api/v1/repos/home/compose/actions/tasks").mock(return_value=httpx.Response(200, json={"total_count": 1, "workflow_runs": [
        task(9, "validate", "running", "ci.yml", "Bump Jellyfin", "2026-09-11T09:00:00Z", base)]}))
    data = await get_adapter(kind).fetch("actions", {"url": base, "token": "t"}, {"repository": " home/compose/ ", "limit": 8}, ctx)
    assert not listing.called
    assert data.items[0]["subtitle"] == "Running · compose · validate" and data.status == "ok"
    with pytest.raises(AdapterError) as bad:
        await get_adapter(kind).fetch("actions", {"url": base, "token": "t"}, {"repository": "compose", "limit": 8}, ctx)
    assert bad.value.code == "bad_repository"


@pytest.mark.parametrize("kind", FORGES)
@respx.mock
async def test_the_summary_counts_from_the_headers(ctx: Context, kind: str) -> None:
    base = FORGES[kind]
    respx.get(f"{base}/api/v1/repos/issues/search").mock(side_effect=lambda request: httpx.Response(
        200, headers={"X-Total-Count": "7" if request.url.params["type"] == "issues" else "2"}, json=[]))
    respx.get(f"{base}/api/v1/user/repos").mock(return_value=httpx.Response(200, headers={"X-Total-Count": "23"}, json=[]))
    data = await get_adapter(kind).fetch("summary", {"url": base, "token": "t"}, {}, ctx)
    assert data.primary == {"label": "Open issues", "value": 7}
    assert data.secondary == [{"label": "Pull requests", "value": 2}, {"label": "Repositories", "value": 23}]
