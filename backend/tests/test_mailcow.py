"""mailcow. NOT measured against a server: mailcow runs over twenty containers and was
not started. The answers below are written after mailcow's OpenAPI file
(``data/web/api/openapi.yaml``) and Postfix's ``postqueue -j`` lines, with made-up
names, so these tests prove the reading, not the server."""

from __future__ import annotations

import time
from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context, Unreachable, outbound_client

CONFIG = {"url": "https://mail.example.com", "api_key": "example-key"}
API = "https://mail.example.com/api/v1"
NOW = 1793124600.0

CONTAINERS = {
    "postfix-mailcow": {"container": "postfix-mailcow", "image": "ghcr.io/mailcow/postfix:1.81", "started_at": "2026-10-18T21:00:08.270660275Z", "state": "running", "type": "info"},
    "clamd-mailcow": {"container": "clamd-mailcow", "image": "ghcr.io/mailcow/clamd:1.71", "started_at": "2026-10-18T21:00:01.622856172Z", "state": "exited", "type": "info"},
}
QUEUE = [
    {"queue_id": "B98C6260CA1", "queue_name": "deferred", "arrival_time": 1793119200, "message_size": 1848,
     "sender": "alice@example.com", "recipients": [
         {"address": "carol@example.net", "delay_reason": "connect to mail.example.net[192.0.2.9]:25: Connection timed out"},
         {"address": "dave@example.net", "delay_reason": ""}]},
    {"queue_id": "C21D4670CB2", "queue_name": "active", "arrival_time": 1793124560, "message_size": 9000,
     "sender": "bob@example.com", "recipients": ["erin@example.org"]},
]
MAILBOXES = [
    {"username": "alice@example.com", "active": 1, "quota": 5 * 1024 ** 3, "quota_used": 2 * 1024 ** 3, "percent_in_use": 40},
    {"username": "bob@example.com", "active": "1", "quota": 1_000_000, "quota_used": 960_000},
    {"username": "old@example.net", "active": 0, "quota": 0, "quota_used": 5000},
]
DOMAINS = [
    {"domain_name": "example.com", "active": "1", "mboxes_in_domain": 2, "max_num_mboxes_for_domain": 10, "quota_used_in_domain": "2147483648", "backupmx": "0"},
    {"domain_name": "example.net", "active": "0", "mboxes_in_domain": 1, "max_num_mboxes_for_domain": 5, "quota_used_in_domain": "0", "backupmx": "1"},
]


@pytest.fixture
def ctx() -> Context:
    return Context(outbound_client(guard=False), integration_id=1, widget_id=1, cache={})


def served(**changed: Any) -> None:
    answers = {"mailq/all": QUEUE, "status/containers": CONTAINERS, "mailbox/all": MAILBOXES, "domain/all": DOMAINS,
               "status/vmail": {"disk": "/dev/sda1", "total": "41G", "type": "info", "used": "11G", "used_percent": "28%"},
               "status/version": {"version": "2026-10"}, **changed}
    for path, body in answers.items():
        respx.get(f"{API}/get/{path}").mock(return_value=httpx.Response(200, json=body))


@respx.mock
async def test_the_overview_counts_the_queue_the_containers_and_the_disk(ctx: Context) -> None:
    served()
    data = await get_adapter("mailcow").fetch("overview", CONFIG, {}, ctx)
    assert data.primary == {"label": "Queued", "value": 2}
    assert data.secondary == [
        {"label": "Mailboxes", "value": 3}, {"label": "Domains", "value": 2},
        {"label": "Containers down", "value": 1}, {"label": "Mail disk", "value": 28.0, "unit": "%"}]
    assert data.status == "bad"
    assert data.metrics == {"queue": 2.0, "containers_down": 1.0}
    assert respx.calls[0].request.headers["X-API-Key"] == "example-key"


@respx.mock
async def test_a_delayed_message_makes_the_overview_yellow_and_a_full_disk_red(ctx: Context) -> None:
    running = {name: {**one, "state": "running"} for name, one in CONTAINERS.items()}
    served(**{"status/containers": running})
    assert (await get_adapter("mailcow").fetch("overview", CONFIG, {}, ctx)).status == "warn"
    ctx.cache.clear()
    served(**{"status/containers": running, "mailq/all": [], "status/vmail": {"used_percent": "97%"}})
    data = await get_adapter("mailcow").fetch("overview", CONFIG, {}, ctx)
    assert data.status == "bad" and data.primary["value"] == 0


