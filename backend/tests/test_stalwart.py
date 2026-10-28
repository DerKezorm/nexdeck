"""Stalwart 1.0. The fixtures were recorded from Stalwart 1.0.0 on 27.10.2026:
two domains, three users and a group, and one message to an address whose
server never answered (``TemporaryFailure`` with a connection error). The
retry and the removal were run for real; their answers are written out here.
Names and addresses are made up."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context, Unreachable, outbound_client
from app.adapters.stalwart import reason_of, state_of

FIXTURES = Path(__file__).parent / "fixtures"
CONFIG = {"url": "http://stalwart:8080", "token": "API_example-key"}
JMAP = "http://stalwart:8080/jmap/"


def recorded(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def ctx() -> Context:
    return Context(outbound_client(guard=False), integration_id=1, widget_id=1, cache={})


def answer(name: str) -> httpx.Response:
    return httpx.Response(200, json=recorded(f"stalwart_{name}.json"))


def sent(call: int = -1) -> dict[str, Any]:
    return json.loads(respx.calls[call].request.content)


@respx.mock
async def test_the_overview_counts_the_queue_the_failing_and_the_directory(ctx: Context) -> None:
    respx.post(JMAP).mock(return_value=answer("overview"))
    data = await get_adapter("stalwart").fetch("overview", CONFIG, {}, ctx)
    assert data.primary == {"label": "Queued", "value": 1}
    assert data.secondary == [
        {"label": "Failing", "value": 1}, {"label": "Accounts", "value": 4}, {"label": "Domains", "value": 2}]
    assert data.status == "warn"
    assert data.metrics == {"queued": 1.0, "failing": 1.0}
    request = respx.calls.last.request
    assert request.headers["Authorization"] == "Bearer API_example-key"
    # The capability that carries the x: objects has to be asked for.
    assert "urn:stalwart:jmap" in sent()["using"]


@respx.mock
async def test_an_empty_queue_is_green(ctx: Context) -> None:
    body = recorded("stalwart_overview.json")
    body["methodResponses"][2][1].update(ids=[], total=0)
    body["methodResponses"][3][1].update(list=[])
    respx.post(JMAP).mock(return_value=httpx.Response(200, json=body))
    data = await get_adapter("stalwart").fetch("overview", CONFIG, {}, ctx)
    assert data.status == "ok" and data.primary["value"] == 0


@respx.mock
async def test_the_queue_card_gives_the_reason_the_server_gave(ctx: Context) -> None:
    respx.post(JMAP).mock(return_value=answer("queue"))
    data = await get_adapter("stalwart").fetch("queue", CONFIG, {}, ctx)
    row = data.items[0]
    assert row["title"] == "alice@example.com → nobody@example.net"
    assert row["subtitle"] == "I/O error: Connection timed out (os error 110) · 1 tries · 80 B"
    assert (row["status"], row["value"]) == ("warn", "Failing")
    assert [action.id for action in row["actions"]] == ["retry", "remove"]
    assert row["actions"][1].danger and row["actions"][1].confirm
    assert not row["actions"][0].danger
    assert data.status == "warn" and data.secondary == [{"label": "Queued", "value": 1}]


@respx.mock
async def test_a_remote_answer_is_shown_with_its_codes(ctx: Context) -> None:
    body = recorded("stalwart_queue.json")
    recipient = next(iter(body["methodResponses"][1][1]["list"][0]["recipients"].values()))
    recipient["status"] = {"@type": "TemporaryFailure", "errorType": "unexpectedResponse", "errorMessage": None,
                           "responseCode": 451, "responseEnhanced": "4.7.1", "responseMessage": "Greylisted,\n try later"}
    respx.post(JMAP).mock(return_value=httpx.Response(200, json=body))
    data = await get_adapter("stalwart").fetch("queue", CONFIG, {}, ctx)
    assert data.items[0]["subtitle"].startswith("451 4.7.1 Greylisted, try later")


@respx.mock
async def test_permanent_failures_come_first_and_are_red_and_waiting_ones_are_green(ctx: Context) -> None:
    body = recorded("stalwart_queue.json")
    message = body["methodResponses"][1][1]["list"][0]
    waiting = {**message, "id": "w1", "recipients": {"a@example.org": {**next(iter(message["recipients"].values())), "status": {"@type": "Scheduled"}, "retryCount": 0},
                                                      "b@example.org": {"retryCount": 0, "status": {"@type": "Scheduled"}}}}
    dead = {**message, "id": "p1", "recipients": {"c@example.org": {"retryCount": 9, "status": {"@type": "PermanentFailure", "responseCode": 550, "responseMessage": "No such user"}}}}
    body["methodResponses"][1][1]["list"] = [waiting, message, dead]
    respx.post(JMAP).mock(return_value=httpx.Response(200, json=body))
    data = await get_adapter("stalwart").fetch("queue", CONFIG, {}, ctx)
    assert [(row["status"], row["value"]) for row in data.items] == [("bad", "Failing"), ("warn", "Failing"), ("ok", "Waiting")]
    assert data.items[0]["subtitle"].startswith("550 No such user")
    assert data.items[2]["title"].endswith("a@example.org +1")
    assert data.items[2]["subtitle"].startswith("Waiting for its turn")
    assert data.status == "bad"


def test_the_state_of_a_message_is_the_worst_of_its_recipients() -> None:
    def one(kind: str) -> dict[str, Any]:
        return {"status": {"@type": kind}}

    assert state_of({"a": one("Completed"), "b": one("TemporaryFailure")}) == "temporary"
    assert state_of({"a": one("Completed"), "b": one("Scheduled")}) == "waiting"
    assert state_of({"a": one("Completed")}) == "done"
    assert state_of({"a": one("TemporaryFailure"), "b": one("PermanentFailure")}) == "permanent"
    assert reason_of({"@type": "Scheduled"}) == ""


@respx.mock
async def test_the_accounts_card_shows_the_fullest_first_and_marks_groups(ctx: Context) -> None:
    respx.post(JMAP).mock(return_value=answer("directory"))
    data = await get_adapter("stalwart").fetch("accounts", CONFIG, {}, ctx)
    rows = {row["title"]: row for row in data.items}
    assert rows["alice@example.com"]["subtitle"] == "3.3 KB of 100.0 MB"
    assert rows["alice@example.com"]["value"] == 3334
    assert rows["team@example.com"]["subtitle"].startswith("Group")
    assert data.items[0]["title"] == "alice@example.com"
    assert data.secondary == [{"label": "Accounts", "value": 4}]


@respx.mock
async def test_an_account_near_its_quota_is_yellow_then_red(ctx: Context) -> None:
    body = recorded("stalwart_directory.json")
    alice = next(one for one in body["methodResponses"][2][1]["list"] if one["name"] == "alice")
    alice["usedDiskQuota"] = 85 * 1024 ** 2
    respx.post(JMAP).mock(return_value=httpx.Response(200, json=body))
    assert (await get_adapter("stalwart").fetch("accounts", CONFIG, {}, ctx)).items[0]["status"] == "warn"
    alice["usedDiskQuota"] = 99 * 1024 ** 2
    respx.post(JMAP).mock(return_value=httpx.Response(200, json=body))
    data = await get_adapter("stalwart").fetch("accounts", CONFIG, {}, ctx)
    assert data.items[0]["status"] == "bad" and data.status == "bad"


@respx.mock
async def test_the_domains_card_counts_the_accounts_of_each(ctx: Context) -> None:
    respx.post(JMAP).mock(return_value=answer("directory"))
    data = await get_adapter("stalwart").fetch("domains", CONFIG, {}, ctx)
    rows = {row["title"]: row for row in data.items}
    assert rows["example.com"]["value"] == 4 and rows["example.net"]["value"] == 0
    assert rows["example.net"]["subtitle"] == "Second domain"
    assert data.secondary == [{"label": "Domains", "value": 2}, {"label": "Accounts", "value": 4}]
    assert data.status == "ok"


@respx.mock
async def test_a_switched_off_domain_turns_the_card_yellow_and_comes_first(ctx: Context) -> None:
    body = recorded("stalwart_directory.json")
    body["methodResponses"][0][1]["list"][1]["enable"] = False
    respx.post(JMAP).mock(return_value=httpx.Response(200, json=body))
    data = await get_adapter("stalwart").fetch("domains", CONFIG, {}, ctx)
    assert (data.items[0]["title"], data.items[0]["status"]) == ("example.net", "warn")
    assert "Switched off" in data.items[0]["subtitle"]
    assert data.status == "warn"


@respx.mock
async def test_retry_now_moves_the_message_and_each_recipient_that_is_not_done(ctx: Context) -> None:
    respx.post(JMAP).mock(side_effect=[
        httpx.Response(200, json={"methodResponses": [["x:QueuedMessage/get", {"list": [{
            "id": "jltbn29kaaaa", "recipients": {
                "nobody@example.net": {"status": {"@type": "TemporaryFailure"}},
                "done/slash@example.org": {"status": {"@type": "Completed"}},
                "odd/one@example.org": {"status": {"@type": "Scheduled"}}}}], "notFound": []}, "one"]]}),
        httpx.Response(200, json={"methodResponses": [["x:QueuedMessage/set", {"updated": {"jltbn29kaaaa": None}}, "set"]]}),
    ])
    message = await get_adapter("stalwart").action("queue", "retry", {"id": "jltbn29kaaaa"}, CONFIG, {}, ctx)
    assert message == "The message will be tried again now."
    update = sent()["methodCalls"][0][1]["update"]["jltbn29kaaaa"]
    assert set(update) == {"nextRetry", "recipients/nobody@example.net/retryDue", "recipients/odd~1one@example.org/retryDue"}
    assert len(set(update.values())) == 1


@respx.mock
async def test_remove_destroys_the_message_and_says_when_it_was_gone(ctx: Context) -> None:
    respx.post(JMAP).mock(return_value=httpx.Response(200, json={"methodResponses": [
        ["x:QueuedMessage/set", {"destroyed": ["jltbn29kaaaa"]}, "set"]]}))
    assert await get_adapter("stalwart").action("queue", "remove", {"id": "jltbn29kaaaa"}, CONFIG, {}, ctx) == "Message removed from the queue."
    assert sent()["methodCalls"][0][1] == {"destroy": ["jltbn29kaaaa"]}
    respx.post(JMAP).mock(return_value=httpx.Response(200, json={"methodResponses": [
        ["x:QueuedMessage/set", {"notDestroyed": {"zzzz": {"type": "notFound"}}}, "set"]]}))
    with pytest.raises(AdapterError) as failure:
        await get_adapter("stalwart").action("queue", "remove", {"id": "zzzz"}, CONFIG, {}, ctx)
    assert failure.value.code == "not_removed"


@respx.mock
async def test_an_id_that_is_not_a_queued_message_never_reaches_the_server(ctx: Context) -> None:
    route = respx.post(JMAP).mock(return_value=httpx.Response(200, json={}))
    for bad in ("", "a/b", "a b", None):
        with pytest.raises(AdapterError) as failure:
            await get_adapter("stalwart").action("queue", "remove", {"id": bad}, CONFIG, {}, ctx)
        assert failure.value.code == "bad_param"
    assert route.call_count == 0


@respx.mock
async def test_the_connection_test_names_the_version_and_the_domains(ctx: Context) -> None:
    session = respx.get("http://stalwart:8080/jmap/session").mock(return_value=answer("session"))
    respx.post(JMAP).mock(return_value=httpx.Response(200, json={"methodResponses": [
        ["x:Domain/query", {"ids": ["c"], "total": 2}, "domains"]]}))
    assert await get_adapter("stalwart").test(CONFIG, ctx) == "Stalwart 1.0.0 answers, 2 domain(s)."
    assert await get_adapter("stalwart").running_version(CONFIG, ctx) == "1.0.0"
    assert session.calls.last.request.headers["Authorization"] == "Bearer API_example-key"


@respx.mock
async def test_a_server_still_in_its_first_setup_says_so(ctx: Context) -> None:
    respx.post(JMAP).mock(return_value=httpx.Response(200, json={"methodResponses": [
        ["error", {"type": "forbidden", "description": "The server is in bootstrap mode. Only the 'Bootstrap' object type can be accessed until the bootstrap process is complete."}, "queueIds"]]}))
    with pytest.raises(AdapterError) as failure:
        await get_adapter("stalwart").fetch("queue", CONFIG, {}, ctx)
    assert failure.value.code == "forbidden" and "bootstrap" in str(failure.value)


@respx.mock
async def test_a_wrong_key_is_an_authentication_failure(ctx: Context) -> None:
    respx.post(JMAP).mock(return_value=httpx.Response(401, json={"type": "about:blank", "status": 401}))
    with pytest.raises(AuthFailed):
        await get_adapter("stalwart").fetch("overview", CONFIG, {}, ctx)


@respx.mock
async def test_an_older_stalwart_or_another_service_is_not_taken_for_one(ctx: Context) -> None:
    respx.post(JMAP).mock(return_value=httpx.Response(200, json={"hello": "world"}))
    with pytest.raises(AdapterError) as failure:
        await get_adapter("stalwart").fetch("overview", CONFIG, {}, ctx)
    assert failure.value.code == "not_jmap"
    respx.post(JMAP).mock(return_value=httpx.Response(404, text="not found"))
    with pytest.raises(AdapterError) as failure:
        await get_adapter("stalwart").fetch("overview", CONFIG, {}, ctx)
    assert failure.value.code == "http_error"


@respx.mock
async def test_an_unreachable_server_is_unreachable(ctx: Context) -> None:
    respx.post(JMAP).mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(Unreachable):
        await get_adapter("stalwart").fetch("overview", CONFIG, {}, ctx)
