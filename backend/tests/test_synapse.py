"""Synapse, against the answers of Synapse 1.164.0 (matrixdotorg/synapse, 27.10.2026).

``fixtures/synapse_answers.json`` holds the real shapes of the Admin API for a
server with three users (one deactivated), two rooms and one reported
message, and the three refusals: 403 for a user who is no admin, 401 for no
token and for a wrong one. Room ids are replaced; the server is ``example.test``.
General had two members when it was measured (the second user was deactivated afterwards, which made it leave) and the rooms come in the order `dir=f` gave. The federation list was empty on the measured server, so its destinations are
made up from Synapse's documentation in the one test that needs them.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context, Unreachable, outbound_client

BASE = "https://matrix.example.com"
ADMIN = f"{BASE}/_synapse/admin"
CONFIG = {"url": BASE, "token": "made-up-token"}
ADAPTER = get_adapter("synapse")
ANSWERS = json.loads((Path(__file__).parent / "fixtures" / "synapse_answers.json").read_text(encoding="utf-8"))


@pytest.fixture
def ctx() -> Context:
    return Context(outbound_client(guard=False), integration_id=1, widget_id=1, cache={})


def fresh() -> Context:
    return Context(outbound_client(guard=False), integration_id=2, widget_id=2, cache={})


def synapse(federation: dict | None = None) -> None:
    def users(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=ANSWERS["users_all"] if request.url.params.get("deactivated") == "true" else ANSWERS["users_active"])

    respx.get(f"{ADMIN}/v2/users").mock(side_effect=users)
    respx.get(f"{ADMIN}/v1/server_version").mock(return_value=httpx.Response(200, json=ANSWERS["version"]))
    respx.get(f"{ADMIN}/v1/rooms").mock(return_value=httpx.Response(200, json=ANSWERS["rooms"]))
    respx.get(f"{ADMIN}/v1/event_reports").mock(return_value=httpx.Response(200, json=ANSWERS["reports"]))
    respx.get(f"{ADMIN}/v1/federation/destinations").mock(return_value=httpx.Response(200, json=federation or ANSWERS["federation"]))


@respx.mock
async def test_the_overview_counts_users_rooms_deactivated_and_reports(ctx: Context) -> None:
    synapse()
    data = await ADAPTER.fetch("overview", CONFIG, {}, ctx)
    assert data.primary == {"label": "Users", "value": 2}
    assert data.secondary == [{"label": "Rooms", "value": 2}, {"label": "Deactivated", "value": 1}, {"label": "Reports", "value": 1}]
    assert data.status == "warn", "a report waits for a moderator"
    assert data.metrics == {"users": 2.0, "rooms": 2.0, "reports": 1.0} and data.link == BASE
    assert respx.calls[0].request.headers["authorization"] == "Bearer made-up-token"
    asked = [call.request.url.params for call in respx.calls if call.request.url.path.endswith("/v2/users")]
    assert {params.get("deactivated") for params in asked} == {None, "true"} and all(params["guests"] == "false" for params in asked)


@respx.mock
async def test_unreachable_servers_are_counted_and_turn_the_card_yellow(ctx: Context) -> None:
    quiet = {**ANSWERS["reports"], "total": 0, "event_reports": []}
    synapse({"total": 3, "destinations": [{"destination": "a.example.net", "failure_ts": 1793147000000, "retry_interval": 60000},
                                          {"destination": "b.example.net", "failure_ts": None}, {"destination": "c.example.net"}]})
    respx.get(f"{ADMIN}/v1/event_reports").mock(return_value=httpx.Response(200, json=quiet))
    data = await ADAPTER.fetch("overview", CONFIG, {}, ctx)
    assert data.status == "warn" and data.secondary[-1] == {"label": "Servers unreachable", "value": 1}
    more = ADAPTER.overview_card({"total": 1}, {"total": 1}, {"total_rooms": 0}, {"total": 0},
                                 {"total": 900, "destinations": [{"destination": "a", "failure_ts": 1}]})
    assert more.secondary[-1] == {"label": "Servers unreachable", "value": "1+"}, "only the first of many were read"
    calm = ADAPTER.overview_card({"total": 1}, {"total": 1}, {"total_rooms": 0}, {"total": 0}, {"total": 0, "destinations": []})
    assert calm.status == "ok" and calm.secondary == [{"label": "Rooms", "value": 0}, {"label": "Reports", "value": 0}]


@respx.mock
async def test_the_reports_card_names_the_room_the_reason_and_who_reported(ctx: Context) -> None:
    synapse()
    data = await ADAPTER.fetch("reports", CONFIG, {"limit": 5}, ctx)
    assert len(data.items) == 1
    row = data.items[0]
    assert row["title"] == "General" and row["subtitle"] == "Spam · by @bob:example.test" and row["status"] == "warn" and row["value"]
    assert data.secondary == [{"label": "Reports", "value": 1}] and data.metrics == {"reports": 1.0}
    assert respx.calls.last.request.url.params["limit"] == "5"
    older, newer = {"name": "A", "reason": "x", "received_ts": 1_000}, {"name": "B", "reason": "y", "received_ts": 2_000}
    assert [row["title"] for row in ADAPTER.reports_card({"event_reports": [older, newer], "total": 2}).items] == ["B", "A"], "the newest first, whatever order came"
    nothing = ADAPTER.reports_card({"event_reports": [{"room_id": "!x:example.test", "reason": "", "received_ts": 0}], "total": 1})
    assert nothing.items[0]["title"] == "Unnamed room" and nothing.items[0]["subtitle"] == "No reason given" and nothing.items[0]["value"] == ""
    assert ADAPTER.reports_card({"event_reports": [], "total": 0}).status == "ok"


@respx.mock
async def test_the_rooms_card_orders_by_members_and_marks_public_and_encrypted(ctx: Context) -> None:
    synapse()
    data = await ADAPTER.fetch("rooms", CONFIG, {}, ctx)
    assert [(row["title"], row["value"], row["subtitle"]) for row in data.items] == [("General", "2", "Public"), ("Private", "1", "Private")]
    assert data.items[0]["progress"] == 100.0 and data.items[1]["progress"] == 50.0
    params = respx.calls.last.request.url.params
    assert params["order_by"] == "joined_members" and params["dir"] == "f", "f is the biggest first; b, measured, is the smallest"
    muddled = ADAPTER.rooms_card({"rooms": [{"name": "Small", "joined_members": 1}, {"name": "Big", "joined_members": 3}]})
    assert [row["title"] for row in muddled.items] == ["Big", "Small"], "sorted again, in case the order comes the other way round"
    encrypted = ADAPTER.rooms_card({"total_rooms": 1, "rooms": [{"canonical_alias": "#family:example.test", "joined_members": 3, "join_rules": "invite", "encryption": "m.megolm.v1.aes-sha2"}]})
    assert encrypted.items[0]["title"] == "#family:example.test" and encrypted.items[0]["subtitle"] == "Private · Encrypted"


@respx.mock
async def test_the_test_asks_for_the_users_because_the_version_answers_without_a_token(ctx: Context) -> None:
    synapse()
    assert await ADAPTER.test(CONFIG, ctx) == "Synapse 1.164.0 accepts the token, 2 users."
    assert respx.calls[0].request.url.path.endswith("/v2/users"), "the version alone would say nothing about the token"


@respx.mock
async def test_each_refusal_is_told_apart(ctx: Context) -> None:
    route = respx.get(f"{ADMIN}/v2/users").mock(return_value=httpx.Response(403, json=ANSWERS["forbidden"]))
    with pytest.raises(AuthFailed) as not_admin:
        await ADAPTER.test(CONFIG, ctx)
    assert "not a server admin" in not_admin.value.message and "admin" in not_admin.value.hint
    route.mock(return_value=httpx.Response(401, json=ANSWERS["unknown_token"]))
    with pytest.raises(AuthFailed) as wrong:
        await ADAPTER.test(CONFIG, fresh())
    assert "rejected the access token" in wrong.value.message and "logged out" in wrong.value.hint
    route.mock(return_value=httpx.Response(401, json=ANSWERS["missing_token"]))
    with pytest.raises(AuthFailed):
        await ADAPTER.test({"url": BASE}, fresh())


@respx.mock
async def test_a_proxy_that_hides_the_admin_api_and_a_wrong_address_are_told_apart(ctx: Context) -> None:
    route = respx.get(f"{ADMIN}/v2/users").mock(return_value=httpx.Response(404, json={"errcode": "M_UNRECOGNIZED", "error": "Unrecognized request"}))
    with pytest.raises(AdapterError) as hidden:
        await ADAPTER.test(CONFIG, ctx)
    assert hidden.value.code == "no_admin_api" and "8008" in hidden.value.hint
    route.mock(return_value=httpx.Response(200, json={"hello": "not synapse"}))
    with pytest.raises(AdapterError) as elsewhere:
        await ADAPTER.test(CONFIG, fresh())
    assert elsewhere.value.code == "not_synapse"
    route.mock(return_value=httpx.Response(429, json={"errcode": "M_LIMIT_EXCEEDED", "retry_after_ms": 2000}))
    with pytest.raises(AdapterError) as limited:
        await ADAPTER.test(CONFIG, fresh())
    assert limited.value.code == "rate_limited"


@respx.mock
async def test_an_old_synapse_without_the_federation_list_still_gives_the_other_figures(ctx: Context) -> None:
    synapse()
    respx.get(f"{ADMIN}/v1/federation/destinations").mock(return_value=httpx.Response(404, json={"errcode": "M_UNRECOGNIZED"}))
    data = await ADAPTER.fetch("overview", CONFIG, {}, ctx)
    assert data.primary == {"label": "Users", "value": 2} and all(row["label"] != "Servers unreachable" for row in data.secondary)


@respx.mock
async def test_an_unreachable_synapse(ctx: Context) -> None:
    respx.get(f"{ADMIN}/v2/users").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(Unreachable):
        await ADAPTER.fetch("overview", CONFIG, {}, ctx)


def test_a_report_a_second_ago_is_dated_in_seconds_since_the_epoch_not_milliseconds() -> None:
    now_ms = time.time() * 1000
    row = ADAPTER.reports_card({"event_reports": [{"name": "Room", "reason": "x", "received_ts": now_ms - 7_200_000}], "total": 1}).items[0]
    assert row["value"] == "2 h"