@respx.mock
async def test_a_long_queue_is_yellow_even_without_a_reason(ctx: Context) -> None:
    running = {name: {**one, "state": "running"} for name, one in CONTAINERS.items()}
    long = [{"queue_id": f"Q{n}", "queue_name": "active", "arrival_time": 1, "message_size": 1, "sender": "a@example.com", "recipients": ["b@example.org"]}
            for n in range(51)]
    served(**{"status/containers": running, "mailq/all": long, "status/vmail": {}})
    data = await get_adapter("mailcow").fetch("overview", CONFIG, {}, ctx)
    assert data.status == "warn"
    assert "Mail disk" not in [row["label"] for row in data.secondary]


@respx.mock
async def test_without_the_vmail_answer_the_overview_still_comes(ctx: Context) -> None:
    served()
    respx.get(f"{API}/get/status/vmail").mock(return_value=httpx.Response(404, text="nope"))
    data = await get_adapter("mailcow").fetch("overview", CONFIG, {}, ctx)
    assert "Mail disk" not in [row["label"] for row in data.secondary]


@respx.mock
async def test_the_queue_card_puts_the_delayed_first_with_the_reason_postfix_gave(ctx: Context) -> None:
    served()
    data = get_adapter("mailcow")._queue(QUEUE[::-1], {}, NOW)
    first, second = data.items
    assert first["title"] == "alice@example.com → carol@example.net +1"
    assert first["subtitle"] == "connect to mail.example.net[192.0.2.9]:25: Connection timed out · deferred · 1.8 KB · 1 h old"
    assert (first["status"], first["value"]) == ("warn", "Delayed")
    # A recipient that is a plain string, as in the OpenAPI example, is read too.
    assert second["title"] == "bob@example.com → erin@example.org"
    assert (second["status"], second["value"]) == ("ok", "Waiting")
    assert data.status == "warn" and data.secondary == [{"label": "Queued", "value": 2}]
    assert [action.id for action in data.actions] == ["flush"] and data.actions[0].confirm


@respx.mock
async def test_an_empty_queue_offers_nothing_to_flush(ctx: Context) -> None:
    served(**{"mailq/all": []})
    data = await get_adapter("mailcow").fetch("queue", CONFIG, {}, ctx)
    assert data.items == [] and data.actions == [] and data.status == "ok"


@respx.mock
async def test_flushing_posts_the_action_and_a_refusal_names_the_key(ctx: Context) -> None:
    route = respx.post(f"{API}/edit/mailq").mock(return_value=httpx.Response(200, json={"type": "success", "msg": "queue_command_success"}))
    assert await get_adapter("mailcow").action("queue", "flush", {}, CONFIG, {}, ctx) == "The queue is being flushed."
    import json

    assert json.loads(route.calls.last.request.content) == {"action": "flush"}
    assert route.calls.last.request.headers["X-API-Key"] == "example-key"
    route.mock(return_value=httpx.Response(200, json=[{"type": "danger", "msg": "access_denied"}]))
    with pytest.raises(AdapterError) as failure:
        await get_adapter("mailcow").action("queue", "flush", {}, CONFIG, {}, ctx)
    assert failure.value.code == "not_flushed" and "read/write" in (failure.value.hint or "")
    with pytest.raises(AdapterError) as failure:
        await get_adapter("mailcow").action("queue", "delete", {}, CONFIG, {}, ctx)
    assert failure.value.code == "no_such_action"


@respx.mock
async def test_the_containers_card_puts_those_not_running_first(ctx: Context) -> None:
    served()
    data = await get_adapter("mailcow").fetch("containers", CONFIG, {}, ctx)
    assert [(row["title"], row["status"], row["value"]) for row in data.items] == [
        ("clamd-mailcow", "bad", "Exited"), ("postfix-mailcow", "ok", "Running")]
    assert data.items[1]["subtitle"].startswith("ghcr.io/mailcow/postfix:1.81 · up ")
    assert data.items[0]["subtitle"] == "ghcr.io/mailcow/clamd:1.71"
    assert data.status == "bad" and data.secondary == [{"label": "Containers", "value": 2}, {"label": "Containers down", "value": 1}]


@respx.mock
async def test_the_mailboxes_card_is_fullest_first_and_marks_the_switched_off(ctx: Context) -> None:
    served()
    data = await get_adapter("mailcow").fetch("mailboxes", CONFIG, {}, ctx)
    assert [row["title"] for row in data.items] == ["alice@example.com", "bob@example.com", "old@example.net"]
    rows = {row["title"]: row for row in data.items}
    assert rows["alice@example.com"]["subtitle"] == "2.0 GB of 5.0 GB" and rows["alice@example.com"]["status"] == "ok"
    assert rows["bob@example.com"]["status"] == "bad"
    assert rows["old@example.net"]["subtitle"] == "4.9 KB · Switched off"
    assert data.status == "bad" and data.secondary == [{"label": "Mailboxes", "value": 3}]


