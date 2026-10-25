"""Which version each connection runs, against the newest release of its project."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.adapters import get_adapter
from app.adapters.base import AdapterError, Context
from app.services import versions

from .conftest import CSRF, create_user, login, setup_admin


@pytest.fixture(autouse=True)
def _fresh() -> None:
    versions.forget()


@pytest.mark.parametrize(
    ("text", "found"),
    [
        ("Sonarr 4.0.11.2680 answers.", "4.0.11.2680"),
        ("Docker 27.3.1 on linux/amd64.", "27.3.1"),
        ("Kubernetes v1.30.2+k3s1 answers, with 3 node(s).", "1.30.2"),
        ("version/2025.8.1", "2025.8.1"),
        ("v2.1.0.5_stable_2025-05-27", "2.1.0.5"),
        ("Pi-hole v6.2 answers.", "6.2"),
        ("Immich v1.132.0-rc1", "1.132.0-rc1"),
        ("Pi-hole ? answers.", None),
        ("Paperless answers with 3 documents.", None),
        ("", None),
    ],
)
def test_the_version_is_read_from_a_sentence_or_a_tag(text: str, found: str | None) -> None:
    assert versions.version_in(text) == found


@pytest.mark.parametrize(
    ("running", "newest", "state"),
    [
        ("4.0.9", "4.0.11", "behind"),
        ("4.0.11", "4.0.11", "current"),
        ("30.0.1.2", "30.0.1", "current"),
        ("30.0.1", "30.0.1.2", "behind"),
        ("2026.10.3", "2026.10.4", "behind"),
        ("1.5.0", "1.4.9", "current"),
        ("6.2-beta", "6.2", "behind"),
        ("6.2", "6.2-beta", "current"),
        ("6.3-beta", "6.2", "current"),
        (None, "1.0", "unknown"),
        ("1.0", None, "unknown"),
    ],
)
def test_versions_are_compared_by_their_numbers(running: str | None, newest: str | None, state: str) -> None:
    assert versions.compare(running, newest) == state


def test_a_jump_of_the_first_number_is_a_major_version() -> None:
    assert versions.major_jump("8.4.13", "9.0.10")
    assert not versions.major_jump("8.4.13", "8.4.14")
    assert not versions.major_jump("9.0.0", "9.0.0")
    assert not versions.major_jump("2025.12.4", "2026.1.0"), "a version named by the year turns over every January"


class _Fake:
    """A service that answers with a version, and counts how often it was asked."""

    def __init__(self, answer: str | None = "4.0.9", fail: bool = False) -> None:
        self.answer = answer
        self.fail = fail
        self.asked = 0

    async def running_version(self, config: dict[str, Any], ctx: Context) -> str | None:
        self.asked += 1
        if self.fail:
            raise AdapterError("The service did not answer.")
        return self.answer


def _resolver(service: _Fake):  # noqa: ANN202
    async def resolve(integration_id: int) -> tuple[Any, dict[str, Any], Context]:
        return service, {}, Context(None)  # type: ignore[arg-type]

    return resolve


@pytest.fixture
def release(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    newest = {"tag": "v4.0.11.2680", "url": "https://github.com/Sonarr/Sonarr/releases/tag/v4.0.11.2680", "published": 1_700_000_000, "prerelease": False}

    async def from_github(self: Any, config: dict[str, Any], ctx: Context, repo: str) -> dict[str, Any]:
        newest["asked"] = newest.get("asked", 0) + 1
        return newest

    monkeypatch.setattr(type(get_adapter("github")), "newest_release", from_github)
    return newest


def test_a_reading_is_kept_for_six_hours(release: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    service = _Fake()
    clock = [1_000_000.0]
    monkeypatch.setattr(versions.time, "time", lambda: clock[0])
    first = asyncio.run(versions.read(1, "sonarr", _resolver(service), Context(None)))  # type: ignore[arg-type]
    assert (first.running, first.newest, first.state) == ("4.0.9", "4.0.11.2680", "behind")
    clock[0] += versions.TTL - 60
    asyncio.run(versions.read(1, "sonarr", _resolver(service), Context(None)))  # type: ignore[arg-type]
    assert service.asked == 1 and release["asked"] == 1, "neither the service nor GitHub is asked again within six hours"
    clock[0] += 120
    asyncio.run(versions.read(1, "sonarr", _resolver(service), Context(None)))  # type: ignore[arg-type]
    assert service.asked == 2 and release["asked"] == 2


def test_a_failed_look_is_tried_again_sooner(release: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    service = _Fake(fail=True)
    clock = [1_000_000.0]
    monkeypatch.setattr(versions.time, "time", lambda: clock[0])
    reading = asyncio.run(versions.read(1, "sonarr", _resolver(service), Context(None)))  # type: ignore[arg-type]
    assert reading.running is None and reading.problem == "The service did not answer."
    assert reading.state == "unknown"
    assert reading.public()["unread"] is True, "not reached, rather than silent about its version"
    clock[0] += versions.RETRY + 1
    asyncio.run(versions.read(1, "sonarr", _resolver(service), Context(None)))  # type: ignore[arg-type]
    assert service.asked == 2


def test_a_service_off_github_is_read_but_not_compared(release: dict[str, Any]) -> None:
    reading = asyncio.run(versions.read(1, "plex", _resolver(_Fake("1.41.0")), Context(None)))  # type: ignore[arg-type]
    assert reading.running == "1.41.0" and reading.newest is None and reading.state == "unknown"
    assert "asked" not in release
    silent = asyncio.run(versions.read(2, "plex", _resolver(_Fake(None)), Context(None)))  # type: ignore[arg-type]
    assert silent.problem == versions.NOT_SAID and silent.public()["unread"] is False


def test_every_upstream_kind_is_a_real_adapter() -> None:
    from app.adapters import all_adapters

    kinds = {adapter.kind for adapter in all_adapters()}
    assert set(versions.UPSTREAM) <= kinds, sorted(set(versions.UPSTREAM) - kinds)
    assert all(repo.count("/") == 1 for repo in versions.UPSTREAM.values())


def _asking(client: TestClient) -> None:
    """The operator's switch under System, About: without it GitHub is never asked."""
    assert client.patch("/api/v1/settings", json={"update_check": True}, headers=CSRF).status_code == 200


