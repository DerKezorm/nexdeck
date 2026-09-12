"""Gatus, against the answers of a live Gatus 5.36.0 (12.09.2026)."""

from __future__ import annotations

import base64
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context, Unreachable
from app.adapters.gatus import GatusAdapter

GT = "http://gatus.example.com:8080"
CONFIG = {"url": GT, "username": "admin", "password": "made-up-password"}
#: Five minutes after the newest check below.
NOW = datetime(2026, 9, 12, 4, 40, 7, tzinfo=UTC).timestamp()
LOOKUP = 'Get "http://web.example.com/": dial tcp: lookup web.example.com on 192.0.2.53:53: server misbehaving'
GONE = 'Get "http://nothing.example.com:8080/": dial tcp: lookup nothing.example.com on 192.0.2.53:53: server misbehaving'


def result(when: str, nanoseconds: int, *conditions: tuple[str, bool], status: int | None = 200, error: str = "",
           host: str = "web.example.com") -> dict[str, Any]:
    """One check as Gatus answered it: ``status`` left out without an HTTP answer, ``errors`` without an error."""
    one: dict[str, Any] = {} if status is None else {"status": status}
    one |= {"hostname": host, "duration": nanoseconds}
    if error:
        one["errors"] = [error]
    one["conditionResults"] = [{"condition": text, "success": held} for text, held in conditions]
    one["success"] = all(held for _text, held in conditions)
    one["timestamp"] = when
    return one


#: Sorted by key, results oldest first, as measured. The nginx behind "web" was stopped and started again in between.
STATUSES = [
    {"name": "no group", "key": "_no-group", "results": [
        result("2026-09-12T04:33:57.262767154Z", 1307892, ("[STATUS] == 200", True)),
        result("2026-09-12T04:34:33.959044721Z", 1250208800, ("[STATUS] (0) == 200", False), status=None, error=LOOKUP),
        result("2026-09-12T04:34:57.264573982Z", 887058, ("[STATUS] == 200", True)),
    ]},
    {"name": "api", "group": "test", "key": "test_api", "results": [
        result("2026-09-12T04:31:09.506772748Z", 601234, ("[STATUS] == 200", True)),
        result("2026-09-12T04:31:19.506772748Z", 576662, ("[STATUS] == 200", True)),
    ]},
    {"name": "gone", "group": "test", "key": "test_gone", "results": [
        result("2026-09-12T04:34:52.708808113Z", 7748970091, ("[CONNECTED] (false) == true", False), status=None, error=GONE, host="nothing.example.com"),
        result("2026-09-12T04:35:02.708999132Z", 7749644468, ("[CONNECTED] (false) == true", False), status=None, error=GONE, host="nothing.example.com"),
    ]},
    {"name": "missing page", "group": "test", "key": "test_missing-page", "results": [
        result("2026-09-12T04:34:56.81775226Z", 910433, ("[STATUS] (404) == 200", False), status=404),
        result("2026-09-12T04:35:06.81802301Z", 944055, ("[STATUS] (404) == 200", False), status=404),
    ]},
    {"name": "web", "group": "test", "key": "test_web", "results": [
        result("2026-09-12T04:33:56.594099226Z", 1154026, ("[STATUS] == 200", True), ("[RESPONSE_TIME] < 500", True)),
        result("2026-09-12T04:34:33.959048358Z", 7364007619, ("[STATUS] (0) == 200", False), ("[RESPONSE_TIME] (7364) < 500", False),
               status=None, error=LOOKUP),
        result("2026-09-12T04:34:50.210036382Z", 3614807743, ("[STATUS] == 200", True), ("[RESPONSE_TIME] (3614) < 500", False)),
        result("2026-09-12T04:35:06.595377319Z", 1030737, ("[STATUS] == 200", True), ("[RESPONSE_TIME] < 500", True)),
    ]},
]


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