@respx.mock
async def test_the_domains_card_counts_mailboxes_and_flags_the_switched_off_one(ctx: Context) -> None:
    served()
    data = await get_adapter("mailcow").fetch("domains", CONFIG, {}, ctx)
    assert data.items[0]["title"] == "example.net" and data.items[0]["status"] == "warn"
    assert data.items[0]["subtitle"] == "1 of 5 mailboxes · Switched off · Backup MX"
    assert data.items[1]["subtitle"] == "2 of 10 mailboxes · 2.0 GB"
    assert data.status == "warn"


@respx.mock
async def test_the_connection_test_names_the_release(ctx: Context) -> None:
    served()
    assert await get_adapter("mailcow").test(CONFIG, ctx) == "mailcow 2026-10 answers."
    assert await get_adapter("mailcow").running_version(CONFIG, ctx) is None


@respx.mock
async def test_a_refused_key_arrives_as_a_200_with_an_error_and_is_an_authentication_failure(ctx: Context) -> None:
    respx.get(f"{API}/get/status/version").mock(return_value=httpx.Response(200, json={"type": "error", "msg": "authentication failed"}))
    with pytest.raises(AuthFailed) as failure:
        await get_adapter("mailcow").test(CONFIG, ctx)
    assert "authentication failed" in str(failure.value)


@respx.mock
async def test_a_401_is_an_authentication_failure_too(ctx: Context) -> None:
    respx.get(f"{API}/get/mailq/all").mock(return_value=httpx.Response(401, text="Unauthorized"))
    with pytest.raises(AuthFailed):
        await get_adapter("mailcow").fetch("queue", CONFIG, {}, ctx)


@respx.mock
async def test_a_page_instead_of_the_api_says_so(ctx: Context) -> None:
    respx.get(f"{API}/get/mailq/all").mock(return_value=httpx.Response(200, text="<html>login</html>"))
    with pytest.raises(AdapterError) as failure:
        await get_adapter("mailcow").fetch("queue", CONFIG, {}, ctx)
    assert failure.value.code == "not_json"
    ctx.cache.clear()
    respx.get(f"{API}/get/mailq/all").mock(return_value=httpx.Response(502, text="bad gateway"))
    with pytest.raises(AdapterError) as failure:
        await get_adapter("mailcow").fetch("queue", CONFIG, {}, ctx)
    assert failure.value.code == "http_error"


@respx.mock
async def test_an_unreachable_server_is_unreachable(ctx: Context) -> None:
    respx.get(f"{API}/get/mailq/all").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(Unreachable):
        await get_adapter("mailcow").fetch("queue", CONFIG, {}, ctx)


def test_the_demo_moves_on_every_card_and_stays_in_the_present() -> None:
    mailcow = get_adapter("mailcow")
    started = time.time()
    for kind in ("overview", "queue", "containers", "mailboxes", "domains"):
        data = mailcow.demo(kind, {}, 3)
        assert data.items or data.primary
    assert time.time() - started < 5


@respx.mock
async def test_a_domain_that_mailcow_writes_active_as_true_is_not_switched_off(ctx: Context) -> None:
    served(**{"domain/all": [{**DOMAINS[0], "active": True}, {**DOMAINS[1], "active": "true"}]})
    data = await get_adapter("mailcow").fetch("domains", CONFIG, {}, ctx)
    assert data.status == "ok" and all("Switched off" not in row["subtitle"] for row in data.items)


@respx.mock
async def test_57_the_right_side_says_the_limit_of_a_domain_and_the_space_of_a_mailbox_in_words(ctx: Context) -> None:
    served()
    domains = await get_adapter("mailcow").fetch("domains", CONFIG, {}, ctx)
    assert [row["display"] for row in domains.items] == ["1 / 5", "2 / 10"]
    boxes = await get_adapter("mailcow").fetch("mailboxes", CONFIG, {}, ctx)
    # Still the fullest first, now readable like the line below it.
    assert [row["display"] for row in boxes.items] == ["2.0 GB", "937.5 KB", "4.9 KB"]
    # The numbers stay where the bars read them.
    assert [row["value"] for row in domains.items] == [1, 2] and [row["value"] for row in boxes.items] == [2 * 1024 ** 3, 960_000, 5000]
