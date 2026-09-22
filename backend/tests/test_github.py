"""GitHub: answers kept with their ETag, the hourly limit read and respected,
an optional token, and the issue, pull request and workflow cards."""

from __future__ import annotations

import time

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context
from app.adapters.github import LIMIT, RESERVE

from .conftest import CSRF, setup_admin

API = "https://api.github.com"
GITHUB = get_adapter("github")


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=None, widget_id=1, cache={})


def _limit(remaining: int, reset: float | None = None) -> dict[str, str]:
    return {"x-ratelimit-remaining": str(remaining), "x-ratelimit-limit": "60", "x-ratelimit-reset": str(int(reset or time.time() + 1800))}


RELEASE = {"tag_name": "1.0", "published_at": "2026-09-01T12:00:00Z", "body": "First.", "html_url": "https://github.com/o/n/releases/1.0"}


@respx.mock
async def test_an_unchanged_answer_is_asked_for_with_its_etag_and_taken_from_memory(ctx: Context) -> None:
    route = respx.get(f"{API}/repos/o/n/releases/latest").mock(side_effect=[
        httpx.Response(200, json=RELEASE, headers={"etag": '"abc"', **_limit(50)}),
        httpx.Response(304, headers={"etag": '"abc"', **_limit(50)}),
    ])
    first = await GITHUB.fetch("releases", {}, {"repos": "o/n"}, ctx)
    second = await GITHUB.fetch("releases", {}, {"repos": "o/n"}, ctx)
    assert route.calls[1].request.headers["if-none-match"] == '"abc"'
    assert "if-none-match" not in route.calls[0].request.headers
    assert first.items == second.items and second.items[0]["title"] == "n 1.0"
    assert "stale_since" not in second.meta, "a 304 is a fresh answer, not an old one"


@respx.mock
async def test_the_last_requests_are_held_back_and_the_card_shows_what_it_has(ctx: Context) -> None:
    route = respx.get(f"{API}/repos/o/n/releases/latest").mock(return_value=httpx.Response(
        200, json=RELEASE, headers={"etag": '"abc"', **_limit(RESERVE)},
    ))
    await GITHUB.fetch("releases", {}, {"repos": "o/n"}, ctx)
    again = await GITHUB.fetch("releases", {}, {"repos": "o/n"}, ctx)
    assert route.call_count == 1, "with only the reserve left, nothing more is spent before the reset"
    assert again.items[0]["title"] == "n 1.0"
    assert isinstance(again.meta["stale_since"], int)


@respx.mock
async def test_after_the_reset_it_asks_again(ctx: Context) -> None:
    route = respx.get(f"{API}/repos/o/n/releases/latest").mock(return_value=httpx.Response(200, json=RELEASE, headers={"etag": '"abc"', **_limit(0)}))
    ctx.cache[LIMIT] = {"remaining": 0, "reset": time.time() - 1, "limit": 60}
    await GITHUB.fetch("releases", {}, {"repos": "o/n"}, ctx)
    assert route.call_count == 1


@respx.mock
async def test_a_used_up_limit_shows_the_last_answer_or_says_until_when(ctx: Context) -> None:
    route = respx.get(f"{API}/repos/o/n/releases/latest").mock(side_effect=[
        httpx.Response(200, json=RELEASE, headers={"etag": '"abc"', **_limit(40)}),
        httpx.Response(403, json={"message": "API rate limit exceeded"}, headers=_limit(0, time.time() + 1500)),
    ])
    await GITHUB.fetch("releases", {}, {"repos": "o/n"}, ctx)
    ctx.cache[LIMIT]["remaining"] = 40  # as if another card had not asked in between
    held = await GITHUB.fetch("releases", {}, {"repos": "o/n"}, ctx)
    assert route.call_count == 2 and held.items[0]["title"] == "n 1.0" and "stale_since" in held.meta

    fresh = Context(httpx.AsyncClient(), integration_id=None, widget_id=2, cache={})
    respx.get(f"{API}/repos/o/other/releases/latest").mock(return_value=httpx.Response(403, json={"message": "API rate limit exceeded"}, headers=_limit(0, time.time() + 1500)))
    with pytest.raises(AdapterError) as failure:
        await GITHUB.fetch("releases", {}, {"repos": "o/other"}, fresh)
    assert failure.value.code == "rate_limited"
    assert "25 min" in failure.value.message
    assert "token" in failure.value.hint


@respx.mock
async def test_a_token_is_sent_and_a_wrong_one_is_said_to_be_wrong(ctx: Context) -> None:
    route = respx.get(f"{API}/repos/o/n/releases/latest").mock(side_effect=[
        httpx.Response(200, json=RELEASE, headers=_limit(4990)),
        httpx.Response(401, json={"message": "Bad credentials"}),
    ])
    await GITHUB.fetch("releases", {"token": "github-token-for-tests"}, {"repos": "o/n"}, ctx)
    assert route.calls[0].request.headers["authorization"] == "Bearer github-token-for-tests"
    ctx.cache.clear()
    with pytest.raises(AuthFailed) as failure:
        await GITHUB.fetch("releases", {"token": "wrong"}, {"repos": "o/n"}, ctx)
    assert "token" in failure.value.message
    ctx.cache.clear()
    respx.get(f"{API}/repos/o/plain/releases/latest").mock(return_value=httpx.Response(200, json=RELEASE, headers=_limit(59)))
    await GITHUB.fetch("releases", {}, {"repos": "o/plain"}, ctx)
    assert "authorization" not in respx.calls.last.request.headers


