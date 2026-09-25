"""The status page and the notices card: what they show, and whose."""

from __future__ import annotations

import time
from datetime import timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.adapters import get_adapter
from app.adapters.base import Context
from app.db import db_session
from app.models import Board, HealthCheck, Notice, Page, User, Widget, utcnow
from app.services import history

from .conftest import CSRF, create_user, setup_admin


@pytest.fixture(autouse=True)
def _no_probes(monkeypatch: pytest.MonkeyPatch) -> None:
    """⚠️ The app's own check loop runs in the test client, and a new check is
    due at once. It asks radarr.example.com for real and can write its answer
    over the state a test has just set. One run of this file went red on
    25.09.2026, six after it did not; this is the way in the code that explains it."""
    from app.services import health

    async def nothing(force: bool = False) -> None:
        return None

    monkeypatch.setattr(health.health, "run_due", nothing)


def _board(client: TestClient, name: str) -> dict:
    response = client.post("/api/v1/boards", json={"name": name}, headers=CSRF)
    assert response.status_code == 201, response.text
    return response.json()


def _card(client: TestClient, page_id: int, kind: str, **extra: object) -> int:
    response = client.post(f"/api/v1/pages/{page_id}/widgets", json={"kind": kind, **extra}, headers=CSRF)
    assert response.status_code == 201, response.text
    return response.json()["widget"]["id"]


def _tile(client: TestClient, page_id: int, title: str) -> int:
    return _card(client, page_id, "core.app", title=title, link=f"https://{title.lower()}.example.com")


def _checked(widget_id: int, ok: bool | None, error: str = "", latency: int | None = None, enabled: bool = True) -> None:
    with db_session() as db:
        check = db.scalar(select(HealthCheck).where(HealthCheck.widget_id == widget_id))
        assert check is not None, "an app tile with a link gets its check"
        check.last_ok, check.last_error, check.last_latency_ms, check.enabled = ok, error, latency, enabled


def _read(kind: str, widget_id: int, **options: object):
    ctx = Context(httpx.AsyncClient(), integration_id=None, widget_id=widget_id, cache={})
    return get_adapter("core").fetch(kind, {}, dict(options), ctx)


def _foreign_board(owner: str, title: str) -> None:
    """A board of somebody else, written straight into the database."""
    with db_session() as db:
        user = db.scalar(select(User).where(User.username == owner))
        board = Board(slug=f"{owner}-board", name=f"{owner}'s board", owner_id=user.id)
        db.add(board)
        db.flush()
        page = Page(board_id=board.id, name="Overview", slug="overview", position=0, layouts={})
        db.add(page)
        db.flush()
        widget = Widget(page_id=page.id, kind="core.app", title=title, link="https://secret.example.com", options={})
        db.add(widget)
        db.flush()
        db.add(HealthCheck(widget_id=widget.id, target=widget.link, kind="http", last_ok=False, last_error="HTTP 502"))


async def test_the_status_page_lists_this_boards_checks_down_first(client: TestClient) -> None:
    setup_admin(client)
    lab = _board(client, "Lab")
    page = lab["pages"][0]["id"]
    radarr, sonarr, nextcloud, quiet = (_tile(client, page, name) for name in ("Radarr", "Sonarr", "Nextcloud", "Quiet"))
    _checked(radarr, True, latency=12)
    _checked(sonarr, False, "ConnectError")
    _checked(nextcloud, None)
    _checked(quiet, True, latency=5, enabled=False)
    now = int(time.time())
    with db_session() as db:
        for offset, up in enumerate((1.0, 1.0, 0.0, 1.0)):
            history.record(db, radarr, {"up": up}, ts=now - 60 - offset)
    status = _card(client, page, "core.status")

    card = await _read("status", status)
    rows = [(row["title"], row["subtitle"], row["status"]) for row in card.items]
    assert rows == [("Sonarr", "ConnectError", "bad"), ("Nextcloud", "Not checked yet.", "unknown"), ("Radarr", "12 ms", "ok")]
    assert "Quiet" not in str(card.items), "a check that is switched off is not on the status page"
    radarr_row = card.items[2]
    assert radarr_row["value"] == 75 and radarr_row["unit"] == "%", "three of four answers in the last slice"
    assert len(radarr_row["bars"]) == 48 and radarr_row["bars"][-1] == 0.75
    assert card.status == "bad" and card.primary == {"label": "Down", "value": 1}

    down = await _read("status", status, only_down=True)
    assert [row["title"] for row in down.items] == ["Sonarr"]
    bare = await _read("status", status, bars="none")
    assert all("bars" not in row for row in bare.items) and bare.items[2]["value"] == 75, "no bars, the availability stays"


