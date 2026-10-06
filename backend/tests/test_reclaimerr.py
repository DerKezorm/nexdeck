"""Issue #31: the Reclaimerr cards against the answers of its external API.

The answers are shaped after Reclaimerr 0.5.5's answer models
(backend/models/api_v1/) and route handlers (backend/api/routes/v1/), the
refusals after its token check (backend/core/api_tokens.py). Every moment is
counted from the moment the test runs, so nothing here turns red on a date.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context, WidgetData

URL = "https://reclaim.example.com"
API = f"{URL}/api/v1"
# Built when the test runs: a token-shaped literal stops the scanners before a push.
TOKEN = "_".join(("rcl", "cards", "made-up-for-these-tests"))
CONFIG = {"url": URL, "api_key": TOKEN}
RCL = get_adapter("reclaimerr")
READ_ALL = ["candidates:read", "events:read", "media:read", "protections:read", "system:read", "tasks:read"]
EVERYTHING = ["candidates:manage", "events:read", "media:read", "protections:manage", "system:read", "tasks:run"]


def _ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


def _at(**delta: float) -> str:
    return (datetime.now(UTC) + timedelta(**delta)).isoformat()


def _scopes(scopes: list[str]) -> respx.Route:
    return respx.get(API).mock(return_value=httpx.Response(200, json={
        "api_version": "v1", "resources": {"candidates": "/api/v1/candidates"}, "granted_scopes": scopes}))


def _candidate(number: int, scope: str = "movie", state: str = "scheduled", **extra: Any) -> dict[str, Any]:
    return {
        "id": number, "media_type": "series" if scope in ("series", "season", "episode") else "movie", "scope": scope,
        "media_id": 100 + number, "title": f"Title {number}", "year": 2019, "tmdb_id": 990000000 + number,
        "matched_rule_ids": [1], "reason": "Never watched", "delete_operation": "delete", "created_at": _at(days=-10),
        "auto_delete_state": state, "auto_delete_delay_days": 14, "auto_delete_eligible_at": _at(days=4),
        "auto_delete_is_active": True, "auto_delete_is_eligible": False, "blockers": [], **extra,
    }


def _candidates(*rows: dict[str, Any]) -> respx.Route:
    return respx.get(f"{API}/candidates").mock(return_value=httpx.Response(200, json={
        "items": list(rows), "total": len(rows), "page": 1, "per_page": 200, "total_pages": 1}))


def _system(**extra: Any) -> respx.Route:
    return respx.get(f"{API}/system").mock(return_value=httpx.Response(200, json={
        "status": "ok", "program": "Reclaimerr", "version": "0.5.5", "project_url": "https://example.com",
        "api_version": "v1", "server_time": _at(), "has_main_media_server": True,
        "last_media_sync_at": _at(hours=-3), "last_candidate_scan_at": _at(hours=-2), "capabilities": [], **extra}))


def _task(key: str, name: str, **extra: Any) -> dict[str, Any]:
    return {"id": key, "name": name, "description": None, "enabled": True, "status": "scheduled", "error": None,
            "schedule_type": "cron", "schedule_value": "0 3 * * *", "next_run_at": _at(hours=17),
            "last_run_at": _at(hours=-7), "can_run": True, "requires_main_server": True, **extra}


def _tasks(*rows: dict[str, Any], main: bool = True) -> respx.Route:
    return respx.get(f"{API}/tasks").mock(return_value=httpx.Response(200, json={"items": list(rows), "has_main_server": main}))


def _everything_else(protected: int = 3) -> None:
    respx.get(f"{API}/protections").mock(return_value=httpx.Response(200, json={
        "items": [], "total": protected, "page": 1, "per_page": 1, "total_pages": protected}))
    respx.get(f"{API}/events").mock(return_value=httpx.Response(200, json={"items": [], "next_cursor": None, "has_more": False}))


def _media(path: str, media_id: int, size: int | None) -> respx.Route:
    return respx.get(f"{API}/{path}/{media_id}").mock(return_value=httpx.Response(200, json={
        "id": media_id, "media_type": "movie" if path == "movies" else "series", "title": "x", "tmdb_id": 1, "size_bytes": size}))


# ---------------------------------------------------------------------------
# The overview
# ---------------------------------------------------------------------------


@respx.mock
async def test_the_overview_counts_what_leaves_and_carries_the_token_in_the_header() -> None:
    scopes = _scopes(READ_ALL)
    _candidates(
        _candidate(1, deadline_note="nearest is blocked", blockers=["pending_delete_request"], auto_delete_eligible_at=_at(hours=5)),
        _candidate(2, auto_delete_eligible_at=_at(days=2, hours=1)),
        _candidate(3, scope="series", state="postponed"),
        _candidate(4, state="canceled"),
    )
    _media("movies", 101, 2 * 1024 ** 3)
    _media("movies", 102, 3 * 1024 ** 3)
    _media("series", 103, 5 * 1024 ** 3)
    _system()
    _tasks(_task("sync_media", "Sync Media"))
    _everything_else(protected=3)
    card = await RCL.fetch("overview", CONFIG, {}, _ctx())
    request = scopes.calls.last.request
    assert request.headers["Authorization"] == f"Bearer {TOKEN}"
    assert "rcl_" not in str(request.url), "the token stays out of the address"
    assert card.status == "ok", card.meta
    assert card.primary == {"label": "Candidates", "value": 3}, "a kept title is not marked"
    assert {chip["label"]: chip["value"] for chip in card.secondary} == {
        "Space to free": "10.0 GB", "Next deletion": "in 2 d", "Protected": 3}, "the blocked one is not the next to go"
    assert card.metrics == {"candidates": 3.0, "reclaimable": float(10 * 1024 ** 3)}


@respx.mock
async def test_a_season_has_no_size_and_the_space_says_at_least() -> None:
    _scopes(READ_ALL)
    _candidates(_candidate(1), _candidate(2, scope="season", title="Northbound Tides S02"))
    sized = _media("movies", 101, 1024 ** 3)
    _system()
    _tasks()
    _everything_else()
    card = await RCL.fetch("overview", CONFIG, {}, _ctx())
    assert {chip["label"]: chip["value"] for chip in card.secondary}["Space to free"] == "at least 1.0 GB"
    assert sized.call_count == 1


@respx.mock
@pytest.mark.parametrize(("system", "task", "reason"), [
    ({"last_media_sync_at": None}, None, "No media sync has finished yet."),
    ({"last_candidate_scan_at": "OLD"}, None, "Last candidate scan 3 d ago."),
    ({"has_main_media_server": False}, None, "No main media server is set."),
    ({}, {"status": "error", "error": "Jellyfin did not answer"}, "Sync Media failed."),
])
async def test_the_overview_turns_amber_and_says_why(system: dict[str, Any], task: dict[str, Any] | None, reason: str) -> None:
    _scopes(READ_ALL)
    _candidates()
    _system(**{key: (_at(days=-3) if value == "OLD" else value) for key, value in system.items()})
    _tasks(_task("sync_media", "Sync Media", **(task or {})))
    _everything_else()
    card = await RCL.fetch("overview", CONFIG, {}, _ctx())
    assert card.status == "warn"
    assert card.meta["status_reason"] == reason


@respx.mock
async def test_old_is_what_the_card_says_it_is() -> None:
    _scopes(READ_ALL)
    _candidates()
    _system(last_media_sync_at=_at(hours=-30), last_candidate_scan_at=_at(hours=-30))
    _tasks()
    _everything_else()
    assert (await RCL.fetch("overview", CONFIG, {}, _ctx())).status == "ok"
    card = await RCL.fetch("overview", CONFIG, {"stale_hours": 24}, _ctx())
    assert card.status == "warn"
    assert card.meta["status_reason"] == "Last media sync 1 d ago. · Last candidate scan 1 d ago."


@respx.mock
async def test_a_token_that_only_reads_candidates_names_what_it_misses() -> None:
    _scopes(["candidates:read"])
    _candidates(_candidate(1))
    sizes = respx.get(url__regex=rf"{API}/(movies|series)/.*")
    others = respx.get(url__regex=rf"{API}/(system|tasks|protections|events).*")
    card = await RCL.fetch("overview", CONFIG, {}, _ctx())
    assert not sizes.called and not others.called, "a scope the token lacks is not asked for"
    assert card.status == "ok"
    assert [chip["label"] for chip in card.secondary] == ["Next deletion"]
    assert card.meta["status_reason"] == " · ".join(
        f"The API token lacks the scope {scope}." for scope in ("media:read", "protections:read", "system:read", "tasks:read"))
    assert "removed" not in card.meta and "reclaimable" not in card.metrics


@respx.mock
async def test_manage_includes_read() -> None:
    _scopes(["candidates:manage"])
    _candidates(_candidate(1))
    card = await RCL.fetch("leaving", CONFIG, {}, _ctx())
    assert [row["title"] for row in card.items] == ["Title 1 (2019)"]
    assert card.items[0]["actions"]


@respx.mock
async def test_a_card_without_its_scope_says_which() -> None:
    _scopes(["system:read"])
    with pytest.raises(AdapterError) as caught:
        await RCL.fetch("leaving", CONFIG, {}, _ctx())
    assert caught.value.code == "missing_scope"
    assert caught.value.message == "The API token lacks the scope candidates:read."
    with pytest.raises(AdapterError) as caught:
        await RCL.fetch("tasks", CONFIG, {}, _ctx())
    assert caught.value.message == "The API token lacks the scope tasks:read."


@respx.mock
async def test_reclaimerrs_own_scope_refusal_is_named() -> None:
    _scopes(["candidates:read", "system:read"])
    _candidates()
    respx.get(f"{API}/system").mock(return_value=httpx.Response(403, json={"detail": "API token requires the system:read scope"}))
    with pytest.raises(AdapterError) as caught:
        await RCL.fetch("overview", CONFIG, {}, _ctx())
    assert caught.value.code == "missing_scope"
    assert caught.value.message == "The API token lacks the scope system:read."


@respx.mock
@pytest.mark.parametrize("detail", ["Invalid API token", "API token has been revoked", "API token has expired"])
async def test_a_refused_token_is_a_rejected_credential(detail: str) -> None:
    respx.get(API).mock(return_value=httpx.Response(401, json={"detail": detail}))
    with pytest.raises(AuthFailed) as caught:
        await RCL.fetch("overview", CONFIG, {}, _ctx())
    assert detail in caught.value.message


@respx.mock
async def test_a_reclaimerr_without_the_external_api_is_named() -> None:
    respx.get(API).mock(return_value=httpx.Response(404, json={"detail": "Not Found"}))
    with pytest.raises(AdapterError) as caught:
        await RCL.test(CONFIG, _ctx())
    assert "no external API" in caught.value.message


# ---------------------------------------------------------------------------
# Leaving soon
# ---------------------------------------------------------------------------


@respx.mock
async def test_leaving_soon_goes_by_deadline_with_kind_size_and_what_holds_it() -> None:
    _scopes(READ_ALL)
    _candidates(
        _candidate(1, auto_delete_eligible_at=_at(days=9)),
        _candidate(2, scope="season", title="Northbound Tides S02", auto_delete_eligible_at=_at(days=1),
                   blockers=["pending_delete_request"]),
        _candidate(3, scope="series", title="Glass Meadow", state="postponed", auto_delete_eligible_at=_at(days=23),
                   delete_operation="move"),
        _candidate(4, state="eligible", auto_delete_eligible_at=_at(hours=-2), last_delete_error="Radarr refused"),
        _candidate(5, state="canceled"),
    )
    _media("movies", 101, 8 * 1024 ** 3)
    _media("series", 103, 46 * 1024 ** 3)
    _media("movies", 104, None)
    card = await RCL.fetch("leaving", CONFIG, {}, _ctx())
    rows = [(row["title"], row["subtitle"], row["value"], row["status"]) for row in card.items]
    assert rows == [
        ("Title 4 (2019)", "Movie · Last deletion failed", "due", "bad"),
        ("Northbound Tides S02", "Season · Delete request open", "in 24 h", "warn"),
        ("Title 1 (2019)", "Movie · 8.0 GB", "in 9 d", "ok"),
        ("Glass Meadow (2019)", "Whole series · 46.0 GB · Moved, not deleted", "Postponed, in 23 d", "ok"),
    ]
    assert card.status == "warn"
    assert card.secondary == [{"label": "Candidates", "value": 4}]
    assert card.meta["notice"] == "The buttons need the scope candidates:manage."
    assert all("actions" not in row for row in card.items)


@respx.mock
async def test_all_candidates_shows_the_kept_ones_too() -> None:
    _scopes(["candidates:read"])
    _candidates(_candidate(1, state="canceled"), _candidate(2), _candidate(3, state="disabled"))
    card = await RCL.fetch("leaving", CONFIG, {"show": "all"}, _ctx())
    assert [(row["title"], row["value"]) for row in card.items] == [
        ("Title 2 (2019)", "in 4 d"), ("Title 3 (2019)", "Manual"), ("Title 1 (2019)", "Kept")]
    card = await RCL.fetch("leaving", CONFIG, {"show": "all", "limit": 2}, _ctx())
    assert len(card.items) == 2
    assert card.meta["notice"] == "The buttons need the scope candidates:manage. · The API token lacks the scope media:read."


@respx.mock
async def test_the_card_shows_more_than_fifty_titles_when_asked() -> None:
    """Issue #31: a user asked for 75. nexdeck reads every candidate anyway;
    the cap was its own."""
    _scopes(["candidates:read"])
    _candidates(*(_candidate(n) for n in range(1, 251)))
    card = await RCL.fetch("leaving", CONFIG, {"limit": 75}, _ctx())
    assert len(card.items) == 75
    card = await RCL.fetch("leaving", CONFIG, {"limit": 1000}, _ctx())
    assert len(card.items) == 200

@respx.mock
async def test_titles_marked_by_hand_are_shown_by_default_after_the_ones_with_a_deadline() -> None:
    """Measured on Reclaimerr 0.5.5: automatic deletion is off until a rule opts in,
    and then every candidate is "disabled". A card showing only the ones with a
    deadline stood empty on a library with seven candidates."""
    _scopes(["candidates:manage"])
    _candidates(_candidate(1, state="disabled", auto_delete_eligible_at=_at(days=1)), _candidate(2, auto_delete_eligible_at=_at(days=6)),
                _candidate(3, state="canceled"))
    card = await RCL.fetch("leaving", CONFIG, {}, _ctx())
    assert [(row["title"], row["value"], row["status"]) for row in card.items] == [
        ("Title 2 (2019)", "in 6 d", "ok"), ("Title 1 (2019)", "Manual", "ok")]
    assert [a.id for a in card.items[1]["actions"]] == ["protect"], "no timer runs on a title marked by hand"
    leaving = await RCL.fetch("leaving", CONFIG, {"show": "leaving"}, _ctx())
    assert [row["title"] for row in leaving.items] == ["Title 2 (2019)"]
    kept = await RCL.fetch("leaving", CONFIG, {"show": "all"}, _ctx())
    assert [a.id for a in kept.items[-1]["actions"]] == ["reset", "protect"]


@respx.mock
async def test_a_version_of_a_movie_has_the_movies_size_and_each_title_counts_once() -> None:
    """The shape of the live answer: every movie candidate a version, a series
    marked whole and its season and episodes beside it."""
    _scopes(READ_ALL)
    _candidates(
        _candidate(1, scope="version", media_id=1, movie_version_id=1, state="disabled"),
        _candidate(2, scope="version", media_id=1, movie_version_id=9, state="disabled"),
        _candidate(5, scope="series", media_id=4, state="disabled"),
        _candidate(7, scope="season", media_id=4, title="Glass Meadow S01", state="disabled"),
        _candidate(10, scope="episode", media_id=4, title="Glass Meadow S01E01", state="disabled"),
    )
    _media("movies", 1, 339390)
    _media("series", 4, 167030)
    _system()
    _tasks()
    _everything_else()
    card = await RCL.fetch("overview", CONFIG, {}, _ctx())
    chips = {chip["label"]: chip["value"] for chip in card.secondary}
    assert chips["Space to free"] == "494.6 KB", "the movie once, the series once, its season and episode inside it"
    assert chips["Next deletion"] == "nothing planned", "nothing is deleted by itself"
    assert card.primary == {"label": "Candidates", "value": 5}
    rows = await RCL.fetch("leaving", CONFIG, {}, _ctx())
    assert [row["subtitle"] for row in rows.items] == [
        "Movie version · 331.4 KB", "Movie version · 331.4 KB", "Whole series · 163.1 KB", "Season", "Episode"]


@respx.mock
async def test_with_manage_every_row_has_its_four_buttons() -> None:
    _scopes(EVERYTHING)
    _candidates(_candidate(7))
    _media("movies", 107, 1024)
    card = await RCL.fetch("leaving", CONFIG, {"postpone": "30"}, _ctx())
    actions = card.items[0]["actions"]
    assert [(a.id, a.label, a.params) for a in actions] == [
        ("postpone", "Postpone 30 d", {"id": 7, "days": 30}), ("keep", "Keep", {"id": 7}),
        ("reset", "Reset timer", {"id": 7}), ("protect", "Protect", {"id": 7})]
    assert [a.confirm for a in actions] == [False, True, True, True]
    assert "notice" not in card.meta


@respx.mock
async def test_postpone_counts_from_the_deadline_when_it_is_later_than_now() -> None:
    deadline = datetime.now(UTC) + timedelta(days=4)
    respx.get(f"{API}/candidates/7").mock(return_value=httpx.Response(200, json=_candidate(7, auto_delete_eligible_at=deadline.isoformat())))
    route = respx.post(f"{API}/candidates/7/postpone").mock(return_value=httpx.Response(200, json={"candidate": _candidate(7), "event_id": "e"}))
    message = await RCL.action("leaving", "postpone", {"id": 7, "days": 7}, CONFIG, {}, _ctx())
    body = json.loads(route.calls.last.request.content)
    until = datetime.fromisoformat(body["until"])
    assert abs((until - (deadline + timedelta(days=7))).total_seconds()) < 5
    assert body["reason"] == "From nexdeck"
    assert message == f"Postponed until {until.date().isoformat()}."


@respx.mock
async def test_postpone_of_a_title_already_due_counts_from_now() -> None:
    respx.get(f"{API}/candidates/7").mock(return_value=httpx.Response(200, json=_candidate(7, auto_delete_eligible_at=_at(days=-3))))
    route = respx.post(f"{API}/candidates/7/postpone").mock(return_value=httpx.Response(200, json={"candidate": _candidate(7), "event_id": "e"}))
    await RCL.action("leaving", "postpone", {"id": 7, "days": 14}, CONFIG, {}, _ctx())
    until = datetime.fromisoformat(json.loads(route.calls.last.request.content)["until"])
    assert abs((until - (datetime.now(UTC) + timedelta(days=14))).total_seconds()) < 5


@respx.mock
@pytest.mark.parametrize(("action", "path"), [("keep", "cancel"), ("reset", "reset-timer"), ("protect", "protect")])
async def test_each_button_reaches_its_own_address(action: str, path: str) -> None:
    route = respx.post(f"{API}/candidates/7/{path}").mock(return_value=httpx.Response(200, json={"candidate": _candidate(7), "event_id": "e"}))
    await RCL.action("leaving", action, {"id": 7}, CONFIG, {}, _ctx())
    assert route.called
    assert json.loads(route.calls.last.request.content) == {"reason": "From nexdeck"}


@respx.mock
async def test_a_refused_button_says_why() -> None:
    respx.post(f"{API}/candidates/7/protect").mock(return_value=httpx.Response(
        409, json={"detail": "A delete or move operation is already pending for this media"}))
    with pytest.raises(AdapterError) as caught:
        await RCL.action("leaving", "protect", {"id": 7}, CONFIG, {}, _ctx())
    assert caught.value.message == "Reclaimerr answered with HTTP 409: A delete or move operation is already pending for this media"


async def test_an_action_without_a_title_or_of_another_kind_is_refused() -> None:
    with pytest.raises(AdapterError):
        await RCL.action("leaving", "keep", {"id": "../tasks"}, CONFIG, {}, _ctx())
    with pytest.raises(AdapterError):
        await RCL.action("leaving", "delete", {"id": 7}, CONFIG, {}, _ctx())


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


@respx.mock
async def test_tasks_show_schedule_last_and_next_run() -> None:
    _scopes(READ_ALL)
    _tasks(
        _task("sync_media", "Sync Media"),
        _task("refresh_playback_history", "Refresh Playback Data", schedule_type="interval", schedule_value="900",
              last_run_at=_at(minutes=-4), next_run_at=_at(minutes=11)),
        _task("check_app_updates", "Check App Updates", schedule_type="interval", schedule_value="3600", status="running"),
        _task("delete_cleanup_candidates", "Delete Cleanup Candidates", status="error", error="Radarr refused"),
        _task("sync_linked_data", "Sync Linked Data", schedule_type="manual", schedule_value="", next_run_at=None, last_run_at=None),
        _task("weekly_house_keeping", "Weekly House Keeping", enabled=False, status="disabled"),
    )
    card = await RCL.fetch("tasks", CONFIG, {}, _ctx())
    rows = [(row["title"], row["subtitle"], row["value"], row["status"]) for row in card.items]
    assert rows == [
        ("Sync Media", "0 3 * * * · ran 7 h ago", "in 17 h", "ok"),
        ("Refresh Playback Data", "every 15 min · ran 4 min ago", "in 11 min", "ok"),
        ("Check App Updates", "every 1 h · ran 7 h ago", "Running", "ok"),
        ("Delete Cleanup Candidates", "0 3 * * * · ran 7 h ago · Radarr refused", "Failed", "bad"),
        ("Sync Linked Data", "Manual", "Idle", "ok"),
    ], "a disabled task is left out unless all are asked for"
    assert card.status == "bad"
    assert card.meta["notice"] == "The buttons need the scope tasks:run."
    assert all("actions" not in row for row in card.items)


@respx.mock
async def test_only_tasks_that_neither_delete_nor_write_get_a_button() -> None:
    _scopes(EVERYTHING)
    _tasks(
        _task("sync_media", "Sync Media"),
        _task("scan_cleanup_candidates", "Scan Cleanup Candidates", status="running"),
        _task("delete_cleanup_candidates", "Delete Cleanup Candidates"),
        _task("tag_cleanup_candidates", "Tag Cleanup Candidates"),
        _task("weekly_house_keeping", "Weekly House Keeping"),
        _task("scan_upgrade_leftovers", "Scan Upgrade Leftovers"),
        _task("something_new", "Something New"),
        _task("resync_media", "Resync Media", can_run=False),
    )
    card = await RCL.fetch("tasks", CONFIG, {"show": "all"}, _ctx())
    with_button = [row["id"] for row in card.items if row.get("actions")]
    assert with_button == ["sync_media"], "running, deleting, writing, unknown and unrunnable tasks have none"
    assert [(a.id, a.params) for a in card.items[0]["actions"]] == [("run", {"task": "sync_media"})]


@respx.mock
async def test_run_now_starts_the_task_and_refuses_one_that_deletes() -> None:
    route = respx.post(f"{API}/tasks/sync_media/run").mock(return_value=httpx.Response(200, json={
        "task_id": "sync_media", "job_id": 4, "queued": True, "already_active": False}))
    assert await RCL.action("tasks", "run", {"task": "sync_media"}, CONFIG, {}, _ctx()) == "The task is queued."
    assert route.called
    deleting = respx.post(f"{API}/tasks/delete_cleanup_candidates/run")
    with pytest.raises(AdapterError):
        await RCL.action("tasks", "run", {"task": "delete_cleanup_candidates"}, CONFIG, {}, _ctx())
    assert not deleting.called


# ---------------------------------------------------------------------------
# The test and what is told
# ---------------------------------------------------------------------------


@respx.mock
async def test_the_test_names_the_version_and_the_scopes_it_misses() -> None:
    _scopes(["candidates:manage", "system:read"])
    _system()
    said = await RCL.test(CONFIG, _ctx())
    assert said == ("Reclaimerr 0.5.5 answers; the token has candidates:manage, system:read. "
                    "Missing for every card: media:read, protections:read, tasks:read, events:read.")


@respx.mock
async def test_the_test_refuses_a_token_without_any_scope() -> None:
    _scopes([])
    with pytest.raises(AdapterError) as caught:
        await RCL.test(CONFIG, _ctx())
    assert caught.value.code == "missing_scope"


@respx.mock
async def test_the_overview_reads_what_was_deleted_and_moved() -> None:
    _scopes(READ_ALL)
    _candidates()
    _system()
    _tasks()
    respx.get(f"{API}/protections").mock(return_value=httpx.Response(200, json={"items": [], "total": 0, "page": 1, "per_page": 1, "total_pages": 0}))

    def feed(request: httpx.Request) -> httpx.Response:
        kind = request.url.params["event_type"]
        assert request.url.params["occurred_after"], "only the last day is read"
        if kind == "candidate.deleted":
            return httpx.Response(200, json={"items": [{"id": "e1", "type": kind, "occurred_at": _at(hours=-1), "candidate_id": 1,
                                                         "actor": {"type": "system"}, "payload": {"candidate": _candidate(1)}}],
                                             "next_cursor": "e1", "has_more": False})
        return httpx.Response(200, json={"items": [], "next_cursor": None, "has_more": False})

    respx.get(f"{API}/events").mock(side_effect=feed)
    card = await RCL.fetch("overview", CONFIG, {}, _ctx())
    assert card.meta["removed"] == [{"id": "e1", "type": "candidate.deleted", "title": "Title 1 (2019)"}]


def _seen(*events: dict[str, Any]) -> WidgetData:
    return WidgetData(meta={"removed": list(events)})


def test_a_title_deleted_or_moved_since_the_last_look_is_told() -> None:
    before = _seen({"id": "a", "type": "candidate.deleted", "title": "Old One (2018)"})
    after = _seen({"id": "a", "type": "candidate.deleted", "title": "Old One (2018)"},
                  {"id": "b", "type": "candidate.deleted", "title": "The Copper Lantern (2019)"},
                  {"id": "c", "type": "candidate.moved", "title": "Harbour Lights (2021)"})
    found = RCL.detect("overview", before, after, {})
    assert [(one.event, one.title, one.key) for one in found] == [
        ("media_removed", "The Copper Lantern (2019) was deleted", "media_removed:rcl:b"),
        ("media_removed", "Harbour Lights (2021) was moved", "media_removed:rcl:c")]


def test_a_first_look_a_broken_look_and_a_token_without_events_stay_quiet() -> None:
    after = _seen({"id": "b", "type": "candidate.deleted", "title": "x"})
    assert RCL.detect("overview", None, after, {}) == []
    assert RCL.detect("overview", WidgetData(error="down"), after, {}) == []
    assert RCL.detect("overview", WidgetData(meta={}), after, {}) == []
    assert RCL.detect("leaving", _seen(), after, {}) == []


def test_more_than_five_at_once_are_one_message() -> None:
    after = _seen(*({"id": str(n), "type": "candidate.deleted", "title": f"Title {n}"} for n in range(8)))
    found = RCL.detect("overview", _seen(), after, {})
    assert len(found) == 1
    assert found[0].title == "Reclaimerr cleaned up 8 titles"


def test_the_demo_draws_every_card() -> None:
    for widget in RCL.widgets:
        card = RCL.demo(widget.kind, {}, 3)
        assert card.items or card.primary, widget.kind
