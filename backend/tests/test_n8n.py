"""n8n: workflows, runs, and the two names one action has.

⚠️ The endpoints here were read out of n8n's own OpenAPI spec, not out of
memory. The one that matters: publishing a workflow is ``/publish`` in the
current API and ``/activate`` in every 1.x instance, where the newer name does
not exist. Upstream marks the old pair deprecated. Picking one would fail on
half the installations out there, so the action tries the new name and falls
back on a 404.

The other trap is the 404 that is not a missing workflow: n8n has a switch
that turns the public API off entirely, and then every address under /api/v1
is gone. Reading that as "no such thing" would send somebody looking for a
workflow that is right there.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context

N8N = "http://n8n.example.com:5678"
CONFIG = {"url": N8N, "api_key": "a-key", "insecure": False}

WORKFLOWS = {"data": [
    {"id": "w1", "name": "Backup to the NAS", "active": True, "isArchived": False, "tags": [{"name": "nightly"}]},
    {"id": "w2", "name": "Test bench", "active": False, "isArchived": False, "tags": []},
    {"id": "w3", "name": "Old thing", "active": False, "isArchived": True, "tags": []},
]}
RUNS = {"data": [
    {"id": 1, "workflowId": "w1", "status": "success", "mode": "trigger",
     "startedAt": "2026-09-08T10:00:00.000Z", "stoppedAt": "2026-09-08T10:00:02.500Z"},
    {"id": 2, "workflowId": "w2", "status": "error", "mode": "manual",
     "startedAt": "2026-09-08T09:00:00.000Z", "stoppedAt": "2026-09-08T09:00:00.120Z"},
    {"id": 3, "workflowId": "w1", "status": "waiting", "mode": "webhook",
     "startedAt": "2026-09-08T08:00:00.000Z", "stoppedAt": None},
]}


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


def _n8n(workflows: dict | None = None, runs: dict | None = None) -> None:
    respx.get(f"{N8N}/api/v1/workflows").mock(return_value=httpx.Response(200, json=workflows or WORKFLOWS))
    respx.get(f"{N8N}/api/v1/executions").mock(return_value=httpx.Response(200, json=runs or RUNS))


def _value(data, label: str):
    return next((row.get("value") for row in data.secondary if row.get("label") == label), None)


@respx.mock
async def test_the_workflow_card_lists_them_with_a_button_each(ctx: Context) -> None:
    _n8n()
    data = await get_adapter("n8n").fetch("workflows", CONFIG, {}, ctx)

    # ⚠️ The archived one is left out. It was put away on purpose, and a row
    # nobody can act on is a row that only makes the list longer.
    assert [one["title"] for one in data.items] == ["Backup to the NAS", "Test bench"]
    assert data.items[0]["status"] == "ok" and data.items[1]["status"] == "unknown"
    assert [action.id for action in data.items[0]["actions"]] == ["unpublish"]
    assert [action.id for action in data.items[1]["actions"]] == ["publish"]
    assert _value(data, "Published") == 1
    assert _value(data, "Workflows") == 2


@respx.mock
async def test_the_run_card_says_which_failed_and_how_long_each_took(ctx: Context) -> None:
    _n8n()
    data = await get_adapter("n8n").fetch("runs", CONFIG, {}, ctx)

    assert data.status == "bad", "a failed run has to colour the card"
    # The run carries a workflow id, not a name; the card shows the name.
    assert data.items[0]["title"] == "Backup to the NAS"
    assert data.items[0]["value"] == "2.5 s"
    assert data.items[1]["status"] == "bad"
    assert data.items[1]["value"] == "120 ms"
    # ⚠️ A waiting run is not a failure. A workflow that waits for a webhook
    # is doing its job, and colouring it red would train people to ignore red.
    assert data.items[2]["status"] == "unknown"
    assert data.items[2]["value"] == "", "a run that has not finished has no duration to give"
    assert _value(data, "Failed") == 1


@respx.mock
async def test_only_the_failed_ones_when_that_is_asked(ctx: Context) -> None:
    _n8n()
    data = await get_adapter("n8n").fetch("runs", CONFIG, {"failed_only": True}, ctx)
    assert [one["title"] for one in data.items] == ["Test bench"]
    # The count underneath still speaks about every run that was read.
    assert _value(data, "Runs") == 3


@respx.mock
async def test_the_summary_says_what_the_share_is_of(ctx: Context) -> None:
    """⚠️ A share of the runs that were read, with the number beside it. "33%
    failed" about a window whose size is not on the card is a figure nobody
    can check."""
    _n8n()
    data = await get_adapter("n8n").fetch("summary", CONFIG, {}, ctx)

    assert data.primary["value"] == 1 and data.primary["unit"] == "/ 2"
    assert _value(data, "Failed runs") == 1
    assert _value(data, "Of the last") == 3
    assert _value(data, "Failure rate") == 33.3
    assert data.metrics == {"active": 1.0, "failed": 1.0}


@respx.mock
async def test_a_refused_key_says_so(ctx: Context) -> None:
    respx.get(f"{N8N}/api/v1/workflows").mock(return_value=httpx.Response(401, json={"message": "unauthorized"}))
    with pytest.raises(AuthFailed):
        await get_adapter("n8n").fetch("workflows", CONFIG, {}, ctx)


@respx.mock
async def test_a_switched_off_public_api_is_not_a_missing_workflow(ctx: Context) -> None:
    """⚠️ n8n can turn the whole public API off, and then every address under
    /api/v1 answers 404. "Not found" would send somebody looking for a
    workflow that is sitting right there."""
    respx.get(f"{N8N}/api/v1/workflows").mock(return_value=httpx.Response(404, text="<html>not found</html>"))
    with pytest.raises(AdapterError) as off:
        await get_adapter("n8n").fetch("workflows", CONFIG, {}, ctx)
    assert off.value.code == "no_public_api"
    assert "public API" in str(off.value)


@respx.mock
async def test_something_that_is_not_json_is_a_message_not_a_crash(ctx: Context) -> None:
    respx.get(f"{N8N}/api/v1/workflows").mock(return_value=httpx.Response(200, text="<html>a sign-in page</html>"))
    with pytest.raises(AdapterError) as garbled:
        await get_adapter("n8n").fetch("workflows", CONFIG, {}, ctx)
    assert garbled.value.code == "bad_json"


# ---------------------------------------------------------------------------
# The action, and the two names it has
# ---------------------------------------------------------------------------


@respx.mock
async def test_publishing_uses_the_current_name(ctx: Context) -> None:
    now = respx.post(f"{N8N}/api/v1/workflows/w2/publish").mock(return_value=httpx.Response(200, json={}))
    old = respx.post(f"{N8N}/api/v1/workflows/w2/activate").mock(return_value=httpx.Response(200, json={}))

    said = await get_adapter("n8n").action("workflows", "publish", {"id": "w2"}, CONFIG, {}, ctx)
    assert now.called and not old.called, "the deprecated name was used although the current one answered"
    assert "published" in said.lower()


@respx.mock
async def test_it_falls_back_to_the_name_a_1x_instance_has(ctx: Context) -> None:
    """⚠️ The whole reason this is not one call. /publish does not exist on a
    1.x instance, and that is most of them."""
    respx.post(f"{N8N}/api/v1/workflows/w2/publish").mock(return_value=httpx.Response(404, json={"message": "not found"}))
    old = respx.post(f"{N8N}/api/v1/workflows/w2/activate").mock(return_value=httpx.Response(200, json={}))

    said = await get_adapter("n8n").action("workflows", "publish", {"id": "w2"}, CONFIG, {}, ctx)
    assert old.called
    assert "published" in said.lower()


@respx.mock
async def test_unpublishing_has_the_same_pair(ctx: Context) -> None:
    respx.post(f"{N8N}/api/v1/workflows/w1/unpublish").mock(return_value=httpx.Response(404, json={}))
    old = respx.post(f"{N8N}/api/v1/workflows/w1/deactivate").mock(return_value=httpx.Response(200, json={}))

    said = await get_adapter("n8n").action("workflows", "unpublish", {"id": "w1"}, CONFIG, {}, ctx)
    assert old.called
    assert "unpublished" in said.lower()


@respx.mock
async def test_neither_name_answering_says_that_rather_than_nothing(ctx: Context) -> None:
    respx.post(f"{N8N}/api/v1/workflows/w1/publish").mock(return_value=httpx.Response(404, json={}))
    respx.post(f"{N8N}/api/v1/workflows/w1/activate").mock(return_value=httpx.Response(404, json={}))
    with pytest.raises(AdapterError) as neither:
        await get_adapter("n8n").action("workflows", "publish", {"id": "w1"}, CONFIG, {}, ctx)
    assert neither.value.code == "action_failed"


@respx.mock
async def test_an_action_nobody_offers_is_refused(ctx: Context) -> None:
    with pytest.raises(AdapterError) as no:
        await get_adapter("n8n").action("workflows", "delete", {"id": "w1"}, CONFIG, {}, ctx)
    assert no.value.code == "no_such_action"


@respx.mock
async def test_a_workflow_id_cannot_carry_a_path(ctx: Context) -> None:
    """⚠️ The id comes back from the browser with the action. Without a check
    it is a piece of an address that somebody else chose."""
    with pytest.raises(AdapterError):
        await get_adapter("n8n").action("workflows", "publish", {"id": "../../users"}, CONFIG, {}, ctx)


@respx.mock
async def test_the_connection_test_counts_the_published_ones(ctx: Context) -> None:
    _n8n()
    said = await get_adapter("n8n").test(CONFIG, ctx)
    assert "n8n answers" in said