def _connection(client: TestClient, kind: str, name: str, admin_only: bool = False) -> int:
    made = client.post("/api/v1/integrations", json={"kind": kind, "name": name, "config": {"url": f"http://{kind}", "api_key": "k"}, "admin_only": admin_only}, headers=CSRF)
    assert made.status_code == 201, made.text
    return made.json()["id"]


@pytest.fixture
def services(monkeypatch: pytest.MonkeyPatch, release: dict[str, Any]) -> dict[str, str]:
    """Sonarr runs 4.0.9 and Radarr the newest, whatever the projects' releases say."""
    running = {"sonarr": "4.0.9", "radarr": "4.0.11.2680"}

    async def running_version(self: Any, config: dict[str, Any], ctx: Context) -> str | None:
        return running.get(self.kind)

    for kind in running:
        monkeypatch.setattr(type(get_adapter(kind)), "running_version", running_version)
    return running


def test_the_system_page_lists_the_version_of_every_connection(client: TestClient, services: dict[str, str]) -> None:
    setup_admin(client)
    _asking(client)
    sonarr = _connection(client, "sonarr", "Series")
    radarr = _connection(client, "radarr", "Movies")
    answer = client.get("/api/v1/integrations/versions")
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert body[str(sonarr)]["running"] == "4.0.9"
    assert body[str(sonarr)]["state"] == "behind"
    assert body[str(sonarr)]["upstream"] == "Sonarr/Sonarr"
    assert body[str(radarr)]["state"] == "current"


def test_only_an_administrator_asks_every_service(client: TestClient, services: dict[str, str]) -> None:
    setup_admin(client)
    create_user(client, "member")
    login(client, "member", "another-long-password")
    assert client.get("/api/v1/integrations/versions").status_code == 403


def test_a_changed_connection_is_read_again(client: TestClient, services: dict[str, str]) -> None:
    setup_admin(client)
    sonarr = _connection(client, "sonarr", "Series")
    assert client.get("/api/v1/integrations/versions").json()[str(sonarr)]["running"] == "4.0.9"
    services["sonarr"] = "4.0.11.2680"
    assert client.get("/api/v1/integrations/versions").json()[str(sonarr)]["running"] == "4.0.9", "kept for six hours"
    client.patch(f"/api/v1/integrations/{sonarr}", json={"config": {"url": "http://sonarr-new", "api_key": "k"}}, headers=CSRF)
    assert client.get("/api/v1/integrations/versions").json()[str(sonarr)]["running"] == "4.0.11.2680"


