"""Mastodon, against the answers its API documentation describes.

⚠️ Not recorded from a running Mastodon, which needs PostgreSQL, Redis, a web,
a streaming and a Sidekiq process: far more than one measuring container. The
answers have the documented shape of Mastodon 4.x; the card is a beta until
somebody runs it against a server.
"""

from __future__ import annotations

import time

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context, Unreachable, outbound_client

BASE = "https://social.example.com"
CONFIG = {"url": BASE, "token": "made-up-token"}
ADAPTER = get_adapter("mastodon")
INSTANCE_V1 = {"uri": "social.example.com", "version": "4.5.0+glitch", "stats": {"user_count": 86, "status_count": 41200, "domain_count": 2310}, "registrations": False,
               "approval_required": True}
INSTANCE_V2 = {"domain": "social.example.com", "title": "Example", "version": "4.5.0+glitch", "usage": {"users": {"active_month": 52}},
               "registrations": {"enabled": True, "approval_required": True}}
ME = {"id": "1", "username": "me", "acct": "me", "followers_count": 312, "following_count": 180, "statuses_count": 1420, "last_status_at": "2026-10-26",
      "url": "https://social.example.com/@me"}


@pytest.fixture
def ctx() -> Context:
    return Context(outbound_client(guard=False), integration_id=1, widget_id=1, cache={})


def fresh() -> Context:
    return Context(outbound_client(guard=False), integration_id=2, widget_id=2, cache={})


def stamp(seconds: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(time.time() - seconds))


def mastodon() -> None:
    respx.get(f"{BASE}/api/v1/instance").mock(return_value=httpx.Response(200, json=INSTANCE_V1))
    respx.get(f"{BASE}/api/v2/instance").mock(return_value=httpx.Response(200, json=INSTANCE_V2))


@respx.mock
async def test_the_server_card_needs_no_token_and_reads_both_instance_answers(ctx: Context) -> None:
    mastodon()
    data = await ADAPTER.fetch("server", {"url": BASE}, {}, ctx)
    assert data.primary == {"label": "Users", "value": 86}
    assert data.secondary == [{"label": "Posts", "value": 41200}, {"label": "Active this month", "value": 52}, {"label": "Servers known", "value": 2310},
                              {"label": "Sign-ups", "value": "Needs approval"}, {"label": "Version", "value": "4.5.0+glitch"}]
    assert data.metrics == {"users": 86.0, "posts": 41200.0, "active": 52.0}
    assert all("authorization" not in call.request.headers for call in respx.calls), "the public figures are not asked for with the token"


@respx.mock
async def test_without_the_second_instance_answer_the_sign_up_mode_comes_from_the_first(ctx: Context) -> None:
    respx.get(f"{BASE}/api/v1/instance").mock(return_value=httpx.Response(200, json={**INSTANCE_V1, "registrations": True, "approval_required": False}))
    respx.get(f"{BASE}/api/v2/instance").mock(return_value=httpx.Response(404, json={"error": "Record not found"}))
    data = await ADAPTER.fetch("server", {"url": BASE}, {}, ctx)
    assert {"label": "Sign-ups", "value": "Open"} in data.secondary and all(row["label"] != "Active this month" for row in data.secondary)
    closed = ADAPTER.server_card(INSTANCE_V1, {"registrations": {"enabled": False, "approval_required": False}})
    assert {"label": "Sign-ups", "value": "Closed"} in closed.secondary


@respx.mock
async def test_the_account_card_counts_followers_posts_and_unread_notifications(ctx: Context) -> None:
    respx.get(f"{BASE}/api/v1/accounts/verify_credentials").mock(return_value=httpx.Response(200, json=ME))
    respx.get(f"{BASE}/api/v1/notifications/unread_count").mock(return_value=httpx.Response(200, json={"count": 7}))
    data = await ADAPTER.fetch("account", CONFIG, {}, ctx)
    assert data.primary == {"label": "Followers", "value": 312}
    assert data.secondary == [{"label": "Account", "value": "@me"}, {"label": "Following", "value": 180}, {"label": "Posts", "value": 1420},
                              {"label": "Last post", "value": data.secondary[3]["value"]}, {"label": "Unread notifications", "value": 7}]
    assert data.metrics == {"followers": 312.0, "posts": 1420.0, "unread": 7.0} and data.link == "https://social.example.com/@me"
    assert respx.calls[0].request.headers["authorization"] == "Bearer made-up-token"


@respx.mock
async def test_an_older_mastodon_counts_the_unread_ones_after_the_marker(ctx: Context) -> None:
    respx.get(f"{BASE}/api/v1/accounts/verify_credentials").mock(return_value=httpx.Response(200, json=ME))
    respx.get(f"{BASE}/api/v1/notifications/unread_count").mock(return_value=httpx.Response(404, json={"error": "Record not found"}))
    respx.get(f"{BASE}/api/v1/markers").mock(return_value=httpx.Response(200, json={"notifications": {"last_read_id": "500", "version": 3}}))
    route = respx.get(f"{BASE}/api/v1/notifications").mock(return_value=httpx.Response(200, json=[{"id": "501"}, {"id": "502"}]))
    data = await ADAPTER.fetch("account", CONFIG, {}, ctx)
    assert {"label": "Unread notifications", "value": 2} in data.secondary and route.calls.last.request.url.params["since_id"] == "500"
    route.mock(return_value=httpx.Response(200, json=[{"id": str(n)} for n in range(40)]))
    full = await ADAPTER.fetch("account", CONFIG, {}, fresh())
    assert {"label": "Unread notifications", "value": "40+"} in full.secondary, "a full page is at least that many"


