"""The updates card: what it gathers, what it leaves out, and that it keeps to the update-check switch."""

from __future__ import annotations

import time
from typing import Any

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.adapters import get_adapter
from app.adapters.base import AdapterError, Context, WidgetData

from .conftest import CSRF, setup_admin


class Source:
    """A container source with a canned answer, standing in for a connection."""

    def __init__(self, kind: str, label: str, data: WidgetData | None = None, fails: str = "") -> None:
        self.kind, self.label, self.data, self.fails = kind, label, data, fails
        self.asked: list[str] = []

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        self.asked.append(widget_kind)
        if self.fails:
            raise AdapterError(self.fails, code="http_error")
        return self.data


def _ctx(sources: dict[int, Source]) -> Context:
    async def resolve(integration_id: int):
        return sources[integration_id], {}, Context(httpx.AsyncClient(), integration_id=integration_id, cache={})

    return Context(httpx.AsyncClient(), integration_id=None, widget_id=1, cache={}, resolve_integration=resolve)


WUD = WidgetData(items=[
    {"title": "immich-server", "subtitle": "Major · ghcr.io/immich-app/immich-server", "status": "warn", "value": "1.140.1 → 2.0.0",
     "actions": [{"id": "update"}]},
    {"title": "old-thing", "subtitle": "Not checked · registry said no", "status": "unknown"},
])
CUP = WidgetData(items=[{"title": "ghcr.io/home-assistant/home-assistant", "subtitle": "Minor", "status": "ok",
                         "value": "2026.9.1 → 2026.10.0", "url": "https://github.com/home-assistant/core"}])


@pytest.fixture
def nexdeck_quiet(monkeypatch: pytest.MonkeyPatch) -> None:
    """No row of nexdeck's own unless a test asks for one."""
    from app.routers import system

    monkeypatch.setattr(system, "update_check_on", lambda db: False)
    monkeypatch.setattr(system, "_update_cache", {})


async def test_container_sources_come_along_without_buttons_and_unchecked_rows(client: TestClient, nexdeck_quiet: None) -> None:
    setup_admin(client)
    sources = {1: Source("wud", "What's Up Docker", WUD), 2: Source("cup", "Cup", CUP)}
    card = await get_adapter("core").fetch("updates", {}, {"sources": ["1", "2"]}, _ctx(sources))
    assert card.items == [
        {"title": "immich-server", "subtitle": "Major · ghcr.io/immich-app/immich-server · What's Up Docker", "status": "warn", "value": "1.140.1 → 2.0.0"},
        {"title": "ghcr.io/home-assistant/home-assistant", "subtitle": "Minor · Cup", "status": "ok", "value": "2026.9.1 → 2026.10.0",
         "url": "https://github.com/home-assistant/core"},
    ]
    assert card.status == "warn" and not card.meta["notice"]
    assert sources[1].asked == ["updates"] and sources[2].asked == ["updates"]


async def test_watchtower_has_a_row_only_when_its_last_run_failed(client: TestClient, nexdeck_quiet: None) -> None:
    setup_admin(client)
    failed = Source("watchtower", "Watchtower", WidgetData(metrics={"updated": 2.0, "failed": 1.0}))
    fine = Source("watchtower", "Watchtower", WidgetData(metrics={"updated": 2.0, "failed": 0.0}))
    card = await get_adapter("core").fetch("updates", {}, {"sources": ["1"]}, _ctx({1: failed}))
    assert [(row["title"], row["status"], row["value"]) for row in card.items] == [("Watchtower", "bad", "1")] and card.status == "bad"
    quiet = await get_adapter("core").fetch("updates", {}, {"sources": ["1"]}, _ctx({1: fine}))
    assert quiet.items == [] and quiet.status == "ok"


async def test_a_source_that_fails_is_a_line_and_the_others_still_speak(client: TestClient, nexdeck_quiet: None) -> None:
    setup_admin(client)
    sources = {1: Source("cup", "Cup", fails="Cup answered with HTTP 500."), 2: Source("wud", "What's Up Docker", WUD)}
    card = await get_adapter("core").fetch("updates", {}, {"sources": ["1", "2"]}, _ctx(sources))
    assert [row["title"] for row in card.items] == ["immich-server"]
    assert card.meta["notice"] == "Cup answered with HTTP 500." and card.status == "warn" and card.error is None
    alone = await get_adapter("core").fetch("updates", {}, {"sources": ["1"]}, _ctx(sources))
    assert alone.items == [] and alone.error == "Cup answered with HTTP 500.", "with nothing else to show, the failure is the card's"


