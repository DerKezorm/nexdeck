"""Healthchecks, against the answers of a live Healthchecks 4.4 (11.09.2026).

Six checks were made there, one in every state the API reports: pinged, failed,
never pinged, paused, overdue within its grace time, and a cron check. The
shapes below are what the read-only and the read-write key got back.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context

HC = "http://healthchecks.example.com"
CONFIG = {"url": HC, "api_key": "hcr_readonlykeyforthetests000000"}


def check(name: str, status: str, **extra: Any) -> dict[str, Any]:
    """A check as the read-only key sees it: ``unique_key``, no ``uuid``."""
    return {
        "name": name, "slug": "", "tags": "", "desc": "", "grace": 3600, "n_pings": 1, "status": status,
        "started": False, "last_ping": "2026-09-11T07:28:46+00:00", "next_ping": "2026-09-12T07:28:46+00:00",
        "manual_resume": False, "methods": "", "subject": "", "subject_fail": "", "start_kw": "", "success_kw": "",
        "failure_kw": "", "filter_subject": False, "filter_body": False, "filter_http_body": False,
        "filter_default_fail": False, "badge_url": f"{HC}/b/2/a4c23930.svg",
        "unique_key": "a-made-up-unique-key", "timeout": 86400, **extra,
    }


BACKUP = check("Nightly backup", "up", tags="backup nas")
CERTIFICATES = check("Certificate renewal", "down", tags="web", next_ping=None)
#: ⚠️ Measured: never pinged and paused carry no last ping at all.
SCRUB = check("Disk scrub", "new", timeout=604800, n_pings=0, last_ping=None, next_ping=None)
OLD = check("Old job", "paused", timeout=3600, n_pings=0, last_ping=None, next_ping=None)
MEDIA = check("Media sync", "grace", timeout=60, tags="media", next_ping="2026-09-11T07:29:46+00:00")
#: ⚠️ Measured: a cron check has ``schedule`` and ``tz`` and no ``timeout``.
DUMP = {key: value for key, value in check("Database dump", "up", schedule="0 3 * * *", tz="Europe/Berlin").items() if key != "timeout"}

EVERYTHING = [BACKUP, CERTIFICATES, SCRUB, OLD, MEDIA, DUMP]


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


def _answer(checks: list[dict[str, Any]]) -> respx.Route:
    return respx.get(f"{HC}/api/v3/checks/").mock(return_value=httpx.Response(200, json={"checks": checks}))


@respx.mock
async def test_every_request_closes_its_connection(ctx: Context) -> None:
    """⚠️ Measured: over a kept-alive connection four of twenty back-to-back
    requests failed with "server disconnected", with ``Connection: close`` none."""
    route = _answer(EVERYTHING)
    await get_adapter("healthchecks").fetch("summary", CONFIG, {}, ctx)
    sent = route.calls.last.request
    assert sent.headers["Connection"] == "close"
    assert sent.headers["X-Api-Key"] == CONFIG["api_key"]


@respx.mock
async def test_the_summary_counts_up_late_and_down(ctx: Context) -> None:
    _answer(EVERYTHING)
    data = await get_adapter("healthchecks").fetch("summary", CONFIG, {}, ctx)
    assert data.primary == {"label": "Checks up", "value": 2, "unit": "/ 6"}
    assert data.secondary == [{"label": "Down", "value": 1}, {"label": "Late", "value": 1},
                              {"label": "Paused", "value": 1}, {"label": "New", "value": 1}]
    assert data.status == "bad"
    assert data.metrics == {"down": 1.0, "late": 1.0}
    assert [(part["label"], part["value"]) for part in data.meta["ring"]] == [("Up", 2.0), ("Late", 1.0), ("Down", 1.0), ("Not running", 2.0)]


@respx.mock
async def test_late_without_down_is_a_warning(ctx: Context) -> None:
    _answer([BACKUP, MEDIA])
    assert (await get_adapter("healthchecks").fetch("summary", CONFIG, {}, ctx)).status == "warn"
    _answer([BACKUP, SCRUB, OLD])
    # A new context: the first one still holds the answer above for a few seconds.
    fresh = Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})
    calm = await get_adapter("healthchecks").fetch("summary", CONFIG, {}, fresh)
    assert calm.status == "ok"
    # Down stays even at zero, because that zero is the news; Late does not.
    assert [chip["label"] for chip in calm.secondary] == ["Down", "Paused", "New"]


@respx.mock
async def test_the_list_puts_down_and_late_first(ctx: Context) -> None:
    _answer(EVERYTHING)
    data = await get_adapter("healthchecks").fetch("checks", CONFIG, {"limit": 12}, ctx)
    assert [row["title"] for row in data.items] == ["Certificate renewal", "Media sync", "Database dump", "Nightly backup", "Disk scrub", "Old job"]
    by_name = {row["title"]: row for row in data.items}
    assert [by_name[name]["status"] for name in ("Certificate renewal", "Media sync", "Nightly backup", "Disk scrub")] == ["bad", "warn", "ok", "unknown"]
    assert by_name["Nightly backup"]["subtitle"] == "24h · backup nas"
    assert by_name["Database dump"]["subtitle"] == "0 3 * * *"
    # The state in words as well as in colour, in the part of the row that is translated.
    assert by_name["Certificate renewal"]["subtitle"] == "Down · 24h · web"
    assert by_name["Media sync"]["subtitle"] == "Late · 1m · media"
    assert (by_name["Disk scrub"]["subtitle"], by_name["Disk scrub"]["value"]) == ("New · 7d", "")
    assert by_name["Old job"]["subtitle"] == "Paused · 1h"
    assert by_name["Nightly backup"]["value"].endswith((" min", " h", " d"))
    # The read-only key hands out no id, so there is no page to link to.
    assert all("url" not in row for row in data.items)
    assert data.secondary == [{"label": "Up", "value": 2}, {"label": "Late", "value": 1}, {"label": "Down", "value": 1}]


@respx.mock
async def test_a_read_write_key_links_every_row_to_its_check(ctx: Context) -> None:
    _answer([{**BACKUP, "uuid": "b8577df7-c565-4802-832e-92c19c7cc9f4", "ping_url": f"{HC}/ping/b8577df7-c565-4802-832e-92c19c7cc9f4"}])
    data = await get_adapter("healthchecks").fetch("checks", CONFIG, {"limit": 12}, ctx)
    assert data.items[0]["url"] == f"{HC}/checks/b8577df7-c565-4802-832e-92c19c7cc9f4/details/"


@respx.mock
async def test_a_tag_is_asked_of_healthchecks_and_problems_are_filtered_here(ctx: Context) -> None:
    route = _answer([BACKUP])
    await get_adapter("healthchecks").fetch("checks", CONFIG, {"limit": 12, "tag": " backup "}, ctx)
    assert route.calls.last.request.url.params["tag"] == "backup"
    _answer(EVERYTHING)
    data = await get_adapter("healthchecks").fetch("checks", CONFIG, {"limit": 12, "problems": True}, ctx)
    assert [row["title"] for row in data.items] == ["Certificate renewal", "Media sync"]
    assert data.meta["empty"] == "No late or down checks."


@respx.mock
async def test_a_wrong_key_is_rejected_not_missing(ctx: Context) -> None:
    """⚠️ Measured: Healthchecks says "missing api key" for a key that is there and wrong."""
    respx.get(f"{HC}/api/v3/checks/").mock(return_value=httpx.Response(401, json={"error": "missing api key"}))
    with pytest.raises(AuthFailed) as refused:
        await get_adapter("healthchecks").test(CONFIG, ctx)
    assert "rejected" in str(refused.value)


@respx.mock
async def test_the_connection_test_and_another_service(ctx: Context) -> None:
    _answer(EVERYTHING)
    assert await get_adapter("healthchecks").test(CONFIG, ctx) == "Healthchecks answers with 6 checks, 1 down."
    respx.get(f"{HC}/api/v3/checks/").mock(return_value=httpx.Response(200, json={"monitors": []}))
    with pytest.raises(AdapterError) as wrong:
        await get_adapter("healthchecks").fetch("checks", CONFIG, {}, ctx)
    assert wrong.value.code == "not_healthchecks"