@respx.mock
async def test_the_moderation_card_lists_reports_before_sign_ups_with_what_each_is_about(ctx: Context) -> None:
    reports = [{"id": "3", "category": "spam", "comment": "Same link\nin ten replies", "created_at": stamp(7200),
                "target_account": {"id": "9", "username": "promo", "account": {"acct": "promo@example.com"}}}]
    signups = [{"id": "8", "username": "newperson", "created_at": stamp(86400), "invite_request": "I run a small homelab blog", "approved": False,
                "email": "must-not-be-shown@example.com", "ip": "192.0.2.1", "account": {"acct": "newperson"}}]
    r = respx.get(f"{BASE}/api/v1/admin/reports").mock(return_value=httpx.Response(200, json=reports))
    a = respx.get(f"{BASE}/api/v1/admin/accounts").mock(return_value=httpx.Response(200, json=signups))
    data = await ADAPTER.fetch("moderation", CONFIG, {}, ctx)
    assert [(row["title"], row["subtitle"], row["value"]) for row in data.items] == [
        ("Report about promo@example.com", "Spam · Same link in ten replies", "2 h"),
        ("Sign-up of newperson", "Waiting for approval · I run a small homelab blog", "1 d")]
    assert data.status == "warn" and data.metrics == {"reports": 1.0, "signups": 1.0}
    assert data.secondary == [{"label": "Open reports", "value": 1}, {"label": "Sign-ups waiting", "value": 1}]
    assert dict(r.calls.last.request.url.params) == {"resolved": "false", "limit": "40"} and dict(a.calls.last.request.url.params) == {"status": "pending", "limit": "40"}
    assert "must-not-be-shown" not in str(data.model_dump()) and "192.0.2.1" not in str(data.model_dump()), "an address and a mail never reach a card"


def test_a_full_page_of_reports_is_at_least_that_many_and_nothing_waiting_is_green() -> None:
    page = [{"category": "other", "created_at": stamp(60), "target_account": {"account": {"acct": f"u{n}"}}} for n in range(40)]
    assert ADAPTER.moderation_card(page, [], 5).secondary[0] == {"label": "Open reports", "value": "40+"}
    calm = ADAPTER.moderation_card([], [], 5)
    assert calm.status == "ok" and calm.items == [] and calm.metrics == {"reports": 0.0, "signups": 0.0}


@respx.mock
async def test_each_refusal_is_told_apart(ctx: Context) -> None:
    route = respx.get(f"{BASE}/api/v1/admin/reports").mock(return_value=httpx.Response(403, json={"error": "This action is not allowed"}))
    respx.get(f"{BASE}/api/v1/admin/accounts").mock(return_value=httpx.Response(200, json=[]))
    with pytest.raises(AuthFailed) as scope:
        await ADAPTER.fetch("moderation", CONFIG, {}, ctx)
    assert "may not read" in scope.value.message and "admin:read:reports" in scope.value.hint
    route.mock(return_value=httpx.Response(401, json={"error": "The access token is invalid"}))
    with pytest.raises(AuthFailed) as wrong:
        await ADAPTER.fetch("moderation", CONFIG, {}, fresh())
    assert "rejected the access token" in wrong.value.message
    with pytest.raises(AuthFailed) as missing:
        await ADAPTER.fetch("account", {"url": BASE}, {}, fresh())
    assert "needs an access token" in missing.value.message


@respx.mock
async def test_the_test_names_the_version_and_the_user_when_there_is_a_token(ctx: Context) -> None:
    mastodon()
    respx.get(f"{BASE}/api/v1/accounts/verify_credentials").mock(return_value=httpx.Response(200, json=ME))
    assert await ADAPTER.test(CONFIG, ctx) == "Mastodon 4.5.0+glitch accepts the token of me."
    assert await ADAPTER.test({"url": BASE}, fresh()) == "Mastodon 4.5.0+glitch answers; the server figures need no token."


@respx.mock
async def test_a_wrong_address_and_an_unreachable_server(ctx: Context) -> None:
    respx.get(f"{BASE}/api/v2/instance").mock(return_value=httpx.Response(200, json={"hello": "not mastodon"}))
    with pytest.raises(AdapterError) as elsewhere:
        await ADAPTER.test({"url": BASE}, ctx)
    assert elsewhere.value.code == "not_mastodon"
    respx.get(f"{BASE}/api/v1/instance").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(Unreachable):
        await ADAPTER.fetch("server", {"url": BASE}, {}, fresh())