@respx.mock
async def test_a_github_release_of_this_week_stands_out(client: TestClient, nexdeck_quiet: None) -> None:
    setup_admin(client)
    fresh = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 2 * 86400))
    respx.get("https://api.github.com/repos/jellyfin/jellyfin/releases/latest").mock(return_value=httpx.Response(200, json={
        "tag_name": "v10.11.11", "html_url": "https://github.com/jellyfin/jellyfin/releases/tag/v10.11.11", "published_at": fresh}))
    respx.get("https://api.github.com/repos/immich-app/immich/releases/latest").mock(return_value=httpx.Response(200, json={
        "tag_name": "v2.0.0", "html_url": "https://github.com/immich-app/immich/releases/tag/v2.0.0", "published_at": "2026-01-02T10:00:00Z"}))
    respx.get("https://api.github.com/repos/example/none/releases/latest").mock(return_value=httpx.Response(404))
    card = await get_adapter("core").fetch("updates", {}, {"repos": "jellyfin/jellyfin\nimmich-app/immich\nexample/none\nnot-a-repo"}, _ctx({}))
    rows = {row["title"]: row for row in card.items}
    assert set(rows) == {"jellyfin/jellyfin", "immich-app/immich"}, "a project without a release has no row"
    assert rows["jellyfin/jellyfin"]["emphasis"] is True and rows["immich-app/immich"]["emphasis"] is False
    assert rows["jellyfin/jellyfin"]["value"] == "v10.11.11" and rows["jellyfin/jellyfin"]["subtitle"] == "Newest release"
    assert card.meta["notice"] == "not-a-repo is not owner/name."


async def test_nexdeck_is_asked_about_only_with_the_switch_on(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """⚠️ The update check is the operator's to allow. The card must not ask GitHub past the switch."""
    from app import __version__
    from app.routers import system

    setup_admin(client)
    asked: list[bool] = []

    async def latest(force: bool = False) -> str:
        asked.append(True)
        return "99.0.0"

    monkeypatch.setattr(system, "latest_version", latest)
    monkeypatch.setattr(system, "_update_cache", {"version": "98.0.0"})
    core = get_adapter("core")

    monkeypatch.setattr(system, "update_check_on", lambda db: False)
    off = await core.fetch("updates", {}, {}, _ctx({}))
    assert asked == [], "with the switch off, nothing goes out"
    assert off.items[0]["value"] == f"{__version__} → 98.0.0", "what a check by hand found still shows"

    monkeypatch.setattr(system, "update_check_on", lambda db: True)
    on = await core.fetch("updates", {}, {}, _ctx({}))
    assert asked == [True] and on.items[0]["value"] == f"{__version__} → 99.0.0" and on.items[0]["status"] == "warn"

    monkeypatch.setattr(system, "_update_cache", {"version": __version__})
    monkeypatch.setattr(system, "update_check_on", lambda db: False)
    assert (await core.fetch("updates", {}, {}, _ctx({}))).items == [], "the version running is no update"


def test_versions_compare_as_numbers() -> None:
    from app.adapters.core import is_newer

    assert is_newer("0.20.0", "0.19.3") and is_newer("v0.19.10", "0.19.9")
    assert not is_newer("0.19.3", "0.19.3") and not is_newer("0.9.0", "0.19.3")


async def test_a_card_that_asks_for_nothing_says_so(client: TestClient) -> None:
    setup_admin(client)
    with pytest.raises(AdapterError) as nothing:
        await get_adapter("core").fetch("updates", {}, {"nexdeck": False}, _ctx({}))
    assert nothing.value.code == "missing_sources"


def test_the_card_can_be_put_on_a_board(client: TestClient) -> None:
    # Asking for nothing on purpose: the collector reads a new card at once, and nothing may go out from a test.
    setup_admin(client)
    board = client.post("/api/v1/boards", json={"name": "Lab"}, headers=CSRF).json()
    created = client.post(f"/api/v1/pages/{board['pages'][0]['id']}/widgets", json={"kind": "core.updates", "options": {"nexdeck": False}}, headers=CSRF)
    assert created.status_code == 201, created.text
    assert get_adapter("core").demo("updates", {}, 0).items
