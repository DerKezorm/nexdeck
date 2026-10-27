"""PeerTube, against the answers of PeerTube 7.3.0 (chocobozzz/peertube with PostgreSQL 17 and Redis 7, 27.10.2026).

The shapes are the measured ones: the stats, the video list, the OAuth sign-in
with its refusal on a host name PeerTube does not know, the job lists asked
with ``count=0``, a report with its video. Names, addresses and the
secrets are made up.
"""

from __future__ import annotations

import itertools

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context, Unreachable, outbound_client

BASE = "http://peertube.example.com:9000"
API = f"{BASE}/api/v1"
PUBLIC = {"url": BASE}
CONFIG = {"url": BASE, "username": "root", "password": "a-made-up-word"}
ADAPTER = get_adapter("peertube")
NOW = 1_793_124_000.0


def fresh() -> Context:
    return Context(outbound_client(guard=False), integration_id=1, widget_id=1, cache={})


@pytest.fixture
def ctx() -> Context:
    return fresh()


STATS = {"totalUsers": 38, "totalDailyActiveUsers": 3, "totalWeeklyActiveUsers": 11, "totalMonthlyActiveUsers": 21, "totalModerators": 1, "totalAdmins": 1,
         "totalLocalVideos": 214, "totalLocalVideoViews": 48210, "totalLocalVideoComments": 311, "totalLocalVideoFilesSize": 442381631488, "totalVideos": 230,
         "totalVideoComments": 400, "totalInstanceFollowers": 57, "totalInstanceFollowing": 4, "totalAbuses": 3}
VIDEOS = {"total": 214, "data": [
    {"id": 2, "uuid": "11111111-1111-4111-8111-111111111111", "name": "Harbour Lights: the tide", "duration": 1260, "views": 41, "isLocal": True,
     "publishedAt": "2026-10-27T15:30:00.000Z", "channel": {"id": 1, "name": "root_channel", "displayName": "Main channel", "host": "peertube.example.com"}},
    {"id": 1, "uuid": "22222222-2222-4222-8222-222222222222", "name": "Signal Lost", "duration": 3, "views": 0, "isLocal": True,
     "publishedAt": "2026-10-26T09:00:00.000Z", "channel": {"displayName": "Orbital Tide"}}]}
ABUSES = {"total": 2, "data": [
    {"id": 7, "reason": "Spam in the description,   links to a shop", "predefinedReasons": ["spamOrMisleading"], "state": {"id": 1, "label": "Pending"},
     "createdAt": "2026-10-27T14:30:00.000Z", "flaggedAccount": {"name": "root", "displayName": "root"},
     "video": {"id": 1, "name": "Signal Lost", "deleted": False, "blacklisted": False}, "comment": None},
    {"id": 6, "reason": "Rude", "createdAt": "2026-10-26T15:00:00.000Z", "flaggedAccount": {"name": "sam"}, "video": None,
     "comment": {"id": 4, "text": "That was a waste of everybody's time, and of the whole afternoon, honestly, nothing in it"}},
    {"id": 5, "reason": "Impersonation", "createdAt": "2026-10-25T15:00:00.000Z", "flaggedAccount": {"name": "kim", "displayName": "Kim R."}, "video": None, "comment": None}]}


