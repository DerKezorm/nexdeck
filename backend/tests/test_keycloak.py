"""Keycloak. The fixtures were recorded from Keycloak 26 (start-dev) on 27.10.2026: a
master realm, a realm "example" with events on (three users, two sessions, a few failed
sign-ins) and a realm "lab" with events off, read by a client in the master realm whose
service account holds the view roles of all three. Names and addresses are made up."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context, Unreachable, outbound_client

FIXTURES = Path(__file__).parent / "fixtures"
CONFIG = {"url": "https://keycloak.example.com", "realm": "master", "client_id": "nexdeck", "client_secret": "example-secret"}
BASE = "https://keycloak.example.com"
ADMIN = f"{BASE}/admin/realms"
TOKEN = f"{BASE}/realms/master/protocol/openid-connect/token"
#: The recorded events are from 1793139905; "now" a minute later, so all are inside 24 hours.
NOW = 1793139995.0


def recorded(name: str) -> Any:
    return json.loads((FIXTURES / f"keycloak_{name}.json").read_text(encoding="utf-8"))


@pytest.fixture
def ctx() -> Context:
    return Context(outbound_client(guard=False), integration_id=1, widget_id=1, cache={})


def served(*, errors: list[dict[str, Any]] | None = None) -> respx.Route:
    token = respx.post(TOKEN).mock(return_value=httpx.Response(200, json=recorded("token")))
    respx.get(ADMIN, params={"briefRepresentation": "true"}).mock(return_value=httpx.Response(200, json=recorded("realms")))
    for realm, users, stats in (("master", 1, "stats_master"), ("example", 3, "stats_example"), ("lab", 0, None)):
        respx.get(f"{ADMIN}/{realm}/users/count").mock(return_value=httpx.Response(200, json=users))
        respx.get(f"{ADMIN}/{realm}/client-session-stats").mock(return_value=httpx.Response(200, json=recorded(stats) if stats else []))
    respx.get(f"{ADMIN}/master/events/config").mock(return_value=httpx.Response(200, json={"eventsEnabled": False, "enabledEventTypes": []}))
    respx.get(f"{ADMIN}/example/events/config").mock(return_value=httpx.Response(200, json=recorded("eventsconfig_example")))
    respx.get(f"{ADMIN}/lab/events/config").mock(return_value=httpx.Response(200, json=recorded("eventsconfig_lab")))
    respx.get(f"{ADMIN}/example/events").mock(return_value=httpx.Response(200, json=errors if errors is not None else recorded("errors")))
    return token


@respx.mock
async def test_the_overview_adds_sessions_users_and_failures_of_the_realms_that_keep_events(ctx: Context) -> None:
    served()
    data = get_adapter("keycloak")._overview(await get_adapter("keycloak")._realms(CONFIG, ctx, None), NOW)
    assert data.primary == {"label": "Sessions", "value": 5}  # three for the admin console, two for the app
    assert data.secondary == [{"label": "Realms", "value": 3}, {"label": "Users", "value": 4},
                              {"label": "Failed sign-ins in 24 h", "value": 6}]
    assert data.metrics == {"sessions": 5.0, "failed_logins": 6.0}
    assert data.status == "ok"


@respx.mock
async def test_the_token_is_fetched_once_for_all_calls_and_sent_as_a_bearer(ctx: Context) -> None:
    token = served()
    await get_adapter("keycloak").fetch("overview", CONFIG, {}, ctx)
    assert token.call_count == 1
    form = token.calls.last.request.content.decode()
    assert "grant_type=client_credentials" in form and "client_id=nexdeck" in form
    sent = {call.request.headers["Authorization"] for call in respx.calls if call.request.url.path.startswith("/admin")}
    assert sent == {"Bearer example-token"}
    await get_adapter("keycloak").fetch("realms", CONFIG, {}, ctx)
    assert token.call_count == 1


@respx.mock
async def test_a_token_that_ran_out_is_fetched_again(ctx: Context) -> None:
    token = served()
    await get_adapter("keycloak").fetch("overview", CONFIG, {}, ctx)
    ctx.cache["keycloak.token"] = (time.monotonic() - 1, "stale")
    await get_adapter("keycloak").fetch("overview", CONFIG, {}, ctx)
    assert token.call_count == 2


@respx.mock
async def test_without_events_the_overview_says_off_and_does_not_count_zero_failures(ctx: Context) -> None:
    served()
    respx.get(f"{ADMIN}/example/events/config").mock(return_value=httpx.Response(200, json={"eventsEnabled": False}))
    data = await get_adapter("keycloak").fetch("overview", CONFIG, {}, ctx)
    assert {"label": "Events", "value": "Off"} in data.secondary
    assert "failed_logins" not in data.metrics


@respx.mock
async def test_ten_failures_make_the_overview_yellow_and_fifty_red(ctx: Context) -> None:
    now = time.time()
    many = [{"time": (now - 60) * 1000, "type": "LOGIN_ERROR", "error": "invalid_user_credentials", "details": {"username": "x"}}] * 10
    served(errors=many)
    assert (await get_adapter("keycloak").fetch("overview", CONFIG, {}, ctx)).status == "warn"
    ctx.cache.clear()
    served(errors=many * 5)
    assert (await get_adapter("keycloak").fetch("overview", CONFIG, {}, ctx)).status == "bad"


@respx.mock
async def test_the_realms_card_gives_users_failures_and_marks_a_realm_without_events(ctx: Context) -> None:
    served()
    realms = await get_adapter("keycloak")._realms(CONFIG, ctx, None)
    data = get_adapter("keycloak")._realm_list(realms, NOW)
    rows = {row["title"]: row for row in data.items}
    assert rows["example"]["subtitle"] == "3 users · 6 failed" and rows["example"]["value"] == 2
    assert rows["lab"]["subtitle"] == "0 users · Events off"
    assert rows["master"]["subtitle"] == "1 users · Events off" and rows["master"]["value"] == 3
    assert data.secondary == [{"label": "Realms", "value": 3}]


@respx.mock
async def test_a_realm_the_account_may_not_read_is_grey_and_does_not_fail_the_card(ctx: Context) -> None:
    served()
    respx.get(f"{ADMIN}/lab/users/count").mock(return_value=httpx.Response(403, json={"error": "HTTP 403 Forbidden"}))
    realms = await get_adapter("keycloak")._realms(CONFIG, ctx, None)
    row = next(row for row in get_adapter("keycloak")._realm_list(realms, NOW).items if row["title"] == "lab")
    assert (row["status"], row["subtitle"]) == ("unknown", "No access")
    assert get_adapter("keycloak")._overview(realms, NOW).secondary[0] == {"label": "Realms", "value": 3}


@respx.mock
async def test_a_disabled_realm_turns_the_card_yellow(ctx: Context) -> None:
    served()
    realms = recorded("realms")
    next(one for one in realms if one["realm"] == "lab")["enabled"] = False
    respx.get(ADMIN, params={"briefRepresentation": "true"}).mock(return_value=httpx.Response(200, json=realms))
    data = get_adapter("keycloak")._realm_list(await get_adapter("keycloak")._realms(CONFIG, ctx, None), NOW)
    assert data.status == "warn" and data.items[0]["title"] == "lab"


@respx.mock
async def test_the_failed_card_names_user_client_address_and_reason_newest_first(ctx: Context) -> None:
    served()
    realms = await get_adapter("keycloak")._realms(CONFIG, ctx, None)
    data = get_adapter("keycloak")._failed(realms, {"limit": 3}, NOW)
    assert len(data.items) == 3
    first = data.items[0]
    assert first["title"] == "nosuch" and first["value"] == "User not found"
    assert first["subtitle"] == "example · app · 192.0.2.50 · 1 min ago"
    assert data.items[1]["value"] == "Wrong password" and data.items[1]["title"] == "carol"
    assert data.status == "warn" and data.secondary == [{"label": "Realms with events", "value": 1}]


@respx.mock
async def test_no_realm_with_events_leaves_the_failed_card_unknown_not_green(ctx: Context) -> None:
    served()
    respx.get(f"{ADMIN}/example/events/config").mock(return_value=httpx.Response(200, json={"eventsEnabled": False}))
    data = await get_adapter("keycloak").fetch("failed", CONFIG, {}, ctx)
    assert data.status == "unknown" and data.items == []


@respx.mock
async def test_the_dateFrom_cut_is_applied_again_on_the_exact_time(ctx: Context) -> None:
    now = time.time()
    old = {"time": (now - 3 * 86400) * 1000, "error": "invalid_user_credentials", "details": {"username": "old"}}
    served(errors=[old])
    data = await get_adapter("keycloak").fetch("overview", CONFIG, {}, ctx)
    assert {"label": "Failed sign-ins in 24 h", "value": 0} in data.secondary


@respx.mock
async def test_a_refused_client_is_an_authentication_failure_with_keycloaks_reason(ctx: Context) -> None:
    respx.post(TOKEN).mock(return_value=httpx.Response(401, json={"error": "unauthorized_client", "error_description": "Invalid client or Invalid client credentials"}))
    with pytest.raises(AuthFailed) as failure:
        await get_adapter("keycloak").fetch("overview", CONFIG, {}, ctx)
    assert "Invalid client credentials" in str(failure.value)


@respx.mock
async def test_a_token_that_expired_between_two_calls_is_replaced_once(ctx: Context) -> None:
    token = respx.post(TOKEN).mock(return_value=httpx.Response(200, json=recorded("token")))
    route = respx.get(ADMIN, params={"briefRepresentation": "true"}).mock(side_effect=[httpx.Response(401), httpx.Response(200, json=[])])
    assert await get_adapter("keycloak").test(CONFIG, ctx) == "Keycloak answers, 0 realm(s)."
    assert token.call_count == 2 and route.call_count == 2


@respx.mock
async def test_an_account_that_may_not_list_realms_is_told_what_to_grant(ctx: Context) -> None:
    served()
    respx.get(ADMIN, params={"briefRepresentation": "true"}).mock(return_value=httpx.Response(403, json={"error": "HTTP 403 Forbidden"}))
    with pytest.raises(AdapterError) as failure:
        await get_adapter("keycloak").fetch("overview", CONFIG, {}, ctx)
    assert failure.value.code == "no_rights" and "view-realm" in (failure.value.hint or "")


@respx.mock
async def test_the_version_is_known_only_when_serverinfo_gives_it(ctx: Context) -> None:
    served()
    route = respx.get(f"{BASE}/admin/serverinfo").mock(return_value=httpx.Response(200, json={"profileInfo": {}}))
    assert await get_adapter("keycloak").running_version(CONFIG, ctx) is None
    ctx.cache.clear()
    route.mock(return_value=httpx.Response(200, json={"systemInfo": {"version": "26.3.1"}}))
    assert await get_adapter("keycloak").running_version(CONFIG, ctx) == "26.3.1"


@respx.mock
async def test_another_service_instead_of_keycloak_is_told_apart(ctx: Context) -> None:
    respx.post(TOKEN).mock(return_value=httpx.Response(200, text="<html></html>"))
    with pytest.raises(AdapterError) as failure:
        await get_adapter("keycloak").fetch("overview", CONFIG, {}, ctx)
    assert failure.value.code == "no_token"
    respx.post(TOKEN).mock(return_value=httpx.Response(404, text="Not Found"))
    with pytest.raises(AdapterError) as failure:
        await get_adapter("keycloak").fetch("overview", CONFIG, {}, outbound_ctx())
    assert failure.value.code == "http_error"


def outbound_ctx() -> Context:
    return Context(outbound_client(guard=False), integration_id=2, widget_id=2, cache={})


@respx.mock
async def test_an_unreachable_server_is_unreachable(ctx: Context) -> None:
    respx.post(TOKEN).mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(Unreachable):
        await get_adapter("keycloak").fetch("overview", CONFIG, {}, ctx)
