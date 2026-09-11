"""Kopia, against the answers of a live Kopia 0.23.1 server (11.09.2026), CSRF check on."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context
from app.adapters.kopia import _moment

KO = "http://kopia.example.com"
CONFIG = {"url": KO, "username": "admin", "password": "made-up-password"}
PAGE = '<html><head><meta name="kopia-csrf-token" content="made-up-csrf"></head></html>'


def source(path: str, host: str, end: str | None, status: str = "IDLE", errors: int = 0) -> dict[str, Any]:
    last = {"id": "made-up-id", "source": {"host": host, "userName": "root", "path": path}, "description": "",
            "startTime": end, "endTime": end, "stats": {"totalSize": 504, "fileCount": 2, "dirCount": 1, "errorCount": errors, "ignoredErrorCount": 0},
            "rootEntry": {"name": "config", "type": "d", "summ": {"size": 504, "files": 2, "dirs": 1, "numFailed": errors}}} if end else None
    entry = {"source": {"host": host, "userName": "root", "path": path}, "status": status, "schedule": {"runMissed": True}}
    if last:
        entry["lastSnapshot"] = last
    return entry


def snapshot_task(identifier: str, path: str, host: str, status: str, end: str, error: str | None = None) -> dict[str, Any]:
    return {"id": identifier, "startTime": end, "endTime": end, "kind": "Snapshot", "description": f"root@{host}:{path} at {end[:19]}Z",
            "status": status, "progressInfo": "", "errorMessage": error, "counters": None}


GOOD = source("/app/config", "nas", "2026-09-11T08:57:29.171643942Z")
#: ⚠️ Measured: the source still says IDLE with the older good snapshot; only the task says FAILED.
VANISHED = source("/tmp/vanishing", "nas", "2026-09-11T08:58:28.106819397Z")
FAILED = snapshot_task("5", "/tmp/vanishing", "nas", "FAILED", "2026-09-11T08:58:35.47701109Z",
                       "unable to create local filesystem: unable to determine entry type: lstat /tmp/vanishing: no such file or directory")
EARLIER_OK = snapshot_task("4", "/tmp/vanishing", "nas", "SUCCESS", "2026-09-11T08:58:28.114426495Z")
#: Measured: a source of another host is REMOTE.
ELSEWHERE = source("/home", "laptop", "2026-09-11T07:00:00.000000000Z", status="REMOTE")


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


def _server(sources: list[dict[str, Any]], tasks: list[dict[str, Any]]) -> tuple[respx.Route, respx.Route]:
    page = respx.get(f"{KO}/").mock(return_value=httpx.Response(200, text=PAGE, headers={"Set-Cookie": "Kopia-Session-Cookie=made-up-session; Path=/"}))

    def guarded(payload: dict[str, Any]):
        def answer(request: httpx.Request) -> httpx.Response:
            # The live server wanted the token and the session cookie together.
            if request.headers.get("X-Kopia-Csrf-Token") != "made-up-csrf" or "Kopia-Session-Cookie=made-up-session" not in request.headers.get("Cookie", ""):
                return httpx.Response(401, text="Invalid or missing CSRF token.\n")
            return httpx.Response(200, json=payload)
        return answer

    api = respx.get(f"{KO}/api/v1/sources").mock(side_effect=guarded({"localUsername": "root", "localHost": "nas", "multiUser": True, "sources": sources}))
    respx.get(f"{KO}/api/v1/tasks").mock(side_effect=guarded({"tasks": tasks}))
    respx.get(f"{KO}/api/v1/repo/status").mock(side_effect=guarded({"connected": True, "storage": "filesystem", "description": "Repository in Filesystem: /repository"}))
    return page, api


def test_nanosecond_times_are_read() -> None:
    assert _moment("2026-09-11T08:58:35.47701109Z") > _moment("2026-09-11T08:58:28.114426495Z") > 0
    assert _moment(None) == 0 and _moment("soon") == 0


@respx.mock
async def test_a_failed_task_outranks_the_older_good_snapshot(ctx: Context) -> None:
    page, api = _server([GOOD, VANISHED, ELSEWHERE], [FAILED, EARLIER_OK])
    data = await get_adapter("kopia").fetch("sources", CONFIG, {"limit": 10}, ctx)
    assert page.called and api.calls.last.request.headers["Authorization"].startswith("Basic ")
    # Sent by the adapter itself, not left to whatever cookie jar the shared client keeps.
    assert ctx.cache["kopia_session"] == {"X-Kopia-Csrf-Token": "made-up-csrf", "Cookie": "Kopia-Session-Cookie=made-up-session"}
    first = data.items[0]
    assert (first["title"], first["status"]) == ("/tmp/vanishing", "bad")
    assert first["subtitle"].startswith("Failed · unable to create local filesystem")
    # Two hosts in the list, so each row says whose it is; REMOTE is judged by its snapshot.
    assert [(row["title"], row["status"], row["subtitle"]) for row in data.items[1:]] == [("/app/config", "ok", "root@nas"), ("/home", "ok", "root@laptop")]
    assert data.secondary == [{"label": "Failed", "value": 1}] and data.status == "bad"


@respx.mock
async def test_a_good_snapshot_after_a_failure_clears_it(ctx: Context) -> None:
    later = source("/tmp/vanishing", "nas", "2026-09-11T09:10:00.000000000Z")
    _server([later], [FAILED])
    data = await get_adapter("kopia").fetch("sources", CONFIG, {"limit": 10}, ctx)
    assert data.items[0]["status"] == "ok" and data.items[0]["subtitle"] == ""


@respx.mock
async def test_running_waiting_never_and_errors(ctx: Context) -> None:
    _server([source("/a", "nas", "2026-09-11T08:00:00Z", status="UPLOADING"), source("/b", "nas", None),
             source("/c", "nas", "2026-09-11T08:00:00Z", status="PAUSED"), source("/d", "nas", "2026-09-11T08:00:00Z", errors=3)], [])
    data = await get_adapter("kopia").fetch("sources", CONFIG, {"limit": 10}, ctx)
    assert {row["title"]: (row["status"], row["subtitle"]) for row in data.items} == {
        "/a": ("warn", "Running"), "/b": ("unknown", "No snapshot yet"), "/c": ("unknown", "Paused"), "/d": ("warn", "3 errors")}


@respx.mock
async def test_the_summary(ctx: Context) -> None:
    _server([GOOD, VANISHED, ELSEWHERE], [FAILED])
    data = await get_adapter("kopia").fetch("summary", CONFIG, {}, ctx)
    assert data.primary == {"label": "Sources fine", "value": 2, "unit": "/ 3"}
    assert data.secondary[0] == {"label": "Failed", "value": 1} and data.secondary[1]["label"] == "Last snapshot"
    assert data.status == "bad"


@respx.mock
async def test_a_stale_session_is_fetched_again_once(ctx: Context) -> None:
    page, _api = _server([GOOD], [])
    ctx.cache["kopia_session"] = {"X-Kopia-Csrf-Token": "from-before-a-restart", "Cookie": "Kopia-Session-Cookie=old"}
    data = await get_adapter("kopia").fetch("sources", CONFIG, {"limit": 10}, ctx)
    assert page.call_count == 1 and data.items[0]["title"] == "/app/config"


@respx.mock
async def test_wrong_password_and_a_server_that_wants_a_token_it_cannot_get(ctx: Context) -> None:
    respx.get(f"{KO}/").mock(return_value=httpx.Response(401, text="Access denied.\n"))
    with pytest.raises(AuthFailed):
        await get_adapter("kopia").test(CONFIG, ctx)
    respx.get(f"{KO}/").mock(return_value=httpx.Response(404, text="not found"))
    respx.get(f"{KO}/api/v1/repo/status").mock(return_value=httpx.Response(401, text="Invalid or missing CSRF token.\n"))
    fresh = Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})
    with pytest.raises(AdapterError) as csrf:
        await get_adapter("kopia").test(CONFIG, fresh)
    assert csrf.value.code == "csrf"


@respx.mock
async def test_the_connection_test(ctx: Context) -> None:
    _server([GOOD, VANISHED], [])
    assert await get_adapter("kopia").test(CONFIG, ctx) == "Kopia answers: repository on filesystem, 2 sources."
