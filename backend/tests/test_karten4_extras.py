"""KARTEN-4: what an own connection gets from its description beyond the connection itself: a dot and an outage like a
built-in one (check path, else test path), the version it runs, the comparison with its project on GitHub, the tile,
the update card and a lock for administrators.

Everything here runs through the places the built-in kinds use, not through ones of its own.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.adapters import get_adapter
from app.adapters.base import Context
from app.config import get_settings
from app.db import db_session
from app.models import Event, HealthCheck, Notice
from app.services import health, versions
from app.services.collector import collector

from .conftest import CSRF
from .karten3_sample import changed, example
from .test_cards_editor_api import admin  # noqa: F401 - the fixture
from .test_cards_router import BASE

API = "/api/v1/own-integrations"
#: A wiki with a check path, a version in its status and a project on GitHub.
WIKI = changed(
    example("wikijs"), short="wiki-x", check="/healthz", test="/api/v1/status", test_expects="json",
    version={"path": "/api/v1/status", "at": "release.version"}, github="requarks/wiki",
)


@pytest.fixture(autouse=True)
def _fresh() -> None:
    versions.forget()


def own(client: TestClient, text: str, *, admin_only: bool = False, **config: Any) -> int:
    made = client.post(API, json={"yaml": text}, headers=CSRF)
    assert made.status_code == 201, made.text
    body = {"kind": made.json()["kind"], "name": "Wiki", "config": {"url": BASE, "token": "k-0123456789", **config}, "admin_only": admin_only}
    connection = client.post("/api/v1/integrations", json=body, headers=CSRF)
    assert connection.status_code == 201, connection.text
    return int(connection.json()["id"])


def switch_on_update_check(client: TestClient) -> None:
    assert client.patch("/api/v1/settings", json={"update_check": True}, headers=CSRF).status_code == 200


def tile_on(client: TestClient, number: int, title: str = "Wiki") -> dict:
    board = client.post("/api/v1/boards", json={"name": f"Lab {title}"}, headers=CSRF).json()
    made = client.post(
        f"/api/v1/pages/{board['pages'][0]['id']}/widgets",
        json={"kind": "core.app", "title": title, "integration_id": number, "options": {"check": True}}, headers=CSRF,
    )
    assert made.status_code == 201, made.text
    widget = made.json()["widget"]
    collector.unschedule(widget["id"])
    put = client.put(f"/api/v1/widgets/{widget['id']}/health", json={"kind": "http", "target": ""}, headers=CSRF)
    assert put.status_code == 200, put.text
    return {**widget, "board": board}


def target_of(widget_id: int) -> str:
    with db_session() as db:
        check = db.scalar(select(HealthCheck).where(HealthCheck.widget_id == widget_id))
        return health.service_target("http", check.widget, db)


def reading_of(client: TestClient, number: int) -> dict:
    answer = client.get("/api/v1/integrations/versions")
    assert answer.status_code == 200, answer.text
    return answer.json()[str(number)]


def newest(monkeypatch: pytest.MonkeyPatch, tag: str | None, asked: list[str] | None = None) -> None:
    async def from_github(self: Any, config: dict[str, Any], ctx: Context, repo: str) -> dict[str, Any] | None:
        if asked is not None:
            asked.append(repo)
        return None if tag is None else {"tag": tag, "url": f"https://github.com/{repo}/releases/tag/{tag}", "published": 1_700_000_000, "prerelease": False}

    monkeypatch.setattr(type(get_adapter("github")), "newest_release", from_github)


# -- AC-1, EC-4: the dot, the outage, the bell, the chronicle, the attention card ------------------------------------


def test_karten4_ac1_the_dot_asks_the_check_path_underneath_the_address(admin: TestClient) -> None:  # noqa: F811
    number = own(admin, WIKI)
    assert target_of(tile_on(admin, number)["id"]) == f"{BASE}/healthz"


def test_karten4_ec4_without_a_check_path_the_dot_asks_the_test_path(admin: TestClient) -> None:  # noqa: F811
    number = own(admin, changed(WIKI, short="wiki-y", check=None))
    assert target_of(tile_on(admin, number)["id"]) == f"{BASE}/api/v1/status"


def test_karten4_ac1_a_slash_at_the_end_of_the_address_does_not_double(admin: TestClient) -> None:  # noqa: F811
    number = own(admin, WIKI, url=f"{BASE}/wiki/")
    assert target_of(tile_on(admin, number)["id"]) == f"{BASE}/wiki/healthz"


@respx.mock
async def test_karten4_ac1_ac6_an_outage_is_told_like_one_of_a_built_in_kind(admin: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    monkeypatch.setattr(get_settings(), "outage_threshold_seconds", 0)
    number = own(admin, WIKI)
    tile = tile_on(admin, number, "Wiki")
    route = respx.get(f"{BASE}/healthz").mock(return_value=httpx.Response(200))
    await health.health.run_due(force=True)
    with db_session() as db:
        check = db.scalar(select(HealthCheck).where(HealthCheck.widget_id == tile["id"]))
        assert check.last_ok is True and check.down_since is None
    assert route.called

    route.mock(return_value=httpx.Response(503))
    await health.health.run_due(force=True)
    await health.health.run_due(force=True)
    with db_session() as db:
        check = db.scalar(select(HealthCheck).where(HealthCheck.widget_id == tile["id"]))
        assert check.last_ok is False and check.down_since is not None
        assert [row.title for row in db.scalars(select(Notice))] == ["Wiki is down"], "the bell"
        assert [(row.kind, row.name) for row in db.scalars(select(Event).where(Event.kind == "outage"))] == [("outage", "Wiki")], "the chronicle"
    ctx = Context(httpx.AsyncClient(), widget_id=tile["id"], cache={})
    attention = await get_adapter("core").fetch("problems", {}, {"updates": False}, ctx)
    assert any("Wiki" in row["title"] for row in attention.items), "the attention card"
    status = await get_adapter("core").fetch("status", {}, {"boards": "all"}, Context(httpx.AsyncClient(), widget_id=tile["id"], cache={}))
    assert "Wiki" in str(status.items), "the status page"


@respx.mock
async def test_karten4_ac1_a_maintenance_window_keeps_it_quiet(admin: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    monkeypatch.setattr(get_settings(), "outage_threshold_seconds", 0)
    number = own(admin, WIKI)
    tile_on(admin, number, "Wiki")
    assert admin.post("/api/v1/maintenance", json={"integration_id": number, "minutes": 60}, headers=CSRF).status_code == 201
    respx.get(f"{BASE}/healthz").mock(return_value=httpx.Response(503))
    for _ in range(3):
        await health.health.run_due(force=True)
    with db_session() as db:
        assert list(db.scalars(select(Notice))) == [] and list(db.scalars(select(Event).where(Event.kind == "outage"))) == []


def test_karten4_ac4_the_tile_follows_the_address_and_the_logo_of_the_connection(admin: TestClient) -> None:  # noqa: F811
    number = own(admin, WIKI)
    tile = tile_on(admin, number)
    listed = {row["id"]: row for row in admin.get("/api/v1/integrations").json()}
    assert listed[number]["icon"] == "wikijs", "the form of the tile takes the logo from here"
    board = admin.get(f"/api/v1/boards/{tile['board']['slug']}").json()
    [shown] = [one for page in board["pages"] for one in page["widgets"] if one["id"] == tile["id"]]
    assert shown["service_link"] == BASE, "the tile leads to the service"


# -- AC-2, EC-1: the version ---------------------------------------------------------------------------------------


@respx.mock
def test_karten4_ac2_the_update_card_shows_the_version_the_description_points_at(admin: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    switch_on_update_check(admin)
    newest(monkeypatch, "v2.5.300")
    respx.get(f"{BASE}/api/v1/status").mock(return_value=httpx.Response(200, json={"release": {"version": "2.5.200"}}))
    number = own(admin, WIKI)
    body = reading_of(admin, number)
    assert body["running"] == "2.5.200" and body["newest"] == "2.5.300" and body["state"] == "behind"
    assert body["upstream"] == "requarks/wiki"
    ctx = Context(collector.client, resolve_integration=collector.resolve_integration)
    card = asyncio.run(get_adapter("core").fetch("updates", {}, {"nexdeck": False}, ctx))
    assert [(row["title"], row["subtitle"], row["value"]) for row in card.items] == [("Wiki", "Runs 2.5.200", "2.5.300")]


@pytest.mark.parametrize(
    "answer",
    [httpx.Response(200, json={"release": {}}), httpx.Response(200, text="<html>login</html>"), httpx.Response(200, json={"release": {"version": True}}),
     httpx.Response(200, json={"release": {"version": "nightly"}})],
    ids=["nothing there", "no JSON", "not a version", "words"],
)
@respx.mock
def test_karten4_ec1_a_version_that_cannot_be_read_is_unknown_not_an_error(admin: TestClient, answer: httpx.Response) -> None:  # noqa: F811
    respx.get(f"{BASE}/api/v1/status").mock(return_value=answer)
    number = own(admin, WIKI)
    body = reading_of(admin, number)
    assert body["running"] is None and body["state"] == "unknown"
    assert body["unread"] is False, "the service answered: it only does not say"


@respx.mock
def test_karten4_ec1_a_service_that_does_not_answer_says_so_in_the_reading(admin: TestClient) -> None:  # noqa: F811
    respx.get(f"{BASE}/api/v1/status").mock(side_effect=httpx.ConnectError("no"))
    number = own(admin, WIKI)
    body = reading_of(admin, number)
    assert body["running"] is None and body["unread"] is True and body["problem"]


@respx.mock
def test_karten4_ac2_a_description_without_a_place_for_the_version_names_none(admin: TestClient) -> None:  # noqa: F811
    respx.get(f"{BASE}/api/v1/status").mock(return_value=httpx.Response(200, json={"release": {"version": "2.5.200"}}))
    number = own(admin, changed(WIKI, short="wiki-z", version=None, github=None, name="Wiki 3.0"))
    body = reading_of(admin, number)
    assert body["running"] is None, "the name is no version"
    assert body["upstream"] == ""


# -- AC-3, EC-2, EC-5: the project on GitHub ---------------------------------------------------------------------------


@respx.mock
def test_karten4_ec5_with_the_check_off_github_is_not_asked_and_the_version_is_shown(admin: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    asked: list[str] = []
    newest(monkeypatch, "v2.5.300", asked)
    respx.get(f"{BASE}/api/v1/status").mock(return_value=httpx.Response(200, json={"release": {"version": "2.5.200"}}))
    number = own(admin, WIKI)
    body = reading_of(admin, number)
    assert asked == [] and body["running"] == "2.5.200" and body["asked"] is False and body["newest"] is None
    switch_on_update_check(admin)
    assert reading_of(admin, number)["newest"] == "2.5.300"
    assert asked == ["requarks/wiki"]


@respx.mock
def test_karten4_ec2_a_project_without_a_release_is_no_comparison(admin: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    switch_on_update_check(admin)
    newest(monkeypatch, None)
    respx.get(f"{BASE}/api/v1/status").mock(return_value=httpx.Response(200, json={"release": {"version": "2.5.200"}}))
    number = own(admin, WIKI)
    body = reading_of(admin, number)
    assert body["running"] == "2.5.200" and body["newest"] is None and body["state"] == "unknown"
    assert body["asked"] is True and body["upstream"] == "requarks/wiki", "the list says: asked, and nothing was there"


@pytest.mark.parametrize(("written", "kept"), [("https://github.com/requarks/wiki", "requarks/wiki"), ("requarks/wiki", "requarks/wiki")])
def test_karten4_ac3_the_project_is_owner_name_or_the_address(admin: TestClient, written: str, kept: str) -> None:  # noqa: F811
    number = own(admin, changed(WIKI, github=written))
    assert versions.repo_of("custom:wiki-x") == kept
    assert number


@pytest.mark.parametrize("written", ["https://gitlab.com/a/b", "not a project", "https://github.com/", "a/b/c"])
def test_karten4_ec3_a_project_that_is_no_github_address_is_refused_when_saved(admin: TestClient, written: str) -> None:  # noqa: F811
    answer = admin.post(API, json={"yaml": changed(WIKI, github=written)}, headers=CSRF)
    assert answer.status_code == 400 and answer.json()["detail"]["code"] == "integration_invalid"
    assert [one["message"] for one in answer.json()["detail"]["problems"]] and not admin.get(API).json()


def test_karten4_ac3_a_description_saved_again_and_a_deleted_one_change_the_project_at_once(admin: TestClient) -> None:  # noqa: F811
    own(admin, WIKI)
    assert versions.repo_of("custom:wiki-x") == "requarks/wiki"
    saved = admin.put(f"{API}/wiki-x", json={"yaml": changed(WIKI, github="other/project")}, headers=CSRF)
    assert saved.status_code == 200, saved.text
    assert versions.repo_of("custom:wiki-x") == "other/project"
    assert admin.delete(f"{API}/wiki-x", headers=CSRF).status_code == 204
    assert versions.repo_of("custom:wiki-x") == ""


# -- EC-6: the lock for administrators ----------------------------------------------------------------------------------


@respx.mock
def test_karten4_ec6_a_locked_connection_stays_off_the_update_card_and_the_catalog_of_members(admin: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    from .conftest import create_user, login

    switch_on_update_check(admin)
    newest(monkeypatch, "v2.5.300")
    respx.get(f"{BASE}/api/v1/status").mock(return_value=httpx.Response(200, json={"release": {"version": "2.5.200"}}))
    number = own(admin, WIKI, admin_only=True)
    ctx = Context(collector.client, resolve_integration=collector.resolve_integration)
    card = asyncio.run(get_adapter("core").fetch("updates", {}, {"nexdeck": False}, ctx))
    assert card.items == [], "the same rule as for a locked built-in connection"
    create_user(admin, "mia", role="user")
    login(admin, "mia", "another-long-password")
    assert number not in [one["id"] for one in admin.get("/api/v1/integrations").json()]
    assert admin.get("/api/v1/integrations/versions").status_code == 403


# -- AC-5: boards and their files ----------------------------------------------------------------------------------------


def test_karten4_ac5_a_board_export_names_the_own_connection_a_template_can_use(admin: TestClient) -> None:  # noqa: F811
    number = own(admin, WIKI)
    tile = tile_on(admin, number, "Wiki")
    exported = admin.get(f"/api/v1/boards/{tile['board']['slug']}/export")
    assert exported.status_code == 200, exported.text
    assert "custom:wiki-x" in exported.text
    imported = admin.post("/api/v1/boards/import", json={"yaml_text": exported.text}, headers=CSRF)
    assert imported.status_code in (200, 201), imported.text


def test_karten4_ac5_a_file_that_names_an_own_kind_this_installation_lacks_is_refused_in_words(admin: TestClient) -> None:  # noqa: F811
    number = own(admin, WIKI)
    exported = admin.get(f"/api/v1/boards/{tile_on(admin, number, 'Wiki')['board']['slug']}/export").text
    assert admin.delete(f"{API}/wiki-x", headers=CSRF).status_code == 204
    refused = admin.post("/api/v1/boards/import", json={"yaml_text": exported}, headers=CSRF)
    assert 400 <= refused.status_code < 500, refused.text


def test_karten4_ac3_the_picker_of_the_update_card_offers_the_own_kinds_with_a_project(admin: TestClient) -> None:  # noqa: F811
    own(admin, WIKI)
    own(admin, changed(WIKI, short="wiki-none", github=None))

    def offered() -> set[str]:
        core = next(one for one in admin.get("/api/v1/adapters").json() if one["kind"] == "core")
        updates = next(one for one in core["widgets"] if one["kind"] == "core.updates")
        return {one["value"] for one in next(field for field in updates["options"] if field["name"] == "picked")["options"]}

    assert "custom:wiki-x" in offered() and "custom:wiki-none" not in offered()
    assert "sonarr" in offered()


@respx.mock
def test_karten4_the_forms_the_screens_read_are_the_ones_the_server_sends(admin: TestClient) -> None:  # noqa: F811
    """What the integrations screen relies on: ``custom`` and ``icon`` in the adapter list, ``ok message hint code`` in a red test."""
    own(admin, WIKI)
    adapter = next(one for one in admin.get("/api/v1/adapters").json() if one["kind"] == "custom:wiki-x")
    assert adapter["custom"] is True and adapter["icon"] == "wikijs" and adapter["label"] == "Wiki.js"
    respx.get(f"{BASE}/api/v1/status").mock(return_value=httpx.Response(401, json={}))
    red = admin.post("/api/v1/integrations/test", json={"kind": "custom:wiki-x", "config": {"url": BASE, "token": "k-0123456789"}}, headers=CSRF).json()
    assert set(red) == {"ok", "message", "hint", "code"} and red["ok"] is False and red["code"] == "auth_failed"
    respx.get(f"{BASE}/api/v1/status").mock(return_value=httpx.Response(200, json={}))
    green = admin.post("/api/v1/integrations/test", json={"kind": "custom:wiki-x", "config": {"url": BASE, "token": "k-0123456789"}}, headers=CSRF).json()
    assert green["ok"] is True and green["message"]