def _card(options: dict[str, Any]) -> Any:
    from app.services.collector import collector

    core = get_adapter("core")
    ctx = Context(collector.client, resolve_integration=collector.resolve_integration)
    return asyncio.run(core.fetch("updates", {}, {"nexdeck": False, **options}, ctx))


def test_the_updates_card_names_the_services_behind(client: TestClient, services: dict[str, str]) -> None:
    setup_admin(client)
    _asking(client)
    _connection(client, "sonarr", "Series")
    _connection(client, "radarr", "Movies")
    card = _card({})
    assert [(row["title"], row["subtitle"], row["value"]) for row in card.items] == [("Series", "Runs 4.0.9", "4.0.11.2680")]
    assert card.status == "warn"

    everything = _card({"show_current": True})
    assert {row["title"]: row["status"] for row in everything.items} == {"Series": "warn", "Movies": "ok"}


def test_the_card_takes_only_the_services_picked(client: TestClient, services: dict[str, str]) -> None:
    setup_admin(client)
    _asking(client)
    _connection(client, "sonarr", "Series")
    movies = _connection(client, "radarr", "Movies")
    card = _card({"services": "pick", "picked": [str(movies)], "show_current": True})
    assert [row["title"] for row in card.items] == ["Movies"]
    with pytest.raises(AdapterError, match="Nothing is chosen"):
        _card({"services": "none", "repos": ""})


def test_a_connection_for_administrators_stays_off_a_card_nobody_admin_owns(client: TestClient, services: dict[str, str]) -> None:
    """⚠️ The card is read once for everyone who sees it. Without a board, as here, there is no administrator behind it."""
    setup_admin(client)
    _asking(client)
    _connection(client, "sonarr", "Series", admin_only=True)
    assert _card({}).items == []


def test_one_service_with_an_odd_answer_does_not_take_the_others_down(release: dict[str, Any]) -> None:
    """⚠️ Found in review: a test that reads a missing field raises KeyError, and the whole list failed."""

    class Odd(_Fake):
        async def running_version(self, config: dict[str, Any], ctx: Context) -> str | None:
            raise KeyError("version")

    services = {1: Odd(), 2: _Fake("4.0.9")}

    async def resolve(integration_id: int) -> tuple[Any, dict[str, Any], Context]:
        return services[integration_id], {}, Context(None)  # type: ignore[arg-type]

    readings = asyncio.run(versions.read_many([(1, "sonarr"), (2, "sonarr")], resolve, Context(None)))  # type: ignore[arg-type]
    assert readings[2].running == "4.0.9"
    assert readings[1].running is None and "KeyError" in readings[1].problem


def test_nothing_goes_to_github_while_the_operator_has_not_switched_it_on(client: TestClient, services: dict[str, str], release: dict[str, Any]) -> None:
    """⚠️ Which projects are asked about tells GitHub which services run here. The switch is off by default."""
    setup_admin(client)
    sonarr = _connection(client, "sonarr", "Series")
    body = client.get("/api/v1/integrations/versions").json()[str(sonarr)]
    assert body["running"] == "4.0.9", "the service's own version is read all the same"
    assert body["newest"] is None and body["asked"] is False and body["state"] == "unknown"
    assert _card({}).items == []
    assert "asked" not in release, "GitHub was never asked"
    _asking(client)
    assert client.get("/api/v1/integrations/versions").json()[str(sonarr)]["state"] == "behind"


def test_an_update_row_says_when_the_newer_release_came_out(client: TestClient, services: dict[str, str], release: dict[str, Any]) -> None:
    setup_admin(client)
    _asking(client)
    _connection(client, "sonarr", "Series")
    [row] = _card({}).items
    assert row["released"] == release["published"]


def test_a_service_that_runs_another_version_is_a_line_of_the_chronicle(client: TestClient, services: dict[str, str]) -> None:
    from sqlalchemy import select

    from app.db import db_session
    from app.models import Event

    setup_admin(client)
    sonarr = _connection(client, "sonarr", "Series")
    client.get("/api/v1/integrations/versions")
    services["sonarr"] = "4.0.11.2680"
    versions.forget_one(sonarr)
    client.get("/api/v1/integrations/versions")
    with db_session() as db:
        lines = [(line.name, line.before, line.after) for line in db.scalars(select(Event).where(Event.kind == "version"))]
    assert lines == [("Series", "4.0.9", "4.0.11.2680")]
