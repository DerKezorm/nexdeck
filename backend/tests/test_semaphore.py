"""Semaphore UI, against the answers of a live Semaphore 2.19.14 (11.09.2026).

One project with two Ansible templates that ran once each: a ping that went
through and a playbook that fails on purpose.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context

SEM = "http://semaphore.example.com"
CONFIG = {"url": SEM, "token": "made-up-token"}


def last_task(identifier: int, template: int, status: str, alias: str, end: str | None) -> dict[str, Any]:
    return {"id": identifier, "template_id": template, "project_id": 1, "status": status, "playbook": "", "user_id": 1,
            "created": "2026-09-11T08:49:12.125266378Z", "start": "2026-09-11T08:49:13.138880597Z", "end": end,
            "limit": "", "tpl_playbook": f"{alias}.yml", "tpl_alias": alias, "tpl_app": "ansible", "user_name": "Tester"}


def template(identifier: int, name: str, last: dict[str, Any] | None) -> dict[str, Any]:
    return {"id": identifier, "project_id": 1, "inventory_id": 1, "repository_id": 1, "environment_id": 1, "environment_ids": None,
            "name": name, "playbook": f"{name}.yml", "app": "ansible", "last_task": last, "permissions": None, "tasks": 1}


GREEN = template(1, "Nightly check", last_task(1, 1, "success", "Nightly check", "2026-09-11T08:49:14.58106541Z"))
RED = template(2, "Broken deploy", last_task(2, 2, "error", "Broken deploy", "2026-09-11T08:49:14.327859792Z"))
NEVER = template(3, "Restore test", None)
BUSY = template(4, "Offsite sync", last_task(3, 4, "running", "Offsite sync", None))


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


def _answers(templates_by_project: dict[str, list[dict[str, Any]]]) -> None:
    projects = [{"id": index + 1, "name": name, "created": "2026-09-11T08:49:11.109727Z", "type": ""} for index, name in enumerate(templates_by_project)]
    respx.get(f"{SEM}/api/projects").mock(return_value=httpx.Response(200, json=projects))
    for index, templates in enumerate(templates_by_project.values()):
        respx.get(f"{SEM}/api/project/{index + 1}/templates").mock(return_value=httpx.Response(200, json=templates))


@respx.mock
async def test_red_first_then_the_latest_and_never_run_last(ctx: Context) -> None:
    _answers({"Homelab": [GREEN, NEVER, RED], "Backups": [BUSY]})
    data = await get_adapter("semaphore").fetch("runs", CONFIG, {"limit": 10}, ctx)
    assert [(row["title"], row["subtitle"], row["status"]) for row in data.items] == [
        ("Broken deploy", "Failed · Homelab", "bad"),
        ("Offsite sync", "Running · Backups", "warn"),
        ("Nightly check", "Homelab", "ok"),
        ("Restore test", "Never run · Homelab", "unknown"),
    ]
    assert data.secondary == [{"label": "Failed", "value": 1}] and data.status == "bad"


@respx.mock
async def test_one_project_by_name(ctx: Context) -> None:
    _answers({"Homelab": [GREEN], "Backups": [BUSY]})
    data = await get_adapter("semaphore").fetch("runs", CONFIG, {"project": " homelab ", "limit": 10}, ctx)
    assert [row["title"] for row in data.items] == ["Nightly check"]
    with pytest.raises(AdapterError) as missing:
        await get_adapter("semaphore").fetch("runs", CONFIG, {"project": "Nope", "limit": 10}, ctx)
    assert missing.value.code == "no_such_project"


@respx.mock
async def test_the_summary_counts_failed_and_running_templates(ctx: Context) -> None:
    _answers({"Homelab": [GREEN, RED, NEVER], "Backups": [BUSY]})
    data = await get_adapter("semaphore").fetch("summary", CONFIG, {}, ctx)
    assert data.primary == {"label": "Failed", "value": 1}
    assert data.secondary == [{"label": "Templates", "value": 4}, {"label": "Running", "value": 1}]
    assert data.status == "bad"


@respx.mock
async def test_the_connection_test_reads_the_version_out_of_the_build_string(ctx: Context) -> None:
    """⚠️ Measured: version, commit and build time come as one string."""
    route = respx.get(f"{SEM}/api/info").mock(return_value=httpx.Response(200, json={"version": "v2.19.14-7d1872e-1788945498", "ansible": "ansible [core 2.20.9]"}))
    respx.get(f"{SEM}/api/projects").mock(return_value=httpx.Response(200, json=[{"id": 1, "name": "Homelab"}]))
    assert await get_adapter("semaphore").test(CONFIG, ctx) == "Semaphore v2.19.14 answers with 1 project."
    assert route.calls.last.request.headers["Authorization"] == "Bearer made-up-token"


@respx.mock
async def test_a_wrong_token_and_another_service(ctx: Context) -> None:
    """Measured: missing and wrong tokens both get 401 with an empty body."""
    respx.get(f"{SEM}/api/info").mock(return_value=httpx.Response(401, text=""))
    with pytest.raises(AuthFailed):
        await get_adapter("semaphore").test(CONFIG, ctx)
    respx.get(f"{SEM}/api/projects").mock(return_value=httpx.Response(200, json={"projects": []}))
    with pytest.raises(AdapterError) as wrong:
        await get_adapter("semaphore").fetch("summary", CONFIG, {}, ctx)
    assert wrong.value.code == "not_semaphore"