@respx.mock
async def test_issues_leave_the_pull_requests_out_and_pull_requests_say_their_state(ctx: Context) -> None:
    respx.get(f"{API}/repos/o/n/issues").mock(return_value=httpx.Response(200, headers=_limit(50), json=[
        {"number": 7, "title": "A bug", "updated_at": "2026-09-20T10:00:00Z", "html_url": "https://github.com/o/n/issues/7"},
        {"number": 8, "title": "A pull request", "updated_at": "2026-09-21T10:00:00Z", "pull_request": {}},
    ]))
    issues = await GITHUB.fetch("issues", {}, {"repos": "o/n", "what": "issues"}, ctx)
    assert [item["title"] for item in issues.items] == ["A bug"]
    assert issues.items[0]["subtitle"] == "n#7" and issues.metrics == {"open": 1.0}

    respx.get(f"{API}/repos/o/n/pulls").mock(return_value=httpx.Response(200, headers=_limit(49), json=[
        {"number": 9, "title": "Draft work", "draft": True, "updated_at": "2026-09-21T09:00:00Z"},
        {"number": 10, "title": "Please look", "draft": False, "requested_reviewers": [{"login": "x"}], "updated_at": "2026-09-21T11:00:00Z"},
        {"number": 11, "title": "Plain", "draft": False, "requested_reviewers": [], "updated_at": "2026-09-19T11:00:00Z"},
    ]))
    pulls = await GITHUB.fetch("issues", {}, {"repos": "o/n", "what": "pulls"}, ctx)
    assert [(item["title"], item["subtitle"]) for item in pulls.items] == [
        ("Please look", "Review requested · n#10"), ("Draft work", "Draft · n#9"), ("Plain", "n#11"),
    ]


@respx.mock
async def test_runs_show_the_latest_of_each_workflow_red_first(ctx: Context) -> None:
    respx.get(f"{API}/repos/o/n/actions/runs").mock(return_value=httpx.Response(200, headers=_limit(50), json={"workflow_runs": [
        {"workflow_id": 1, "name": "CI", "display_title": "Newest CI", "status": "completed", "conclusion": "success", "updated_at": "2026-09-21T12:00:00Z"},
        {"workflow_id": 2, "name": "Image", "display_title": "Image build", "status": "completed", "conclusion": "failure", "updated_at": "2026-09-21T08:00:00Z"},
        {"workflow_id": 1, "name": "CI", "display_title": "Older CI", "status": "completed", "conclusion": "failure", "updated_at": "2026-09-20T12:00:00Z"},
        {"workflow_id": 3, "name": "Deploy", "display_title": "Deploying", "status": "in_progress", "conclusion": None, "updated_at": "2026-09-21T11:00:00Z"},
    ]}))
    data = await GITHUB.fetch("runs", {}, {"repos": "o/n"}, ctx)
    assert [item["title"] for item in data.items] == ["Image build", "Newest CI", "Deploying"]
    assert [item["status"] for item in data.items] == ["bad", "ok", "warn"]
    assert data.status == "bad" and data.metrics == {"failing": 1.0}, "CI's older failure is history, not a red workflow"


async def test_a_project_is_named_as_owner_and_name(ctx: Context) -> None:
    with pytest.raises(AdapterError) as failure:
        await GITHUB.fetch("issues", {}, {"repos": "just-a-name"}, ctx)
    assert failure.value.code == "bad_repository"
    with pytest.raises(AdapterError):
        await GITHUB.fetch("runs", {}, {"repos": ""}, ctx)


def test_a_github_card_takes_a_token_connection_and_works_without(client: TestClient) -> None:
    setup_admin(client)
    kinds = {entry["kind"]: entry for entry in client.get("/api/v1/adapters").json()}
    assert kinds["github"]["optional_integration"] is True and kinds["github"]["needs_integration"] is False
    board = client.post("/api/v1/boards", json={"name": "Code"}, headers=CSRF).json()
    page = board["pages"][0]["id"]
    bare = client.post(f"/api/v1/pages/{page}/widgets", json={"kind": "github.releases"}, headers=CSRF)
    assert bare.status_code == 201, bare.text
    connection = client.post("/api/v1/integrations", json={"kind": "github", "name": "GitHub", "config": {"token": "github-token-for-tests"}}, headers=CSRF)
    assert connection.status_code == 201, connection.text
    bound = client.post(f"/api/v1/pages/{page}/widgets", json={"kind": "github.runs", "integration_id": connection.json()["id"], "options": {"repos": "o/n"}}, headers=CSRF)
    assert bound.status_code == 201, bound.text
    assert bound.json()["widget"]["integration_id"] == connection.json()["id"]


@respx.mock
async def test_the_connection_test_says_what_the_connection_is_good_for(ctx: Context) -> None:
    """It used to report nexdeck's own release, which nobody had asked for."""
    respx.get(f"{API}/rate_limit").mock(return_value=httpx.Response(200, json={"resources": {"core": {"limit": 60, "remaining": 57}}}))
    said = await GITHUB.test({}, ctx)
    assert "without a token" in said and "57 of 60" in said and "nexdeck" not in said
    respx.get(f"{API}/user").mock(return_value=httpx.Response(200, json={"login": "someone"}))
    assert "someone" in await GITHUB.test({"token": "github-token-for-tests"}, Context(httpx.AsyncClient(), cache={}))
