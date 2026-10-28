"""Lemmy, against the answers its API documentation describes.

⚠️ Not recorded from a running Lemmy, which needs PostgreSQL, pict-rs and the
server: three processes, and only one measuring container was allowed. The
answers have the documented shape of API version 3 (Lemmy 0.19 and 0.20); the
card is a beta until somebody runs it against an instance.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context, Unreachable, outbound_client

BASE = "https://lemmy.example.com"
API = f"{BASE}/api/v3"
CONFIG = {"url": BASE, "username": "admin", "password": "made-up-password"}
ADAPTER = get_adapter("lemmy")
SITE = {"version": "0.19.5", "site_view": {"site": {"name": "Example"}, "local_site": {"registration_mode": "RequireApplication"},
                                            "counts": {"users": 410, "posts": 5300, "comments": 21800, "communities": 36, "users_active_day": 18,
                                                       "users_active_week": 61, "users_active_month": 96, "users_active_half_year": 210}}}
REPORTS = {"post_reports": 2, "comment_reports": 3, "private_message_reports": 0, "community_id": None}
NOT_LOGGED_IN = {"error": "not_logged_in"}


@pytest.fixture
def ctx() -> Context:
    return Context(outbound_client(guard=False), integration_id=1, widget_id=1, cache={})


def fresh() -> Context:
    return Context(outbound_client(guard=False), integration_id=2, widget_id=2, cache={})


def lemmy(admin: bool = True) -> None:
    respx.get(f"{API}/site").mock(return_value=httpx.Response(200, json=SITE))
    respx.post(f"{API}/user/login").mock(return_value=httpx.Response(200, json={"jwt": "made-up-jwt", "registration_created": False, "verify_email_sent": False}))
    respx.get(f"{API}/report_count").mock(return_value=httpx.Response(200, json=REPORTS if admin else {"post_reports": 1, "comment_reports": 0, "private_message_reports": None}))
    respx.get(f"{API}/registration_application/count").mock(
        return_value=httpx.Response(200, json={"registration_applications": 4}) if admin else httpx.Response(400, json={"error": "not_an_admin"}))
    respx.get(f"{API}/user/unread_count").mock(return_value=httpx.Response(200, json={"replies": 5, "mentions": 1, "private_messages": 2}))


@respx.mock
async def test_the_instance_card_needs_no_sign_in(ctx: Context) -> None:
    lemmy()
    data = await ADAPTER.fetch("instance", {"url": BASE}, {}, ctx)
    assert data.primary == {"label": "Users", "value": 410}
    assert data.secondary == [{"label": "Posts", "value": 5300}, {"label": "Comments", "value": 21800}, {"label": "Communities", "value": 36},
                              {"label": "Active this month", "value": 96}, {"label": "Active this week", "value": 61},
                              {"label": "Sign-ups", "value": "Needs approval"}, {"label": "Version", "value": "0.19.5"}]
    assert data.metrics == {"users": 410.0, "posts": 5300.0, "active": 96.0}
    assert all("authorization" not in call.request.headers and call.request.method == "GET" for call in respx.calls), "no sign-in for the public figures"


@respx.mock
async def test_the_moderation_card_counts_reports_applications_and_unread_replies(ctx: Context) -> None:
    lemmy()
    data = await ADAPTER.fetch("moderation", CONFIG, {}, ctx)
    assert data.primary == {"label": "Open reports", "value": 5}
    assert data.secondary == [{"label": "Reported posts", "value": 2}, {"label": "Reported comments", "value": 3}, {"label": "Reported messages", "value": 0},
                              {"label": "Applications waiting", "value": 4}, {"label": "Unread replies", "value": 8}]
    assert data.status == "warn" and data.metrics == {"reports": 5.0, "applications": 4.0}
    signed = [call.request for call in respx.calls if call.request.url.path.endswith("/report_count")][0]
    assert signed.headers["authorization"] == "Bearer made-up-jwt"


@respx.mock
async def test_a_moderator_who_is_no_admin_gets_the_reports_and_no_word_about_applications(ctx: Context) -> None:
    lemmy(admin=False)
    data = await ADAPTER.fetch("moderation", CONFIG, {}, ctx)
    labels = [row["label"] for row in data.secondary]
    assert labels == ["Reported posts", "Reported comments", "Unread replies"], "private message reports and applications are the admin's"
    assert data.primary == {"label": "Open reports", "value": 1} and data.metrics["applications"] == 0.0


def test_nothing_waiting_is_green() -> None:
    calm = ADAPTER.moderation_card({"post_reports": 0, "comment_reports": 0}, {"registration_applications": 0}, {})
    assert calm.status == "ok" and calm.primary["value"] == 0
    assert ADAPTER.moderation_card({"post_reports": 0, "comment_reports": 0}, {"registration_applications": 1}, {}).status == "warn"


@respx.mock
async def test_the_session_is_kept_and_replaced_once_when_it_has_run_out(ctx: Context) -> None:
    lemmy()
    login = respx.post(f"{API}/user/login").mock(return_value=httpx.Response(200, json={"jwt": "new-jwt"}))
    route = respx.get(f"{API}/user/unread_count").mock(side_effect=[httpx.Response(400, json=NOT_LOGGED_IN), httpx.Response(200, json={"replies": 1})])
    ctx.cache["lemmy:jwt"] = "old-jwt"
    assert (await ADAPTER._get(CONFIG, ctx, "/user/unread_count", signed=True))["replies"] == 1
    assert login.call_count == 1 and route.calls[0].request.headers["authorization"] == "Bearer old-jwt" and route.calls[1].request.headers["authorization"] == "Bearer new-jwt"


@respx.mock
async def test_a_wrong_password_and_missing_credentials_are_told_apart(ctx: Context) -> None:
    lemmy()
    respx.post(f"{API}/user/login").mock(return_value=httpx.Response(400, json={"error": "incorrect_login"}))
    with pytest.raises(AuthFailed) as wrong:
        await ADAPTER.fetch("moderation", CONFIG, {}, ctx)
    assert "rejected the user name" in wrong.value.message and "two-factor" in wrong.value.hint
    with pytest.raises(AuthFailed) as nobody:
        await ADAPTER.fetch("moderation", {"url": BASE}, {}, fresh())
    assert "needs a user name" in nobody.value.message
    respx.post(f"{API}/user/login").mock(return_value=httpx.Response(200, json={"jwt": None, "registration_created": False, "verify_email_sent": True}))
    with pytest.raises(AdapterError) as waiting:
        await ADAPTER.fetch("moderation", CONFIG, {}, fresh())
    assert waiting.value.code == "no_session"


@respx.mock
async def test_the_test_says_whether_it_signed_in(ctx: Context) -> None:
    lemmy()
    assert await ADAPTER.test({"url": BASE}, ctx) == "Lemmy 0.19.5 answers; the instance figures need no sign-in."
    assert await ADAPTER.test(CONFIG, fresh()) == "Lemmy 0.19.5 accepts the sign-in of admin."


@respx.mock
async def test_a_wrong_address_a_private_instance_and_an_unreachable_one(ctx: Context) -> None:
    respx.get(f"{API}/site").mock(return_value=httpx.Response(404, text="not found"))
    with pytest.raises(AdapterError) as elsewhere:
        await ADAPTER.test({"url": BASE}, ctx)
    assert elsewhere.value.code == "not_lemmy"
    respx.get(f"{API}/site").mock(return_value=httpx.Response(200, json={"hello": "not lemmy"}))
    with pytest.raises(AdapterError) as other:
        await ADAPTER.test({"url": BASE}, fresh())
    assert other.value.code == "not_lemmy"
    respx.get(f"{API}/site").mock(return_value=httpx.Response(400, json={"error": "not_logged_in"}))
    with pytest.raises(AuthFailed):
        await ADAPTER.fetch("instance", {"url": BASE}, {}, fresh())
    respx.get(f"{API}/site").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(Unreachable):
        await ADAPTER.fetch("instance", {"url": BASE}, {}, fresh())
