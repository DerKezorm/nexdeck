"""ChangeDetection.io, against the answers of a live 0.60.4 (11.09.2026).

Watches were made there that change on every check, that fail, and that
were paused before their first check; the two it creates on its own first
start were left as they were.
"""

from __future__ import annotations

import time
from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context

CD = "http://changedetection.example.com"
CONFIG = {"url": CD, "api_key": "not-a-real-key"}
NOW = time.time()


def watch(url: str, **extra: Any) -> dict[str, Any]:
    """A watch as the list hands it out: no ``paused``, no ``notification_muted``."""
    return {"last_changed": 0, "last_checked": int(NOW - 600), "last_error": False, "link": url, "open_link": url,
            "page_title": None, "tags": [], "title": None, "url": url, "viewed": False, **extra}


#: ⚠️ Measured: ``viewed`` is false although nothing ever changed.
QUIET = watch("https://changedetection.io/CHANGELOG.txt")
NEWS = watch("https://news.ycombinator.com/", page_title="Hacker News", last_changed=int(NOW - 7200))
SEEN = watch("https://httpbin.org/uuid", title="Test changing", last_changed=int(NOW - 86400 * 3), viewed=True)
FAILING = watch("http://192.0.2.10:1/", title="Test failing", last_error="Exception: Fetch blocked: resolves to a private/reserved IP address")
#: ⚠️ Measured: a watch paused before its first check is only ``last_checked: 0`` in the list.
PAUSED = watch("https://example.com/", title="Test paused", last_checked=0)

EVERYTHING = {"98d5": QUIET, "eb7a": NEWS, "1b55": SEEN, "f52f": FAILING, "9132": PAUSED}


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


def _watches(watches: dict[str, Any]) -> respx.Route:
    return respx.get(f"{CD}/api/v1/watch").mock(return_value=httpx.Response(200, json=watches))


@respx.mock
async def test_failing_first_then_the_latest_change(ctx: Context) -> None:
    route = _watches(EVERYTHING)
    data = await get_adapter("changedetection").fetch("changes", CONFIG, {"limit": 10}, ctx)
    assert route.calls.last.request.headers["x-api-key"] == "not-a-real-key"
    assert [row["title"] for row in data.items] == ["Test failing", "Hacker News", "Test changing", "https://changedetection.io/CHANGELOG.txt", "Test paused"]
    failing, news, seen, quiet, paused = data.items
    assert (failing["status"], failing["subtitle"], failing["value"]) == ("bad", "Error · 192.0.2.10", "")
    assert (news["subtitle"], news["value"], news["url"]) == ("Unviewed · news.ycombinator.com", "2 h", f"{CD}/diff/eb7a")
    assert (seen["subtitle"], seen["value"]) == ("httpbin.org", "3 d")
    assert (quiet["url"], quiet["status"]) == (f"{CD}/preview/98d5", "ok")
    assert (paused["subtitle"], paused["status"]) == ("Not checked yet · example.com", "unknown")
    assert data.secondary == [{"label": "Unviewed", "value": 1}, {"label": "Errors", "value": 1}]
    assert data.status == "bad"


@respx.mock
async def test_the_tag_is_asked_for_and_unchanged_pages_can_be_left_out(ctx: Context) -> None:
    route = _watches({"eb7a": NEWS})
    await get_adapter("changedetection").fetch("changes", CONFIG, {"limit": 10, "tag": "Tech news"}, ctx)
    assert route.calls.last.request.url.params["tag"] == "Tech news"
    _watches(EVERYTHING)
    data = await get_adapter("changedetection").fetch("changes", CONFIG, {"limit": 10, "changed_only": True}, ctx)
    assert [row["title"] for row in data.items] == ["Hacker News", "Test changing"]
    assert data.meta["empty"] == "Nothing has changed yet."


@respx.mock
async def test_the_summary_counts_unviewed_changes_errors_and_the_queue(ctx: Context) -> None:
    _watches(EVERYTHING)
    respx.get(f"{CD}/api/v1/systeminfo").mock(return_value=httpx.Response(200, json={
        "queue_size": 2, "overdue_watches": ["eb7a"], "uptime": 870.58, "watch_count": 5, "version": "0.60.4"}))
    data = await get_adapter("changedetection").fetch("summary", CONFIG, {}, ctx)
    assert data.primary == {"label": "Unviewed changes", "value": 1}
    assert data.secondary == [{"label": "Watches", "value": 5}, {"label": "Errors", "value": 1},
                              {"label": "In queue", "value": 2}, {"label": "Overdue", "value": 1}]
    quiet = get_adapter("changedetection")._summary({"eb7a": NEWS}, {"queue_size": 0, "overdue_watches": []})
    assert quiet.secondary == [{"label": "Watches", "value": 1}]
    assert data.status == "bad"
    assert data.metrics == {"unviewed": 1.0, "errors": 1.0}
    assert [action.id for action in data.actions] == ["recheck_all"]


@respx.mock
async def test_a_wrong_key_and_another_service(ctx: Context) -> None:
    """⚠️ Measured: missing and wrong keys both get 403 with a JSON string."""
    respx.get(f"{CD}/api/v1/systeminfo").mock(return_value=httpx.Response(403, json="Invalid access - API key invalid."))
    with pytest.raises(AuthFailed):
        await get_adapter("changedetection").test(CONFIG, ctx)
    respx.get(f"{CD}/api/v1/systeminfo").mock(return_value=httpx.Response(200, json={"queue_size": 0, "watch_count": 5, "version": "0.60.4"}))
    assert await get_adapter("changedetection").test(CONFIG, ctx) == "ChangeDetection.io 0.60.4 answers with 5 watches."
    respx.get(f"{CD}/api/v1/watch").mock(return_value=httpx.Response(200, json=["not", "watches"]))
    with pytest.raises(AdapterError) as wrong:
        await get_adapter("changedetection").fetch("changes", CONFIG, {}, ctx)
    assert wrong.value.code == "not_changedetection"


@respx.mock
async def test_check_all_now_reports_how_many_were_queued(ctx: Context) -> None:
    route = respx.get(f"{CD}/api/v1/watch", params={"recheck_all": "1"}).mock(
        return_value=httpx.Response(200, json={"status": "OK, queued 5 watches for rechecking"}))
    message = await get_adapter("changedetection").action("summary", "recheck_all", {}, CONFIG, {}, ctx)
    assert route.called and message == "ChangeDetection.io is checking 5 watches again."
    with pytest.raises(AdapterError):
        await get_adapter("changedetection").action("summary", "delete", {}, CONFIG, {}, ctx)
