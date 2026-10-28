"""Jenkins, against the answers of Jenkins 2.580.1 (jenkins/jenkins:lts-jdk21, 27.10.2026).

``fixtures/jenkins_answers.json`` holds the real shapes of the job tree (a
passing, a failing, a running, a never built, a disabled and a parameterised
job, two of them inside a folder), the queue, the executors and the shorter
tree the test asks. Names and the address are made up. The build button is
checked against the statuses Jenkins answered: 201, 400 for a job with
parameters on ``build``, 409 for a disabled job, 404 for one that is gone.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context, Unreachable, outbound_client
from app.adapters.jenkins import _flatten

BASE = "http://jenkins.example.com:8080"
CONFIG = {"url": BASE, "user": "admin", "token": "made-up-token"}
ADAPTER = get_adapter("jenkins")
ANSWERS = json.loads((Path(__file__).parent / "fixtures" / "jenkins_answers.json").read_text(encoding="utf-8"))
#: A moment shortly after the recorded builds.
NOW = 1793146100.0


@pytest.fixture
def ctx() -> Context:
    return Context(outbound_client(guard=False), integration_id=1, widget_id=1, cache={})


def jenkins() -> None:
    headers = {"X-Jenkins": "2.580.1"}
    respx.get(f"{BASE}/api/json").mock(side_effect=lambda request: httpx.Response(
        200, headers=headers, json=ANSWERS["top"] if "numExecutors" in request.url.params["tree"] else ANSWERS["root"]))
    respx.get(f"{BASE}/queue/api/json").mock(return_value=httpx.Response(200, headers=headers, json=ANSWERS["queue"]))
    respx.get(f"{BASE}/computer/api/json").mock(return_value=httpx.Response(200, headers=headers, json=ANSWERS["computer"]))


def titles(data) -> list[str]:  # noqa: ANN001
    return [row["title"] for row in data.items]


def test_folders_are_walked_into_and_left_out_themselves() -> None:
    names = [job["fullName"] for job in _flatten(ANSWERS["root"]["jobs"])]
    assert "team/api-tests" in names and "team" not in names and len(names) == 8
    deep = [{"name": "a", "jobs": [{"name": "b", "jobs": [{"name": "c", "fullName": "a/b/c", "color": "blue"}]}]}]
    assert [job["fullName"] for job in _flatten(deep)] == ["a/b/c"], "three folders down"
    assert _flatten([{"name": "empty", "jobs": []}]) == []


def test_the_jobs_card_puts_failing_first_then_running_then_the_newest() -> None:
    jobs = _flatten(ANSWERS["root"]["jobs"])
    data = ADAPTER.jobs_card(jobs, {}, BASE, NOW)
    assert titles(data) == ["team/api-flaky", "build-fail", "slow", "team/api-tests", "deploy", "build-ok", "never-built"]
    assert data.status == "bad" and data.metrics == {"failing": 2.0}
    assert data.secondary == [{"label": "Failing", "value": 2}, {"label": "Jobs", "value": 7}]
    flaky = data.items[0]
    assert flaky["status"] == "bad" and flaky["subtitle"].startswith("Failed · #1") and flaky["value"] == "1 min"
    assert flaky["url"] == f"{BASE}/job/team/job/api-flaky/"
    assert flaky["actions"] == [{"id": "build", "label": "Build now", "icon": "play", "confirm": True, "params": {"job": "team/api-flaky"}}]
    slow = data.items[2]
    assert slow["status"] == "unknown" and slow["subtitle"] == "Running · #1", "a first build that has not finished yet"
    assert [row["subtitle"] for row in data.items if row["title"] == "never-built"] == ["Never built"]
    assert data.items[3]["subtitle"].startswith("#2") and data.items[3]["status"] == "ok", "a passing build says no word, only its number and time"
    assert data.link == BASE


def test_a_running_build_shows_how_far_it_is_and_a_disabled_job_has_no_button() -> None:
    running = {"fullName": "web", "name": "web", "url": f"{BASE}/job/web/", "color": "red_anime",
               "lastBuild": {"number": 5, "building": True, "timestamp": int((NOW - 60) * 1000), "duration": 0, "estimatedDuration": 240000}}
    off = {"fullName": "off", "name": "off", "url": f"{BASE}/job/off/", "color": "disabled", "lastBuild": None}
    data = ADAPTER.jobs_card([running, off], {}, None, NOW)
    assert titles(data) == ["web"], "disabled jobs are left out unless asked for"
    assert data.items[0]["progress"] == 25.0 and data.items[0]["status"] == "bad", "red while it runs: the last finished build failed"
    shown = ADAPTER.jobs_card([running, off], {"disabled": True}, None, NOW)
    assert titles(shown) == ["web", "off"] and "actions" not in shown.items[1] and shown.items[1]["subtitle"] == "Disabled"


def test_the_jobs_card_can_be_narrowed_to_the_failing_ones_and_to_a_folder() -> None:
    jobs = _flatten(ANSWERS["root"]["jobs"])
    assert titles(ADAPTER.jobs_card(jobs, {"only_failing": True}, None, NOW)) == ["team/api-flaky", "build-fail"]
    assert titles(ADAPTER.jobs_card(jobs, {"folder": "team"}, None, NOW)) == ["team/api-flaky", "team/api-tests"]
    assert titles(ADAPTER.jobs_card(jobs, {"folder": "tea"}, None, NOW)) == [], "a folder is a whole name, not a prefix of one"
    assert titles(ADAPTER.jobs_card(jobs, {"limit": 2}, None, NOW)) == ["team/api-flaky", "build-fail"]


@respx.mock
async def test_the_overview_counts_failing_running_queued_and_executors(ctx: Context) -> None:
    jenkins()
    data = await ADAPTER.fetch("overview", CONFIG, {}, ctx)
    assert data.primary == {"label": "Failing", "value": 2}
    assert data.secondary == [{"label": "Jobs", "value": 7}, {"label": "Running", "value": 1}, {"label": "Queued", "value": len(ANSWERS["queue"]["items"])},
                              {"label": "Executors busy", "value": "1 of 2"}]
    assert data.status == "bad" and data.metrics == {"failing": 2.0, "queue": float(len(ANSWERS["queue"]["items"])), "busy": 1.0}
    request = next(call.request for call in respx.calls if call.request.url.path == "/api/json")
    assert base64.b64decode(request.headers["authorization"].split()[1]) == b"admin:made-up-token"
    assert request.url.params["tree"].startswith("jobs[name,fullName,url,color,lastBuild[")


def test_an_offline_node_and_an_unstable_job_turn_the_overview_yellow() -> None:
    jobs = [{"fullName": "a", "color": "yellow"}, {"fullName": "b", "color": "blue"}]
    computers = {"busyExecutors": 0, "totalExecutors": 2, "computer": [{"displayName": "agent", "offline": True}]}
    data = ADAPTER.overview_card(jobs, {"items": []}, computers)
    assert data.status == "warn"
    assert {"label": "Unstable", "value": 1} in data.secondary and {"label": "Nodes offline", "value": 1} in data.secondary


@respx.mock
async def test_the_test_names_the_version_from_the_header(ctx: Context) -> None:
    jenkins()
    assert await ADAPTER.test(CONFIG, ctx) == "Jenkins 2.580.1 answers, 7 jobs at the top."


@respx.mock
async def test_a_wrong_token_and_missing_credentials_are_told_apart(ctx: Context) -> None:
    route = respx.get(f"{BASE}/api/json").mock(return_value=httpx.Response(401, text=""))
    with pytest.raises(AuthFailed) as wrong:
        await ADAPTER.fetch("jobs", CONFIG, {}, ctx)
    assert "rejected" in wrong.value.message and "Security > API Token" in wrong.value.hint
    route.mock(return_value=httpx.Response(403, headers={"X-Jenkins": "2.580.1"}, text="Authentication required"))
    ctx.cache.clear()
    with pytest.raises(AuthFailed) as anonymous:
        await ADAPTER.fetch("jobs", {"url": BASE}, {}, ctx)
    assert "wants a user name" in anonymous.value.message


@respx.mock
async def test_an_unreachable_jenkins_and_a_wrong_address(ctx: Context) -> None:
    route = respx.get(f"{BASE}/api/json").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(Unreachable):
        await ADAPTER.fetch("overview", CONFIG, {}, ctx)
    route.mock(return_value=httpx.Response(200, json={"hello": "not jenkins"}))
    with pytest.raises(AdapterError) as elsewhere:
        await ADAPTER.test(CONFIG, ctx)
    assert elsewhere.value.code == "not_jenkins"


@respx.mock
async def test_the_build_button_queues_a_job_in_a_folder(ctx: Context) -> None:
    route = respx.post(f"{BASE}/job/team/job/api-flaky/build").mock(return_value=httpx.Response(201))
    message = await ADAPTER.action("jobs", "build", {"job": "team/api-flaky"}, CONFIG, {}, ctx)
    assert message == "team/api-flaky is queued." and route.call_count == 1
    assert "authorization" in route.calls.last.request.headers


@respx.mock
async def test_a_job_with_parameters_is_built_with_their_defaults(ctx: Context) -> None:
    plain = respx.post(f"{BASE}/job/deploy/build").mock(return_value=httpx.Response(400))
    with_defaults = respx.post(f"{BASE}/job/deploy/buildWithParameters").mock(return_value=httpx.Response(201))
    assert await ADAPTER.action("jobs", "build", {"job": "deploy"}, CONFIG, {}, ctx) == "deploy is queued."
    assert plain.call_count == 1 and with_defaults.call_count == 1


@respx.mock
async def test_the_build_button_says_why_it_failed(ctx: Context) -> None:
    respx.post(f"{BASE}/job/old/build").mock(return_value=httpx.Response(409))
    with pytest.raises(AdapterError) as disabled:
        await ADAPTER.action("jobs", "build", {"job": "old"}, CONFIG, {}, ctx)
    assert disabled.value.code == "job_disabled"
    respx.post(f"{BASE}/job/gone/build").mock(return_value=httpx.Response(404))
    with pytest.raises(AdapterError) as gone:
        await ADAPTER.action("jobs", "build", {"job": "gone"}, CONFIG, {}, ctx)
    assert gone.value.code == "not_found"
    respx.post(f"{BASE}/job/locked/build").mock(return_value=httpx.Response(403, text="No valid crumb was included in the request"))
    with pytest.raises(AuthFailed) as refused:
        await ADAPTER.action("jobs", "build", {"job": "locked"}, CONFIG, {}, ctx)
    assert "CSRF crumb" in refused.value.hint


@respx.mock
async def test_a_job_name_is_one_quoted_segment_per_folder(ctx: Context) -> None:
    route = respx.post(f"{BASE}/job/My%20Team/job/build%20it/build").mock(return_value=httpx.Response(201))
    await ADAPTER.action("jobs", "build", {"job": "My Team/build it"}, CONFIG, {}, ctx)
    assert route.call_count == 1
    for bad in ("", "../x", "a/../b", "a//b", "a?x=1", "/a", "a\\b", None):
        with pytest.raises(AdapterError) as refused:
            await ADAPTER.action("jobs", "build", {"job": bad}, CONFIG, {}, ctx)
        assert refused.value.code == "bad_param", bad
    assert route.call_count == 1, "nothing but the one build went out"
