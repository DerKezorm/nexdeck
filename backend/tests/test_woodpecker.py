"""Woodpecker CI.

Measured against woodpeckerci/woodpecker-server v3 (3.19.0, 27.10.2026) without
a forge, so only what needs no sign-in: ``/api/version`` and the plain text
401 every other address answers. The repositories, pipelines, queue and agents
below have the shape of Woodpecker's documentation and were never answered by
a real server; the card is a beta for that reason.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context, Unreachable, outbound_client

BASE = "https://ci.example.com"
CONFIG = {"url": BASE, "token": "made-up-token"}
ADAPTER = get_adapter("woodpecker")
#: Measured.
VERSION = {"source": "https://github.com/woodpecker-ci/woodpecker", "version": "3.19.0"}
NOT_AUTHORIZED = "User not authorized"
#: From the documentation.
REPOS = [
    {"id": 1, "full_name": "example/api", "active": True,
     "last_pipeline": {"number": 212, "status": "failure", "event": "push", "branch": "main", "message": "Cache the session lookups\n\nlong text", "finished": 1793146000}},
    {"id": 2, "full_name": "example/web", "active": True},
    {"id": 3, "full_name": "example/old", "active": False},
    {"id": 4, "full_name": "example/new", "active": True},
]
WEB_PIPELINE = [{"number": 97, "status": "running", "event": "pull_request", "branch": "feature/menu", "message": "Move the settings page", "started": 1793146400}]
QUEUE = {"pending": [], "running": [], "stats": {"worker_count": 2, "pending_count": 3, "running_count": 1, "completed_count": 40}, "paused": False}
NOW = 1793146500.0


@pytest.fixture
def ctx() -> Context:
    return Context(outbound_client(guard=False), integration_id=1, widget_id=1, cache={})


def fresh() -> Context:
    return Context(outbound_client(guard=False), integration_id=2, widget_id=2, cache={})


def woodpecker(admin: bool = True) -> None:
    respx.get(f"{BASE}/api/version").mock(return_value=httpx.Response(200, json=VERSION))
    respx.get(f"{BASE}/api/user").mock(return_value=httpx.Response(200, json={"id": 1, "login": "admin"}))
    respx.get(f"{BASE}/api/user/repos").mock(return_value=httpx.Response(200, json=REPOS))
    respx.get(f"{BASE}/api/repos/2/pipelines").mock(return_value=httpx.Response(200, json=WEB_PIPELINE))
    respx.get(f"{BASE}/api/repos/4/pipelines").mock(return_value=httpx.Response(200, json=[]))
    if admin:
        respx.get(f"{BASE}/api/queue/info").mock(return_value=httpx.Response(200, json=QUEUE))
        respx.get(f"{BASE}/api/agents").mock(return_value=httpx.Response(200, json=[{"name": "a1", "last_contact": NOW - 20}, {"name": "a2", "last_contact": NOW - 900}]))
    else:
        respx.get(f"{BASE}/api/queue/info").mock(return_value=httpx.Response(403, text="Access denied"))
        respx.get(f"{BASE}/api/agents").mock(return_value=httpx.Response(403, text="Access denied"))


@respx.mock
async def test_the_pipelines_card_asks_for_the_newest_where_the_list_has_none(ctx: Context) -> None:
    woodpecker()
    data = await ADAPTER.fetch("pipelines", CONFIG, {}, ctx)
    assert [(row["title"], row["status"]) for row in data.items] == [("example/api", "bad"), ("example/web", "warn"), ("example/new", "unknown")]
    api, web, new = data.items
    assert api["subtitle"] == "Failed · main · push · Cache the session lookups" and api["url"] == f"{BASE}/repos/1/pipeline/212"
    assert web["subtitle"] == "Running · feature/menu · pull request · Move the settings page"
    assert new["subtitle"] == "No pipeline yet" and "url" not in new
    assert data.secondary == [{"label": "Failing", "value": 1}, {"label": "Repositories", "value": 3}] and data.metrics == {"failing": 1.0}
    assert respx.calls[0].request.headers["authorization"] == "Bearer made-up-token"
    asked = [call.request for call in respx.calls if call.request.url.path.endswith("/pipelines")]
    assert [request.url.path for request in asked] == ["/api/repos/2/pipelines", "/api/repos/4/pipelines"], "a repository that is off is not asked about"
    assert all(request.url.params["perPage"] == "1" for request in asked)
    failing = await ADAPTER.fetch("pipelines", CONFIG, {"only_failing": True}, fresh())
    assert [row["title"] for row in failing.items] == ["example/api"]


@respx.mock
async def test_the_overview_counts_failing_running_waiting_and_agents(ctx: Context) -> None:
    woodpecker()
    data = await ADAPTER.fetch("overview", CONFIG, {}, ctx)
    assert data.primary == {"label": "Failing", "value": 1}
    assert data.secondary[:3] == [{"label": "Repositories", "value": 3}, {"label": "Running", "value": 1}, {"label": "Waiting", "value": 3}]
    assert data.metrics == {"failing": 1.0, "running": 1.0, "pending": 3.0} and data.status == "bad"
    agents = ADAPTER.overview_card([], QUEUE, [{"last_contact": NOW - 20}, {"last_contact": NOW - 900}], None, NOW)
    assert agents.secondary[-1] == {"label": "Agents", "value": "1 of 2"} and agents.status == "warn", "an agent not heard from for five minutes is gone"


@respx.mock
async def test_a_user_who_is_no_admin_gets_the_overview_without_queue_and_agents(ctx: Context) -> None:
    woodpecker(admin=False)
    data = await ADAPTER.fetch("overview", CONFIG, {}, ctx)
    assert [row["label"] for row in data.secondary] == ["Repositories", "Running"], "nothing is said about what could not be read"
    assert data.secondary[1]["value"] == 1, "running is counted from the last pipelines instead"


@respx.mock
async def test_the_test_names_the_version_and_the_user(ctx: Context) -> None:
    woodpecker()
    assert await ADAPTER.test(CONFIG, ctx) == "Woodpecker 3.19.0 accepts the token of admin."


@respx.mock
async def test_the_plain_text_401_is_a_refused_token(ctx: Context) -> None:
    respx.get(f"{BASE}/api/version").mock(return_value=httpx.Response(200, json=VERSION))
    respx.get(f"{BASE}/api/user").mock(return_value=httpx.Response(401, text=NOT_AUTHORIZED))
    with pytest.raises(AuthFailed) as refused:
        await ADAPTER.test(CONFIG, ctx)
    assert "rejected the token" in refused.value.message and "personal access token" in refused.value.hint
    respx.get(f"{BASE}/api/user/repos").mock(return_value=httpx.Response(401, text=NOT_AUTHORIZED))
    with pytest.raises(AuthFailed):
        await ADAPTER.fetch("pipelines", CONFIG, {}, fresh())


@respx.mock
async def test_a_wrong_address_and_an_unreachable_server(ctx: Context) -> None:
    respx.get(f"{BASE}/api/version").mock(return_value=httpx.Response(200, json=["not", "woodpecker"]))
    respx.get(f"{BASE}/api/user").mock(return_value=httpx.Response(200, json={"login": "x"}))
    with pytest.raises(AdapterError) as elsewhere:
        await ADAPTER.test(CONFIG, ctx)
    assert elsewhere.value.code == "not_woodpecker"
    respx.get(f"{BASE}/api/user/repos").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(Unreachable):
        await ADAPTER.fetch("overview", CONFIG, {}, fresh())
