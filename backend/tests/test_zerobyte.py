"""Zerobyte, against the answers of a live Zerobyte 0.43.2 (27.10.2026)."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context, Unreachable, WidgetData
from app.adapters.zerobyte import ZerobyteAdapter

FIXTURES = Path(__file__).parent / "fixtures"
ZB = "http://zerobyte.example.com:4096"
KEY = "made-up-api-key"
# The answers carry the dates of the day they were measured, long past by now; how old a backup
# may be is tested on its own below, so the rule is off for the rest.
CONFIG = {"url": ZB, "api_key": KEY, "stale_hours": 0}
HOUR = 3600.0


def fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


BACKUPS = fixture("zerobyte_backups.json")
REPOSITORIES = fixture("zerobyte_repositories.json")
#: Two minutes after the last backup of the fixture ran.
NOW = max(one["lastBackupAt"] for one in BACKUPS if one["lastBackupAt"]) / 1000 + 120


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


def named(data: WidgetData) -> dict[str, dict[str, Any]]:
    return {row["title"]: row for row in data.items}


def test_the_schedules_failed_first_each_with_source_destination_and_the_next_run() -> None:
    data = ZerobyteAdapter._backups(ZerobyteAdapter._rows(BACKUPS, 0, NOW), 10)
    assert [(row["title"], row["status"]) for row in data.items] == [
        ("Broken paths", "bad"), ("Vanished", "bad"), ("Paused", "unknown"), ("Documents", "ok")]
    rows = named(data)
    # The failed run: the first line of restic's report, not the JSON line that ends it.
    assert rows["Broken paths"]["subtitle"] == (
        "Failed · /srcdata/docs/no-such-dir does not exist, skipping · docs-source → local-repo · next in 10 h")
    assert rows["Documents"]["subtitle"] == "docs-source → local-repo · next in 10 h"
    assert rows["Documents"]["value"] == "2 min"
    assert data.status == "bad" and data.secondary == [{"label": "Failed", "value": 2}] and data.metrics == {"failed": 2.0}


def test_the_button_names_the_schedule_by_its_short_id() -> None:
    """⚠️ Measured: ``/backups/{shortId}/run``; the number ``id`` is a 404."""
    rows = named(ZerobyteAdapter._backups(ZerobyteAdapter._rows(BACKUPS, 0, NOW), 10))
    run = rows["Documents"]["actions"][0]
    assert (run.id, run.params, run.confirm, run.label) == ("run", {"backup": "jMGTmi_j"}, True, "Run now")


def test_a_reason_is_the_first_line_that_says_something() -> None:
    from app.adapters.zerobyte import _reason

    assert _reason('{"message_type":"exit_error","code":1}') == ""
    assert _reason('{"message_type":"status"}\nunable to open the repository\n{"x":1}') == "unable to open the repository"
    assert _reason(None) == "" and len(_reason("x" * 500)) == 160


def test_a_folder_that_is_gone_is_told_by_its_volume() -> None:
    """⚠️ Measured: the schedule never gets a status, only the volume says why it cannot run."""
    row = named(ZerobyteAdapter._backups(ZerobyteAdapter._rows(BACKUPS, 0, NOW), 10))["Vanished"]
    assert row["status"] == "bad"
    assert row["subtitle"].startswith("Source unavailable · ENOENT: no such file or directory, access '/srcdata/gone'")
    assert "value" not in row


def test_a_paused_schedule_is_grey_and_can_still_be_run() -> None:
    row = named(ZerobyteAdapter._backups(ZerobyteAdapter._rows(BACKUPS, 0, NOW), 10))["Paused"]
    assert row["status"] == "unknown" and row["subtitle"].startswith("Paused · ")
    # A paused schedule has no next run to promise.
    assert "next in" not in row["subtitle"]
    assert [action.id for action in row["actions"]] == ["run"]


def test_a_backup_that_runs_now_is_not_a_verdict_and_offers_no_second_run() -> None:
    running = copy.deepcopy(BACKUPS)
    documents = next(one for one in running if one["name"] == "Documents")
    documents["lastBackupStatus"] = "in_progress"
    rows = ZerobyteAdapter._rows(running, 0, NOW)
    row = named(ZerobyteAdapter._backups(rows, 10))["Documents"]
    assert row["status"] == "unknown" and row["subtitle"].startswith("Running · ") and "actions" not in row
    # ⚠️ Measured: lastBackupAt still holds the finished backup before it.
    assert row["value"] == "2 min"
    summary = ZerobyteAdapter._summary(rows, NOW)
    assert {line["label"]: line["value"] for line in summary.secondary if line["label"] in ("Running", "Paused", "Failed")} == {
        "Failed": 2, "Running": 1, "Paused": 1}


def test_the_summary_counts_every_kind() -> None:
    data = ZerobyteAdapter._summary(ZerobyteAdapter._rows(BACKUPS, 0, NOW), NOW)
    assert data.primary == {"label": "Backups fine", "value": 1, "unit": "/ 4"}
    assert data.secondary == [{"label": "Failed", "value": 2}, {"label": "Running", "value": 0}, {"label": "Paused", "value": 1},
                              {"label": "Last backup", "value": "2 min"}]
    assert data.status == "bad" and data.metrics == {"failed": 2.0}


def test_the_repositories_with_their_state_and_size() -> None:
    data = ZerobyteAdapter._repositories(REPOSITORIES, 10, NOW)
    [row] = data.items
    assert (row["title"], row["status"], row["value"]) == ("local-repo", "ok", "1.1 GB")
    assert row["subtitle"].startswith("local · 4 snapshots")
    assert data.status == "ok" and data.metrics == {"broken": 0.0}
    broken = copy.deepcopy(REPOSITORIES)
    broken[0].update(status="error", lastError="Fatal: unable to open config file\nIs there a repository at the following location?")
    worse = ZerobyteAdapter._repositories(broken, 10, NOW)
    assert worse.items[0]["status"] == "bad" and worse.items[0]["subtitle"].startswith("Error · Fatal: unable to open config file · local")
    assert worse.status == "bad" and worse.metrics == {"broken": 1.0}
    assert ZerobyteAdapter._repositories([], 10).status == "unknown"


def test_a_repository_in_error_turns_its_schedules_red() -> None:
    broken = copy.deepcopy(BACKUPS)
    documents = next(one for one in broken if one["name"] == "Documents")
    documents["repository"].update(status="error", lastError="Fatal: wrong password or no key found")
    row = named(ZerobyteAdapter._backups(ZerobyteAdapter._rows(broken, 0, NOW), 10))["Documents"]
    assert row["status"] == "bad" and row["subtitle"].startswith("Repository error · Fatal: wrong password or no key found")


def test_a_good_backup_older_than_the_limit_turns_yellow_and_says_so() -> None:
    later = NOW + 30 * HOUR
    rows = ZerobyteAdapter._rows(BACKUPS, 26 * HOUR, later)
    listed = ZerobyteAdapter._backups(rows, 10)
    old = named(listed)["Documents"]
    assert old["status"] == "warn" and old["subtitle"] == "Too old · docs-source → local-repo" and old["stale"] is True
    # The paused schedule that went well is as old, and is not hidden behind its pause.
    assert named(listed)["Paused"]["status"] == "warn"
    summary = ZerobyteAdapter._summary(rows, later)
    assert {line["label"]: line["value"] for line in summary.secondary}["Too old"] == 2 and summary.primary["value"] == 0
    # Without a limit, or inside it, nothing is old.
    assert named(ZerobyteAdapter._backups(ZerobyteAdapter._rows(BACKUPS, 0, later), 10))["Documents"]["status"] == "ok"
    assert named(ZerobyteAdapter._backups(ZerobyteAdapter._rows(BACKUPS, 26 * HOUR, NOW), 10))["Documents"]["status"] == "ok"
    # A failed one is red and says why; it is not "too old" on top.
    assert named(listed)["Broken paths"]["status"] == "bad" and not named(listed)["Broken paths"].get("stale")


def test_a_schedule_that_became_too_old_is_told_once() -> None:
    adapter = get_adapter("zerobyte")
    fresh = ZerobyteAdapter._backups(ZerobyteAdapter._rows(BACKUPS, 26 * HOUR, NOW), 10)
    old = ZerobyteAdapter._backups(ZerobyteAdapter._rows(BACKUPS, 26 * HOUR, NOW + 30 * HOUR), 10)
    [news] = [one for one in adapter.detect("backups", fresh, old, {}) if "Documents" in one.title]
    assert news.event == "backup_stale" and news.key == "backup_stale:Documents"
    assert adapter.detect("backups", old, old, {}) == []
    assert adapter.detect("backups", None, old, {}) == []
    assert adapter.detect("summary", fresh, old, {}) == []


@respx.mock
async def test_the_cards_read_with_the_key_in_its_header(ctx: Context) -> None:
    backups = respx.get(f"{ZB}/api/v1/backups").mock(return_value=httpx.Response(200, json=BACKUPS))
    repositories = respx.get(f"{ZB}/api/v1/repositories").mock(return_value=httpx.Response(200, json=REPOSITORIES))
    adapter = get_adapter("zerobyte")
    listed = await adapter.fetch("backups", CONFIG, {"limit": 2}, ctx)
    assert backups.calls.last.request.headers["X-Api-Key"] == KEY
    assert [row["title"] for row in listed.items] == ["Broken paths", "Vanished"]
    summary = await adapter.fetch("summary", CONFIG, {}, ctx)
    assert summary.primary["unit"] == "/ 4"
    repos = await adapter.fetch("repositories", CONFIG, {}, ctx)
    assert repositories.calls.last.request.headers["X-Api-Key"] == KEY and repos.items[0]["title"] == "local-repo"


@respx.mock
async def test_the_connection_test_names_the_version(ctx: Context) -> None:
    respx.get(f"{ZB}/api/v1/backups").mock(return_value=httpx.Response(200, json=BACKUPS))
    respx.get(f"{ZB}/api/v1/system/updates").mock(return_value=httpx.Response(
        200, json={"currentVersion": "v0.43.2", "latestVersion": "v0.43.2", "hasUpdate": False, "missedReleases": []}))
    adapter = get_adapter("zerobyte")
    assert await adapter.test(CONFIG, ctx) == "Zerobyte 0.43.2 answers with 4 backups."
    assert await adapter.running_version(CONFIG, ctx) == "0.43.2"
    # The update check is not worth failing the test for.
    respx.get(f"{ZB}/api/v1/system/updates").mock(return_value=httpx.Response(500))
    assert await adapter.test({**CONFIG}, Context(httpx.AsyncClient(), integration_id=2, widget_id=1, cache={})) == "Zerobyte answers with 4 backups."


@respx.mock
async def test_a_rejected_key(ctx: Context) -> None:
    """⚠️ Measured: a wrong key and no key get the same 401."""
    respx.get(f"{ZB}/api/v1/backups").mock(return_value=httpx.Response(401, json={"message": "Invalid or expired session"}))
    with pytest.raises(AuthFailed):
        await get_adapter("zerobyte").fetch("backups", CONFIG, {}, ctx)


@respx.mock
async def test_an_unreachable_zerobyte(ctx: Context) -> None:
    respx.get(f"{ZB}/api/v1/backups").mock(side_effect=httpx.ConnectError("connection refused"))
    with pytest.raises(Unreachable):
        await get_adapter("zerobyte").fetch("backups", CONFIG, {}, ctx)


@respx.mock
async def test_something_that_is_not_zerobyte(ctx: Context) -> None:
    adapter = get_adapter("zerobyte")
    respx.get(f"{ZB}/api/v1/backups").mock(return_value=httpx.Response(200, text="<html>sign in</html>"))
    with pytest.raises(AdapterError) as html:
        await adapter.fetch("backups", CONFIG, {}, ctx)
    assert html.value.code == "not_json"
    respx.get(f"{ZB}/api/v1/backups").mock(return_value=httpx.Response(200, json={"hello": "world"}))
    with pytest.raises(AdapterError) as other:
        await adapter.fetch("backups", CONFIG, {}, Context(httpx.AsyncClient(), integration_id=3, widget_id=1, cache={}))
    assert other.value.code == "not_zerobyte"
    respx.get(f"{ZB}/api/v1/backups").mock(return_value=httpx.Response(404))
    with pytest.raises(AdapterError) as old:
        await adapter.fetch("backups", CONFIG, {}, Context(httpx.AsyncClient(), integration_id=4, widget_id=1, cache={}))
    assert old.value.code == "http_error" and "0.40" in old.value.hint


@respx.mock
async def test_running_a_backup_now(ctx: Context) -> None:
    route = respx.post(f"{ZB}/api/v1/backups/jMGTmi_j/run").mock(return_value=httpx.Response(202, json={"taskId": "t-1", "status": "started"}))
    adapter = get_adapter("zerobyte")
    assert await adapter.action("backups", "run", {"backup": "jMGTmi_j"}, CONFIG, {}, ctx) == "Zerobyte has started the backup."
    assert route.calls.last.request.headers["X-Api-Key"] == KEY
    # ⚠️ Measured: a second run while it runs is 409, and a folder that is gone is 400, both with the reason.
    route.mock(return_value=httpx.Response(409, json={"message": "Backup is already running for this schedule"}))
    with pytest.raises(AdapterError) as running:
        await adapter.action("backups", "run", {"backup": "jMGTmi_j"}, CONFIG, {}, ctx)
    assert running.value.code == "action_failed" and running.value.message == "Zerobyte could not run the backup: Backup is already running for this schedule"
    route.mock(return_value=httpx.Response(400, json={"message": "ENOENT: no such file or directory, access '/srcdata/gone'"}))
    with pytest.raises(AdapterError) as gone:
        await adapter.action("backups", "run", {"backup": "jMGTmi_j"}, CONFIG, {}, ctx)
    assert "ENOENT" in gone.value.message
    route.mock(return_value=httpx.Response(404, json={"message": "Backup schedule not found"}))
    with pytest.raises(AdapterError) as missing:
        await adapter.action("backups", "run", {"backup": "jMGTmi_j"}, CONFIG, {}, ctx)
    assert missing.value.code == "not_found"
    route.mock(return_value=httpx.Response(401, json={"message": "Invalid or expired session"}))
    with pytest.raises(AuthFailed):
        await adapter.action("backups", "run", {"backup": "jMGTmi_j"}, CONFIG, {}, ctx)


async def test_the_button_takes_only_a_name_of_a_schedule(ctx: Context) -> None:
    adapter = get_adapter("zerobyte")
    for bad in ("../volumes", "", "a/b", "x?y=1", None):
        with pytest.raises(AdapterError) as refused:
            await adapter.action("backups", "run", {"backup": bad}, CONFIG, {}, ctx)
        assert refused.value.code == "bad_param", bad
    with pytest.raises(AdapterError) as other:
        await adapter.action("backups", "forget", {"backup": "jMGTmi_j"}, CONFIG, {}, ctx)
    assert other.value.code == "no_such_action"


def test_the_key_is_a_secret_and_the_limit_is_there() -> None:
    adapter = get_adapter("zerobyte")
    assert {field.name for field in adapter.fields if field.secret} == {"api_key"}
    assert "stale_hours" in {field.name for field in adapter.fields} and adapter.beta is True


def test_every_card_has_demo_data_that_moves() -> None:
    adapter = get_adapter("zerobyte")
    for widget in adapter.widgets:
        options = {field.name: field.default for field in widget.options}
        assert adapter.demo(widget.kind, options, 0).error is None, widget.kind
    states = {tuple(row["status"] for row in adapter.demo("backups", {"limit": 10}, tick).items) for tick in range(0, 600, 15)}
    assert len(states) > 1
