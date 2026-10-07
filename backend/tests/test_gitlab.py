"""The GitLab cards against the answers of its API v4.

The answers are shaped after GitLab.com's, measured on 07.10.2026 against
gitlab-org/cli without a token: merge request and workload pipelines among
the branch ones, ``x-total`` on the lists, no ``open_issues_count`` on a
project read without a token, 404 for a project that is not there.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context

URL = "https://gitlab.example.com"
API = f"{URL}/api/v4"
CONFIG = {"url": URL}
GL = get_adapter("gitlab")
APP = f"{API}/projects/group%2Fapp"
LIB = f"{API}/projects/group%2Fsub%2Flib"


def _ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


def _at(**delta: float) -> str:
    return (datetime.now(UTC) + timedelta(**delta)).isoformat().replace("+00:00", "Z")


def _pipeline(ref: str, status: str, source: str = "push", **delta: float) -> dict[str, Any]:
    return {"id": 1, "ref": ref, "status": status, "source": source, "updated_at": _at(**(delta or {"minutes": -30})),
            "web_url": f"{URL}/group/app/-/pipelines/1"}


@respx.mock
@pytest.mark.asyncio
async def test_the_projects_card_reads_pipeline_merge_requests_and_issue_count_per_project() -> None:
    respx.get(APP).mock(return_value=httpx.Response(200, json={"name": "app", "web_url": f"{URL}/group/app", "last_activity_at": _at(hours=-3)}))
    respx.get(f"{APP}/pipelines/latest").mock(return_value=httpx.Response(200, json=_pipeline("main", "failed")))
    respx.get(f"{APP}/merge_requests").mock(return_value=httpx.Response(200, json=[{"iid": 1}], headers={"x-total": "71"}))
    respx.get(f"{APP}/issues_statistics").mock(return_value=httpx.Response(200, json={"statistics": {"counts": {"all": 9, "closed": 5, "opened": 4}}}))
    respx.get(LIB).mock(return_value=httpx.Response(200, json={"name": "lib", "last_activity_at": _at(days=-2)}))
    respx.get(f"{LIB}/pipelines/latest").mock(return_value=httpx.Response(404, json={"message": "404 Not found"}))
    respx.get(f"{LIB}/merge_requests").mock(return_value=httpx.Response(200, json=[]))
    respx.get(f"{LIB}/issues_statistics").mock(return_value=httpx.Response(200, json={"statistics": {"counts": {"opened": 0}}}))
    data = await GL.fetch("projects", CONFIG, {"projects": "group/app\nhttps://gitlab.example.com/group/sub/lib/-/pipelines"}, _ctx())
    assert data.status == "bad"
    app, lib = data.items
    assert app == {"title": "app", "subtitle": "Failed · 71 MRs · 4 issues", "status": "bad", "value": "3 h", "url": f"{URL}/group/app"}
    assert lib["subtitle"] == "No pipeline · 0 MRs · 0 issues" and lib["status"] == "unknown"
    assert data.metrics == {"failing": 1.0}


@respx.mock
@pytest.mark.asyncio
async def test_the_default_branch_pipeline_is_named_by_its_project() -> None:
    respx.get(f"{APP}/pipelines/latest").mock(return_value=httpx.Response(200, json=_pipeline("main", "running")))
    data = await GL.fetch("pipelines", CONFIG, {"projects": "group/app"}, _ctx())
    assert data.items[0]["title"] == "app" and data.items[0]["subtitle"] == "Running · main"
    assert data.status == "ok"


@respx.mock
@pytest.mark.asyncio
async def test_every_branch_leaves_the_merge_request_and_workload_pipelines_out_and_puts_red_first() -> None:
    """Measured on gitlab-org/cli: of the twenty newest pipelines, one ran on a branch."""
    route = respx.get(f"{APP}/pipelines").mock(return_value=httpx.Response(200, json=[
        _pipeline("refs/workloads/e12dd81db78", "failed", "duo_workflow", minutes=-1),
        _pipeline("refs/merge-requests/4021/merge", "failed", "merge_request_event", minutes=-2),
        _pipeline("main", "success", minutes=-5),
        _pipeline("feature/cache", "failed", hours=-6),
        _pipeline("nightly", "success", "schedule", hours=-9),
    ]))
    data = await GL.fetch("pipelines", CONFIG, {"projects": "group/app", "scope": "branches"}, _ctx())
    assert route.calls.last.request.url.params["scope"] == "branches"
    assert [item["title"] for item in data.items] == ["feature/cache", "main", "nightly"]
    assert data.items[0]["subtitle"] == "Failed · app" and data.items[2]["subtitle"] == "app · Scheduled"
    assert data.secondary == [{"label": "Failing pipelines", "value": 1}]


@respx.mock
@pytest.mark.asyncio
async def test_merge_requests_say_why_they_wait_and_are_counted_from_x_total() -> None:
    route = respx.get(f"{APP}/merge_requests").mock(return_value=httpx.Response(200, headers={"x-total": "71"}, json=[
        {"iid": 4021, "title": "Draft: Validate the remote", "draft": True, "detailed_merge_status": "draft_status",
         "references": {"short": "!4021"}, "updated_at": _at(minutes=-7), "web_url": f"{URL}/group/app/-/merge_requests/4021"},
        {"iid": 4015, "title": "Show the real total", "detailed_merge_status": "not_approved",
         "references": {"short": "!4015"}, "updated_at": _at(minutes=-20)},
    ]))
    # Above 10,000 GitLab leaves x-total out: a full page then says "at least".
    respx.get(f"{LIB}/merge_requests").mock(return_value=httpx.Response(200, json=[
        {"iid": 3, "title": "Bump", "detailed_merge_status": "mergeable", "references": {"short": "!3"}, "updated_at": _at(hours=-2)},
        {"iid": 2, "title": "Old", "detailed_merge_status": "conflict", "references": {"short": "!2"}, "updated_at": _at(hours=-5)},
    ]))
    data = await GL.fetch("merge_requests", CONFIG, {"projects": "group/app\ngroup/sub/lib", "limit": 2}, _ctx())
    assert route.calls.last.request.url.params["state"] == "opened"
    assert [item["title"] for item in data.items] == ["Validate the remote", "Show the real total"]
    assert [item["subtitle"] for item in data.items] == ["Draft · app!4021", "Needs approval · app!4015"]
    assert data.secondary == [{"label": "Merge requests", "value": "73+"}]


@respx.mock
@pytest.mark.asyncio
async def test_issues_come_from_the_issue_list() -> None:
    respx.get(f"{APP}/issues").mock(return_value=httpx.Response(200, headers={"x-total": "264"}, json=[
        {"iid": 8592, "title": "Truncated diffs", "references": {"short": "#8592"}, "updated_at": _at(minutes=-15)}]))
    data = await GL.fetch("merge_requests", CONFIG, {"projects": "group/app", "what": "issues"}, _ctx())
    assert data.items[0]["subtitle"] == "app#8592"
    assert data.secondary == [{"label": "Open issues", "value": 264}]


@respx.mock
@pytest.mark.asyncio
async def test_releases_take_the_newest_of_each_project() -> None:
    respx.get(f"{APP}/releases").mock(return_value=httpx.Response(200, json=[
        {"tag_name": "v1.121.0", "released_at": _at(days=-1), "description": "## Changelog\n* feat: stacks\n",
         "_links": {"self": f"{URL}/group/app/-/releases/v1.121.0"}}]))
    respx.get(f"{LIB}/releases").mock(return_value=httpx.Response(200, json=[]))
    data = await GL.fetch("releases", CONFIG, {"projects": "group/app\ngroup/sub/lib"}, _ctx())
    assert len(data.items) == 1
    assert data.items[0]["title"] == "app v1.121.0" and data.items[0]["summary"] == "* feat: stacks"


@respx.mock
@pytest.mark.asyncio
async def test_a_missing_project_is_said_on_its_line_and_the_others_still_show() -> None:
    respx.get(f"{APP}/releases").mock(return_value=httpx.Response(404, json={"message": "404 Project Not Found"}))
    respx.get(f"{LIB}/releases").mock(return_value=httpx.Response(200, json=[{"tag_name": "v1", "released_at": _at(days=-1)}]))
    data = await GL.fetch("releases", CONFIG, {"projects": "group/app\ngroup/sub/lib"}, _ctx())
    assert data.meta["failures"] == ["group/app: not found, or not visible to this token"]
    assert len(data.items) == 1
    respx.get(f"{LIB}/releases").mock(return_value=httpx.Response(404))
    data = await GL.fetch("releases", CONFIG, {"projects": "group/app\ngroup/sub/lib"}, _ctx())
    assert data.status == "bad" and "group/app" in data.error


@respx.mock
@pytest.mark.asyncio
async def test_the_token_goes_in_private_token_and_a_refusal_stops_every_line() -> None:
    route = respx.get(f"{APP}/pipelines/latest").mock(return_value=httpx.Response(401, json={"message": "401 Unauthorized"}))
    token = "-".join(("made", "up", "for", "this", "test"))
    with pytest.raises(AuthFailed):
        await GL.fetch("pipelines", {**CONFIG, "token": token}, {"projects": "group/app\ngroup/sub/lib"}, _ctx())
    assert route.calls.last.request.headers["PRIVATE-TOKEN"] == token
    assert route.call_count == 1


@respx.mock
@pytest.mark.asyncio
async def test_a_used_up_limit_says_when_to_try_again() -> None:
    respx.get(f"{APP}/pipelines/latest").mock(return_value=httpx.Response(429, headers={"retry-after": "42"}))
    with pytest.raises(AdapterError) as caught:
        await GL.fetch("pipelines", CONFIG, {"projects": "group/app"}, _ctx())
    assert caught.value.code == "rate_limited" and "42 s" in caught.value.message


@pytest.mark.asyncio
async def test_a_card_without_a_project_says_so() -> None:
    with pytest.raises(AdapterError) as caught:
        await GL.fetch("pipelines", CONFIG, {"projects": "  \n"}, _ctx())
    assert caught.value.code == "missing_project"


@respx.mock
@pytest.mark.asyncio
async def test_the_connection_test_with_and_without_a_token() -> None:
    respx.get(f"{API}/projects").mock(return_value=httpx.Response(200, json=[{"id": 1}], headers={"ratelimit-remaining": "499"}))
    assert await GL.test(CONFIG, _ctx()) == "GitLab answers without a token; public projects can be read, 499 requests left this minute."
    respx.get(f"{API}/user").mock(return_value=httpx.Response(200, json={"username": "someone"}))
    respx.get(f"{API}/version").mock(return_value=httpx.Response(200, json={"version": "18.4.1"}))
    assert await GL.test({**CONFIG, "token": "x"}, _ctx()) == "GitLab 18.4.1 accepts the token of someone."


@respx.mock
@pytest.mark.asyncio
async def test_an_address_that_is_not_gitlab_says_so() -> None:
    respx.get(f"{API}/projects").mock(return_value=httpx.Response(200, text="<html>sign in</html>"))
    with pytest.raises(AdapterError) as caught:
        await GL.test(CONFIG, _ctx())
    assert caught.value.code == "not_json"


@respx.mock
@pytest.mark.asyncio
async def test_unreachable_is_said() -> None:
    respx.get(f"{APP}/pipelines/latest").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(AdapterError) as caught:
        await GL.fetch("pipelines", CONFIG, {"projects": "group/app\ngroup/sub/lib"}, _ctx())
    assert caught.value.code == "unreachable"