async def test_the_availability_is_rounded_down_never_up(client: TestClient) -> None:
    """One miss in a hundred in one of two slices is 99.5 per cent; the card must not say 100."""
    setup_admin(client)
    lab = _board(client, "Lab")
    radarr = _tile(client, lab["pages"][0]["id"], "Radarr")
    _checked(radarr, True, latency=12)
    now = int(time.time())
    with db_session() as db:
        for second in range(100):
            history.record(db, radarr, {"up": 0.0 if second == 0 else 1.0}, ts=now - 1800 - 60 - second)
        history.record(db, radarr, {"up": 1.0}, ts=now - 60)
    card = await _read("status", _card(client, lab["pages"][0]["id"], "core.status"))
    assert card.items[0]["value"] == 99


async def test_every_board_means_the_owners_boards_and_no_others(client: TestClient) -> None:
    """⚠️ The card is read once for everyone who sees it; somebody else's board must never appear."""
    setup_admin(client)
    create_user(client, "robin")
    _foreign_board("robin", "Secret")
    lab, media = _board(client, "Lab"), _board(client, "Media")
    _checked(_tile(client, lab["pages"][0]["id"], "Radarr"), True, latency=12)
    _checked(_tile(client, media["pages"][0]["id"], "Plex"), True, latency=30)
    status = _card(client, lab["pages"][0]["id"], "core.status", options={"scope": "owner"})

    mine = await _read("status", status, scope="owner")
    assert sorted(row["title"] for row in mine.items) == ["Plex · Media", "Radarr · Lab"]
    here = await _read("status", status)
    assert [row["title"] for row in here.items] == ["Radarr"]


async def test_the_status_page_of_a_card_that_is_gone_says_nothing(client: TestClient) -> None:
    setup_admin(client)
    card = await _read("status", 9999)
    assert card.items == [] and card.status == "unknown"
    empty = _board(client, "Empty")
    lonely = await _read("status", _card(client, empty["pages"][0]["id"], "core.status"))
    assert lonely.items == [] and lonely.meta["empty"]


def _notices(user_id: int) -> None:
    now = utcnow()
    with db_session() as db:
        db.add_all([
            Notice(user_id=user_id, event="outage", level="error", title="Nextcloud is down", body="3 minutes", created_at=now - timedelta(minutes=3)),
            Notice(user_id=user_id, event="update", level="warn", title="Disk almost full", created_at=now - timedelta(hours=2), read_at=now),
            Notice(user_id=user_id, event="backup", level="info", title="Backup written", link="/system/backups", created_at=now - timedelta(hours=5)),
        ])


async def test_the_notices_card_shows_the_owners_notices_newest_first(client: TestClient) -> None:
    setup_admin(client)
    robin = create_user(client, "robin")
    with db_session() as db:
        admin_id = db.scalar(select(User.id).where(User.username == "admin"))
    _notices(admin_id)
    with db_session() as db:
        db.add(Notice(user_id=robin["id"], event="outage", level="error", title="Robin's own"))
    lab = _board(client, "Lab")
    notices = _card(client, lab["pages"][0]["id"], "core.notices")

    card = await _read("notices", notices)
    assert [row["title"] for row in card.items] == ["Nextcloud is down", "Disk almost full", "Backup written"]
    assert [row["status"] for row in card.items] == ["bad", "warn", "ok"]
    assert [row["emphasis"] for row in card.items] == [True, False, True]
    assert card.items[2]["url"] == "/system/backups" and isinstance(card.items[0]["when"], float)
    assert card.primary == {"label": "Unread", "value": 2} and card.meta["headline"] is True
    assert card.status == "bad", "an unread error makes the card red"

    assert [row["title"] for row in (await _read("notices", notices, level="warn")).items] == ["Nextcloud is down", "Disk almost full"]
    assert [row["title"] for row in (await _read("notices", notices, level="error")).items] == ["Nextcloud is down"]
    assert [row["title"] for row in (await _read("notices", notices, unread_only=True)).items] == ["Nextcloud is down", "Backup written"]
    assert len((await _read("notices", notices, limit=1)).items) == 1
    with db_session() as db:
        unread = db.scalars(select(Notice).where(Notice.user_id == admin_id, Notice.read_at.is_(None))).all()
    assert len(unread) == 2, "showing a notice on a board does not mark it read"


def test_the_demos_of_both_cards_draw_rows() -> None:
    core = get_adapter("core")
    assert core.demo("status", {}, 0).items and core.demo("notices", {}, 0).items
    assert len(core.demo("status", {"only_down": True}, 0).items) == 1
