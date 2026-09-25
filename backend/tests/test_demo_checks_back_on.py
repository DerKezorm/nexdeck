"""Issue #17: app tiles edited out of the demo get their reachability check back."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.db import db_session, get_engine
from app.migrations import MIGRATIONS
from app.models import HealthCheck

from .conftest import CSRF, setup_admin


@pytest.fixture(autouse=True)
def _no_probes(monkeypatch: pytest.MonkeyPatch) -> None:
    """The app's check loop would ask these addresses for real; only the flag matters here."""
    from app.services import health

    async def nothing(force: bool = False) -> None:
        return None

    monkeypatch.setattr(health.health, "run_due", nothing)


def _tile(client: TestClient, page_id: int, title: str, link: str) -> int:
    response = client.post(f"/api/v1/pages/{page_id}/widgets", json={"kind": "core.app", "title": title, "link": link}, headers=CSRF)
    assert response.status_code == 201, response.text
    return response.json()["widget"]["id"]


def _enabled(widget_id: int) -> bool:
    with db_session() as db:
        return db.scalar(select(HealthCheck.enabled).where(HealthCheck.widget_id == widget_id))


def test_the_demo_board_still_starts_with_its_checks_off(client: TestClient) -> None:
    setup_admin(client, demo=True)
    with db_session() as db:
        flags = set(db.scalars(select(HealthCheck.enabled)))
    assert flags == {False}, "the demo's tiles point at example.com and are never probed"


def test_an_edited_demo_tile_gets_its_check_back_and_a_demo_tile_does_not(client: TestClient) -> None:
    setup_admin(client)
    board = client.post("/api/v1/boards", json={"name": "Lab"}, headers=CSRF).json()
    page = board["pages"][0]["id"]
    edited = _tile(client, page, "Sonarr", "https://sonarr.home.example.org")
    still_demo = _tile(client, page, "Radarr", "https://radarr.example.com")
    fine = _tile(client, page, "Jellyfin", "https://jellyfin.home.example.org")
    with get_engine().begin() as connection:
        # As the demo leaves them: switched off.
        connection.execute(text("UPDATE health_checks SET enabled = 0 WHERE widget_id IN (:a, :b)"), {"a": edited, "b": still_demo})

    step = {version: function for version, _description, function in MIGRATIONS}[14]
    with get_engine().begin() as connection:
        step(connection)

    assert _enabled(edited) is True, "a tile that points at a real service is checked again"
    assert _enabled(still_demo) is False, "a tile still on the demo's address stays as the demo left it"
    assert _enabled(fine) is True
