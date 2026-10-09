"""nginx ignition, against recorded answers from its own source.

No test here touches the network. What is checked is the part that can be
wrong without anybody noticing: the shape nginx ignition answers with, the
three ways its statistics cannot be read, the buttons a token may not press, and
the certificate with no date that would otherwise be 739000 days in the past.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, Context, WidgetData

BASE = "http://nginx-ignition:8090"
CONFIG = {"url": BASE, "token": "eyJhbGciOiJIUzUxMiJ9.body.signature"}
ONE = {"pageSize": 1, "pageNumber": 0}
FULL = {"pageSize": 1000, "pageNumber": 0}
EVERY_PERMISSION = (
    "hosts", "streams", "certificates", "logs", "integrations", "accessLists",
    "settings", "users", "nginxServer", "exportData", "vpns", "caches", "trafficStats",
)


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


def again() -> Context:
    """A context with an empty cache, for a second reading in one test.

    Answers are held per integration for as long as the card asked for, so
    three cases in one test would otherwise all read the first one's answer.
    """
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


def in_days(days: float) -> str:
    """A timestamp ``days`` from now, plus half a day of slack.

    A card counts whole days left, and a timestamp of exactly four days is four
    days and a minute ago by the time the test reads it.
    """
    return (datetime.now(UTC) + timedelta(days=days + 0.5)).isoformat().replace("+00:00", "Z")


def certificate(name: str, days: float | None) -> dict[str, Any]:
    """One certificate as nginx ignition writes it."""
    return {
        "validUntil": in_days(days) if days is not None else "0001-01-01T00:00:00Z",
        "id": "cert-" + name.replace(".", "-"),
        "providerId": "letsencrypt",
        "domainNames": [name],
    }


def page(contents: list[dict[str, Any]] | None = None, total: int | None = None) -> dict[str, Any]:
    """A list answer, with totalItems counting the whole set."""
    rows = contents if contents is not None else []
    return {"contents": rows, "pageNumber": 0, "pageSize": len(rows),
            "totalItems": total if total is not None else len(rows)}


def mock_permissions(nginx: str = "READ_ONLY", certificates: str = "READ_ONLY") -> None:
    """A user with these two permissions and no access to the rest."""
    granted = {name: "READ_ONLY" for name in EVERY_PERMISSION}
    granted["nginxServer"] = nginx
    granted["certificates"] = certificates
    respx.get(f"{BASE}/api/users/current").mock(return_value=httpx.Response(200, json={
        "id": "u1", "name": "Admin", "username": "admin", "enabled": True, "totpEnabled": False,
        "permissions": granted,
    }))


def mock_metadata(*, version: str = "1.27.0", stats: bool = True, support: str = "DYNAMIC") -> None:
    respx.get(f"{BASE}/api/nginx/metadata").mock(return_value=httpx.Response(200, json={
        "version": version,
        "stats": {"enabled": stats, "allHosts": False},
        "availableSupport": {"streams": "DYNAMIC", "runCode": "NONE", "tlsSni": "DYNAMIC",
                             "stats": support, "grpc": "NONE"},
    }))


def mock_running(running: bool = True, uptime: int | None = 97_200) -> None:
    respx.get(f"{BASE}/api/nginx/status").mock(return_value=httpx.Response(200, json={
        "running": running, "uptimeSeconds": uptime if running else None,
    }))


def mock_frontend(current: str | None = "2.47.0") -> None:
    respx.get(f"{BASE}/api/frontend/configuration").mock(return_value=httpx.Response(200, json={
        "version": {"current": current, "latest": "2.47.0"},
    }))


def mock_certificates(entries: list[dict[str, Any]], total: int | None = None) -> respx.Route:
    return respx.get(f"{BASE}/api/certificates", params=FULL).mock(
        return_value=httpx.Response(200, json=page(entries, total)))


def statistics(*, requests: int = 184_203, in_bytes: int = 107_374_182_400,
               five: int = 3, four: int = 120, avg_msec: int = 1_250) -> dict[str, Any]:
    """What nginx ignition answers with, the global zone and the connections."""
    return {
        "hostName": "nginx-ignition",
        "connections": {"active": 128, "reading": 18, "writing": 74, "waiting": 36,
                        "accepted": 184_400, "handled": 184_400, "requests": requests},
        "serverZones": {
            "*": {
                "requestCounter": requests, "inBytes": in_bytes, "outBytes": in_bytes // 4,
                "requestMsec": avg_msec, "requestMsecCounter": requests,
                "requestMsecs": {"times": [], "msecs": []},
                "responses": {"1xx": 0, "2xx": 184_000, "3xx": 80, "4xx": four, "5xx": five,
                              "miss": 0, "bypass": 0, "expired": 0, "stale": 0,
                              "updating": 0, "revalidated": 0, "hit": 0, "scarce": 0},
            },
        },
        "filterZones": None,
        "upstreamZones": None,
    }


def labels(data: WidgetData) -> list[tuple[str, Any]]:
    return [(str(row.get("label")), row.get("value")) for row in data.secondary]


@respx.mock
async def test_status_hides_the_buttons_a_read_only_token_may_not_press(ctx: Context) -> None:
    """A token that may only read gets the numbers and no buttons at all."""
    mock_running()
    mock_metadata()
    respx.get(f"{BASE}/api/hosts", params=ONE).mock(return_value=httpx.Response(200, json=page([], 16)))
    respx.get(f"{BASE}/api/streams", params=ONE).mock(return_value=httpx.Response(200, json=page([], 2)))
    mock_certificates([certificate("example.com", 45)], total=3)
    mock_permissions(nginx="READ_ONLY")

    data = await get_adapter("nginxignition").fetch("status", CONFIG, {}, ctx)

    assert data.actions == [], "read is not write"


@respx.mock
async def test_status_offers_each_command_only_where_it_is_the_thing_to_press(ctx: Context) -> None:
    """Starting nginx that already runs reloads it, and reloading nginx that is
    down does nothing, so the buttons follow the state instead of sitting in a row."""
    adapter = get_adapter("nginxignition")
    mock_metadata()
    respx.get(f"{BASE}/api/hosts", params=ONE).mock(return_value=httpx.Response(200, json=page([], 14)))
    respx.get(f"{BASE}/api/streams", params=ONE).mock(return_value=httpx.Response(200, json=page([], 2)))
    mock_certificates([certificate("example.com", 45)], total=3)
    mock_permissions(nginx="READ_WRITE")

    mock_running(uptime=183_600)
    running = await adapter.fetch("status", CONFIG, {}, ctx)
    assert [one.id for one in running.actions] == ["reload", "stop"]
    assert [one.label for one in running.actions] == ["Reload", "Stop"]
    assert [one.confirm for one in running.actions] == [True, True], "acting on nginx asks first"
    assert [one.danger for one in running.actions] == [False, True], "stopping the proxy stops everything behind it"
    assert running.primary == {"label": "Uptime", "value": "2d 3h"}

    mock_running(running=False)
    stopped = await adapter.fetch("status", CONFIG, {}, again())
    assert [one.id for one in stopped.actions] == ["start"]
    assert [one.confirm for one in stopped.actions] == [True]
    assert stopped.primary == {"label": "State", "value": "Stopped"}
    assert stopped.status == "bad", "a server that is not running is not ok"


@respx.mock
async def test_status_counts_what_there_is_and_says_which_nginx(ctx: Context) -> None:
    """Three counts and a version. The counts come from totalItems beside a
    page of one, so a card that wants a number does not pay for every record."""
    mock_running(uptime=183_600)
    mock_metadata(version="1.27.0")
    hosts = respx.get(f"{BASE}/api/hosts", params=ONE).mock(
        return_value=httpx.Response(200, json=page([{"id": "h1", "domainNames": ["deck.example.com"]}], 16)))
    respx.get(f"{BASE}/api/streams", params=ONE).mock(return_value=httpx.Response(200, json=page([{"id": "s1"}], 2)))
    mock_certificates([certificate("example.com", 45), certificate("mail.example.org", 60),
                       certificate("old.example.net", 200)], total=3)
    mock_permissions()

    data = await get_adapter("nginxignition").fetch("status", CONFIG, {}, ctx)

    assert data.status == "ok"
    assert labels(data) == [("Hosts", 16), ("Streams", 2), ("Certificates", 3), ("nginx", "1.27.0")]
    assert data.metrics == {"hosts": 16.0}
    assert hosts.call_count == 1
    assert dict(hosts.calls[0].request.url.params) == {"pageSize": "1", "pageNumber": "0"}
    assert hosts.calls[0].request.headers["Authorization"] == f"Bearer {CONFIG['token']}"


@respx.mock
async def test_status_is_not_ok_while_a_certificate_runs_out(ctx: Context) -> None:
    mock_running()
    mock_metadata()
    respx.get(f"{BASE}/api/hosts", params=ONE).mock(return_value=httpx.Response(200, json=page([], 14)))
    respx.get(f"{BASE}/api/streams", params=ONE).mock(return_value=httpx.Response(200, json=page([], 2)))
    mock_certificates([certificate("example.com", 30)], total=1)
    mock_permissions()

    data = await get_adapter("nginxignition").fetch("status", CONFIG, {}, ctx)

    assert data.status == "warn", "thirty days is the line nginx ignition draws"


@respx.mock
async def test_traffic_reports_totals_and_never_a_rate(ctx: Context) -> None:
    """Everything nginx ignition counts is a total and there is no rate anywhere
    in its API: 100 GB is 100 GB, and not a number of bytes a second."""
    mock_metadata()
    mock_running()
    respx.get(f"{BASE}/api/nginx/traffic-stats").mock(
        return_value=httpx.Response(200, json=statistics()))

    data = await get_adapter("nginxignition").fetch("traffic", CONFIG, {}, ctx)

    assert data.status == "ok", "three 5xx out of 184203 is not an outage"
    assert data.primary == {"label": "Requests", "value": 184_203, "metric": "requests"}
    assert labels(data) == [
        ("Received", "100.0 GB"), ("Sent", "25.0 GB"), ("Avg. time", "1.25s"),
        ("Active", 128), ("Reading", 18), ("Writing", 74), ("Waiting", 36),
    ]
    assert data.metrics == {"requests": 184_203.0, "received": 107_374_182_400.0,
                            "sent": 26_843_545_600.0, "avg_time": 1_250.0,
                            "active": 128.0, "reading": 18.0, "writing": 74.0, "waiting": 36.0}


@respx.mock
async def test_traffic_turns_amber_when_server_errors_carry(ctx: Context) -> None:
    mock_metadata()
    mock_running()
    respx.get(f"{BASE}/api/nginx/traffic-stats").mock(
        return_value=httpx.Response(200, json=statistics(requests=1000, five=30)))

    data = await get_adapter("nginxignition").fetch("traffic", CONFIG, {}, ctx)

    assert data.status == "warn", "three in a hundred server errors is worth a look"


@respx.mock
async def test_traffic_says_each_way_the_statistics_can_be_unavailable(ctx: Context) -> None:
    """nginx ignition's home page checks all three before it asks, because a
    missing switch or a stopped server is an empty 500 and nothing else. Each
    answer names what to do rather than turning the card red."""
    adapter = get_adapter("nginxignition")

    mock_metadata(support="NONE")
    with pytest.raises(AdapterError) as unsupported:
        await adapter.fetch("traffic", CONFIG, {}, ctx)
    assert unsupported.value.code == "nginxignition_stats_unsupported"

    mock_metadata(stats=False)
    with pytest.raises(AdapterError) as disabled:
        await adapter.fetch("traffic", CONFIG, {}, again())
    assert disabled.value.code == "nginxignition_stats_disabled"

    mock_metadata()
    mock_running(running=False)
    with pytest.raises(AdapterError) as stopped:
        await adapter.fetch("traffic", CONFIG, {}, again())
    assert stopped.value.code == "nginxignition_stats_stopped"


@respx.mock
async def test_traffic_names_the_socket_when_the_numbers_do_not_arrive(ctx: Context) -> None:
    """The module hands the figures over a socket of its own, and a dead
    socket is an empty 500. "HTTP 500" would be true and would say nothing."""
    mock_metadata()
    mock_running()
    respx.get(f"{BASE}/api/nginx/traffic-stats").mock(return_value=httpx.Response(500))

    with pytest.raises(AdapterError) as failure:
        await get_adapter("nginxignition").fetch("traffic", CONFIG, {}, ctx)

    assert failure.value.code == "nginxignition_stats_unavailable"
    assert "socket" in failure.value.hint


@respx.mock
async def test_traffic_with_nothing_in_it_is_a_fresh_install_not_a_fault(ctx: Context) -> None:
    """Nothing has asked nginx for anything yet. The card keeps its zeros and
    says why, rather than going grey and looking broken."""
    mock_metadata()
    mock_running()
    respx.get(f"{BASE}/api/nginx/traffic-stats").mock(
        return_value=httpx.Response(200, json=statistics(requests=0, in_bytes=0, five=0, four=0)))

    data = await get_adapter("nginxignition").fetch("traffic", CONFIG, {}, ctx)

    assert data.status == "unknown"
    assert data.primary["value"] == 0
    assert data.meta["status_reason"] == "No traffic data recorded yet."


@respx.mock
async def test_certificates_warn_at_thirty_days_like_nginx_ignition_does(ctx: Context) -> None:
    """Its own home page lists what is coming up on the same thirty days, so
    the amber dot and the count on this card can never disagree."""
    adapter = get_adapter("nginxignition")
    mock_permissions(certificates="READ_ONLY")

    mock_certificates([certificate("far.example.com", 31)], total=1)
    outside = await adapter.fetch("certificates", CONFIG, {}, ctx)
    assert outside.status == "ok", "thirty-one days is not soon"

    mock_certificates([certificate("soon.example.com", 30)], total=1)
    on_the_line = await adapter.fetch("certificates", CONFIG, {}, again())
    assert on_the_line.status == "warn"

    mock_certificates([certificate("urgent.example.com", 4)], total=1)
    urgent = await adapter.fetch("certificates", CONFIG, {}, again())
    assert urgent.status == "bad", "four days left is today's work"

    mock_certificates([certificate("today.example.com", 0)], total=1)
    today = await adapter.fetch("certificates", CONFIG, {}, again())
    assert today.status == "bad", "today is not the same as never"


@respx.mock
async def test_certificates_count_what_runs_out_and_ignore_a_missing_date(ctx: Context) -> None:
    """A certificate with no date arrives as the zero time of year one. Read
    as a number that is 739000 days into the past and the card is red for ever,
    so it counts as no answer and is never counted as expired either."""
    mock_certificates([
        certificate("example.com", 4),
        certificate("other.example.org", 18),
        certificate("late.example.net", 120),
        certificate("undated.example.io", None),
    ], total=4)
    mock_permissions(certificates="READ_ONLY")

    data = await get_adapter("nginxignition").fetch("certificates", CONFIG, {}, ctx)

    assert data.status == "bad"
    assert data.primary == {"label": "Certificates", "value": 4}
    assert labels(data) == [("Expiring within 30d", 2), ("Expiring within 7d", 1),
                            ("Expired", 0), ("Next expiration in", "4 d")]
    assert data.metrics == {"certificates": 4.0, "expiring_soon": 2.0, "days_left": 4.0}
    assert data.link == f"{BASE}/certificates", "the full list and its Renew button live there"


@respx.mock
async def test_certificates_count_the_two_windows_apart(ctx: Context) -> None:
    """Past, this week and this month are three separate questions, and an
    expired certificate belongs to none of the two forward-looking ones."""
    mock_certificates([
        certificate("gone.example.com", -2),
        certificate("today.example.com", 0),
        certificate("week.example.com", 7),
        certificate("month.example.com", 30),
        certificate("later.example.net", 31),
    ], total=5)
    mock_permissions(certificates="READ_ONLY")

    data = await get_adapter("nginxignition").fetch("certificates", CONFIG, {}, ctx)

    assert labels(data) == [("Expiring within 30d", 3), ("Expiring within 7d", 2),
                            ("Expired", 1), ("Next expiration in", "-2 d")]
    assert data.status == "bad"


@respx.mock
async def test_certificates_with_nothing_on_them_are_unknown_not_ok(ctx: Context) -> None:
    mock_certificates([], total=0)
    mock_permissions(certificates="READ_ONLY")

    data = await get_adapter("nginxignition").fetch("certificates", CONFIG, {}, ctx)

    assert data.status == "unknown"
    assert labels(data) == [("Expiring within 30d", 0), ("Expiring within 7d", 0),
                            ("Expired", 0), ("Next expiration in", "?")]
    assert "days_left" not in data.metrics, "nothing measured is nothing recorded"


@respx.mock
async def test_renew_asks_which_certificate_when_there_are_several(ctx: Context) -> None:
    """A picker, so that nobody renews whichever one came first. One candidate
    needs no question, and none means no button: an empty choice looks like a
    question with no answer."""
    adapter = get_adapter("nginxignition")
    mock_permissions(certificates="READ_WRITE")

    mock_certificates([certificate("example.com", 4), certificate("other.example.org", 18)], total=2)
    several = await adapter.fetch("certificates", CONFIG, {}, ctx)
    renew = several.actions[0]
    assert renew.id == "renew" and renew.confirm
    assert [one.name for one in renew.asks] == ["id"]
    assert [one.label for one in renew.asks[0].options] == ["example.com, 4 d left", "other.example.org, 18 d left"]

    mock_certificates([certificate("only.example.com", 4)], total=1)
    one = await adapter.fetch("certificates", CONFIG, {}, again())
    assert one.actions[0].params == {"id": "cert-only-example-com"}
    assert one.actions[0].asks == []

    mock_certificates([certificate("far.example.com", 200)], total=1)
    none = await adapter.fetch("certificates", CONFIG, {}, again())
    assert none.actions == [], "nothing is running out, so there is nothing to renew"


@respx.mock
async def test_renew_is_withheld_from_a_token_that_may_not_write(ctx: Context) -> None:
    mock_certificates([certificate("example.com", 4)], total=1)
    mock_permissions(certificates="READ_ONLY")

    data = await get_adapter("nginxignition").fetch("certificates", CONFIG, {}, ctx)

    assert data.actions == [], "the counts are the point of a read-only token"
    assert data.primary["value"] == 1


@respx.mock
async def test_a_refused_renewal_is_a_sentence_and_not_a_status_code(ctx: Context) -> None:
    """This endpoint answers 200 whether it worked or not and says inside the
    body which of the two it was."""
    respx.post(f"{BASE}/api/certificates/cert-example-com/renew").mock(
        return_value=httpx.Response(200, json={"success": False, "errorReason": "the challenge port is taken"}))

    with pytest.raises(AdapterError) as failure:
        await get_adapter("nginxignition").action("certificates", "renew", {"id": "cert-example-com"},
                                                 CONFIG, {}, ctx)

    assert failure.value.code == "certificate_failed"
    assert "the challenge port is taken" in failure.value.message


@respx.mock
async def test_a_renewed_certificate_says_so(ctx: Context) -> None:
    respx.post(f"{BASE}/api/certificates/cert-example-com/renew").mock(
        return_value=httpx.Response(200, json={"success": True, "errorReason": None}))

    said = await get_adapter("nginxignition").action("certificates", "renew", {"id": "cert-example-com"},
                                                     CONFIG, {}, ctx)

    assert said == "Certificate renewed."


@respx.mock
async def test_a_refused_token_is_named_as_one(ctx: Context) -> None:
    """403 is a token nginx ignition knows that may not do this one thing,
    which is the ordinary shape of a read-only token here."""
    respx.post(f"{BASE}/api/nginx/reload").mock(return_value=httpx.Response(403, json={"message": "no"}))

    with pytest.raises(AdapterError) as failure:
        await get_adapter("nginxignition").action("status", "reload", {}, CONFIG, {}, ctx)

    assert failure.value.code == "forbidden_permission"
    assert "Permissions" in failure.value.hint


@respx.mock
async def test_nginx_that_will_not_reload_says_what_nginx_ignition_said(ctx: Context) -> None:
    """424 is nginx ignition's own failed dependency, and the one refusal here
    that has nothing to do with the token."""
    respx.post(f"{BASE}/api/nginx/reload").mock(
        return_value=httpx.Response(424, json={"message": "nginx is not running"}))

    with pytest.raises(AdapterError) as failure:
        await get_adapter("nginxignition").action("status", "reload", {}, CONFIG, {}, ctx)

    assert failure.value.code == "action_failed"
    assert "nginx is not running" in failure.value.message


@respx.mock
async def test_a_nginx_command_that_works_says_what_it_did(ctx: Context) -> None:
    respx.post(f"{BASE}/api/nginx/reload").mock(return_value=httpx.Response(204))

    assert await get_adapter("nginxignition").action("status", "reload", {}, CONFIG, {}, ctx) == "nginx reloaded."


def _card(days: float | None, name: str = "example.com") -> WidgetData:
    metrics: dict[str, float] = {"certificates": 3.0, "expiring_soon": 1.0}
    if days is not None:
        metrics["days_left"] = days
    return WidgetData(metrics=metrics, meta={"soonest": name})


def test_a_certificate_says_once_as_it_crosses_the_line() -> None:
    """Said at the crossing, not every morning while it counts down. Thirty
    days is a month of identical notifications otherwise."""
    adapter = get_adapter("nginxignition")

    assert adapter.detect("certificates", _card(31), _card(30), {}) != [], "it crossed today"
    assert adapter.detect("certificates", _card(30), _card(29), {}) == [], "it crossed yesterday"
    assert adapter.detect("certificates", _card(45), _card(40), {}) == [], "plenty of time left"
    assert adapter.detect("certificates", None, _card(4), {}) == [], "a card opened today says nothing"
    assert adapter.detect("certificates", _card(None), _card(4), {}) == [], "no date to compare against"
    assert adapter.detect("traffic", _card(31), _card(30), {}) == [], "only the certificate card speaks"


def test_a_certificate_that_is_close_is_worth_a_person() -> None:
    found = get_adapter("nginxignition").detect("certificates", _card(20), _card(4), {})

    assert len(found) == 1
    assert found[0].level == "bad"
    assert found[0].title == "example.com runs out in 4 days"


@respx.mock
async def test_the_connection_test_names_both_versions(ctx: Context) -> None:
    mock_metadata(version="1.27.0")
    mock_frontend("2.47.0")

    said = await get_adapter("nginxignition").test(CONFIG, ctx)

    assert said == ("Connected successfully to nginx ignition version 2.47.0 "
                    "with nginx version 1.27.0.")


@respx.mock
async def test_a_build_without_a_version_calls_itself_a_development_one(ctx: Context) -> None:
    """current is null on a development build"""
    mock_metadata(version="1.27.0")
    mock_frontend(None)

    said = await get_adapter("nginxignition").test(CONFIG, ctx)

    assert said == ("Connected successfully to nginx ignition development version "
                    "with nginx version 1.27.0.")


def test_a_certificate_that_runs_out_today_has_not_run_out_yet() -> None:
    """0 days left is today, and the card says so instead of calling it gone."""
    adapter = get_adapter("nginxignition")

    assert adapter.detect("certificates", _card(20), _card(0), {})[0].title == "example.com runs out today"
    assert adapter.detect("certificates", _card(20), _card(-1), {})[0].title == "example.com has run out"
    renew = adapter._renew_action([{"id": "a", "name": "today.example.com", "days": 0},
                                   {"id": "b", "name": "gone.example.com", "days": -2}])
    assert [one.label for one in renew.asks[0].options] == ["today.example.com, runs out today",
                                                            "gone.example.com, already run out"]