def sign_in(seen: list[httpx.Request] | None = None, expires: int = 86399) -> dict[str, respx.Route]:
    numbers = itertools.count(1)

    def client(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        # Measured: only the host name PeerTube knows itself by gets its client.
        if request.headers.get("host") != "peertube.example.org":
            return httpx.Response(403, json={"type": "about:blank", "title": "Forbidden", "status": 403,
                                              "detail": "Getting client tokens for host peertube.example.com:9000 is forbidden"})
        return httpx.Response(200, json={"client_id": "made-up-client", "client_secret": "made-up-secret"})
    return {
        "client": respx.get(f"{API}/oauth-clients/local").mock(side_effect=client),
        "token": respx.post(f"{API}/users/token").mock(side_effect=lambda _r: httpx.Response(
            200, json={"token_type": "Bearer", "access_token": f"made-up-access-token-{next(numbers)}", "refresh_token": "made-up-refresh",
                       "expires_in": expires})),
    }


HOSTED = {**CONFIG, "host": "peertube.example.org"}


@respx.mock
async def test_the_stats_card_reads_the_public_numbers_without_a_sign_in(ctx: Context) -> None:
    route = respx.get(f"{API}/server/stats").mock(return_value=httpx.Response(200, json=STATS))
    data = await ADAPTER.fetch("stats", PUBLIC, {}, ctx)
    assert data.primary == {"label": "Videos", "value": 214}
    assert data.secondary == [{"label": "Views", "value": 48210}, {"label": "Users", "value": 38}, {"label": "Active this month", "value": 21},
                              {"label": "Storage", "value": "412.0 GB"}, {"label": "Followers", "value": 57}]
    assert data.metrics == {"videos": 214.0, "views": 48210.0}
    assert "authorization" not in route.calls.last.request.headers


@respx.mock
async def test_the_newest_videos_name_channel_length_and_age(ctx: Context) -> None:
    route = respx.get(f"{API}/videos").mock(return_value=httpx.Response(200, json=VIDEOS))
    data = await ADAPTER.fetch("latest", PUBLIC, {"limit": 2}, ctx)
    assert data.items[0]["title"] == "Harbour Lights: the tide" and data.items[0]["value"] == "41 views"
    assert data.items[0]["subtitle"].startswith("Main channel · 21m · ")
    assert data.items[1]["subtitle"].startswith("Orbital Tide · 3s · ")
    assert data.secondary == [{"label": "Videos", "value": 214}]
    query = route.calls.last.request.url.params
    assert (query["count"], query["sort"], query["isLocal"]) == ("2", "-publishedAt", "true")
    await ADAPTER.fetch("latest", PUBLIC, {"local": False}, fresh())
    assert "isLocal" not in route.calls.last.request.url.params


@respx.mock
async def test_an_instance_without_videos_says_so(ctx: Context) -> None:
    respx.get(f"{API}/videos").mock(return_value=httpx.Response(200, json={"total": 0, "data": []}))
    data = await ADAPTER.fetch("latest", PUBLIC, {}, ctx)
    assert (data.items, data.meta["empty"]) == ([], "No video is published.")


@respx.mock
async def test_the_job_queue_counts_waiting_running_and_failed_with_count_zero(ctx: Context) -> None:
    sign_in()
    routes = {state: respx.get(f"{API}/jobs/{state}").mock(return_value=httpx.Response(200, json={"total": total, "data": []}))
              for state, total in (("waiting", 6), ("active", 2), ("failed", 1))}
    data = await ADAPTER.fetch("jobs", HOSTED, {}, ctx)
    assert (data.status, data.primary) == ("warn", {"label": "Waiting", "value": 6})
    assert data.secondary == [{"label": "Running", "value": 2}, {"label": "Failed", "value": 1}]
    assert data.metrics == {"waiting": 6.0, "failed": 1.0}
    assert routes["failed"].calls.last.request.url.params["count"] == "0"
    assert routes["failed"].calls.last.request.headers["authorization"] == "Bearer made-up-access-token-1"
    quiet = ADAPTER.jobs_card({"waiting": 0, "active": 0, "failed": 0})
    assert quiet.status == "ok"


@respx.mock
async def test_the_moderation_card_names_what_each_report_is_about(ctx: Context) -> None:
    sign_in()
    respx.get(f"{API}/abuses").mock(return_value=httpx.Response(200, json=ABUSES))
    registrations = respx.get(f"{API}/users/registrations").mock(return_value=httpx.Response(200, json={"total": 1, "data": []}))
    held = respx.get(f"{API}/videos/blacklist").mock(return_value=httpx.Response(200, json={"total": 0, "data": []}))
    data = await ADAPTER.fetch("moderation", HOSTED, {}, ctx)
    assert data.status == "warn"
    assert [(item["title"], item["subtitle"]) for item in data.items] == [
        ("Video: Signal Lost", "Spam in the description, links to a shop"),
        ("Comment: That was a waste of everybody's time, and of the whole afte…", "Rude"),
        ("Account: Kim R.", "Impersonation")]
    assert data.secondary == [{"label": "Reports", "value": 2}, {"label": "Accounts waiting", "value": 1}, {"label": "Videos held back", "value": 0}]
    assert data.metrics == {"reports": 2.0}
    assert registrations.calls.last.request.url.params["state"] == "pending"
    assert held.calls.last.request.url.params["type"] == "2"


def test_nothing_waiting_is_green_and_says_so() -> None:
    data = ADAPTER.moderation_card({"total": 0, "data": []}, 0, 0, {})
    assert (data.status, data.items, data.meta["empty"]) == ("ok", [], "Nothing waits for a moderator.")
    assert ADAPTER.moderation_card({"total": 0, "data": []}, 0, 2, {}).status == "warn"


@respx.mock
async def test_the_sign_in_sends_the_host_name_and_is_made_once_while_the_token_holds(ctx: Context) -> None:
    seen: list[httpx.Request] = []
    routes = sign_in(seen)
    respx.get(f"{API}/jobs/waiting").mock(return_value=httpx.Response(200, json={"total": 0, "data": []}))
    respx.get(f"{API}/jobs/active").mock(return_value=httpx.Response(200, json={"total": 0, "data": []}))
    respx.get(f"{API}/jobs/failed").mock(return_value=httpx.Response(200, json={"total": 0, "data": []}))
    await ADAPTER.fetch("jobs", HOSTED, {}, ctx)
    ctx.forget_answers()
    await ADAPTER.fetch("jobs", HOSTED, {}, ctx)
    assert routes["token"].call_count == 1
    form = routes["token"].calls.last.request.content.decode()
    assert "grant_type=password" in form and "username=root" in form and "client_id=made-up-client" in form
    assert routes["token"].calls.last.request.headers["host"] == "peertube.example.org"


@respx.mock
async def test_a_token_about_to_run_out_is_made_again(ctx: Context) -> None:
    routes = sign_in(expires=30)
    respx.get(f"{API}/jobs/waiting").mock(return_value=httpx.Response(200, json={"total": 0, "data": []}))
    await ADAPTER._private(HOSTED, ctx, "/api/v1/jobs/waiting")
    ctx.forget_answers()
    await ADAPTER._private(HOSTED, ctx, "/api/v1/jobs/waiting")
    assert routes["token"].call_count == 2


@respx.mock
async def test_a_token_peertube_no_longer_knows_is_replaced_once(ctx: Context) -> None:
    routes = sign_in()
    answers = iter([401, 200, 200, 200, 200])
    respx.get(url__regex=rf"{API}/jobs/.*").mock(side_effect=lambda _r: (
        httpx.Response(401, json={"code": "invalid_token"}) if next(answers) == 401 else httpx.Response(200, json={"total": 3, "data": []})))
    data = await ADAPTER.fetch("jobs", HOSTED, {}, ctx)
    assert routes["token"].call_count == 2 and data.primary["value"] == 3


@respx.mock
async def test_an_internal_address_gets_the_403_and_the_hint_to_fill_in_the_host_name(ctx: Context) -> None:
    sign_in()
    respx.get(f"{API}/config").mock(return_value=httpx.Response(200, json={"serverVersion": "7.3.0"}))
    with pytest.raises(AdapterError) as failure:
        await ADAPTER.test(CONFIG, ctx)
    assert failure.value.code == "wrong_host" and "Host name of the instance" in failure.value.hint


@respx.mock
async def test_a_wrong_password_is_a_refusal_of_the_credentials(ctx: Context) -> None:
    sign_in()
    respx.post(f"{API}/users/token").mock(return_value=httpx.Response(400, json={
        "type": "https://docs.joinpeertube.org/api-rest-reference.html#section/Errors/invalid_grant",
        "detail": "Invalid grant: user credentials are invalid", "status": 400, "code": "invalid_grant"}))
    with pytest.raises(AuthFailed) as failure:
        await ADAPTER.fetch("jobs", HOSTED, {}, ctx)
    assert "user name or the password" in str(failure.value)


@respx.mock
async def test_a_card_that_needs_the_sign_in_says_so_when_there_is_none(ctx: Context) -> None:
    for kind in ("jobs", "moderation"):
        with pytest.raises(AdapterError) as failure:
            await ADAPTER.fetch(kind, PUBLIC, {}, ctx)
        assert failure.value.code == "needs_login"


@respx.mock
async def test_an_account_that_is_not_allowed_to_see_the_queue_is_told_so(ctx: Context) -> None:
    sign_in()
    respx.get(url__regex=rf"{API}/jobs/.*").mock(return_value=httpx.Response(403, json={"detail": "Forbidden"}))
    with pytest.raises(AuthFailed) as failure:
        await ADAPTER.fetch("jobs", HOSTED, {}, ctx)
    assert "does not let this account" in str(failure.value)


@respx.mock
async def test_the_test_names_the_version_and_the_account(ctx: Context) -> None:
    respx.get(f"{API}/config").mock(return_value=httpx.Response(200, json={"serverVersion": "7.3.0", "instance": {"name": "PeerTube"}}))
    assert await ADAPTER.test(PUBLIC, ctx) == "PeerTube 7.3.0 answers."
    assert await ADAPTER.running_version(PUBLIC, fresh()) == "7.3.0"
    sign_in()
    assert await ADAPTER.test(HOSTED, fresh()) == "PeerTube 7.3.0 answers, signed in as root."


@respx.mock
async def test_something_else_at_the_address_is_not_taken_for_peertube(ctx: Context) -> None:
    respx.get(f"{API}/config").mock(return_value=httpx.Response(404, text="nothing"))
    with pytest.raises(AdapterError) as failure:
        await ADAPTER.test(PUBLIC, ctx)
    assert failure.value.code == "not_peertube"
    respx.get(f"{API}/config").mock(return_value=httpx.Response(200, json={"hello": "world"}))
    with pytest.raises(AdapterError) as failure:
        await ADAPTER.test(PUBLIC, fresh())
    assert failure.value.code == "not_peertube"
    respx.get(f"{API}/config").mock(return_value=httpx.Response(200, text="<html></html>"))
    with pytest.raises(AdapterError) as failure:
        await ADAPTER.test(PUBLIC, fresh())
    assert failure.value.code == "not_json"


@respx.mock
async def test_an_unreachable_peertube(ctx: Context) -> None:
    respx.get(f"{API}/server/stats").mock(side_effect=httpx.ConnectError("connection refused"))
    with pytest.raises(Unreachable):
        await ADAPTER.fetch("stats", PUBLIC, {}, ctx)


def test_the_demo_fills_every_card() -> None:
    for tick in range(0, 400, 30):
        assert ADAPTER.demo("stats", {}, tick).primary
        assert ADAPTER.demo("latest", {}, tick).items
        assert ADAPTER.demo("jobs", {}, tick).primary
        assert ADAPTER.demo("moderation", {}, tick).items
