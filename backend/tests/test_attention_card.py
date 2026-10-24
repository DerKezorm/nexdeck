"""The problems card grew into the attention card (roadmap M1, 24.10.2026).

It looks at every board of the board's owner, says since when a card is
yellow or red, counts the unread warnings of the bell, leaves out what is in
maintenance and names waiting updates on a quiet line that never colours it.
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.adapters import get_adapter
from app.adapters.base import Context, WidgetData
from app.adapters.core import CoreAdapter
from app.db import db_session, get_engine
from app.models import Notice, utcnow
from app.services import maintenance
from app.services.collector import collector
from app.services.state import live

from .conftest import CSRF, create_user, login, setup_admin


def _board(client: TestClient, name: str) -> dict:
    response = client.post("/api/v1/boards", json={"name": name}, headers=CSRF)
    assert response.status_code == 201, response.text
    return response.json()


def _widget(client: TestClient, page_id: int, kind: str = "core.clock", **extra: object) -> dict:
    response = client.post(f"/api/v1/pages/{page_id}/widgets", json={"kind": kind, **extra}, headers=CSRF)
    assert response.status_code == 201, response.text
    widget = response.json()["widget"]
    collector.unschedule(widget["id"])
    return widget


async def _read(card: dict, **options: object) -> WidgetData:
    ctx = Context(httpx.AsyncClient(), widget_id=card["id"], cache={})
    return await get_adapter("core").fetch("problems", {}, {"updates": False, **options}, ctx)


@pytest.fixture
def lab(client: TestClient) -> dict:
    """Two boards of the admin: the card on "Media", the trouble on "Infrastructure"."""
    setup_admin(client)
    media = _board(client, "Media")
    infra = _board(client, "Infrastructure")
    card = _widget(client, media["pages"][0]["id"], kind="core.problems", title="Attention")
    nas = _widget(client, infra["pages"][0]["id"], title="Synology")
    plex = _widget(client, media["pages"][0]["id"], title="Plex")
    return {"media": media, "infra": infra, "card": card, "nas": nas, "plex": plex}


async def test_it_finds_trouble_on_another_board_of_the_owner_and_says_where(lab: dict) -> None:
    live.set(lab["plex"]["id"], WidgetData(status="ok"))
    live.set(lab["nas"]["id"], WidgetData(status="ok"))
    live.set(lab["nas"]["id"], WidgetData(status="warn", meta={"status_reason": "Volume 1 is 91 % full"}))

    data = await _read(lab["card"])

    [row] = data.items
    assert data.status == "warn"
    assert row["title"] == "Synology" and row["subtitle"] == "Volume 1 is 91 % full"
    assert row["board"] == "Infrastructure" and row["source"] == "card"
    assert row["target"] == {"board": lab["infra"]["slug"], "page": lab["infra"]["pages"][0]["slug"], "widget": lab["nas"]["id"]}
    assert abs(row["since"] - time.time()) < 5, "it turned yellow while somebody watched"
    # Only this board: the trouble on the other one is not there.
    assert (await _read(lab["card"], scope="board")).items == []


async def test_since_is_the_moment_it_turned_not_the_moment_it_was_first_seen(lab: dict) -> None:
    live.set(lab["nas"]["id"], WidgetData(status="ok"))
    # Green since an hour ago, as a card that has run all day.
    live._since[lab["nas"]["id"]] = time.time() - 3600
    live.set(lab["nas"]["id"], WidgetData(status="ok"))
    live.set(lab["nas"]["id"], WidgetData(status="warn"))

    [row] = (await _read(lab["card"])).items
    assert abs(row["since"] - time.time()) < 5


async def test_a_card_that_was_yellow_when_first_seen_has_no_since(lab: dict) -> None:
    """After a restart nobody knows since when; "just now" would be a lie."""
    live.set(lab["nas"]["id"], WidgetData(status="warn", meta={"status_reason": "Volume 1 is 91 % full"}))

    [row] = (await _read(lab["card"])).items
    assert "since" not in row


async def test_red_comes_first_then_the_newest(lab: dict, client: TestClient) -> None:
    sonarr = _widget(client, lab["media"]["pages"][0]["id"], title="Sonarr")
    for widget in (lab["nas"], lab["plex"], sonarr):
        live.set(widget["id"], WidgetData(status="ok"))
    live.set(lab["nas"]["id"], WidgetData(status="warn"))
    await asyncio.sleep(0.02)
    live.set(lab["plex"]["id"], WidgetData(status="warn"))
    await asyncio.sleep(0.02)
    live.set(sonarr["id"], WidgetData(status="unknown", error="The service rejected the API key.", meta={"code": "auth_failed"}))

    data = await _read(lab["card"])

    assert [row["title"] for row in data.items] == ["Sonarr", "Plex", "Synology"]
    assert data.status == "bad"
    assert data.items[0]["error_code"] == "auth_failed"


async def test_boards_of_somebody_else_never_show_up(lab: dict, client: TestClient) -> None:
    create_user(client, "mia", role="user")
    login(client, "mia", "another-long-password")
    hers = _board(client, "Mia")
    stranger = _widget(client, hers["pages"][0]["id"], title="Her printer")
    live.set(stranger["id"], WidgetData(status="ok"))
    live.set(stranger["id"], WidgetData(status="bad"))

    assert [row["title"] for row in (await _read(lab["card"])).items] == []


async def test_another_attention_card_is_not_listed(lab: dict, client: TestClient) -> None:
    other = _widget(client, lab["infra"]["pages"][0]["id"], kind="core.problems", title="Attention too")
    live.set(other["id"], WidgetData(status="ok"))
    live.set(other["id"], WidgetData(status="bad"))

    assert (await _read(lab["card"])).items == []


def _notice(user_id: int, level: str, title: str, *, read: bool = False) -> int:
    with db_session() as db:
        notice = Notice(user_id=user_id, event="backup_failed", level=level, title=title, body="Task Photos",
                        read_at=utcnow() if read else None)
        db.add(notice)
        db.flush()
        return notice.id


async def test_unread_warnings_of_the_owner_count_and_plain_news_does_not(lab: dict) -> None:
    owner = lab["media"]["owner_id"]
    warned = _notice(owner, "warn", "Backup failed")
    _notice(owner, "info", "Download finished")
    _notice(owner, "error", "Old and read", read=True)

    data = await _read(lab["card"])

    [row] = data.items
    assert (row["title"], row["source"], row["notice"], row["status"]) == ("Backup failed", "bell", warned, "warn")
    assert data.status == "warn"
    assert (await _read(lab["card"], bell=False)).items == []


async def test_a_failing_check_counts_from_the_moment_it_went_down(lab: dict, client: TestClient) -> None:
    from app.models import HealthCheck

    tile = _widget(client, lab["infra"]["pages"][0]["id"], kind="core.app", title="Paperless", link="http://paperless.invalid")
    down = utcnow() - timedelta(minutes=12)
    with db_session() as db:
        check = db.query(HealthCheck).filter(HealthCheck.widget_id == tile["id"]).one()
        check.last_ok, check.last_error, check.down_since = False, "ConnectError", down

    [row] = (await _read(lab["card"])).items
    assert (row["title"], row["source"], row["subtitle"]) == ("Paperless", "check", "ConnectError")
    assert abs(row["since"] - down.timestamp()) < 1


async def test_what_is_in_maintenance_is_left_out_and_named_on_a_quiet_line(lab: dict, client: TestClient) -> None:
    integration = client.post("/api/v1/integrations", json={"kind": "radarr", "name": "Movies", "config": {"url": "http://radarr:7878", "api_key": "k"}}, headers=CSRF).json()
    queue = _widget(client, lab["infra"]["pages"][0]["id"], kind="radarr.queue", integration_id=integration["id"], title="Radarr")
    live.set(queue["id"], WidgetData(status="ok"))
    live.set(queue["id"], WidgetData(status="bad", meta={"status_reason": "3 downloads hang"}))
    with db_session() as db:
        maintenance.start(db, integration_id=integration["id"], widget_id=None, ends_at=utcnow() + timedelta(hours=2), user_id=None)

    data = await _read(lab["card"])

    assert data.items == [] and data.status == "ok"
    [line] = data.meta["maintenance"]
    assert line["title"] == "Movies"


async def test_updates_are_a_quiet_line_that_never_colours_the_card(lab: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    async def behind(cls: type, ctx: Context, services: str, picked: object, show_current: bool) -> list[dict]:
        return [{"title": "Sonarr", "value": "4.0.16", "status": "warn"}]

    monkeypatch.setattr(CoreAdapter, "_services", classmethod(behind))
    ctx = Context(httpx.AsyncClient(), widget_id=lab["card"]["id"], cache={})

    data = await get_adapter("core").fetch("problems", {}, {}, ctx)
    assert data.status == "ok" and data.items == []
    assert data.meta["updates"] == [{"title": "Sonarr", "value": "4.0.16"}]

    quiet = await get_adapter("core").fetch("problems", {}, {"updates": False}, ctx)
    assert quiet.meta["updates"] == []


async def test_the_card_says_how_much_it_looked_at_and_what_a_tap_opens(lab: dict) -> None:
    data = await _read(lab["card"])
    assert data.meta["counted"]["boards"] >= 2 and data.meta["counted"]["cards"] >= 2
    assert data.meta["opens"] == "card"
    assert (await _read(lab["card"], opens="service")).meta["opens"] == "service"


def test_problems_cards_made_before_keep_their_old_answers(client: TestClient) -> None:
    from app.migrations import MIGRATIONS

    setup_admin(client)
    board = _board(client, "Lab")
    old = _widget(client, board["pages"][0]["id"], kind="core.problems")
    chosen = _widget(client, board["pages"][0]["id"], kind="core.problems")
    clock = _widget(client, board["pages"][0]["id"], kind="core.clock")
    with get_engine().begin() as connection:
        connection.execute(text("UPDATE widgets SET options = :o WHERE id = :i"), {"o": json.dumps({"scope": "all"}), "i": chosen["id"]})

    step = {version: function for version, _description, function in MIGRATIONS}[24]
    with get_engine().begin() as connection:
        step(connection)
        rows = dict(connection.execute(text("SELECT id, options FROM widgets")).all())

    assert json.loads(rows[old["id"]]) == {"scope": "board", "bell": False, "updates": False, "opens": "service"}
    assert json.loads(rows[chosen["id"]])["scope"] == "all", "a choice already made stays"
    assert "scope" not in json.loads(rows[clock["id"]])