@respx.mock
async def test_endpoints_down_first_then_unstable_with_their_response_time(ctx: Context) -> None:
    route = respx.get(f"{GT}/api/v1/endpoints/statuses").mock(return_value=httpx.Response(200, json=STATUSES))
    data = await get_adapter("gatus").fetch("endpoints", CONFIG, {"limit": 10}, ctx)
    request = route.calls.last.request
    assert request.headers["Authorization"] == "Basic " + base64.b64encode(b"admin:made-up-password").decode()
    assert dict(request.url.params) == {"pageSize": "20"}
    # ⚠️ Measured: the durations are nanoseconds.
    assert [(row["title"], row["subtitle"], row["status"], row.get("value")) for row in data.items] == [
        ("gone", f"Down · test · {GONE}", "bad", "7.7 s"),
        ("missing page", "Down · test · [STATUS] (404) == 200", "bad", "0.9 ms"),
        ("no group", "Unstable", "warn", "0.9 ms"),
        ("web", "Unstable · test", "warn", "1.0 ms"),
        ("api", "test", "ok", "0.6 ms"),
    ]
    assert data.secondary == [{"label": "Down", "value": 2}] and data.status == "bad" and data.metrics == {"down": 2.0}


def test_a_check_that_answered_too_slowly_is_down_with_its_condition() -> None:
    """⚠️ Measured: status 200 and still failed, because the response time did not hold."""
    slow = {**STATUSES[4], "results": STATUSES[4]["results"][:3]}
    data = GatusAdapter._endpoints([slow], 10)
    assert [(row["subtitle"], row["status"], row["value"]) for row in data.items] == [("Down · test · [RESPONSE_TIME] (3614) < 500", "bad", "3.6 s")]
    shaky = GatusAdapter._endpoints([STATUSES[0], STATUSES[1]], 10)
    assert shaky.status == "warn" and shaky.secondary == [{"label": "Down", "value": 0}]
    assert [row["title"] for row in GatusAdapter._endpoints(STATUSES, 2).items] == ["gone", "missing page"]


def test_the_summary() -> None:
    data = GatusAdapter._summary(STATUSES, now=NOW)
    assert data.primary == {"label": "Endpoints up", "value": 3, "unit": "/ 5"}
    assert data.secondary == [{"label": "Down", "value": 2}, {"label": "Last check", "value": "5 min"}]
    assert data.status == "bad" and data.metrics == {"up": 3.0, "down": 2.0}


@respx.mock
async def test_without_a_user_no_credentials_are_sent(ctx: Context) -> None:
    route = respx.get(f"{GT}/api/v1/endpoints/statuses").mock(return_value=httpx.Response(200, json=STATUSES))
    assert await get_adapter("gatus").test({"url": GT}, ctx) == "Gatus answers with 5 endpoints."
    assert "Authorization" not in route.calls.last.request.headers and route.calls.last.request.url.params["pageSize"] == "1"


@respx.mock
async def test_a_rejected_password(ctx: Context) -> None:
    """⚠️ Measured: no header, a wrong password and a made-up bearer token all get 401."""
    respx.get(f"{GT}/api/v1/endpoints/statuses").mock(return_value=httpx.Response(401, text="Unauthorized", headers={"www-authenticate": "Basic"}))
    with pytest.raises(AuthFailed):
        await get_adapter("gatus").fetch("summary", CONFIG, {}, ctx)


@respx.mock
async def test_an_address_that_is_not_gatus(ctx: Context) -> None:
    route = respx.get(f"{GT}/api/v1/endpoints/statuses").mock(return_value=httpx.Response(200, json=[{"status": "UP"}]))
    with pytest.raises(AdapterError) as other:
        await get_adapter("gatus").fetch("endpoints", CONFIG, {}, ctx)
    assert other.value.code == "not_gatus"
    route.mock(return_value=httpx.Response(200, text="<html>sign in</html>"))
    # A fresh context: the one above still remembers the first answer for a few seconds.
    with pytest.raises(AdapterError) as page:
        await get_adapter("gatus").fetch("endpoints", CONFIG, {}, Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={}))
    assert page.value.code == "not_json"


@respx.mock
async def test_an_unreachable_gatus(ctx: Context) -> None:
    respx.get(f"{GT}/api/v1/endpoints/statuses").mock(side_effect=httpx.ConnectError("connection refused"))
    with pytest.raises(Unreachable):
        await get_adapter("gatus").fetch("endpoints", CONFIG, {}, ctx)
